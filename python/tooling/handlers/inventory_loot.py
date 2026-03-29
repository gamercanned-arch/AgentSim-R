from __future__ import annotations

import uuid
from copy import deepcopy

from config import (
    AUTO_LOOT_RADIUS,
    DROP_REPICKUP_COOLDOWN,
    GROUND_PICKUP_RADIUS,
    MAX_INVENTORY,
)
from locations import get_distance_3d
from tooling.helpers import (
    canonicalize_item_name,
    has_item_index,
    store_currently_holding_if_possible,
)


def _find_ground_item(world, agent, item_name: str):
    item_name = item_name.lower()
    for gi in world.ground_items:
        if gi.get("item", "").lower() != item_name:
            continue
        d = get_distance_3d((agent.x, agent.y, agent.z), (gi["x"], gi["y"], gi["z"]))
        if d <= GROUND_PICKUP_RADIUS:
            return gi
    return None


def _find_corpse_item(world, agent, item_name: str):
    item_name = item_name.lower()
    for estate in world.corpse_estates:
        d = get_distance_3d((agent.x, agent.y, agent.z), (estate["x"], estate["y"], estate["z"]))
        if d > GROUND_PICKUP_RADIUS:
            continue
        for it in estate.get("items", []):
            if it.get("item", "").lower() == item_name:
                return estate, it
    return None, None


def _remove_empty_estates(world) -> None:
    world.corpse_estates = [
        e for e in world.corpse_estates if float(e.get("money", 0.0)) > 0.0 or e.get("items")
    ]


def try_auto_collect_loot(agent, world) -> None:
    if not agent.alive:
        return

    for estate in list(world.corpse_estates):
        d = get_distance_3d((agent.x, agent.y, agent.z), (estate["x"], estate["y"], estate["z"]))
        if d > AUTO_LOOT_RADIUS:
            continue

        taken_items = []
        available_space = max(0, MAX_INVENTORY - len(agent.inventory))
        if available_space > 0 and estate.get("items"):
            taken_items = estate["items"][:available_space]
            agent.inventory.extend(taken_items)
            estate["items"] = estate["items"][available_space:]

        taken_money = float(estate.get("money", 0.0))
        if taken_money > 0:
            agent.money += taken_money
            estate["money"] = 0.0

        if taken_items or taken_money > 0:
            item_list = ", ".join(i["item"] for i in taken_items) if taken_items else "no items"
            agent.pending_notifications.append(
                f"You found items from a dead body: {item_list}. Cash recovered: ${taken_money:.2f}."
            )

    _remove_empty_estates(world)


def handle_pick_item(agent, world, args: dict):
    raw_item = str(args.get("item_name", "")).strip()

    if raw_item.lower() in ["none", "store", "unequip", "put away", ""]:
        if agent.currently_holding:
            if len(agent.inventory) >= MAX_INVENTORY:
                agent.failed_calls += 1
                return "Inventory full. Cannot store held item.", False, 30
            held_name = agent.currently_holding["item"]
            agent.inventory.append(agent.currently_holding)
            agent.currently_holding = None
            return f"Stored {held_name} back in inventory.", True, 30
        agent.failed_calls += 1
        return "You aren't holding anything to store.", False, 30

    item = canonicalize_item_name(raw_item)

    # Task prop step
    if agent.task_state == "job_pick":
        flavor = agent.pending_task_data.get("flavor", {}) or {}
        required = str(flavor.get("pick", "")).strip()
        if not required:
            agent.failed_calls += 1
            return "Task is missing required prop.", False, 30

        if item.lower() != required.lower():
            agent.failed_calls += 1
            task_failures = int(agent.pending_task_data.get("task_failures", 0)) + 1
            agent.pending_task_data["task_failures"] = task_failures
            if task_failures >= 3:
                agent.task_state = "idle"
                agent.pending_task_data = {}
                agent.active_task_entities = {}
                if not agent.is_sleeping:
                    agent.current_activity = "idle"
                return f"You need to pick_item '{required}'. Task cancelled after 3 failed attempts.", False, 30
            return f"You need to pick_item '{required}'. Failed attempts {task_failures}/3.", False, 30

        ok, why = store_currently_holding_if_possible(agent)
        if not ok:
            agent.failed_calls += 1
            return why, False, 30

        agent.currently_holding = {"id": "job_prop", "item": required, "durability": 99}
        agent.task_state = "job_mcq"
        return (
            f"[TASK] You grabbed the required prop: {required}. "
            f"Now answer via interact_with(person_or_object='{flavor.get('obj','')}', action='A|B|C').",
            True,
            60,
        )

    # Inventory -> hand
    idx = has_item_index(agent, item)
    if idx != -1:
        if agent.currently_holding:
            ok, why = store_currently_holding_if_possible(agent)
            if not ok:
                agent.failed_calls += 1
                return why, False, 30
        agent.currently_holding = agent.inventory.pop(idx)
        return f"Now holding {agent.currently_holding['item']} in hand.", True, 30

    # Ground pickup
    ground_item = _find_ground_item(world, agent, item)
    if ground_item:
        if (
            ground_item.get("dropper_id") == agent.id
            and world.sim_time < float(ground_item.get("repickup_block_until", 0.0))
        ):
            agent.failed_calls += 1
            return "You cannot re-pick your own dropped item yet. Wait a bit longer.", False, 30

        if agent.currently_holding:
            ok, why = store_currently_holding_if_possible(agent)
            if not ok:
                agent.failed_calls += 1
                return why, False, 30

        agent.currently_holding = {
            "id": ground_item["id"],
            "item": ground_item["item"],
            "durability": ground_item.get("durability", 5),
            "bought": ground_item.get("bought", world.sim_time),
        }
        world.ground_items.remove(ground_item)

        dropper = world.agents.get(ground_item.get("dropper_id"))
        if dropper and dropper.alive and dropper.id != agent.id:
            dropper.pending_notifications.append(
                f"{ground_item['item']} you dropped was picked up by someone else."
            )

        return f"Picked up {item} from the ground.", True, 30

    # Corpse loot pickup
    estate, estate_item = _find_corpse_item(world, agent, item)
    if estate and estate_item:
        if agent.currently_holding:
            ok, why = store_currently_holding_if_possible(agent)
            if not ok:
                agent.failed_calls += 1
                return why, False, 30
        agent.currently_holding = deepcopy(estate_item)
        estate["items"].remove(estate_item)
        _remove_empty_estates(world)
        return f"Recovered {item} from {estate.get('source_agent_name', 'a corpse')}'s remains.", True, 30

    agent.failed_calls += 1
    return f"Item {item} not in inventory or nearby.", False, 60


def handle_drop_item(agent, world, args: dict):
    item = canonicalize_item_name(str(args.get("item_name", "")).strip())
    item_data = None

    if agent.currently_holding and (not item or item.lower() == agent.currently_holding["item"].lower()):
        if agent.currently_holding.get("id") == "job_prop":
            agent.failed_calls += 1
            return "Do not drop the required task prop. Finish or cancel the task first.", False, 30
        item_data = agent.currently_holding
        agent.currently_holding = None
    else:
        idx = has_item_index(agent, item)
        if idx != -1:
            item_data = agent.inventory.pop(idx)

    if not item_data:
        agent.failed_calls += 1
        return f"You don't have {item} to drop.", False, 30

    world.ground_items.append(
        {
            "id": str(uuid.uuid4()),
            "item": item_data["item"],
            "durability": item_data.get("durability", 5),
            "bought": item_data.get("bought", world.sim_time),
            "x": float(agent.x),
            "y": float(agent.y),
            "z": float(agent.z),
            "dropper_id": agent.id,
            "repickup_block_until": world.sim_time + DROP_REPICKUP_COOLDOWN,
        }
    )
    return f"Dropped {item_data['item']} on the ground.", True, 30