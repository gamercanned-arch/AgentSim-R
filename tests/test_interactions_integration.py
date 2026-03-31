import random

import pytest

from conftest import StubServer, last_user_observation, tool_xml


def make_world_two_agents():
    from state import AgentState, WorldState

    w = WorldState()
    w.sim_time = 0.0
    w.last_passive = 0.0
    w.market_price = 100.0
    w.weather = "Sunny"

    a = AgentState(id=0, name="Alice", age=30)
    b = AgentState(id=1, name="Bob", age=30)

    # Keep them outside any location box to avoid "same-floor location" gating
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
    import scheduler

    w, a, b = make_world_two_agents()

    # Bob is sleeping for 2 minutes.
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
    monkeypatch.setattr(scheduler, "call_server", stub)

    # Tick 1: Alice calls Bob (voicemail).
    scheduler.run_tick(w)
    assert len(getattr(b, "voicemail_inbox", [])) == 1

    # Tick 2: Alice sleeps 1h so Bob becomes next to act at t=120.
    scheduler.run_tick(w)

    # Tick 3: Bob wakes and acts; his observation should show voicemail.
    scheduler.run_tick(w)
    obs = last_user_observation(stub.last_messages[1])
    assert "Voicemail Inbox: 1 message(s)" in obs
    assert "From Alice" in obs
    assert "hey bob" in obs


def test_give_item_queued_to_sleeping_target_delivered_on_wake(temp_logs, monkeypatch):
    import scheduler

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
    monkeypatch.setattr(scheduler, "call_server", stub)

    scheduler.run_tick(w)  # queue delivery
    assert not any(it["item"] == "Book" for it in a.inventory), "escrow should remove item from sender immediately"
    assert hasattr(w, "pending_deliveries") and len(w.pending_deliveries) == 1

    scheduler.run_tick(w)  # Alice sleeps
    scheduler.run_tick(w)  # Bob wakes; delivery processed before his observation

    assert any(it["item"] == "Book" for it in b.inventory), "item should be delivered to recipient on wake"
    obs = last_user_observation(stub.last_messages[1])
    assert "Received queued item delivery" in obs or "queued item" in obs.lower()


def test_give_item_cancelled_if_recipient_inventory_full_item_returned_to_sender(temp_logs, monkeypatch):
    import scheduler
    from config import MAX_INVENTORY

    w, a, b = make_world_two_agents()
    a.inventory.append({"id": "i1", "item": "Book", "durability": 5, "bought": 0.0})

    # Fill Bob's inventory completely.
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
    monkeypatch.setattr(scheduler, "call_server", stub)

    scheduler.run_tick(w)  # queue
    assert not any(it["item"] == "Book" for it in a.inventory)
    assert len(w.pending_deliveries) == 1

    scheduler.run_tick(w)  # Alice sleeps
    scheduler.run_tick(w)  # Bob wakes; delivery should cancel and refund item

    assert not any(it["item"] == "Book" for it in b.inventory), "recipient should not receive item when inventory full"
    assert any(it["item"] == "Book" for it in a.inventory), "item should be returned to sender on cancel"
    assert len(w.pending_deliveries) == 0

    # Bob observation should mention cancellation (substring-based; passive notifs may exist too).
    obs = last_user_observation(stub.last_messages[1]).lower()
    assert "cancel" in obs or "inventory was full" in obs


def test_queued_money_refunded_if_recipient_dies_before_delivery(temp_logs, monkeypatch):
    import scheduler

    w, a, b = make_world_two_agents()
    a.money = 1000.0

    b.is_sleeping = True
    b.busy_until = 120.0
    b.health = 1.0  # ensure kill on first hit

    # Deterministic damage
    monkeypatch.setattr(random, "uniform", lambda lo, hi: 5.0)

    plans = {
        0: [
            tool_xml("give_money", person="Bob", amount="100"),
            tool_xml("attack_person", person="Bob"),
            tool_xml("change_status", person="", type="", value="after-refund"),
        ],
    }
    stub = StubServer(plans)
    monkeypatch.setattr(scheduler, "call_server", stub)

    scheduler.run_tick(w)  # queued money (escrow now)
    assert a.money == pytest.approx(900.0)
    assert len(w.pending_deliveries) == 1

    scheduler.run_tick(w)  # attack kills Bob
    assert not b.alive

    # Next tick processes pending deliveries and refunds (recipient dead)
    scheduler.run_tick(w)
    assert a.money == pytest.approx(1000.0)
    assert len(w.pending_deliveries) == 0


def test_notification_drip_only_consumes_shown(temp_logs, monkeypatch):
    import scheduler

    w, a, b = make_world_two_agents()
    # Keep only Alice alive for this test
    b.alive = False

    a.pending_notifications = [f"n{i}" for i in range(20)]

    plans = {
        0: [tool_xml("change_status", person="", type="", value="noop")],
    }
    stub = StubServer(plans)
    monkeypatch.setattr(scheduler, "call_server", stub)

    scheduler.run_tick(w)
    assert len(a.pending_notifications) == 8, "default drip shows/consumes 12 and keeps remaining queued"


def test_attack_sleeping_target_succeeds_and_wakes(temp_logs, monkeypatch):
    import scheduler

    w, a, b = make_world_two_agents()
    b.is_sleeping = True
    b.busy_until = 9999.0  # sleeping far into the future; should still be attackable

    monkeypatch.setattr(random, "uniform", lambda lo, hi: 5.0)

    plans = {0: [tool_xml("attack_person", person="Bob")]}
    stub = StubServer(plans)
    monkeypatch.setattr(scheduler, "call_server", stub)

    scheduler.run_tick(w)
    assert b.is_sleeping is False
    assert b.health == pytest.approx(95.0)


def test_attack_mid_task_cancels_task_and_interrupts_busy_until(temp_logs, monkeypatch):
    import scheduler

    w, a, b = make_world_two_agents()

    b.task_state = "job_mcq"
    b.pending_task_data = {"type": "work_job", "hours": 5, "flavor": {"obj": "Task Board", "ans": "B"}}
    b.active_task_entities = {"prop": "Laptop", "target": "Task Board", "scenario_id": "developer_01"}
    b.currently_holding = {"id": "job_prop", "item": "Laptop", "durability": 99}
    b.busy_until = 1000.0

    monkeypatch.setattr(random, "uniform", lambda lo, hi: 5.0)

    plans = {0: [tool_xml("attack_person", person="Bob")]}
    stub = StubServer(plans)
    monkeypatch.setattr(scheduler, "call_server", stub)

    scheduler.run_tick(w)

    assert b.task_state == "idle"
    assert b.pending_task_data == {}
    assert b.active_task_entities == {}
    assert b.currently_holding is None
    assert b.busy_until <= w.sim_time
    assert b.health == pytest.approx(95.0)


def test_attack_time_busy_non_task_target_fails(temp_logs, monkeypatch):
    import scheduler

    w, a, b = make_world_two_agents()
    b.task_state = "idle"
    b.is_sleeping = False
    b.busy_until = 1000.0  # busy for other reason

    plans = {0: [tool_xml("attack_person", person="Bob")]}
    stub = StubServer(plans)
    monkeypatch.setattr(scheduler, "call_server", stub)

    scheduler.run_tick(w)
    # Should remain uninjured
    assert b.health == pytest.approx(100.0)


def test_change_status_queued_while_target_sleeping_requires_proximity(temp_logs, monkeypatch):
    import scheduler

    w, a, b = make_world_two_agents()
    b.is_sleeping = True
    b.busy_until = 120.0

    plans = {
        0: [tool_xml("change_status", person="Bob", type="dating", value="")],
    }
    stub = StubServer(plans)
    monkeypatch.setattr(scheduler, "call_server", stub)

    scheduler.run_tick(w)
    assert b.pending_status_requests.get("alice") == "dating"
