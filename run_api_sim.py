from __future__ import annotations

import glob
import json
import os
import time

from dotenv import load_dotenv

from python.api_llm import LLMRouter, ProviderConfig, Summarizer
from python.bootstrap import build_starting_world
from python.config import CACHE_DIR, LOG_DIR, MAX_RUNTIME_MINUTES, N_AGENTS
from python.locations import describe_home_location
from python.logger import log_global
from python.persistence import load_world, save_exists, save_world
import python.scheduler as scheduler


SAVE_PATH = "saves/world.json"
AUTOSAVE_TICKS = int(os.environ.get("AUTOSAVE_TICKS", "10"))

API_CONTEXT_SIZE = int(os.environ.get("API_CONTEXT_SIZE", "100000"))
API_CONTEXT_FILL_RATIO = float(os.environ.get("API_CONTEXT_FILL_RATIO", "0.80"))
API_MAX_NEW_TOKENS = int(os.environ.get("API_MAX_NEW_TOKENS", "16384"))
API_TOKEN_TARGET = int(API_CONTEXT_SIZE * API_CONTEXT_FILL_RATIO)


def _wipe_cache_and_logs() -> None:
    for f in glob.glob(os.path.join(CACHE_DIR, "*.bin")):
        try:
            os.remove(f)
        except OSError:
            pass
    for f in glob.glob(os.path.join(LOG_DIR, "*.*")):
        try:
            os.remove(f)
        except OSError:
            pass
    try:
        if os.path.exists(SAVE_PATH):
            os.remove(SAVE_PATH)
    except OSError:
        pass


def _render_prompt_plain(messages: list) -> str:
    parts = []
    for m in messages or []:
        parts.append(f"[{m.get('role','?').upper()}]\n{m.get('content','')}\n")
    return "\n".join(parts)


def _estimate_prompt_tokens_plain(messages: list, prompt_text: str | None = None) -> int:
    if prompt_text is None:
        prompt_text = _render_prompt_plain(messages)
    return max(1, len(prompt_text) // 4)


def _count_turns(chat_history: list) -> int:
    return sum(1 for m in chat_history if m.get("role") == "user")


def _extract_turn_text(chat_history: list, turn_count: int, max_chars_per_msg: int = 800) -> str:
    def trunc(s: str) -> str:
        s = "" if s is None else str(s)
        s = s.replace("\x00", "")
        if len(s) > max_chars_per_msg:
            s = s[: max_chars_per_msg - 20] + f"... ({len(s)} chars)"
        return s

    n_msgs = min(len(chat_history), turn_count * 3)
    chunk = chat_history[:n_msgs]
    lines = []
    for i, m in enumerate(chunk, start=1):
        role = m.get("role", "?")
        lines.append(f"{i:03d}:{role}: {trunc(m.get('content',''))}")
    return "\n".join(lines)


def _drop_first_n_turns(chat_history: list, turn_count: int) -> list:
    n_msgs = min(len(chat_history), turn_count * 3)
    return chat_history[n_msgs:]


def _ensure_summary_fields(agent) -> None:
    if not hasattr(agent, "summary_text"):
        agent.summary_text = ""
    if not hasattr(agent, "summary_turns_summarized"):
        agent.summary_turns_summarized = 0


def _summarize_old_turns(agent, summarizer: Summarizer, turns_to_summarize: int) -> None:
    if turns_to_summarize <= 0:
        return
    chunk_text = _extract_turn_text(agent.chat_history, turn_count=turns_to_summarize)
    agent.summary_text = summarizer.summarize(agent.summary_text, chunk_text)
    agent.summary_turns_summarized += turns_to_summarize
    agent.chat_history = _drop_first_n_turns(agent.chat_history, turn_count=turns_to_summarize)


def _maybe_summarize_agent(agent, world, summarizer: Summarizer, base_build_messages) -> None:
    if getattr(agent, "_summary_checked_at_time", None) == world.sim_time:
        return
    agent._summary_checked_at_time = world.sim_time

    _ensure_summary_fields(agent)

    while True:
        msgs = base_build_messages(agent.id, world, "")
        summary = (getattr(agent, "summary_text", "") or "").strip()
        if summary:
            msgs = [msgs[0], {"role": "system", "content": "Summary of prior events:\n" + summary}] + msgs[1:]
        est_tokens = _estimate_prompt_tokens_plain(msgs)

        turns = _count_turns(agent.chat_history)

        if turns >= 40:
            _summarize_old_turns(agent, summarizer, 30)
            agent.pending_notifications.append("Context compression: summarized 30 older turns.")
            continue

        if est_tokens > API_TOKEN_TARGET and turns > 10:
            to_sum = max(1, turns - 10)
            _summarize_old_turns(agent, summarizer, to_sum)
            agent.pending_notifications.append("Context compression: summarized older turns to fit context.")
            continue

        break


def _build_messages_api_wrapper(base_build_messages, summarizer: Summarizer):
    def _wrapped(agent_id: int, world, notifications: str):
        agent = world.agents[agent_id]
        _maybe_summarize_agent(agent, world, summarizer, base_build_messages)

        msgs = base_build_messages(agent_id, world, notifications)
        summary = (getattr(agent, "summary_text", "") or "").strip()
        if summary:
            msgs2 = [msgs[0]]
            msgs2.append({"role": "system", "content": "Summary of prior events:\n" + summary})
            msgs2.extend(msgs[1:])
            return msgs2
        return msgs

    return _wrapped


def _parse_models_value(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.lstrip().startswith("["):
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            pass
    raw = raw.replace(";", ",").replace("\n", ",")
    return [p.strip() for p in raw.split(",") if p.strip()]


def _models_from_env(provider_prefix: str, default: str) -> list[str]:
    raw_list = os.environ.get(f"{provider_prefix}_MODELS", "")
    models = _parse_models_value(raw_list)

    if not models:
        for i in range(1, 6):
            v = (os.environ.get(f"{provider_prefix}_MODEL_{i}", "") or "").strip()
            if v:
                models.append(v)

    if not models and default:
        models = [default]

    out, seen = [], set()
    for m in models:
        if m not in seen:
            out.append(m)
            seen.add(m)
    return out


def main():
    load_dotenv()

    tool_role_mode = os.environ.get("TOOL_ROLE_MODE", "tool").strip().lower()
    if tool_role_mode != "tool":
        raise RuntimeError("TOOL_ROLE_MODE must be 'tool' (tool_call_id enforced).")

    if save_exists(SAVE_PATH):
        choice = input("Save found. Continue from save? [c]ontinue / [w]ipe: ").strip().lower()
        if choice.startswith("w"):
            _wipe_cache_and_logs()
            world = build_starting_world()
        else:
            world = load_world(SAVE_PATH)
    else:
        choice = input("No save found. Start fresh? [y]/n: ").strip().lower()
        if choice.startswith("n"):
            return
        _wipe_cache_and_logs()
        world = build_starting_world()

    mode = input("Provider mode: [o]rdered / [r]andom_provider: ").strip().lower()
    provider_mode = "random_provider" if mode.startswith("r") else "ordered"

    provider_order = ["openrouter", "groq", "cerebras"]

    temp = float(os.environ.get("TEMP", "0.7"))
    top_p = float(os.environ.get("TOP_P", "0.9"))

    openrouter_models = _models_from_env("OPENROUTER", default="openai/gpt-5.2")
    groq_models = _models_from_env("GROQ", default="openai/gpt-oss-120b")
    cerebras_models = _models_from_env("CEREBRAS", default="qwen-3-235b-a22b-instruct-2507")

    provider_configs = {
        "openrouter": ProviderConfig(name="openrouter", models=openrouter_models, temperature=temp, top_p=top_p),
        "groq": ProviderConfig(name="groq", models=groq_models, temperature=temp, top_p=top_p),
        "cerebras": ProviderConfig(name="cerebras", models=cerebras_models, temperature=temp, top_p=top_p),
    }

    openrouter_headers = {}
    ref = os.environ.get("OPENROUTER_HTTP_REFERER", "").strip()
    title = os.environ.get("OPENROUTER_TITLE", "").strip()
    if ref:
        openrouter_headers["HTTP-Referer"] = ref
    if title:
        openrouter_headers["X-OpenRouter-Title"] = title

    router = LLMRouter(
        provider_order=provider_order,
        provider_configs=provider_configs,
        max_output_tokens=API_MAX_NEW_TOKENS,
        mode=provider_mode,
        openrouter_headers=openrouter_headers,
        tool_role_mode="tool",
    )

    sum_provider = os.environ.get("SUMMARY_PROVIDER", "openrouter").strip().lower()
    sum_model = os.environ.get("SUMMARY_MODEL", openrouter_models[0] if openrouter_models else "openai/gpt-5.2")

    sum_user_path = (os.environ.get("SUMMARY_USER_PROMPT_PATH", "") or "").strip() or None
    sum_user_inline = (os.environ.get("SUMMARY_USER_PROMPT", "") or "").strip() or None
    sum_system_inline = (os.environ.get("SUMMARY_SYSTEM_PROMPT", "") or "").strip() or None

    summarizer = Summarizer(
        router=router,
        provider=sum_provider,
        model=sum_model,
        max_output_tokens=int(os.environ.get("SUMMARY_MAX_TOKENS", "2048")),
        user_template=sum_user_inline,
        user_template_path=sum_user_path,
        system_prompt=sum_system_inline,
    )

    # Monkeypatch scheduler to use API router and simple token estimates
    scheduler.call_server = router  # type: ignore
    scheduler.render_prompt = _render_prompt_plain  # type: ignore
    scheduler.estimate_prompt_tokens = _estimate_prompt_tokens_plain  # type: ignore
    scheduler.CONTEXT_SIZE = API_CONTEXT_SIZE  # type: ignore
    scheduler.CONTEXT_FILL_RATIO = API_CONTEXT_FILL_RATIO  # type: ignore
    scheduler.MAX_NEW_TOKENS = API_MAX_NEW_TOKENS  # type: ignore

    base_build_messages = scheduler.build_messages
    scheduler.build_messages = _build_messages_api_wrapper(base_build_messages, summarizer)  # type: ignore

    for agent in world.agents.values():
        agent.z = 0.0
        if hasattr(agent, "vehicle_z"):
            agent.vehicle_z = 0.0
        print(
            f"Initialized {agent.name:>6s} | Job: {agent.job:<15s} | "
            f"Home: Home_{agent.name} ({describe_home_location(agent.home_location)}) | "
            f"Cash: ${agent.money:.2f} | Vehicle: {agent.vehicle_type}"
        )

    print(f"\nAgentSim-R API runner starting...\nTime limit: {MAX_RUNTIME_MINUTES}m")
    tick = 0
    start_wall = time.time()

    try:
        while True:
            if (time.time() - start_wall) / 60.0 >= MAX_RUNTIME_MINUTES:
                break

            scheduler.run_tick(world)
            tick += 1

            if AUTOSAVE_TICKS > 0 and tick % AUTOSAVE_TICKS == 0:
                save_world(world, SAVE_PATH)

            alive = sum(1 for a in world.agents.values() if a.alive)
            if tick % 5 == 0:
                print(
                    f"Tick {tick:4d} | Time: {world.sim_time/3600:.1f}h | "
                    f"Alive: {alive}/{N_AGENTS} | Mkt: ${world.market_price:.2f}"
                )

            if alive == 0:
                break
    except KeyboardInterrupt:
        print("\n[USER ABORTED]")
    except Exception as e:
        print(f"\n[FATAL ERROR] {e}")

    save_world(world, SAVE_PATH)

    log_global(
        {
            "simulation_complete": True,
            "ticks": tick,
            "sim_time_hours": round(world.sim_time / 3600.0, 2),
            "alive_agents": sum(1 for a in world.agents.values() if a.alive),
            "market_price": round(world.market_price, 2),
            "runner": "run_sim_api.py",
        }
    )
    print("\nSimulation complete.")


if __name__ == "__main__":
    main()