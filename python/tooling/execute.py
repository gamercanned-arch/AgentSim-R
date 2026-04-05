from __future__ import annotations

import json
import uuid
from typing import Callable, Dict, Tuple

from python.config import TOOLS_PATH
from python.tooling.parsing import parse_tool_calls

from python.tooling.handlers.movement import handle_move_to, handle_walk
from python.tooling.handlers.workstudy import (
    handle_get_education,
    handle_interact_with,
    handle_work_job,
)
from python.tooling.handlers.economy import (
    handle_buy_item,
    handle_buy_stock,
    handle_eat_food,
    handle_seek_medicalcare,
    handle_sell_stock,
)
from python.tooling.handlers.social import (
    handle_attack_person,
    handle_call_person,
    handle_change_status,
    handle_give_item,
    handle_give_money,
    handle_talk_to,
)
from python.tooling.handlers.inventory_loot import (
    handle_drop_item,
    handle_hold_item,
    handle_pick_item,
    try_auto_collect_loot,
)
from python.tooling.handlers.needs import (
    handle_do_hobby,
    handle_sleep,
)

ToolHandler = Callable[[object, object, dict], Tuple[str, bool, int]]

REGISTRY: Dict[str, ToolHandler] = {
    "move_to": handle_move_to,
    "walk": handle_walk,
    "work_job": handle_work_job,
    "get_education": handle_get_education,
    "pick_item": handle_pick_item,
    "hold_item": handle_hold_item,
    "drop_item": handle_drop_item,
    "interact_with": handle_interact_with,
    "buy_item": handle_buy_item,
    "eat_food": handle_eat_food,
    "seek_medicalcare": handle_seek_medicalcare,
    "buy_stock": handle_buy_stock,
    "sell_stock": handle_sell_stock,
    "sleep": handle_sleep,
    "do_hobby": handle_do_hobby,
    "talk_to": handle_talk_to,
    "call_person": handle_call_person,
    "give_item": handle_give_item,
    "give_money": handle_give_money,
    "change_status": handle_change_status,
    "attack_person": handle_attack_person,
}

TASK_ALLOWED = {"interact_with", "pick_item"}

FALLBACK_TOOL_SCHEMAS: Dict[str, set[str]] = {
    "talk_to": {"person", "message"},
    "eat_food": {"item"},
    "buy_item": {"item"},
    "work_job": {"jobname", "hours"},
    "get_education": {"type", "hours"},
    "seek_medicalcare": set(),
    "move_to": {"place"},
    "walk": {"direction"},
    "call_person": {"person", "message"},
    "interact_with": {"person_or_object", "action"},
    "change_status": {"person", "type", "value"},
    "attack_person": {"person"},
    "buy_stock": {"shares"},
    "sell_stock": {"shares"},
    "sleep": {"hours"},
    "do_hobby": {"item"},
    "give_item": {"person", "item"},
    "give_money": {"person", "amount"},
    "pick_item": {"item_name"},
    "hold_item": {"item_name"},
    "drop_item": {"item_name"},
}

try:
    with open(TOOLS_PATH, encoding="utf-8") as f:
        _tools = json.load(f).get("tools", [])
except Exception:
    _tools = []

TOOL_SCHEMAS: Dict[str, set[str]] = dict(FALLBACK_TOOL_SCHEMAS)
for t in _tools:
    name = str(t.get("name", "")).strip()
    if not name:
        continue
    TOOL_SCHEMAS[name] = set(t.get("params", []) or [])


def _validate_schema(name: str, args: dict) -> str | None:
    expected = TOOL_SCHEMAS.get(name)
    if expected is None:
        return f"Tool {name} not found."

    provided = set((args or {}).keys())
    missing = [p for p in expected if p not in provided]
    if missing:
        return f"Missing required parameter(s) for {name}: {', '.join(sorted(missing))}."

    extras = [p for p in provided if p not in expected]
    if extras:
        return f"Unexpected parameter(s) for {name}: {', '.join(sorted(extras))}."

    return None


def _clamp_agent_floor1(agent) -> None:
    if getattr(agent, "z", 0.0) != 0.0:
        agent.z = 0.0
    if hasattr(agent, "vehicle_z") and getattr(agent, "vehicle_z", 0.0) != 0.0:
        agent.vehicle_z = 0.0


def _execute_one(name: str, args: dict, agent, world) -> Tuple[str, bool, int]:
    if agent.is_sleeping and world.sim_time >= agent.busy_until:
        agent.is_sleeping = False
        if agent.task_state == "idle":
            agent.current_activity = "idle"

    try_auto_collect_loot(agent, world)

    if not name:
        agent.failed_calls += 1
        agent.last_parse_error = True
        return "Parse error: No tool name.", False, 60

    schema_err = _validate_schema(name, args or {})
    if schema_err:
        agent.failed_calls += 1
        agent.last_parse_error = True
        return schema_err, False, 60

    if agent.task_state != "idle" and name not in TASK_ALLOWED:
        agent.failed_calls += 1
        return (
            "You are in the middle of a task. You must follow the required next step.",
            False,
            60,
        )

    handler = REGISTRY.get(name)
    if not handler:
        agent.failed_calls += 1
        return f"Tool {name} not found.", False, 60

    try:
        res, suc, cost = handler(agent, world, args)
        if suc:
            _clamp_agent_floor1(agent)
        return res, suc, cost
    except Exception as e:
        agent.failed_calls += 1
        return f"Tool {name} crashed: {type(e).__name__}: {e}", False, 60


def execute_tool(tool_call_str: str, agent_id: int, world) -> Tuple[str, bool, int]:
    calls, parse_error = parse_tool_calls(tool_call_str)

    agent = world.agents.get(agent_id)
    if not agent:
        return "Agent not found.", False, 0
    if not agent.alive:
        return "Agent inactive.", False, 0

    agent._last_api_tool_steps = []

    if parse_error:
        agent.last_parse_error = True
        agent.failed_calls += 1
        return parse_error, False, 60

    agent.last_parse_error = False

    if not calls:
        agent.failed_calls += 1
        agent.last_parse_error = True
        return "Parse error: No tool name.", False, 60

    def new_id() -> str:
        return "call_" + uuid.uuid4().hex

    if len(calls) == 1:
        name, args = calls[0]
        res, suc, cost = _execute_one(name, args, agent, world)
        agent._last_api_tool_steps = [
            {"id": new_id(), "name": name, "args": dict(args or {}), "result": res, "success": bool(suc), "cost": int(cost)}
        ]
        return res, suc, cost

    step_results = []
    all_success = True
    total_cost = 0
    steps = []

    for idx, (name, args) in enumerate(calls, start=1):
        res, suc, cost = _execute_one(name, args, agent, world)
        all_success = all_success and suc
        if suc:
            total_cost += max(0, int(cost))
        else:
            total_cost += max(60, int(cost))

        steps.append({"id": new_id(), "name": name, "args": dict(args or {}), "result": res, "success": bool(suc), "cost": int(cost)})
        step_results.append(f"{idx}. {name}: {'OK' if suc else 'FAIL'} - {res}")

    agent._last_api_tool_steps = steps
    return " | ".join(step_results), all_success, total_cost