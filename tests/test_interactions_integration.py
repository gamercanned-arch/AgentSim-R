import random

import pytest

from conftest import StubServer, last_user_observation, tool_xml


def make_world_two_agents():
    from python.state import AgentState, WorldState

    w = WorldState()
    w.sim_time = 0.0
    w.last_passive = 0.0
    w.market_price = 100.0
    w.weather = "Sunny"

    a = AgentState(id=0, name="Alice", age=30)
    b = AgentState(id=1, name="Bob", age=30)

    a.x = a.y = 10.0
    a.z = 0.0
    b.x = b.y = 10.0
    b.z = 0.0

    a.location = "Outside"
    b.location = "Outside"

    a.busy_until = 0.0
    b.busy_until = 0.0

    w.agents[a.id] = a
    w.agents[b.id] = b
    return w, a, b


def test_voicemail_left_when_target_sleeping_and_shown_after_wake(temp_logs, monkeypatch):
    import python.scheduler

    w, a, b = make_world_two_agents()
    b.is_sleeping = True
    b.busy_until = 120.0

    plans = {
        0: [
            tool_xml("call_person", person="Bob", message="hey bob"),
            tool_xml("sleep", hours="1"),
        ],
        1: [
            tool_xml("change_status", person="", type="", value="awake"),
        ],
    }
    stub = StubServer(plans)
    monkeypatch.setattr(python.scheduler, "call_server", stub)

    python.scheduler.run_tick(w)
    assert len(getattr(b, "voicemail_inbox", [])) == 1

    python.scheduler.run_tick(w)
    python.scheduler.run_tick(w)
    obs = last_user_observation(stub.last_messages[1])
    assert "Voicemail Inbox: 1 message(s)" in obs
    assert "From Alice" in obs
    assert "hey bob" in obs


def test_give_item_queued_to_sleeping_target_delivered_on_wake(temp_logs, monkeypatch):
    import python.scheduler

    w, a, b = make_world_two_agents()

    a.inventory.append({"id": "i1", "item": "Book", "durability": 5, "bought": 0.0})

    b.is_sleeping = True
    b.busy_until = 120.0

    plans = {
        0: [
            tool_xml("give_item", person="Bob", item="Book"),
            tool_xml("sleep", hours="1"),
        ],
        1: [
            tool_xml("change_status", person="", type="", value="ok"),
        ],
    }
    stub = StubServer(plans)
    monkeypatch.setattr(python.scheduler, "call_server", stub)

    python.scheduler.run_tick(w)
    assert not any(it["item"] == "Book" for it in a.inventory)
    assert hasattr(w, "pending_deliveries") and len(w.pending_deliveries) == 1

    python.scheduler.run_tick(w)
    python.scheduler.run_tick(w)

    assert any(it["item"] == "Book" for it in b.inventory)
    obs = last_user_observation(stub.last_messages[1])
    assert "Received queued item delivery" in obs or "queued item" in obs.lower()


def test_give_item_cancelled_if_recipient_inventory_full_item_returned_to_sender(temp_logs, monkeypatch):
    import python.scheduler
    from python.config import MAX_INVENTORY

    w, a, b = make_world_two_agents()
    a.inventory.append({"id": "i1", "item": "Book", "durability": 5, "bought": 0.0})

    for i in range(MAX_INVENTORY):
        b.inventory.append({"id": f"junk{i}", "item": "Snacks", "durability": 1, "bought": 0.0})

    b.is_sleeping = True
    b.busy_until = 120.0

    plans = {
        0: [
            tool_xml("give_item", person="Bob", item="Book"),
            tool_xml("sleep", hours="1"),
        ],
        1: [
            tool_xml("change_status", person="", type="", value="ok"),
        ],
    }
    stub = StubServer(plans)
    monkeypatch.setattr(python.scheduler, "call_server", stub)

    python.scheduler.run_tick(w)
    assert not any(it["item"] == "Book" for it in a.inventory)
    assert len(w.pending_deliveries) == 1

    python.scheduler.run_tick(w)
    python.scheduler.run_tick(w)

    assert not any(it["item"] == "Book" for it in b.inventory)
    assert any(it["item"] == "Book" for it in a.inventory)
    assert len(w.pending_deliveries) == 0

    obs = last_user_observation(stub.last_messages[1]).lower()
    assert "cancel" in obs or "inventory was full" in obs


def test_give_money_remote_immediate_even_if_target_sleeping(temp_logs, monkeypatch):
    import python.scheduler

    w, a, b = make_world_two_agents()
    a.money = 1000.0
    b.is_sleeping = True
    b.busy_until = 120.0
    b.x = 3000.0
    b.y = 3000.0

    plans = {
        0: [
            tool_xml("give_money", person="Bob", amount="100"),
        ],
    }
    stub = StubServer(plans)
    monkeypatch.setattr(python.scheduler, "call_server", stub)

    python.scheduler.run_tick(w)
    assert a.money == pytest.approx(900.0)
    assert b.money == pytest.approx(600.0)
    assert len(w.pending_deliveries) == 0


def test_notification_drip_only_consumes_shown(temp_logs, monkeypatch):
    import python.scheduler

    w, a, b = make_world_two_agents()
    b.alive = False

    a.pending_notifications = [f"n{i}" for i in range(20)]

    plans = {
        0: [tool_xml("change_status", person="", type="", value="noop")],
    }
    stub = StubServer(plans)
    monkeypatch.setattr(python.scheduler, "call_server", stub)

    python.scheduler.run_tick(w)
    assert len(a.pending_notifications) == 8


def test_attack_sleeping_target_succeeds_and_wakes(temp_logs, monkeypatch):
    import python.scheduler

    w, a, b = make_world_two_agents()
    b.is_sleeping = True
    b.busy_until = 9999.0

    monkeypatch.setattr(random, "uniform", lambda lo, hi: 5.0)

    plans = {0: [tool_xml("attack_person", person="Bob")]}
    stub = StubServer(plans)
    monkeypatch.setattr(python.scheduler, "call_server", stub)

    python.scheduler.run_tick(w)
    assert b.is_sleeping is False
    assert b.health == pytest.approx(95.0)


def test_attack_mid_task_cancels_task_and_interrupts_busy_until(temp_logs, monkeypatch):
    import python.scheduler

    w, a, b = make_world_two_agents()

    b.task_state = "job_mcq"
    b.pending_task_data = {"type": "work_job", "hours": 5, "flavor": {"obj": "Task Board", "ans": "B"}}
    b.active_task_entities = {"prop": "Laptop", "target": "Task Board", "scenario_id": "developer_01"}
    b.currently_holding = {"id": "job_prop", "item": "Laptop", "durability": 99}
    b.busy_until = 1000.0

    monkeypatch.setattr(random, "uniform", lambda lo, hi: 5.0)

    plans = {0: [tool_xml("attack_person", person="Bob")]}
    stub = StubServer(plans)
    monkeypatch.setattr(python.scheduler, "call_server", stub)

    python.scheduler.run_tick(w)

    assert b.task_state == "idle"
    assert b.pending_task_data == {}
    assert b.active_task_entities == {}
    assert b.currently_holding is None
    assert b.busy_until <= w.sim_time
    assert b.health == pytest.approx(95.0)


def test_attack_time_busy_non_task_target_succeeds(temp_logs, monkeypatch):
    import python.scheduler

    w, a, b = make_world_two_agents()
    b.task_state = "idle"
    b.is_sleeping = False
    b.busy_until = 1000.0

    monkeypatch.setattr(random, "uniform", lambda lo, hi: 5.0)

    plans = {0: [tool_xml("attack_person", person="Bob")]}
    stub = StubServer(plans)
    monkeypatch.setattr(python.scheduler, "call_server", stub)

    python.scheduler.run_tick(w)
    assert b.health == pytest.approx(95.0)  # Attack succeeds, damage applied


def test_change_status_sleeping_target_fails_and_does_not_queue(temp_logs, monkeypatch):
    import python.scheduler

    w, a, b = make_world_two_agents()
    b.is_sleeping = True
    b.busy_until = 120.0

    plans = {
        0: [tool_xml("change_status", person="Bob", type="dating", value="")],
    }
    stub = StubServer(plans)
    monkeypatch.setattr(python.scheduler, "call_server", stub)

    python.scheduler.run_tick(w)
    assert b.pending_status_requests.get("alice") is None


def test_change_status_accepts_pending_request_and_updates_both_agents():
    from python.tooling.handlers.social import handle_change_status

    w, a, b = make_world_two_agents()
    b.pending_status_requests["alice"] = "dating"

    res, suc, cost = handle_change_status(
        b, w, {"person": "Alice", "type": "dating", "value": ""}
    )

    assert suc is True
    assert cost == 30
    assert "Accepted status change" in res
    assert b.pending_status_requests.get("alice") is None
    assert a.relationships_status == "dating"
    assert b.relationships_status == "dating"
    assert a.relationship_partner == "Bob"
    assert b.relationship_partner == "Alice"


def test_interruption_during_wait(temp_logs, monkeypatch):
    import python.scheduler

    w, a, b = make_world_two_agents()
    
    b.current_activity = "waiting"
    b.busy_until = 6000.0

    monkeypatch.setattr(random, "uniform", lambda lo, hi: 5.0)

    plans = {0: [tool_xml("attack_person", person="Bob")]}
    stub = StubServer(plans)
    monkeypatch.setattr(python.scheduler, "call_server", stub)

    python.scheduler.run_tick(w)

    assert b.busy_until <= w.sim_time
    assert b.current_activity == "idle"
    assert any("interrupted" in n.lower() for n in b.pending_notifications)

