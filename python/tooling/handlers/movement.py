from __future__ import annotations

import math
import re
from typing import Optional, Tuple

from python.locations import (
    describe_home_location,
    get_current_location_def,
    get_distance_3d,
    get_location_by_name,
    get_location_entrance_point,
    get_location_outside_entrance_point,
    is_home_location,
)
from python.tooling.catalogs import VEHICLE_CATALOG
from python.tooling.helpers import (
    canonicalize_place_name,
    check_open_hours,
    find_agent_by_name,
    normalize_label,
    record_expense,
)
from python.tooling.navigation import shortest_route_distance_m

VEHICLE_BOARD_MAX_DISTANCE = 100.0

_COORD_RE = re.compile(
    r"^\s*\(?\s*-?\d+(?:\.\d+)?\s*(?:,\s*|\s+)-?\d+(?:\.\d+)?(?:\s*(?:,\s*|\s+)-?\d+(?:\.\d+)?)?\s*\)?\s*$"
)


def _bearing_to_text(dx: float, dy: float) -> str:
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return "here"
    ang = math.degrees(math.atan2(dy, dx))
    dirs = [
        ("east", 0),
        ("northeast", 45),
        ("north", 90),
        ("northwest", 135),
        ("west", 180),
        ("southwest", -135),
        ("south", -90),
        ("southeast", -45),
    ]
    best = min(dirs, key=lambda d: abs(((ang - d[1] + 180) % 360) - 180))
    return best[0]


def _looks_like_coordinates(text: str) -> bool:
    return bool(_COORD_RE.match(str(text or "").strip()))


def _resolve_home_alias(place: str, world) -> Tuple[Optional[str], Optional[object]]:
    norm = normalize_label(place)
    if norm in ("home", "house"):
        return None, None

    if norm.startswith("home "):
        owner_name = norm.split(" ", 1)[1].strip()
        owner = find_agent_by_name(world, owner_name)
        if owner:
            return owner.home_location, owner
    return None, None


def _resolve_destination(place: str, raw_place: str, agent, world):
    raw_norm = normalize_label(raw_place)
    place_norm = normalize_label(place)

    if raw_norm in ("home", "house"):
        target_loc = get_location_by_name(agent.home_location)
        return target_loc, agent, None

    alias_loc_name, home_owner = _resolve_home_alias(raw_place, world)
    if alias_loc_name:
        target_loc = get_location_by_name(alias_loc_name)
        return target_loc, home_owner, None

    target_loc = get_location_by_name(place)
    if target_loc:
        owner = next(
            (a for a in world.agents.values() if a.home_location == target_loc.name),
            None,
        )
        if is_home_location(target_loc.name) and not raw_norm.startswith("home"):
            return (
                None,
                None,
                "Use a friendly home alias like Home_Taylor instead of an internal home location ID.",
            )
        return target_loc, owner, None

    if place_norm.startswith("home "):
        alias_loc_name, home_owner = _resolve_home_alias(place, world)
        if alias_loc_name:
            target_loc = get_location_by_name(alias_loc_name)
            return target_loc, home_owner, None

    return (
        None,
        None,
        f"Unknown place: '{raw_place}'. Use a named place like Library or Home_Taylor.",
    )


def _distance_to_vehicle(agent) -> float:
    vx = getattr(agent, "vehicle_x", agent.x)
    vy = getattr(agent, "vehicle_y", agent.y)
    vz = getattr(agent, "vehicle_z", agent.z)
    return get_distance_3d((agent.x, agent.y, agent.z), (vx, vy, vz))


def handle_move_to(agent, world, args: dict):
    raw_place = str(args.get("place", ""))[:100].strip()
    if not raw_place:
        agent.failed_calls += 1
        return (
            "No destination provided. Use a named place like Library or Home_Taylor.",
            False,
            60,
        )

    if _looks_like_coordinates(raw_place):
        agent.failed_calls += 1
        return (
            "Coordinates are not valid move_to inputs. Use a named place like Library, Store_A, or Home_Taylor.",
            False,
            60,
        )

    place = canonicalize_place_name(raw_place, world)
    target_loc, home_owner, err = _resolve_destination(place, raw_place, agent, world)
    if err:
        agent.failed_calls += 1
        return err, False, 60
    if not target_loc:
        agent.failed_calls += 1
        return "Unknown place.", False, 60

    outside_xyz = get_location_outside_entrance_point(target_loc, offset_m=20.0)
    entrance_xyz = get_location_entrance_point(target_loc)

    dist_m = shortest_route_distance_m((agent.x, agent.y, agent.z), outside_xyz)

    walk_speed_mps = 1.5
    walk_energy_per_m = 0.005

    mode = "walk"
    speed = walk_speed_mps
    energy_per_m = walk_energy_per_m
    fuel_cost = 0.0

    v_dist = _distance_to_vehicle(agent)
    can_use_vehicle = v_dist <= VEHICLE_BOARD_MAX_DISTANCE

    if can_use_vehicle:
        vtype = getattr(agent, "vehicle_type", "Scooter")
        vstats = VEHICLE_CATALOG.get(vtype, VEHICLE_CATALOG["Scooter"])
        speed = float(vstats["speed_mps"])
        energy_per_m = float(vstats.get("energy_per_km", 0.05)) / 1000.0
        fuel_cost = (dist_m / 1000.0) * float(vstats.get("fuel_per_km", 0.05))

        if agent.money >= fuel_cost:
            mode = "vehicle"
        else:
            agent.failed_calls += 1
            return (
                f"Cannot afford fuel for {vtype} travel (${fuel_cost:.2f}).",
                False,
                60,
            )

    time_cost = max(60, int(dist_m / max(0.5, speed)))
    energy_drain = dist_m * energy_per_m

    if agent.energy < energy_drain:
        agent.failed_calls += 1
        return (
            f"Too exhausted to travel {dist_m:.0f}m. Need {energy_drain:.1f} Energy.",
            False,
            60,
        )

    agent.energy -= energy_drain
    if fuel_cost > 0:
        agent.money -= fuel_cost
        record_expense(agent, fuel_cost)

    agent.x, agent.y, agent.z = (
        float(outside_xyz[0]),
        float(outside_xyz[1]),
        float(outside_xyz[2]),
    )
    agent.location = (
        f"Outside {target_loc.name}" if target_loc.has_roof else target_loc.name
    )
    agent.current_activity = "moving"

    if mode == "vehicle":
        agent.vehicle_x, agent.vehicle_y, agent.vehicle_z = agent.x, agent.y, agent.z

    dx = entrance_xyz[0] - outside_xyz[0]
    dy = entrance_xyz[1] - outside_xyz[1]
    door_dist = math.hypot(dx, dy)
    direction = _bearing_to_text(dx, dy)

    will_be_open = check_open_hours(target_loc, world.sim_time + time_cost)
    status_hint = ""
    if not will_be_open and not is_home_location(target_loc.name):
        status_hint = (
            " The place will be CLOSED when you arrive (you can still wait outside)."
        )

    label = target_loc.name
    if is_home_location(target_loc.name):
        if home_owner and home_owner.id == agent.id:
            label = f"Home_{agent.name} ({describe_home_location(target_loc.name)})"
        elif home_owner:
            label = (
                f"Home_{home_owner.name} ({describe_home_location(target_loc.name)})"
            )
        else:
            label = describe_home_location(target_loc.name)

    cost_hint = f"-{energy_drain:.1f} Energy"
    if fuel_cost > 0:
        cost_hint += f", -${fuel_cost:.2f} fuel"

    if target_loc.has_roof:
        return (
            f"Travelled to entrance area of {label} by {mode} ({dist_m:.0f}m; {cost_hint}). "
            f"Door is ~{door_dist:.0f}m {direction} of you.{status_hint}",
            True,
            time_cost,
        )

    return (
        f"Travelled to {label} by {mode} ({dist_m:.0f}m; {cost_hint}).{status_hint}",
        True,
        time_cost,
    )


def _entering_locked_home(agent, new_loc_name: str, world) -> Optional[str]:
    if not is_home_location(new_loc_name):
        return None

    owned = set(getattr(agent, "owned_locations", []) or [])
    if new_loc_name == agent.home_location or new_loc_name in owned:
        return None

    owner = next(
        (
            a
            for a in world.agents.values()
            if a.alive and a.home_location == new_loc_name
        ),
        None,
    )
    if owner:
        return f"{owner.name}'s home is private and locked."
    return "This home is private and locked."


def handle_walk(agent, world, args: dict):
    direction = str(args.get("direction", "")).strip().lower()
    _diag = 30.0 / math.sqrt(2)
    delta_map = {
        "north": (0, 30),
        "south": (0, -30),
        "east": (30, 0),
        "west": (-30, 0),
        "northeast": (_diag, _diag),
        "northwest": (-_diag, _diag),
        "southeast": (_diag, -_diag),
        "southwest": (-_diag, -_diag),
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

    # Enforce open hours ONLY when transitioning into a location.
    # Always allow moving within a location (even after close) and allow exiting to Outside.
    if new_loc and (not current_loc or current_loc.name != new_loc.name):
        if not check_open_hours(new_loc, world.sim_time):
            agent.failed_calls += 1
            return f"{new_loc.name} is currently closed.", False, 60

    if new_loc and (not current_loc or current_loc.name != new_loc.name):
        lock_reason = _entering_locked_home(agent, new_loc.name, world)
        if lock_reason:
            agent.failed_calls += 1
            return lock_reason, False, 60

    agent.x = new_x
    agent.y = new_y
    agent.location = new_loc.name if new_loc else "Outside"
    agent.current_activity = "moving"

    if current_loc and new_loc and current_loc.name != new_loc.name:
        return f"Walked {direction}. You entered {new_loc.name}.", True, 60
    return f"Walked {direction}. Location updated to: {agent.location}.", True, 60