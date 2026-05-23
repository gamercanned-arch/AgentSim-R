from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections import Counter
from typing import List, Optional

import jinja2

from python.config import (
    AUTO_LOOT_RADIUS,
    CACHE_DIR,
    CHARS_PER_TOKEN,
    GROUND_PICKUP_RADIUS,
    MAX_NEW_TOKENS,
    PROMPTS_DIR,
    TOOLS_PATH,
)
from python.core import get_time_string, is_market_open
from python.locations import (
    PUBLIC_LOCATIONS_3D,
    describe_home_location,
    get_current_location_def,
    get_distance_3d,
    get_location_entrance_point,
    humanize_location_name,
    is_home_location,
)
from python.tooling.catalogs import ITEM_CATALOG, generate_catalog_text

SERVER_URL = "http://127.0.0.1:8080"

jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader(PROMPTS_DIR))


def raise_exception(msg):
    raise ValueError(msg)


jinja_env.globals["raise_exception"] = raise_exception


try:
    with open(TOOLS_PATH, encoding="utf-8") as f:
        GLOBAL_TOOLS_LIST = json.load(f)["tools"]
except Exception as e:
    print(f"[WARNING] Could not load tools.json: {e}")
    GLOBAL_TOOLS_LIST = []


def _load_text_file(*candidate_names: str) -> str:
    for name in candidate_names:
        path = os.path.join(PROMPTS_DIR, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read().strip()
    return ""


def _format_hour(hour_float: float) -> str:
    total_minutes = int(round(float(hour_float) * 60))
    if total_minutes >= 1440:
        return "24:00"
    hh = (total_minutes // 60) % 24
    mm = total_minutes % 60
    return f"{hh:02d}:{mm:02d}"


def _is_all_day(loc) -> bool:
    return float(loc.open_time) == float(loc.close_time) or (
        float(loc.open_time) == 0.0 and float(loc.close_time) >= 24.0
    )


def _static_open_hours_text() -> str:
    lines = ["[Public Location Hours]"]
    for loc in PUBLIC_LOCATIONS_3D:
        if _is_all_day(loc):
            hours = "00:00-24:00"
        else:
            hours = f"{_format_hour(loc.open_time)}-{_format_hour(loc.close_time)}"
        lines.append(f"- {loc.name}: {hours}")
    return "\n".join(lines)


def _build_base_system_prompt(agent) -> str:
    common_prompt = _load_text_file("common_prompt.txt", "common_prompts.txt")
    persona_prompt = _load_text_file(f"{agent.name.lower()}.txt", f"{agent.name}.txt")

    dynamic_rules = (
        "[Dynamic Simulation Rules]\n"
        "- You MUST output exactly one valid XML tool call each turn.\n"
        "- You MAY think in an optional <think>...</think> block before the tool call.\n"
        "- If your model does NOT support <think> tags, you MUST still provide brief reasoning BEFORE the <tool_call> in plain text.\n"
        "  (The engine will treat any text before <tool_call> as reasoning.)\n"
        "- Do NOT output any text after </tool_call>.\n"
        "- Coordinates shown in observations are read-only telemetry. Never pass coordinates into any tool.\n"
        "- For move_to, use only a named public location or a home alias like Home_Taylor. Never use raw coordinates or internal location IDs.\n"
        "- Place, item, and person names are normalized loosely by the engine, so close variants like Startup Sowl or Office FedEx are acceptable.\n"
        "- move_to travels to the OUTSIDE entrance area for roofed buildings; to enter a building, walk into its boundary.\n"
        "- Open-air destinations like Park_Central count as being at that location when you arrive.\n"
        "- Vehicles: you can ride only if within 100m of your parked vehicle; fuel costs $/km when riding.\n"
        "- If you cannot afford fuel, move_to fails.\n"
        "- pick_item is for nearby dropped ground items, or for the required task prop during an active work or study task.\n"
        "- hold_item moves an inventory item into your hand, or stores your held item back into inventory when item_name is store or None.\n"
        "- Required task props cannot be stored away until the task ends.\n"
        "- Corpse estate loot is collected automatically when you get close enough.\n"
        "- Environmental objects are NOT inventory items unless shown in Held or Inventory.\n"
        "- Use visible stairs, elevators, or escalators when you need to change floors.\n"
        "- Use exact location and item names when possible; do not invent new places.\n"
    )

    catalog_text = generate_catalog_text()
    hours_text = _static_open_hours_text()
    sections = [
        s
        for s in (
            common_prompt,
            persona_prompt,
            dynamic_rules,
            hours_text,
            catalog_text,
        )
        if s
    ]
    return "\n\n".join(sections).strip()


def _display_location(agent, world) -> str:
    if agent.home_location and agent.location == agent.home_location:
        return f"Home_{agent.name} ({describe_home_location(agent.home_location)})"

    if agent.location and is_home_location(agent.location):
        for other in world.agents.values():
            if not other.alive:
                continue
            if other.home_location and agent.location == other.home_location:
                return (
                    f"Home_{other.name} ({describe_home_location(other.home_location)})"
                )
        return describe_home_location(agent.location)

    return humanize_location_name(agent.location)


def _bearing_to_text(dx: float, dy: float) -> str:
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return "here"
    import math

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


def _safe_prompt_text(text: str, max_chars: int = 240) -> str:
    s = "" if text is None else str(text)
    s = s.replace("\x00", "")
    s = s.replace("<", "‹").replace(">", "›")
    s = re.sub(r"[\r\t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    if len(s) > max_chars:
        s = s[: max_chars - 20] + f"... ({len(s)} chars)"
    return s


def _nearby_people_same_floor(agent, world) -> str:
    agent_loc = get_current_location_def(agent.x, agent.y, agent.z)
    out = []
    for other in world.agents.values():
        if not other.alive or other.id == agent.id:
            continue
        d = get_distance_3d((agent.x, agent.y, agent.z), (other.x, other.y, other.z))
        if d > 60:
            continue
        other_loc = get_current_location_def(other.x, other.y, other.z)

        same_local_space = True
        if agent_loc or other_loc:
            same_local_space = (
                agent_loc is not None
                and other_loc is not None
                and agent_loc.name == other_loc.name
                and abs(agent.z - other.z) <= 1.0
            )
        if not same_local_space:
            continue
        out.append(f"{other.name} ({d:.0f}m) [{other.current_activity}]")
    return ", ".join(out) if out else "None"


def _visible_objects_here(agent) -> str:
    loc_def = get_current_location_def(agent.x, agent.y, agent.z)
    if not loc_def:
        return "None"
        
    if "Outside" in agent.location and loc_def.has_roof:
        return "None"

    names = []
    for obj in loc_def.interactables:
        if "target_z" in obj:
            continue

        if abs(float(obj.get("z", 0.0)) - agent.z) <= 1.0:
            names.append(obj["name"])

    task_entities = getattr(agent, "active_task_entities", {}) or {}
    if agent.task_state in {"job_pick", "job_mcq"}:
        task_loc = str(task_entities.get("location", "")).strip()
        if loc_def and loc_def.name == task_loc:
            prop = str(task_entities.get("prop", "")).strip()
            target = str(task_entities.get("target", "")).strip()
            if prop:
                names.append(f"{prop} [task]")
            if target:
                names.append(f"{target} [task]")

    deduped = []
    seen = set()
    for n in names:
        k = n.lower()
        if k not in seen:
            deduped.append(n)
            seen.add(k)

    return ", ".join(deduped) if deduped else "None"


def _nearest_entrances(agent, max_show: int = 3, max_dist: float = 120.0) -> str:
    from python.locations import LOCATIONS_3D

    candidates = []
    for loc in LOCATIONS_3D:
        if is_home_location(loc.name) and loc.name != agent.home_location:
            continue
        ex, ey, ez = get_location_entrance_point(loc)
        d = get_distance_3d((agent.x, agent.y, agent.z), (ex, ey, ez))
        if d <= max_dist:
            dx, dy = ex - agent.x, ey - agent.y
            candidates.append((d, loc.name, _bearing_to_text(dx, dy)))
    candidates.sort(key=lambda x: x[0])
    top = candidates[:max_show]
    if not top:
        return "None"
    return "; ".join(
        [
            f"{humanize_location_name(name)} door {d:.0f}m {dirn}"
            for (d, name, dirn) in top
        ]
    )


def _owned_food_and_drinks(agent) -> str:
    owned = []
    if (
        agent.currently_holding
        and agent.currently_holding.get("item") in ITEM_CATALOG["food"]
    ):
        owned.append(agent.currently_holding["item"])
    for it in agent.inventory:
        if it["item"] in ITEM_CATALOG["food"]:
            owned.append(it["item"])
    owned = sorted(set(owned))
    return ", ".join(owned) if owned else "None"


def _inventory_line(agent) -> str:
    counts = Counter()
    durability_map = {}
    for it in agent.inventory:
        name = it.get("item", "Unknown")
        counts[name] += 1
        dur = it.get("durability")
        if dur is not None:
            durability_map.setdefault(name, []).append(dur)
    if not counts:
        return "None"
    parts = []
    for name in sorted(counts.keys()):
        n = counts[name]
        base = f"{name} x{n}" if n > 1 else name
        if name in durability_map:
            durs = sorted(durability_map[name])
            base += f" [dur:{','.join(str(d) for d in durs)}]"
        parts.append(base)
    return ", ".join(parts)


def _vehicle_line(agent) -> str:
    vtype = getattr(agent, "vehicle_type", "Scooter")
    vx = getattr(agent, "vehicle_x", agent.x)
    vy = getattr(agent, "vehicle_y", agent.y)
    vz = getattr(agent, "vehicle_z", agent.z)
    d = get_distance_3d((agent.x, agent.y, agent.z), (vx, vy, vz))
    within = "YES" if d <= 100.0 else "NO"
    return f"{vtype} at ({vx:.0f},{vy:.0f},{vz:.0f}) dist={d:.0f}m can_ride={within}"


def _is_loc_open_now(loc, sim_time: float) -> bool:
    current_hour = (sim_time % 86400) / 3600.0
    if _is_all_day(loc):
        return True
    if loc.open_time <= loc.close_time:
        return loc.open_time <= current_hour < loc.close_time
    return current_hour >= loc.open_time or current_hour < loc.close_time


def _nearby_location_hours(
    agent, sim_time: float, max_show: int = 6, max_dist: float = 1200.0
) -> str:
    candidates = []
    for loc in PUBLIC_LOCATIONS_3D:
        ex, ey, ez = get_location_entrance_point(loc)
        d = get_distance_3d((agent.x, agent.y, agent.z), (ex, ey, ez))
        if d <= max_dist:
            status = "OPEN" if _is_loc_open_now(loc, sim_time) else "CLOSED"
            if _is_all_day(loc):
                hours = "00:00-24:00"
            else:
                hours = f"{_format_hour(loc.open_time)}-{_format_hour(loc.close_time)}"
            candidates.append((d, f"{loc.name} {d:.0f}m {status} ({hours})"))
    candidates.sort(key=lambda x: x[0])
    top = [entry for _, entry in candidates[:max_show]]
    return "; ".join(top) if top else "None"


def _task_line(agent) -> str:
    if agent.task_state == "idle":
        return "Task: idle"

    flavor = agent.pending_task_data.get("flavor", {}) or {}
    prop = str(flavor.get("pick", "")).strip()
    target = str(flavor.get("obj", "")).strip()
    workplace = str(agent.pending_task_data.get("workplace", "")).strip() or "Unknown"

    if agent.task_state == "job_pick":
        if prop:
            return (
                f"Task: ACTIVE at {workplace} | Next step: use pick_item for the required task prop {prop}. "
                f"The prop is only available while you remain in the correct location."
            )
        return "Task: ACTIVE | Next step: use pick_item for the required task prop."

    if agent.task_state == "job_mcq":
        q = str(flavor.get("q", "")).strip()
        choices = flavor.get("choices", {}) or {}
        a = str(choices.get("A", "")).strip()
        b = str(choices.get("B", "")).strip()
        c = str(choices.get("C", "")).strip()
        return (
            f"Task: ACTIVE at {workplace} | Next step: answer the current scenario.\n"
            f"Task Target: {target or 'Unknown'}\n"
            f"Question: {q or 'Unknown'}\n"
            f"Choices: A) {a} | B) {b} | C) {c}\n"
            f"Answer by using interact_with on {target or 'the target'} with action A, B, or C."
        )

    return f"Task: {agent.task_state}"


def _voicemail_preview(agent, max_show: int = 10) -> str:
    inbox = getattr(agent, "voicemail_inbox", None) or []
    if not inbox:
        return "None"
    shown = inbox[-max_show:]
    parts = []
    for vm in shown:
        from_name = _safe_prompt_text(vm.get("from", "Unknown"), 80)
        t = vm.get("time", None)
        t_str = (
            get_time_string(float(t), include_weekday=True)
            if isinstance(t, (int, float))
            else "Unknown time"
        )
        msg = _safe_prompt_text(vm.get("message", ""), 180)
        parts.append(f"- From {from_name} at {t_str}: {msg}")
    if len(inbox) > len(shown):
        parts.append(f"(+{len(inbox) - len(shown)} older voicemails)")
    return "\n".join(parts)


def _pending_status_requests_line(agent) -> str:
    reqs = getattr(agent, "pending_status_requests", {}) or {}
    if not reqs:
        return "None"
    parts = [
        f"{_safe_prompt_text(k, 40)} -> {_safe_prompt_text(v, 40)}"
        for k, v in sorted(reqs.items())
    ]
    return ", ".join(parts)


def _pending_market_orders_line(agent) -> str:
    orders = getattr(agent, "pending_market_orders", []) or []
    if not orders:
        return "None"
    parts = []
    for order in orders[-8:]:
        otype = _safe_prompt_text(order.get("type", "?"), 20)
        shares = int(order.get("shares", 0))
        parts.append(f"{otype} {shares}")
    return ", ".join(parts) if parts else "None"


def _nearby_ground_items(agent, world, max_show: int = 8) -> str:
    out = []
    for gi in getattr(world, "ground_items", []) or []:
        d = get_distance_3d((agent.x, agent.y, agent.z), (gi["x"], gi["y"], gi["z"]))
        if d <= GROUND_PICKUP_RADIUS:
            out.append((d, f"{gi.get('item', 'Unknown')} ({d:.0f}m)"))
    out.sort(key=lambda x: x[0])
    return ", ".join([s for _, s in out[:max_show]]) if out else "None"


def _nearby_estates(agent, world, max_show: int = 6) -> str:
    out = []
    for estate in getattr(world, "corpse_estates", []) or []:
        d = get_distance_3d(
            (agent.x, agent.y, agent.z), (estate["x"], estate["y"], estate["z"])
        )
        if d <= AUTO_LOOT_RADIUS:
            src = _safe_prompt_text(estate.get("source_agent_name", "Unknown"), 40)
            cash = float(estate.get("money", 0.0))
            item_count = len(estate.get("items", []) or [])
            out.append(
                (d, f"{src} estate ({d:.0f}m, cash=${cash:.2f}, items={item_count})")
            )
    out.sort(key=lambda x: x[0])
    return ", ".join([s for _, s in out[:max_show]]) if out else "None"


def _history_for_model(agent) -> list[dict]:
    out: list[dict] = []
    for m in list(agent.chat_history or []):
        role = m.get("role", "")
        if role == "tool":
            # Convert tool role to user role for LLM compatibility
            out.append({"role": "user", "content": str(m.get("content", ""))})
        else:
            out.append(m)
    return out


def build_messages(agent_id: int, world, notifications: str) -> List[dict]:
    agent = world.agents[agent_id]

    if not agent.system_prompt:
        agent.system_prompt = _build_base_system_prompt(agent)

    system_content = agent.system_prompt
    market_status = "OPEN" if is_market_open(world.sim_time) else "CLOSED"

    held = "None"
    if agent.currently_holding:
        held = agent.currently_holding.get("item", "Unknown") if isinstance(agent.currently_holding, dict) else "None"

    loc_label = _display_location(agent, world)
    loc_def = get_current_location_def(agent.x, agent.y, agent.z)
    inside_name = humanize_location_name(loc_def.name) if loc_def else "Outside"

    notif_str = (
        _safe_prompt_text(notifications.strip(), 1800)
        if notifications and notifications.strip()
        else "None"
    )
    nearby_people = _nearby_people_same_floor(agent, world)
    visible_objs = _visible_objects_here(agent) if loc_def else "None"
    nearby_doors = _nearest_entrances(agent) if not loc_def else "None"
    nearby_hours = _nearby_location_hours(agent, world.sim_time)

    vm_inbox = getattr(agent, "voicemail_inbox", None) or []
    vm_count = len(vm_inbox)
    vm_preview = _voicemail_preview(agent, max_show=10)

    partner = agent.relationship_partner if agent.relationship_partner else "None"
    beliefs = _safe_prompt_text(agent.beliefs, 220)

    user_msg = (
        "Stats:\n"
        f"Date/Time: {get_time_string(world.sim_time)}\n"
        f"Weather: {world.weather}\n"
        f"Location: ({agent.x:.0f},{agent.y:.0f},{agent.z:.0f}) [{loc_label}] (inside={inside_name})\n"
        f"Money: ${agent.money:.2f}\n"
        f"Health: {agent.health:.0f}%\n"
        f"Hunger: {agent.hunger:.0f}%\n"
        f"Energy: {agent.energy:.0f}%\n"
        f"Hydration: {getattr(agent, 'hydration', 0.0):.0f}%\n"
        f"Stress: {agent.stress:.0f}%\n"
        f"Happiness: {agent.happiness:.0f}%\n"
        f"Education: {agent.education:.0f}%\n"
        f"Relationships: {agent.relationships:.1f} | Status: {agent.relationships_status} | Partner: {partner}\n"
        f"Beliefs/Goals: {beliefs}\n"
        f"Current Activity: {agent.current_activity}\n"
        f"Held Item: {held}\n"
        f"Inv Count: {len(agent.inventory)}\n"
        f"Inventory: {_inventory_line(agent)}\n"
        f"Food/Drink Owned: {_owned_food_and_drinks(agent)}\n"
        f"Nearby People: {nearby_people}\n"
        f"Visible Objects: {visible_objs}\n"
        f"Nearby Ground Items: {_nearby_ground_items(agent, world)}\n"
        f"Nearby Estates: {_nearby_estates(agent, world)}\n"
        f"Nearby Doors (if outside): {nearby_doors}\n"
        f"Nearby Locations/Hrs: {nearby_hours}\n"
        f"Vehicle: {_vehicle_line(agent)}\n"
        f"Market line: {market_status}, ${world.market_price:.4f}, stocks owned: {agent.shares_owned}\n"
        f"Pending Market Orders: {_pending_market_orders_line(agent)}\n"
        f"Pending Relationship Requests: {_pending_status_requests_line(agent)}\n"
        f"Voicemail Inbox: {vm_count} message(s)\n"
        f"Voicemails (most recent):\n{vm_preview}\n"
        f"{_task_line(agent)}\n"
        f"Last Result: {_safe_prompt_text(agent.last_action_result, 500)}\n"
        f"Notifications: {notif_str}\n"
    )

    return (
        [{"role": "system", "content": system_content}]
        + _history_for_model(agent)
        + [{"role": "user", "content": user_msg}]
    )


def render_prompt(messages: list) -> str:
    template = jinja_env.get_template("template.jinja")
    return template.render(
        messages=messages, tools=GLOBAL_TOOLS_LIST, add_generation_prompt=True
    )


def estimate_prompt_tokens(messages: list, prompt_text: Optional[str] = None) -> int:
    if prompt_text is None:
        prompt_text = render_prompt(messages)
    return max(1, len(prompt_text) // CHARS_PER_TOKEN)


_THINK_CLEAN_RE = re.compile(r"(</think>\s*){2,}", re.DOTALL)


def _normalize_assistant_output(out: str) -> str:
    out = (out or "").strip()
    if not out:
        return ""

    out = re.sub(_THINK_CLEAN_RE, "</think>\n", out)

    if "<think>" in out:
        return out

    if "<tool_call>" in out:
        reasoning, rest = out.split("<tool_call>", 1)
        reasoning = reasoning.strip()
        if reasoning:
            return f"<think>\n{reasoning}\n</think>\n\n<tool_call>{rest}"
        return f"<tool_call>{rest}"

    return out


def manage_slot(agent_id: int, action: str):
    # Note: Assumes slot 0 is safe to use in a single-threaded environment.
    if action == "restore":
        cache_path = os.path.join(CACHE_DIR, f"agent_{agent_id}.bin")
        if not os.path.exists(cache_path):
            return

    url = f"{SERVER_URL}/slots/0?action={action}"
    data = json.dumps({"filename": f"agent_{agent_id}.bin"}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req)
    except Exception:
        pass


def call_server(
    messages: list, agent_id: int, prompt_text: Optional[str] = None
) -> tuple:
    manage_slot(agent_id, action="restore")
    if prompt_text is None:
        prompt_text = render_prompt(messages)

    req_data = {
        "prompt": prompt_text,
        "n_predict": MAX_NEW_TOKENS,
        "temperature": 0.7,
        "top_p": 0.9,
        "top_k": 20,
        "repeat_penalty": 1.1,
        "presence_penalty": 1.0,
        "stop": ["<|im_end|>"],
    }

    req = urllib.request.Request(
        f"{SERVER_URL}/completion",
        data=json.dumps(req_data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req) as res:
            res_data = json.loads(res.read().decode("utf-8"))

            raw = res_data.get("content", "") or ""
            out = _normalize_assistant_output(raw)

            if not hasattr(call_server, "last_raw"):
                call_server.last_raw = {}  # type: ignore[attr-defined]
            call_server.last_raw[int(agent_id)] = {  # type: ignore[attr-defined]
                "provider": "local",
                "model": "llama.cpp",
                "content": str(raw),
                "reasoning": "",
            }

            prompt_tokens = res_data.get(
                "tokens_evaluated", max(1, len(prompt_text) // CHARS_PER_TOKEN)
            )
            gen_tokens = res_data.get(
                "tokens_predicted", max(1, len(out) // CHARS_PER_TOKEN)
            )
            manage_slot(agent_id, action="save")
            return out, prompt_tokens, gen_tokens
    except Exception as e:
        if not hasattr(call_server, "last_raw"):
            call_server.last_raw = {}  # type: ignore[attr-defined]
        call_server.last_raw[int(agent_id)] = {  # type: ignore[attr-defined]
            "provider": "local",
            "model": "llama.cpp",
            "content": f"[SERVER ERROR] {e}",
            "reasoning": "",
        }
        return f"[SERVER ERROR] {e}", 0, 0
