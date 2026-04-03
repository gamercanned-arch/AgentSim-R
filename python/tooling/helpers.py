from __future__ import annotations

import re
from typing import Optional, Tuple

from python.config import MAX_INVENTORY, OBJECT_Z_TOLERANCE, STATUS_MAX_DISTANCE, WORKPLACE_MAX_DISTANCE
from python.locations import LOCATIONS_3D, get_current_location_def, get_distance_3d
from python.tooling.catalogs import ITEM_CATALOG, VEHICLE_CATALOG, WORKPLACE_BY_JOB

_WS_RE = re.compile(r"\s+")
_PARENS_TAIL_RE = re.compile(r"\s*\([^)]*\)\s*$")
_PREFIX_RE = re.compile(r"^(village_stock:|village stock:|store:|stock:)", flags=re.I)
_STORE_PREFIX_RE = re.compile(r"^store[_\s]+", flags=re.I)


def strip_wrapping_quotes(text: str) -> str:
    text = str(text or "").strip()
    pairs = [
        ("'", "'"),
        ('"', '"'),
        ("“", "”"),
        ("‘", "’"),
        ("`", "`"),
    ]
    changed = True
    while changed and len(text) >= 2:
        changed = False
        for left, right in pairs:
            if text.startswith(left) and text.endswith(right):
                text = text[1:-1].strip()
                changed = True
    return text


def normalize_label(text: str) -> str:
    text = strip_wrapping_quotes(str(text or "").strip())
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(_WS_RE, " ", text)
    return text.lower().strip()


def canonicalize_from_names(raw: str, names) -> Optional[str]:
    cleaned = strip_wrapping_quotes(str(raw or "").strip())
    cleaned = re.sub(_PARENS_TAIL_RE, "", cleaned).strip()
    cleaned = re.sub(_PREFIX_RE, "", cleaned).strip()
    cleaned = re.sub(_STORE_PREFIX_RE, "", cleaned).strip()
    cleaned = strip_wrapping_quotes(cleaned)
    normalized = normalize_label(cleaned)

    for name in names:
        if normalize_label(name) == normalized:
            return name
    return None


def canonicalize_item_name(raw_name: str, categories=None) -> str:
    raw_name = strip_wrapping_quotes(raw_name)
    categories = categories or ITEM_CATALOG.keys()
    names = []
    for category in categories:
        names.extend(ITEM_CATALOG[category].keys())
    names.extend(VEHICLE_CATALOG.keys())
    return canonicalize_from_names(raw_name, names) or strip_wrapping_quotes(str(raw_name).strip())


def canonicalize_food_name(raw_name: str) -> str:
    raw_name = strip_wrapping_quotes(raw_name)
    return canonicalize_from_names(raw_name, ITEM_CATALOG["food"].keys()) or strip_wrapping_quotes(str(raw_name).strip())


def canonicalize_place_name(raw_place: str, world) -> str:
    raw_place = strip_wrapping_quotes(str(raw_place or "").strip())
    if not raw_place:
        return raw_place

    normalized = normalize_label(raw_place)
    if normalized in ("home", "house"):
        return "home"

    if normalized.startswith("home "):
        suffix = normalized[len("home "):].strip()
        owner = find_agent_by_name(world, suffix)
        if owner:
            return f"Home_{owner.name}"

    loc_match = canonicalize_from_names(raw_place, [loc.name for loc in LOCATIONS_3D])
    if loc_match:
        return loc_match

    return strip_wrapping_quotes(raw_place)


def find_agent_by_name(world, name: str):
    wanted = normalize_label(name)
    return next((a for a in world.agents.values() if normalize_label(a.name) == wanted), None)


def check_open_hours(loc, sim_time: float) -> bool:
    if not loc:
        return True

    current_hour = (sim_time % 86400) / 3600.0
    if loc.open_time == loc.close_time:
        return True

    if loc.open_time <= loc.close_time:
        return loc.open_time <= current_hour < loc.close_time
    return current_hour >= loc.open_time or current_hour < loc.close_time


def seconds_until_close(loc, sim_time: float) -> float:
    if not loc:
        return float("inf")

    if loc.open_time == loc.close_time:
        return float("inf")

    current_day_seconds = sim_time % 86400
    close_seconds = loc.close_time * 3600.0
    open_seconds = loc.open_time * 3600.0

    if loc.open_time <= loc.close_time:
        return max(0.0, close_seconds - current_day_seconds)

    if current_day_seconds >= open_seconds:
        return (24 * 3600.0) - current_day_seconds + close_seconds
    if current_day_seconds < close_seconds:
        return close_seconds - current_day_seconds
    return 0.0


def is_busy(target_agent, sim_time: float) -> bool:
    if not target_agent.alive:
        return True
    if target_agent.is_sleeping:
        return True
    if target_agent.task_state != "idle":
        return True
    if target_agent.busy_until > sim_time:
        return True
    return False


def can_physically_reach_person(agent, target, max_distance: float) -> Tuple[bool, str]:
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


def has_item_index(agent, item_name: str) -> int:
    wanted = normalize_label(item_name)
    for i, it in enumerate(agent.inventory):
        if normalize_label(it["item"]) == wanted:
            return i
    return -1


def store_currently_holding_if_possible(agent) -> Tuple[bool, Optional[str]]:
    if not agent.currently_holding:
        return True, None

    if agent.currently_holding.get("id") == "job_prop":
        return False, "You are holding a required task prop."

    if len(agent.inventory) >= MAX_INVENTORY:
        return False, "You are already holding an object, and your inventory is full. Dropping is recommended."

    agent.inventory.append(agent.currently_holding)
    agent.currently_holding = None
    return True, None


def record_expense(agent, amount: float) -> None:
    if amount <= 0:
        return
    agent.expenses += amount
    agent.total_expenses += amount


def validate_shares(raw) -> Tuple[int, Optional[str]]:
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


def resolve_workplace_name(job_raw: str, agent) -> Optional[str]:
    lowered = normalize_label(job_raw)
    for key, loc_name in WORKPLACE_BY_JOB.items():
        if normalize_label(key) in lowered:
            return loc_name

    fallback = normalize_label(agent.job or "")
    for key, loc_name in WORKPLACE_BY_JOB.items():
        if normalize_label(key) in fallback:
            return loc_name

    return None
