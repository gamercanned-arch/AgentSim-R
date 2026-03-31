import glob
import os
import random
import time

import numpy as np

from config import BASE_STORE_INVENTORY, CACHE_DIR, LOG_DIR, MAX_RUNTIME_MINUTES, N_AGENTS, RANDOM_SEED
from locations import describe_home_location, get_location_by_name, get_location_outside_entrance_point
from logger import log_global
from scheduler import run_tick
from state import AgentState, WorldState

_STARTING_PROFILES = {
    "Alex": {
        "wage": 50,
        "money": 5000,
        "home": "Small Apartment",
        "job": "developer",
    },
    "Jamie": {
        "wage": 60,
        "money": 6000,
        "home": "Apartment",
        "job": "nurse",
    },
    "Taylor": {
        "wage": 20,
        "money": 20,
        "home": "Small Apartment",
        "job": "student",
    },
    "Jordan": {
        "wage": 20,
        "money": 2000,
        "home": "Apartment",
        "job": "delivery driver",
    },
    "Mia": {
        "wage": 35,
        "money": 3500,
        "home": "House",
        "job": "teacher",
    },
    "Ethan": {
        "wage": 100,
        "money": 10000,
        "home": "Luxury House",
        "job": "founder",
    },
}


def main():
    print("Sweeping old cache and log files for a clean simulation start...")

    for f in glob.glob(os.path.join(CACHE_DIR, "*.bin")):
        try:
            os.remove(f)
        except OSError:
            pass

    for f in glob.glob(os.path.join(LOG_DIR, "*.*")):
        try:
            os.remove(f)
        except OSError:
            pass

    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)

    world = WorldState()
    world.store_inventory = dict(BASE_STORE_INVENTORY)

    world.sim_time = 8 * 3600
    world.last_passive = world.sim_time
    world.last_market_tick = world.sim_time

    names = ["Alex", "Jamie", "Taylor", "Jordan", "Mia", "Ethan"]
    ages = [28, 35, 21, 39, 41, 30]

    if N_AGENTS > len(names):
        raise ValueError(f"N_AGENTS={N_AGENTS} exceeds configured starting profiles.")

    for i in range(N_AGENTS):
        name = names[i]
        profile = _STARTING_PROFILES[name]

        agent = AgentState(
            id=i,
            name=name,
            age=ages[i],
        )

        agent.hourly_wage = profile["wage"]
        agent.money = profile["money"]
        agent.job = profile["job"]

        home_type = profile["home"]
        home_location = world.allocate_home_lot(home_type, prefer_floor1=True)
        if not home_location:
            raise RuntimeError(f"No vacant home lots available for starting home type '{home_type}'.")

        agent.current_home_type = home_type
        agent.home_location = home_location
        agent.owned_locations = [home_location]
        agent.location = home_location

        loc_def = get_location_by_name(home_location)
        if loc_def:
            agent.x = (loc_def.x_min + loc_def.x_max) / 2.0
            agent.y = (loc_def.y_min + loc_def.y_max) / 2.0
            agent.z = loc_def.z_min

        if loc_def:
            outside = get_location_outside_entrance_point(loc_def, offset_m=15.0)
            agent.vehicle_x, agent.vehicle_y, agent.vehicle_z = outside
        else:
            agent.vehicle_x, agent.vehicle_y, agent.vehicle_z = agent.x, agent.y, agent.z

        agent.busy_until = random.uniform(world.sim_time, world.sim_time + 60.0)
        agent.current_activity = "idle"

        world.agents[i] = agent

        print(
            f"Initialized {agent.name:>6s} | Job: {agent.job:<15s} | "
            f"Home: Home_{agent.name} ({describe_home_location(home_location)}) | "
            f"Cash: ${agent.money:.2f} | Vehicle: {agent.vehicle_type}"
        )

    print(f"\nAgentSim-R starting...\nTime limit: {MAX_RUNTIME_MINUTES}m")

    tick = 0
    start_wall_time = time.time()

    try:
        while True:
            elapsed_minutes = (time.time() - start_wall_time) / 60.0
            if elapsed_minutes >= MAX_RUNTIME_MINUTES:
                break

            context_full = run_tick(world)
            tick += 1

            alive = sum(1 for a in world.agents.values() if a.alive)

            if tick % 5 == 0:
                print(
                    f"Tick {tick:4d} | Time: {world.sim_time/3600:.1f}h | "
                    f"Alive: {alive}/{N_AGENTS} | Mkt: ${world.market_price:.2f}"
                )

            if alive == 0 or context_full:
                break

    except KeyboardInterrupt:
        print("\n[USER ABORTED]")
    except Exception as e:
        print(f"\n[FATAL ERROR] {str(e)}")

    log_global(
        {
            "simulation_complete": True,
            "ticks": tick,
            "sim_time_hours": round(world.sim_time / 3600.0, 2),
            "alive_agents": sum(1 for a in world.agents.values() if a.alive),
            "market_price": round(world.market_price, 2),
        }
    )
    print("\nSimulation complete.")


if __name__ == "__main__":
    main()
