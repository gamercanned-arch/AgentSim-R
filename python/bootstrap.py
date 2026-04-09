from __future__ import annotations
import random
import numpy as np
from python.config import BASE_STORE_INVENTORY, N_AGENTS, RANDOM_SEED
from python.locations import get_location_by_name, get_location_outside_entrance_point
from python.state import AgentState, WorldState

STARTING_PROFILES = {
    "Alex": {"wage": 50, "money": 5000, "home": "Small Apartment", "job": "developer"},
    "Jamie": {"wage": 60, "money": 6000, "home": "Apartment", "job": "nurse"},
    "Taylor": {"wage": 20, "money": 20, "home": "Small Apartment", "job": "student"},
    "Jordan": {
        "wage": 20,
        "money": 2000,
        "home": "Apartment",
        "job": "delivery driver",
    },
    "Mia": {"wage": 35, "money": 3500, "home": "House", "job": "teacher"},
    "Ethan": {"wage": 100, "money": 10000, "home": "Luxury House", "job": "founder"},
}

STARTING_NAMES = ["Alex", "Jamie", "Taylor", "Jordan", "Mia", "Ethan"]
STARTING_AGES = [28, 35, 21, 39, 41, 30]


def build_starting_world(
    seed: int = RANDOM_SEED, n_agents: int = N_AGENTS
) -> WorldState:
    random.seed(seed)
    np.random.seed(seed)

    world = WorldState()
    world.store_inventory = dict(BASE_STORE_INVENTORY)
    world.sim_time = 8 * 3600
    world.last_passive = world.sim_time
    world.last_market_tick = world.sim_time

    if n_agents > len(STARTING_NAMES):
        raise ValueError(f"N_AGENTS={n_agents} exceeds configured starting profiles.")

    for i in range(n_agents):
        name = STARTING_NAMES[i]
        profile = STARTING_PROFILES[name]

        agent = AgentState(id=i, name=name, age=STARTING_AGES[i])
        agent.hourly_wage = profile["wage"]
        agent.money = profile["money"]
        agent.job = profile["job"]

        home_type = profile["home"]
        # Floor-1-only: if no floor-1 lot exists, fail loudly.
        home_location = world.allocate_home_lot(home_type, prefer_floor1=True)
        if not home_location:
            raise RuntimeError(
                f"No vacant FLOOR 1 home lots available for starting home type '{home_type}'."
            )

        agent.current_home_type = home_type
        agent.home_location = home_location
        agent.owned_locations = [home_location]
        agent.location = home_location

        loc_def = get_location_by_name(home_location)
        if loc_def:
            agent.x = (loc_def.x_min + loc_def.x_max) / 2.0
            agent.y = (loc_def.y_min + loc_def.y_max) / 2.0
            # FIX 8: Ground-floor-only — always clamp agent Z to 0.0 at bootstrap.
            # Previously used loc_def.z_min which could be non-zero for upper-floor
            # apartments, creating a coordinate mismatch with the Z=0 invariant.
            agent.z = 0.0

            outside = get_location_outside_entrance_point(loc_def, offset_m=15.0)
            agent.vehicle_x, agent.vehicle_y = outside[0], outside[1]
            agent.vehicle_z = 0.0  # FIX 8: clamp vehicle Z to ground plane
        else:
            agent.vehicle_x, agent.vehicle_y, agent.vehicle_z = agent.x, agent.y, 0.0

        agent.busy_until = random.uniform(world.sim_time, world.sim_time + 60.0)
        agent.current_activity = "idle"
        world.agents[i] = agent

    return world
