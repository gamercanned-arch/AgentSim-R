import os
import random
import re
import uuid
from copy import deepcopy
from typing import Dict, Optional, Tuple

from config import (
    AUTO_LOOT_RADIUS,
    CACHE_DIR,
    DROP_REPICKUP_COOLDOWN,
    GROUND_PICKUP_RADIUS,
    MAX_INVENTORY,
    OBJECT_Z_TOLERANCE,
    STATUS_MAX_DISTANCE,
    WORKPLACE_MAX_DISTANCE,
)
from locations import (
    LOCATIONS_3D,
    describe_home_location,
    get_current_location_def,
    get_distance_3d,
    get_location_by_name,
    get_location_center,
    is_home_location,
)
from logger import log_death
from state import WorldState

ITEM_CATALOG = {
    "food": {
        "Snacks": {"price": 4, "hunger": 10, "time": 60, "caffeine": 0},
        "Water": {"price": 2, "hunger": 5, "time": 60, "caffeine": 0},
        "Coffee": {"price": 5, "hunger": 5, "time": 120, "caffeine": 1},
        "Sandwich": {"price": 10, "hunger": 30, "time": 600, "caffeine": 0},
        "Pizza": {"price": 15, "hunger": 45, "time": 1200, "caffeine": 0},
        "Premium Meal": {"price": 25, "hunger": 80, "time": 1800, "caffeine": 0},
    },
    "everyday": {
        "Toothbrush": 5,
        "Clothes": 50,
        "Book": 20,
        "Art Supplies": 40,
        "Notebook": 5,
    },
    "housing": {
        "Small Apartment": 75_000,
        "Apartment": 120_000,
        "House": 400_000,
        "Luxury House": 750_000,
    },
    "health": {
        "Medicine": 12,
        "Vitamins": 25,
        "First aid kit": 30,
    },
}

HOBBY_ITEMS = {"Book", "Art Supplies", "Notebook"}

JOB_FLAVORS = {
    "tech": {
        "pick": "Laptop",
        "obj": "Standing Desk",
        "q": "Server crashed due to OOM. A) Restart server blindly, B) Optimize memory, C) Download more RAM.",
        "ans": "B",
    },
    "startup": {
        "pick": "Pitch Deck",
        "obj": "Standing Desk",
        "q": "Investor asks about churn rate. A) Lie, B) Explain retention strategy, C) Cry.",
        "ans": "B",
    },
    "founder": {
        "pick": "Pitch Deck",
        "obj": "Standing Desk",
        "q": "Investor asks about churn rate. A) Lie, B) Explain retention strategy, C) Cry.",
        "ans": "B",
    },
    "nurse": {
        "pick": "Stethoscope",
        "obj": "Patient",
        "q": "Patient has high BP. A) Give adrenaline, B) Administer beta-blockers, C) Ignore.",
        "ans": "B",
    },
    "doctor": {
        "pick": "Stethoscope",
        "obj": "Patient",
        "q": "Patient has high BP. A) Give adrenaline, B) Administer beta-blockers, C) Ignore.",
        "ans": "B",
    },
    "teacher": {
        "pick": "Marker",
        "obj": "Whiteboard",
        "q": "Student asks for help with fractions. A) Ignore them, B) Explain visually, C) Give detention.",
        "ans": "B",
    },
    "tutor": {
        "pick": "Marker",
        "obj": "Whiteboard",
        "q": "Student asks for help with fractions. A) Ignore them, B) Explain visually, C) Give detention.",
        "ans": "B",
    },
    "delivery": {
        "pick": "Scanner",
        "obj": "Loading Dock",
        "q": "Label is torn. A) Guess address, B) Return to depot for relabeling, C) Throw it away.",
        "ans": "B",
    },
    "driver": {
        "pick": "Scanner",
        "obj": "Loading Dock",
        "q": "Label is torn. A) Guess address, B) Return to depot for relabeling, C) Throw it away.",
        "ans": "B",
    },
    "fedex": {
        "pick": "Scanner",
        "obj": "Loading Dock",
        "q": "Label is torn. A) Guess address, B) Return to depot for relabeling, C) Throw it away.",
        "ans": "B",
    },
    "developer": {
        "pick": "Laptop",
        "obj": "Standing Desk",
        "q": "Client wants 10 extra features today. A) Agree blindly, B) Negotiate scope, C) Block client.",
        "ans": "B",
    },
    "generic": {
        "pick": "Notebook",
        "obj": "Desk",
        "q": "A mundane task appears. A) Procrastinate, B) Complete it efficiently, C) Complain.",
        "ans": "B",
    },
    "education": {
        "pick": "Notebook",
        "obj": "Exam",
        "q": "What is the powerhouse of the cell? A) Nucleus, B) Mitochondria, C) Ribosome.",
        "ans": "B",
    },
}

WORKPLACE_BY_JOB = {
    "developer": "Startup_Sowl",
    "tech": "Startup_Sowl",
    "startup": "Startup_Sowl",
    "founder": "Startup_Sowl",
    "nurse": "Hospital",
    "doctor": "Hospital",
    "delivery": "Office_FedEx",
    "driver": "Office_FedEx",
    "fedex": "Office_FedEx",
    "teacher": "School",
    "tutor": "School",
}

EDUCATION_LOCATIONS = ["School", "Library"]


def parse_tool_call(tool_call_str: str) -> tuple:
    try:
        clean_str = re.sub(r"<think>.*?</think>", "", tool_call_str, flags=re.DOTALL).strip()

        matches = list(re.finditer(r"<tool_call>(.*?)</tool_call>", clean_str, re.DOTALL))
        if not matches:
            return "Parse error: No <tool_call> tags found.", {}
        if len(matches) != 1:
            return f"Parse error: Expected exactly one <tool_call> block, found {len(matches)}.", {}
        if matches[0].span() != (0, len(clean_str)):
            return "Parse error: Unexpected text outside <tool_call> block.", {}

        block = matches[0].group(1).strip()
        func_matches = list(re.finditer(r"<function=([^>\n]+)>(.*?)</function>", block, re.DOTALL))
        if not func_matches:
            return "Parse error: No <function=name> tag found.", {}
        if len(func_matches) != 1:
            return f"Parse error: Expected exactly one <function=name> block, found {len(func_matches)}.", {}
        if func_matches[0].span() != (0, len(block)):
            return "Parse error: Unexpected text inside <tool_call> block.", {}

        func_match = func_matches[0]
        name = func_match.group(1).strip()
        if not name:
            return "Parse error: Empty function name.", {}
        params_block = func_match.group(2)

        args = {}
        cursor = 0
        param_matches = list(re.finditer(r"<parameter=([^>]+)>(.*?)</parameter>", params_block, re.DOTALL))
        for p in param_matches:
            if params_block[cursor:p.start()].strip():
                return "Parse error: Unexpected text inside <function> block.", {}
            key = p.group(1).strip()
            if not key:
                return "Parse error: Empty parameter name.", {}
            if key in args:
                return f"Parse error: Duplicate parameter '{key}'.", {}
            val = p.group(2).strip()
            args[key] = val
            cursor = p.end()

        if params_block[cursor:].strip():
            return "Parse error: Unexpected text inside <function> block.", {}

        return name, args
    except Exception as e:
        return f"Parse error: {e}", {}


def _is_always_open(loc) -> bool:
    return bool(loc and (loc.open_time == loc.close_time or (loc.open_time <= 0.0 and loc.close_time >= 24.0)))


def _check_open_hours(loc, current_time: float) -> bool:
    if not loc:
        return True

    current_hour = (current_time % 86400) / 3600.0

    if _is_always_open(loc):
        return True

    if loc.open_time <= loc.close_time:
        return loc.open_time <= current_hour < loc.close_time
    return current_hour >= loc.open_time or current_hour < loc.close_time


def _seconds_until_close(loc, current_time: float) -> float:
    if not loc:
        return float("inf")

    if _is_always_open(loc):
        return float("inf")

    current_day_seconds = current_time % 86400
    close_seconds = loc.close_time * 3600.0
    open_seconds = loc.open_time * 3600.0

    if loc.open_time <= loc.close_time:
        return max(0.0, close_seconds - current_day_seconds)

    if current_day_seconds >= open_seconds:
        return (24 * 3600.0) - current_day_seconds + close_seconds
    if current_day_seconds < close_seconds:
        return close_seconds - current_day_seconds
    return 0.0


def _has_item(agent, item_name: str) -> int:
    for i, it in enumerate(agent.inventory):
        if it["item"].lower() == item_name.lower():
            return i
    return -1


def _is_busy(target_agent, current_time: float) -> bool:
    if not target_agent.alive:
        return True
    if target_agent.is_sleeping:
        return True
    if target_agent.task_state != "idle":
        return True
    if target_agent.busy_until > current_time and target_agent.current_activity != "idle":
        return True
    return False


def _validate_shares(raw) -> tuple:
    try:
        val = float(raw)
        if not val.is_integer():
            return 0, "Shares must be a whole number."
        shares = int(val)
        if shares <= 0:
            return 0, "Shares must be > 0."
        return shares, None
    except (ValueError, TypeError):
        return 0, "Invalid number of shares."


def _record_expense(agent, amount: float) -> None:
    if amount <= 0:
        return
    agent.expenses += amount
    agent.total_expenses += amount


def _social_bump(a, b=None, amount: float = 0.2) -> None:
    a.relationships = min(25.0, a.relationships + amount)
    if b is not None:
        b.relationships = min(25.0, b.relationships + amount * 0.75)


def _social_penalty(a, b=None, amount: float = 0.5) -> None:
    a.relationships = max(0.0, a.relationships - amount * 0.2)
    if b is not None:
        b.relationships = max(0.0, b.relationships - amount)


def _clear_task_state(agent, reset_activity: bool = True) -> None:
    if agent.currently_holding and agent.currently_holding.get("id") == "job_prop":
        agent.currently_holding = None
    agent.task_state = "idle"
    agent.pending_task_data = {}
    if reset_activity and not agent.is_sleeping:
        agent.current_activity = "idle"


def _task_failure(agent, message: str, cost: int = 60) -> tuple:
    task_failures = int(agent.pending_task_data.get("task_failures", 0)) + 1
    agent.pending_task_data["task_failures"] = task_failures

    if task_failures >= 3:
        _clear_task_state(agent)
        return (
            f"{message} Task cancelled after 3 failed attempts. You may start over.",
            False,
            cost,
        )
    return (f"{message} Failed attempts in this task: {task_failures}/3.", False, cost)


def _find_agent_by_name(world, name: str):
    return next((a for a in world.agents.values() if a.name.lower() == name.lower()), None)


def _can_physically_reach_person(agent, target, max_distance: float) -> Tuple[bool, str]:
    d = get_distance_3d((agent.x, agent.y, agent.z), (target.x, target.y, target.z))
    if d > max_distance:
        return False, "Too far."

    agent_loc = get_current_location_def(agent.x, agent.y, agent.z)
    target_loc = get_current_location_def(target.x, target.y, target.z)

    if agent_loc or target_loc:
        if not agent_loc or not target_loc:
            return False, "You must be on the same floor nearby."
        if agent_loc.name != target_loc.name:
            return False, "You must be on the same floor nearby."
        if abs(agent.z - target.z) > OBJECT_Z_TOLERANCE:
            return False, "You must be on the same floor nearby."

    return True, ""


def _normalize_label(text: str) -> str:
    text = str(text or "").strip()
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def _canonicalize_from_names(raw: str, names) -> Optional[str]:
    cleaned = str(raw or "").strip()
    cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", cleaned).strip()
    cleaned = re.sub(r"^(village_stock:|village stock:|store:|stock:)", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"^store[_\s]+", "", cleaned, flags=re.I).strip()
    normalized = _normalize_label(cleaned)

    for name in names:
        if _normalize_label(name) == normalized:
            return name
    return None


def _canonicalize_item_name(raw_name: str, categories=None) -> str:
    categories = categories or ITEM_CATALOG.keys()
    names = []
    for category in categories:
        names.extend(ITEM_CATALOG[category].keys())
    return _canonicalize_from_names(raw_name, names) or str(raw_name).strip()


def _canonicalize_food_name(raw_name: str) -> str:
    return _canonicalize_from_names(raw_name, ITEM_CATALOG["food"].keys()) or str(raw_name).strip()


def _canonicalize_place_name(raw_place: str, world) -> str:
    raw_place = str(raw_place or "").strip()
    if not raw_place:
        return raw_place

    if _normalize_label(raw_place) in ("home", "house"):
        return "home"

    if _normalize_label(raw_place).startswith("home "):
        suffix = re.sub(r"^\s*home[_\s]+", "", raw_place, flags=re.I).strip()
        owner = _find_agent_by_name(world, suffix)
        if owner:
            return f"Home_{owner.name}"

    loc_match = _canonicalize_from_names(raw_place, [loc.name for loc in LOCATIONS_3D])
    if loc_match:
        return loc_match

    return raw_place


def _resolve_home_alias(place: str, world) -> Tuple[Optional[str], Optional[object]]:
    if place.lower() in ("home", "house"):
        return None, None

    if place.lower().startswith("home_"):
        owner_name = place.split("_", 1)[1]
        owner = _find_agent_by_name(world, owner_name)
        if owner:
            return owner.home_location, owner
    return None, None


def _resolve_destination(place: str, agent, world):
    raw_place = str(place or "").strip()
    raw_place = re.sub(r"\s*\([^)]*\)\s*$", "", raw_place).strip()

    if not raw_place:
        return None, None, "Unknown place."

    if raw_place.lower() in ("home", "house"):
        target_loc = get_location_by_name(agent.home_location)
        return target_loc, agent, None

    alias_loc_name, home_owner = _resolve_home_alias(raw_place, world)
    if alias_loc_name:
        target_loc = get_location_by_name(alias_loc_name)
        return target_loc, home_owner, None

    target_loc = get_location_by_name(raw_place)
    if target_loc:
        owner = next((a for a in world.agents.values() if a.home_location == target_loc.name), None)
        return target_loc, owner, None

    return None, None, f"Unknown place: '{raw_place}'."


def _set_agent_to_location(agent, loc) -> None:
    center = get_location_center(loc)
    agent.x = center[0]
    agent.y = center[1]
    agent.z = center[2]
    agent.location = loc.name


def _store_currently_holding_if_possible(agent) -> Tuple[bool, Optional[str]]:
    if not agent.currently_holding:
        return True, None

    if agent.currently_holding.get("id") == "job_prop":
        return False, "You are holding a required task prop."

    if len(agent.inventory) >= MAX_INVENTORY:
        return False, "You are already holding an object, and your inventory is full. Dropping is recommended."

    agent.inventory.append(agent.currently_holding)
    agent.currently_holding = None
    return True, None


def _find_ground_item(world, agent, item_name: str):
    item_name = item_name.lower()
    for gi in world.ground_items:
        if gi["item"].lower() != item_name:
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
        for it in estate["items"]:
            if it["item"].lower() == item_name:
                return estate, it
    return None, None


def _remove_empty_estates(world):
    world.corpse_estates = [
        e for e in world.corpse_estates if e.get("money", 0.0) > 0 or e.get("items")
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
        if available_space > 0 and estate["items"]:
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
                f"You found these items from a dead body: {item_list}. "
                f"Cash recovered: ${taken_money:.2f}. These have been stored to your inventory where possible."
            )

    _remove_empty_estates(world)


def _resolve_workplace_name(job_raw: str, agent) -> Optional[str]:
    lowered = (job_raw or "").lower().strip()
    for key, loc_name in WORKPLACE_BY_JOB.items():
        if key in lowered:
            return loc_name

    fallback = (agent.job or "").lower()
    for key, loc_name in WORKPLACE_BY_JOB.items():
        if key in fallback:
            return loc_name

    return None


def _match_job_flavor(job_raw: str, mode: str) -> Dict:
    if mode == "get_education":
        return JOB_FLAVORS["education"]

    lowered = (job_raw or "").lower()
    for key, val in JOB_FLAVORS.items():
        if key in lowered:
            return val
    return JOB_FLAVORS["generic"]


def _nearest_named_location_within(agent, names, max_distance: float):
    best = None
    best_dist = None

    for name in names:
        loc = get_location_by_name(name)
        if not loc:
            continue
        center = get_location_center(loc)
        d = get_distance_3d((agent.x, agent.y, agent.z), center)
        if d <= max_distance and (best is None or d < best_dist):
            best = loc
            best_dist = d

    return best, best_dist


def _liquidate_portfolio(agent, world) -> float:
    if agent.shares_owned <= 0:
        return 0.0
    proceeds = agent.shares_owned * world.market_price
    agent.money += proceeds
    agent.shares_owned = 0
    agent.last_known_price = 0.0
    return proceeds


def _delete_agent_cache(agent_id: int) -> None:
    cache_path = os.path.join(CACHE_DIR, f"agent_{agent_id}.bin")
    try:
        if os.path.exists(cache_path):
            os.remove(cache_path)
    except OSError:
        pass


def _kill_agent(target, world, cause: str = "unknown") -> None:
    if not target.alive:
        return

    if target.currently_holding and target.currently_holding.get("id") != "job_prop":
        target.inventory.append(target.currently_holding)
    target.currently_holding = None

    liquidated = _liquidate_portfolio(target, world)

    pre_death_state = {
        "health": round(target.health, 2),
        "energy": round(target.energy, 2),
        "happiness": round(target.happiness, 2),
        "stress": round(target.stress, 2),
        "hunger": round(target.hunger, 2),
        "money": round(target.money, 2),
        "location": target.location,
        "x": round(target.x, 2),
        "y": round(target.y, 2),
        "z": round(target.z, 2),
        "inventory": [deepcopy(i) for i in target.inventory],
        "currently_holding": None,
        "current_home_type": target.current_home_type,
        "home_location": target.home_location,
        "job": target.job,
        "beliefs": target.beliefs,
    }

    estate = {
        "id": str(uuid.uuid4()),
        "source_agent_id": target.id,
        "source_agent_name": target.name,
        "x": target.x,
        "y": target.y,
        "z": target.z,
        "money": round(target.money, 2),
        "items": [deepcopy(i) for i in target.inventory],
    }

    world.corpse_estates.append(estate)

    if target.current_home_type and target.home_location:
        world.release_home_lot(target.current_home_type, target.home_location)

    target.owned_locations = []
    target.current_home_type = ""
    target.home_location = ""

    target.inventory.clear()
    target.money = 0.0
    target.pending_market_orders.clear()
    target.alive = False
    target.is_sleeping = False
    target.current_activity = "dead"
    target.task_state = "idle"
    target.pending_task_data = {}

    _delete_agent_cache(target.id)
    log_death(
        target,
        cause=cause,
        estate=estate,
        shares_liquidated=liquidated,
        pre_death_state=pre_death_state,
    )


def _find_catalog_entry(item_name: str):
    for category, items in ITEM_CATALOG.items():
        if item_name in items:
            return category, items[item_name]
    return None, None


def execute_tool(tool_call_str: str, agent_id: int, world: WorldState) -> tuple:
    name, args = parse_tool_call(tool_call_str)

    agent = world.agents.get(agent_id)
    if not agent:
        return "Agent not found.", False, 0
    if not agent.alive:
        return "Agent inactive.", False, 0

    if agent.is_sleeping and world.sim_time >= agent.busy_until:
        agent.is_sleeping = False
        if agent.task_state == "idle":
            agent.current_activity = "idle"

    try_auto_collect_loot(agent, world)

    if isinstance(name, str) and name.startswith("Parse error"):
        agent.last_parse_error = True
        agent.failed_calls += 1
        return name, False, 60

    agent.last_parse_error = False

    if not name:
        agent.failed_calls += 1
        return "Parse error: No tool name.", False, 60

    if agent.task_state != "idle" and name not in ["interact_with", "pick_item", "drop_item"]:
        agent.failed_calls += 1
        return _task_failure(
            agent,
            "You are in the middle of a task. You must follow the required next step.",
            60,
        )

    time_cost = 300

    if name == "sleep":
        try:
            hours = float(args.get("hours", 8))
        except (ValueError, TypeError):
            hours = 8.0

        hours = max(1.0, min(12.0, hours))
        time_cost = int(hours * 3600)

        loc_def = get_current_location_def(agent.x, agent.y, agent.z)
        is_home = bool(loc_def and loc_def.name == agent.home_location)

        agent.awake_hours = 0
        agent.is_sleeping = True
        agent.current_activity = "sleeping"

        energy_gain = hours * 10.0
        if is_home:
            agent.energy = min(100.0, agent.energy + energy_gain)
        else:
            agent.energy = max(agent.energy, min(60.0, agent.energy + energy_gain))

        agent.stress = max(0.0, agent.stress - (hours * 2.0))
        msg = f"Slept {hours:.1f}h. Energy: {agent.energy:.1f}. Do Not Disturb active."
        if not is_home:
            msg += " (Poor sleep outside home: recovery capped at 60%)."
        return msg, True, time_cost

    if name == "move_to":
        place = _canonicalize_place_name(str(args.get("place", ""))[:100], world)
        target_loc, home_owner, err = _resolve_destination(place, agent, world)
        if err:
            agent.failed_calls += 1
            return err, False, 60
        if not target_loc:
            agent.failed_calls += 1
            return "Unknown place.", False, 60

        if home_owner and home_owner.id != agent.id:
            owner_loc = get_current_location_def(home_owner.x, home_owner.y, home_owner.z)
            if not owner_loc or owner_loc.name != home_owner.home_location:
                agent.failed_calls += 1
                return f"{home_owner.name} is not home. Door is locked.", False, 60

        if not _check_open_hours(target_loc, world.sim_time):
            agent.failed_calls += 1
            return f"{target_loc.name} is currently closed.", False, 60

        target_coords = get_location_center(target_loc)
        dist = get_distance_3d((agent.x, agent.y, agent.z), target_coords)
        energy_drain = dist * 0.005
        time_cost = max(60, int(dist / 1.5))
        arrival_time = world.sim_time + time_cost

        if not _check_open_hours(target_loc, arrival_time):
            agent.failed_calls += 1
            return (
                f"{target_loc.name} would be closed by the time you arrive. "
                f"Try going earlier."
            ), False, 60

        if agent.energy < energy_drain:
            agent.failed_calls += 1
            return f"Too exhausted to travel {dist:.0f}m. Need {energy_drain:.1f} Energy.", False, 60

        agent.energy -= energy_drain
        _set_agent_to_location(agent, target_loc)
        agent.current_activity = "moving"

        if is_home_location(target_loc.name):
            if home_owner and home_owner.id == agent.id:
                label = f"Home_{agent.name} ({describe_home_location(target_loc.name)})"
            elif home_owner:
                label = f"Home_{home_owner.name} ({describe_home_location(target_loc.name)})"
            else:
                label = describe_home_location(target_loc.name)
        else:
            label = target_loc.name

        return f"Travelled to {label} (-{energy_drain:.1f} Energy).", True, time_cost

    if name == "walk":
        direction = str(args.get("direction", "")).strip().lower()
        delta_map = {
            "north": (0, 30),
            "south": (0, -30),
            "east": (30, 0),
            "west": (-30, 0),
            "northeast": (21, 21),
            "northwest": (-21, 21),
            "southeast": (21, -21),
            "southwest": (-21, -21),
        }
        delta = delta_map.get(direction)
        if not delta:
            agent.failed_calls += 1
            return "Invalid direction.", False, 60

        new_x = max(0.0, min(5000.0, agent.x + delta[0]))
        new_y = max(0.0, min(5000.0, agent.y + delta[1]))
        current_loc = get_current_location_def(agent.x, agent.y, agent.z)
        new_loc = get_current_location_def(new_x, new_y, agent.z)

        if agent.z > 0.0 and new_loc is None:
            agent.failed_calls += 1
            return (
                "Oops, you were about to fall from the building. Be careful next time. "
                "There are doors on the ground floor.",
                False,
                60,
            )

        if new_loc and not _check_open_hours(new_loc, world.sim_time):
            agent.failed_calls += 1
            return f"{new_loc.name} is currently closed.", False, 60

        agent.x = new_x
        agent.y = new_y
        agent.location = new_loc.name if new_loc else "Outside"
        agent.current_activity = "moving"

        if current_loc and new_loc and current_loc.name != new_loc.name:
            return f"Walked {direction}. You entered {new_loc.name}.", True, 60
        return f"Walked {direction}. Location updated to: {agent.location}.", True, 60

    if name == "pick_item":
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

        item = _canonicalize_item_name(raw_item)

        if agent.task_state == "job_pick":
            flavor = agent.pending_task_data["flavor"]
            required = flavor["pick"]
            if item.lower() != required.lower():
                agent.failed_calls += 1
                return _task_failure(agent, f"You need to pick_item '{required}' to do this task.", 30)

            ok, why = _store_currently_holding_if_possible(agent)
            if not ok:
                agent.failed_calls += 1
                return why, False, 30

            agent.currently_holding = {"id": "job_prop", "item": required, "durability": 99}
            agent.task_state = "job_mcq"
            return (
                f"[WORK] You grab the {required}. Scenario: {flavor['q']} "
                f"Use interact_with(person_or_object='{flavor['obj']}', action='A, B, or C').",
                True,
                60,
            )

        idx = _has_item(agent, item)
        if idx != -1:
            if agent.currently_holding:
                ok, why = _store_currently_holding_if_possible(agent)
                if not ok:
                    agent.failed_calls += 1
                    return why, False, 30
            agent.currently_holding = agent.inventory.pop(idx)
            return f"Now holding {item} in hand.", True, 30

        ground_item = _find_ground_item(world, agent, item)
        if ground_item:
            if (
                ground_item.get("dropper_id") == agent.id
                and world.sim_time < ground_item.get("repickup_block_until", 0.0)
            ):
                agent.failed_calls += 1
                return "You cannot re-pick your own dropped item yet. Wait a bit longer.", False, 30

            if agent.currently_holding:
                ok, why = _store_currently_holding_if_possible(agent)
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

        estate, estate_item = _find_corpse_item(world, agent, item)
        if estate and estate_item:
            if agent.currently_holding:
                ok, why = _store_currently_holding_if_possible(agent)
                if not ok:
                    agent.failed_calls += 1
                    return why, False, 30

            agent.currently_holding = deepcopy(estate_item)
            estate["items"].remove(estate_item)
            _remove_empty_estates(world)
            return f"Recovered {item} from {estate['source_agent_name']}'s remains.", True, 30

        agent.failed_calls += 1
        return f"Item {item} not in inventory or nearby.", False, 60

    if name == "drop_item":
        item = _canonicalize_item_name(str(args.get("item_name", "")).strip())
        item_data = None

        if agent.currently_holding and (not item or item.lower() == agent.currently_holding["item"].lower()):
            if agent.currently_holding.get("id") == "job_prop":
                agent.failed_calls += 1
                return "Do not drop the required task prop. Finish or cancel the task first.", False, 30
            item_data = agent.currently_holding
            agent.currently_holding = None
        else:
            idx = _has_item(agent, item)
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
                "x": agent.x,
                "y": agent.y,
                "z": agent.z,
                "dropper_id": agent.id,
                "repickup_block_until": world.sim_time + DROP_REPICKUP_COOLDOWN,
            }
        )
        return f"Dropped {item_data['item']} on the ground.", True, 30

    if name in ["work_job", "get_education"]:
        if agent.task_state != "idle":
            agent.failed_calls += 1
            return "Already doing a task.", False, 60

        if name == "work_job":
            job_raw = str(args.get("jobname", agent.job or "generic")).strip() or (agent.job or "generic")
        else:
            job_raw = str(args.get("type", "education")).strip() or "education"

        try:
            hours = float(args.get("hours", 8))
        except (ValueError, TypeError):
            hours = 8.0
        hours = max(1.0, min(12.0, hours))

        required_energy = hours * 10.0
        if agent.energy < required_energy:
            agent.failed_calls += 1
            return f"Need {required_energy:.1f} energy to spend {hours:.1f}h on this task. Have {agent.energy:.1f}.", False, 60

        if name == "work_job":
            workplace_name = _resolve_workplace_name(job_raw, agent)
            if workplace_name:
                workplace = get_location_by_name(workplace_name)
                center = get_location_center(workplace)
                d = get_distance_3d((agent.x, agent.y, agent.z), center)
                if d > WORKPLACE_MAX_DISTANCE:
                    agent.failed_calls += 1
                    return (
                        f"You must be within {WORKPLACE_MAX_DISTANCE:.0f}m of {workplace_name} to work there. "
                        f"Move there first with move_to(place='{workplace_name}').",
                        False,
                        60,
                    )
                if not _check_open_hours(workplace, world.sim_time):
                    agent.failed_calls += 1
                    return (
                        f"{workplace_name} is currently closed. Move there first and try again during open hours.",
                        False,
                        60,
                    )
                remaining = _seconds_until_close(workplace, world.sim_time)
                if hours * 3600.0 > remaining:
                    agent.failed_calls += 1
                    return (
                        f"{workplace_name} closes in {remaining / 3600.0:.1f}h. "
                        f"Reduce requested work time to {max(0.0, remaining / 3600.0):.1f}h or less.",
                        False,
                        60,
                    )
            else:
                workplace_name = "Generic_Workplace"

            matched_flavor = _match_job_flavor(job_raw, name)
            agent.task_state = "job_pick"
            agent.current_activity = "working"
            agent.pending_task_data = {
                "type": name,
                "hours": hours,
                "job_raw": job_raw,
                "workplace": workplace_name,
                "flavor": matched_flavor,
                "task_failures": 0,
            }
            return (
                f"[SCENARIO INITIATED] Shift started as {job_raw} near {workplace_name}. "
                f"To begin, use pick_item(item_name='{matched_flavor['pick']}').",
                True,
                60,
            )

        edu_loc, _ = _nearest_named_location_within(agent, EDUCATION_LOCATIONS, WORKPLACE_MAX_DISTANCE)
        if not edu_loc:
            agent.failed_calls += 1
            return (
                "You must be within 150m of School or Library to study. "
                "Move there first with move_to(place='School') or move_to(place='Library').",
                False,
                60,
            )

        if not _check_open_hours(edu_loc, world.sim_time):
            agent.failed_calls += 1
            return f"{edu_loc.name} is currently closed.", False, 60

        remaining = _seconds_until_close(edu_loc, world.sim_time)
        if hours * 3600.0 > remaining:
            agent.failed_calls += 1
            return (
                f"{edu_loc.name} closes in {remaining / 3600.0:.1f}h. "
                f"Reduce requested study time to {max(0.0, remaining / 3600.0):.1f}h or less.",
                False,
                60,
            )

        lowered = job_raw.lower()
        tuition = 2000.0
        if "phd" in lowered or "doctorate" in lowered:
            tuition = 8000.0
        elif "master" in lowered:
            tuition = 4000.0

        if agent.money < tuition:
            agent.failed_calls += 1
            return f"Cannot afford tuition (${tuition:.2f}).", False, 60

        agent.money -= tuition
        _record_expense(agent, tuition)
        agent.pending_notifications.append(f"Paid ${tuition:.2f} in tuition fees.")

        matched_flavor = JOB_FLAVORS["education"]
        agent.task_state = "job_pick"
        agent.current_activity = "studying"
        agent.pending_task_data = {
            "type": name,
            "hours": hours,
            "job_raw": job_raw,
            "workplace": edu_loc.name,
            "flavor": matched_flavor,
            "task_failures": 0,
        }
        return (
            f"[SCENARIO INITIATED] Study session started for {job_raw} near {edu_loc.name}. "
            f"To begin, use pick_item(item_name='{matched_flavor['pick']}').",
            True,
            60,
        )

    if name == "interact_with":
        target = str(args.get("person_or_object", "")).strip()
        action = str(args.get("action", "")).strip()

        if agent.task_state == "job_mcq":
            flavor = agent.pending_task_data["flavor"]
            required_target = flavor["obj"]

            if target.lower() != required_target.lower():
                agent.failed_calls += 1
                return _task_failure(agent, f"You must interact_with '{required_target}' to complete the task.", 60)

            data = dict(agent.pending_task_data)
            if agent.currently_holding and agent.currently_holding.get("id") == "job_prop":
                agent.currently_holding = None

            busy_activity = "studying" if data["type"] == "get_education" else "working"
            _clear_task_state(agent, reset_activity=False)
            agent.current_activity = busy_activity

            time_cost = int(data["hours"] * 3600)
            agent.energy = max(0.0, agent.energy - data["hours"] * 10.0)
            correct = flavor["ans"].lower() in action.lower()

            if data["type"] == "get_education":
                edu_gain = 5.0 if correct else 1.0
                wage_gain = 5.0 if correct else 1.0
                agent.education = min(100.0, agent.education + edu_gain)
                agent.hourly_wage += wage_gain
                return (
                    f"Exam finished. Correct? {correct}. Education +{edu_gain:.1f}, Wage +{wage_gain:.1f}. "
                    f"Time passed: {data['hours']:.1f}h. DND active.",
                    True,
                    time_cost,
                )

            pay = agent.hourly_wage * data["hours"] * (world.market_price / 100.0)
            if not correct:
                pay *= 0.5
            agent.money += pay
            return (
                f"Task resolved. Success? {correct}. Earned ${pay:.2f}. "
                f"Time passed: {data['hours']:.1f}h. DND active.",
                True,
                time_cost,
            )

        if agent.task_state == "job_pick":
            agent.failed_calls += 1
            return _task_failure(agent, "You need to pick up the required task item first.", 60)

        target_agent = next(
            (a for a in world.agents.values() if a.name.lower() == target.lower() and a.alive),
            None,
        )
        if target_agent:
            if _is_busy(target_agent, world.sim_time):
                agent.failed_calls += 1
                return f"{target_agent.name} is currently busy/sleeping (DND).", False, 60

            ok, reason = _can_physically_reach_person(agent, target_agent, 20.0)
            if not ok:
                agent.failed_calls += 1
                return reason, False, 60

            _social_bump(agent, target_agent, 0.15)
            target_agent.pending_notifications.append(f"{agent.name} interacted with you ({action}).")
            return f"Interacted with {target_agent.name}.", True, 60

        loc = get_current_location_def(agent.x, agent.y, agent.z)
        if loc:
            for obj in loc.interactables:
                if obj["name"].lower() != target.lower():
                    continue
                if abs(float(obj.get("z", 0.0)) - agent.z) > OBJECT_Z_TOLERANCE:
                    continue

                if "target_z" in obj:
                    agent.z = float(obj["target_z"])
                    return f"Used {target}. Moved to floor Z={agent.z}.", True, 60
                return f"Used {target} ({action}).", True, 60

        agent.failed_calls += 1
        return f"No nearby visible object named '{target}' found on your current floor.", False, 60

    if name == "change_status":
        value = str(args.get("value", "")).strip()
        person = str(args.get("person", "")).strip()
        rel_type = str(args.get("type", "")).strip().lower()

        if value:
            agent.beliefs = value
            return f'Belief/Goal updated to: "{value}".', True, 30

        if person and rel_type:
            target = next((a for a in world.agents.values() if a.name.lower() == person.lower() and a.alive), None)
            if not target:
                agent.failed_calls += 1
                return f"Person '{person}' not found.", False, 60

            if _is_busy(target, world.sim_time):
                agent.failed_calls += 1
                return f"{target.name} is busy (DND).", False, 60

            ok, reason = _can_physically_reach_person(agent, target, STATUS_MAX_DISTANCE)
            if not ok:
                agent.failed_calls += 1
                if reason == "Too far.":
                    return f"You must be within {STATUS_MAX_DISTANCE:.0f}m to change relationship status.", False, 60
                return f"You must be within {STATUS_MAX_DISTANCE:.0f}m on the same floor to change relationship status.", False, 60

            req_key = person.lower()
            if agent.pending_status_requests.get(req_key) == rel_type:
                if rel_type == "single":
                    agent.relationship_partner = ""
                    target.relationship_partner = ""
                else:
                    agent.relationship_partner = target.name
                    target.relationship_partner = agent.name

                agent.relationships_status = rel_type
                target.relationships_status = rel_type
                del agent.pending_status_requests[req_key]
                _social_bump(agent, target, 0.4)
                target.pending_notifications.append(f"{agent.name} accepted status: {rel_type}.")
                return f"Status with {person} changed to: {rel_type}.", True, 30

            target.pending_status_requests[agent.name.lower()] = rel_type
            target.pending_notifications.append(f"{agent.name} wants status: {rel_type}.")
            return f"Requested status change to '{rel_type}' with {person}.", True, 30

        agent.failed_calls += 1
        return "Invalid parameters.", False, 60

    if name == "attack_person":
        t_name = str(args.get("person", "")).strip()
        target = next((a for a in world.agents.values() if a.name.lower() == t_name.lower() and a.alive), None)
        if not target:
            agent.failed_calls += 1
            return "Target not found.", False, 60

        if _is_busy(target, world.sim_time):
            agent.failed_calls += 1
            return f"{target.name} is securely locked away working or sleeping. Cannot attack.", False, 60

        ok, reason = _can_physically_reach_person(agent, target, 20.0)
        if not ok:
            agent.failed_calls += 1
            return reason, False, 60

        damage = random.uniform(5.0, 25.0)
        target.health -= damage
        target.stress = min(100.0, target.stress + 15.0)
        _social_penalty(agent, target, 0.8)
        target.pending_notifications.append(f"URGENT: {agent.name} attacked you!")

        if target.health <= 0.0:
            _kill_agent(target, world, cause=f"killed by {agent.name}")
            return f"Killed {t_name}.", True, 60

        return f"Attacked {t_name} for {damage:.1f} damage.", True, 60

    if name == "talk_to":
        t_name = str(args.get("person", "")).strip()
        msg = str(args.get("message", "")).strip()
        target = next((a for a in world.agents.values() if a.name.lower() == t_name.lower() and a.alive), None)
        if not target:
            agent.failed_calls += 1
            return "Target not found.", False, 60

        if _is_busy(target, world.sim_time):
            agent.failed_calls += 1
            return f"{target.name} is currently working or sleeping (DND).", False, 60

        ok, reason = _can_physically_reach_person(agent, target, 50.0)
        if not ok:
            agent.failed_calls += 1
            return "Cannot reach target." if reason == "Too far." else reason, False, 60

        _social_bump(agent, target, 0.2)
        agent.social_fulfillment = min(100.0, agent.social_fulfillment + 10.0)
        target.pending_notifications.append(f"{agent.name} said: {msg}")

        for other in world.agents.values():
            if not other.alive or other.id in (agent.id, target.id):
                continue
            if _is_busy(other, world.sim_time):
                continue

            ok, _ = _can_physically_reach_person(agent, other, 50.0)
            if ok:
                other.pending_notifications.append(f"Overheard {agent.name} say to {t_name}: '{msg}'")

        return f"Talked to {t_name}.", True, 60

    if name == "call_person":
        t_name = str(args.get("person", "")).strip()
        msg = str(args.get("message", "")).strip()
        target = next((a for a in world.agents.values() if a.name.lower() == t_name.lower() and a.alive), None)
        if not target:
            agent.failed_calls += 1
            return "Target not found.", False, 60

        if _is_busy(target, world.sim_time):
            agent.failed_calls += 1
            return f"Call to {target.name} went straight to voicemail (DND).", False, 60

        _social_bump(agent, target, 0.1)
        target.pending_notifications.append(f"Phone Call from {agent.name}: {msg}")
        return f"Called {t_name}.", True, 60

    if name == "give_item":
        t_name = str(args.get("person", "")).strip()
        item_name = _canonicalize_item_name(str(args.get("item", "")).strip())
        target = next((a for a in world.agents.values() if a.name.lower() == t_name.lower() and a.alive), None)

        if not target:
            agent.failed_calls += 1
            return "Target not found.", False, 60

        if _is_busy(target, world.sim_time):
            agent.failed_calls += 1
            return f"{target.name} is busy (DND).", False, 60

        ok, reason = _can_physically_reach_person(agent, target, 20.0)
        if not ok:
            agent.failed_calls += 1
            return reason, False, 60

        if len(target.inventory) >= MAX_INVENTORY:
            agent.failed_calls += 1
            return f"{target.name}'s inventory is full.", False, 60

        item_data = None
        if agent.currently_holding and agent.currently_holding["item"].lower() == item_name.lower():
            item_data = agent.currently_holding
            agent.currently_holding = None
        else:
            idx = _has_item(agent, item_name)
            if idx != -1:
                item_data = agent.inventory.pop(idx)

        if not item_data:
            agent.failed_calls += 1
            return f"You don't have {item_name} in your hand or inventory.", False, 60

        target.inventory.append(item_data)
        _social_bump(agent, target, 0.25)
        agent.social_fulfillment = min(100.0, agent.social_fulfillment + 15.0)
        target.pending_notifications.append(f"{agent.name} gave you {item_name}.")
        return f"Gave {item_name} to {t_name}.", True, 60

    if name == "give_money":
        t_name = str(args.get("person", "")).strip()
        try:
            amount = float(args.get("amount", 0))
        except (ValueError, TypeError):
            amount = 0.0

        if amount <= 0:
            agent.failed_calls += 1
            return "Invalid amount.", False, 60

        if agent.money < amount:
            agent.failed_calls += 1
            return "Not enough money.", False, 60

        target = next((a for a in world.agents.values() if a.name.lower() == t_name.lower() and a.alive), None)
        if not target:
            agent.failed_calls += 1
            return "Target not found.", False, 60

        if _is_busy(target, world.sim_time):
            agent.failed_calls += 1
            return f"{target.name} is busy (DND).", False, 60

        ok, reason = _can_physically_reach_person(agent, target, 20.0)
        if not ok:
            agent.failed_calls += 1
            return reason, False, 60

        agent.money -= amount
        target.money += amount
        _social_bump(agent, target, 0.2)
        agent.social_fulfillment = min(100.0, agent.social_fulfillment + 15.0)
        target.pending_notifications.append(f"{agent.name} gave you ${amount:.2f}.")
        return f"Gave ${amount:.2f} to {t_name}.", True, 60

    if name == "buy_item":
        item = _canonicalize_item_name(str(args.get("item", "")).strip()[:100])

        if item in ITEM_CATALOG["housing"]:
            if item == agent.current_home_type:
                agent.failed_calls += 1
                return "You seem to already own this type of house.", False, 60

            price = ITEM_CATALOG["housing"][item]
            old_home_type = agent.current_home_type
            old_home_location = agent.home_location
            old_price = ITEM_CATALOG["housing"].get(old_home_type, 0.0)
            sell_price = old_price * 0.7 if old_home_type else 0.0

            if (agent.money + sell_price) < price:
                agent.failed_calls += 1
                return (
                    f"Cannot afford {item}. Need ${price:.2f}, have ${agent.money:.2f} "
                    f"+ ${sell_price:.2f} in home equity.",
                    False,
                    60,
                )

            new_home_location = world.allocate_home_lot(item)
            if not new_home_location:
                agent.failed_calls += 1
                return f"No vacant {item} lots are currently available.", False, 60

            if old_home_type and old_home_location:
                world.release_home_lot(old_home_type, old_home_location)

            agent.money += sell_price
            agent.money -= price
            _record_expense(agent, price)

            agent.current_home_type = item
            agent.home_location = new_home_location
            agent.owned_locations = [new_home_location]

            loc_def = get_location_by_name(new_home_location)
            if loc_def:
                _set_agent_to_location(agent, loc_def)

            return (
                f"Sold {old_home_type or 'previous home'} for ${sell_price:.2f}. "
                f"Bought {item} for ${price:.2f}. "
                f"New home: Home_{agent.name} ({describe_home_location(new_home_location)}).",
                True,
                3600,
            )

        category, entry = _find_catalog_entry(item)
        if category is None or category == "housing":
            agent.failed_calls += 1
            valid_buy_names = (
                list(ITEM_CATALOG["food"].keys())
                + list(ITEM_CATALOG["everyday"].keys())
                + list(ITEM_CATALOG["health"].keys())
                + list(ITEM_CATALOG["housing"].keys())
            )
            return (
                f"Item '{item}' not found. Valid purchasable item names: {', '.join(valid_buy_names)}.",
                False,
                60,
            )

        if len(agent.inventory) >= MAX_INVENTORY:
            agent.failed_calls += 1
            return "Inventory full.", False, 60

        if world.store_inventory.get(item, 0) <= 0:
            agent.failed_calls += 1
            return f"'{item}' is completely out of stock in the village.", False, 60

        price = entry["price"] if isinstance(entry, dict) else entry
        if agent.money < price:
            agent.failed_calls += 1
            return "Cannot afford.", False, 60

        agent.money -= price
        _record_expense(agent, price)
        world.store_inventory[item] -= 1
        agent.inventory.append(
            {
                "id": str(uuid.uuid4()),
                "item": item,
                "durability": 5,
                "bought": world.sim_time,
            }
        )
        return f"Bought {item} for ${price:.2f}.", True, 120

    if name == "eat_food":
        item = _canonicalize_food_name(str(args.get("item", "")).strip()[:100])
        food_data = None

        if agent.currently_holding and agent.currently_holding["item"].lower() == item.lower():
            if item not in ITEM_CATALOG["food"]:
                agent.failed_calls += 1
                return f"{item} is not edible food.", False, 60
            food_data = agent.currently_holding
            agent.currently_holding = None
        else:
            idx = _has_item(agent, item)
            if idx != -1:
                if item not in ITEM_CATALOG["food"]:
                    agent.failed_calls += 1
                    return f"{item} is not edible food.", False, 60
                food_data = agent.inventory.pop(idx)

        if food_data:
            if world.sim_time - food_data.get("bought", world.sim_time) > 172800:
                agent.health = max(0.0, agent.health - 10.0)
                return "The food was spoiled! Health -10.", True, 60
        else:
            if item not in ITEM_CATALOG["food"]:
                agent.failed_calls += 1
                return (
                    f"Food not found. Valid exact food names: {', '.join(ITEM_CATALOG['food'].keys())}.",
                    False,
                    60,
                )

            if world.store_inventory.get(item, 0) <= 0:
                agent.failed_calls += 1
                return f"'{item}' is completely out of stock in the village.", False, 60

            cost = ITEM_CATALOG["food"][item]["price"]
            if agent.money < cost:
                agent.failed_calls += 1
                return "Cannot afford.", False, 60

            agent.money -= cost
            _record_expense(agent, cost)
            world.store_inventory[item] -= 1

        f_stats = ITEM_CATALOG["food"][item]
        agent.hunger = max(0.0, agent.hunger - f_stats["hunger"])
        agent.caffeine_level += f_stats["caffeine"]
        agent.health = min(100.0, agent.health + 2.0)
        agent.energy = min(100.0, agent.energy + 5.0)
        return f"Ate {item}. Hunger reduced. Health +2, Energy +5.", True, f_stats["time"]

    if name == "do_hobby":
        item = _canonicalize_item_name(str(args.get("item", "")).strip()[:100])
        item_data = None
        source = None

        if agent.currently_holding and agent.currently_holding["item"].lower() == item.lower():
            item_data = agent.currently_holding
            source = "hand"
        else:
            idx = _has_item(agent, item)
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

    if name == "buy_stock":
        shares, err = _validate_shares(args.get("shares", 0))
        if err:
            agent.failed_calls += 1
            return err, False, 60

        from utils import is_market_open

        if not is_market_open(world.sim_time):
            agent.pending_market_orders.append({"type": "buy", "shares": shares, "queued_at": world.sim_time})
            return f"Market closed. Buy order for {shares} shares queued.", True, 60

        cost = world.market_price * shares
        if agent.money < cost:
            agent.failed_calls += 1
            return "Cannot afford.", False, 60

        agent.money -= cost
        old_cost_basis = agent.last_known_price * agent.shares_owned
        agent.shares_owned += shares
        agent.last_known_price = (old_cost_basis + cost) / agent.shares_owned
        world.net_volume_this_period += shares
        return f"Bought {shares} share(s).", True, 60

    if name == "sell_stock":
        shares, err = _validate_shares(args.get("shares", 0))
        if err:
            agent.failed_calls += 1
            return err, False, 60

        if agent.shares_owned < shares:
            agent.failed_calls += 1
            return "Not enough shares.", False, 60

        from utils import is_market_open

        if not is_market_open(world.sim_time):
            agent.pending_market_orders.append({"type": "sell", "shares": shares, "queued_at": world.sim_time})
            return f"Market closed. Sell order for {shares} shares queued.", True, 60

        proceeds = world.market_price * shares
        agent.money += proceeds
        agent.shares_owned -= shares
        if agent.shares_owned == 0:
            agent.last_known_price = 0.0
        world.net_volume_this_period -= shares
        return f"Sold {shares} share(s).", True, 60

    if name == "seek_medicalcare":
        hospital = get_location_by_name("Hospital")
        center = get_location_center(hospital)
        d = get_distance_3d((agent.x, agent.y, agent.z), center)
        if d > WORKPLACE_MAX_DISTANCE:
            agent.failed_calls += 1
            return (
                "You must be within 150m of Hospital to seek medical care. "
                "Move there first with move_to(place='Hospital').",
                False,
                60,
            )

        if not _check_open_hours(hospital, world.sim_time):
            agent.failed_calls += 1
            return "Hospital is currently closed.", False, 60

        cost = 50.0
        if agent.money < cost:
            agent.failed_calls += 1
            return "Cannot afford medical care.", False, 60

        agent.money -= cost
        _record_expense(agent, cost)
        agent.health = min(100.0, agent.health + 30.0)
        return "Received medical care. Health +30.", True, 600

    agent.failed_calls += 1
    return f"Tool {name} not found.", False, 60
