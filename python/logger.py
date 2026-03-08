import json
import os
from datetime import datetime
from python.config import LOG_DIR

os.makedirs(LOG_DIR, exist_ok=True)

def log_agent(agent_id: int, entry: dict):
    path = os.path.join(LOG_DIR, f"agent_{agent_id}.log")
    entry["timestamp"] = datetime.utcnow().isoformat()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

def log_global(entry: dict):
    path = os.path.join(LOG_DIR, "global_summary.jsonl")
    entry["timestamp"] = datetime.utcnow().isoformat()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")