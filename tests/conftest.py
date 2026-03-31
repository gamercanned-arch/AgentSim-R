import os
import random
import sys
from pathlib import Path

import numpy as np
import pytest

# Ensure the simulation modules (python/*.py) are importable as top-level modules
# like `import scheduler`, `import config`, etc.
ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = ROOT / "python"

# Put ./python first so `import config` resolves to python/config.py
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

# Also keep repo root importable (general sanity)
if str(ROOT) not in sys.path:
    sys.path.insert(1, str(ROOT))


@pytest.fixture(autouse=True)
def _seed_everything():
    random.seed(0)
    np.random.seed(0)


@pytest.fixture()
def temp_logs(tmp_path, monkeypatch):
    """
    Redirect logger writes into a temp directory (prevents polluting real ./logs).
    """
    import logger as _logger

    monkeypatch.setattr(_logger, "LOG_DIR", str(tmp_path))
    os.makedirs(_logger.LOG_DIR, exist_ok=True)
    return tmp_path


def tool_xml(tool_name: str, **params) -> str:
    """
    Build a valid single XML tool call compatible with tooling/parsing.py.
    Values are inserted as raw text; keep test strings simple (avoid XML metachars).
    """
    parts = ["<tool_call>\n", f"<function={tool_name}>\n"]
    for k, v in params.items():
        parts.append(f"<parameter={k}>\n{v}\n</parameter>\n")
    parts.append("</function>\n</tool_call>")
    return "".join(parts)


class StubServer:
    """
    Monkeypatch target for scheduler.call_server.

    plans = { agent_id: [xml1, xml2, ...], ... }

    Records last_messages per agent_id so tests can inspect the observation content.
    """

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
            # Safe fallback tool call if a test under-specifies a plan.
            out = tool_xml("change_status", person="", type="", value="(test fallback)")

        # prompt_tokens/gen_tokens are only used for stats; keep nonzero.
        return out, 100, 20


def last_user_observation(messages: list) -> str:
    users = [m.get("content", "") for m in messages if m.get("role") == "user"]
    return users[-1] if users else ""
