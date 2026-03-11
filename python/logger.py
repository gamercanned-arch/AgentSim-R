import json
import os
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
            f.write(json.dumps(data) + "\n")
    except OSError as e:
        print(f"[LOGGER ERROR] Could not write to {path}: {e}")


def log_agent(agent_id: int, entry: dict) -> None:
    _write(os.path.join(LOG_DIR, f"agent_{agent_id}.log"), entry)


def log_global(event: dict) -> None:
    _write(os.path.join(LOG_DIR, "global_summary.jsonl"), event)


def log_death(agent) -> None:
    death_entry = {
        "event": "death",
        "agent": agent.name,
        "age":   agent.age,
        "final_stats": {
            "health":         round(agent.health,    1),
            "energy":         round(agent.energy,    1),
            "happiness":      round(agent.happiness, 1),
            "stress":         round(agent.stress,    1),
            "hunger":         round(agent.hunger,    1),
            "money":          round(agent.money,     2),
            "hourly_wage":    round(agent.hourly_wage, 2),
            "total_expenses": round(agent.total_expenses, 2),
            "location":       agent.location,
            "inventory":      dict(agent.inventory),
        },
    }
    log_global(death_entry)
    print(f"[DEATH] {agent.name} has died. Stats snapshot logged.")