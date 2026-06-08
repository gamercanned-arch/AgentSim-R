import random

import pytest

from conftest import tool_xml


def _mk_world():
    from python.state import WorldState

    w = WorldState()
    w.sim_time = 9 * 3600
    w.last_passive = w.sim_time
    w.weather = "Sunny"
    w.market_price = 100.0
    return w


def _add_agent(world, agent_id: int, name: str):
    from python.state import AgentState

    a = AgentState(id=agent_id, name=name, age=30)
    a.x = 10.0 + agent_id
    a.y = 10.0 + agent_id
    a.z = 0.0
    a.location = "Outside"
    a.busy_until = world.sim_time
    world.agents[a.id] = a
    return a


def _set_inside(agent, place_name: str):
    from python.locations import get_location_by_name

    loc = get_location_by_name(place_name)
    assert loc is not None, f"Test location missing: {place_name}"
    agent.x = (loc.x_min + loc.x_max) / 2.0
    agent.y = (loc.y_min + loc.y_max) / 2.0
    agent.z = loc.z_min
    agent.location = loc.name


def _exec(world, agent, xml: str):
    from python.tools import execute_tool

    res, suc, cost = execute_tool(xml, agent.id, world)
    return res, suc, cost


def test_parse_accepts_multiple_tool_calls():
    from python.tooling.parsing import parse_tool_calls

    s = (
        "<tool_call><function=walk><parameter=direction>\nwest\n</parameter></function></tool_call>\n"
        "<tool_call><function=walk><parameter=direction>\neast\n</parameter></function></tool_call>"
    )
    calls, err = parse_tool_calls(s)
    assert err is None
    assert len(calls) == 2


def test_parse_rejects_trailing_text_after_tool_call():
    from python.tooling.parsing import parse_tool_calls

    s = (
        "<tool_call><function=walk><parameter=direction>\nwest\n</parameter></function></tool_call>\n"
        "extra text"
    )
    calls, err = parse_tool_calls(s)
    assert calls == []
    assert err is not None
    assert "Unexpected text outside tool calls" in err


def test_move_to_rejects_coordinates():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    res, suc, _ = _exec(w, a, tool_xml("move_to", place="(10, 20)"))
    assert suc is False
    assert "Coordinates are not valid" in res


def test_move_to_success_and_sets_outside_for_roofed_place():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    res, suc, cost = _exec(w, a, tool_xml("move_to", place="Library"))
    assert suc is True
    assert cost >= 60
    assert a.location == "moving"
    from python.scheduler import _refresh_agent_activity
    _refresh_agent_activity(a, w.sim_time + cost)
    assert a.location == "Outside Library"
    assert "Travelled to entrance area" in res


def test_move_to_open_air_sets_named_location():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    res, suc, cost = _exec(w, a, tool_xml("move_to", place="Park_Central"))
    assert suc is True
    assert a.location == "moving"
    from python.scheduler import _refresh_agent_activity
    _refresh_agent_activity(a, w.sim_time + cost)
    assert a.location == "Park_Central"


def test_move_to_vehicle_fails_when_cant_afford_fuel():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.vehicle_type = "Car"
    a.vehicle_x, a.vehicle_y, a.vehicle_z = a.x, a.y, a.z
    a.money = 0.0

    res, suc, _ = _exec(w, a, tool_xml("move_to", place="Mall"))
    assert suc is False
    assert "Cannot afford fuel" in res


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


def test_seek_medicalcare_requires_inside_hospital():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    a.money = 100.0
    res, suc, _ = _exec(w, a, tool_xml("seek_medicalcare"))
    assert suc is False
    assert "inside Hospital" in res


def test_schema_validation_rejects_unexpected_param():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    xml = (
        "<tool_call>"
        "<function=seek_medicalcare>"
        "<parameter=foo>\nbar\n</parameter>"
        "</function>"
        "</tool_call>"
    )
    res, suc, _ = _exec(w, a, xml)
    assert suc is False
    assert "Unexpected parameter" in res


def test_multiple_tool_calls_execute_sequentially():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    xml = (
        "<tool_call><function=walk><parameter=direction>\neast\n</parameter></function></tool_call>\n"
        "<tool_call><function=walk><parameter=direction>\nwest\n</parameter></function></tool_call>"
    )
    old_x = a.x
    res, suc, cost = _exec(w, a, xml)
    assert suc is True
    # New behavior: multi-call time cost sums successful steps.
    assert cost == 120
    assert a.x == pytest.approx(old_x)
    assert "1. walk: OK" in res
    assert "2. walk: OK" in res


def test_multiple_tool_calls_sum_cost_not_max():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    xml = (
        "<tool_call><function=walk><parameter=direction>\neast\n</parameter></function></tool_call>\n"
        "<tool_call><function=sleep><parameter=hours>\n2\n</parameter></function></tool_call>"
    )
    res, suc, cost = _exec(w, a, xml)
    assert suc is True
    assert cost == 7260  # 60 + 7200
    assert a.x > 10.0
    assert a.is_sleeping is True
    assert "1. walk: OK" in res
    assert "2. sleep: OK" in res


def test_wait_tool_success():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    xml = tool_xml("wait", minutes="15")
    res, suc, cost = _exec(w, a, xml)
    assert suc is True
    assert cost == 15 * 60
    assert a.current_activity == "waiting"
    assert "Waited in place" in res


def test_wait_tool_clamping():
    w = _mk_world()
    a = _add_agent(w, 0, "Alice")
    xml = tool_xml("wait", minutes="300")
    res, suc, cost = _exec(w, a, xml)
    assert suc is True
    assert cost == 180 * 60
    assert a.current_activity == "waiting"
    assert "Waited in place for 180.0 minutes" in res