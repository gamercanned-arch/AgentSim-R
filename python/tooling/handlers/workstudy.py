from __future__ import annotations
import re
from typing import Tuple
from python.locations import get_current_location_def, get_location_by_name
from python.tooling.catalogs import EDUCATION_LOCATIONS
from python.tooling.helpers import (
    busy_reason,
    can_physically_reach_person,
    check_open_hours,
    is_unavailable,
    normalize_label,
    record_expense,
    resolve_workplace_name,
    seconds_until_close,
)
from python.tooling.scenarios import pick_scenario, pool_key_for_job

def _task_failure(agent, world, message: str, cost: int = 60) -> Tuple[str, bool, int]:
    task_failures = int(agent.pending_task_data.get("task_failures", 0)) + 1
    agent.pending_task_data["task_failures"] = task_failures
    if task_failures >= 3:
        is_education = agent.pending_task_data.get("type") == "get_education"
        if not is_education:
            agent.hourly_wage = max(0.0, agent.hourly_wage - 1.0)
        _clear_task_state(agent, world, current_time=float(getattr(agent, 'busy_until', 0.0)))
        msg = f"{message} Task cancelled after 3 failed attempts."
        if not is_education:
            msg += " Wage penalized -1.0."
        msg += " You may start over."
        return (msg, False, cost)
    return (f"{message} Failed attempts in this task: {task_failures}/3.", False, cost)

def _clear_task_state(agent, world, current_time: float, reset_activity: bool = True, refund: bool = True) -> None:
    if agent.task_state != "idle":
        if refund:
            spent = agent.pending_task_data.get("energy_spent", 0.0)
            start = agent.pending_task_data.get("start_time", current_time)
            elapsed_hours = max(0.0, (current_time - start) / 3600.0)
            energy_used = elapsed_hours * 10.0
            refund_val = max(0.0, spent - energy_used)
            agent.energy = min(100.0, agent.energy + refund_val)
            
            if agent.pending_task_data.get("type") == "get_education":
                tuition_paid = agent.pending_task_data.get("tuition_paid", 0.0)
                if tuition_paid > 0:
                    ratio = min(1.0, elapsed_hours / max(0.1, float(agent.pending_task_data.get("hours", 1.0))))
                    t_refund = tuition_paid * (1.0 - ratio)
                    agent.money += t_refund
                    agent.expenses = max(0.0, agent.expenses - t_refund)
                    agent.total_expenses = max(0.0, agent.total_expenses - t_refund)
    if agent.currently_holding and agent.currently_holding.get("id") == "job_prop":
        agent.currently_holding = None
    agent.task_state = "idle"
    agent.pending_task_data = {}
    agent.active_task_entities = {}
    if reset_activity and not getattr(agent, "is_sleeping", False):
        agent.current_activity = "idle"

def _extract_choice_letter(action: str) -> str:
    text = str(action or "").strip()
    m = re.fullmatch(r"""(?:answer\s*:?\s*)?['"]?\s*([ABCabc])\s*['"]?""", text, flags=re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return ""

def _task_location_ok(agent) -> bool:
    here = get_current_location_def(agent.x, agent.y, agent.z)
    workplace = str(agent.pending_task_data.get("workplace", "")).strip()
    return bool(here and workplace and here.name == workplace)

def _object_visible_here(agent, target_name: str, allow_task_target: bool = False) -> bool:
    here = get_current_location_def(agent.x, agent.y, agent.z)
    if not here:
        return False
    if "Outside" in agent.location and here.has_roof:
        return False
        
    wanted = normalize_label(target_name)
    for obj in here.interactables:
        if normalize_label(obj["name"]) != wanted:
            continue
        if abs(float(obj.get("z", 0.0)) - agent.z) > 1.0:
            continue
        return True
    if allow_task_target:
        task_entities = getattr(agent, "active_task_entities", {}) or {}
        target = str(task_entities.get("target", "")).strip()
        location = str(task_entities.get("location", "")).strip()
        if target and normalize_label(target) == wanted and location == here.name:
            return True
    return False

def _task_target_ok(agent, target: str) -> bool:
    task_entities = getattr(agent, "active_task_entities", {}) or {}
    required_target = str(task_entities.get("target", "")).strip()
    if not required_target:
        return False
    if normalize_label(target) != normalize_label(required_target):
        return False
    return _object_visible_here(agent, required_target, allow_task_target=True)

def handle_work_job(agent, world, args: dict):
    if agent.task_state != "idle":
        agent.failed_calls += 1
        return "Already doing a task.", False, 60
        
    if agent.stress > 99.0:
        agent.failed_calls += 1
        return "Stress was too high, consider sleeping or doing a hobby first.", False, 60
        
    job_raw = str(args.get("jobname", agent.job or "")).strip() or (agent.job or "")
    try:
        hours = float(args.get("hours", 8))
    except (ValueError, TypeError):
        hours = 8.0
    hours = max(1.0, min(10.0, hours))
    required_energy = hours * 10.0
    
    if agent.energy < required_energy:
        agent.failed_calls += 1
        return (
            f"Need {required_energy:.1f} energy to spend {hours:.1f}h on this task. Have {agent.energy:.1f}.",
            False,
            60,
        )
    workplace_name = resolve_workplace_name(job_raw, agent)
    if not workplace_name:
        agent.failed_calls += 1
        return (
            f"Invalid or unsupported job '{job_raw}'. Use a valid jobname for your workplace.",
            False,
            60,
        )
    here = get_current_location_def(agent.x, agent.y, agent.z)
    workplace = get_location_by_name(workplace_name)
    if not workplace:
        agent.failed_calls += 1
        return f"Workplace '{workplace_name}' not found.", False, 60
    if not here or here.name != workplace_name or "Outside" in agent.location:
        agent.failed_calls += 1
        return (
            f"You must be inside {workplace_name} to work. "
            f"Use move_to for {workplace_name}, then walk into the building.",
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
        
    agent.energy -= required_energy
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
        "energy_spent": required_energy,
        "start_time": float(world.sim_time),
    }
    agent.active_task_entities = {
        "prop": scenario["pick"],
        "target": scenario["obj"],
        "scenario_id": scenario["id"],
        "location": workplace_name,
    }
    return (
        f"Shift started as {job_raw} at {workplace_name}. Energy deducted upfront. "
        f"Next step: pick up the required task prop {scenario['pick']}.",
        True,
        60,
    )

def handle_get_education(agent, world, args: dict):
    if agent.task_state != "idle":
        agent.failed_calls += 1
        return "Already doing a task.", False, 60
        
    if agent.stress > 99.0:
        agent.failed_calls += 1
        return "Stress was too high, consider sleeping or doing a hobby first.", False, 60
        
    study_type = str(args.get("type", "education")).strip() or "education"
    try:
        hours = float(args.get("hours", 8))
    except (ValueError, TypeError):
        hours = 8.0
    hours = max(1.0, min(10.0, hours))
    required_energy = hours * 10.0
    if agent.energy < required_energy:
        agent.failed_calls += 1
        return (
            f"Need {required_energy:.1f} energy to spend {hours:.1f}h on this task. Have {agent.energy:.1f}.",
            False,
            60,
        )
    here = get_current_location_def(agent.x, agent.y, agent.z)
    if not here or here.name not in EDUCATION_LOCATIONS or "Outside" in agent.location:
        agent.failed_calls += 1
        return (
            "You must be inside School or Library to study. "
            "Use move_to for School or Library, then walk inside.",
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
    if "student" in (agent.job or "").lower():
        tuition = min(tuition, 150.0)
    if agent.money < tuition:
        agent.failed_calls += 1
        return f"Cannot afford tuition (${tuition:.2f}).", False, 60
        
    agent.money -= tuition
    record_expense(agent, tuition)
    agent.pending_notifications.append(f"Paid ${tuition:.2f} in tuition fees.")
    agent.energy -= required_energy
    
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
        "energy_spent": required_energy,
        "tuition_paid": tuition,
        "start_time": float(world.sim_time),
    }
    agent.active_task_entities = {
        "prop": scenario["pick"],
        "target": scenario["obj"],
        "scenario_id": scenario["id"],
        "location": edu_loc.name,
    }
    return (
        f"Study session started for {study_type} at {edu_loc.name}. Energy deducted upfront. "
        f"Next step: pick up the required task prop {scenario['pick']}.",
        True,
        60,
    )

def handle_interact_with(agent, world, args: dict):
    target = str(args.get("person_or_object", "")).strip()
    action = str(args.get("action", "")).strip()
    
    if agent.task_state == "idle":
        act_norm = normalize_label(action)
        if any(re.search(r'\b' + k + r'\b', act_norm) for k in ("work", "study", "shift", "job", "exam", "earn", "salary")):
            agent.failed_calls += 1
            return (
                "This does not count as paid work or study. Use work_job or get_education to start a task.",
                False,
                60,
            )
            
    if agent.task_state == "job_mcq":
        flavor = agent.pending_task_data.get("flavor", {}) or {}
        required_target = str(flavor.get("obj", "")).strip()
        if not _task_location_ok(agent):
            agent.failed_calls += 1
            return _task_failure(agent, world, "You left the required task location.", 60)
        if not _task_target_ok(agent, target) or normalize_label(target) != normalize_label(required_target):
            agent.failed_calls += 1
            return _task_failure(
                agent,
                world,
                f"You must interact with {required_target} to complete the task.",
                60,
            )
        choice = _extract_choice_letter(action)
        if choice not in {"A", "B", "C"}:
            agent.failed_calls += 1
            return _task_failure(agent, world, "Answer must clearly be A, B, or C.", 60)
            
        data = dict(agent.pending_task_data)
        if agent.currently_holding and agent.currently_holding.get("id") == "job_prop":
            agent.currently_holding = None
            
        busy_activity = "studying" if data.get("type") == "get_education" else "working"
        _clear_task_state(agent, world, world.sim_time, reset_activity=False, refund=False)
        agent.current_activity = busy_activity
        
        hours = float(data.get("hours", 1.0))
        time_cost = int(hours * 3600)
        correct = choice == str(flavor.get("ans", "B")).strip().upper()
        
        if data.get("type") == "get_education":
            edu_gain = 5.0 if correct else 1.0
            wage_gain = 5.0 if correct else 1.0
            agent.education = min(100.0, agent.education + edu_gain)
            agent.hourly_wage = min(200.0, agent.hourly_wage + wage_gain)
            
            agent._work_meta = {
                "start_time": float(world.sim_time),
                "total_time": float(time_cost),
                "pay": 0.0,
                "edu_gain": float(edu_gain),
                "wage_gain": float(wage_gain),
                "energy_spent": float(data.get("energy_spent", 0.0)),
                "tuition_paid": float(data.get("tuition_paid", 0.0))
            }
            
            return (
                f"Exam finished. Correct? {correct}. Education +{edu_gain:.1f}, Wage +{wage_gain:.1f}. "
                f"Time passed: {hours:.1f}h. DND active.",
                True,
                time_cost,
            )
            
        pay = agent.hourly_wage * hours * (world.market_price / 100.0)
        if not correct:
            pay *= 0.5
        agent.money += pay
        
        agent._work_meta = {
            "start_time": float(world.sim_time),
            "total_time": float(time_cost),
            "pay": float(pay),
            "edu_gain": 0.0,
            "wage_gain": 0.0,
            "energy_spent": float(data.get("energy_spent", 0.0))
        }
        
        return (
            f"Task resolved. Correct? {correct}. Earned ${pay:.2f}. "
            f"Time passed: {hours:.1f}h. DND active.",
            True,
            time_cost,
        )
        
    if agent.task_state == "job_pick":
        agent.failed_calls += 1
        return _task_failure(agent, world, "You need to pick up the required task prop first.", 60)
        
    target_agent = next(
        (a for a in world.agents.values() if a.alive and normalize_label(a.name) == normalize_label(target)),
        None,
    )
    if target_agent:
        if getattr(target_agent, "current_activity", "") == "moving":
            agent.failed_calls += 1
            return "Target is currently in transit. Call them or wait until they arrive.", False, 60
        if is_unavailable(target_agent, world.sim_time):
            reason = busy_reason(target_agent, world.sim_time)
            agent.failed_calls += 1
            return (f"{target_agent.name} is currently {reason} (unavailable).", False, 60)
        ok, reason = can_physically_reach_person(agent, target_agent, 20.0)
        if not ok:
            agent.failed_calls += 1
            return reason, False, 60
        agent.relationships = min(25.0, agent.relationships + 0.15)
        target_agent.relationships = min(25.0, target_agent.relationships + 0.10)
        target_agent.pending_notifications.append(f"{agent.name} interacted with you ({action}).")
        
        from python.scheduler import _apply_interruption_rollback
        _apply_interruption_rollback(target_agent, world)
        return f"Interacted with {target_agent.name}.", True, 60
        
    if not _object_visible_here(agent, target, allow_task_target=False):
        agent.failed_calls += 1
        return (f"No nearby visible object named '{target}' found on your current floor.", False, 60)
        
    loc = get_current_location_def(agent.x, agent.y, agent.z)
    if loc:
        for obj in loc.interactables:
            if normalize_label(obj["name"]) != normalize_label(target):
                continue
            if abs(float(obj.get("z", 0.0)) - agent.z) > 1.0:
                continue
            if "target_z" in obj:
                agent.z = float(obj["target_z"])
                return f"Used {obj['name']} ({action}). Elevation changed to Z={agent.z:.1f}.", True, 60
            return f"Used {obj['name']} ({action}).", True, 60
            
    agent.failed_calls += 1
    return (f"No nearby visible object named '{target}' found on your current floor.", False, 60)
