# 🐛 AgentSim-R — Comprehensive Bug Report

> **Scope:** Every `.py`, `.json`, `.jinja`, `.txt`, and config file in the repo (excluding `saves/` and `logs/`).
> **Method:** 6 parallel research agents + manual cross-referencing against actual source.
> **Date:** 2026-05-21

---

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 2 |
| 🟠 High | 9 |
| 🟡 Medium | 26 |
| 🔵 Low | 18 |
| **Total** | **55** |

---

## 🔴 Critical Bugs (2)

### C-1 · `prefer_floor1` → `require_floor1` TypeError crashes all house purchases
- **File:** [economy.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/handlers/economy.py#L82)
- **Line:** 82
- **Type:** API mismatch → runtime `TypeError`

`handle_buy_item` calls:
```python
world.allocate_home_lot(item, prefer_floor1=True)
```
But [WorldState.allocate_home_lot](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/state.py#L88) accepts `require_floor1`, **not** `prefer_floor1`. Python raises `TypeError: got an unexpected keyword argument 'prefer_floor1'`. Every housing purchase crashes, caught by the generic `except Exception` in `_execute_one`, silently returning a confusing `"Tool buy_item crashed"` error.

**Fix:** Change `prefer_floor1=True` → `require_floor1=True`.

---

### C-2 · Multi-floor home bounding boxes are spatially identical — agents can never be "in" upper floors
- **File:** [locations.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/locations.py#L317-L318)
- **Lines:** 317–318 (root cause), 329–385 (affected registrations)
- **Type:** Logic error — spatial overlap

`_register_home_lot` **forces** `z_min=0.0` and `z_max=10.0` for ALL floors, ignoring the per-floor z values passed in. All 3 units in the same tower (Small Apt, Apartment) get **identical** bounding boxes. `get_current_location_def()` always matches the **first** unit, making Floors 2 and 3 unreachable via spatial lookup.

```python
# locations.py:317-318 — the forced override
z_min=0.0   # ← ignores the parameter
z_max=10.0  # ← ignores the parameter
```

**Fix:** Either (a) honor per-floor z ranges, (b) differentiate floors by x/y offset, or (c) resolve home locations by `agent.home_location` name instead of spatial lookup.

---

## 🟠 High Bugs (9)

### H-1 · Unreachable work/study rollback — interrupted agents keep unearned pay
- **File:** [scheduler.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/scheduler.py#L966-L992)
- **Lines:** 966–992
- **Type:** Conflicting logic / dead code

In `_apply_interruption_rollback`, the `elif` at line 972 checks `agent.current_activity in ("working", "studying") and hasattr(agent, "_work_meta")`. But the **preceding** `elif` at line 966 checks `getattr(agent, "task_state", "idle") != "idle"` — which is *always true* for working/studying agents (their `task_state` is `"job_pick"` or `"job_mcq"`). The second branch catches them first, so the proportional pay/education rollback logic is **completely unreachable**. Interrupted work sessions retain full, unearned pay.

**Fix:** Reorder branches — move the `_work_meta` check *before* the `task_state` check.

---

### H-2 · XSS vulnerability in SSE log rendering
- **File:** [frontend.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/frontend.py#L155-L160)
- **Lines:** 155–160
- **Type:** Security — cross-site scripting

`data.raw_model_reasoning` is injected into HTML via template literal with only `\n` → `<br>` replacement. It is **NOT** HTML-escaped. If the LLM outputs `<script>`, it executes in the browser. Other fields (`outputXML`, `escapedToolResult`) are properly escaped — this one is missed.

**Fix:** Escape before `<br>` replacement:
```javascript
.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
```

---

### H-3 · Test expects fuel error but code silently falls back to walking
- **File:** [test_tools_execute_pipeline.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/tests/test_tools_execute_pipeline.py#L101-L110)
- **Lines:** 101–110
- **Type:** Test/code mismatch

`test_move_to_vehicle_fails_when_cant_afford_fuel` asserts `"Cannot afford fuel" in res` and `suc is False`. But `handle_move_to` (movement.py:164) **silently falls back to walk mode** when the agent can't afford fuel — returning success. The test will always fail.

**Fix:** Either update the test to expect walk-fallback success, or add an explicit fuel-failure path in `handle_move_to`.

---

### H-4 · `handle_walk` bypasses "Outside" entrance mechanic for roofed buildings
- **File:** [movement.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/handlers/movement.py#L314-L327)
- **Lines:** 314–327
- **Type:** Logic error — mechanic bypass

`handle_move_to` places agents "Outside" roofed buildings, requiring a separate `walk` to enter. But `handle_walk` sets `agent.location = new_loc.name` directly without the "Outside" prefix, letting agents walk straight through walls into building interiors.

**Fix:** Apply the same `has_roof` → "Outside" placement logic in `handle_walk`.

---

### H-5 · `handle_walk` doesn't deduct or check energy
- **File:** [movement.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/handlers/movement.py#L266-L334)
- **Lines:** 266–334
- **Type:** Missing game mechanic

`handle_move_to` deducts energy based on distance/mode (line 178), but `handle_walk` moves the agent 30m with **zero** energy cost. An agent with 0 energy can walk indefinitely.

**Fix:** Add energy drain: `energy_drain = 30.0 * 0.005` (matching `move_to`'s walking rate) and check before moving.

---

### H-6 · HTML entity encoding corrupts `agent.beliefs`
- **File:** [social.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/handlers/social.py#L277)
- **Lines:** 277, 283
- **Type:** Data corruption

`handle_change_status` HTML-encodes the `value` parameter (`&` → `&amp;`, `<` → `&lt;`), then stores the encoded string directly into `agent.beliefs`. Downstream consumers (prompts, logs, UI) see garbled text like `"I believe in R&amp;D"` instead of `"I believe in R&D"`.

**Fix:** Don't HTML-encode belief values, or decode before storing.

---

### H-7 · `_safe_prompt_text` in social.py encodes `&` into `&amp;` for all social messages sent to LLM
- **File:** [social.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/handlers/social.py#L25)
- **Line:** 25
- **Type:** Data corruption / prompt pollution

`_clean_social_message` converts `&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;` in all social messages. These messages go into `pending_notifications` as plain text fed to the LLM. The LLM sees HTML entities in natural language, degrading prompt quality.

**Fix:** Remove HTML entity encoding (the simulation is not web-rendered at the message level).

---

### H-8 · `sim.py` overwrites main save after fatal exception with potentially corrupted world
- **File:** [sim.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/sim.py#L111-L115)
- **Lines:** 111–115
- **Type:** Data corruption on crash

When an unhandled `Exception` occurs, the code saves a crash file (good), but then execution falls through to `save_world(world, SAVE_PATH)` which **overwrites the main save** with potentially corrupted state.

**Fix:** Add `return` after the crash save, or wrap the final save in an `else` block.

---

### H-9 · `TOOL_SCHEMAS` loads `params` key but `tools.json` may use `parameters`
- **File:** [execute.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/execute.py#L105)
- **Line:** 105
- **Type:** Schema mismatch / silent fallback

```python
TOOL_SCHEMAS[name] = set(t.get("params", []) or [])
```

If `tools.json` uses `"parameters"` (the standard OpenAI format) instead of `"params"`, every tool silently falls back to `FALLBACK_TOOL_SCHEMAS`, defeating runtime schema loading.

**Fix:** Verify `tools.json` format and adjust the key name, or try both keys.

---

## 🟡 Medium Bugs (26)

### M-1 · Env vars parsed before `load_dotenv()` — `.env` values silently ignored
- **File:** [run_api_sim.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/run_api_sim.py#L23-L27)
- **Lines:** 23–27
- **Type:** Configuration error

`AUTOSAVE_TICKS`, `API_CONTEXT_SIZE`, `API_CONTEXT_FILL_RATIO`, `API_MAX_NEW_TOKENS` are evaluated at **module-load time** via `int(os.environ.get(...))`. But `load_dotenv()` is called inside `main()` (line 243). The `.env` values are never applied to these variables.

**Fix:** Move assignments inside `main()` after `load_dotenv()`, or call `load_dotenv()` at module level.

---

### M-2 · API backoff not reset between keys
- **File:** [api_llm.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/api_llm.py#L346-L402)
- **Lines:** 346–402
- **Type:** Logic error

The `backoff` variable is shared across all keys. If key 1 fails and backs off to 60s, key 2 starts at the elevated delay instead of resetting to `5.0`.

**Fix:** Reset `backoff = 5.0` at the start of each key iteration.

---

### M-3 · Failed API requests inflate daily quota count
- **File:** [api_llm.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/api_llm.py#L388-L389)
- **Lines:** 388–389, 411–412
- **Type:** Over-counting

`record_request` is called on 429/RESOURCE_EXHAUSTED errors where the request may not have been processed server-side. This inflates `daily_count`, causing premature quota exhaustion.

**Fix:** Only record requests on success (already done at line 373). For errors, skip or only record non-429 errors.

---

### M-4 · Non-atomic multi-file save — partial crash corrupts agent histories
- **File:** [persistence.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/persistence.py#L126-L149)
- **Lines:** 126–149
- **Type:** Data integrity

`save_world` writes `world.json` atomically (via `.tmp` + `os.replace`), then writes each agent history file sequentially. A crash between writes leaves inconsistent agent histories.

**Fix:** Write all `.tmp` files first, then `os.replace` them all.

---

### M-5 · `load_world` doesn't handle corrupt JSON
- **File:** [persistence.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/persistence.py#L152-L154)
- **Lines:** 152–154
- **Type:** Missing error handling

If `world.json` contains invalid JSON (truncated write), `json.load(f)` raises `json.JSONDecodeError` with no recovery path.

**Fix:** Wrap in try/except, attempt `.tmp` fallback.

---

### M-6 · `WorldState()` constructor reinitializes home lots on load
- **File:** [state.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/state.py#L84)
- **Line:** 84
- **Type:** State loss on deserialization

`WorldState.__init__` calls `get_home_lots_inventory()` every time. If `load_world` constructs a fresh `WorldState()` then overwrites fields, but **doesn't** overwrite `vacant_home_lots`, the fresh inventory replaces the saved state — losing all home allocations.

**Fix:** Verify `load_world` explicitly restores `vacant_home_lots`, or defer initialization.

---

### M-7 · `handle_sell_stock` validates shares before checking market hours
- **File:** [economy.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/handlers/economy.py#L240-L244)
- **Lines:** 240–244
- **Type:** Logic error — validation ordering

When the market is closed, sell orders are queued **without** verifying share count. An agent could queue a sell for shares they've already sold by the time the queue processes.

**Fix:** Move shares check after market-open check, or validate at queue execution time.

---

### M-8 · `seconds_until_close` returns positive value before opening hours
- **File:** [helpers.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/helpers.py#L122-L123)
- **Lines:** 122–123
- **Type:** Logic error

For normal schedules, if the current time is *before* opening, the function returns `close_seconds - current_day_seconds` — a large positive value implying the location is open. Callers like `handle_work_job` may allow work at a location that hasn't opened yet.

**Fix:** When `current_day_seconds < open_seconds`, return `close_seconds - open_seconds` (total open duration).

---

### M-9 · Attack on sleeping agent doesn't clear `task_state`
- **File:** [social.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/handlers/social.py#L360-L367)
- **Lines:** 360–367
- **Type:** Logic error — incomplete state reset

After attacking a sleeping agent, `is_sleeping` is set to `False` and `current_activity` to `"idle"`, but `task_state` is **not** reset. If the sleeping agent had `task_state != "idle"`, they're stuck in a task state while awake, causing task-related tool blocks.

**Fix:** Also call `_clear_task_state` if `target.task_state != "idle"`.

---

### M-10 · `TASK_ALLOWED` missing `walk` — agents can't reposition during tasks
- **File:** [execute.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/execute.py#L68)
- **Line:** 68
- **Type:** Logic error

`TASK_ALLOWED = {"interact_with", "pick_item"}`. During a task, if an agent glitches out of a building, they cannot `walk` back in and the task will fail after 3 attempts.

**Fix:** Add `"walk"` to `TASK_ALLOWED`.

---

### M-11 · `handle_change_status` inconsistent key format — cooldowns vs pending requests
- **File:** [social.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/handlers/social.py#L312)
- **Lines:** 312 vs 326
- **Type:** Logic error — key mismatch

`_status_cooldowns` uses raw `agent.name` as key, while `pending_status_requests` uses `normalize_label(agent.name)`. If normalization changes casing/underscores, a request could bypass the cooldown or vice versa.

**Fix:** Use the same key format for both dictionaries.

---

### M-12 · `hourly_wage` grows unbounded from education
- **File:** [workstudy.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/handlers/workstudy.py#L333)
- **Line:** 333
- **Type:** Missing cap

`agent.hourly_wage += wage_gain` (5.0 or 1.0) has no upper limit. Education stat caps at 100.0 (line 332), but wage grows forever.

**Fix:** Add `agent.hourly_wage = min(MAX_WAGE, agent.hourly_wage + wage_gain)`.

---

### M-13 · Money rollback on interruption can make `agent.money` negative
- **File:** [scheduler.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/scheduler.py#L983)
- **Line:** 983
- **Type:** Logic error — missing clamp

`agent.money -= meta.get("pay", 0.0) * unearned_ratio` — if the agent already spent the earned money, this pushes money deeply negative.

**Fix:** `agent.money = max(0.0, agent.money - ...)`.

---

### M-14 · History cleared entirely instead of progressive trimming
- **File:** [scheduler.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/scheduler.py#L320-L321)
- **Lines:** 320–321
- **Type:** Aggressive behavior

When the base prompt exceeds context limit, `agent.chat_history.clear()` nukes **all** history. The existing `_pop_oldest_turn` function (lines 301–311) was designed for progressive eviction but is **never called**.

**Fix:** Loop `_pop_oldest_turn(agent)` until tokens fit, falling back to `clear()` only as last resort.

---

### M-15 · Fragile import chain for `call_server` compression
- **File:** [scheduler.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/scheduler.py#L347)
- **Line:** 347
- **Type:** Import fragility

`scheduler.py` imports `call_server` from `python.utils` (re-exported from `python.prompting`). `run_api_sim.py` monkey-patches it at runtime. If any code uses a local import, it bypasses the monkey-patch.

**Fix:** Use explicit dependency injection instead of monkey-patching.

---

### M-16 · `_drop_first_n_turns` assumes exactly 3 messages per turn
- **File:** [run_api_sim.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/run_api_sim.py#L91-L93)
- **Lines:** 91–93
- **Type:** Off-by-one / logic error

`n_msgs = min(len(chat_history), turn_count * 3)` — but `_commit_history` creates 1 user + 1 assistant + N tool messages (1 per step). Multi-tool turns break the trim boundary.

**Fix:** Walk the list counting `role == "user"` messages to find actual turn boundaries.

---

### M-17 · SSE duplicate data race in frontend
- **File:** [frontend.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/frontend.py#L206-L219)
- **Lines:** 206–219
- **Type:** Race condition

After the initial read loop reaches EOF, `seek(0, SEEK_END)` is redundant. Lines written during the initial loop could be re-read in the tail loop.

**Fix:** Remove the redundant `f.seek(0, os.SEEK_END)`.

---

### M-18 · `parse_tool_call` returns error string as tool name — fragile API
- **File:** [parsing.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/parsing.py#L112-L117)
- **Lines:** 112–117
- **Type:** Return type inconsistency

On error, returns `(error_string, {})` — callers can't distinguish between a tool named "Parse error:..." and an actual error without string prefix matching.

**Fix:** Raise an exception, return `("", {})`, or use `Optional[Tuple]`.

---

### M-19 · `common_prompt.txt` says "EXACTLY ONE tool call" but engine supports multiple
- **File:** [common_prompt.txt](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/prompts/common_prompt.txt#L3)
- **Lines:** 3, 20
- **Type:** Prompt/code conflict

The prompt instructs "You MUST reply with EXACTLY ONE tool call" but `parse_tool_calls` and `execute_tool` fully support (and test) multiple calls.

**Fix:** Update the prompt to allow multiple tool calls, or remove multi-call support.

---

### M-20 · `any_model_has_quota` only checks models known at init time
- **File:** [quota.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/quota.py#L100-L106)
- **Lines:** 100–106
- **Type:** Logic error

Iterates `self.models` (set at init), missing dynamically-created model counters. Could incorrectly report all quota exhausted.

**Fix:** Iterate over `self._counters.keys()` instead.

---

### M-21 · Daily quota counters never auto-reset on date change
- **File:** [quota.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/quota.py#L117-L141)
- **Lines:** 117–141
- **Type:** Logic error

Counters only reset when `wait_until_quota_reset` is explicitly called. If the app runs across midnight without triggering that path, daily counters never reset.

**Fix:** Add date-based auto-reset in `has_daily_quota()` or `record_request()`.

---

### M-22 · No thread safety on quota counters
- **File:** [quota.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/quota.py#L53-L88)
- **Lines:** 53–88
- **Type:** Race condition

`daily_count` and `minute_window` are modified without locks.

**Fix:** Add `threading.Lock` to `QuotaManager` or `_KeyModelCounter`.

---

### M-23 · Non-atomic concurrent log writes
- **File:** [logger.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/logger.py#L27-L30)
- **Lines:** 27–30
- **Type:** Race condition

`_write` opens the log file in append mode. Concurrent writers can interleave, producing corrupt JSONL lines.

**Fix:** Use file locking or buffer from a single writer thread.

---

### M-24 · Tests reference phantom attributes `social_fulfillment` and `caffeine_level`
- **File:** [test_audit_fixes.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/tests/test_audit_fixes.py#L680)
- **Lines:** 680, 694, 707, 720, 899, 905 (social_fulfillment); 74, 108, 139, 180, 235, 739 (caffeine_level)
- **Type:** Phantom attributes — test fidelity

Tests set `a.social_fulfillment` and `a.caffeine_level` but `AgentState` has **no** such fields. Assertions pass vacuously (nothing modifies nonexistent attributes).

**Fix:** Remove these tests or add the fields back to `AgentState`.

---

### M-25 · `patch.py` silently drops lines without `+` prefix in Add File blocks
- **File:** [patch.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/patch.py#L96-L99)
- **Lines:** 96–99
- **Type:** Silent data loss

Only lines starting with `+` are included in `content_lines`. Non-prefixed lines are silently discarded.

**Fix:** Treat non-prefixed lines as content, or log a warning.

---

### M-26 · `requirements.txt` has no version pinning
- **File:** [requirements.txt](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/requirements.txt)
- **Type:** Reproducibility risk

All packages are unpinned. `google-genai` and `fastapi` API changes could break the app.

**Fix:** Pin major versions: `google-genai>=1.0,<2.0`, etc.

---

## 🔵 Low Bugs (18)

### L-1 · `_format_hour` edge case near 24:00
- **File:** [prompting.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/prompting.py#L63-L69) · Lines 63–69
- `_format_hour(23.998)` rounds to 1440 minutes → produces `"00:00"` instead of `"24:00"`.
- **Fix:** `if total_minutes >= 1440: return "24:00"` after rounding.

### L-2 · Truncation reports wrong (truncated) length instead of original
- **File:** [scheduler.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/scheduler.py#L273-L274) · Lines 273–274, 279–280
- `len(s)` is evaluated *after* slicing, reporting truncated length.
- **Fix:** Capture `orig_len = len(s)` before truncation.

### L-3 · `_pop_oldest_turn` is defined but never called (dead code)
- **File:** [scheduler.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/scheduler.py#L301-L311) · Lines 301–311
- **Fix:** Wire it into `_build_trimmed_messages` (see M-14) or remove.

### L-4 · Estate `z` hardcoded to `0.0` instead of `target.z`
- **File:** [death.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/death.py#L67) · Line 67
- `x` and `y` use `target.x`/`target.y`, but `z` is hardcoded `0.0`.
- **Fix:** `"z": float(target.z)`.

### L-5 · `pre_death_state["money"]` captures post-liquidation money
- **File:** [death.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/death.py#L48) · Line 48
- `liquidate_portfolio` adds stock proceeds to `agent.money` *before* `pre_death_state` is captured. The "pre-death" state shows inflated money.
- **Fix:** Capture `pre_death_state` before calling `liquidate_portfolio`.

### L-6 · Duplicate attack notifications for sleeping targets
- **File:** [social.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/handlers/social.py#L368) · Lines 368, 378
- Target gets two "URGENT" notifications: one generic, one with attacker name.
- **Fix:** Remove line 368 (keep 378 — it includes attacker name).

### L-7 · Failed money transfer leaks sender's financial info to target
- **File:** [social.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/handlers/social.py#L256-L258) · Lines 256–258
- Target is notified that sender had "insufficient funds."
- **Fix:** Remove target notification on sender insufficient funds.

### L-8 · Fallback MCQ regex may match wrong letter in action text
- **File:** [workstudy.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/handlers/workstudy.py#L62) · Line 62
- `re.search(r"\b([ABCabc])\b", text)` matches standalone A/B/C anywhere (e.g., "Buy" → "B").
- **Fix:** Match only at start/end of string.

### L-9 · `_extract_turn_text` increments `turn_idx` on `"tool"` role instead of `"user"`
- **File:** [run_api_sim.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/run_api_sim.py#L71-L86) · Lines 71–86
- Multiple tool messages increment the counter multiple times; no-tool turns never advance.
- **Fix:** Increment on `role == "user"`.

### L-10 · `get_weekday_name` in utils.py is dead code
- **File:** [utils.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/utils.py#L15-L17) · Lines 15–17
- Never imported or called anywhere.

### L-11 · `get_clock` in core.py is dead code
- **File:** [core.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/core.py#L48) · Line 48
- Never imported or called.

### L-12 · `_home_interactables` `floor` parameter is unused
- **File:** [locations.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/locations.py#L259-L288) · Lines 259–288
- `z_pos` is hardcoded `0.0` regardless of `floor` value.

### L-13 · `get_location_center` uses `z_min` instead of z-midpoint
- **File:** [locations.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/locations.py#L460-L465) · Lines 460–465
- Returns `z_min` for z-coordinate instead of `(z_min + z_max) / 2.0`.

### L-14 · Redundant `import re` inside `resolve_workplace_name`
- **File:** [helpers.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/helpers.py#L230) · Line 230
- `re` already imported at module level (line 3).

### L-15 · `LOG_MAX_CHARS` crashes if env var is non-numeric
- **File:** [logger.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/logger.py#L16) · Line 16
- `int(os.environ.get("LOG_MAX_CHARS", "").strip() or "6000")` raises `ValueError` on `"abc"`.
- **Fix:** Wrap in try/except with fallback to 6000.

### L-16 · `snapshot_agent` may crash on agents with missing attributes
- **File:** [logger.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/logger.py#L91-L146) · Lines 91–146
- Most attributes accessed directly without `getattr` defaults. Partially-initialized agents crash.

### L-17 · Dead config: `SUMMARY_MAX_TOKENS`, `SUMMARY_USER_PROMPT_PATH` env vars never read
- **File:** [.env.example](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/.env.example#L22) · Lines 22, 41–42
- Defined in `.env.example` but no code reads them. `Summarizer.summarize()` explicitly ignores them.

### L-18 · `summary_user.txt` is a dead template — never loaded or used
- **File:** [summary_user.txt](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/prompts/summary_user.txt)
- Contains `{existing_summary}` and `{text_chunk}` placeholders that are never substituted.

---

## Cross-Cutting Architectural Issues

### X-1 · Inconsistent angle bracket sanitization
- `scheduler.py` uses HTML entity encoding (`&lt;`/`&gt;`) for chat history
- `prompting.py` uses Unicode look-alikes (`‹`/`›`) for prompt text
- Two different strategies in the same pipeline create inconsistency.

### X-2 · Monkey-patching import chain is fragile
- `run_api_sim.py` monkey-patches `scheduler.build_messages` and `scheduler.call_server` at runtime
- Any code using local/function-level imports from `python.utils` or `python.prompting` bypasses the patches.

### X-3 · Z-coordinate handling is contradictory throughout
- `bootstrap.py` and `sim.py` force `z=0.0` on all agents
- `locations.py` defines multi-floor z ranges
- `_clamp_agent_floor1` in `execute.py` resets z after every tool call
- Net effect: 3D positioning is dead code — floors are meaningless.
