from conftest import tool_xml


def _world_with_agent():
    from python.state import AgentState, WorldState

    world = WorldState()
    world.sim_time = 0.0
    agent = AgentState(id=0, name="Alice", age=30)
    world.agents[0] = agent
    return world, agent


def test_single_legacy_tool_failure_uses_minimum_failure_cost():
    from python.tools import execute_tool

    world, agent = _world_with_agent()

    result, success, cost = execute_tool(
        tool_xml("drop_item", item_name=""),
        agent.id,
        world,
    )

    assert success is False
    assert "drop" in result.lower()
    assert cost == 60


def test_social_tools_reject_self_targets():
    from python.tooling.handlers.social import (
        handle_attack_person,
        handle_call_person,
        handle_change_status,
        handle_give_item,
        handle_talk_to,
    )
    from python.tooling.handlers.workstudy import handle_interact_with

    world, agent = _world_with_agent()
    agent.inventory.append({"id": "book1", "item": "Book"})

    calls = [
        handle_talk_to(agent, world, {"person": "Alice", "message": "hi"}),
        handle_call_person(agent, world, {"person": "Alice", "message": "hi"}),
        handle_give_item(agent, world, {"person": "Alice", "item": "Book"}),
        handle_change_status(
            agent,
            world,
            {"person": "Alice", "type": "relationship", "value": "dating"},
        ),
        handle_attack_person(agent, world, {"person": "Alice"}),
        handle_interact_with(agent, world, {"person_or_object": "Alice", "action": "wave"}),
    ]

    for _result, success, _cost in calls:
        assert success is False


def test_defaulted_tool_params_are_optional_in_schema():
    from python.tooling.execute import _validate_schema

    omitted_ok = [
        ("change_status", {}),
        ("do_hobby", {}),
        ("do_hobby", {"description": "breathing"}),
        ("drop_item", {}),
        ("get_education", {}),
        ("sleep", {}),
        ("wait", {}),
        ("work_job", {}),
    ]
    for name, args in omitted_ok:
        assert _validate_schema(name, args) is None

    still_required = [
        ("talk_to", {"person": "Alice"}),
        ("give_item", {"person": "Alice"}),
        ("interact_with", {"person_or_object": "Desk"}),
        ("move_to", {}),
    ]
    for name, args in still_required:
        assert _validate_schema(name, args) is not None


def test_quota_manager_persists_usage_by_key_fingerprint(tmp_path):
    from python.quota import QuotaManager

    state_path = str(tmp_path / "quota_state.json")
    model = "gemini-3.1-flash-lite"
    key_fingerprints = ["fake-key-fingerprint"]

    quota = QuotaManager(
        1,
        [model],
        key_fingerprints=key_fingerprints,
        state_path=state_path,
    )
    quota.record_request(0, model, prompt_tokens=10, completion_tokens=5)

    reloaded = QuotaManager(
        1,
        [model],
        key_fingerprints=key_fingerprints,
        state_path=state_path,
    )
    snapshot = reloaded.debug_snapshot()
    usage = snapshot["usage"][key_fingerprints[0]][model]

    assert usage["requests"] == 1
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 5
    assert usage["total_tokens"] == 15


def test_quota_manager_persists_recent_rate_windows(tmp_path):
    from python.quota import QuotaManager

    state_path = str(tmp_path / "quota_state.json")
    model = "gemini-3.1-flash-lite"
    key_fingerprints = ["fake-key-fingerprint"]

    quota = QuotaManager(
        1,
        [model],
        key_fingerprints=key_fingerprints,
        state_path=state_path,
        rpm_limit=1,
        flash_lite_tpm_limit=100,
    )
    quota.reserve_request(0, model, estimated_tokens=80)
    quota.record_request(0, model, prompt_tokens=40, completion_tokens=10)

    reloaded = QuotaManager(
        1,
        [model],
        key_fingerprints=key_fingerprints,
        state_path=state_path,
        rpm_limit=1,
        flash_lite_tpm_limit=100,
    )

    assert reloaded.seconds_until_request_slot(0, model, estimated_tokens=1) > 0
    assert reloaded.seconds_until_request_slot(0, model, estimated_tokens=80) > 0


def test_gemini_value_error_rotates_instead_of_returning_empty(monkeypatch, tmp_path):
    import os
    import time

    from google import genai
    from python.api_llm import LLMRouter, ProviderConfig

    for key in list(os.environ.keys()):
        if key.startswith("GEMINI_API_KEY"):
            monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("GEMINI_API_KEY_1", "key1")
    monkeypatch.setenv("GEMINI_API_KEY_2", "key2")
    monkeypatch.setenv("GEMINI_QUOTA_STATE_PATH", str(tmp_path / "quota_state.json"))
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    monkeypatch.setattr("python.api_llm.load_dotenv", lambda: None)

    cfg = ProviderConfig(name="gemini", models=["gemini-3.1-flash-lite"])
    router = LLMRouter(provider_order=["gemini"], provider_configs={"gemini": cfg})

    called_keys = []

    class DummyResponse:
        candidates = []
        usage_metadata = None

    class DummyClient:
        def __init__(self, api_key):
            self.api_key = api_key

            class DummyModels:
                def generate_content(inner_self, model, contents, config):
                    called_keys.append(api_key)
                    if api_key == "key1":
                        raise ValueError("provider rejected request")
                    return DummyResponse()

            self.models = DummyModels()

    monkeypatch.setattr(genai, "Client", lambda api_key: DummyClient(api_key))

    raw = router._call_gemini_rich(
        "gemini-3.1-flash-lite",
        cfg,
        [{"role": "user", "content": "hi"}],
        agent_id=1,
    )

    assert called_keys == ["key1", "key2"]
    assert raw.provider == "gemini"
