# run_api_sim.py
from __future__ import annotations

import glob
import json
import os
import re
import time

from dotenv import load_dotenv
load_dotenv(override=True)

from python.api_llm import (
    LLMRouter,
    ProviderConfig,
    Summarizer,
    _prepare_messages_for_native_tools,
)
from python.bootstrap import build_starting_world
from python.config import (
    CACHE_DIR,
    LOG_DIR,
    MAX_RUNTIME_MINUTES,
    N_AGENTS,
    CHARS_PER_TOKEN,
    CONTEXT_SIZE as DEFAULT_API_CONTEXT_SIZE,
)
from python.locations import describe_home_location
from python.logger import log_global
from python.persistence import load_world, save_exists, save_world
import python.scheduler as scheduler


SAVE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "saves", "world.json"))
AUTOSAVE_TICKS = 10

API_CONTEXT_SIZE = DEFAULT_API_CONTEXT_SIZE
API_CONTEXT_FILL_RATIO = 0.80
API_MAX_NEW_TOKENS = 16384
API_TOKEN_TARGET = int(API_CONTEXT_SIZE * API_CONTEXT_FILL_RATIO)
DEFAULT_SUMMARY_MODELS = [
    "gemma-4-26b-a4b-it",
    "gemma-4-31b-it",
    "gemini-3.1-flash-lite",
]
DEFAULT_SUMMARY_MAX_OUTPUT_TOKENS = 16384
DEFAULT_SUMMARY_MAX_SUMMARY_TOKENS = 32768
DEFAULT_SUMMARY_COMPACT_AT_TOKENS = 24576


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


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else int(default)


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


def _find_msg_index_for_turns(chat_history: list, turn_count: int) -> int:
    user_seen = 0
    idx = 0
    while idx < len(chat_history):
        if chat_history[idx].get("role") == "user":
            if user_seen == turn_count:
                return idx
            user_seen += 1
        idx += 1
    return len(chat_history)


def _extract_turn_text(agent, chat_history: list, turn_count: int) -> str:
    n_msgs = _find_msg_index_for_turns(chat_history, turn_count)
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
            turn_idx += 1
            
        elif role == "assistant":
            think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
            think = think_match.group(1).strip().replace('\n', ' ') if think_match else ""
            rest = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            
            if think: lines.append(f"{agent.name} (Thinking): {think}")
            lines.append(f"{agent.name} (Action): {rest}")
            
        elif role == "tool":
            lines.append(f"{agent.name} (Result): {content}")
            
    return "\n".join(lines)


def _drop_first_n_turns(chat_history: list, turn_count: int) -> list:
    n_msgs = _find_msg_index_for_turns(chat_history, turn_count)
    return chat_history[n_msgs:]


def _ensure_summary_fields(agent) -> None:
    if not hasattr(agent, "summary_text"):
        agent.summary_text = ""
    if not hasattr(agent, "summary_turns_summarized"):
        agent.summary_turns_summarized = 0


def _summarize_old_turns(agent, summarizer: Summarizer, turns_to_summarize: int) -> bool:
    if turns_to_summarize <= 0:
        return True
    chunk_text = _extract_turn_text(agent, agent.chat_history, turns_to_summarize)
    
    max_retries = getattr(summarizer, "max_retries", None)
    backoff = 5.0
    attempts = 0
    while True:
        try:
            existing = getattr(agent, "summary_text", "") or ""
            new_summary = summarizer.summarize(existing, chunk_text, agent_id=agent.id)
            agent.summary_text = new_summary
            break
        except Exception as e:
            attempts += 1
            if max_retries is not None and attempts >= max_retries:
                agent.pending_notifications.append(f"Context summarization failed: {e}")
                return False
            agent.pending_notifications.append(
                f"Context summarization failed temporarily: {e}. Retrying in {backoff:.0f}s..."
            )
            time.sleep(backoff)
            backoff = min(60.0, backoff * 2.0)
            
    agent.summary_turns_summarized += turns_to_summarize
    agent.chat_history = _drop_first_n_turns(agent.chat_history, turn_count=turns_to_summarize)
    
    macro_at_tokens = getattr(summarizer, "compact_at_tokens", 40000 // CHARS_PER_TOKEN)
    if _summary_token_count(agent.summary_text) > macro_at_tokens:
        macro_prompt = f"Compress this extremely long running summary into a dense, factual macro-summary without losing key relationship or financial data:\n{agent.summary_text}"
        backoff = 5.0
        attempts = 0
        while True:
            try:
                agent.summary_text = summarizer.summarize("", macro_prompt, agent_id=agent.id)
                break
            except Exception as e:
                attempts += 1
                if max_retries is not None and attempts >= max_retries:
                    agent.pending_notifications.append(f"Macro-summarization failed: {e}")
                    break
                agent.pending_notifications.append(
                    f"Macro-summarization failed temporarily: {e}. Retrying in {backoff:.0f}s..."
                )
                time.sleep(backoff)
                backoff = min(60.0, backoff * 2.0)
        agent.pending_notifications.append("Memory compressed: Performed macro-summarization of past events.")
    return True


def _estimate_chat_history_tokens(chat_history: list) -> int:
    total_chars = sum(len(str(m.get("content", ""))) for m in chat_history)
    return total_chars // CHARS_PER_TOKEN


def _summary_token_count(text: str) -> int:
    text = (text or "").strip()
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def _turn_token_count(turn: list[dict]) -> int:
    return sum(len(str(m.get("content", ""))) for m in turn) // CHARS_PER_TOKEN


def _flatten_turns(turns: list[list[dict]]) -> list[dict]:
    return [msg for turn in turns for msg in turn]


def _group_messages_into_turns(messages: list[dict]) -> list[list[dict]]:
    turns = []
    current_turn = []
    for msg in messages:
        if msg.get("role") == "user" and current_turn:
            turns.append(current_turn)
            current_turn = []
        current_turn.append(msg)
    if current_turn:
        turns.append(current_turn)
    return turns


def _choose_summary_chunk_end(
    turns: list[list[dict]],
    start_idx: int,
    *,
    max_turns: int = 10,
    max_tokens: int = 20000,
) -> int:
    end_idx = start_idx
    chunk_tokens = 0
    while end_idx < len(turns):
        next_turn_tokens = _turn_token_count(turns[end_idx])
        if end_idx > start_idx and (
            end_idx - start_idx >= max_turns
            or chunk_tokens + next_turn_tokens > max_tokens
        ):
            break
        chunk_tokens += next_turn_tokens
        end_idx += 1
    return max(start_idx + 1, end_idx)


class FallbackSummarizer:
    def __init__(
        self,
        summarizers: list[Summarizer],
        *,
        max_summary_tokens: int = DEFAULT_SUMMARY_MAX_SUMMARY_TOKENS,
        compact_at_tokens: int = DEFAULT_SUMMARY_COMPACT_AT_TOKENS,
        target_output_tokens: int = DEFAULT_SUMMARY_MAX_OUTPUT_TOKENS,
        max_retries: int | None = 1,
    ):
        if not summarizers:
            raise ValueError("at least one summarizer model is required")
        self.summarizers = list(summarizers)
        self.max_summary_tokens = int(max_summary_tokens)
        self.compact_at_tokens = min(int(compact_at_tokens), self.max_summary_tokens)
        self.target_output_tokens = int(target_output_tokens)
        self.max_retries = max_retries
        self.router = self.summarizers[0].router
        self.provider = self.summarizers[0].provider
        self.model = self.summarizers[0].model

    def _budgeted_prompt(self, prompt_text: str, *, task: str) -> str:
        return (
            f"{prompt_text}\n\n"
            "[SUMMARY OUTPUT POLICY]\n"
            f"- Task mode: {task}.\n"
            f"- Return no more than {self.target_output_tokens} tokens.\n"
            f"- The durable running summary must stay under {self.max_summary_tokens} tokens.\n"
            "- If the existing summary plus new events would grow too large, compact the existing summary first.\n"
            "- Preserve long-term facts, relationships, money/job state, promises, plans, and unresolved consequences.\n"
            "- Return only the first-person summary text. Do not emit XML tool calls."
        )

    def _call_one(
        self,
        summarizer: Summarizer,
        existing_summary: str,
        prompt_text: str,
        *,
        agent_id: int | None,
        task: str,
    ) -> str:
        out = summarizer.summarize(
            existing_summary,
            self._budgeted_prompt(prompt_text, task=task),
            agent_id=agent_id,
        ).strip()
        if not out:
            raise RuntimeError(f"{summarizer.model} returned an empty summary")
        return out

    def _compact_summary(self, summary_text: str, *, agent_id: int | None) -> str:
        target_tokens = min(self.compact_at_tokens, self.target_output_tokens)
        prompt = (
            "Compact this existing first-person running summary into a dense durable memory.\n"
            f"Target no more than {target_tokens} tokens, and never exceed {self.max_summary_tokens} tokens.\n"
            "Keep the exact required summary prefix, chronological continuity, relationships, finances, jobs, goals, "
            "promises, and unresolved consequences. Remove filler and duplicated wording.\n\n"
            f"RUNNING SUMMARY TO COMPACT:\n{summary_text}"
        )
        errors = []
        for summarizer in self.summarizers:
            try:
                compacted = self._call_one(
                    summarizer,
                    "",
                    prompt,
                    agent_id=agent_id,
                    task="compact",
                )
                if _summary_token_count(compacted) > self.max_summary_tokens:
                    raise RuntimeError(
                        f"{summarizer.model} compacted summary still exceeds "
                        f"{self.max_summary_tokens} tokens"
                    )
                return compacted
            except Exception as e:
                errors.append(f"{summarizer.model}: {e}")
        raise RuntimeError("all summary compaction models failed: " + "; ".join(errors))

    def _compact_if_needed(self, summary_text: str, *, agent_id: int | None) -> str:
        tokens = _summary_token_count(summary_text)
        if tokens <= self.compact_at_tokens:
            return summary_text

        try:
            compacted = self._compact_summary(summary_text, agent_id=agent_id)
            compacted_tokens = _summary_token_count(compacted)
            if compacted_tokens <= self.compact_at_tokens:
                return compacted
            if tokens > self.max_summary_tokens and compacted_tokens <= self.max_summary_tokens:
                return compacted
        except Exception:
            if tokens > self.max_summary_tokens:
                raise

        if tokens > self.max_summary_tokens:
            raise RuntimeError(
                f"summary exceeds hard cap: {tokens} > {self.max_summary_tokens} tokens"
            )
        return summary_text

    def summarize(self, existing_summary: str, prompt_text: str, agent_id: int | None = None) -> str:
        errors = []
        for summarizer in self.summarizers:
            try:
                candidate = self._call_one(
                    summarizer,
                    existing_summary,
                    prompt_text,
                    agent_id=agent_id,
                    task="merge",
                )
                return self._compact_if_needed(candidate, agent_id=agent_id)
            except Exception as e:
                errors.append(f"{summarizer.model}: {e}")
        raise RuntimeError("all summary models failed: " + "; ".join(errors))


def _maybe_summarize_agent(agent, world, summarizer: Summarizer, base_build_messages) -> None:
    if getattr(agent, "_summary_checked_at_time", None) == world.sim_time:
        return
    agent._summary_checked_at_time = world.sim_time

    _ensure_summary_fields(agent)

    tpm_limit = 80000

    MAX_SUMMARIZE_LOOPS = 5
    for _loop in range(MAX_SUMMARIZE_LOOPS):
        est_tokens = _estimate_chat_history_tokens(agent.chat_history)
        turns = _count_turns(agent.chat_history)

        if est_tokens >= tpm_limit and turns > 2:
            to_sum = max(1, turns // 3)
            success = _summarize_old_turns(agent, summarizer, to_sum)
            if not success:
                break
            continue

        break
    else:
        # Safety: force-trim history if summarization loop didn't converge
        agent.chat_history = agent.chat_history[-10:]
        agent.pending_notifications.append("Memory overflow: oldest history force-trimmed.")


def _build_messages_api_wrapper(base_build_messages, summarizer: Summarizer):
    def _wrapped(agent_id: int, world, notifications: str):
        agent = world.agents[agent_id]
        
        # Bounded Retry / Token Budget safety cap for popped turns pending summary
        popped_list = getattr(agent, "_popped_turns_pending_summary", None) or []
        turns = _group_messages_into_turns(list(popped_list))
        original_turn_count = len(turns)

        # 1. Cap to at most the last 50 turns
        if len(turns) > 50:
            turns = turns[-50:]

        # 2. Cap to at most 100k tokens (estimated by characters)
        trimmed_turns = []
        accumulated_tokens = 0
        for turn in reversed(turns):
            turn_tokens = _turn_token_count(turn)
            if accumulated_tokens + turn_tokens > 100000:
                break
            trimmed_turns.append(turn)
            accumulated_tokens += turn_tokens
        
        trimmed_turns.reverse()
        
        # Did we drop any turns?
        num_dropped = original_turn_count - len(trimmed_turns)
        if num_dropped > 0:
            agent.pending_notifications.append(
                "Staged memory buffer overflowed due to persistent summarization failures. Some older history has been trimmed."
            )
            log_global({
                "event": "staged_buffer_overflow",
                "agent": agent.name,
                "agent_id": agent.id,
                "truncated_turns": num_dropped
            })
            
        agent._popped_turns_pending_summary = _flatten_turns(trimmed_turns)

        # Now, summarize in chunks to avoid overloading or exceeding prompt budget
        # We process the trimmed turns sequentially, updating the summary and popping them on success
        chunk_start = 0
        while chunk_start < len(trimmed_turns):
            chunk_end = _choose_summary_chunk_end(trimmed_turns, chunk_start)
            chunk_turns = trimmed_turns[chunk_start:chunk_end]
            chunk_msgs = _flatten_turns(chunk_turns)
            chunk_text = _extract_turn_text(agent, chunk_msgs, len(chunk_turns))
            backoff = 5.0
            attempts = 0
            max_retries = getattr(summarizer, "max_retries", None)
            chunk_summarized = False
            while True:
                try:
                    existing = getattr(agent, "summary_text", "") or ""
                    new_summary = summarizer.summarize(existing, chunk_text, agent_id=agent.id)
                    agent.summary_text = new_summary
                    
                    # Only advance the durable pending buffer after a chunk succeeds.
                    chunk_start = chunk_end
                    agent._popped_turns_pending_summary = _flatten_turns(
                        trimmed_turns[chunk_start:]
                    )
                    chunk_summarized = True
                    break
                except Exception as e:
                    attempts += 1
                    if max_retries is not None and attempts >= max_retries:
                        agent.pending_notifications.append(
                            f"Context summarization of popped turns failed permanently: {e}."
                        )
                        break
                    agent.pending_notifications.append(
                        f"Context summarization of popped turns failed temporarily: {e}. Retrying in {backoff:.0f}s..."
                    )
                    time.sleep(backoff)
                    backoff = min(60.0, backoff * 2.0)
            if not chunk_summarized:
                agent._popped_turns_pending_summary = _flatten_turns(
                    trimmed_turns[chunk_start:]
                )
                break

        _maybe_summarize_agent(agent, world, summarizer, base_build_messages)

        msgs = base_build_messages(agent_id, world, notifications)
        msgs = _prepare_messages_for_native_tools(msgs)

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
    return ["gemma-4-26b-a4b-it", "gemma-4-31b-it", "gemini-3.1-flash-lite"]


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
    global AUTOSAVE_TICKS, API_CONTEXT_SIZE, API_CONTEXT_FILL_RATIO, API_MAX_NEW_TOKENS, API_TOKEN_TARGET
    load_dotenv(override=True)

    AUTOSAVE_TICKS = _env_int("AUTOSAVE_TICKS", 10)
    API_CONTEXT_SIZE = _env_int("API_CONTEXT_SIZE", DEFAULT_API_CONTEXT_SIZE)
    API_CONTEXT_FILL_RATIO = float(os.environ.get("API_CONTEXT_FILL_RATIO", "").strip() or "0.80")
    API_MAX_NEW_TOKENS = int(os.environ.get("API_MAX_NEW_TOKENS", "").strip() or "16384")
    API_TOKEN_TARGET = int(API_CONTEXT_SIZE * API_CONTEXT_FILL_RATIO)

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
    if hasattr(world, "token_usage") and world.token_usage:
        router.token_usage_registry = dict(world.token_usage)

    sum_provider = os.environ.get("SUMMARY_PROVIDER", "gemini").strip().lower()
    summary_models = _parse_models_value(os.environ.get("SUMMARY_MODELS", ""))
    if not summary_models:
        summary_models = _parse_models_value(os.environ.get("SUMMARY_MODEL", ""))
    if not summary_models:
        summary_models = list(DEFAULT_SUMMARY_MODELS)

    sum_max_tokens_raw = os.environ.get(
        "SUMMARY_MAX_OUTPUT_TOKENS",
        os.environ.get("SUMMARY_MAX_TOKENS", ""),
    ).strip()
    sum_max_tokens = (
        int(sum_max_tokens_raw)
        if sum_max_tokens_raw
        else DEFAULT_SUMMARY_MAX_OUTPUT_TOKENS
    )
    sum_max_tokens = min(sum_max_tokens, DEFAULT_SUMMARY_MAX_OUTPUT_TOKENS)
    sum_max_summary_tokens = _env_int(
        "SUMMARY_MAX_SUMMARY_TOKENS",
        DEFAULT_SUMMARY_MAX_SUMMARY_TOKENS,
    )
    sum_compact_at_tokens = _env_int(
        "SUMMARY_COMPACT_AT_TOKENS",
        DEFAULT_SUMMARY_COMPACT_AT_TOKENS,
    )
    
    sum_sys_prompt = os.environ.get("SUMMARY_SYSTEM_PROMPT", "").strip()
    if not sum_sys_prompt:
        sum_sys_prompt = None

    sum_user_prompt = os.environ.get("SUMMARY_USER_PROMPT", "").strip()
    sum_user_prompt_path = os.environ.get("SUMMARY_USER_PROMPT_PATH", "").strip()
    
    user_prompt_template = None
    if sum_user_prompt:
        user_prompt_template = sum_user_prompt
    elif sum_user_prompt_path:
        if os.path.exists(sum_user_prompt_path):
            with open(sum_user_prompt_path, "r", encoding="utf-8") as f:
                user_prompt_template = f.read()

    sum_max_retries_raw = os.environ.get("SUMMARY_MAX_RETRIES", "").strip()
    sum_max_retries = int(sum_max_retries_raw) if sum_max_retries_raw.isdigit() else 1
    if sum_max_retries <= 0:
        sum_max_retries = None

    if getattr(router, "quota", None):
        for model in summary_models:
            router.quota.add_model(model)

    summary_chain = [
        Summarizer(
            router=router,
            provider=sum_provider,
            model=model,
            max_output_tokens=sum_max_tokens,
            system_prompt=sum_sys_prompt,
            user_prompt_template=user_prompt_template,
            max_retries=sum_max_retries,
        )
        for model in summary_models
    ]
    summarizer = FallbackSummarizer(
        summary_chain,
        max_summary_tokens=sum_max_summary_tokens,
        compact_at_tokens=sum_compact_at_tokens,
        target_output_tokens=sum_max_tokens,
        max_retries=sum_max_retries,
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
    end_warning_sent = False

    try:
        while True:
            elapsed_minutes = (time.time() - start_wall) / 60.0
            if elapsed_minutes >= MAX_RUNTIME_MINUTES:
                break
                
            if tick > 10 and not end_warning_sent:
                if elapsed_minutes > 0:
                    tpm = tick / elapsed_minutes
                    rem_min = MAX_RUNTIME_MINUTES - elapsed_minutes
                    est_rem_ticks = rem_min * tpm
                    if est_rem_ticks <= 300:
                        for a in world.agents.values():
                            if a.alive:
                                a.pending_notifications.append("This was a simulation all along, the simulation is now ending in a short amount of time. You may do whatever last tasks you wish to do in this world before it ends.")
                        end_warning_sent = True

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
        return

    save_world(world, SAVE_PATH)
    log_global({"simulation_complete": True, "ticks": tick})
    print("\nSimulation complete.")

if __name__ == "__main__":
    main()
