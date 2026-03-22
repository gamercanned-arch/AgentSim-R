import math
import random

import numpy as np

from config import (
    BASE_STORE_INVENTORY,
    CONTEXT_FILL_RATIO,
    CONTEXT_SIZE,
    IMPACT_FACTOR,
    MAX_NEW_TOKENS,
    PASSIVE_TICK_SECONDS,
    STOCK_MU,
    STOCK_SIGMA,
    TAX_AMOUNT,
)
from logger import log_global, log_io, log_turn, snapshot_agent
from tools import ITEM_CATALOG, _kill_agent, execute_tool, parse_tool_call, try_auto_collect_loot
from utils import build_messages, call_server, estimate_prompt_tokens, get_time_string, is_market_open


def run_tick(world) -> bool:
    while True:
        alive_agents = [a for a in world.agents.values() if a.alive]
        if not alive_agents:
            return False

        agent = min(alive_agents, key=lambda a: (a.busy_until, a.id))

        if agent.busy_until > world.sim_time:
            world.sim_time = agent.busy_until

        while world.sim_time - world.last_passive >= PASSIVE_TICK_SECONDS:
            world.last_passive += PASSIVE_TICK_SECONDS

            _process_market_queues(world)
            _update_market_price(world)
            _update_weather(world)
            _restock_if_needed(world)
            _apply_midnight_taxes(world)

            for a in list(world.agents.values()):
                if not a.alive:
                    continue
                try_auto_collect_loot(a, world)
                _apply_passive_updates(a, world, world.last_passive)

            for a in world.agents.values():
                _refresh_agent_activity(a, world.last_passive)

        alive_agents = [a for a in world.agents.values() if a.alive]
        if not alive_agents:
            return False

        ready_agents = [a for a in alive_agents if a.busy_until <= world.sim_time]
        if ready_agents:
            agent = min(ready_agents, key=lambda a: (a.busy_until, a.id))
            break

    _refresh_agent_activity(agent, world.sim_time)
    try_auto_collect_loot(agent, world)

    notifications = "\n".join(agent.pending_notifications)
    msgs = build_messages(agent.id, world, notifications)

    estimated_tokens = estimate_prompt_tokens(msgs)
    context_limit = int(CONTEXT_SIZE * CONTEXT_FILL_RATIO)
    if estimated_tokens + MAX_NEW_TOKENS >= context_limit:
        if agent.chat_history and agent.chat_history[-1].get("role") == "user":
            agent.chat_history.pop()

        log_global(
            {
                "event": "context_limit_reached",
                "agent": agent.name,
                "agent_id": agent.id,
                "sim_time": world.sim_time,
                "sim_time_str": get_time_string(world.sim_time),
                "estimated_prompt_tokens": estimated_tokens,
                "generation_reserve": MAX_NEW_TOKENS,
                "context_limit": context_limit,
            }
        )
        return True

    pre_state = snapshot_agent(agent)
    gen, prompt_tokens, gen_tokens = call_server(msgs, agent.id)

    log_io(agent.name, world.sim_time, msgs, gen)

    if gen.startswith("[SERVER ERROR]"):
        raise RuntimeError(gen)

    agent.total_prompt_tokens += int(prompt_tokens)
    agent.pending_notifications.clear()
    agent.chat_history.append({"role": "assistant", "content": gen})

    parsed_tool, parsed_args = parse_tool_call(gen)
    res, suc, cost = execute_tool(gen, agent.id, world)
    agent.last_action_result = res

    if agent.alive:
        agent.busy_until = max(world.sim_time, agent.busy_until) + max(0, int(cost))

    if suc:
        agent.fail_counter = 0
    else:
        agent.fail_counter += 1

    _refresh_agent_activity(agent, world.sim_time)
    post_state = snapshot_agent(agent)

    log_turn(
        agent=agent,
        sim_time=world.sim_time,
        notifications=notifications,
        messages=msgs,
        raw_output=gen,
        parsed_tool=parsed_tool,
        parsed_args=parsed_args,
        result=res,
        success=suc,
        cost=int(cost),
        pre_state=pre_state,
        post_state=post_state,
    )

    return False


def _refresh_agent_activity(agent, current_time: float) -> None:
    if not agent.alive:
        agent.current_activity = "dead"
        return

    if agent.is_sleeping and current_time >= agent.busy_until:
        agent.is_sleeping = False

    if (
        not agent.is_sleeping
        and agent.task_state == "idle"
        and agent.busy_until <= current_time
        and agent.current_activity != "dead"
    ):
        agent.current_activity = "idle"


def _process_market_queues(world) -> None:
    if not is_market_open(world.last_passive):
        return

    for agent in world.agents.values():
        if not agent.alive or not agent.pending_market_orders:
            continue

        for order in list(agent.pending_market_orders):
            shares = int(order.get("shares", 0))
            if shares <= 0:
                continue

            if order["type"] == "buy":
                cost = world.market_price * shares
                if agent.money >= cost:
                    old_cost_basis = agent.last_known_price * agent.shares_owned
                    agent.money -= cost
                    agent.shares_owned += shares
                    agent.last_known_price = (old_cost_basis + cost) / agent.shares_owned
                    world.net_volume_this_period += shares
                    agent.pending_notifications.append(
                        f"MARKET: Queued buy executed at ${world.market_price:.2f} for {shares} share(s)."
                    )
                else:
                    agent.pending_notifications.append("MARKET: Queued buy failed. Insufficient funds.")

            elif order["type"] == "sell":
                if agent.shares_owned >= shares:
                    proceeds = world.market_price * shares
                    agent.money += proceeds
                    agent.shares_owned -= shares
                    if agent.shares_owned == 0:
                        agent.last_known_price = 0.0
                    world.net_volume_this_period -= shares
                    agent.pending_notifications.append(
                        f"MARKET: Queued sell executed at ${world.market_price:.2f} for {shares} share(s)."
                    )
                else:
                    agent.pending_notifications.append("MARKET: Queued sell failed. Insufficient shares.")

        agent.pending_market_orders.clear()


def _update_market_price(world) -> None:
    if is_market_open(world.last_passive):
        shock = np.random.normal()
        gbm_multiplier = math.exp((STOCK_MU - 0.5 * (STOCK_SIGMA ** 2)) + STOCK_SIGMA * shock)

        impact_multiplier = 1.0 + (IMPACT_FACTOR * world.net_volume_this_period)
        impact_multiplier = min(1.15, max(0.85, impact_multiplier))

        new_price = world.market_price * gbm_multiplier * impact_multiplier
        world.market_price = max(10.0, round(new_price, 4))

    world.price_history.append(round(world.market_price, 2))
    if len(world.price_history) > 168:
        world.price_history.pop(0)

    world.net_volume_this_period = 0


def _update_weather(world) -> None:
    old_weather = world.weather
    if random.random() < 0.05:
        world.weather = random.choice(["Sunny", "Rain", "Snow", "Cloudy"])

    if world.weather != old_weather and world.weather in ["Rain", "Snow"]:
        for agent in world.agents.values():
            if not agent.alive:
                continue
            loc = _safe_current_location(agent)
            if not loc or not loc.has_roof:
                agent.pending_notifications.append(
                    f"It started to {world.weather.lower()}. {world.weather} falls onto your skin."
                )


def _restock_if_needed(world) -> None:
    if world.sim_time - world.last_restock_time >= (7 * 24 * 3600):
        world.store_inventory = dict(BASE_STORE_INVENTORY)
        world.last_restock_time = world.sim_time
        world.global_news.append("Village stores have been restocked for the week.")
        world.global_news = world.global_news[-20:]


def _apply_midnight_taxes(world) -> None:
    hour = (int(world.last_passive) // 3600) % 24
    if hour != 0:
        return

    for agent in world.agents.values():
        if not agent.alive:
            continue
        agent.money -= TAX_AMOUNT
        agent.expenses += TAX_AMOUNT
        agent.total_expenses += TAX_AMOUNT
        agent.pending_notifications.append(f"Tax deducted: ${TAX_AMOUNT:.2f}")


def _safe_current_location(agent):
    from locations import get_current_location_def

    return get_current_location_def(agent.x, agent.y, agent.z)


def _apply_passive_updates(agent, world, current_time: float) -> None:
    if not agent.alive:
        return

    is_sleeping_now = agent.is_sleeping and agent.busy_until > current_time

    agent.hours_lived += 1

    if not is_sleeping_now:
        agent.awake_hours += 1

    agent.expenses *= 0.99
    agent.social_fulfillment = max(0.0, agent.social_fulfillment - 1.0)
    agent.caffeine_level = max(0, agent.caffeine_level - 1)

    for key, until in list(agent.social_cooldowns.items()):
        if until <= current_time:
            del agent.social_cooldowns[key]

    if not is_sleeping_now and agent.hunger >= 90.0:
        _attempt_emergency_food(agent, world)

    hunger_gain = 0.5 if is_sleeping_now else 5.0
    agent.hunger = min(100.0, agent.hunger + hunger_gain)

    if not is_sleeping_now:
        agent.energy = max(0.0, agent.energy - 2.0)

    eps = 1.0
    rel_scaled = min(100.0, (agent.relationships / 5.0) * 100.0)

    happiness_target = (
        0.3 * agent.health
        + 0.3 * rel_scaled
        + 0.4 * 100.0 * math.tanh(agent.money / (agent.expenses + eps))
    )
    agent.happiness = max(0.0, min(100.0, agent.happiness * 0.7 + happiness_target * 0.3))

    w1, w2, w3 = 1.0, 2.0, 0.5
    alpha, beta = 0.01, 0.001

    loneliness = max(0.0, 3.0 - agent.relationships) ** 2
    crowding = max(0.0, agent.relationships - 10.0) * 2.0
    rel_tension = w1 * (loneliness + crowding)

    money_floor = max(0.0, agent.money)
    fin_pressure = w2 * (agent.expenses / (money_floor + 1.0))

    market_anxiety = 0.0
    if agent.shares_owned > 0 and len(world.price_history) >= 2:
        price_change = world.price_history[-1] - world.price_history[-2]
        if price_change < 0:
            position_value = agent.shares_owned * world.market_price
            market_anxiety = w3 * abs(price_change) * (position_value / (money_floor + 1.0))

    stress_target = (rel_tension + fin_pressure + market_anxiety) / (
        1.0 + alpha * agent.happiness + beta * agent.hourly_wage
    )
    stress_penalty = 1.5 if agent.money < 0 else 1.0
    agent.stress = max(0.0, min(100.0, agent.stress * 0.7 + (stress_target * stress_penalty) * 0.3))

    age_factor = math.exp(0.02 * agent.age)
    energy_penalty = 0.0 if agent.energy > 10.0 else 0.5

    delta_h = (
        (-(0.5 * agent.stress + 0.3 * agent.hunger + energy_penalty * 10.0) + 0.1 * agent.happiness)
        * age_factor
        * 0.02
    )
    agent.health = max(0.0, min(100.0, agent.health + delta_h))

    if agent.hunger >= 100.0:
        agent.starvation_hours += 1
        agent.health -= min(32.0, 2 ** agent.starvation_hours)
    else:
        agent.starvation_hours = 0

    if agent.health <= 0.0:
        _kill_agent(agent, world, cause="passive health collapse")


def _attempt_emergency_food(agent, world) -> None:
    if agent.currently_holding and agent.currently_holding.get("item") in ITEM_CATALOG["food"]:
        held_food = agent.currently_holding
        fstats = ITEM_CATALOG["food"][held_food["item"]]
        agent.currently_holding = None
        agent.hunger = max(0.0, agent.hunger - fstats["hunger"])
        agent.pending_notifications.append(f"Auto-consumed held {held_food['item']} due to extreme hunger.")
        return

    food_idx = next(
        (i for i, item in enumerate(agent.inventory) if item["item"] in ITEM_CATALOG["food"]),
        -1,
    )

    if food_idx != -1:
        eaten = agent.inventory.pop(food_idx)
        fstats = ITEM_CATALOG["food"][eaten["item"]]
        agent.hunger = max(0.0, agent.hunger - fstats["hunger"])
        agent.pending_notifications.append(f"Auto-consumed {eaten['item']} due to extreme hunger.")
        return

    available_foods = [item for item in ITEM_CATALOG["food"] if world.store_inventory.get(item, 0) > 0]
    affordable = [f for f in available_foods if agent.money >= ITEM_CATALOG["food"][f]["price"]]

    if affordable:
        chosen_food = min(affordable, key=lambda f: ITEM_CATALOG["food"][f]["price"])
        cost = ITEM_CATALOG["food"][chosen_food]["price"]
        hunger_gain = ITEM_CATALOG["food"][chosen_food]["hunger"]

        agent.money -= cost
        agent.expenses += cost
        agent.total_expenses += cost
        agent.hunger = max(0.0, agent.hunger - hunger_gain)
        world.store_inventory[chosen_food] -= 1
        agent.pending_notifications.append(
            f"Auto-bought emergency {chosen_food} (${cost:.2f}) due to starvation."
        )
    elif agent.money < 10:
        agent.pending_notifications.append("Starving! Cannot afford any emergency food.")
    else:
        agent.pending_notifications.append("Starving! The village stores are completely out of food.")