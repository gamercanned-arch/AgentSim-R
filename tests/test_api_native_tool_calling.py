from types import SimpleNamespace


def test_prepare_messages_for_native_tools_removes_legacy_xml_contract():
    from python.api_llm import _prepare_messages_for_native_tools

    messages = [
        {
            "role": "system",
            "content": (
                "You MUST reply with one or more tool calls.\n"
                "- Use only the tools listed in your system instructions.\n"
                "TOOL CALLING FORMAT: (EXAMPLE CALL)\n"
                "<tool_call>\n"
                "<function=move_to>\n"
                "<parameter=place>\n"
                "Library\n"
                "</parameter>\n"
                "</function>\n"
                "</tool_call>\n\n"
                "[Dynamic Simulation Rules]\n"
                "- Do NOT output any text after </tool_call>.\n"
                "- Coordinates shown in observations are read-only telemetry.\n"
            ),
        }
    ]

    prepared = _prepare_messages_for_native_tools(messages)
    system_text = prepared[0]["content"]

    assert "[Native Tool Calling]" in system_text
    assert "function tools provided by the API request" in system_text
    assert "<tool_call" not in system_text
    assert "<function=" not in system_text
    assert "TOOL CALLING FORMAT" not in system_text
    assert "Coordinates shown in observations" in system_text


def test_router_sends_tools_via_genai_config_and_adapts_function_call(monkeypatch):
    import os
    import time

    from python.api_llm import LLMRouter, ProviderConfig
    from python.tooling.parsing import parse_tool_calls
    from google import genai
    from google.genai import types

    for key in list(os.environ):
        if key.startswith("GEMINI_API_KEY"):
            monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_TPM_LIMIT", "220000")
    monkeypatch.setattr("python.api_llm.load_dotenv", lambda: None)
    monkeypatch.setattr(time, "sleep", lambda _: None)

    captured = {}

    class DummyClient:
        def __init__(self, api_key):
            captured["api_key"] = api_key

            class DummyModels:
                def generate_content(inner_self, model, contents, config):
                    captured["model"] = model
                    captured["contents"] = contents
                    captured["config"] = config
                    return SimpleNamespace(
                        function_calls=[
                            SimpleNamespace(name="wait", args={"minutes": 15})
                        ],
                        candidates=[],
                        usage_metadata=SimpleNamespace(
                            prompt_token_count=11,
                            candidates_token_count=2,
                        ),
                    )

            self.models = DummyModels()

    monkeypatch.setattr(genai, "Client", lambda api_key: DummyClient(api_key))

    cfg = ProviderConfig(
        name="gemini",
        models=["gemini-test"],
        max_output_tokens=64,
    )
    router = LLMRouter(
        provider_order=["gemini"],
        provider_configs={"gemini": cfg},
        max_output_tokens=64,
    )
    router.quota = None

    out, prompt_tokens, completion_tokens = router(
        [
            {
                "role": "system",
                "content": "<tools>legacy prompt tools should not be sent</tools>",
            },
            {"role": "user", "content": "Stats: tired, waiting for store open."},
        ],
        agent_id=1,
    )

    calls, err = parse_tool_calls(out)
    assert err is None
    assert calls == [("wait", {"minutes": "15"})]
    assert prompt_tokens == 11
    assert completion_tokens == 2

    config = captured["config"]
    assert config.tools
    declarations = config.tools[0].function_declarations
    declaration_names = {d.name for d in declarations}
    assert "wait" in declaration_names
    assert "move_to" in declaration_names
    assert config.tool_config.function_calling_config.mode == types.FunctionCallingConfigMode.ANY
    assert config.automatic_function_calling.disable is True
    assert "<tools>" not in (config.system_instruction or "")


def test_call_specific_raw_does_not_attach_simulation_tools(monkeypatch):
    import os
    import time

    from python.api_llm import LLMRouter, ProviderConfig
    from google import genai

    for key in list(os.environ):
        if key.startswith("GEMINI_API_KEY"):
            monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("python.api_llm.load_dotenv", lambda: None)
    monkeypatch.setattr(time, "sleep", lambda _: None)

    captured = {}

    class DummyClient:
        def __init__(self, api_key):
            class DummyModels:
                def generate_content(inner_self, model, contents, config):
                    captured["config"] = config
                    return SimpleNamespace(
                        candidates=[
                            SimpleNamespace(
                                content=SimpleNamespace(
                                    parts=[
                                        SimpleNamespace(
                                            text="summary text",
                                            thought=False,
                                            function_call=None,
                                        )
                                    ]
                                )
                            )
                        ],
                        usage_metadata=None,
                    )

            self.models = DummyModels()

    monkeypatch.setattr(genai, "Client", lambda api_key: DummyClient(api_key))

    cfg = ProviderConfig(name="gemini", models=["gemini-test"])
    router = LLMRouter(
        provider_order=["gemini"],
        provider_configs={"gemini": cfg},
    )
    router.quota = None

    out = router.call_specific_raw(
        "gemini",
        "gemini-test",
        [{"role": "user", "content": "summarize"}],
    )

    assert out == "summary text"
    assert captured["config"].tools is None
    assert captured["config"].tool_config is None
