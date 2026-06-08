# AgentSim-R — Agent Simulation (Research)

AgentSim-R is a synthetic "imaginary world" simulation of multiple LLM-driven agents acting under explicit constraints: **time, money, energy, hunger, hydration, open hours, proximity, inventory limits, and inventory/hand state**. The goal is to study **emergent behavior** (economic, social, and survival dynamics) when agents must make grounded decisions in a shared environment.

This is not freeform roleplay. Agents must choose **one concrete action per turn** via tool calls, and the environment enforces hard constraints.

> [!NOTE]   
> **Summary**: This project is aimed at observing *emergent behavior* when multiple agents interact in a shared environment with enforceable rules. It is designed to be research-auditable and grounded, not "creative RP".

> [!WARNING]   
> The engine can execute multiple tool calls if the model outputs them (robustness), but agents are still instructed to output exactly one.

> [!NOTE]   
> Any and all open source contributions are appreciated!

---

## 1) Run modes & Technical setup

### Install pre-requisites:
Install packages via pip

```bash
pip install -r requirements.txt
```

### A) Local runner (llama-server style)
AgentSim-R expects a local `llama-server` compatible endpoint.

#### Setup llama.cpp:
Install llama.cpp first
```bash
# if you have vscode dev tools for cpp compilation (recommended):
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp

# cpu only:
cmake -B build
cmake --build build --config Release

# nvidia gpu (cuda):
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release
```

If you do not have c++ compilers:
```bash
# windows:
winget install llama.cpp

# linux and macos:
brew install lllama.cpp
```
Example:

```bash
llama-server -m /path/to/model.gguf -c 262144 --parallel 1 --slot-save-path ./cache
# adjust `-c {int(len(context_window))} ^ here according to your hardware
```

Key points:
- Context is configured for large windows (`CONTEXT_SIZE=262144` in `python/config.py`).
- **Per-agent slot save/restore** is enabled using `cache/agent_{id}.bin`.
- Generation settings are configured in `python/prompting.py` (`temperature`, `top_p`, `repeat_penalty`, etc.).

Run:

```bash
python python/sim.py
```

### B) API runner (Google GenAI SDK)
Runs exclusively using the Google GenAI SDK (optimized natively for Gemini 3.1 & Gemma 4 reasoning traces).

```bash
python run_api_sim.py
```

### View Logs:
To view the logs (in real time)

```bash
python frontend.py
```

Then open `localhost:9261` in a browser.
 (wait for all agents to have a turn, if you cant see **agent $0 \cdots 5$**, then refresh.)


### Prompt extraction / debugging
To dump the fully rendered prompt for each starting agent:

```bash
python extract_t1.py
```
This writes to `prompt.log`.

### Save/continue support
Both `python/sim.py` and `run_api_sim.py` support:
- **Continue from save** (`saves/world.json`)
- Or **wipe** cache/logs/save and start fresh

**Optimized Resume**: When continuing a simulation, the engine automatically caps the raw chat history, relying strictly on the agent's deeply compacted **summary texts** combined with the short-term remainder. This prevents massive context bloat and makes resuming long simulations (e.g., Week 2+) highly efficient and scalable.

Autosaves occur every `AUTOSAVE_TICKS` ticks (default 10).

---

## 2) Tool-call contract (critical)

Agents must output **exactly one** XML tool call per turn.

Allowed structure:

```xml
<think>
(optional)
</think>
<tool_call>
<function=tool_name>
<parameter=param_name>
value
</parameter>
</function>
</tool_call>
```

**No text is allowed after `</tool_call>`.**

Tool schemas are described in `tools.json` and enforced by the engine.

### Important contract notes:
- `move_to` accepts **named places only**, such as `Library`, `Store_A`, `Startup_Sowl`, or `Home_Taylor`.
- Coordinates shown in observations are **read-only telemetry** and are never valid tool inputs.
- The engine tolerates loose name variants, e.g. `Startup Sowl` → `Startup_Sowl`.
- Roofed-building rule: `move_to(place=...)` takes you to the **outside entrance area**; use `walk` to enter.
- Corpse estate loot is automatic when close enough; do not manually loot item-by-item.

### Engine robustness: multiple tool calls in one model response
If the model outputs multiple `<tool_call>...</tool_call>` blocks, the engine executes them sequentially and returns a combined result string.
- Each step is reported as `OK` or `FAIL`.
- Overall `success` is **True only if ALL steps succeeded**.
- **Time cost is summed** across steps. Failed steps add a minimum 60-second penalty. This prevents multi-call outputs from "cheating time".

### API runner note: native tool calling
In API mode, Gemini receives `tools` through the Google GenAI SDK's native function-calling API. The router converts returned function calls into the engine's XML shape internally so the existing scheduler and tool executor can keep using the same path.

---

## 3) Determinism note (research honesty)

- The simulation logic is largely deterministic given a fixed seed (movement graph, passive updates, scenario selection constraints).
- **Overall runs are not guaranteed deterministic** because LLM sampling depends on inference server behavior.
- Slot/KV cache loss does **not** erase simulation memory; the source of truth is still Python-side prompt state (`system_prompt`, `chat_history`, and current world state). Cache loss mainly affects speed.

---

## 4) World model (imaginary world)

The village is a continuous coordinate plane (`0..5000m`), with hardcoded 3D location boxes (buildings, parks, outdoor spaces, homes).
- **Temporary floor restriction**: For now, agents are clamped to the **ground floor (Z=0)**. Floor-changing interactions are disabled.

Public locations include:
- `Hospital`, `School`, `Office_FedEx`, `Startup_Sowl`
- `Store_A`, `Store_B`, `Market`
- `Park_Central`, `Cafe`, `Library`, `Gym`, `Village_Square`
- `Farm`, `Mall`, `Lake`, `Vehicle_Dealership`

### Home aliases
Agents should use home aliases (e.g., `Home_Alex`, `Home_Taylor`) rather than internal location IDs.

### Simulation date/time
The simulation starts on **Monday, 30-03-2026 08:00**. Prompts/logs use real date formatting.

---

## 5) Scheduling model (parallel-by-busy_until)
The simulation is event-driven:
- each agent has a `busy_until` timestamp.
- the scheduler always picks the next available agent.
- passive "hourly ticks" apply when simulated time advances.
This approximates parallel action: one agent can be busy for hours while others continue acting.

---

## 6) Movement + pathing (Python DSA, shortest-route)
Movement distance is computed with an infrastructure-aware approximation:
- A coarse road grid over the $5\text{km} \times 5\text{km}$ plane
- Shortest path via **A\*** on a 4-neighbor grid
- Connector distance from real coordinates to nearest road nodes

Let:
- grid spacing be $s = 250$ meters
- $d_{\text{tail}}$ be distance from start to nearest road node
- $d_{\text{grid}}$ be $A^*$ path length on the road grid
- $d_{\text{head}}$ be distance from destination road node to destination point

Then:
$$
d = d_{\text{tail}} + d_{\text{grid}} + d_{\text{head}}
$$

**Movement fuel rule**: If the agent can use a vehicle and **cannot afford fuel**, `move_to` **fails** (no walk fallback).

---

## 7) Vehicles (asset-based, fuel-per-km)
Agents have a **vehicle asset** (default: Scooter). Vehicles are not inventory items.
Rules:
- Ride only if within **100m** of the parked vehicle.
- Time cost depends on vehicle speed and route distance.
- Fuel cost is simplified as **$ per km**.

---

## 8) Core state variables (bounded)
Key numeric state (bounded unless noted):
- `health`, `energy`, `hydration`, `hunger`, `stress`, `happiness`, `education` ∈ [0, 100]
- `relationships` ∈ [0, 25]
- `money` (float; can go negative)
- `hourly_wage`, `expenses`, `inventory`, `held item`, etc.

---

## 9) Passive dynamics (math models)
Passive updates occur once per simulated hour.

### 9.1 Happiness & Stress model

Relationships scaling:

$$R_{\text{scaled}} = \min\!\left(100, \frac{\text{relationships}}{5}\cdot 100\right)$$

Happiness target:   

$$H^* = 0.3\cdot \text{health} + 0.3\cdot R_{\text{scaled}} + 0.4\cdot 100 \cdot \tanh\!\left(\frac{\text{money}}{\text{expenses} + 1}\right)$$

Update:   

$$\text{happiness}_{t+1} = \mathrm{clamp}_{[0,100]}\!\left(0.7\cdot \text{happiness}_{t} + 0.3\cdot H^*\right)$$

Stress relies on relationship tension, financial pressure, and market anxiety. 

$$\text{stress}_{t+1} = \mathrm{clamp}_{[0,100]}\left(0.7 \cdot \text{stress}_t + 0.3 \cdot \Psi^* \cdot \text{debt}_{penalty}\right)$$


### 9.2 Health model
Health drops based on stress, hunger, and energy/dehydration penalties. 
Starvation damage (if hunger = 100 for consecutive hours):  $\text{health} \leftarrow \text{health} - \min(32, 2^h)$
Dehydration damage (if hydration = 0 for consecutive hours):  $\text{health} \leftarrow \text{health} - \min(16, 1.5^d)$

If health ≤ 0: agent dies and becomes a lootable estate.

### 9.3 Hunger / hydration drift & emergency auto-consumption
Per hour:
- Hunger: $+5$ if awake, $+0.5$ if sleeping
- Hydration: $-4$ if awake, $-1.5$ if sleeping
- Energy: $-2$ if awake

Emergency triggers:
- If awake and hunger ≥ 90 → attempt emergency consume/buy.
- If awake and hydration ≤ 12 → attempt emergency drink/buy.

---

## 10) Work + education tasks (anti-farming)
Work/study are multi-step tasks:
1. Initiate (`work_job` / `get_education`)
2. `pick_item` required task prop
3. `interact_with` MCQ answer (`A` / `B` / `C`)

Rules:
- Must be **inside** the correct building to start.
- Unrelated tools are blocked mid-task.
- After 3 failures, the task cancels.
- Duration is capped (1 to 10 hours).

Pay model (work):

$$\text{pay} = \text{hourly}_{wage} \cdot \text{hours} \cdot \frac{\text{market}_{price}}{100}$$

Half pay if incorrect.

Education model:
- correct: education +5, wage +5
- incorrect: education +1, wage +1
- Tuition charged up front.

---

## 11) Stock market model
Market open: Mon–Fri 09:30–16:00.
Price updates hourly during open hours:

$$P_{t+1} = P_t \cdot \exp\!\Big((\mu-\tfrac{1}{2}\sigma^2) + \sigma \epsilon_t\Big)\cdot \text{impact}$$
Orders placed when closed are queued and executed during open hours.

---

## 12) Taxes
A midnight tax is applied, but low-cash agents are exempt (money < 200).

---

## 13) Social: Hard Interruption & Interactions

**Interaction Rule**: Only **sleeping** prevents interaction. Agents can freely socialize, talk, interact, and be called even if they are actively marked as busy/working.

Social rules:
- **Hard Interruption & Proration**: If an agent is actively performing a multi-hour task (e.g., `work_job` or `get_education`) and someone talks to them, calls them, or gives them an item/money, **the task is hard-interrupted**. The engine uses transient metadata to calculate the elapsed ratio, refunds unspent energy, and claws back unearned wages/stats. The target agent's `busy_until` is truncated so they can respond immediately.
- **Transit Restrictions**: In-person tools (`talk_to`, `give_item`, `change_status`, `attack_person`) instantly fail if the target is mid-movement (`current_activity == "moving"`). Remote tools like `call_person` succeed and safely halt the agent on the road (prorating distance/fuel).
- `call_person`: If target is sleeping → goes to **voicemail**. Otherwise, real-time notification (and interruption).
- `talk_to`: If target is sleeping → fails, target receives **missed interaction** notification.
- `change_status`: Fails if target is sleeping.
- `give_item` / `give_money`: If target is sleeping → transfer is **queued** and delivered automatically upon waking.
  - `give_money` = bank transfer. No proximity required, only fails if sender lacks funds.

---

## 14) Notifications (drip-fed)
Notifications can accumulate. To keep prompts usable:
- Only a limited number of notifications are shown per turn.
- The rest remain queued: "Queued notifications remaining: N".

---

## 15) Logging
Logs are JSONL (one JSON object per line) and include:
- Pre/post agent state snapshots
- Tool name/args/result
- Prompt hash + prompt char count
- Structured `system_prompt` + `user_observation` fields

Enable full prompt/messages logging:

```bash
LOG_FULL_MESSAGES=1 python python/sim.py
```

---

## 16) Repository layout (modularized)

- `python/tools.py`: facade re-exporting tool execution + catalogs
- `python/utils.py`: facade re-exporting prompting + server call functions
- `python/prompting.py`: prompt builder + llama-server call
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
- `python/api_llm.py`: Google GenAI SDK (Gemini/Gemma models) + summarizer

---

## 17) Phase 1 starting agents

| Name   | Role            | Age | Hourly Wage | Starting Cash | Home Type       |
| ------ | --------------- | --- | ----------- | ------------- | --------------- |
| Alex   | developer       | 28  | $50         | $5000         | Small Apartment |
| Jamie  | nurse           | 35  | $60         | $6000         | Apartment       |
| Taylor | student         | 21  | $20         | $20           | Small Apartment |
| Jordan | delivery driver | 39  | $20         | $2000         | Apartment       |
| Mia    | teacher         | 41  | $35         | $3500         | House           |
| Ethan  | founder         | 30  | $100        | $10000        | Luxury House    |

---

## 18) License
Modified MIT. See `LICENSE`.

> Thank you for reading!
