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
python run_sim_api.py
```

The API runner:
- Rotates among **up to 5 keys per provider** on HTTP 429 rate-limit
- Uses strict **OpenAI-style tool handshake** (`assistant.tool_calls[]` + `tool.tool_call_id`)
- Uses summarization to keep prompts under a target context budget

---

## 2) Save/continue support

Both `python/sim.py` and `run_sim_api.py` support:
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

## 4) Social tool semantics (project-specific)

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

## 5) Movement fuel rule
If the agent can use a vehicle and **cannot afford fuel**, `move_to` **fails** (no walk fallback).

---

## 6) Temporary floor restriction (Floor 1 only)
For now:
- Agents are clamped to **floor 1 (Z=0)** after any successful tool
- Floor-changing interactions (stairs/elevators to Z!=0) are blocked
- Homes are allocated/purchased on **Floor 1 only**

This prevents agents from getting stuck on upper floors during early development.

---

## 7) Repository layout (modularized)

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
- `python/api_llm.py`: provider router (OpenRouter/Groq/Cerebras) + strict tool_call_id support + summarizer

---

## 8) World model (imaginary world, hardcoded boundaries)

The village is a continuous coordinate plane (`0..5000m` on both x and y), with hardcoded 3D location boxes (buildings, parks, outdoor spaces, homes, and interactables).

Primary files:
- Locations + bounding boxes: `python/locations.py`
- Each location has an entrance point
- Agents are either "Outside" or inside a location box

---

## 9) Scheduling model (parallel-by-busy_until)

The simulation is event-driven:
- each agent has a `busy_until` timestamp
- the scheduler always picks the next available agent
- passive "hourly ticks" apply when simulated time advances

This approximates parallel action: one agent can be busy for hours while others continue acting.

---

## 10) Movement + pathing (shortest-route A* on road grid)

Movement distance is computed with an infrastructure-aware approximation:
- a coarse road grid over the $5\text{km} \times 5\text{km}$ plane
- shortest path via **A\*** on a 4-neighbor grid
- connector distance from real coordinates to nearest road nodes

Let:
- grid spacing be $s = 250$ meters
- $d_{\text{tail}}$ be distance from start to nearest road node
- $d_{\text{grid}}$ be $A^*$ path length on the road grid
- $d_{\text{head}}$ be distance from destination road node to destination point

Then:   
$$
d = d_{\text{tail}} + d_{\text{grid}} + d_{\text{head}}
$$

Implemented in `python/tooling/navigation.py`.

---

## 11) Vehicles (asset-based, fuel-per-km)

Agents have a **vehicle asset** (default: Scooter). Vehicles are not inventory items.

Rules (as implemented):
- ride only if within **100m** of the parked vehicle
- time cost depends on vehicle speed and route distance
- fuel cost is simplified as **$ per km**
- **if fuel is unaffordable, movement fails** (no walking fallback)

Vehicle parameters live in `python/tooling/catalogs.py`.

---

## 12) Passive dynamics (math models — aligned to code)

Passive updates occur once per simulated hour (see `python/scheduler.py::_apply_passive_updates`).

### 12.1 Hunger / hydration / energy drift

Per simulated hour:

- Hunger increases by:
  - $+5$ if awake
  - $+0.5$ if sleeping

- Hydration decreases by:
  - $-4$ if awake
  - $-1.5$ if sleeping

- Energy decreases by:
  - $-2$ if awake **and** not in a task (`task_state == "idle"`)
  - (no passive energy drain during active tasks; the task resolution applies its own cost)

Emergency triggers:
- If awake and hunger $\ge 90$, attempt emergency consume/buy.
- If awake and hydration $\le 12$, attempt emergency drink/buy.

### 12.2 Happiness model

Definitions used in code:
- $\varepsilon = 1$
- Relationship scaling:   
$$
R_{\text{scaled}} = \min\left(100, \frac{\text{relationships}}{5} \cdot 100\right)
$$

Happiness target:   
$$
H^* = 0.3 \cdot \text{health} \;+\; 0.3 \cdot R_{\text{scaled}} \;+\; 0.4 \cdot 100 \cdot \tanh\!\left(\frac{\text{money}}{\text{expenses}+\varepsilon}\right)
$$

Update:   
$$
\text{happiness}_{t+1} = \mathrm{clamp}_{[0,100]}\!\left(0.7\cdot \text{happiness}_t + 0.3\cdot H^*\right)
$$

### 12.3 Stress model

Weights/constants in code:   
- $w_1=1,\; w_2=2,\; w_3=0.5$  
- $\alpha=0.01,\; \beta=0.001$

Relationship tension:   
- loneliness term:   
$$
L = \max(0,\; 3-\text{relationships})^2
$$   
- crowding term:   
$$
C = 2\cdot \max(0,\; \text{relationships}-10)
$$   
- relationship tension:   
$$
T_{\text{rel}} = w_1\cdot (L + C)
$$

Financial pressure:   
- with money floor $\text{money}_+ = \max(0,\text{money})$   
$$
P_{\text{fin}} = w_2\cdot \frac{\text{expenses}}{\text{money}_+ + 1}
$$

Market anxiety (only if shares owned and price drops):   
- if $\Delta P < 0$, position value $V = \text{shares}\cdot P$   
$$
A_{\text{mkt}} = w_3\cdot |\Delta P|\cdot \frac{V}{\text{money}_+ + 1}
$$   
else $A_{\text{mkt}}=0$.

Base stress target:  
$$
\Psi^* = \frac{T_{\text{rel}} + P_{\text{fin}} + A_{\text{mkt}}}{1 + \alpha\cdot \text{happiness} + \beta\cdot \text{hourly\_wage}}
$$

Hydration scaling (awake only):   
- if hydration < 30: $\Psi^*\leftarrow 1.1\Psi^*$
- if hydration < 15: $\Psi^*\leftarrow 1.25\Psi^*$

Debt penalty:   
- if money < 0: multiply by $1.5$

Update:   
$$
\text{stress}_{t+1}=\mathrm{clamp}_{[0,100]}\!\left(0.7\cdot \text{stress}_t + 0.3\cdot (\Psi^*\cdot \text{debt\_penalty})\right)
$$

### 12.4 Health model

Age factor:   
$$
A = e^{0.02\cdot \text{age}}
$$

Energy penalty:   
$$
E_p =
\begin{cases}
0 & \text{if energy} > 10 \\
0.5 & \text{otherwise}
\end{cases}
$$

Dehydration penalty:   
$$
D =
\begin{cases}
0.2\cdot (20-\text{hydration}) & \text{if hydration}<20 \\
0 & \text{otherwise}
\end{cases}
$$

Health delta used in code:   
$$
\Delta h = \left(\;-\left(0.5\cdot \text{stress} + 0.3\cdot \text{hunger} + 10\cdot E_p + D\right) + 0.1\cdot \text{happiness}\;\right)\cdot A \cdot 0.02
$$

Then:   
$$
\text{health} \leftarrow \text{health} + \Delta h
$$

Starvation damage (if hunger = 100 for consecutive hours):   
$$
\text{health} \leftarrow \text{health} - \min(32, 2^{s})
$$

where $s$ increments each consecutive starvation hour.

Dehydration damage (if hydration = 0 for consecutive hours):   
$$
\text{health} \leftarrow \text{health} - \min(16, 1.5^{d})
$$

where $d$ increments each consecutive dehydration hour.

Finally clamp:   
$$
\text{health}\leftarrow \mathrm{clamp}_{[0,100]}(\text{health})
$$

If health $\le 0$, the agent dies and becomes a lootable estate.

### 12.5 Sleep recovery (implemented at wake-up)

Sleep recovery is applied when the agent wakes (see `_refresh_agent_activity`), prorated by actual sleep duration:

- If sleeping at home: energy rate 10/h, stress recovery 2/h  
- Elsewhere: energy rate 6/h, stress recovery 1/h

---

## 13) Work + education tasks

Work/study are multi-step tasks:
1. initiate (`work_job` / `get_education`)
2. `pick_item` required task prop
3. `interact_with` MCQ answer (`A` / `B` / `C`)

### 13.1 Work pay model (as implemented)

Pay:   
$$
\text{pay} = \text{hourly\_wage} \cdot \text{hours} \cdot \frac{P_{\text{market}}}{100}
$$

If incorrect: pay is halved.

Energy cost at completion:   
$$
\text{energy} \leftarrow \max(0,\; \text{energy} - 10\cdot \text{hours})
$$

### 13.2 Education gains (as implemented)

If correct:
- education +5
- wage +5

If incorrect:
- education +1
- wage +1

Tuition charged up front:
- baseline 2000
- masters 4000
- phd 8000
- student discount: tuition capped at 150

---

## 14) Stock market model (GBM + jump + impact)

Market open:
- Mon–Fri 09:30–16:00

Ticks every 5 minutes during open hours (`MARKET_TICK_SECONDS = 300`).

For a tick of duration $\Delta t$ hours:   
- $\epsilon \sim \mathcal{N}(0,1)$   
- baseline multiplier:   
$$
M_{\text{gbm}} = \exp\!\left((\mu-\tfrac{1}{2}\sigma^2)\Delta t + \sigma\sqrt{\Delta t}\,\epsilon\right)
$$

Jump shocks:
- with probability $p = \lambda \Delta t$ where $\lambda = \text{JUMP\_PROB\_PER\_HOUR}$
- jump $J\sim \mathcal{N}(0,\sigma_J)$ where $\sigma_J=\text{JUMP\_SIGMA}$
- jump multiplier: $M_{\text{jump}}=\exp(J)$

Volume impact:
- net volume over the period: $V$
- impact multiplier:   
$$
M_{\text{impact}} = \mathrm{clamp}_{[\ell,h]}\left(1+\kappa V\right)
$$
where $\kappa=\text{IMPACT\_FACTOR}$ and bounds are `IMPACT_CLAMP_LO/HI`.

Price update (open hours):   
$$
P_{t+1} = \mathrm{clamp}_{[10,1000]}\left(P_t\cdot M_{\text{gbm}}\cdot M_{\text{jump}}\cdot M_{\text{impact}}\right)
$$

Orders placed when market is closed are queued and executed during open hours.

---

## 15) API runner environment variables

Create a `.env` (see `.env.example`).

### Keys (up to 5 each)
- `OPENROUTER_API_KEY_1 .. OPENROUTER_API_KEY_5`
- `GROQ_API_KEY_1 .. GROQ_API_KEY_5`
- `CEREBRAS_API_KEY_1 .. CEREBRAS_API_KEY_5`

### Model lists (recommended)
Set model lists per provider:

- `OPENROUTER_MODELS`
- `GROQ_MODELS`
- `CEREBRAS_MODELS`

Each can be:
- a JSON list: `["model-a","model-b"]`
- or comma/newline-separated: `model-a, model-b`

Fallback:
- `OPENROUTER_MODEL_1 .. OPENROUTER_MODEL_5` (and similarly for Groq/Cerebras)

### Summarizer
- `SUMMARY_PROVIDER`
- `SUMMARY_MODEL`
- `SUMMARY_MAX_TOKENS`
- Optional prompt overrides:
  - `SUMMARY_USER_PROMPT_PATH` (preferred)
  - `SUMMARY_USER_PROMPT` (inline; must include `{existing_summary}` and `{chunk_text}`)
  - `SUMMARY_SYSTEM_PROMPT`

### Context + output
- `API_CONTEXT_SIZE` (default 100000)
- `API_CONTEXT_FILL_RATIO` (default 0.80 target ~80k)
- `API_MAX_NEW_TOKENS` (default 16384)

### Tool-role stability
- `TOOL_ROLE_MODE=tool` is enforced (strict tool_call_id handshake).

---

## 16) License
Modified MIT. See `LICENSE`.