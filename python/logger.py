import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime, timezone

from config import LOG_DIR

# Logging controls:
# - default: do NOT write full prompts/history every turn (keeps logs small)
# - set LOG_FULL_MESSAGES=1 to restore old behavior
LOG_FULL_MESSAGES = str(os.environ.get("LOG_FULL_MESSAGES", "0")).lower() in ("1", "true", "yes")
LOG_MAX_CHARS = int(os.environ.get("LOG_MAX_CHARS", "6000"))

try:
    os.makedirs(LOG_DIR, exist_ok=True)
except OSError as e:
    print(
        f"[LOGGER WARNING] Could not create log directory {LOG_DIR}: {e}\n"
        f"  Logging will attempt to write but may fail."
    )


def _write(path: str, data: dict) -> None:
    data["timestamp"] = datetime.now(timezone.utc).isoformat()
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[LOGGER ERROR] Could not write to {path}: {e}")


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
    """
    Return a compact summary of messages, without storing the full system prompt / full history.
    """
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
            # Hash only; system prompts can be huge
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


def snapshot_agent(agent) -> dict:
    return {
        "id": agent.id,
        "name": agent.name,
        "alive": agent.alive,
        "age": agent.age,
        "health": round(agent.health, 2),
        "energy": round(agent.energy, 2),
        "hydration": round(getattr(agent, "hydration", 0.0), 2),
        "happiness": round(agent.happiness, 2),
        "stress": round(agent.stress, 2),
        "hunger": round(agent.hunger, 2),
        "education": round(agent.education, 2),
        "relationships": round(agent.relationships, 2),
        "relationships_status": agent.relationships_status,
        "relationship_partner": agent.relationship_partner,
        "beliefs": agent.beliefs,
        "money": round(agent.money, 2),
        "expenses": round(agent.expenses, 2),
        "total_expenses": round(agent.total_expenses, 2),
        "hourly_wage": round(agent.hourly_wage, 2),
        "job": agent.job,
        "shares_owned": agent.shares_owned,
        "last_known_price": round(agent.last_known_price, 2),
        "location": agent.location,
        "x": round(agent.x, 2),
        "y": round(agent.y, 2),
        "z": round(agent.z, 2),
        "current_home_type": agent.current_home_type,
        "home_location": agent.home_location,
        "busy_until": round(agent.busy_until, 2),
        "is_sleeping": agent.is_sleeping,
        "current_activity": agent.current_activity,
        "task_state": agent.task_state,
        "pending_task_data": deepcopy(agent.pending_task_data),
        "active_task_entities": deepcopy(getattr(agent, "active_task_entities", {})),
        "inventory": deepcopy(agent.inventory),
        "currently_holding": _clean_item(agent.currently_holding),
        "pending_notifications": list(agent.pending_notifications),
        "pending_market_orders": deepcopy(agent.pending_market_orders),
        "failed_calls": agent.failed_calls,
        "fail_counter": agent.fail_counter,
        "last_parse_error": agent.last_parse_error,
        "hours_lived": agent.hours_lived,
        "awake_hours": agent.awake_hours,
        "total_prompt_tokens": agent.total_prompt_tokens,
        "social_cooldowns": deepcopy(agent.social_cooldowns),
        "last_action_result": agent.last_action_result,
        "vehicle_type": getattr(agent, "vehicle_type", ""),
        "vehicle_pos": (
            round(getattr(agent, "vehicle_x", 0.0), 2),
            round(getattr(agent, "vehicle_y", 0.0), 2),
            round(getattr(agent, "vehicle_z", 0.0), 2),
        ),
        "recent_scenarios": deepcopy(getattr(agent, "recent_scenarios", {})),
    }


def log_agent(agent_id: int, entry: dict) -> None:
    _write(os.path.join(LOG_DIR, f"agent_{agent_id}.log"), entry)


def log_turn(
    agent,
    sim_time: float,
    notifications: str,
    messages: list,
    raw_output: str,
    parsed_tool: str,
    parsed_args: dict,
    result: str,
    success: bool,
    cost: int,
    pre_state: dict,
    post_state: dict,
    prompt_hash: str = "",
    prompt_chars: int = 0,
) -> None:
    entry = {
        "event": "turn",
        "agent": agent.name,
        "agent_id": agent.id,
        "sim_time": sim_time,
        "notifications_presented": notifications,
        "prompt_hash": prompt_hash,
        "prompt_chars": int(prompt_chars) if prompt_chars else 0,
        "raw_model_output": raw_output,
        "parsed_tool": parsed_tool,
        "parsed_args": parsed_args,
        "tool_result": result,
        "tool_success": success,
        "time_cost_seconds": cost,
        "pre_state": pre_state,
        "post_state": post_state,
    }

    if LOG_FULL_MESSAGES:
        entry["input_messages"] = messages
    else:
        entry["input_messages_summary"] = _summarize_messages(messages)

    log_agent(agent.id, entry)


def log_global(event: dict) -> None:
    _write(os.path.join(LOG_DIR, "global_summary.jsonl"), event)


def log_io(agent_name: str, sim_time: float, messages: list, raw_output: str, prompt_hash: str = "", prompt_chars: int = 0) -> None:
    """
    Dataset-like IO logging. Defaults to summarized prompt to avoid huge logs.
    Set LOG_FULL_MESSAGES=1 to store full prompt/messages.
    """
    io_entry = {
        "event": "io",
        "agent": agent_name,
        "sim_time": sim_time,
        "prompt_hash": prompt_hash,
        "prompt_chars": int(prompt_chars) if prompt_chars else 0,
        "output_generated": raw_output,
    }

    if LOG_FULL_MESSAGES:
        io_entry["input_prompt"] = messages
    else:
        io_entry["input_prompt_summary"] = _summarize_messages(messages)

    _write(os.path.join(LOG_DIR, "global_io_dataset.jsonl"), io_entry)


def log_death(agent, cause: str = "unknown", estate: dict = None, shares_liquidated: float = 0.0, pre_death_state: dict = None) -> None:
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