from __future__ import annotations

from tooling.helpers import canonicalize_item_name, has_item_index
from tooling.catalogs import HOBBY_ITEMS


def handle_sleep(agent, world, args: dict):
    try:
        hours = float(args.get("hours", 8))
    except (ValueError, TypeError):
        hours = 8.0

    hours = max(1.0, min(12.0, hours))
    time_cost = int(hours * 3600)

    from locations import get_current_location_def

    loc_def = get_current_location_def(agent.x, agent.y, agent.z)
    is_home = bool(loc_def and loc_def.name == agent.home_location)

    agent.awake_hours = 0
    agent.is_sleeping = True
    agent.current_activity = "sleeping"

    energy_gain = hours * 10.0
    if is_home:
        agent.energy = min(100.0, agent.energy + energy_gain)
    else:
        # poorer sleep outside home
        agent.energy = max(agent.energy, min(60.0, agent.energy + energy_gain))

    agent.stress = max(0.0, agent.stress - (hours * 2.0))

    msg = (
        f"Sleep started for {hours:.1f}h. You will be unavailable (DND) until you wake. "
        f"Energy: {agent.energy:.1f}."
    )
    if not is_home:
        msg += " (Poor sleep outside home: recovery capped at 60%)."
    return msg, True, time_cost


def handle_do_hobby(agent, world, args: dict):
    item = canonicalize_item_name(str(args.get("item", "")).strip()[:100])
    item_data = None
    source = None

    # hand
    if agent.currently_holding and agent.currently_holding["item"].lower() == item.lower():
        item_data = agent.currently_holding
        source = "hand"
    else:
        idx = has_item_index(agent, item)
        if idx != -1:
            item_data = agent.inventory[idx]
            source = idx

    if not item_data:
        agent.failed_calls += 1
        return f"You don't have {item}.", False, 60

    if item_data["item"] not in HOBBY_ITEMS:
        agent.failed_calls += 1
        return f"{item_data['item']} is not a valid hobby item.", False, 60

    agent.stress = max(0.0, agent.stress - 15.0)
    agent.happiness = min(100.0, agent.happiness + 10.0)

    item_data["durability"] = item_data.get("durability", 5) - 1
    msg = f"Enjoyed hobby time with {item_data['item']}. Stress fell."

    if item_data["durability"] <= 0:
        if source == "hand":
            agent.currently_holding = None
        elif isinstance(source, int):
            agent.inventory.pop(source)
        msg += f" {item_data['item']} wore out."

    return msg, True, 3600
