import math
import random
import numpy as np

from utils import build_messages, call_server, is_market_open
from tools import execute_tool, ITEM_CATALOG
from locations import get_current_location_def
from logger import log_agent, log_global, log_death, log_io
from config import PASSIVE_TICK_SECONDS, TAX_AMOUNT
from sim import BASE_STORE_INVENTORY

def run_tick(world) -> bool:
    alive_agents = [a for a in world.agents.values() if a.alive]
    if not alive_agents: return False

    agent = min(alive_agents, key=lambda a: a.busy_until)
    if agent.busy_until > world.sim_time: world.sim_time = agent.busy_until

    while world.sim_time - world.last_passive >= PASSIVE_TICK_SECONDS:
        world.last_passive += PASSIVE_TICK_SECONDS
        
        _process_market_queues(world)
        
        # Weather Processing
        old_weather = world.weather
        if random.random() < 0.05: 
            world.weather = random.choice(["Sunny", "Rain", "Snow", "Cloudy"])
        
        if world.weather != old_weather and world.weather in ["Rain", "Snow"]:
            for a in world.agents.values():
                if not a.alive: continue
                loc = get_current_location_def(a.x, a.y, a.z)
                if not loc or not loc.has_roof:
                    a.pending_notifications.append(f"It started to {world.weather.lower()}. {world.weather} falls onto your skin.")
                    
        # Restocking Logic (Every 7 Days)
        if world.sim_time - world.last_restock_time >= (7 * 24 * 3600):
            world.store_inventory = dict(BASE_STORE_INVENTORY)
            world.last_restock_time = world.sim_time
            world.global_news.append("Village stores have been restocked for the week.")
        
        hour = (int(world.last_passive // 60) // 60) % 24
        if hour == 0:
            for a in world.agents.values(): 
                a.money -= TAX_AMOUNT
                a.pending_notifications.append(f"Tax deducted: ${TAX_AMOUNT}")

        for a in world.agents.values():
            if not a.alive: continue
            _apply_passive_updates(a, world)

    msgs = build_messages(agent.id, world, "\n".join(agent.pending_notifications), agent.failed_calls)
    gen, p_tok, g_tok = call_server(msgs, agent.id)
    log_io(agent.name, world.sim_time, msgs, gen)

    if gen.startswith("[SERVER ERROR]"): raise RuntimeError(gen)

    agent.pending_notifications.clear()
    agent.chat_history.append({"role": "assistant", "content": gen})

    res, suc, cost = execute_tool(gen, agent.id, world)
    agent.last_action_result = res
    
    if agent.task_state == "idle": agent.busy_until = world.sim_time + cost
    if not suc: agent.fail_counter += 1

    log_agent(agent.id, {"sim_time": world.sim_time, "result": res})
    return False

def _process_market_queues(world):
    if not is_market_open(world.last_passive): return
    for a in world.agents.values():
        if not a.alive or not a.pending_market_orders: continue
        for order in list(a.pending_market_orders):
            shares = order["shares"]
            if order["type"] == "buy":
                cost = world.market_price * shares
                if a.money >= cost:
                    a.money -= cost
                    a.shares_owned += shares
                    a.pending_notifications.append(f"MARKET: Queued buy executed at ${world.market_price:.2f}.")
                    world.net_volume_this_period += shares
                else: a.pending_notifications.append("MARKET: Queued buy failed. Insufficient funds.")
            elif order["type"] == "sell":
                if a.shares_owned >= shares:
                    proceeds = world.market_price * shares
                    a.money += proceeds
                    a.shares_owned -= shares
                    a.pending_notifications.append(f"MARKET: Queued sell executed at ${world.market_price:.2f}.")
                    world.net_volume_this_period -= shares
                else: a.pending_notifications.append("MARKET: Queued sell failed. Insufficient shares.")
        a.pending_market_orders.clear()

def _apply_passive_updates(agent, world):
    agent.awake_hours += 1
    
    if agent.hunger >= 90:
        food_idx = next((i for i, item in enumerate(agent.inventory) if item["item"] in ITEM_CATALOG["food"]), -1)
        if food_idx != -1:
            eaten = agent.inventory.pop(food_idx)
            agent.hunger -= 20
            agent.pending_notifications.append(f"Auto-consumed {eaten['item']} due to extreme hunger.")
        else:
            if agent.money >= 10:
                agent.money -= 10
                agent.hunger -= 30
                agent.pending_notifications.append("Auto-bought emergency food ($10) due to starvation.")

    if agent.hunger >= 100:
        agent.starvation_hours += 1
        agent.health -= min(32, 2 ** agent.starvation_hours)
    else: agent.starvation_hours = 0

    is_sleeping = agent.busy_until > world.sim_time and "Slept" in agent.last_action_result
    hunger_gain = 1.0 if is_sleeping else 5.0
    agent.hunger = min(100.0, agent.hunger + hunger_gain)
    
    agent.energy = max(0.0, agent.energy - 2.0)
    agent.social_fulfillment = max(0.0, agent.social_fulfillment - 1.0)
    
    age_factor = math.exp(0.02 * agent.age)
    stress_penalty = 1.5 if agent.money < 0 else 1.0 
    
    delta_h = (-(0.5 * agent.stress * stress_penalty + 0.3 * agent.hunger) + 0.1 * agent.happiness) * age_factor * 0.05
    agent.health = max(0.0, min(100.0, agent.health + delta_h))

    if agent.health <= 0.0:
        agent.alive = False
        log_death(agent)