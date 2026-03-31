import random

import pytest

from conftest import tool_xml


def _mk_world():
    from state import AgentState, WorldState

    w = WorldState()
    w.sim_time = 9 * 3600  # 09:00 by default (most public places open)
    w.last_passive = w.sim_time
    w.weather = "Sunny"
    w.market_price = 100.0
    return w


def _add_agent(world, agent_id: int, name: str):
    from state import AgentState

    a = AgentState(id=agent_id, name=name, age=30)
    a.x = 10.0 + agent_id
    a.y = 10.0 + agent_id
    a.z = 0.0
    a.location = "Outside"
    a.busy_until = world.sim_time
    world.agents[a.id] = a
    return a


def _set_inside(agent, place_name: str):
    from locations import get_location_by_name

    loc = get_location_by_name(place_name)
    assert loc is not None, f"Test location missing: {place_name}"
    agent.x = (loc.x_min + loc.x_max) / 2.0
    agent.y = (loc.y_min + loc.y_max) / 2.0
    agent.z = loc.z_min
    agent.location = loc.name


def _exec(world, agent, xml: str):
    from tools import execute_tool

    res, suc, cost = execute_tool(xml, agent.id, world)
    return res, suc, cost


def test_parse_rejects_multiple_tool_calls():
    from tooling.parsing import parse_tool_call

    s = (
        "<tool_call><function=walk><parameter=direction>\nwest\n</parameter></function></tool_call>\n"
        "<tool_call><function=walk><parameter=direction>\neast\n</parameter></function></tool_call>"
    )
    name, args = parse_tool_call(s)
    assert name.startswith("Parse error")


def test_move_to_rejects_coordinates():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    res, suc, _ = _exec(w, a, tool_xml("move_to", place="(10, 20)"))
    assert suc is False
    assert "Coordinates are not valid" in res


def test_move_to_success_and_sets_outside():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    res, suc, cost = _exec(w, a, tool_xml("move_to", place="Library"))
    assert suc is True
    assert cost >= 60
    assert a.location == "Outside"
    assert "Travelled to entrance area" in res


def test_move_to_vehicle_fallback_notification_when_cant_afford_fuel():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")

    # Ensure vehicle is near enough to ride, but fuel is unaffordable
    a.vehicle_type = "Car"
    a.vehicle_x, a.vehicle_y, a.vehicle_z = a.x, a.y, a.z
    a.money = 0.0

    _exec(w, a, tool_xml("move_to", place="Mall"))
    assert any("Walked instead of riding" in n for n in a.pending_notifications)


def test_walk_invalid_direction():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    res, suc, _ = _exec(w, a, tool_xml("walk", direction="up"))
    assert suc is False
    assert "Invalid direction" in res


def test_walk_prevents_falling_from_z_level():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.z = 5.0
    res, suc, _ = _exec(w, a, tool_xml("walk", direction="north"))
    assert suc is False
    assert "fall" in res.lower()


def test_buy_food_from_anywhere_uses_village_stock():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.money = 100.0
    w.store_inventory["Water"] = 5
    res, suc, _ = _exec(w, a, tool_xml("buy_item", item="Water"))
    assert suc is True
    assert "Bought Water" in res
    assert any(it["item"] == "Water" for it in a.inventory)


def test_buy_nonfood_requires_being_inside_store():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.money = 1000.0
    res, suc, _ = _exec(w, a, tool_xml("buy_item", item="Toothbrush"))
    assert suc is False
    assert "Non-food items can only be bought" in res


def test_buy_nonfood_inside_store_succeeds():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.money = 1000.0
    _set_inside(a, "Store_A")
    w.store_inventory["Toothbrush"] = 5
    res, suc, _ = _exec(w, a, tool_xml("buy_item", item="Toothbrush"))
    assert suc is True
    assert any(it["item"] == "Toothbrush" for it in a.inventory)


def test_buy_vehicle_requires_dealership_inside():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.money = 999999.0
    res, suc, _ = _exec(w, a, tool_xml("buy_item", item="Motorcycle"))
    assert suc is False
    assert "inside Vehicle_Dealership" in res


def test_buy_vehicle_inside_dealership_succeeds():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.money = 999999.0
    _set_inside(a, "Vehicle_Dealership")
    res, suc, _ = _exec(w, a, tool_xml("buy_item", item="Motorcycle"))
    assert suc is True
    assert a.vehicle_type == "Motorcycle"


def test_eat_food_from_inventory():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.hunger = 80.0
    a.hydration = 10.0
    a.inventory.append({"id": "x", "item": "Water", "durability": 1, "bought": w.sim_time})
    res, suc, _ = _exec(w, a, tool_xml("eat_food", item="Water"))
    assert suc is True
    assert "Ate Water" in res
    assert a.hydration > 10.0
    assert not any(it["item"] == "Water" for it in a.inventory)


def test_eat_food_spoiled_penalty():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.health = 100.0
    # Bought long ago
    a.inventory.append({"id": "x", "item": "Sandwich", "durability": 1, "bought": 0.0})
    w.sim_time = 200000.0
    res, suc, _ = _exec(w, a, tool_xml("eat_food", item="Sandwich"))
    assert suc is True
    assert "spoiled" in res.lower()
    assert a.health == pytest.approx(90.0)


def test_seek_medicalcare_requires_inside_hospital():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.money = 100.0
    res, suc, _ = _exec(w, a, tool_xml("seek_medicalcare"))
    assert suc is False
    assert "inside Hospital" in res


def test_seek_medicalcare_inside_hospital_succeeds():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.money = 100.0
    a.health = 20.0
    _set_inside(a, "Hospital")
    res, suc, _ = _exec(w, a, tool_xml("seek_medicalcare"))
    assert suc is True
    assert a.health > 20.0


def test_buy_stock_market_closed_queues_order():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.money = 10000.0
    # 09:00 is before 09:30 → closed
    w.sim_time = 9 * 3600
    res, suc, _ = _exec(w, a, tool_xml("buy_stock", shares="2"))
    assert suc is True
    assert "queued" in res.lower()
    assert len(a.pending_market_orders) == 1


def test_sell_stock_market_closed_queues_order():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.shares_owned = 5
    w.sim_time = 9 * 3600
    res, suc, _ = _exec(w, a, tool_xml("sell_stock", shares="2"))
    assert suc is True
    assert "queued" in res.lower()
    assert len(a.pending_market_orders) == 1


def test_sleep_sets_sleeping_and_busy_time():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.energy = 0.0
    res, suc, cost = _exec(w, a, tool_xml("sleep", hours="2"))
    assert suc is True
    assert a.is_sleeping is True
    assert cost == 7200


def test_do_hobby_requires_valid_item_and_reduces_stress():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.stress = 80.0
    a.inventory.append({"id": "b", "item": "Book", "durability": 1, "bought": w.sim_time})
    res, suc, _ = _exec(w, a, tool_xml("do_hobby", item="Book"))
    assert suc is True
    assert a.stress < 80.0


def test_hold_item_moves_inventory_to_hand_and_store_puts_back():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.inventory.append({"id": "b", "item": "Notebook", "durability": 1, "bought": w.sim_time})
    res, suc, _ = _exec(w, a, tool_xml("hold_item", item_name="Notebook"))
    assert suc is True
    assert a.currently_holding and a.currently_holding["item"] == "Notebook"
    res, suc, _ = _exec(w, a, tool_xml("hold_item", item_name="store"))
    assert suc is True
    assert a.currently_holding is None
    assert any(it["item"] == "Notebook" for it in a.inventory)


def test_drop_then_pick_ground_item():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.currently_holding = {"id": "h", "item": "Book", "durability": 2, "bought": w.sim_time}
    res, suc, _ = _exec(w, a, tool_xml("drop_item", item_name="Book"))
    assert suc is True
    assert a.currently_holding is None
    assert len(w.ground_items) == 1

    # Picking it back immediately should be blocked by cooldown
    res, suc, _ = _exec(w, a, tool_xml("pick_item", item_name="Book"))
    assert suc is False
    assert "cannot re-pick" in res.lower()


def test_interact_with_escalator_or_floor_object_if_present():
    # Minimal check that interact_with can operate on visible objects when inside a location.
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    _set_inside(a, "Hospital")
    # Some objects are z-specific; just assert failure is well-formed if not found on floor.
    res, suc, _ = _exec(w, a, tool_xml("interact_with", person_or_object="Reception Desk", action="use"))
    assert suc is True or "No nearby visible object" in res


def test_talk_to_success_and_overhear():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    b = _add_agent(w, 1, "Bob")
    c = _add_agent(w, 2, "Cara")
    # all within 50m already
    res, suc, _ = _exec(w, a, tool_xml("talk_to", person="Bob", message="hello"))
    assert suc is True
    assert any("Alice said: hello" in n for n in b.pending_notifications)
    # Cara should overhear (if not busy)
    assert any("Overheard Alice" in n for n in c.pending_notifications)


def test_talk_to_busy_creates_missed_notification_for_target():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    b = _add_agent(w, 1, "Bob")
    b.task_state = "job_pick"
    res, suc, _ = _exec(w, a, tool_xml("talk_to", person="Bob", message="ping"))
    assert suc is False
    assert any("Missed in-person talk" in n for n in b.pending_notifications)


def test_call_person_available_creates_notification_not_voicemail():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    b = _add_agent(w, 1, "Bob")
    res, suc, _ = _exec(w, a, tool_xml("call_person", person="Bob", message="yo"))
    assert suc is True
    assert any("Phone Call from Alice" in n for n in b.pending_notifications)
    assert len(getattr(b, "voicemail_inbox", [])) == 0


def test_call_person_busy_leaves_voicemail():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    b = _add_agent(w, 1, "Bob")
    b.is_sleeping = True
    b.busy_until = w.sim_time + 9999
    res, suc, _ = _exec(w, a, tool_xml("call_person", person="Bob", message="vm"))
    assert suc is True
    assert len(getattr(b, "voicemail_inbox", [])) == 1


def test_change_status_beliefs_update():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    res, suc, _ = _exec(w, a, tool_xml("change_status", person="", type="", value="I will focus on health."))
    assert suc is True
    assert "focus on health" in a.beliefs.lower()


def test_change_status_request_queued_while_target_sleeping_requires_proximity():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    b = _add_agent(w, 1, "Bob")
    b.is_sleeping = True
    b.busy_until = w.sim_time + 9999
    res, suc, _ = _exec(w, a, tool_xml("change_status", person="Bob", type="dating", value=""))
    assert suc is True
    assert b.pending_status_requests.get("alice") == "dating"


def test_give_money_immediate_when_target_available():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    b = _add_agent(w, 1, "Bob")
    a.money = 100.0
    res, suc, _ = _exec(w, a, tool_xml("give_money", person="Bob", amount="10"))
    assert suc is True
    assert a.money == pytest.approx(90.0)
    assert b.money == pytest.approx(510.0)


def test_attack_busy_until_non_task_fails():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    b = _add_agent(w, 1, "Bob")
    b.busy_until = w.sim_time + 1000
    b.task_state = "idle"
    b.is_sleeping = False
    res, suc, _ = _exec(w, a, tool_xml("attack_person", person="Bob"))
    assert suc is False
    assert b.health == pytest.approx(100.0)


def test_attack_sleeping_succeeds():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    b = _add_agent(w, 1, "Bob")
    b.is_sleeping = True
    b.busy_until = w.sim_time + 10000
    random.seed(0)
    res, suc, _ = _exec(w, a, tool_xml("attack_person", person="Bob"))
    assert suc is True
    assert b.is_sleeping is False
    assert b.health < 100.0


def test_work_job_full_flow_and_task_lock_blocks_unrelated_tool():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.job = "developer"
    a.hourly_wage = 50.0
    a.energy = 100.0
    _set_inside(a, "Startup_Sowl")

    # Start work (enters job_pick)
    res, suc, _ = _exec(w, a, tool_xml("work_job", jobname="developer", hours="1"))
    assert suc is True
    assert a.task_state == "job_pick"
    required = a.pending_task_data["flavor"]["pick"]

    # Unrelated tool should be blocked mid-task by execute_tool
    res2, suc2, _ = _exec(w, a, tool_xml("move_to", place="Library"))
    assert suc2 is False
    assert "middle of a task" in res2.lower()

    # Pick prop
    res, suc, _ = _exec(w, a, tool_xml("pick_item", item_name=required))
    assert suc is True
    assert a.task_state == "job_mcq"

    # Answer correctly
    ans = a.pending_task_data["flavor"]["ans"]
    target = a.pending_task_data["flavor"]["obj"]
    before = a.money
    res, suc, _ = _exec(w, a, tool_xml("interact_with", person_or_object=target, action=ans))
    assert suc is True
    assert a.task_state == "idle"
    assert a.money >= before  # earned pay


def test_get_education_full_flow_increases_education_and_wage():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.job = "student"
    a.money = 1000.0
    a.energy = 100.0
    _set_inside(a, "Library")

    res, suc, _ = _exec(w, a, tool_xml("get_education", type="education", hours="1"))
    assert suc is True
    assert a.task_state == "job_pick"
    required = a.pending_task_data["flavor"]["pick"]

    res, suc, _ = _exec(w, a, tool_xml("pick_item", item_name=required))
    assert suc is True
    assert a.task_state == "job_mcq"

    ans = a.pending_task_data["flavor"]["ans"]
    target = a.pending_task_data["flavor"]["obj"]
    edu_before = a.education
    wage_before = a.hourly_wage
    res, suc, _ = _exec(w, a, tool_xml("interact_with", person_or_object=target, action=ans))
    assert suc is True
    assert a.education > edu_before
    assert a.hourly_wage > wage_before
