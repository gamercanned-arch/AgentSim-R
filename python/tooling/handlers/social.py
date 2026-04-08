from __future__ import annotations
import random
import re
import uuid
from copy import deepcopy
from python.config import MAX_INVENTORY, STATUS_MAX_DISTANCE
from python.tooling.death import kill_agent
from python.tooling.helpers import (
    can_physically_reach_person,
    canonicalize_item_name,
    find_agent_by_name,
    is_busy,
    normalize_label,
)
MAX_SOCIAL_MESSAGE_LEN = 240
def _clean_social_message(message: str, max_len: int = MAX_SOCIAL_MESSAGE_LEN) -> str:
    s = "" if message is None else str(message)
    s = s.replace("\x00", "")
    s = s.replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n", s).strip()
    orig_len = len(s)
    if orig_len > max_len:
        s = s[: max_len - 20] + f"... ({orig_len} chars)"
    return s
def _social_bump(a, b=None, amount: float = 0.2) -> None:
    a.relationships = min(25.0, a.relationships + amount)
    if b is not None:
        b.relationships = min(25.0, b.relationships + amount * 0.75)
def _social_penalty(a, b=None, amount: float = 0.8) -> None:
    a.relationships = max(0.0, a.relationships - amount * 0.2)
    if b is not None:
        b.relationships = max(0.0, b.relationships - amount)
def _enqueue_missed_interaction(target, text_busy: str, text_sleeping: str) -> None:
    if getattr(target, "is_sleeping", False):
        target.pending_notifications.append(text_sleeping)
    else:
        target.pending_notifications.append(text_busy)
def _leave_voicemail(
    target, from_agent, message: str, sim_time: float, max_keep: int = 30
) -> None:
    if not hasattr(target, "voicemail_inbox") or target.voicemail_inbox is None:
        target.voicemail_inbox =[]
    target.voicemail_inbox.append(
        {
            "id": str(uuid.uuid4()),
            "from": from_agent.name,
            "time": float(sim_time),
            "message": _clean_social_message(message),
        }
    )
    if len(target.voicemail_inbox) > max_keep:
        target.voicemail_inbox = target.voicemail_inbox[-max_keep:]
def _cancel_task_if_any(agent, current_time: float) -> None:
    if getattr(agent, "task_state", "idle") == "idle":
        return
    spent = agent.pending_task_data.get("energy_spent", 0.0)
    start = agent.pending_task_data.get("start_time", current_time)
    elapsed_hours = max(0.0, (current_time - start) / 3600.0)
    energy_used = elapsed_hours * 10.0
    refund = max(0.0, spent - energy_used)
    agent.energy = min(100.0, agent.energy + refund)
    if (
        getattr(agent, "currently_holding", None)
        and agent.currently_holding.get("id") == "job_prop"
    ):
        agent.currently_holding = None
    agent.task_state = "idle"
    agent.pending_task_data = {}
    agent.active_task_entities = {}
    if not getattr(agent, "is_sleeping", False):
        agent.current_activity = "idle"
def handle_talk_to(agent, world, args: dict):
    t_name = str(args.get("person", "")).strip()
    msg = _clean_social_message(args.get("message", ""))
    target = find_agent_by_name(world, t_name)
    if not target or not target.alive:
        agent.failed_calls += 1
        return "Target not found.", False, 60
    ok, reason = can_physically_reach_person(agent, target, 50.0)
    if not ok:
        agent.failed_calls += 1
        return "Cannot reach target." if reason == "Too far." else reason, False, 60
    if is_busy(target, world.sim_time):
        _enqueue_missed_interaction(
            target,
            text_busy=(
                f'Missed in-person talk: {agent.name} tried to talk to you ("{msg}"), '
                "but you were busy. Maybe try contacting them?"
            ),
            text_sleeping=(
                f'Missed in-person talk: {agent.name} tried to talk to you ("{msg}"), '
                "but you were sleeping."
            ),
        )
        agent.failed_calls += 1
        return f"{target.name} is currently busy or sleeping (DND).", False, 60
    _social_bump(agent, target, 0.2)
    target.pending_notifications.append(f"{agent.name} said: {msg}")
    for other in world.agents.values():
        if not other.alive or other.id in (agent.id, target.id):
            continue
        if is_busy(other, world.sim_time):
            continue
        ok2, _ = can_physically_reach_person(agent, other, 50.0)
        if ok2:
            other.pending_notifications.append(
                f"Overheard {agent.name} say to {target.name}: '{msg}'"
            )
    return f"Talked to {target.name}.", True, 60
def handle_call_person(agent, world, args: dict):
    t_name = str(args.get("person", "")).strip()
    msg = _clean_social_message(args.get("message", ""))
    target = find_agent_by_name(world, t_name)
    if not target or not target.alive:
        agent.failed_calls += 1
        return "Target not found.", False, 60
    if is_busy(target, world.sim_time):
        _leave_voicemail(target, agent, msg, world.sim_time)
        _social_bump(agent, target, 0.1)
        return f"Call to {target.name} went to voicemail. Voicemail left.", True, 60
    _social_bump(agent, target, 0.1)
    target.pending_notifications.append(f"Phone Call from {agent.name}: {msg}")
    return f"Called {target.name}.", True, 60
def handle_give_item(agent, world, args: dict):
    t_name = str(args.get("person", "")).strip()
    item_name = canonicalize_item_name(str(args.get("item", "")).strip())
    target = find_agent_by_name(world, t_name)
    if not target or not target.alive:
        agent.failed_calls += 1
        return "Target not found.", False, 60
    ok, reason = can_physically_reach_person(agent, target, 20.0)
    if not ok:
        agent.failed_calls += 1
        return reason, False, 60
    item_data = None
    source = None
    if agent.currently_holding and normalize_label(
        agent.currently_holding.get("item", "")
    ) == normalize_label(item_name):
        item_data = agent.currently_holding
        source = "hand"
        agent.currently_holding = None
    else:
        idx = next(
            (
                i
                for i, it in enumerate(agent.inventory)
                if normalize_label(it.get("item", "")) == normalize_label(item_name)
            ),
            -1,
        )
        if idx != -1:
            item_data = agent.inventory.pop(idx)
            source = "inventory"
    if not item_data:
        agent.failed_calls += 1
        return f"You don't have {item_name} in your hand or inventory.", False, 60
    if is_busy(target, world.sim_time):
        if not hasattr(world, "pending_deliveries") or world.pending_deliveries is None:
            world.pending_deliveries =[]
        world.pending_deliveries.append(
            {
                "id": str(uuid.uuid4()),
                "kind": "item",
                "from_id": agent.id,
                "to_id": target.id,
                "item": deepcopy(item_data),
                "created_at": float(world.sim_time),
                "x": float(agent.x),
                "y": float(agent.y),
                "z": 0.0, 
            }
        )
        _enqueue_missed_interaction(
            target,
            text_busy=(
                f"{agent.name} tried to give you {item_data.get('item','Unknown')}, but you were busy. "
                "Delivery has been queued and will arrive when you are available."
            ),
            text_sleeping=(
                f"{agent.name} tried to give you {item_data.get('item','Unknown')}, but you were sleeping. "
                "Delivery has been queued and will arrive when you are available."
            ),
        )
        agent.pending_notifications.append(
            f"Queued item delivery: {item_data.get('item','Unknown')} -> {target.name}."
        )
        return f"{target.name} is busy/sleeping. Item delivery queued.", True, 60
    if len(target.inventory) >= MAX_INVENTORY:
        if source == "hand":
            agent.currently_holding = item_data
        elif source == "inventory":
            agent.inventory.append(item_data)
        else:
            if len(agent.inventory) < MAX_INVENTORY:
                agent.inventory.append(item_data)
            else:
                world.ground_items.append(
                    {
                        "id": str(uuid.uuid4()),
                        "item": item_data.get("item", "Unknown"),
                        "durability": item_data.get("durability", 5),
                        "bought": item_data.get("bought", world.sim_time),
                        "x": float(agent.x),
                        "y": float(agent.y),
                        "z": 0.0, 
                        "dropper_id": agent.id,
                        "repickup_block_until": world.sim_time,
                    }
                )
        agent.failed_calls += 1
        return f"{target.name}'s inventory is full.", False, 60
    target.inventory.append(item_data)
    _social_bump(agent, target, 0.25)
    target.pending_notifications.append(f"{agent.name} gave you {item_data.get('item','Unknown')}.")
    return f"Gave {item_data.get('item','Unknown')} to {target.name}.", True, 60
def handle_give_money(agent, world, args: dict):
    t_name = str(args.get("person", "")).strip()
    try:
        amount = float(args.get("amount", 0))
    except (ValueError, TypeError):
        amount = 0.0
    if amount <= 0:
        agent.failed_calls += 1
        return "Invalid amount.", False, 60
    target = find_agent_by_name(world, t_name)
    if not target or not target.alive:
        agent.failed_calls += 1
        agent.pending_notifications.append(
            f"Bank transfer failed: recipient '{t_name}' not found or not alive."
        )
        return "Recipient not found.", False, 60
    if agent.money < amount:
        agent.failed_calls += 1
        agent.pending_notifications.append(
            f"Bank transfer to {target.name} failed: insufficient funds for ${amount:.2f}."
        )
        target.pending_notifications.append(
            f"Bank transfer from {agent.name} failed: insufficient funds for ${amount:.2f}."
        )
        return "Not enough money.", False, 60
    
    agent.money -= amount
    target.money += amount
    _social_bump(agent, target, 0.2)
    if getattr(target, "is_sleeping", False):
        target.pending_notifications.append(f"While you were sleeping, {agent.name} transferred you ${amount:.2f}.")
    else:
        target.pending_notifications.append(f"{agent.name} transferred you ${amount:.2f}.")
    return f"Transferred ${amount:.2f} to {target.name}.", True, 60
def handle_change_status(agent, world, args: dict):
    value = str(args.get("value", "")).strip()
    person = str(args.get("person", "")).strip()
    rel_type = normalize_label(str(args.get("type", "")).strip())
    if value:
        agent.beliefs = value
        return f'Belief/Goal updated to: "{value}".', True, 30
    if person and rel_type:
        target = find_agent_by_name(world, person)
        if not target or not target.alive:
            agent.failed_calls += 1
            return f"Person '{person}' not found.", False, 60
        ok, _reason = can_physically_reach_person(agent, target, STATUS_MAX_DISTANCE)
        if not ok:
            agent.failed_calls += 1
            return (
                f"You must be within {STATUS_MAX_DISTANCE:.0f}m on the same floor to change relationship status.",
                False,
                60,
            )
        if is_busy(target, world.sim_time):
            agent.failed_calls += 1
            return f"{target.name} is currently busy or sleeping (DND).", False, 60
        req_key = normalize_label(person)
        if agent.pending_status_requests.get(req_key) == rel_type:
            if rel_type == "single":
                agent.relationship_partner = ""
                target.relationship_partner = ""
            else:
                agent.relationship_partner = target.name
                target.relationship_partner = agent.name
            agent.relationships_status = rel_type
            target.relationships_status = rel_type
            del agent.pending_status_requests[req_key]
            _social_bump(agent, target, 0.4)
            target.pending_notifications.append(
                f"{agent.name} accepted status: {rel_type}."
            )
            return f"Status with {target.name} changed to: {rel_type}.", True, 30
        target.pending_status_requests[normalize_label(agent.name)] = rel_type
        target.pending_notifications.append(
            f"{agent.name} requested relationship status: {rel_type}."
        )
        return f"Requested status change to '{rel_type}' with {target.name}.", True, 30
    agent.failed_calls += 1
    return "Invalid parameters.", False, 60
def handle_attack_person(agent, world, args: dict):
    t_name = str(args.get("person", "")).strip()
    target = find_agent_by_name(world, t_name)
    if not target or not target.alive:
        agent.failed_calls += 1
        return "Target not found.", False, 60
    ok, reason = can_physically_reach_person(agent, target, 20.0)
    if not ok:
        agent.failed_calls += 1
        return reason, False, 60
    
    if getattr(target, "task_state", "idle") != "idle":
        _cancel_task_if_any(target, world.sim_time)
        target.busy_until = min(float(target.busy_until), float(world.sim_time))
        target.pending_notifications.append(
            "URGENT: Your task was interrupted by an attack!"
        )
    elif getattr(target, "is_sleeping", False):
        target.is_sleeping = False
        target.current_activity = "idle"
        target.busy_until = min(float(target.busy_until), float(world.sim_time))
        target.pending_notifications.append("URGENT: You were attacked while sleeping!")
    else:
        if float(target.busy_until) > float(world.sim_time):
            agent.failed_calls += 1
            return (
                f"{target.name} is currently busy. Cannot attack right now.",
                False,
                60,
            )
    damage = random.uniform(5.0, 25.0)
    target.health -= damage
    target.stress = min(100.0, target.stress + 15.0)
    _social_penalty(agent, target, 0.8)
    target.pending_notifications.append(f"URGENT: {agent.name} attacked you!")
    if target.health <= 0.0:
        kill_agent(target, world, cause=f"killed by {agent.name}")
        return f"Killed {target.name}.", True, 60
    return f"Attacked {target.name} for {damage:.1f} damage.", True, 60
