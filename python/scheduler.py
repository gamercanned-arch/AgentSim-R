import math
import random

import numpy as np

from python.utils import build_messages, call_server
from python.tools import execute_tool
from python.logger import log_agent, log_global, log_death
from python.config import (
    PASSIVE_TICK_SECONDS,
    STOCK_MU, STOCK_SIGMA, IMPACT_FACTOR,
    SIM_HOURS_PER_YEAR,
    CONTEXT_SIZE, CONTEXT_FILL_RATIO,
)


def run_tick(world) -> bool:
    alive_agents = [a for a in world.agents.values() if a.alive]
    if not alive_agents:
        return False

    # Event-Driven Architecture: fetch agent who is available earliest
    agent = min(alive_agents, key=lambda a: a.busy_until)

    # Advance world time to this agent's availability
    if agent.busy_until > world.sim_time:
        world.sim_time = agent.busy_until

    # Catch up on any passive hour intervals crossed
    max_iters = 0
    while world.sim_time - world.last_passive >= PASSIVE_TICK_SECONDS:
        max_iters += 1
        if max_iters > 1000:
            world.last_passive = world.sim_time
            print(f"[WARNING] Fast-forwarded passive ticks to prevent loop at {world.sim_time}")
            break

        world.last_passive += PASSIVE_TICK_SECONDS

        # stock market update (GBM then linear impact)
        gbm_return = (
            (STOCK_MU - 0.5 * STOCK_SIGMA ** 2)
            + STOCK_SIGMA * np.random.normal()
        )
        base_price = world.market_price * np.exp(gbm_return)
        impact     = 1.0 + IMPACT_FACTOR * world.net_volume_this_period
        world.market_price = max(10.0, base_price * impact)
        world.net_volume_this_period = 0

        world.price_history.append(round(world.market_price, 2))

        for a in world.agents.values():
            if not a.alive:
                continue
            _apply_passive_updates(a, world)

        log_global({
            "event":             "passive_tick",
            "sim_time":          world.sim_time,
            "market_price":      round(world.market_price, 2),
            "price_history_len": len(world.price_history),
        })

    agent_id = agent.id
    notification_snapshot = (
        "\n".join(agent.pending_notifications)
        if agent.pending_notifications
        else "No recent events."
    )

    # Build the message array (appends user message to history)
    messages = build_messages(agent_id, world, notification_snapshot, agent.failed_calls)
    
    # Call server and retrieve exact token counts processed by Jinja
    generated, prompt_tokens, generated_tokens = call_server(messages)

    # Set total tokens to current absolute context size (NOT cumulative +=)
    agent.total_prompt_tokens = prompt_tokens + generated_tokens

    if generated.startswith("[SERVER ERROR]"):
        log_agent(agent_id, {
            "event":    "server_error",
            "agent":    agent.name,
            "error":    generated,
            "sim_time": world.sim_time,
        })
        agent.failed_calls += 1
        agent.busy_until = world.sim_time + 60.0 
        
        # Pop the user message so we can retry cleanly next turn
        if agent.chat_history: 
            agent.chat_history.pop()
        return False

    agent.pending_notifications.clear()

    # Save the assistant's generation to memory so it remembers its actions/thoughts
    agent.chat_history.append({"role": "assistant", "content": generated})

    result, success, time_cost = execute_tool(generated, agent_id, world)

    # Store result to be injected into the next turn's user message
    agent.last_action_result = result
    
    # Agent is occupied for duration of action
    agent.busy_until = world.sim_time + time_cost

    # ── Handle Ignored Relationship Requests ──
    if success and agent.pending_status_requests:
        for sender_name, rel_type in list(agent.pending_status_requests.items()):
            sender = next((a for a in world.agents.values() if a.name.lower() == sender_name), None)
            if sender and sender.alive:
                sender.pending_notifications.append(
                    f"{agent.name} ignored/denied your request to change relationship status to: '{rel_type}'."
                )
        agent.pending_status_requests.clear()

    log_agent(agent_id, {
        "event":        "action",
        "agent":        agent.name,
        "location":     agent.location,
        "sim_time":     world.sim_time,
        "raw_output":   generated,
        "result":       result,
        "success":      success,
        "time_cost":    time_cost,
        "prompt_tokens": prompt_tokens,
        "total_tokens":  agent.total_prompt_tokens,
        "stats": {
            "health":       round(agent.health,    1),
            "energy":       round(agent.energy,    1),
            "happiness":    round(agent.happiness, 1),
            "stress":       round(agent.stress,    1),
            "hunger":       round(agent.hunger,    1),
            "money":        round(agent.money,     2),
            "shares_owned": agent.shares_owned,
        },
    })

    if success:
        agent.failed_calls = 0
    else:
        agent.failed_calls += 1

    # Check if ANY agent has exceeded the context window (halts simulation instantly)
    context_limit = int(CONTEXT_SIZE * CONTEXT_FILL_RATIO)
    for a in world.agents.values():
        if a.total_prompt_tokens >= context_limit:
            log_global({
                "event":        "context_limit_reached",
                "agent":        a.name,
                "total_tokens": a.total_prompt_tokens,
                "sim_time":     world.sim_time,
            })
            return True

    return False


# ── passive stat update ──────────────────────────────────────────────

def _apply_passive_updates(agent, world):

    # ── aging ──
    agent.hours_lived += 1
    if agent.hours_lived % SIM_HOURS_PER_YEAR == 0:
        agent.age += 1
        agent.pending_notifications.append(
            f"Happy birthday! You are now {agent.age} years old."
        )
        log_global({
            "event":    "birthday",
            "agent":    agent.name,
            "new_age":  agent.age,
            "sim_time": world.sim_time,
        })

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
    ) * age_factor * 0.05
    agent.health = max(0.0, min(100.0, agent.health + delta_health))

    # ── happiness ──
    eps        = 1.0
    rel_scaled = min(100.0, (agent.relationships / 5.0) * 100.0)
    happiness_target = (
        0.3 * agent.health
        + 0.3 * rel_scaled
        + 0.4 * 100.0 * math.tanh(agent.money / (agent.expenses + eps))
    )
    agent.happiness = max(0.0, min(100.0,
        agent.happiness * 0.7 + happiness_target * 0.3
    ))

    # ── stress ──
    w1, w2, w3  = 1.0, 2.0, 0.5
    alpha, beta = 0.01, 0.001
    rel_tension  = w1 * max(0.0, agent.relationships - 1) ** 2
    fin_pressure = w2 * (agent.expenses / (agent.money + 1.0))

    market_anxiety = 0.0
    if agent.shares_owned > 0 and len(world.price_history) >= 2:
        price_change = world.price_history[-1] - world.price_history[-2]
        if price_change < 0:
            position_value = agent.shares_owned * world.market_price
            market_anxiety = w3 * abs(price_change) * (
                position_value / (agent.money + 1.0)
            )

    stress_target = (rel_tension + fin_pressure + market_anxiety) / (
        1.0 + alpha * agent.happiness + beta * agent.hourly_wage
    )
    agent.stress = max(0.0, min(100.0,
        agent.stress * 0.7 + stress_target * 0.3
    ))

    # ── death check ──
    if agent.health <= 0.0:
        agent.alive = False
        log_death(agent)
        log_global({
            "event":    "agent_death",
            "agent":    agent.name,
            "sim_time": world.sim_time,
            "cause":    "health depleted",
        })