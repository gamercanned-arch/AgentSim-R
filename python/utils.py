import json
import os
import re
import subprocess
import urllib.error
import urllib.request

import jinja2

from config import (
    CACHE_DIR,
    CHARS_PER_TOKEN,
    LLAMA_CLI_PATH,
    MARKET_CLOSE_HOUR,
    MARKET_CLOSE_MINUTE,
    MARKET_OPEN_HOUR,
    MARKET_OPEN_MINUTE,
    MAX_NEW_TOKENS,
    PROMPTS_DIR,
    SUMMARIZER_MODEL_PATH,
    SUMMARIZER_PROMPT_TEMPLATE,
    SUMMARY_COMPRESS_CYCLES,
    SUMMARY_KEEP_CYCLES,
    SUMMARY_TRIGGER_CYCLES,
    TOOLS_PATH,
)
from locations import (
    describe_home_location,
    get_current_location_def,
    get_distance_3d,
    get_location_by_name,
    get_location_center,
)
from tools import EDUCATION_LOCATIONS, HOBBY_ITEMS, ITEM_CATALOG, WORKPLACE_BY_JOB

SERVER_URL = "http://127.0.0.1:8080"
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

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


def _get_time_parts(sim_time: float):
    total_minutes = int(sim_time // 60)
    total_days = total_minutes // 1440
    day_number = total_days + 1
    weekday_idx = total_days % 7
    hour = (total_minutes // 60) % 24
    minute = total_minutes % 60
    return day_number, weekday_idx, hour, minute


def get_time_string(sim_time: float, include_weekday: bool = True) -> str:
    day_number, weekday_idx, hour, minute = _get_time_parts(sim_time)
    if include_weekday:
        return f"Day {day_number} ({WEEKDAY_NAMES[weekday_idx]}), {hour:02d}:{minute:02d}"
    return f"Day {day_number}, {hour:02d}:{minute:02d}"


def get_weekday_name(sim_time: float) -> str:
    _, weekday_idx, _, _ = _get_time_parts(sim_time)
    return WEEKDAY_NAMES[weekday_idx]


def is_market_open(sim_time: float) -> bool:
    _, weekday_idx, hour, minute = _get_time_parts(sim_time)
    if weekday_idx >= 5:
        return False
    current_minutes = hour * 60 + minute
    open_minutes = MARKET_OPEN_HOUR * 60 + MARKET_OPEN_MINUTE
    close_minutes = MARKET_CLOSE_HOUR * 60 + MARKET_CLOSE_MINUTE
    return open_minutes <= current_minutes < close_minutes


def _load_text_file(*candidate_names: str) -> str:
    for name in candidate_names:
        path = os.path.join(PROMPTS_DIR, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read().strip()
    return ""


def _extract_completed_cycles(chat_history: list) -> list:
    cycles = []
    i = 0
    while i + 1 < len(chat_history):
        first = chat_history[i]
        second = chat_history[i + 1]
        if first.get("role") == "user" and second.get("role") == "assistant":
            cycles.append([first, second])
            i += 2
        else:
            i += 1
    return cycles


def _history_chunk_to_text(chunk_messages: list) -> str:
    lines = []
    for msg in chunk_messages:
        role = msg.get("role", "").upper()
        content = msg.get("content", "")
        lines.append(f"[{role}] {content}")
    return "\n".join(lines)


def _fallback_summary(prior_summary: str, chunk_messages: list) -> str:
    key_lines = []
    for idx in range(0, len(chunk_messages), 2):
        user_msg = chunk_messages[idx].get("content", "")
        assistant_msg = chunk_messages[idx + 1].get("content", "") if idx + 1 < len(chunk_messages) else ""

        result_line = ""
        for line in user_msg.splitlines():
            if line.startswith("[RESULT]:"):
                result_line = line.replace("[RESULT]:", "").strip()
                break

        tool_line = ""
        if "<function=" in assistant_msg:
            try:
                tool_line = assistant_msg.split("<function=", 1)[1].split(">", 1)[0].strip()
            except Exception:
                tool_line = ""

        snippet = result_line or tool_line or "Agent took an action."
        if tool_line and result_line:
            snippet = f"{tool_line}: {result_line}"
        key_lines.append(snippet)

    merged = ""
    if prior_summary:
        merged += prior_summary.strip() + " "
    merged += " ".join(key_lines)
    merged = " ".join(merged.split())
    return merged[:4000].strip()


def _run_summarizer(prior_summary: str, text_chunk: str) -> str:
    summary_input = text_chunk
    if prior_summary:
        summary_input = f"[PRIOR ROLLING MEMORY]\n{prior_summary}\n\n[NEW HISTORY CHUNK]\n{text_chunk}"

    prompt = SUMMARIZER_PROMPT_TEMPLATE.format(text_chunk=summary_input)

    try:
        res = subprocess.run(
            [LLAMA_CLI_PATH, "-m", SUMMARIZER_MODEL_PATH, "-p", prompt, "-n", "220", "--log-disable"],
            capture_output=True,
            text=True,
            timeout=45,
        )
        out = (res.stdout or "").strip()
        if out:
            return out[:5000]
    except Exception:
        pass
    return ""


def compress_chat_history(agent) -> None:
    cycles = _extract_completed_cycles(agent.chat_history)
    if len(cycles) < SUMMARY_TRIGGER_CYCLES:
        return

    compress_count = min(SUMMARY_COMPRESS_CYCLES, len(cycles) - SUMMARY_KEEP_CYCLES)
    if compress_count <= 0:
        return

    agent.is_summarizing = True
    messages_to_compress = compress_count * 2
    chunk_messages = agent.chat_history[:messages_to_compress]
    text_chunk = _history_chunk_to_text(chunk_messages)

    summary = _run_summarizer(agent.rolling_summary, text_chunk)
    if not summary:
        summary = _fallback_summary(agent.rolling_summary, chunk_messages)

    if summary:
        agent.rolling_summary = summary
        agent.chat_history = agent.chat_history[messages_to_compress:]

    agent.is_summarizing = False


def manage_slot(agent_id: int, action: str):
    if action == "restore":
        cache_path = os.path.join(CACHE_DIR, f"agent_{agent_id}.bin")
        if not os.path.exists(cache_path):
            return

    url = f"{SERVER_URL}/slots/0?action={action}"
    data = json.dumps({"filename": f"agent_{agent_id}.bin"}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req)
    except urllib.error.URLError:
        pass


def _build_base_system_prompt(agent) -> str:
    common_prompt = _load_text_file("common_prompt.txt")
    persona_prompt = _load_text_file(f"{agent.name.lower()}.txt", f"{agent.name}.txt")

    dynamic_rules = (
        "[Dynamic Simulation Rules]\n"
        "- Tools cost simulated time and should be used realistically.\n"
        "- Protect your health, energy, and finances.\n"
        "- Work and education are multi-step tasks: initiate them, follow the exact required next step, and finish the scenario.\n"
        "- Sleeping, active work/study tasks, and other busy states mean Do Not Disturb.\n"
        "- Your home is referred to as Home_{name}. Home aliases resolve to physical assigned lots.\n"
        "- Use do_hobby with proper hobby items like Book, Art Supplies, or Notebook.\n"
        "- Use drop_item if your hands are full and you need to free them.\n"
        "- Keep your tool call valid XML.\n"
        "- Use exact item and place names from the state prompt when possible.\n"
    ).format(name=agent.name)

    sections = [s for s in [common_prompt, persona_prompt, dynamic_rules] if s]
    return "\n\n".join(sections).strip()


def _display_location(agent, world) -> str:
    if agent.location == agent.home_location and agent.home_location:
        return f"Home_{agent.name} ({describe_home_location(agent.home_location)})"

    for other in world.agents.values():
        if other.alive and other.home_location and agent.location == other.home_location:
            return f"Home_{other.name} ({describe_home_location(other.home_location)})"

    return agent.location.replace("_", " ")


def _format_clock(hour_value: float) -> str:
    h = int(hour_value) % 24
    m = int(round((hour_value - int(hour_value)) * 60)) % 60
    return f"{h:02d}:{m:02d}"


def _is_location_open_now(loc, sim_time: float) -> bool:
    current_hour = (sim_time % 86400) / 3600.0
    if loc.open_time == loc.close_time:
        return True
    if loc.open_time <= loc.close_time:
        return loc.open_time <= current_hour < loc.close_time
    return current_hour >= loc.open_time or current_hour < loc.close_time


def _resolve_agent_workplace_name(agent) -> str:
    job = (agent.job or "").lower()
    for key, loc_name in WORKPLACE_BY_JOB.items():
        if key in job:
            return loc_name
    return ""


def _location_brief(agent, world, loc_name: str) -> str:
    loc = get_location_by_name(loc_name)
    if not loc:
        return f"{loc_name} (unknown)"

    center = get_location_center(loc)
    d = get_distance_3d((agent.x, agent.y, agent.z), center)
    dist_text = "here" if d < 1.0 else f"{d:.0f}m away"
    status = "open" if _is_location_open_now(loc, world.sim_time) else "closed"
    hours = "24h" if loc.open_time == loc.close_time else f"{_format_clock(loc.open_time)}-{_format_clock(loc.close_time)}"
    return f"{loc_name} ({dist_text}, {status}, hours {hours})"


def _affordable_food_names(agent, world) -> list:
    return [
        name
        for name, stats in ITEM_CATALOG["food"].items()
        if world.store_inventory.get(name, 0) > 0 and agent.money >= stats["price"]
    ]


def _owned_food_names(agent) -> list:
    names = []
    if agent.currently_holding and agent.currently_holding["item"] in ITEM_CATALOG["food"]:
        names.append(agent.currently_holding["item"])
    names.extend([it["item"] for it in agent.inventory if it["item"] in ITEM_CATALOG["food"]])
    return sorted(set(names))


def _owned_hobby_names(agent) -> list:
    names = []
    if agent.currently_holding and agent.currently_holding["item"] in HOBBY_ITEMS:
        names.append(agent.currently_holding["item"])
    names.extend([it["item"] for it in agent.inventory if it["item"] in HOBBY_ITEMS])
    return sorted(set(names))


def _action_affordance_summary(agent, world) -> tuple[list, list]:
    can_now = ["sleep", "move_to", "buy_item"]
    blocked = []

    if _owned_food_names(agent) or _affordable_food_names(agent, world):
        can_now.append("eat_food (use exact food names)")
    else:
        blocked.append("eat_food: no held/inventory food and no affordable in-stock food")

    if _owned_hobby_names(agent):
        can_now.append("do_hobby")

    workplace_name = _resolve_agent_workplace_name(agent)
    if workplace_name:
        loc = get_location_by_name(workplace_name)
        center = get_location_center(loc)
        d = get_distance_3d((agent.x, agent.y, agent.z), center)
        if d <= 150.0 and _is_location_open_now(loc, world.sim_time):
            can_now.append(f"work_job near {workplace_name}")
        elif d > 150.0:
            blocked.append(f"work_job: move closer to {workplace_name} first")
        else:
            blocked.append(f"work_job: {workplace_name} is currently closed")

    edu_ready = False
    edu_reasons = []
    for loc_name in EDUCATION_LOCATIONS:
        loc = get_location_by_name(loc_name)
        center = get_location_center(loc)
        d = get_distance_3d((agent.x, agent.y, agent.z), center)
        if d <= 150.0 and _is_location_open_now(loc, world.sim_time):
            edu_ready = True
            break
        if d > 150.0:
            edu_reasons.append(f"too far from {loc_name}")
        else:
            edu_reasons.append(f"{loc_name} is closed")

    if edu_ready:
        can_now.append("get_education")
    else:
        blocked.append("get_education: " + "; ".join(edu_reasons[:2]))

    hospital = get_location_by_name("Hospital")
    center = get_location_center(hospital)
    d = get_distance_3d((agent.x, agent.y, agent.z), center)
    if d <= 150.0 and _is_location_open_now(hospital, world.sim_time):
        can_now.append("seek_medicalcare")
    elif d > 150.0:
        blocked.append("seek_medicalcare: move closer to Hospital first")
    else:
        blocked.append("seek_medicalcare: Hospital is currently closed")

    return can_now, blocked


def _task_hint(agent) -> str:
    if agent.task_state == "job_pick":
        flavor = agent.pending_task_data.get("flavor", {})
        return f"Mid-task. Next step: pick_item with item_name='{flavor.get('pick', '')}'."
    if agent.task_state == "job_mcq":
        flavor = agent.pending_task_data.get("flavor", {})
        return (
            f"Mid-task. Next step: interact_with person_or_object='{flavor.get('obj', '')}' "
            f"and action='A' or 'B' or 'C'."
        )
    return "Idle."


def _nearby_ground_items(agent, world) -> str:
    visible = []
    for item in world.ground_items:
        d = get_distance_3d((agent.x, agent.y, agent.z), (item["x"], item["y"], item["z"]))
        if d <= 20:
            visible.append(f'{item["item"]} ({d:.0f}m)')
    return ", ".join(visible) if visible else "None"


def _nearby_corpse_loot(agent, world) -> str:
    visible = []
    for estate in world.corpse_estates:
        d = get_distance_3d((agent.x, agent.y, agent.z), (estate["x"], estate["y"], estate["z"]))
        if d <= 300:
            item_preview = ", ".join(i["item"] for i in estate["items"][:4]) if estate["items"] else "no items"
            money_preview = f"${estate['money']:.2f}" if estate["money"] > 0 else "$0.00"
            visible.append(f'{estate["source_agent_name"]} estate ({d:.0f}m, {money_preview}, {item_preview})')
    return "; ".join(visible) if visible else "None"


def build_messages(agent_id: int, world, notifications: str) -> list:
    agent = world.agents[agent_id]
    compress_chat_history(agent)

    if not agent.system_prompt:
        agent.system_prompt = _build_base_system_prompt(agent)

    system_content = agent.system_prompt
    if agent.rolling_summary:
        system_content += f"\n\n[Rolling Memory]\n{agent.rolling_summary}"

    prox = []
    agent_loc = get_current_location_def(agent.x, agent.y, agent.z)

    for other in world.agents.values():
        if not other.alive or other.id == agent.id:
            continue

        d = get_distance_3d((agent.x, agent.y, agent.z), (other.x, other.y, other.z))
        if d >= 100:
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

        if same_local_space:
            held = f" [Holding {other.currently_holding['item']}]" if other.currently_holding else ""
            prox.append(f"{other.name} ({d:.0f}m) [{other.current_activity}]{held}")

    loc_def = get_current_location_def(agent.x, agent.y, agent.z)
    vision = []
    visible_object_names = []
    if loc_def and loc_def.interactables:
        for obj in loc_def.interactables:
            if abs(float(obj.get("z", 0.0)) - agent.z) <= 1.0:
                visible_object_names.append(obj["name"])
                if "target_z" in obj:
                    vision.append(f"{obj['name']} (leads to Z={obj['target_z']})")
                else:
                    vision.append(obj["name"])
    vision_str = ", ".join(vision) if vision else "None"

    inv_str = ", ".join([i["item"] for i in agent.inventory]) or "Empty"
    held_str = agent.currently_holding["item"] if agent.currently_holding else "Nothing"
    news = " | ".join(world.global_news[-3:]) if world.global_news else "None"
    notif_str = notifications.strip() if notifications.strip() else "None"
    market_status = "OPEN" if is_market_open(world.sim_time) else "CLOSED"
    partner = agent.relationship_partner or "None"
    parse_warning = "Yes" if agent.last_parse_error else "No"

    food_exact = ", ".join(ITEM_CATALOG["food"].keys())
    everyday_exact = ", ".join(ITEM_CATALOG["everyday"].keys())
    health_exact = ", ".join(ITEM_CATALOG["health"].keys())
    housing_exact = ", ".join(ITEM_CATALOG["housing"].keys())
    visible_exact = ", ".join(visible_object_names) if visible_object_names else "None"

    food_owned = ", ".join(_owned_food_names(agent)) or "None"
    food_affordable = ", ".join(_affordable_food_names(agent, world)) or "None"
    hobby_owned = ", ".join(_owned_hobby_names(agent)) or "None"

    workplace_name = _resolve_agent_workplace_name(agent)
    workplace_line = _location_brief(agent, world, workplace_name) if workplace_name else "None"
    education_line = "; ".join(_location_brief(agent, world, loc_name) for loc_name in EDUCATION_LOCATIONS)
    hospital_line = _location_brief(agent, world, "Hospital")

    can_now, blocked_now = _action_affordance_summary(agent, world)
    can_now_str = ", ".join(can_now) if can_now else "None obvious"
    blocked_now_str = " | ".join(blocked_now) if blocked_now else "None obvious"

    known_public_places = "Hospital, School, Office_FedEx, Startup_Sowl, Store_A, Store_B, Market, Park_Central, Cafe, Library, Gym, Village_Square"

    user_msg = f"""[RESULT]: {agent.last_action_result}

[STATE]
Time: {get_time_string(world.sim_time)} | Weather: {world.weather}
Location: {_display_location(agent, world)} (Z={agent.z:.1f})
Home: Home_{agent.name} -> {describe_home_location(agent.home_location)} | Home Type: {agent.current_home_type}
Activity: {agent.current_activity}
Task: {_task_hint(agent)}
Visible Environmental Objects: {vision_str}
Visible Ground Items: {_nearby_ground_items(agent, world)}
Nearby Corpse Loot: {_nearby_corpse_loot(agent, world)}
Health: {agent.health:.1f} | Energy: {agent.energy:.1f} | Hunger: {agent.hunger:.1f} | Stress: {agent.stress:.1f} | Happiness: {agent.happiness:.1f}
Education: {agent.education:.1f} | Relationships: {agent.relationships:.1f} | Status: {agent.relationships_status} | Partner: {partner}
Money: ${agent.money:.2f} | Expenses(memory): ${agent.expenses:.2f} | Lifetime Expenses: ${agent.total_expenses:.2f}
Shares: {agent.shares_owned} | Avg Cost: ${agent.last_known_price:.2f} | Market: ${world.market_price:.2f} ({market_status})
Job: {agent.job}
Held: {held_str} | Inv: [{inv_str}]
Beliefs/Goals: {agent.beliefs}
Failures: consecutive={agent.fail_counter}, lifetime={agent.failed_calls}, last_parse_error={parse_warning}

[EXACT NAMES - USE THESE STRINGS]
Food: {food_exact}
Everyday Items: {everyday_exact}
Health Items: {health_exact}
Housing: {housing_exact}
Visible Object Names Here: {visible_exact}
Food You Already Have: {food_owned}
Affordable In-Stock Food Now: {food_affordable}
Hobby Items You Own: {hobby_owned}
Known Public Places: {known_public_places}
Important: Visible environmental objects are not inventory items unless they are explicitly in Held or Inv.

[PLANNING AIDS]
Workplace: {workplace_line}
Education: {education_line}
Medical: {hospital_line}
Likely valid now: {can_now_str}
Likely to fail now: {blocked_now_str}
Important: Use exact item and place names shown above. Do not invent food names like "breakfast", "bread", or "store_bread".

[ENV]
Nearby People: {", ".join(prox) or "None"}
News: {news}
Notifications: {notif_str}
"""
    agent.chat_history.append({"role": "user", "content": user_msg})
    agent.first_turn = False
    return [{"role": "system", "content": system_content}] + agent.chat_history


def render_prompt(messages: list) -> str:
    template = jinja_env.get_template("template.jinja")
    return template.render(
        messages=messages,
        tools=GLOBAL_TOOLS_LIST,
        add_generation_prompt=True,
    )


def estimate_prompt_tokens(messages: list) -> int:
    prompt_text = render_prompt(messages)
    return max(1, len(prompt_text) // CHARS_PER_TOKEN)


def _normalize_assistant_output(out: str) -> str:
    out = (out or "").strip()
    if not out:
        return "<think>\n\n</think>\n"

    out = re.sub(r"(</think>\s*){2,}", "</think>\n", out)

    if "<think>" in out:
        if "</think>" not in out:
            if "<tool_call>" in out:
                before, after = out.split("<tool_call>", 1)
                out = before.rstrip() + "\n</think>\n\n<tool_call>" + after
            else:
                out = out.rstrip() + "\n</think>"
        return out

    if "<tool_call>" in out:
        reasoning, rest = out.split("<tool_call>", 1)
        reasoning = reasoning.strip()
        if reasoning:
            return f"<think>\n{reasoning}\n</think>\n\n<tool_call>{rest}"
        return f"<think>\n\n</think>\n\n<tool_call>{rest}"

    return f"<think>\n{out}\n</think>"


def call_server(messages: list, agent_id: int) -> tuple:
    manage_slot(agent_id, action="restore")
    prompt_text = render_prompt(messages)

    req_data = {
        "prompt": prompt_text,
        "n_predict": MAX_NEW_TOKENS,
        "temperature": 0.7,
        "top_p": 0.95,
        "repeat_penalty": 1.1,
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
            out = _normalize_assistant_output(res_data.get("content", ""))
            prompt_tokens = res_data.get("tokens_evaluated", max(1, len(prompt_text) // CHARS_PER_TOKEN))
            gen_tokens = res_data.get("tokens_predicted", max(1, len(out) // CHARS_PER_TOKEN))
            manage_slot(agent_id, action="save")
            return out, prompt_tokens, gen_tokens
    except Exception as e:
        return f"[SERVER ERROR] {e}", 0, 0