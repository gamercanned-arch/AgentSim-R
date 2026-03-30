from __future__ import annotations

from typing import Callable, Dict, Tuple

from tooling.parsing import parse_tool_call

# Handlers
from tooling.handlers.movement import handle_move_to, handle_walk
from tooling.handlers.workstudy import (
    handle_get_education,
    handle_interact_with,
    handle_work_job,
)
from tooling.handlers.economy import (
    handle_buy_item,
    handle_buy_stock,
    handle_eat_food,
    handle_seek_medicalcare,
    handle_sell_stock,
)
from tooling.handlers.social import (
    handle_attack_person,
    handle_call_person,
    handle_change_status,
    handle_give_item,
    handle_give_money,
    handle_talk_to,
)
from tooling.handlers.inventory_loot import (
    handle_drop_item,
    handle_hold_item,
    handle_pick_item,
    try_auto_collect_loot,
)
from tooling.handlers.needs import (
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

TASK_ALLOWED = {"interact_with", "pick_item", "hold_item", "drop_item"}


def execute_tool(tool_call_str: str, agent_id: int, world) -> Tuple[str, bool, int]:
    name, args = parse_tool_call(tool_call_str)

    agent = world.agents.get(agent_id)
    if not agent:
        return "Agent not found.", False, 0
    if not agent.alive:
        return "Agent inactive.", False, 0

    if agent.is_sleeping and world.sim_time >= agent.busy_until:
        agent.is_sleeping = False
        if agent.task_state == "idle":
            agent.current_activity = "idle"

    try_auto_collect_loot(agent, world)

    if isinstance(name, str) and name.startswith("Parse error"):
        agent.last_parse_error = True
        agent.failed_calls += 1
        return name, False, 60
    agent.last_parse_error = False

    if not name:
        agent.failed_calls += 1
        return "Parse error: No tool name.", False, 60

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

    return handler(agent, world, args)