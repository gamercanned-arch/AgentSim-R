from __future__ import annotations

import random
import uuid
from copy import deepcopy

from config import MAX_INVENTORY, STATUS_MAX_DISTANCE
from tooling.death import kill_agent
from tooling.helpers import (
    can_physically_reach_person,
    canonicalize_item_name,
    find_agent_by_name,
    is_busy,
    normalize_label,
)


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


def _leave_voicemail(target, from_agent, message: str, sim_time: float, max_keep: int = 30) -> None:
    if not hasattr(target, "voicemail_inbox") or target.voicemail_inbox is None:
        target.voicemail_inbox = []
    target.voicemail_inbox.append(
        {
            "id": str(uuid.uuid4()),
            "from": from_agent.name,
            "time": float(sim_time),
            "message": str(message),
        }
    )
    # Keep only most recent max_keep
    if len(target.voicemail_inbox) > max_keep:
        target.voicemail_inbox = target.voicemail_inbox[-max_keep:]


def _cancel_task_if_any(agent) -> None:
    if getattr(agent, "task_state", "idle") == "idle":
        return
    if getattr(agent, "currently_holding", None) and agent.currently_holding.get("id") == "job_prop":
        agent.currently_holding = None
    agent.task_state = "idle"
    agent.pending_task_data = {}
    agent.active_task_entities = {}
    if not getattr(agent, "is_sleeping", False):
        agent.current_activity = "idle"


def handle_talk_to(agent, world, args: dict):
    t_name = str(args.get("person", "")).strip()
    msg = str(args.get("message", "")).strip()

    target = find_agent_by_name(world, t_name)
    if not target or not target.alive:
        agent.failed_calls += 1
        return "Target not found.", False, 60

    if is_busy(target, world.sim_time):
        _enqueue_missed_interaction(
            target,
            text_busy=(
                f"Missed in-person talk: {agent.name} tried to talk to you (\"{msg}\"), "
                "but you were busy. Maybe try contacting them?"
            ),
            text_sleeping=(
                f"Missed in-person talk: {agent.name} tried to talk to you (\"{msg}\"), "
                "but you were sleeping. Don't let them waiting!"
            ),
        )
        agent.failed_calls += 1
        return f"{target.name} is currently busy or sleeping (DND).", False, 60

    ok, reason = can_physically_reach_person(agent, target, 50.0)
    if not ok:
        agent.failed_calls += 1
        return "Cannot reach target." if reason == "Too far." else reason, False, 60

    _social_bump(agent, target, 0.2)
    agent.social_fulfillment = min(100.0, agent.social_fulfillment + 10.0)
    target.pending_notifications.append(f"{agent.name} said: {msg}")

    for other in world.agents.values():
        if not other.alive or other.id in (agent.id, target.id):
            continue
        if is_busy(other, world.sim_time):
            continue

        ok2, _ = can_physically_reach_person(agent, other, 50.0)
        if ok2:
            other.pending_notifications.append(f"Overheard {agent.name} say to {target.name}: '{msg}'")

    return f"Talked to {target.name}.", True, 60


def handle_call_person(agent, world, args: dict):
    t_name = str(args.get("person", "")).strip()
    msg = str(args.get("message", "")).strip()

    target = find_agent_by_name(world, t_name)
    if not target or not target.alive:
        agent.failed_calls += 1
        return "Target not found.", False, 60

    if is_busy(target, world.sim_time):
        # Voicemail always succeeds
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

    # Pull item from sender (escrow immediately if queued)
    item_data = None
    if agent.currently_holding and normalize_label(agent.currently_holding["item"]) == normalize_label(item_name):
        item_data = agent.currently_holding
        agent.currently_holding = None
    else:
        idx = next(
            (i for i, it in enumerate(agent.inventory) if normalize_label(it["item"]) == normalize_label(item_name)),
            -1,
        )
        if idx != -1:
            item_data = agent.inventory.pop(idx)

    if not item_data:
        agent.failed_calls += 1
        return f"You don't have {item_name} in your hand or inventory.", False, 60

    # If target is busy/sleeping, queue delivery
    if is_busy(target, world.sim_time):
        if not hasattr(world, "pending_deliveries") or world.pending_deliveries is None:
            world.pending_deliveries = []
        world.pending_deliveries.append(
            {
                "id": str(uuid.uuid4()),
                "kind": "item",
                "from_id": agent.id,
                "to_id": target.id,
                "item": deepcopy(item_data),
                "created_at": float(world.sim_time),
            }
        )

        _enqueue_missed_interaction(
            target,
            text_busy=(
                f"{agent.name} tried to give you {item_data['item']}, but you were busy. "
                "Delivery has been queued and will arrive when you are available."
            ),
            text_sleeping=(
                f"{agent.name} tried to give you {item_data['item']}, but you were sleeping. "
                "Delivery has been queued and will arrive when you are available."
            ),
        )
        agent.pending_notifications.append(f"Queued item delivery: {item_data['item']} -> {target.name}.")
        return f"{target.name} is busy/sleeping. Item delivery queued.", True, 60

    # Immediate delivery if available
    if len(target.inventory) >= MAX_INVENTORY:
        # Return item to sender (best effort)
        agent.inventory.append(item_data)
        agent.failed_calls += 1
        return f"{target.name}'s inventory is full.", False, 60

    target.inventory.append(item_data)
    _social_bump(agent, target, 0.25)
    agent.social_fulfillment = min(100.0, agent.social_fulfillment + 15.0)
    target.pending_notifications.append(f"{agent.name} gave you {item_data['item']}.")
    return f"Gave {item_data['item']} to {target.name}.", True, 60


def handle_give_money(agent, world, args: dict):
    t_name = str(args.get("person", "")).strip()
    try:
        amount = float(args.get("amount", 0))
    except (ValueError, TypeError):
        amount = 0.0

    if amount <= 0:
        agent.failed_calls += 1
        return "Invalid amount.", False, 60

    if agent.money < amount:
        agent.failed_calls += 1
        return "Not enough money.", False, 60

    target = find_agent_by_name(world, t_name)
    if not target or not target.alive:
        agent.failed_calls += 1
        return "Target not found.", False, 60

    ok, reason = can_physically_reach_person(agent, target, 20.0)
    if not ok:
        agent.failed_calls += 1
        return reason, False, 60

    # Escrow immediately if queued
    if is_busy(target, world.sim_time):
        agent.money -= amount
        if not hasattr(world, "pending_deliveries") or world.pending_deliveries is None:
            world.pending_deliveries = []
        world.pending_deliveries.append(
            {
                "id": str(uuid.uuid4()),
                "kind": "money",
                "from_id": agent.id,
                "to_id": target.id,
                "amount": float(amount),
                "created_at": float(world.sim_time),
            }
        )

        _enqueue_missed_interaction(
            target,
            text_busy=(
                f"{agent.name} tried to give you ${amount:.2f}, but you were busy. "
                "Transfer has been queued and will arrive when you are available."
            ),
            text_sleeping=(
                f"{agent.name} tried to give you ${amount:.2f}, but you were sleeping. "
                "Transfer has been queued and will arrive when you are available."
            ),
        )
        agent.pending_notifications.append(f"Queued money transfer: ${amount:.2f} -> {target.name}.")
        return f"{target.name} is busy/sleeping. Money transfer queued.", True, 60

    # Immediate transfer if available
    agent.money -= amount
    target.money += amount
    _social_bump(agent, target, 0.2)
    agent.social_fulfillment = min(100.0, agent.social_fulfillment + 15.0)
    target.pending_notifications.append(f"{agent.name} gave you ${amount:.2f}.")
    return f"Gave ${amount:.2f} to {target.name}.", True, 60


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

        ok, reason = can_physically_reach_person(agent, target, STATUS_MAX_DISTANCE)
        if not ok:
            agent.failed_calls += 1
            return f"You must be within {STATUS_MAX_DISTANCE:.0f}m on the same floor to change relationship status.", False, 60

        req_key = normalize_label(person)

        # Acceptance path: if this agent has a pending request from target, allow acceptance even if target is busy.
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
            target.pending_notifications.append(f"{agent.name} accepted status: {rel_type}.")
            return f"Status with {target.name} changed to: {rel_type}.", True, 30

        # Request path: queue even if target is busy/sleeping
        target.pending_status_requests[normalize_label(agent.name)] = rel_type
        _enqueue_missed_interaction(
            target,
            text_busy=f"{agent.name} requested relationship status: {rel_type}. (Queued while you were busy.)",
            text_sleeping=f"{agent.name} requested relationship status: {rel_type}. (Queued while you were sleeping.)",
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

    # New semantics:
    # - If target is sleeping: allow attack (wake them).
    # - If target is in a task: interrupt/cancel task + allow attack.
    # - If target is otherwise busy (busy_until > sim_time): do not allow.
    if getattr(target, "task_state", "idle") != "idle":
        _cancel_task_if_any(target)
        target.busy_until = min(float(target.busy_until), float(world.sim_time))
        target.pending_notifications.append("URGENT: Your task was interrupted by an attack!")
    elif getattr(target, "is_sleeping", False):
        target.is_sleeping = False
        target.current_activity = "idle"
        target.busy_until = min(float(target.busy_until), float(world.sim_time))
        target.pending_notifications.append("URGENT: You were attacked while sleeping!")
    else:
        if float(target.busy_until) > float(world.sim_time):
            agent.failed_calls += 1
            return f"{target.name} is currently busy. Cannot attack right now.", False, 60

    damage = random.uniform(5.0, 25.0)
    target.health -= damage
    target.stress = min(100.0, target.stress + 15.0)
    _social_penalty(agent, target, 0.8)
    target.pending_notifications.append(f"URGENT: {agent.name} attacked you!")

    if target.health <= 0.0:
        kill_agent(target, world, cause=f"killed by {agent.name}")
        return f"Killed {target.name}.", True, 60

    return f"Attacked {target.name} for {damage:.1f} damage.", True, 60
