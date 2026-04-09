# run_api_sim.py
from __future__ import annotations

import glob
import json
import os
import re
import time

from dotenv import load_dotenv

from python.api_llm import LLMRouter, ProviderConfig, Summarizer, _tools_system_prefix
from python.bootstrap import build_starting_world
from python.config import CACHE_DIR, LOG_DIR, MAX_RUNTIME_MINUTES, N_AGENTS, CHARS_PER_TOKEN
from python.locations import describe_home_location
from python.logger import log_global
from python.persistence import load_world, save_exists, save_world
from python.prompting import GLOBAL_TOOLS_LIST
import python.scheduler as scheduler


SAVE_PATH = "saves/world.json"
AUTOSAVE_TICKS = int(os.environ.get("AUTOSAVE_TICKS", "").strip() or "10")

API_CONTEXT_SIZE = int(os.environ.get("API_CONTEXT_SIZE", "").strip() or "1000000")
API_CONTEXT_FILL_RATIO = float(os.environ.get("API_CONTEXT_FILL_RATIO", "").strip() or "0.80")
API_MAX_NEW_TOKENS = int(os.environ.get("API_MAX_NEW_TOKENS", "").strip() or "16384")
API_TOKEN_TARGET = int(API_CONTEXT_SIZE * API_CONTEXT_FILL_RATIO)


def _wipe_cache_and_logs() -> None:
    for f in glob.glob(os.path.join(CACHE_DIR, "*.bin")):
        try: os.remove(f)
        except OSError: pass
    for f in glob.glob(os.path.join(LOG_DIR, "*.*")):
        try: os.remove(f)
        except OSError: pass
    try:
        if os.path.exists(SAVE_PATH):
            os.remove(SAVE_PATH)
    except OSError: pass


def _render_prompt_plain(messages: list) -> str:
    parts = []
    for m in messages or []:
        parts.append(f"[{m.get('role','?').upper()}]\n{m.get('content','')}\n")
    return "\n".join(parts)


def _estimate_prompt_tokens_plain(messages: list, prompt_text: str | None = None) -> int:
    if prompt_text is None:
        prompt_text = _render_prompt_plain(messages)
    return max(1, len(prompt_text) // CHARS_PER_TOKEN)


def _count_turns(chat_history: list) -> int:
    return sum(1 for m in chat_history if m.get("role") == "user")


def _extract_turn_text(agent, chat_history: list, turn_count: int) -> str:
    n_msgs = min(len(chat_history), turn_count * 3)
    chunk = chat_history[:n_msgs]
    lines = []
    turn_idx = 1
    
    for m in chunk:
        role = m.get("role", "?")
        content = m.get("content", "")
        
        if role == "user":
            stats_part = content[:500].replace('\n', ' | ') 
            lines.append(f"\n--- Turn {turn_idx} ---")
            lines.append(f"Observation: {stats_part}...")
            
        elif role == "assistant":
            think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
            think = think_match.group(1).strip().replace('\n', ' ') if think_match else ""
            rest = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            
            if think: lines.append(f"{agent.name} (Thinking): {think}")
            lines.append(f"{agent.name} (Action): {rest}")
            
        elif role == "tool":
            lines.append(f"{agent.name} (Result): {content}")
            turn_idx += 1
            
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
    chunk_text = _extract_turn_text(agent, agent.chat_history, turns_to_summarize)
    
    try:
        # Cohesive Weaving Summarization
        existing = getattr(agent, "summary_text", "") or ""
        new_summary = summarizer.summarize(existing, chunk_text)
        agent.summary_text = new_summary
            
        agent.summary_turns_summarized += turns_to_summarize
        agent.chat_history = _drop_first_n_turns(agent.chat_history, turn_count=turns_to_summarize)
        
        # Hierarchical Compression: If the running summary gets too big (> 40k chars)
        if len(agent.summary_text) > 40000:
            macro_prompt = f"Compress this extremely long running summary into a dense, factual macro-summary without losing key relationship or financial data:\n{agent.summary_text}"
            agent.summary_text = summarizer.summarize("", macro_prompt)
            agent.pending_notifications.append("Memory compressed: Performed macro-summarization of past events.")
            
    except Exception as e:
        agent.pending_notifications.append(f"Context summarization failed temporarily: {e}")


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
            continue

        if est_tokens > API_TOKEN_TARGET and turns > 10:
            to_sum = max(1, turns - 10)
            _summarize_old_turns(agent, summarizer, to_sum)
            continue

        break


def _ensure_tools_prefixed_in_system(msgs: list[dict]) -> list[dict]:
    if not msgs:
        msgs = [{"role": "system", "content": ""}]
    if msgs[0].get("role") != "system":
        msgs = [{"role": "system", "content": ""}] + list(msgs)

    base = str(msgs[0].get("content", "") or "")
    if "<tools>" in base:
        return msgs

    msgs = list(msgs)
    msgs[0] = dict(msgs[0])
    msgs[0]["content"] = _tools_system_prefix(GLOBAL_TOOLS_LIST) + "\n\n" + base
    return msgs


def _build_messages_api_wrapper(base_build_messages, summarizer: Summarizer):
    def _wrapped(agent_id: int, world, notifications: str):
        agent = world.agents[agent_id]
        _maybe_summarize_agent(agent, world, summarizer, base_build_messages)

        msgs = base_build_messages(agent_id, world, notifications)
        msgs = _ensure_tools_prefixed_in_system(msgs)

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
    if not raw: return []
    if raw.lstrip().startswith("["):
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except Exception: pass
    raw = raw.replace(";", ",").replace("\n", ",")
    return [p.strip() for p in raw.split(",") if p.strip()]


def _load_models_list(filepath: str = "models_list") -> list[str]:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
            if lines: return lines
    except OSError: pass
    return ["gemini-2.5-flash"]


def _models_from_env(provider_prefix: str, default: str) -> list[str]:
    raw_list = os.environ.get(f"{provider_prefix}_MODELS", "")
    models = _parse_models_value(raw_list)

    if not models:
        i = 1
        misses = 0
        while misses < 20:
            v = (os.environ.get(f"{provider_prefix}_MODEL_{i}", "") or "").strip()
            if v:
                models.append(v)
                misses = 0
            else:
                misses += 1
            i += 1

    if not models and default:
        models = [default]

    out, seen = [], set()
    for m in models:
        if m not in seen:
            out.append(m)
            seen.add(m)
    return out


def main():
    load_dotenv(override=True)

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

    provider_mode = "ordered"
    provider_order = ["gemini"]

    temp = float(os.environ.get("LLM_TEMPERATURE", "").strip() or "0.7")
    top_p = float(os.environ.get("LLM_TOP_P", "").strip() or "0.9")

    default_models = _load_models_list()
    gemini_models = _models_from_env("GEMINI", default=default_models[0])
    if not gemini_models: gemini_models = default_models

    provider_configs = {
        "gemini": ProviderConfig(name="gemini", models=gemini_models, temperature=temp, top_p=top_p),
    }

    router = LLMRouter(
        provider_order=provider_order,
        provider_configs=provider_configs,
        max_output_tokens=API_MAX_NEW_TOKENS,
        mode=provider_mode,
        openrouter_headers={},
    )

    sum_provider = os.environ.get("SUMMARY_PROVIDER", "gemini").strip().lower()
    sum_model = os.environ.get("SUMMARY_MODEL", gemini_models[0] if gemini_models else default_models[0])

    summarizer = Summarizer(
        router=router,
        provider=sum_provider,
        model=sum_model,
        max_output_tokens=2048,
    )

    scheduler.call_server = router  
    scheduler.render_prompt = _render_prompt_plain  
    scheduler.estimate_prompt_tokens = _estimate_prompt_tokens_plain  
    scheduler.CONTEXT_SIZE = API_CONTEXT_SIZE  
    scheduler.CONTEXT_FILL_RATIO = API_CONTEXT_FILL_RATIO  
    scheduler.MAX_NEW_TOKENS = API_MAX_NEW_TOKENS  

    base_build_messages = scheduler.build_messages
    scheduler.build_messages = _build_messages_api_wrapper(base_build_messages, summarizer)  

    for agent in world.agents.values():
        agent.z = 0.0
        if hasattr(agent, "vehicle_z"):
            agent.vehicle_z = 0.0
        print(f"Initialized {agent.name:>6s} | Job: {agent.job:<15s} | Cash: ${agent.money:.2f}")

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
                print(f"Tick {tick:4d} | Time: {world.sim_time/3600:.1f}h | Alive: {alive}/{N_AGENTS}")

            if alive == 0:
                break
    except KeyboardInterrupt:
        print("\n[USER ABORTED]")
    except Exception as e:
        print(f"\n[FATAL ERROR] {e}")

    save_world(world, SAVE_PATH)
    log_global({"simulation_complete": True, "ticks": tick})
    print("\nSimulation complete.")

if __name__ == "__main__":
    main()