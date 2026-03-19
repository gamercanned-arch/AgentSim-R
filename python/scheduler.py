import math
import random
import numpy as np

from utils import build_messages, call_server
from tools import execute_tool
from logger import log_agent, log_global, log_death
from config import (
    PASSIVE_TICK_SECONDS,
    STOCK_MU, STOCK_SIGMA, IMPACT_FACTOR,
    SIM_HOURS_PER_YEAR,
    CONTEXT_SIZE, CONTEXT_FILL_RATIO,
)


def run_tick(world) -> bool:
    alive_agents = [a for a in world.agents.values() if a.alive]
    if not alive_agents:
        return False

    agent = min(alive_agents, key=lambda a: a.busy_until)

    if agent.busy_until > world.sim_time:
        world.sim_time = agent.busy_until

    max_iters = 0
    while world.sim_time - world.last_passive >= PASSIVE_TICK_SECONDS:
        max_iters += 1
        if max_iters > 1000:
            world.last_passive = world.sim_time
            print(f"[WARNING] Fast-forwarded passive ticks to prevent loop at {world.sim_time}")
            break

        world.last_passive += PASSIVE_TICK_SECONDS

        gbm_return = ((STOCK_MU - 0.5 * STOCK_SIGMA ** 2) + STOCK_SIGMA * np.random.normal())
        base_price = world.market_price * np.exp(gbm_return)
        impact     = 1.0 + IMPACT_FACTOR * world.net_volume_this_period
        world.market_price = max(10.0, base_price * impact)
        world.net_volume_this_period = 0

        world.price_history.append(round(world.market_price, 2))

        for a in world.agents.values():
            if not a.alive: continue
            _apply_passive_updates(a, world)

    agent_id = agent.id
    notification_snapshot = (
        "\n".join(agent.pending_notifications)
        if agent.pending_notifications else "No recent events."
    )

    messages = build_messages(agent_id, world, notification_snapshot, agent.failed_calls)
    
    generated, prompt_tokens, generated_tokens = call_server(messages)
    agent.total_prompt_tokens = prompt_tokens + generated_tokens

    if generated.startswith("[SERVER ERROR]"):
        agent.failed_calls += 1
        agent.busy_until = world.sim_time + 60.0 
        if agent.chat_history: agent.chat_history.pop()
        return False

    agent.pending_notifications.clear()
    agent.chat_history.append({"role": "assistant", "content": generated})

    result, success, time_cost = execute_tool(generated, agent_id, world)

    agent.last_action_result = result
    agent.busy_until = world.sim_time + time_cost
    
    # Track parse errors vs logic errors for the user prompt
    agent.last_parse_error = result.startswith("Parse error")

    if success:
        agent.failed_calls = 0
    else:
        agent.failed_calls += 1

    log_agent(agent_id, {
        "event":        "action",
        "agent":        agent.name,
        "location":     agent.location,
        "sim_time":     world.sim_time,
        "raw_output":   generated,
        "result":       result,
        "success":      success,
        "time_cost":    time_cost,
    })

    context_limit = int(CONTEXT_SIZE * CONTEXT_FILL_RATIO)
    for a in world.agents.values():
        if a.total_prompt_tokens >= context_limit:
            return True

    return False


def _apply_passive_updates(agent, world):
    # ── aging ──
    agent.hours_lived += 1
    if agent.hours_lived % SIM_HOURS_PER_YEAR == 0:
        agent.age += 1
        agent.pending_notifications.append(f"Happy birthday! You are now {agent.age} years old.")

    # ── energy decay ──
    agent.energy = max(0.0, agent.energy - 2.0)

    # ── hunger ──
    agent.hunger = min(100.0, agent.hunger + 5.0)

    # ── expense decay ──
    agent.expenses = agent.expenses * 0.99  

    # ── health ──
    age_factor = math.exp(0.01 * agent.age)
    energy_penalty = 0.0 if agent.energy > 10.0 else 0.5
    delta_health = (
        -(0.5 * agent.stress + 0.3 * agent.hunger + energy_penalty * 10.0)
        + 0.1 * agent.happiness
    ) * age_factor * 0.02
    agent.health = max(0.0, min(100.0, agent.health + delta_health))

    # ── happiness ──
    eps        = 1.0
    rel_scaled = min(100.0, (agent.relationships / 5.0) * 100.0)
    happiness_target = (
        0.3 * agent.health
        + 0.3 * rel_scaled
        + 0.4 * 100.0 * math.tanh(agent.money / (agent.expenses + eps))
    )
    agent.happiness = max(0.0, min(100.0, agent.happiness * 0.7 + happiness_target * 0.3))

    # ── stress (Fixed Friendship Penalty) ──
    w1, w2, w3  = 1.0, 2.0, 0.5
    alpha, beta = 0.01, 0.001
    
    # Punish extreme loneliness (<3) and extreme crowding (>10), sweet spot is 3-10
    loneliness = max(0.0, 3.0 - agent.relationships) ** 2
    crowding   = max(0.0, agent.relationships - 10.0) * 2.0
    rel_tension = w1 * (loneliness + crowding)
    
    fin_pressure = w2 * (agent.expenses / (agent.money + 1.0))

    market_anxiety = 0.0
    if agent.shares_owned > 0 and len(world.price_history) >= 2:
        price_change = world.price_history[-1] - world.price_history[-2]
        if price_change < 0:
            position_value = agent.shares_owned * world.market_price
            market_anxiety = w3 * abs(price_change) * (position_value / (agent.money + 1.0))

    stress_target = (rel_tension + fin_pressure + market_anxiety) / (
        1.0 + alpha * agent.happiness + beta * agent.hourly_wage
    )
    agent.stress = max(0.0, min(100.0, agent.stress * 0.7 + stress_target * 0.3))

    # ── death check ──
    if agent.health <= 0.0:
        agent.alive = False
        log_death(agent)