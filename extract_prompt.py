#!/usr/bin/env python3
"""
Script to extract the full prompt for Taylor (agent ID 2).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'python'))

from python.sim import main as init_sim
from python.prompting import build_messages, render_prompt
from python.state import WorldState
from python.config import N_AGENTS

def extract_taylor_prompt():
    # Initialize the world as in sim.py
    world = WorldState()
    world.store_inventory = {}  # dummy
    world.sim_time = 8 * 3600
    world.last_passive = world.sim_time

    names = ["Alex", "Jamie", "Taylor", "Jordan", "Mia", "Ethan"]
    ages = [28, 35, 21, 39, 41, 30]
    profiles = {
        "Alex": {"wage": 50, "money": 5000, "home": "Small Apartment", "job": "developer"},
        "Jamie": {"wage": 60, "money": 6000, "home": "Apartment", "job": "nurse"},
        "Taylor": {"wage": 20, "money": 20, "home": "Small Apartment", "job": "student"},
        "Jordan": {"wage": 20, "money": 2000, "home": "Apartment", "job": "delivery driver"},
        "Mia": {"wage": 35, "money": 3500, "home": "House", "job": "teacher"},
        "Ethan": {"wage": 100, "money": 10000, "home": "Luxury House", "job": "founder"},
    }

    for i in range(N_AGENTS):
        from python.state import AgentState
        name = names[i]
        profile = profiles[name]

        agent = AgentState(id=i, name=name, age=ages[i])
        agent.hourly_wage = profile["wage"]
        agent.money = profile["money"]
        agent.job = profile["job"]

        home_type = profile["home"]
        home_location = world.allocate_home_lot(home_type)
        if not home_location:
            print(f"No home for {name}")
            continue

        agent.current_home_type = home_type
        agent.home_location = home_location
        agent.owned_locations = [home_location]
        agent.location = home_location

        from python.locations import get_location_by_name
        loc_def = get_location_by_name(home_location)
        if loc_def:
            agent.x = (loc_def.x_min + loc_def.x_max) / 2.0
            agent.y = (loc_def.y_min + loc_def.y_max) / 2.0
            agent.z = loc_def.z_min

        agent.busy_until = world.sim_time + 60.0
        agent.current_activity = "idle"

        world.agents[i] = agent

    # Now build messages for Taylor (id=2)
    taylor_id = 2
    notifications = ""
    msgs = build_messages(taylor_id, world, notifications)
    prompt_text = render_prompt(msgs)

    print("Full prompt for Taylor:")
    print("=" * 80)
    print(prompt_text)
    print("=" * 80)

if __name__ == "__main__":
    extract_taylor_prompt()