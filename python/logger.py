import json
import os
from copy import deepcopy
from datetime import datetime, timezone

from config import LOG_DIR

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


def snapshot_agent(agent) -> dict:
    return {
        "id": agent.id,
        "name": agent.name,
        "alive": agent.alive,
        "age": agent.age,
        "health": round(agent.health, 2),
        "energy": round(agent.energy, 2),
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
        "rolling_summary": agent.rolling_summary,
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
) -> None:
    entry = {
        "event": "turn",
        "agent": agent.name,
        "agent_id": agent.id,
        "sim_time": sim_time,
        "notifications_presented": notifications,
        "input_messages": messages,
        "raw_model_output": raw_output,
        "parsed_tool": parsed_tool,
        "parsed_args": parsed_args,
        "tool_result": result,
        "tool_success": success,
        "time_cost_seconds": cost,
        "pre_state": pre_state,
        "post_state": post_state,
    }
    log_agent(agent.id, entry)


def log_global(event: dict) -> None:
    _write(os.path.join(LOG_DIR, "global_summary.jsonl"), event)


def log_io(agent_name: str, sim_time: float, messages: list, raw_output: str) -> None:
    io_entry = {
        "event": "io",
        "agent": agent_name,
        "sim_time": sim_time,
        "input_prompt": messages,
        "output_generated": raw_output,
    }
    _write(os.path.join(LOG_DIR, "global_io_dataset.jsonl"), io_entry)


def log_death(agent, cause: str = "unknown", estate: dict = None, shares_liquidated: float = 0.0, pre_death_state: dict = None) -> None:
    estate = estate or {"items": list(agent.inventory), "money": round(agent.money, 2)}

    final_stats = pre_death_state or {
        "health": round(agent.health, 2),
        "energy": round(agent.energy, 2),
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