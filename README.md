# AgentSim-R — Agent Simulation (Research)

AgentSim-R is a synthetic "imaginary world" simulation of multiple LLM-driven agents acting under explicit constraints: **time, money, energy, hunger, hydration, open hours, proximity, inventory limits, and inventory/hand state**. The goal is to study **emergent behavior** (economic, social, and survival dynamics) when agents must make grounded decisions in a shared environment with enforceable rules.

This is not freeform roleplay. Agents are instructed to output one concrete action per turn via tool calls, and the engine enforces constraints.

> [!WARNING]  
> The engine can execute multiple tool calls if the model outputs them (robustness), but agents are still instructed to output one.

---

## 1) Run modes

### A) Local runner (llama-server style)
```bash
python python/sim.py
```

### B) API runner (OpenRouter HTTP + Groq SDK + Cerebras SDK)
```bash
python run_api_sim.py
```

---

## 2) Save/continue support

Both `python/sim.py` and `run_api_sim.py` support:
- **Continue from save** (`saves/world.json`)
- Or **wipe** cache/logs/save and start fresh

Autosave:
- Every `AUTOSAVE_TICKS` ticks (default 10).

---

## 3) Tool-call contract (critical)

Agents are instructed to output **exactly one** XML tool call per turn, e.g.:

```xml
<tool_call>
<function=move_to>
<parameter=place>
Library
</parameter>
</function>
</tool_call>
```

### Engine robustness: multiple tool calls in one model response
If the model outputs multiple `<tool_call>...</tool_call>` blocks, the engine executes them sequentially and returns a combined result string:

- Each step is reported as `OK` or `FAIL`.
- Overall `success` is **True only if ALL steps succeeded**.
- **Time cost is summed** across steps:
  - Successful step: adds its normal cost
  - Failed step: adds at least **60 seconds penalty**

This prevents multi-call outputs from “cheating time”.

---

## 4) API runner note: provider tool calling is deprecated

In API mode, providers are used as **plain chat completions**. The model outputs XML tool calls as normal text, and the AgentSim-R engine parses and executes them.

- No `assistant.tool_calls[]` / `tool_call_id` handshake is required.
- Tool results are shown to the model as simple transcript lines like:
  - `RESULT (move_to): Travelled to ...`

This matches the local llama.cpp-style runner behavior.

---

## 5) Social tool semantics (project-specific)

### `give_money` = bank transfer
`give_money(person, amount)` is a bank transfer:
- No proximity requirement
- Ignores sleeping/busy/DND
- Fails only if:
  - recipient not found/alive (sender notified)
  - sender has insufficient funds (both sender and recipient notified)

### `change_status`
If the target is busy or sleeping, `change_status` **fails** (no queue).

---

## 6) Movement fuel rule
If the agent can use a vehicle and **cannot afford fuel**, `move_to` **fails** (no walk fallback).

---

## 7) Temporary floor restriction (Ground floor only)
For now:
- Agents are clamped to **ground floor (Z=0)** after any successful tool
- Floor-changing interactions are disabled
- Homes are allocated/purchased on the ground floor only

---

## 8) Repository layout (modularized)

Stable import paths + modular internals:
- `python/tools.py`: facade re-exporting tool execution + catalogs
- `python/utils.py`: facade re-exporting prompting + server call functions
- `python/prompting.py`: prompt builder + llama-server call (local runner)
- `python/core.py`: time/date utilities + market-hours logic
- `python/bootstrap.py`: starting-world initialization
- `python/persistence.py`: JSON save/load (`saves/world.json`)

Tool engine:
- `python/tooling/execute.py`: dispatcher + registry + schema validation
- `python/tooling/parsing.py`: strict XML tool-call parser
- `python/tooling/catalogs.py`: item + vehicle catalogs + workplace mappings
- `python/tooling/navigation.py`: shortest-route distance on a coarse road grid (A*)
- `python/tooling/scenarios.py`: scenario pools with recency control
- `python/tooling/helpers.py`: canonicalization, reachability, busy checks, etc.
- `python/tooling/death.py`: death/estate logic
- `python/tooling/handlers/*.py`: domain handlers

API runner:
- `python/api_llm.py`: provider router (OpenRouter/Groq/Cerebras) + summarizer

---

## 9) License
Modified MIT. See `LICENSE`.
```

---