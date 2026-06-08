from __future__ import annotations

from python.tooling.helpers import canonicalize_item_name, has_item_index
from python.tooling.catalogs import HOBBY_ITEMS


def handle_sleep(agent, world, args: dict):
    try:
        hours = float(args.get("hours", 8))
    except (ValueError, TypeError):
        hours = 8.0

    hours = max(1.0, min(12.0, hours))
    time_cost = int(hours * 3600)

    agent.awake_hours = 0
    agent.is_sleeping = True
    agent.current_activity = "sleeping"
    agent._sleep_start = world.sim_time

    return (
        f"Sleep started for {hours:.1f}h. You will be unavailable (DND) until you wake.",
        True,
        time_cost,
    )


def handle_do_hobby(agent, world, args: dict):
    item = canonicalize_item_name(str(args.get("item", "")).strip()[:100])
    item_data = None
    source = None

    if (
        agent.currently_holding
        and str(agent.currently_holding.get("item", "")).lower() == item.lower()
    ):
        item_data = agent.currently_holding
        source = "hand"
    else:
        idx = has_item_index(agent, item)
        if idx != -1:
            item_data = agent.inventory[idx]
            source = idx

    if not item_data:
        # Check if we can fall back to meditation (no hobby items and money < $5)
        has_any_hobby_item = False
        if agent.currently_holding and agent.currently_holding.get("item") in HOBBY_ITEMS:
            has_any_hobby_item = True
        else:
            for it in agent.inventory:
                if it.get("item") in HOBBY_ITEMS:
                    has_any_hobby_item = True
                    break
        
        if not has_any_hobby_item and agent.money < 5.0:
            agent.stress = max(0.0, agent.stress - 5.0)
            agent.happiness = min(100.0, agent.happiness + 3.0)
            return "With no hobby items available and insufficient funds to buy one, you meditate and breathe deeply. Stress fell slightly.", True, 3600

        agent.failed_calls += 1
        return f"You don't have {item}.", False, 60

    if item_data.get("item") not in HOBBY_ITEMS:
        agent.failed_calls += 1
        return f"{item_data.get('item','Unknown')} is not a valid hobby item.", False, 60

    agent.stress = max(0.0, agent.stress - 15.0)
    agent.happiness = min(100.0, agent.happiness + 10.0)

    item_data["durability"] = item_data.get("durability", 5) - 1
    desc = str(args.get("description", "")).strip()
    if desc:
        desc = desc.encode("ascii", "ignore").decode("ascii")
        msg = f"Enjoyed hobby time with {item_data.get('item','Unknown')} ({desc}). Stress fell."
    else:
        msg = f"Enjoyed hobby time with {item_data.get('item','Unknown')}. Stress fell."

    if item_data["durability"] <= 0:
        if source == "hand":
            agent.currently_holding = None
        elif isinstance(source, int):
            agent.inventory.pop(source)
        msg += f" {item_data.get('item','Unknown')} wore out."

    return msg, True, 3600


def handle_wait(agent, world, args: dict):
    try:
        minutes = float(args.get("minutes", 10.0))
    except (ValueError, TypeError):
        minutes = 10.0

    minutes = max(1.0, min(180.0, minutes))
    time_cost = int(minutes * 60)

    agent.current_activity = "waiting"

    return f"Waited in place for {minutes:.1f} minutes.", True, time_cost