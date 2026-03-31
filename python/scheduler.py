import hashlib
import math
import random
import uuid

import numpy as np

from config import (
    BASE_STORE_INVENTORY,
    CONTEXT_FILL_RATIO,
    CONTEXT_SIZE,
    IMPACT_FACTOR,
    MAX_INVENTORY,
    MAX_NEW_TOKENS,
    PASSIVE_TICK_SECONDS,
    STOCK_MU,
    STOCK_SIGMA,
    TAX_AMOUNT,
    TAX_EXEMPT_BELOW_CASH,
)
from logger import log_global, log_io, log_turn, snapshot_agent
from tools import _kill_agent, execute_tool, parse_tool_call, try_auto_collect_loot
from utils import (
    build_messages,
    call_server,
    estimate_prompt_tokens,
    get_time_string,
    is_market_open,
    render_prompt,
)


def _ensure_agent_schema(agent) -> None:
    if not hasattr(agent, "hydration"):
        agent.hydration = 70.0
    if not hasattr(agent, "dehydration_hours"):
        agent.dehydration_hours = 0

    if not hasattr(agent, "vehicle_type"):
        agent.vehicle_type = "Scooter"
    if not hasattr(agent, "vehicle_x"):
        agent.vehicle_x = getattr(agent, "x", 0.0)
    if not hasattr(agent, "vehicle_y"):
        agent.vehicle_y = getattr(agent, "y", 0.0)
    if not hasattr(agent, "vehicle_z"):
        agent.vehicle_z = getattr(agent, "z", 0.0)

    if not hasattr(agent, "recent_scenarios") or agent.recent_scenarios is None:
        agent.recent_scenarios = {}
    if not hasattr(agent, "active_task_entities") or agent.active_task_entities is None:
        agent.active_task_entities = {}

    if not hasattr(agent, "voicemail_inbox") or agent.voicemail_inbox is None:
        agent.voicemail_inbox = []


def _sha16(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()[:16]


def _peek_notifications_for_prompt(agent, max_count: int = 12, max_chars: int = 1800) -> tuple[list[str], int]:
    """
    Return (shown_lines, remaining_count) without mutating pending_notifications.
    """
    pending = list(getattr(agent, "pending_notifications", []) or [])
    shown = []
    total = 0
    for n in pending:
        if len(shown) >= max_count:
            break
        n = str(n)
        if total + len(n) + 1 > max_chars and shown:
            break
        shown.append(n)
        total += len(n) + 1
    remaining = max(0, len(pending) - len(shown))
    return shown, remaining


def _consume_notifications(agent, count: int) -> None:
    if not hasattr(agent, "pending_notifications") or agent.pending_notifications is None:
        agent.pending_notifications = []
    if count <= 0:
        return
    del agent.pending_notifications[:count]


def _drop_ground_item(world, x: float, y: float, z: float, item_data: dict, dropper_id: int | None = None) -> None:
    if not hasattr(world, "ground_items") or world.ground_items is None:
        world.ground_items = []
    world.ground_items.append(
        {
            "id": str(uuid.uuid4()),
            "item": item_data.get("item", "Unknown"),
            "durability": item_data.get("durability", 5),
            "bought": item_data.get("bought", world.sim_time),
            "x": float(x),
            "y": float(y),
            "z": float(z),
            "dropper_id": int(dropper_id) if dropper_id is not None else -1,
            "repickup_block_until": float(world.sim_time),
        }
    )


def _process_pending_deliveries(world, current_time: float) -> None:
    deliveries = getattr(world, "pending_deliveries", None) or []
    if not deliveries:
        return

    new_deliveries = []
    for d in deliveries:
        kind = d.get("kind")
        from_id = d.get("from_id")
        to_id = d.get("to_id")
        sender = world.agents.get(from_id) if isinstance(from_id, int) else None
        target = world.agents.get(to_id) if isinstance(to_id, int) else None

        # If target missing or dead: refund to sender if possible; otherwise drop/lose.
        if not target or not target.alive:
            if kind == "money":
                amt = float(d.get("amount", 0.0))
                if sender and sender.alive:
                    sender.money += amt
                    sender.pending_notifications.append(
                        f"Queued transfer to {d.get('to_id')} cancelled (recipient unavailable). Refunded ${amt:.2f}."
                    )
            elif kind == "item":
                item = d.get("item", None)
                if sender and sender.alive and isinstance(item, dict):
                    if len(sender.inventory) < MAX_INVENTORY:
                        sender.inventory.append(item)
                        sender.pending_notifications.append(
                            "Queued item delivery cancelled (recipient unavailable). Item returned to you."
                        )
                    else:
                        _drop_ground_item(world, sender.x, sender.y, sender.z, item, dropper_id=sender.id)
                        sender.pending_notifications.append(
                            "Queued item delivery cancelled (recipient unavailable). Your inventory was full, so the item was dropped on the ground at your feet."
                        )
            continue

        # Wait until target is available (not sleeping, not mid-task, not time-busy).
        if target.is_sleeping or target.task_state != "idle" or float(target.busy_until) > float(current_time):
            new_deliveries.append(d)
            continue

        if kind == "money":
            amt = float(d.get("amount", 0.0))
            target.money += amt
            target.pending_notifications.append(f"Received queued money transfer: ${amt:.2f}.")
            if sender and sender.alive:
                sender.pending_notifications.append(f"Queued money transfer delivered to {target.name}: ${amt:.2f}.")
            continue

        if kind == "item":
            item = d.get("item", None)
            if not isinstance(item, dict):
                continue

            if len(target.inventory) >= MAX_INVENTORY:
                # Cancel delivery and return to sender
                if sender and sender.alive:
                    if len(sender.inventory) < MAX_INVENTORY:
                        sender.inventory.append(item)
                        sender.pending_notifications.append(
                            f"Queued item delivery to {target.name} failed (their inventory was full). Item returned to you."
                        )
                        target.pending_notifications.append(
                            f"A queued item delivery from {sender.name} was cancelled because your inventory was full."
                        )
                    else:
                        _drop_ground_item(world, sender.x, sender.y, sender.z, item, dropper_id=sender.id)
                        sender.pending_notifications.append(
                            f"Queued item delivery to {target.name} failed (their inventory was full). Your inventory was also full, so the item was dropped on the ground at your feet."
                        )
                        target.pending_notifications.append(
                            f"A queued item delivery from {sender.name} was cancelled because your inventory was full."
                        )
                else:
                    # Sender unavailable; drop at recipient.
                    _drop_ground_item(world, target.x, target.y, target.z, item, dropper_id=-1)
                    target.pending_notifications.append(
                        "A queued item delivery could not be returned to the sender. It was dropped on the ground near you."
                    )
                continue

            target.inventory.append(item)
            target.pending_notifications.append(
                f"Received queued item delivery: {item.get('item', 'Unknown')}."
            )
            if sender and sender.alive:
                sender.pending_notifications.append(
                    f"Queued item delivery delivered to {target.name}: {item.get('item', 'Unknown')}."
                )
            continue

        # Unknown kind; drop
    world.pending_deliveries = new_deliveries


def run_tick(world) -> bool:
    while True:
        alive_agents = [a for a in world.agents.values() if a.alive]
        if not alive_agents:
            return False

        agent = min(alive_agents, key=lambda a: (a.busy_until, a.id))
        _ensure_agent_schema(agent)

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
                _ensure_agent_schema(a)
                try_auto_collect_loot(a, world)
                _apply_passive_updates(a, world, world.last_passive)

            for a in world.agents.values():
                _ensure_agent_schema(a)
                _refresh_agent_activity(a, world.last_passive)

            # Process deliveries after passive updates potentially end sleep/tasks
            _process_pending_deliveries(world, world.last_passive)

        alive_agents = [a for a in world.agents.values() if a.alive]
        if not alive_agents:
            return False

        ready_agents = [a for a in alive_agents if a.busy_until <= world.sim_time]
        if ready_agents:
            agent = min(ready_agents, key=lambda a: (a.busy_until, a.id))
            _ensure_agent_schema(agent)
            break

    _refresh_agent_activity(agent, world.sim_time)
    try_auto_collect_loot(agent, world)

    # Process deliveries at current time too (event-driven)
    _process_pending_deliveries(world, world.sim_time)

    # Notification drip: peek first (do not mutate until context check passes)
    shown_lines, remaining_count = _peek_notifications_for_prompt(agent, max_count=12, max_chars=1800)
    notifications_text = "\n".join(shown_lines).strip()
    if remaining_count > 0:
        notifications_text = (notifications_text + "\n" if notifications_text else "") + f"(Queued notifications remaining: {remaining_count})"

    msgs = build_messages(agent.id, world, notifications_text)

    prompt_text = render_prompt(msgs)
    prompt_hash = _sha16(prompt_text)
    prompt_chars = len(prompt_text)

    estimated_tokens = estimate_prompt_tokens(msgs, prompt_text=prompt_text)
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
                "prompt_hash": prompt_hash,
                "prompt_chars": prompt_chars,
            }
        )
        return True

    # Now that context check passed, actually consume shown notifications
    _consume_notifications(agent, len(shown_lines))

    pre_state = snapshot_agent(agent)

    gen, prompt_tokens, gen_tokens = call_server(msgs, agent.id, prompt_text=prompt_text)

    try:
        log_io(agent.name, world.sim_time, msgs, gen, prompt_hash=prompt_hash, prompt_chars=prompt_chars)
    except TypeError:
        log_io(agent.name, world.sim_time, msgs, gen)

    if gen.startswith("[SERVER ERROR]"):
        raise RuntimeError(gen)

    agent.total_prompt_tokens += int(prompt_tokens)
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

    try:
        log_turn(
            agent=agent,
            sim_time=world.sim_time,
            notifications=notifications_text,
            messages=msgs,
            raw_output=gen,
            parsed_tool=parsed_tool,
            parsed_args=parsed_args,
            result=res,
            success=suc,
            cost=int(cost),
            pre_state=pre_state,
            post_state=post_state,
            prompt_hash=prompt_hash,
            prompt_chars=prompt_chars,
            notifications_shown=shown_lines,
            notifications_remaining=remaining_count,
        )
    except TypeError:
        log_turn(
            agent=agent,
            sim_time=world.sim_time,
            notifications=notifications_text,
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
    p = world.market_price
    if not isinstance(p, (int, float)) or not math.isfinite(p) or p <= 0:
        world.market_price = 100.0

    if is_market_open(world.last_passive):
        shock = np.random.normal()
        gbm_multiplier = math.exp((STOCK_MU - 0.5 * (STOCK_SIGMA ** 2)) + STOCK_SIGMA * shock)

        impact_multiplier = 1.0 + (IMPACT_FACTOR * world.net_volume_this_period)
        impact_multiplier = min(1.15, max(0.85, impact_multiplier))

        new_price = world.market_price * gbm_multiplier * impact_multiplier
        world.market_price = max(10.0, min(1000.0, round(new_price, 4)))

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
        if agent.money < TAX_EXEMPT_BELOW_CASH:
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

    if not hasattr(agent, "hydration"):
        agent.hydration = 70.0
    if not hasattr(agent, "dehydration_hours"):
        agent.dehydration_hours = 0

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
        _attempt_emergency_consume(agent, world, mode="hunger")

    agent.hydration = max(0.0, agent.hydration - (1.5 if is_sleeping_now else 4.0))
    if not is_sleeping_now and agent.hydration <= 12.0:
        _attempt_emergency_consume(agent, world, mode="thirst")

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

    if agent.hydration < 30.0 and not is_sleeping_now:
        stress_target *= 1.1
    if agent.hydration < 15.0 and not is_sleeping_now:
        stress_target *= 1.25

    stress_penalty = 1.5 if agent.money < 0 else 1.0
    agent.stress = max(0.0, min(100.0, agent.stress * 0.7 + (stress_target * stress_penalty) * 0.3))

    age_factor = math.exp(0.02 * agent.age)
    energy_penalty = 0.0 if agent.energy > 10.0 else 0.5

    dehydration_penalty = 0.0
    if agent.hydration < 20.0:
        dehydration_penalty = (20.0 - agent.hydration) * 0.2

    delta_h = (
        (-(0.5 * agent.stress + 0.3 * agent.hunger + energy_penalty * 10.0 + dehydration_penalty) + 0.1 * agent.happiness)
        * age_factor
        * 0.02
    )
    agent.health = max(0.0, min(100.0, agent.health + delta_h))

    if agent.hunger >= 100.0:
        agent.starvation_hours += 1
        agent.health -= min(32.0, 2 ** agent.starvation_hours)
    else:
        agent.starvation_hours = 0

    if agent.hydration <= 0.0:
        agent.dehydration_hours += 1
        agent.health -= min(16.0, 1.5 ** agent.dehydration_hours)
    else:
        agent.dehydration_hours = 0

    if agent.health <= 0.0:
        _kill_agent(agent, world, cause="passive health collapse")


def _attempt_emergency_consume(agent, world, mode: str = "hunger") -> None:
    from tools import ITEM_CATALOG

    prefer = set()
    if mode == "thirst":
        prefer = {"Water", "Coffee"}

    if agent.currently_holding and agent.currently_holding.get("item") in ITEM_CATALOG["food"]:
        held = agent.currently_holding
        if not prefer or held["item"] in prefer:
            fstats = ITEM_CATALOG["food"][held["item"]]
            agent.currently_holding = None
            agent.hunger = max(0.0, agent.hunger - fstats["hunger"])
            agent.hydration = min(100.0, agent.hydration + fstats.get("hydration", 0))
            agent.pending_notifications.append(f"Auto-consumed held {held['item']} due to critical {mode}.")
            return

    idx = -1
    for i, item in enumerate(agent.inventory):
        if item["item"] in ITEM_CATALOG["food"]:
            if prefer and item["item"] not in prefer:
                continue
            idx = i
            break

    if idx != -1:
        eaten = agent.inventory.pop(idx)
        fstats = ITEM_CATALOG["food"][eaten["item"]]
        agent.hunger = max(0.0, agent.hunger - fstats["hunger"])
        agent.hydration = min(100.0, agent.hydration + fstats.get("hydration", 0))
        agent.pending_notifications.append(f"Auto-consumed {eaten['item']} due to critical {mode}.")
        return

    available = [item for item in ITEM_CATALOG["food"] if world.store_inventory.get(item, 0) > 0]
    if prefer:
        available = [i for i in available if i in prefer]

    affordable = [f for f in available if agent.money >= ITEM_CATALOG["food"][f]["price"]]
    if affordable:
        chosen = min(affordable, key=lambda f: ITEM_CATALOG["food"][f]["price"])
        cost = ITEM_CATALOG["food"][chosen]["price"]
        agent.money -= cost
        agent.expenses += cost
        agent.total_expenses += cost
        fstats = ITEM_CATALOG["food"][chosen]
        agent.hunger = max(0.0, agent.hunger - fstats["hunger"])
        agent.hydration = min(100.0, agent.hydration + fstats.get("hydration", 0))
        world.store_inventory[chosen] -= 1
        agent.pending_notifications.append(f"Auto-bought emergency {chosen} (${cost:.2f}) due to critical {mode}.")
    else:
        agent.pending_notifications.append(f"Critical {mode}! Cannot afford any emergency consumables.")
