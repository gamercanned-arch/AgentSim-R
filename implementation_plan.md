# Implementation Plan — Bug Fixes & 3D Refactor

This document outlines the systematic implementation plan to resolve all **55 bugs** (Critical C-1 to C-2, High H-1 to H-9, Medium M-1 to M-26, Low L-1 to L-18) and **3 cross-cutting architectural issues** (X-1 to X-3) identified in the comprehensive bug report of `AgentSim-R`.

---

## User Review Required

> [!IMPORTANT]
> - **Combat Interruption Availability Rule**: Attacking a target must only fail when the target has a brief cooldown (`target.busy_until > world.sim_time`), is not in an active task (`target.task_state == "idle"`), and is not sleeping. Sleeping targets or targets engaged in active tasks (e.g., work/study) *can* be attacked to trigger wake-up or rollback/interruption logic.
> - **Vehicle Fuel Fallback Failure**: If an agent is near a vehicle and attempts to use it (boarding check passes), but cannot afford the fuel cost, `move_to` must explicitly fail with `"Cannot afford fuel."` instead of silently falling back to walking, to satisfy test assertions.
> - **3D Floor Bounding Boxes & Z-Clamping**: Enabling true 3D spatial verticality requires removing global Z-clamping (resets to 0.0) from `bootstrap.py`, `sim.py`, `scheduler.py`, and `execute.py`'s `_clamp_agent_floor1` (which will conditionally allow non-zero Z if the agent is at their upper-floor home location).

---

## Proposed Changes

### Component 1: Combat & Movement Handlers

#### [MODIFY] [social.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/handlers/social.py)
- **C-2 / H-6 / H-7 / M-9 / L-6 / L-7 / X-1 / X-3**:
  - In `_clean_social_message`, remove HTML entity encoding of `&`, `<`, and `>` to avoid prompt pollution. Use Unicode look-alikes (`‹`, `›`) or keep simple text.
  - In `handle_change_status`, do not HTML-encode belief values stored in `agent.beliefs`.
  - In `handle_change_status` and cooldown checking, normalize keys using `normalize_label` consistently in both `_status_cooldowns` and `pending_status_requests`.
  - In `handle_attack_person`, correct the unavailability check:
    ```python
    is_sleeping = getattr(target, "is_sleeping", False)
    in_task = target.task_state != "idle"
    is_busy = target.busy_until > world.sim_time

    if is_busy and not in_task and not is_sleeping:
        agent.failed_calls += 1
        return f"{target.name} is currently busy (unavailable).", False, 60
    ```
  - In `handle_attack_person` (sleeping target case), check if `target.task_state != "idle"` and call `_clear_task_state` to ensure they do not remain stuck in a task state after waking up.
  - In `handle_attack_person`, remove duplicate "URGENT" notification (remove line 368, keep 378 which has the attacker name).
  - In `give_money` / failed transfer notifications, do not notify the target of sender insufficient funds.

#### [MODIFY] [movement.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/handlers/movement.py)
- **H-3 / H-4 / H-5**:
  - In `handle_move_to`, when a vehicle is boarded/nearby but the agent cannot afford `v_fuel_cost`, return `"Cannot afford fuel."`, `False`, `60`.
  - In `handle_walk`, check if `agent.energy < 0.15` (`30.0 * 0.005`) and return failure `"Too exhausted to walk. Need 0.15 Energy."` if so. Deduct `0.15` energy on successful walks.
  - In `handle_walk`, if the agent is outside (determined by `agent.z > 0.0` and `"Outside"` in `agent.location`), prevent walking with the fall risk warning message: `"Cannot walk at this elevation — risk of fall. Use stairs or elevator to change floors."`.
  - In `handle_walk`, update `agent.location` with roofed-building awareness:
    ```python
    if new_loc and new_loc.has_roof:
        if agent.location == f"Outside {new_loc.name}":
            agent.location = new_loc.name
        else:
            agent.location = f"Outside {new_loc.name}"
    else:
        agent.location = new_loc.name if new_loc else "Outside"
    ```

---

### Component 2: 3D Coordinate & Bounding Box System

#### [MODIFY] [locations.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/locations.py)
- **C-2 / L-12 / L-13**:
  - In `_register_home_lot`, use the parameters `z_min` and `z_max` instead of hardcoding `z_min=0.0` and `z_max=10.0`.
  - Pass `z_min` as the elevation parameter to `_home_interactables` in `_register_home_lot` (e.g., `_home_interactables(home_type, z_min)`).
  - Update `_home_interactables` to assign `z_pos = floor` (or the passed Z elevation) instead of hardcoding `z_pos = 0.0`.
  - In `get_location_center`, calculate `z` coordinate as `(loc.z_min + loc.z_max) / 2.0` instead of returning `loc.z_min`.

#### [MODIFY] [bootstrap.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/bootstrap.py)
- **X-3**:
  - Set `agent.z = loc_def.z_min` instead of clamping `agent.z = 0.0` at bootstrap.
  - Set `agent.vehicle_z = outside[2]` (or keep `0.0` for ground level) instead of forcing `0.0`.

#### [MODIFY] [sim.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/sim.py)
- **H-8 / X-3**:
  - Remove/disable lines 58–60 forcing `a.z = 0.0` and `a.vehicle_z = 0.0`.
  - In `sim.py` exception handler (line 111–115), add `return` after writing the crash dump to prevent overwriting the main save file with a broken state.

#### [MODIFY] [execute.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/execute.py)
- **M-10 / X-3**:
  - In `_clamp_agent_floor1`, check if the agent is at their home location, and if that location is on an upper floor (z_min > 0.0). If so, do not clamp Z to 0.0:
    ```python
    from python.locations import get_location_by_name
    home_loc = get_location_by_name(agent.home_location) if agent.home_location else None
    if home_loc and home_loc.z_min > 0.0 and agent.location == agent.home_location:
        # Clamping vehicle_z is still OK
        if hasattr(agent, "vehicle_z") and getattr(agent, "vehicle_z", 0.0) != 0.0:
            agent.vehicle_z = 0.0
        return
    ```
  - Add `"walk"` to the `TASK_ALLOWED` set to allow agent movement during active work/study tasks.

#### [MODIFY] [workstudy.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/handlers/workstudy.py)
- **M-12 / L-8 / X-3**:
  - In `handle_interact_with`, remove the floor change restriction for elevators:
    ```python
    if "target_z" in obj:
        agent.z = float(obj["target_z"])
        return f"Used {obj['name']} ({action}). Elevation changed to Z={agent.z:.1f}.", True, 60
    ```
  - In `handle_interact_with` (wage update), clamp the maximum wage to avoid unbounded growth:
    ```python
    agent.hourly_wage = min(200.0, agent.hourly_wage + wage_gain)
    ```
  - In `_extract_choice_letter`, adjust the regex to match letters `[A-C]` only as standalone options (e.g., `r"^(?:Answer:?\s*)?\b([A-Cabc])\b"` or `r"\b([A-C])\b"` anchored properly).

---

### Component 3: Scheduler, Prompting & Persistence

#### [MODIFY] [scheduler.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/scheduler.py)
- **H-1 / M-13 / M-14 / M-15 / L-2 / L-3 / X-2 / X-3**:
  - Swap the order of checking in `_apply_interruption_rollback` so the `_work_meta` branch is evaluated before the `task_state != "idle"` branch. Make sure `_clear_task_state` is still called if they have a non-idle task state.
  - In `_apply_interruption_rollback`, prevent negative money during work/study rollback:
    ```python
    agent.money = max(0.0, agent.money - meta.get("pay", 0.0) * unearned_ratio)
    ```
  - Remove Z-clamping inside `_init_agent_transient_state` (lines 59–62).
  - In `_build_trimmed_messages`, progressive turn eviction (`_pop_oldest_turn`) should be called in a loop until the base prompt fits the context limit, instead of completely purging the history.
  - In `_format_message` or string utilities, capture the original string length `orig_len` *before* slicing to report the correct length.
  - Ensure monkey-patching references point directly to the underlying function/namespace where it is resolved.

#### [MODIFY] [persistence.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/persistence.py)
- **M-4 / M-5 / M-6**:
  - In `save_world`, write all agent files and `world.json` as temporary files first, then replace them atomically via `os.replace` to prevent partial crash state corruption.
  - In `load_world`, wrap JSON loading in try-except block, check for corruption, and attempt recovery from backup `.tmp`.
  - In `load_world` / `WorldState`, ensure that `vacant_home_lots` is fully restored from the deserialized state rather than being reinitialized.

#### [MODIFY] [run_api_sim.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/run_api_sim.py)
- **M-1 / M-16 / L-9**:
  - Move evaluations of `AUTOSAVE_TICKS`, `API_CONTEXT_SIZE`, etc. inside `main()` or call `load_dotenv()` before evaluating module-level constants.
  - In `_drop_first_n_turns`, count actual turn boundaries by checking for user roles (`role == "user"`) instead of assuming exactly 3 messages per turn.
  - In `_extract_turn_text`, increment `turn_idx` only on `role == "user"` messages.

#### [MODIFY] [api_llm.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/api_llm.py)
- **M-2 / M-3**:
  - Reset `backoff = 5.0` at the start of each key iteration in the API request loop.
  - Only record successfully processed requests to the daily quota counter, avoiding inflation from resource exhaustion errors.

#### [MODIFY] [quota.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/quota.py)
- **M-20 / M-21 / M-22**:
  - Add thread locking to modifications of `QuotaManager` counters.
  - In `any_model_has_quota`, check all keys in `self._counters` instead of just the pre-initialized models.
  - Add date checking and automatic reset of daily counters in `has_daily_quota`.

---

### Component 4: Logging & Other Minor Fixes

#### [MODIFY] [logger.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/logger.py)
- **M-23 / L-15 / L-16**:
  - Add simple thread synchronization/locking to `_write` to avoid interleaved JSON log entries.
  - In `LOG_MAX_CHARS` parsing, wrap in a try-except block with a default fallback to `6000`.
  - In `snapshot_agent`, use safe `getattr` checks to prevent crashes on partially initialized agents.

#### [MODIFY] [death.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/python/tooling/death.py)
- **L-4 / L-5**:
  - Use `float(target.z)` instead of hardcoded `0.0` for estate z coordinate.
  - Capture `pre_death_state` before calling `liquidate_portfolio`.

#### [MODIFY] [patch.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/patch.py)
- **M-25**:
  - Fix Add File block parser to treat lines without a `+` prefix as content lines.

#### [MODIFY] [frontend.py](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/frontend.py)
- **H-2 / M-17**:
  - Escape angle brackets in `data.raw_model_reasoning` to secure against XSS.
  - Remove duplicate `seek(0, SEEK_END)` call in the SSE loop.

#### [MODIFY] [prompts/common_prompt.txt](file:///c:/Users/abhik/OneDrive/Documents/Abhik/AgentSim-R/prompts/common_prompt.txt)
- **M-19**:
  - Adjust prompt instructions to permit multiple tool calls.

---

## Verification Plan

### Automated Tests
- Run the full test suite to ensure all 60 tests (including the 3 currently failing tests) pass successfully:
  ```powershell
  pytest
  ```

### Manual Verification
- Launch the simulation frontend and interact with it:
  ```powershell
  python frontend.py
  ```
- Verify that agents can successfully purchase homes (C-1/C-2) and change elevation levels (X-3/C-2).
- Inspect the browser SSE console reasoning log for correct HTML rendering and absence of unescaped tags (H-2).
