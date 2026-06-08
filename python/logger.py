import hashlib
import json
import os
import threading
from copy import deepcopy
from datetime import datetime, timezone

from python.config import LOG_DIR

LOG_FULL_MESSAGES = str(os.environ.get("LOG_FULL_MESSAGES", "0")).lower() in (
    "1",
    "true",
    "yes",
)

try:
    LOG_MAX_CHARS = int(os.environ.get("LOG_MAX_CHARS", "").strip() or "6000")
except ValueError:
    LOG_MAX_CHARS = 6000

_WRITE_LOCK = threading.Lock()

try:
    os.makedirs(LOG_DIR, exist_ok=True)
except OSError as e:
    print(
        f"[LOGGER WARNING] Could not create log directory {LOG_DIR}: {e}\n"
        f"  Logging will attempt to write but may fail."
    )


def _write(path: str, data: dict) -> None:
    data["timestamp"] = datetime.now(timezone.utc).isoformat()
    line = json.dumps(data, ensure_ascii=False, default=str) + "\n"
    with _WRITE_LOCK:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)


def _clean_item(item):
    if item is None:
        return None
    return deepcopy(item)


def _truncate(text: str, max_chars: int = LOG_MAX_CHARS) -> str:
    text = "" if text is None else str(text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20] + f"...(truncated,{len(text)} chars)"


def _sha16(text: str) -> str:
    b = (text or "").encode("utf-8", errors="ignore")
    return hashlib.sha256(b).hexdigest()[:16]


def _summarize_messages(messages: list) -> dict:
    if not messages:
        return {"message_count": 0}

    role_counts = {}
    last_user = ""
    last_assistant = ""
    system_hash = ""

    for m in messages:
        role = m.get("role", "")
        role_counts[role] = role_counts.get(role, 0) + 1

        if role == "system":
            system_hash = _sha16(m.get("content", ""))
        elif role == "user":
            last_user = m.get("content", "") or last_user
        elif role == "assistant":
            last_assistant = m.get("content", "") or last_assistant

    return {
        "message_count": len(messages),
        "role_counts": role_counts,
        "system_hash": system_hash,
        "last_user_preview": _truncate(last_user, 2000),
        "last_assistant_preview": _truncate(last_assistant, 1200),
    }


def _extract_system_user(messages: list) -> tuple[str, str]:
    system = ""
    last_user = ""
    for m in messages or []:
        if m.get("role") == "system" and not system:
            system = m.get("content", "") or ""
        if m.get("role") == "user":
            last_user = m.get("content", "") or last_user
    return system, last_user


def _get_new_messages_this_turn(messages: list, raw_output: str) -> list:
    if not messages:
        return [{"role": "assistant", "content": raw_output}]
    
    last_assistant_idx = -1
    for idx, msg in enumerate(messages):
        if msg.get("role") == "assistant":
            last_assistant_idx = idx
            
    if last_assistant_idx == -1:
        new_msgs = list(messages)
    else:
        new_msgs = list(messages[last_assistant_idx + 1:])
        
    new_msgs.append({"role": "assistant", "content": raw_output})
    return new_msgs


def snapshot_agent(agent, global_token_usage: dict | None = None) -> dict:
    def num(name: str, default: float = 0.0) -> float:
        try:
            return round(float(getattr(agent, name, default)), 2)
        except (TypeError, ValueError):
            return round(float(default), 2)

    return {
        "id": getattr(agent, "id", None),
        "global_token_usage": deepcopy(global_token_usage) if global_token_usage else {},
        "name": getattr(agent, "name", ""),
        "alive": bool(getattr(agent, "alive", False)),
        "age": getattr(agent, "age", 0),
        "health": num("health"),
        "energy": num("energy"),
        "hydration": num("hydration"),
        "happiness": num("happiness"),
        "stress": num("stress"),
        "hunger": num("hunger"),
        "education": num("education"),
        "relationships": num("relationships"),
        "relationships_status": getattr(agent, "relationships_status", ""),
        "relationship_partner": getattr(agent, "relationship_partner", ""),
        "beliefs": getattr(agent, "beliefs", ""),
        "money": num("money"),
        "expenses": num("expenses"),
        "total_expenses": num("total_expenses"),
        "hourly_wage": num("hourly_wage"),
        "job": getattr(agent, "job", ""),
        "shares_owned": getattr(agent, "shares_owned", 0),
        "last_known_price": num("last_known_price"),
        "location": getattr(agent, "location", ""),
        "x": num("x"),
        "y": num("y"),
        "z": num("z"),
        "current_home_type": getattr(agent, "current_home_type", ""),
        "home_location": getattr(agent, "home_location", ""),
        "busy_until": num("busy_until"),
        "is_sleeping": bool(getattr(agent, "is_sleeping", False)),
        "current_activity": getattr(agent, "current_activity", ""),
        "task_state": getattr(agent, "task_state", "idle"),
        "pending_task_data": deepcopy(getattr(agent, "pending_task_data", {})),
        "active_task_entities": deepcopy(getattr(agent, "active_task_entities", {})),
        "inventory": deepcopy(getattr(agent, "inventory", [])),
        "currently_holding": _clean_item(getattr(agent, "currently_holding", None)),
        "pending_notifications": list(getattr(agent, "pending_notifications", []) or []),
        "pending_market_orders": deepcopy(getattr(agent, "pending_market_orders", [])),
        "failed_calls": getattr(agent, "failed_calls", 0),
        "fail_counter": getattr(agent, "fail_counter", 0),
        "last_parse_error": bool(getattr(agent, "last_parse_error", False)),
        "hours_lived": getattr(agent, "hours_lived", 0),
        "awake_hours": getattr(agent, "awake_hours", 0),
        "total_prompt_tokens": getattr(agent, "total_prompt_tokens", 0),
        "last_action_result": getattr(agent, "last_action_result", ""),
        "vehicle_type": getattr(agent, "vehicle_type", ""),
        "vehicle_pos": (
            num("vehicle_x"),
            num("vehicle_y"),
            num("vehicle_z"),
        ),
        "recent_scenarios": deepcopy(getattr(agent, "recent_scenarios", {})),
        "voicemail_inbox": deepcopy(getattr(agent, "voicemail_inbox",[])),
    }


def log_agent(agent_id: int, entry: dict) -> None:
    _write(os.path.join(LOG_DIR, f"agent_{agent_id}.log"), entry)


def log_turn(
    agent,
    sim_time: float,
    notifications: str,
    messages: list,
    raw_output: str,
    parsed_tool,
    parsed_args,
    result: str,
    success: bool,
    cost: int,
    pre_state: dict,
    post_state: dict,
    prompt_hash: str = "",
    prompt_chars: int = 0,
    notifications_shown: list | None = None,
    notifications_remaining: int = 0,
    raw_provider: str | None = None,
    raw_model: str | None = None,
    raw_reasoning: str | None = None,
    processed_output: str | None = None,
) -> None:
    system_prompt, user_observation = _extract_system_user(messages)

    entry = {
        "event": "turn",
        "agent": agent.name,
        "agent_id": agent.id,
        "sim_time": sim_time,
        "notifications_presented": notifications,
        "notifications_shown_list": notifications_shown or[],
        "notifications_remaining_count": int(notifications_remaining),
        "system_prompt": system_prompt,
        "user_observation": user_observation,
        "prompt_hash": prompt_hash,
        "prompt_chars": int(prompt_chars) if prompt_chars else 0,
        "raw_provider": raw_provider,
        "raw_model": raw_model,
        "raw_model_output": raw_output,
        "raw_model_reasoning": raw_reasoning,
        "native_reasoning": raw_reasoning,
        "processed_model_output": processed_output
        if processed_output is not None
        else raw_output,
        "parsed_tool": parsed_tool,
        "parsed_args": parsed_args,
        "tool_result": result,
        "tool_success": success,
        "time_cost_seconds": cost,
        "pre_state": pre_state,
        "post_state": post_state,
    }

    entry["turn_messages"] = _get_new_messages_this_turn(messages, raw_output)
    log_agent(agent.id, entry)


def log_global(event: dict) -> None:
    _write(os.path.join(LOG_DIR, "global_summary.jsonl"), event)


def log_io(
    agent_name: str,
    sim_time: float,
    messages: list,
    raw_output: str,
    prompt_hash: str = "",
    prompt_chars: int = 0,
    raw_provider: str | None = None,
    raw_model: str | None = None,
    raw_reasoning: str | None = None,
    processed_output: str | None = None,
) -> None:
    system_prompt, user_observation = _extract_system_user(messages)

    io_entry = {
        "event": "io",
        "agent": agent_name,
        "sim_time": sim_time,
        "system_prompt": system_prompt,
        "user_observation": user_observation,
        "prompt_hash": prompt_hash,
        "prompt_chars": int(prompt_chars) if prompt_chars else 0,
        "raw_provider": raw_provider,
        "raw_model": raw_model,
        "raw_model_output": raw_output,
        "raw_model_reasoning": raw_reasoning,
        "native_reasoning": raw_reasoning,
        "processed_model_output": processed_output
        if processed_output is not None
        else raw_output,
    }


    io_entry["turn_messages"] = _get_new_messages_this_turn(messages, raw_output)

    _write(os.path.join(LOG_DIR, "global_io_dataset.jsonl"), io_entry)


def log_death(
    agent,
    cause: str = "unknown",
    estate: dict = None,
    shares_liquidated: float = 0.0,
    pre_death_state: dict = None,
) -> None:
    estate = estate or {"items": list(agent.inventory), "money": round(agent.money, 2)}

    final_stats = pre_death_state or {
        "health": round(agent.health, 2),
        "energy": round(agent.energy, 2),
        "hydration": round(getattr(agent, "hydration", 0.0), 2),
        "happiness": round(agent.happiness, 2),
        "stress": round(agent.stress, 2),
        "hunger": round(agent.hunger, 2),
        "money": round(agent.money, 2),
        "location": agent.location,
        "x": round(agent.x, 2),
        "y": round(agent.y, 2),
        "z": round(agent.z, 2),
        "inventory": deepcopy(agent.inventory),
        "currently_holding": _clean_item(agent.currently_holding),
        "current_home_type": agent.current_home_type,
        "home_location": agent.home_location,
        "job": agent.job,
        "beliefs": agent.beliefs,
        "vehicle_type": getattr(agent, "vehicle_type", ""),
    }

    death_entry = {
        "event": "death",
        "agent": agent.name,
        "agent_id": agent.id,
        "cause": cause,
        "age": agent.age,
        "shares_liquidated": round(shares_liquidated, 2),
        "final_stats": final_stats,
        "estate": deepcopy(estate),
    }
    log_global(death_entry)
    print(f"[DEATH] {agent.name} has died. Stats snapshot logged.")
