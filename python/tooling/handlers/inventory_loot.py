from __future__ import annotations

import uuid

from python.config import (
    AUTO_LOOT_RADIUS,
    DROP_REPICKUP_COOLDOWN,
    GROUND_PICKUP_RADIUS,
    MAX_INVENTORY,
)
from python.locations import get_current_location_def, get_distance_3d
from python.tooling.helpers import (
    canonicalize_item_name,
    has_item_index,
    normalize_label,
    store_currently_holding_if_possible,
)


def _task_failure(agent, world, message: str, cost: int = 30):
    task_failures = int(agent.pending_task_data.get("task_failures", 0)) + 1
    agent.pending_task_data["task_failures"] = task_failures

    if task_failures >= 3:
        spent = agent.pending_task_data.get("energy_spent", 0.0)
        start = agent.pending_task_data.get("start_time", world.sim_time)
        elapsed_hours = max(0.0, (world.sim_time - start) / 3600.0)
        refund = max(0.0, spent - (elapsed_hours * 10.0))
        agent.energy = min(100.0, agent.energy + refund)

        if agent.currently_holding and agent.currently_holding.get("id") == "job_prop":
            agent.currently_holding = None
        agent.task_state = "idle"
        agent.pending_task_data = {}
        agent.active_task_entities = {}
        if not agent.is_sleeping:
            agent.current_activity = "idle"
        return (
            f"{message} Task cancelled after 3 failed attempts. You may start over.",
            False,
            cost,
        )

    return f"{message} Failed attempts in this task: {task_failures}/3.", False, cost


def _find_ground_item(world, agent, item_name: str):
    wanted = normalize_label(item_name)
    for gi in world.ground_items:
        if normalize_label(gi.get("item", "")) != wanted:
            continue
        d = get_distance_3d((agent.x, agent.y, agent.z), (gi["x"], gi["y"], gi["z"]))
        if d <= GROUND_PICKUP_RADIUS:
            return gi
    return None


def _corpse_item_nearby(world, agent, item_name: str) -> bool:
    wanted = normalize_label(item_name)
    for estate in world.corpse_estates:
        d = get_distance_3d(
            (agent.x, agent.y, agent.z), (estate["x"], estate["y"], estate["z"])
        )
        if d > AUTO_LOOT_RADIUS:
            continue
        for it in estate.get("items", []):
            if normalize_label(it.get("item", "")) == wanted:
                return True
    return False


def _remove_empty_estates(world) -> None:
    world.corpse_estates = [
        e
        for e in world.corpse_estates
        if float(e.get("money", 0.0)) > 0.0 or e.get("items")
    ]


def try_auto_collect_loot(agent, world) -> None:
    if not agent.alive:
        return

    for estate in list(world.corpse_estates):
        d = get_distance_3d(
            (agent.x, agent.y, agent.z), (estate["x"], estate["y"], estate["z"])
        )
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
            item_list = (
                ", ".join(i["item"] for i in taken_items) if taken_items else "no items"
            )
            agent.pending_notifications.append(
                f"You automatically collected nearby estate loot: {item_list}. Cash recovered: ${taken_money:.2f}."
            )

    _remove_empty_estates(world)


def handle_hold_item(agent, world, args: dict):
    raw_item = str(args.get("item_name", "")).strip()
    if not raw_item:
        agent.failed_calls += 1
        return "Error: No item specified.", False, 30

    action_word = normalize_label(raw_item)
    if action_word in {"none", "store", "unequip", "put away"}:
        if not agent.currently_holding:
            agent.failed_calls += 1
            return "You aren't holding anything to store.", False, 30
        if agent.currently_holding.get("id") == "job_prop":
            agent.failed_calls += 1
            return (
                "You are holding a required task prop. Finish the task before storing it.",
                False,
                30,
            )
        if len(agent.inventory) >= MAX_INVENTORY:
            agent.failed_calls += 1
            return "Inventory full. Cannot store held item.", False, 30
        held_name = agent.currently_holding.get("item", "Unknown")
        agent.inventory.append(agent.currently_holding)
        agent.currently_holding = None
        return f"Stored {held_name} back in inventory.", True, 30

    item = canonicalize_item_name(raw_item)

    if agent.currently_holding and normalize_label(
        agent.currently_holding.get("item", "")
    ) == normalize_label(item):
        return f"You are already holding {agent.currently_holding.get('item','Unknown')}.", True, 5

    idx = has_item_index(agent, item)
    if idx == -1:
        if _find_ground_item(world, agent, item):
            agent.failed_calls += 1
            return (
                f"{item} is on the ground nearby. Use pick_item to pick it up.",
                False,
                30,
            )
        agent.failed_calls += 1
        return f"{item} is not in your inventory.", False, 30

    if agent.currently_holding:
        ok, why = store_currently_holding_if_possible(agent)
        if not ok:
            agent.failed_calls += 1
            return why, False, 30

    agent.currently_holding = agent.inventory.pop(idx)
    return f"Now holding {agent.currently_holding.get('item','Unknown')} in hand.", True, 30


def handle_pick_item(agent, world, args: dict):
    raw_item = str(args.get("item_name", "")).strip()
    if not raw_item:
        agent.failed_calls += 1
        return "Error: No item specified.", False, 30

    item = canonicalize_item_name(raw_item)

    if agent.task_state == "job_pick":
        flavor = agent.pending_task_data.get("flavor", {}) or {}
        required = str(flavor.get("pick", "")).strip()
        workplace = str(agent.pending_task_data.get("workplace", "")).strip()
        task_entities = getattr(agent, "active_task_entities", {}) or {}
        active_prop = str(task_entities.get("prop", "")).strip()
        here = get_current_location_def(agent.x, agent.y, agent.z)

        if not required or not active_prop:
            agent.failed_calls += 1
            return _task_failure(agent, world, "Task is missing required prop.", 30)

        if not here or here.name != workplace:
            agent.failed_calls += 1
            return _task_failure(
                agent,
                world,
                "You must remain in the correct task location to pick up the task prop.",
                30,
            )

        if normalize_label(item) != normalize_label(required) or normalize_label(
            item
        ) != normalize_label(active_prop):
            agent.failed_calls += 1
            return _task_failure(
                agent, world, f"You need to pick up the required task prop {required}.", 30
            )

        ok, why = store_currently_holding_if_possible(agent)
        if not ok:
            agent.failed_calls += 1
            return why, False, 30

        agent.currently_holding = {"id": "job_prop", "item": required, "durability": 99}
        agent.task_state = "job_mcq"
        target = str(flavor.get("obj", "")).strip() or "the task target"
        return (
            f"You picked up the required task prop {required}. "
            f"The question is now active in your observation. "
            f"Answer it by using interact_with on {target} and choosing A, B, or C.",
            True,
            60,
        )

    action_word = normalize_label(raw_item)
    if action_word in {"none", "store", "unequip", "put away"}:
        agent.failed_calls += 1
        return (
            "pick_item only picks nearby ground items or required task props. Use hold_item to manage your hand.",
            False,
            30,
        )

    if has_item_index(agent, item) != -1:
        agent.failed_calls += 1
        return (
            f"{item} is already in your inventory. Use hold_item to put it in your hand.",
            False,
            30,
        )

    ground_item = _find_ground_item(world, agent, item)
    if ground_item:
        if ground_item.get("dropper_id") == agent.id and world.sim_time < float(
            ground_item.get("repickup_block_until", 0.0)
        ):
            agent.failed_calls += 1
            return (
                "You cannot re-pick your own dropped item yet. Wait a bit longer.",
                False,
                30,
            )

        if agent.currently_holding:
            ok, why = store_currently_holding_if_possible(agent)
            if not ok:
                agent.failed_calls += 1
                return why, False, 30

        agent.currently_holding = {
            "id": ground_item["id"],
            "item": ground_item.get("item", "Unknown"),
            "durability": ground_item.get("durability", 5),
            "bought": ground_item.get("bought", world.sim_time),
        }
        world.ground_items.remove(ground_item)

        dropper = world.agents.get(ground_item.get("dropper_id"))
        if dropper and dropper.alive and dropper.id != agent.id:
            dropper.pending_notifications.append(
                f"{ground_item.get('item','Unknown')} you dropped was picked up by someone else."
            )

        return f"Picked up {agent.currently_holding.get('item','Unknown')} from the ground.", True, 30

    if _corpse_item_nearby(world, agent, item):
        agent.failed_calls += 1
        return (
            (
                f"{item} is part of nearby estate loot. Estate loot is collected automatically when you are close enough. "
                f"Check your inventory or make space first."
            ),
            False,
            30,
        )

    agent.failed_calls += 1
    return f"Nearby ground item {item} not found.", False, 60


def handle_drop_item(agent, world, args: dict):
    raw_item = str(args.get("item_name", "")).strip()
    
    # FIX: explicitly handle the empty case
    if not raw_item and not agent.currently_holding:
        agent.failed_calls += 1
        return "You aren't holding anything to drop.", False, 30

    if not raw_item:
        if agent.currently_holding:
#... continues as normal
            if agent.currently_holding.get("id") == "job_prop":
                agent.failed_calls += 1
                return (
                    "Do not drop the required task prop. Finish or cancel the task first.",
                    False,
                    30,
                )
            item_data = agent.currently_holding
            agent.currently_holding = None
            world.ground_items.append(
                {
                    "id": str(uuid.uuid4()),
                    "item": item_data.get("item", "Unknown"),
                    "durability": item_data.get("durability", 5),
                    "bought": item_data.get("bought", world.sim_time),
                    "x": float(agent.x),
                    "y": float(agent.y),
                    "z": 0.0,  # clamp to ground-plane
                    "dropper_id": agent.id,
                    "repickup_block_until": world.sim_time + DROP_REPICKUP_COOLDOWN,
                }
            )
            return f"Dropped {item_data.get('item','Unknown')} on the ground.", True, 30
        item = ""
    else:
        item = canonicalize_item_name(raw_item)

    item_data = None

    if agent.currently_holding and normalize_label(item) == normalize_label(
        agent.currently_holding.get("item", "")
    ):
        if agent.currently_holding.get("id") == "job_prop":
            agent.failed_calls += 1
            return (
                "Do not drop the required task prop. Finish or cancel the task first.",
                False,
                30,
            )
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
            "item": item_data.get("item", "Unknown"),
            "durability": item_data.get("durability", 5),
            "bought": item_data.get("bought", world.sim_time),
            "x": float(agent.x),
            "y": float(agent.y),
            "z": 0.0,  # clamp
            "dropper_id": agent.id,
            "repickup_block_until": world.sim_time + DROP_REPICKUP_COOLDOWN,
        }
    )
    return f"Dropped {item_data.get('item','Unknown')} on the ground.", True, 30