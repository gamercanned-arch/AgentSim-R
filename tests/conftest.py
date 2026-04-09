import os
import random
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _seed_everything():
    random.seed(0)
    np.random.seed(0)


@pytest.fixture()
def temp_logs(tmp_path, monkeypatch):
    import python.logger as _logger

    monkeypatch.setattr(_logger, "LOG_DIR", str(tmp_path))
    os.makedirs(_logger.LOG_DIR, exist_ok=True)
    return tmp_path


def tool_xml(tool_name: str, **params) -> str:
    parts = ["<tool_call>\n", f"<function={tool_name}>\n"]
    for k, v in params.items():
        parts.append(f"<parameter={k}>\n{v}\n</parameter>\n")
    parts.append("</function>\n</tool_call>")
    return "".join(parts)


class StubServer:
    def __init__(self, plans: dict[int, list[str]]):
        self.plans = {int(k): list(v) for k, v in (plans or {}).items()}
        self.last_messages = {}
        self.call_count = 0

    def __call__(self, messages: list, agent_id: int, prompt_text=None):
        self.call_count += 1
        self.last_messages[int(agent_id)] = messages

        q = self.plans.get(int(agent_id), [])
        if q:
            out = q.pop(0)
        else:
            out = tool_xml("change_status", person="", type="", value="(test fallback)")

        return out, 100, 20


def last_user_observation(messages: list) -> str:
    users = [m.get("content", "") for m in messages if m.get("role") == "user"]
    return users[-1] if users else ""
