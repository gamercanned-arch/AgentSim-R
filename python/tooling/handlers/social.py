from __future__ import annotations

import random

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


def handle_talk_to(agent, world, args: dict):
    t_name = str(args.get("person", "")).strip()
    msg = str(args.get("message", "")).strip()

    target = find_agent_by_name(world, t_name)
    if not target or not target.alive:
        agent.failed_calls += 1
        return "Target not found.", False, 60

    if is_busy(target, world.sim_time):
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
        agent.failed_calls += 1
        return f"Call to {target.name} went straight to voicemail (DND).", False, 60

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

    if is_busy(target, world.sim_time):
        agent.failed_calls += 1
        return f"{target.name} is busy (DND).", False, 60

    ok, reason = can_physically_reach_person(agent, target, 20.0)
    if not ok:
        agent.failed_calls += 1
        return reason, False, 60

    if len(target.inventory) >= MAX_INVENTORY:
        agent.failed_calls += 1
        return f"{target.name}'s inventory is full.", False, 60

    item_data = None
    if agent.currently_holding and normalize_label(agent.currently_holding["item"]) == normalize_label(item_name):
        item_data = agent.currently_holding
        agent.currently_holding = None
    else:
        idx = next((i for i, it in enumerate(agent.inventory) if normalize_label(it["item"]) == normalize_label(item_name)), -1)
        if idx != -1:
            item_data = agent.inventory.pop(idx)

    if not item_data:
        agent.failed_calls += 1
        return f"You don't have {item_name} in your hand or inventory.", False, 60

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

    if is_busy(target, world.sim_time):
        agent.failed_calls += 1
        return f"{target.name} is busy (DND).", False, 60

    ok, reason = can_physically_reach_person(agent, target, 20.0)
    if not ok:
        agent.failed_calls += 1
        return reason, False, 60

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

        if is_busy(target, world.sim_time):
            agent.failed_calls += 1
            return f"{target.name} is busy (DND).", False, 60

        ok, reason = can_physically_reach_person(agent, target, STATUS_MAX_DISTANCE)
        if not ok:
            agent.failed_calls += 1
            return f"You must be within {STATUS_MAX_DISTANCE:.0f}m on the same floor to change relationship status.", False, 60

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
            target.pending_notifications.append(f"{agent.name} accepted status: {rel_type}.")
            return f"Status with {target.name} changed to: {rel_type}.", True, 30

        target.pending_status_requests[normalize_label(agent.name)] = rel_type
        target.pending_notifications.append(f"{agent.name} wants status: {rel_type}.")
        return f"Requested status change to '{rel_type}' with {target.name}.", True, 30

    agent.failed_calls += 1
    return "Invalid parameters.", False, 60


def handle_attack_person(agent, world, args: dict):
    t_name = str(args.get("person", "")).strip()
    target = find_agent_by_name(world, t_name)
    if not target or not target.alive:
        agent.failed_calls += 1
        return "Target not found.", False, 60

    if is_busy(target, world.sim_time):
        agent.failed_calls += 1
        return f"{target.name} is busy/sleeping (DND). Cannot attack.", False, 60

    ok, reason = can_physically_reach_person(agent, target, 20.0)
    if not ok:
        agent.failed_calls += 1
        return reason, False, 60

    damage = random.uniform(5.0, 25.0)
    target.health -= damage
    target.stress = min(100.0, target.stress + 15.0)
    _social_penalty(agent, target, 0.8)
    target.pending_notifications.append(f"URGENT: {agent.name} attacked you!")

    if target.health <= 0.0:
        kill_agent(target, world, cause=f"killed by {agent.name}")
        return f"Killed {target.name}.", True, 60

    return f"Attacked {target.name} for {damage:.1f} damage.", True, 60