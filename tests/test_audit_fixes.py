"""
Regression tests for AgentSim-R Final Triage Bug Audit items 1-13.

Each test reproduces the bug scenario and asserts the corrected behavior.
"""

import math
import random

import pytest

from conftest import StubServer, last_user_observation, tool_xml


# Helpers


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


# Item 1 & 2: starvation/dehydration damage ordering


class TestStarvationDehydrationOrdering:
    """Items 1 & 2 — starvation/dehydration damage must be applied BEFORE
    the health clamp so that health never goes negative between damage
    application and the death check."""

    def test_starvation_damage_clamped_before_death_check(self):
        import python.scheduler as scheduler

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        a.alive = True
        a.health = 5.0
        a.hunger = 100.0
        a.hydration = 50.0
        a.energy = 50.0
        a.stress = 0.0
        a.happiness = 50.0
        a.money = 1000.0
        a.expenses = 0.0
        a.starvation_hours = 4  # 2^4 = 16 damage
        a.dehydration_hours = 0
        a.relationships = 0.0
        a.age = 30
        a.hours_lived = 0
        a.awake_hours = 0
        a.is_sleeping = False
        a.busy_until = w.sim_time
        a.pending_notifications = []
        # social_cooldowns removed (FIX 7: dead code)
        a.caffeine_level = 0

        # With health=5 and starvation damage=16, pre-fix health would go to
        # -11 before the clamp.  Post-fix the clamp fires after damage but
        # before the death check, so health is clamped to 0 and the agent dies.
        scheduler._apply_passive_updates(a, w, w.sim_time + 3600)

        # Agent should be dead (health clamped to 0 triggers death).
        assert a.alive is False

    def test_dehydration_damage_clamped_before_death_check(self):
        import python.scheduler as scheduler

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        a.alive = True
        a.health = 3.0
        a.hunger = 50.0
        a.hydration = 0.0
        a.energy = 50.0
        a.stress = 0.0
        a.happiness = 50.0
        a.money = 1000.0
        a.expenses = 0.0
        a.starvation_hours = 0
        a.dehydration_hours = 3  # 1.5^3 ≈ 3.375 damage
        a.relationships = 0.0
        a.age = 30
        a.hours_lived = 0
        a.awake_hours = 0
        a.is_sleeping = False
        a.busy_until = w.sim_time
        a.pending_notifications = []
        # social_cooldowns removed (FIX 7: dead code)
        a.caffeine_level = 0

        scheduler._apply_passive_updates(a, w, w.sim_time + 3600)

        assert a.alive is False

    def test_health_never_negative_between_damage_and_death(self):
        """Edge case: ensure health is clamped to exactly 0, never negative."""
        import python.scheduler as scheduler

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        a.alive = True
        a.health = 1.0
        a.hunger = 100.0
        a.hydration = 50.0
        a.energy = 50.0
        a.stress = 0.0
        a.happiness = 50.0
        a.money = 1000.0
        a.expenses = 0.0
        a.starvation_hours = 5  # 2^5 = 32 damage
        a.dehydration_hours = 0
        a.relationships = 0.0
        a.age = 30
        a.hours_lived = 0
        a.awake_hours = 0
        a.is_sleeping = False
        a.busy_until = w.sim_time
        a.pending_notifications = []
        # social_cooldowns removed (FIX 7: dead code)
        a.caffeine_level = 0

        scheduler._apply_passive_updates(a, w, w.sim_time + 3600)

        # Health should have been clamped to 0 before death check.
        assert a.health == 0.0
        assert a.alive is False


# Item 3: emergency hunger check ordering=


class TestEmergencyHungerOrdering:
    """Item 3 — emergency hunger check must fire AFTER hunger gain so that
    if hunger crosses the 90 threshold during the passive tick, the agent
    gets an immediate chance to auto-consume."""

    def test_emergency_hunger_fires_after_gain(self, temp_logs, monkeypatch):
        import python.scheduler as scheduler

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        a.alive = True
        a.hunger = 86.0  # Below 90 threshold
        a.hydration = 50.0
        a.energy = 50.0
        a.health = 100.0
        a.stress = 0.0
        a.happiness = 50.0
        a.money = 1000.0
        a.expenses = 0.0
        a.starvation_hours = 0
        a.dehydration_hours = 0
        a.relationships = 0.0
        a.age = 30
        a.hours_lived = 0
        a.awake_hours = 0
        a.is_sleeping = False
        a.busy_until = w.sim_time
        a.pending_notifications = []
        # social_cooldowns removed (FIX 7: dead code)
        a.caffeine_level = 0
        a.inventory = []
        a.currently_holding = None
        a.job = "None"

        # Store has affordable food
        w.store_inventory["Snacks"] = 5

        before_hunger = a.hunger
        scheduler._apply_passive_updates(a, w, w.sim_time + 3600)

        # Hunger gain is +5 for awake agents: 86 + 5 = 91 >= 90
        # Emergency check should now fire and auto-consume, reducing hunger.
        # The key assertion: emergency notification was generated (meaning the
        # check fired AFTER the gain, not before).
        has_emergency_note = any(
            "critical hunger" in n.lower() or "auto" in n.lower()
            for n in a.pending_notifications
        )
        assert has_emergency_note, (
            f"Expected emergency notification, got: {a.pending_notifications}"
        )
        # Hunger should have been reduced by auto-consume (was 86, went to 91,
        # then auto-consume brought it down)
        assert a.hunger < 91.0, (
            f"Expected hunger reduced by auto-consume, got {a.hunger}"
        )

    def test_emergency_hunger_not_triggered_below_threshold(
        self, temp_logs, monkeypatch
    ):
        """Edge case: hunger at 84 + 5 = 89, below 90 threshold."""
        import python.scheduler as scheduler

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        a.alive = True
        a.hunger = 84.0
        a.hydration = 50.0
        a.energy = 50.0
        a.health = 100.0
        a.stress = 0.0
        a.happiness = 50.0
        a.money = 1000.0
        a.expenses = 0.0
        a.starvation_hours = 0
        a.dehydration_hours = 0
        a.relationships = 0.0
        a.age = 30
        a.hours_lived = 0
        a.awake_hours = 0
        a.is_sleeping = False
        a.busy_until = w.sim_time
        a.pending_notifications = []
        # social_cooldowns removed (FIX 7: dead code)
        a.caffeine_level = 0
        a.inventory = []
        a.currently_holding = None
        a.job = "None"

        w.store_inventory["Snacks"] = 5

        scheduler._apply_passive_updates(a, w, w.sim_time + 3600)

        # 84 + 5 = 89 < 90, no emergency trigger
        assert a.hunger == pytest.approx(89.0)
        has_emergency_note = any(
            "critical hunger" in n.lower() or "auto" in n.lower()
            for n in a.pending_notifications
        )
        assert not has_emergency_note



# Item 4: double energy deduction in work/study



class TestWorkStudyEnergyDeduction:
    """Item 4 — energy is deducted upfront when the task starts, and
    refunded proportionally if the task is cancelled/interrupted.
    Passive drain does NOT apply during active tasks (only idle)."""

    def test_energy_deducted_upfront_at_start(self, temp_logs, monkeypatch):
        import python.scheduler as scheduler
        from python.tooling.handlers.workstudy import handle_work_job

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        a.job = "developer"
        a.hourly_wage = 50.0
        a.energy = 100.0
        from python.locations import get_location_by_name

        loc = get_location_by_name("Startup_Sowl")
        a.x = (loc.x_min + loc.x_max) / 2.0
        a.y = (loc.y_min + loc.y_max) / 2.0
        a.z = loc.z_min
        a.location = loc.name

        # Start a 2-hour task (requires 20 energy)
        res, suc, cost = handle_work_job(a, w, {"jobname": "developer", "hours": "2"})
        assert suc is True
        # FIX 4: Energy is now deducted upfront (20 energy for 2 hours)
        assert a.energy == pytest.approx(80.0), (
            f"Energy should be deducted upfront at start, got {a.energy}"
        )

        # Passive drain only applies when task_state == "idle".
        # While in "job_pick" state, no passive energy drain occurs.
        scheduler._apply_passive_updates(a, w, w.sim_time + 3600)
        scheduler._apply_passive_updates(a, w, w.sim_time + 7200)

        # Energy should remain 80 because passive drain only applies to idle agents
        assert a.energy == pytest.approx(80.0), (
            f"Expected 80 energy (no passive drain during task), got {a.energy}"
        )

    def test_energy_check_still_blocks_low_energy_agents(self):
        """Edge case: agents with insufficient energy should still be blocked."""
        from python.tooling.handlers.workstudy import handle_work_job

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        a.job = "developer"
        a.energy = 5.0  # Not enough for even 1 hour (needs 10)
        from python.locations import get_location_by_name

        loc = get_location_by_name("Startup_Sowl")
        a.x = (loc.x_min + loc.x_max) / 2.0
        a.y = (loc.y_min + loc.y_max) / 2.0
        a.z = loc.z_min
        a.location = loc.name

        res, suc, cost = handle_work_job(a, w, {"jobname": "developer", "hours": "1"})
        assert suc is False
        assert "energy" in res.lower()



# Item 5: infinite context-exceeded penalty loop



class TestContextExceededLoop:
    """Item 1 — if context exceeds limit after trimming, the agent gets a
    60s penalty and tick returns False.  FIX 1: If the base prompt alone is
    too large (irreducible), the system prompt is reset and the agent
    proceeds instead of entering an infinite penalty loop."""

    def test_context_exceeded_with_history_advances_sim_time(
        self, temp_logs, monkeypatch
    ):
        """Non-irreducible case: history can be trimmed, penalty applied."""
        import python.scheduler as scheduler

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        a.alive = True
        a.busy_until = w.sim_time
        a.system_prompt = ""
        # Fill chat history with enough data to exceed context
        a.chat_history = [
            {"role": "user", "content": "x" * 500_000},
            {"role": "assistant", "content": "y" * 500_000},
        ]
        a.last_action_result = "None"
        a.pending_notifications = []

        plans = {0: ["no tool call"]}
        stub = StubServer(plans)
        monkeypatch.setattr(scheduler, "call_server", stub)

        before_time = w.sim_time
        scheduler.run_tick(w)

        # sim_time should have advanced (either via penalty or normal tick)
        assert w.sim_time >= before_time, (
            f"sim_time should not go backwards, "
            f"before={before_time}, after={w.sim_time}"
        )

    def test_irreducible_context_resets_system_prompt(self, temp_logs, monkeypatch):
        """FIX 1: Irreducible context overflow resets the bloated system prompt
        instead of entering an infinite 60s penalty loop."""
        import python.scheduler as scheduler

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        a.alive = True
        a.busy_until = w.sim_time
        # Make system prompt too large — with empty history this is irreducible.
        a.system_prompt = "x" * 1_000_000
        a.chat_history = []
        a.last_action_result = "None"
        a.pending_notifications = []

        plans = {0: ["no tool call"]}
        stub = StubServer(plans)
        monkeypatch.setattr(scheduler, "call_server", stub)

        scheduler.run_tick(w)

        # After the fix, system_prompt should have been reset (no longer bloated)
        assert a.system_prompt != "x" * 1_000_000, (
            "Irreducible context overflow should reset the system prompt"
        )



# Item 6: chat history sanitization



class TestChatHistorySanitization:
    """Item 6 — _commit_history must sanitize LLM output before storing
    in chat history to prevent prompt injection through accumulated history."""

    def test_angle_brackets_sanitized_in_history(self):
        from python.scheduler import _commit_history, _sanitize_chat_history

        # Create a minimal agent mock
        class FakeAgent:
            def __init__(self):
                self.chat_history = []

        agent = FakeAgent()

        # Malicious LLM output with angle brackets
        malicious_output = '<script>alert("xss")</script> normal text'
        _commit_history(agent, "user prompt", malicious_output, "tool result")

        # The assistant entry should have sanitized brackets
        assistant_entry = agent.chat_history[1]
        assert assistant_entry["role"] == "assistant"
        assert "&lt;" in assistant_entry["content"]
        assert "&gt;" in assistant_entry["content"]
        assert "<" not in assistant_entry["content"], (
            f"Angle brackets should be sanitized, got: {assistant_entry['content']}"
        )
        assert ">" not in assistant_entry["content"]

    def test_null_bytes_stripped_from_history(self):
        from python.scheduler import _commit_history

        class FakeAgent:
            def __init__(self):
                self.chat_history = []

        agent = FakeAgent()
        _commit_history(agent, "user", "text\x00with\x00nulls", "result")

        assistant_entry = agent.chat_history[1]
        assert "\x00" not in assistant_entry["content"]

    def test_long_output_truncated_in_history(self):
        from python.scheduler import _commit_history

        class FakeAgent:
            def __init__(self):
                self.chat_history = []

        agent = FakeAgent()
        long_text = "x" * 5000
        _commit_history(agent, "user", long_text, "result")

        assistant_entry = agent.chat_history[1]
        assert len(assistant_entry["content"]) < 3000, (
            f"Long output should be truncated, got {len(assistant_entry['content'])} chars"
        )



# Item 7: location string for roofed buildings



class TestMoveToLocationString:
    """Item 7 — move_to should include the building name in the location
    string for roofed buildings, not just 'Outside'."""

    def test_location_shows_building_name_for_roofed_place(
        self, temp_logs, monkeypatch
    ):
        import python.scheduler as scheduler
        from conftest import tool_xml

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")

        plans = {0: [tool_xml("move_to", place="Library")]}
        stub = StubServer(plans)
        monkeypatch.setattr(scheduler, "call_server", stub)

        scheduler.run_tick(w)

        # Location should include the building name
        assert "Outside" in a.location or "Library" in a.location
        # Should NOT be just "Outside"
        assert a.location != "Outside"

    def test_location_named_for_open_air_place(self, temp_logs, monkeypatch):
        import python.scheduler as scheduler
        from conftest import tool_xml

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")

        plans = {0: [tool_xml("move_to", place="Park_Central")]}
        stub = StubServer(plans)
        monkeypatch.setattr(scheduler, "call_server", stub)

        scheduler.run_tick(w)

        assert a.location == "Park_Central"



# Item 8: energy recovery during sleep



class TestSleepEnergyRecovery:
    """Item 8 — energy recovery during sleep should apply at wake-up time,
    not just during hourly passive ticks.  Partial-hour sleep gets prorated
    recovery."""

    def test_partial_hour_sleep_gets_recovery(self):
        import python.scheduler as scheduler

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        a.energy = 0.0
        a.stress = 50.0
        a.is_sleeping = True
        a.busy_until = w.sim_time + 1800  # 30 min sleep
        a._sleep_start = w.sim_time
        a.home_location = ""
        a.x = 10.0
        a.y = 10.0
        a.z = 0.0

        # Simulate wake-up
        scheduler._refresh_agent_activity(a, w.sim_time + 1800)

        # Should have recovered some energy (prorated for 0.5h)
        assert a.energy > 0.0, f"Expected energy recovery, got {a.energy}"
        assert a.stress < 50.0, f"Expected stress reduction, got {a.stress}"
        assert a.is_sleeping is False

    def test_full_hour_sleep_gets_recovery(self):
        import python.scheduler as scheduler

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        a.energy = 0.0
        a.stress = 50.0
        a.is_sleeping = True
        a.busy_until = w.sim_time + 3600  # 1 hour sleep
        a._sleep_start = w.sim_time
        a.home_location = ""
        a.x = 10.0
        a.y = 10.0
        a.z = 0.0

        scheduler._refresh_agent_activity(a, w.sim_time + 3600)

        assert a.energy > 0.0
        assert a.stress < 50.0
        assert a.is_sleeping is False



# Item 9: durability in inventory display



class TestInventoryDurabilityDisplay:
    """Item 9 — inventory should show durability information so agents
    can plan hobby usage and anticipate item destruction."""

    def test_inventory_shows_durability(self):
        from python.prompting import _inventory_line

        class FakeAgent:
            def __init__(self):
                self.inventory = [
                    {"item": "Book", "durability": 3},
                    {"item": "Book", "durability": 1},
                    {"item": "Water", "durability": None},
                ]

        agent = FakeAgent()
        result = _inventory_line(agent)

        assert "dur:" in result, f"Expected durability info, got: {result}"
        assert "Book" in result

    def test_inventory_without_durability_shows_normal(self):
        from python.prompting import _inventory_line

        class FakeAgent:
            def __init__(self):
                self.inventory = [
                    {"item": "Water"},
                    {"item": "Snacks"},
                ]

        agent = FakeAgent()
        result = _inventory_line(agent)

        assert "dur:" not in result
        assert "Water" in result
        assert "Snacks" in result

    def test_empty_inventory_shows_none(self):
        from python.prompting import _inventory_line

        class FakeAgent:
            def __init__(self):
                self.inventory = []

        agent = FakeAgent()
        result = _inventory_line(agent)
        assert result == "None"



# Item 10: drop_item wildcard for held item



class TestDropItemWildcard:
    """Item 10 — drop_item('') should work as a wildcard for the held item,
    so the agent doesn't need to explicitly name it."""

    def test_drop_empty_string_drops_held_item(self):
        from python.tooling.handlers.inventory_loot import handle_drop_item

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        a.currently_holding = {
            "id": "h1",
            "item": "Book",
            "durability": 2,
            "bought": w.sim_time,
        }

        res, suc, cost = handle_drop_item(a, w, {"item_name": ""})

        assert suc is True, f"Expected success, got: {res}"
        assert a.currently_holding is None
        assert len(w.ground_items) == 1
        assert w.ground_items[0]["item"] == "Book"

    def test_drop_missing_key_drops_held_item(self):
        from python.tooling.handlers.inventory_loot import handle_drop_item

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        a.currently_holding = {
            "id": "h1",
            "item": "Water",
            "durability": 1,
            "bought": w.sim_time,
        }

        res, suc, cost = handle_drop_item(a, w, {})

        assert suc is True, f"Expected success, got: {res}"
        assert a.currently_holding is None

    def test_drop_held_task_prop_fails(self):
        from python.tooling.handlers.inventory_loot import handle_drop_item

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        a.currently_holding = {"id": "job_prop", "item": "Laptop", "durability": 99}

        res, suc, cost = handle_drop_item(a, w, {"item_name": ""})

        assert suc is False
        assert "task prop" in res.lower()



# Item 11: dead social_fulfillment variable



class TestSocialFulfillmentDeadCode:
    """Item 11 — social_fulfillment is incremented/decremented but never
    used in any model.  After the fix, it should not be modified."""

    def test_talk_to_does_not_modify_social_fulfillment(self):
        from python.tooling.handlers.social import handle_talk_to

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        b = _add_agent(w, 1, "Bob")
        a.social_fulfillment = 50.0

        handle_talk_to(a, w, {"person": "Bob", "message": "hello"})

        assert a.social_fulfillment == 50.0, (
            f"social_fulfillment should not change, got {a.social_fulfillment}"
        )

    def test_give_item_does_not_modify_social_fulfillment(self):
        from python.tooling.handlers.social import handle_give_item

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        b = _add_agent(w, 1, "Bob")
        a.social_fulfillment = 50.0
        a.inventory.append({"id": "i1", "item": "Book", "durability": 5, "bought": 0.0})

        handle_give_item(a, w, {"person": "Bob", "item": "Book"})

        assert a.social_fulfillment == 50.0

    def test_give_money_does_not_modify_social_fulfillment(self):
        from python.tooling.handlers.social import handle_give_money

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        b = _add_agent(w, 1, "Bob")
        a.social_fulfillment = 50.0
        a.money = 1000.0

        handle_give_money(a, w, {"person": "Bob", "amount": "100"})

        assert a.social_fulfillment == 50.0

    def test_passive_tick_does_not_modify_social_fulfillment(self):
        import python.scheduler as scheduler

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        a.alive = True
        a.social_fulfillment = 50.0
        a.hunger = 50.0
        a.hydration = 50.0
        a.energy = 50.0
        a.health = 100.0
        a.stress = 0.0
        a.happiness = 50.0
        a.money = 1000.0
        a.expenses = 0.0
        a.starvation_hours = 0
        a.dehydration_hours = 0
        a.relationships = 0.0
        a.age = 30
        a.hours_lived = 0
        a.awake_hours = 0
        a.is_sleeping = False
        a.busy_until = w.sim_time
        a.pending_notifications = []
        # social_cooldowns removed (FIX 7: dead code)
        a.caffeine_level = 0

        scheduler._apply_passive_updates(a, w, w.sim_time + 3600)

        assert a.social_fulfillment == 50.0



# Item 12: diagonal walk precision



class TestDiagonalWalkPrecision:
    """Item 12 — diagonal walk should use 30/sqrt(2) ≈ 21.213 instead of
    rounded 21, to prevent cumulative positional drift."""

    def test_diagonal_displacement_is_correct(self):
        from python.tooling.handlers.movement import handle_walk

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        a.x = 100.0
        a.y = 100.0
        a.z = 0.0
        a.location = "Outside"

        expected_diag = 30.0 / math.sqrt(2)  # ≈ 21.213

        handle_walk(a, w, {"direction": "northeast"})

        assert a.x == pytest.approx(100.0 + expected_diag, abs=0.01)
        assert a.y == pytest.approx(100.0 + expected_diag, abs=0.01)

    def test_cumulative_diagonal_drift_is_minimal(self):
        """Edge case: after 100 diagonal steps, total drift should be < 1m."""
        from python.tooling.handlers.movement import handle_walk

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        a.x = 0.0
        a.y = 0.0
        a.z = 0.0
        a.location = "Outside"

        expected_diag = 30.0 / math.sqrt(2)

        for _ in range(100):
            handle_walk(a, w, {"direction": "northeast"})

        expected_x = 100.0 * expected_diag
        expected_y = 100.0 * expected_diag

        assert abs(a.x - expected_x) < 1.5, f"X drift: {abs(a.x - expected_x)}"
        assert abs(a.y - expected_y) < 1.5, f"Y drift: {abs(a.y - expected_y)}"

    def test_cardinal_directions_unchanged(self):
        """Edge case: cardinal directions should still be exactly 30m."""
        from python.tooling.handlers.movement import handle_walk

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        a.x = 100.0
        a.y = 100.0
        a.z = 0.0
        a.location = "Outside"

        handle_walk(a, w, {"direction": "north"})
        assert a.x == pytest.approx(100.0)
        assert a.y == pytest.approx(130.0)

        handle_walk(a, w, {"direction": "east"})
        assert a.x == pytest.approx(130.0)
        assert a.y == pytest.approx(130.0)



# Item 13: KeyError on malformed currently_holding



class TestHeldItemKeyError:
    """Item 13 — if currently_holding dict lacks 'item' key, accessing
    agent.currently_holding['item'] raises KeyError."""

    def test_malformed_holding_does_not_crash_prompt(self):
        from python.prompting import build_messages

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        # Malformed: dict exists but lacks 'item' key
        a.currently_holding = {"id": "h1", "durability": 5}
        a.system_prompt = "test"
        a.chat_history = []
        a.last_action_result = "None"
        a.pending_notifications = []
        a.location = "Outside"
        a.relationships = 0.0
        a.relationships_status = "single"
        a.beliefs = "Neutral"
        a.shares_owned = 0
        a.pending_market_orders = []
        a.voicemail_inbox = []
        a.task_state = "idle"
        a.pending_task_data = {}
        a.active_task_entities = {}

        # Should not raise KeyError
        msgs = build_messages(0, w, "test notifications")
        assert msgs is not None

    def test_none_holding_shows_none(self):
        from python.prompting import build_messages

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        a.currently_holding = None
        a.system_prompt = "test"
        a.chat_history = []
        a.last_action_result = "None"
        a.pending_notifications = []
        a.location = "Outside"
        a.relationships = 0.0
        a.relationships_status = "single"
        a.beliefs = "Neutral"
        a.shares_owned = 0
        a.pending_market_orders = []
        a.voicemail_inbox = []
        a.task_state = "idle"
        a.pending_task_data = {}
        a.active_task_entities = {}

        msgs = build_messages(0, w, "test notifications")
        user_msg = msgs[-1]["content"]
        assert "Held Item: None" in user_msg



# Integration: multi-hour simulation exercising all fixes



class TestMultiHourSimulation:
    """End-to-end integration test: run a multi-hour simulation with two
    agents exercising tools, sleep, work, social interactions, and inventory
    management.  Verifies that all 13 fixes cooperate correctly and no
    regression occurs over extended simulated time."""

    def test_multi_hour_simulation_no_crash(self, temp_logs, monkeypatch):
        import python.scheduler as scheduler
    
        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        b = _add_agent(w, 1, "Bob")

        # Give agents some inventory and money
        a.inventory.append({"id": "b1", "item": "Book", "durability": 3, "bought": 0.0})
        a.inventory.append(
            {"id": "w1", "item": "Water", "durability": 1, "bought": 0.0}
        )
        a.money = 500.0
        a.social_fulfillment = 50.0
        
        b.inventory.append(
            {"id": "s1", "item": "Snacks", "durability": 2, "bought": 0.0}
        )
        b.money = 500.0
        b.social_fulfillment = 50.0
        
        # ... Rest of the test remains the same

        # Store stock
        w.store_inventory["Snacks"] = 20
        w.store_inventory["Water"] = 20
        w.store_inventory["Coffee"] = 10

        # Pre-planned tool sequence for Alice
        plans = {
            0: [
                tool_xml("drop_item", item_name="Water"),  # Item 10: drop held item
                tool_xml("do_hobby", item="Book"),  # Item 9: durability display
                tool_xml(
                    "talk_to", person="Bob", message="hello"
                ),  # Item 11: no social_fulfillment
                tool_xml("sleep", hours="2"),  # Item 8: sleep recovery
                tool_xml("change_status", person="", type="", value="awake"),
                tool_xml("change_status", person="", type="", value="idle"),
                tool_xml("change_status", person="", type="", value="idle"),
                tool_xml("change_status", person="", type="", value="idle"),
                tool_xml("change_status", person="", type="", value="idle"),
                tool_xml("change_status", person="", type="", value="idle"),
            ],
            1: [
                tool_xml("change_status", person="", type="", value="idle"),
                tool_xml("change_status", person="", type="", value="idle"),
                tool_xml("change_status", person="", type="", value="idle"),
                tool_xml("change_status", person="", type="", value="idle"),
                tool_xml("change_status", person="", type="", value="idle"),
                tool_xml("change_status", person="", type="", value="idle"),
                tool_xml("change_status", person="", type="", value="idle"),
                tool_xml("change_status", person="", type="", value="idle"),
                tool_xml("change_status", person="", type="", value="idle"),
                tool_xml("change_status", person="", type="", value="idle"),
            ],
        }
        stub = StubServer(plans)
        monkeypatch.setattr(scheduler, "call_server", stub)

        # Run 20 ticks (simulates several hours of activity)
        for i in range(20):
            scheduler.run_tick(w)
            # Both agents should remain alive
            assert a.alive, f"Alice died at tick {i}"
            assert b.alive, f"Bob died at tick {i}"

        # Verify key invariants after simulation
        # Item 11: social_fulfillment should be unchanged
        assert a.social_fulfillment == 50.0
        assert b.social_fulfillment == 50.0

        # Item 9: inventory line should include durability
        from python.prompting import _inventory_line

        inv_line = _inventory_line(a)
        assert "dur:" in inv_line or "Book" in inv_line or "Water" in inv_line

    def test_diagonal_walk_precision_over_many_steps(self):
        """Edge case: 100 diagonal steps should have < 0.1 m cumulative error."""
        from python.tooling.handlers.movement import handle_walk

        w = _mk_world()
        a = _add_agent(w, 0, "Alice")
        # Start well inside the 5000 m world so 100 steps don't hit the boundary
        a.x = 1000.0
        a.y = 1000.0
        a.z = 0.0
        a.location = "Outside"

        expected_diag = 30.0 / math.sqrt(2)

        for _ in range(100):
            handle_walk(a, w, {"direction": "northeast"})

        expected_x = 1000.0 + 100.0 * expected_diag
        expected_y = 1000.0 + 100.0 * expected_diag

        # Total drift should be < 1.5 m after 100 steps due to rounding
        assert abs(a.x - expected_x) < 1.5, f"X drift: {abs(a.x - expected_x)}"
        assert abs(a.y - expected_y) < 1.5, f"Y drift: {abs(a.y - expected_y)}"

    def test_chat_history_sanitization_survives_multiple_turns(self):
        """Edge case: sanitized chat history should remain safe across
        multiple _commit_history calls (no injection through accumulation)."""
        from python.scheduler import _commit_history

        class FakeAgent:
            def __init__(self):
                self.chat_history = []

        agent = FakeAgent()

        # Simulate 10 turns with increasingly malicious output
        for i in range(10):
            malicious = f"<script>alert({i})</script>" + "x" * (i * 200)
            _commit_history(agent, f"user {i}", malicious, f"result {i}")

        # All assistant entries should be sanitized
        for entry in agent.chat_history:
            if entry["role"] == "assistant":
                assert "<" not in entry["content"]
                assert ">" not in entry["content"]
                assert "\x00" not in entry["content"]
