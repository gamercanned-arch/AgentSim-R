from __future__ import annotations

from typing import Tuple

from locations import get_current_location_def, get_location_by_name
from tooling.catalogs import EDUCATION_LOCATIONS
from tooling.helpers import (
    can_physically_reach_person,
    canonicalize_item_name,
    check_open_hours,
    is_busy,
    record_expense,
    resolve_workplace_name,
    seconds_until_close,
    store_currently_holding_if_possible,
)
from tooling.scenarios import pick_scenario, pool_key_for_job


def _task_failure(agent, message: str, cost: int = 60) -> Tuple[str, bool, int]:
    task_failures = int(agent.pending_task_data.get("task_failures", 0)) + 1
    agent.pending_task_data["task_failures"] = task_failures

    if task_failures >= 3:
        # clear task
        if agent.currently_holding and agent.currently_holding.get("id") == "job_prop":
            agent.currently_holding = None
        agent.task_state = "idle"
        agent.pending_task_data = {}
        agent.active_task_entities = {}
        if not agent.is_sleeping:
            agent.current_activity = "idle"
        return (f"{message} Task cancelled after 3 failed attempts. You may start over.", False, cost)

    return (f"{message} Failed attempts in this task: {task_failures}/3.", False, cost)


def _clear_task_state(agent, reset_activity: bool = True) -> None:
    if agent.currently_holding and agent.currently_holding.get("id") == "job_prop":
        agent.currently_holding = None
    agent.task_state = "idle"
    agent.pending_task_data = {}
    agent.active_task_entities = {}
    if reset_activity and not agent.is_sleeping:
        agent.current_activity = "idle"


def handle_work_job(agent, world, args: dict):
    if agent.task_state != "idle":
        agent.failed_calls += 1
        return "Already doing a task.", False, 60

    job_raw = str(args.get("jobname", agent.job or "generic")).strip() or (agent.job or "generic")
    try:
        hours = float(args.get("hours", 8))
    except (ValueError, TypeError):
        hours = 8.0
    hours = max(1.0, min(12.0, hours))

    required_energy = hours * 10.0
    if agent.energy < required_energy:
        agent.failed_calls += 1
        return f"Need {required_energy:.1f} energy to spend {hours:.1f}h on this task. Have {agent.energy:.1f}.", False, 60

    here = get_current_location_def(agent.x, agent.y, agent.z)

    workplace_name = resolve_workplace_name(job_raw, agent) or "Generic_Workplace"
    if workplace_name != "Generic_Workplace":
        workplace = get_location_by_name(workplace_name)
        if not workplace:
            agent.failed_calls += 1
            return f"Workplace '{workplace_name}' not found.", False, 60

        if not here or here.name != workplace_name:
            agent.failed_calls += 1
            return (
                f"You must be inside {workplace_name} to work. "
                f"Use move_to(place='{workplace_name}') then walk into the building.",
                False,
                60,
            )

        if not check_open_hours(workplace, world.sim_time):
            agent.failed_calls += 1
            return f"{workplace_name} is currently closed.", False, 60

        remaining = seconds_until_close(workplace, world.sim_time)
        if hours * 3600.0 > remaining:
            agent.failed_calls += 1
            return (
                f"{workplace_name} closes in {remaining / 3600.0:.1f}h. "
                f"Reduce requested work time to {max(0.0, remaining / 3600.0):.1f}h or less.",
                False,
                60,
            )

    pool_key = pool_key_for_job(job_raw, "work_job")
    scenario = pick_scenario(agent, pool_key)

    agent.task_state = "job_pick"
    agent.current_activity = "working"
    agent.pending_task_data = {
        "type": "work_job",
        "hours": hours,
        "job_raw": job_raw,
        "workplace": workplace_name,
        "flavor": scenario,
        "task_failures": 0,
        "pool_key": pool_key,
    }
    agent.active_task_entities = {"prop": scenario["pick"], "target": scenario["obj"], "scenario_id": scenario["id"]}

    return (
        f"[SCENARIO INITIATED] Shift started as {job_raw} at {workplace_name}. "
        f"To begin, use pick_item(item_name='{scenario['pick']}').",
        True,
        60,
    )


def handle_get_education(agent, world, args: dict):
    if agent.task_state != "idle":
        agent.failed_calls += 1
        return "Already doing a task.", False, 60

    study_type = str(args.get("type", "education")).strip() or "education"
    try:
        hours = float(args.get("hours", 8))
    except (ValueError, TypeError):
        hours = 8.0
    hours = max(1.0, min(12.0, hours))

    required_energy = hours * 10.0
    if agent.energy < required_energy:
        agent.failed_calls += 1
        return f"Need {required_energy:.1f} energy to spend {hours:.1f}h on this task. Have {agent.energy:.1f}.", False, 60

    here = get_current_location_def(agent.x, agent.y, agent.z)
    if not here or here.name not in EDUCATION_LOCATIONS:
        agent.failed_calls += 1
        return (
            "You must be inside School or Library to study. "
            "Use move_to(place='School') or move_to(place='Library') then walk inside.",
            False,
            60,
        )

    edu_loc = get_location_by_name(here.name)
    if not edu_loc:
        agent.failed_calls += 1
        return "Education location not found.", False, 60

    if not check_open_hours(edu_loc, world.sim_time):
        agent.failed_calls += 1
        return f"{edu_loc.name} is currently closed.", False, 60

    remaining = seconds_until_close(edu_loc, world.sim_time)
    if hours * 3600.0 > remaining:
        agent.failed_calls += 1
        return (
            f"{edu_loc.name} closes in {remaining / 3600.0:.1f}h. "
            f"Reduce requested study time to {max(0.0, remaining / 3600.0):.1f}h or less.",
            False,
            60,
        )

    lowered = study_type.lower()
    tuition = 2000.0
    if "phd" in lowered or "doctorate" in lowered:
        tuition = 8000.0
    elif "master" in lowered:
        tuition = 4000.0

    # student discount
    if "student" in (agent.job or "").lower():
        tuition = min(tuition, 150.0)

    if agent.money < tuition:
        agent.failed_calls += 1
        return f"Cannot afford tuition (${tuition:.2f}).", False, 60

    agent.money -= tuition
    record_expense(agent, tuition)
    agent.pending_notifications.append(f"Paid ${tuition:.2f} in tuition fees.")

    pool_key = "education"
    scenario = pick_scenario(agent, pool_key)

    agent.task_state = "job_pick"
    agent.current_activity = "studying"
    agent.pending_task_data = {
        "type": "get_education",
        "hours": hours,
        "job_raw": study_type,
        "workplace": edu_loc.name,
        "flavor": scenario,
        "task_failures": 0,
        "pool_key": pool_key,
    }
    agent.active_task_entities = {"prop": scenario["pick"], "target": scenario["obj"], "scenario_id": scenario["id"]}

    return (
        f"[SCENARIO INITIATED] Study session started for {study_type} at {edu_loc.name}. "
        f"To begin, use pick_item(item_name='{scenario['pick']}').",
        True,
        60,
    )


def handle_pick_item(agent, world, args: dict):
    # This handler supports task props now; full ground/corpse pickup will be moved to inventory_loot.py next batch.
    raw_item = str(args.get("item_name", "")).strip()

    if raw_item.lower() in ["none", "store", "unequip", "put away", ""]:
        if agent.currently_holding:
            if len(agent.inventory) >= 20:
                agent.failed_calls += 1
                return "Inventory full. Cannot store held item.", False, 30
            held_name = agent.currently_holding["item"]
            agent.inventory.append(agent.currently_holding)
            agent.currently_holding = None
            return f"Stored {held_name} back in inventory.", True, 30
        agent.failed_calls += 1
        return "You aren't holding anything to store.", False, 30

    item = canonicalize_item_name(raw_item)

    # Task prop step
    if agent.task_state == "job_pick":
        flavor = agent.pending_task_data.get("flavor", {}) or {}
        required = str(flavor.get("pick", "")).strip()
        if not required:
            agent.failed_calls += 1
            return _task_failure(agent, "Task is missing required prop.", 30)

        if item.lower() != required.lower():
            agent.failed_calls += 1
            return _task_failure(agent, f"You need to pick_item '{required}' to do this task.", 30)

        ok, why = store_currently_holding_if_possible(agent)
        if not ok:
            agent.failed_calls += 1
            return why, False, 30

        agent.currently_holding = {"id": "job_prop", "item": required, "durability": 99}
        agent.task_state = "job_mcq"
        return (
            f"[TASK] You grabbed the required prop: {required}. "
            f"Now answer by interacting with '{flavor.get('obj','')}'. "
            f"Question: {flavor.get('q','')} "
            f"Choices: A) {flavor.get('choices',{}).get('A','')} "
            f"B) {flavor.get('choices',{}).get('B','')} "
            f"C) {flavor.get('choices',{}).get('C','')}. "
            f"Use interact_with(person_or_object='{flavor.get('obj','')}', action='A' or 'B' or 'C').",
            True,
            60,
        )

    # Non-task: simple inventory->hand move (full loot support later)
    idx = next((i for i, it in enumerate(agent.inventory) if it.get("item", "").lower() == item.lower()), -1)
    if idx != -1:
        if agent.currently_holding:
            ok, why = store_currently_holding_if_possible(agent)
            if not ok:
                agent.failed_calls += 1
                return why, False, 30
        agent.currently_holding = agent.inventory.pop(idx)
        return f"Now holding {agent.currently_holding['item']} in hand.", True, 30

    agent.failed_calls += 1
    return f"Item {item} not in inventory or nearby.", False, 60


def handle_interact_with(agent, world, args: dict):
    target = str(args.get("person_or_object", "")).strip()
    action = str(args.get("action", "")).strip()

    # Block pseudo-work/study when idle
    if agent.task_state == "idle":
        act_norm = action.lower()
        if any(k in act_norm for k in ("work", "study", "shift", "job", "exam", "earn", "salary")):
            agent.failed_calls += 1
            return (
                "This does not count as paid work/study. Use work_job(...) or get_education(...) to start a task.",
                False,
                60,
            )

    # MCQ resolution
    if agent.task_state == "job_mcq":
        flavor = agent.pending_task_data.get("flavor", {}) or {}
        required_target = str(flavor.get("obj", "")).strip()

        if target.lower() != required_target.lower():
            agent.failed_calls += 1
            return _task_failure(agent, f"You must interact_with '{required_target}' to complete the task.", 60)

        data = dict(agent.pending_task_data)
        if agent.currently_holding and agent.currently_holding.get("id") == "job_prop":
            agent.currently_holding = None

        busy_activity = "studying" if data.get("type") == "get_education" else "working"
        _clear_task_state(agent, reset_activity=False)
        agent.current_activity = busy_activity

        time_cost = int(float(data.get("hours", 1.0)) * 3600)
        agent.energy = max(0.0, agent.energy - float(data.get("hours", 1.0)) * 10.0)
        correct = str(flavor.get("ans", "B")).lower() in action.lower()

        if data.get("type") == "get_education":
            edu_gain = 5.0 if correct else 1.0
            wage_gain = 5.0 if correct else 1.0
            agent.education = min(100.0, agent.education + edu_gain)
            agent.hourly_wage += wage_gain
            return (
                f"Exam finished. Correct? {correct}. Education +{edu_gain:.1f}, Wage +{wage_gain:.1f}. "
                f"Time passed: {float(data.get('hours',1.0)):.1f}h. DND active.",
                True,
                time_cost,
            )

        pay = agent.hourly_wage * float(data.get("hours", 1.0)) * (world.market_price / 100.0)
        if not correct:
            pay *= 0.5
        agent.money += pay
        return (
            f"Task resolved. Correct? {correct}. Earned ${pay:.2f}. "
            f"Time passed: {float(data.get('hours',1.0)):.1f}h. DND active.",
            True,
            time_cost,
        )

    if agent.task_state == "job_pick":
        agent.failed_calls += 1
        return _task_failure(agent, "You need to pick up the required task item first.", 60)

    # Person interaction (nearby)
    target_agent = next((a for a in world.agents.values() if a.alive and a.name.lower() == target.lower()), None)
    if target_agent:
        if is_busy(target_agent, world.sim_time):
            agent.failed_calls += 1
            return f"{target_agent.name} is currently busy/sleeping (DND).", False, 60

        ok, reason = can_physically_reach_person(agent, target_agent, 20.0)
        if not ok:
            agent.failed_calls += 1
            return reason, False, 60

        # small social bump (kept here for now; will be centralized in social.py later)
        agent.relationships = min(25.0, agent.relationships + 0.15)
        target_agent.relationships = min(25.0, target_agent.relationships + 0.10)
        target_agent.pending_notifications.append(f"{agent.name} interacted with you ({action}).")
        return f"Interacted with {target_agent.name}.", True, 60

    # Object interaction (cosmetic unless it changes floors)
    loc = get_current_location_def(agent.x, agent.y, agent.z)
    if loc:
        for obj in loc.interactables:
            if obj["name"].lower() != target.lower():
                continue
            if abs(float(obj.get("z", 0.0)) - agent.z) > 1.0:
                continue
            if "target_z" in obj:
                agent.z = float(obj["target_z"])
                return f"Used {target}. Moved to floor Z={agent.z}.", True, 60
            return f"Used {target} ({action}). (No job/study progress.)", True, 60

    agent.failed_calls += 1
    return f"No nearby visible object named '{target}' found on your current floor.", False, 60