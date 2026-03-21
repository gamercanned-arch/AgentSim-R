import random
import time
import numpy as np
import os
import glob

from config import (
    N_AGENTS, RANDOM_SEED, CONTEXT_SIZE, CONTEXT_FILL_RATIO, 
    MAX_RUNTIME_MINUTES, CACHE_DIR, LOG_DIR, BASE_STORE_INVENTORY
)
from state import WorldState, AgentState
from scheduler import run_tick
from locations import get_location_by_name
from logger import log_global

_STARTING_PROFILES = {
    "Alex":   {"wage": 50,  "money": 5000,  "home": "Small House"},
    "Jamie":  {"wage": 60,  "money": 6000,  "home": "Apartment"},
    "Taylor": {"wage": 20,  "money": 20,    "home": "Small Apartment"},
    "Jordan": {"wage": 20,  "money": 2000,  "home": "Apartment"},
    "Mia":    {"wage": 35,  "money": 3500,  "home": "House"},
    "Ethan":  {"wage": 100, "money": 10000, "home": "Luxury House"},
}

def main():
    print("Sweeping old cache and log files for a clean Phase 1 Expansion start...")
    for f in glob.glob(os.path.join(CACHE_DIR, "*.bin")):
        try: os.remove(f)
        except OSError: pass
    for f in glob.glob(os.path.join(LOG_DIR, "*.*")):
        try: os.remove(f)
        except OSError: pass

    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)

    world = WorldState()
    world.store_inventory = dict(BASE_STORE_INVENTORY)
    
    names = ["Alex", "Jamie", "Taylor", "Jordan", "Mia", "Ethan"]
    ages  = [28,      35,      21,       39,       41,    30]

    for i in range(N_AGENTS):
        agent = AgentState(i, names[i], ages[i])
        prof  = _STARTING_PROFILES[names[i]]
        
        home_item = prof["home"]
        agent.current_home = home_item
        agent.owned_locations.append(home_item)
        
        home_loc_name = f"Home_{names[i]}"
        agent.location = home_loc_name
        
        loc_def = get_location_by_name(home_loc_name)
        if loc_def:
            agent.x = (loc_def.x_min + loc_def.x_max) / 2
            agent.y = (loc_def.y_min + loc_def.y_max) / 2
            agent.z = loc_def.z_min
        
        agent.hourly_wage = prof["wage"]
        agent.money       = prof["money"]
        agent.busy_until = random.uniform(0, 60)
        world.agents[i]  = agent

    context_limit = int(CONTEXT_SIZE * CONTEXT_FILL_RATIO)
    print(f"AgentSim-R Phase 1 Expansion starting...\nContext limit: {CONTEXT_SIZE:,}\nTime limit: {MAX_RUNTIME_MINUTES}m")

    tick = 0
    start_wall_time = time.time()

    try:
        while True:
            elapsed_minutes = (time.time() - start_wall_time) / 60.0
            if elapsed_minutes >= MAX_RUNTIME_MINUTES: break

            context_full = run_tick(world)
            tick += 1
            alive = sum(1 for a in world.agents.values() if a.alive)

            if tick % 5 == 0:
                print(f"Tick {tick:4d} | Time: {world.sim_time/3600:.1f}h | Alive: {alive}/{N_AGENTS} | Mkt: ${world.market_price:.2f}")

            if alive == 0 or context_full: break

    except KeyboardInterrupt: print("\n[USER ABORTED]")
    except Exception as e: print(f"\n[FATAL ERROR] {str(e)}")

    log_global({
        "simulation_complete": True,
        "ticks": tick,
        "sim_time_hours": round(world.sim_time / 3600, 2),
    })
    print("\nSimulation complete.")

if __name__ == "__main__": main()