# AgentSim-R — Agent Simulation (Research)

AgentSim-R is a synthetic “imaginary world” simulation of multiple LLM-driven agents acting under explicit constraints: time, money, energy, hunger, hydration, open hours, proximity, and inventory limits. The goal is to study **emergent behavior** (economic, social, and survival dynamics) when agents must make grounded decisions in a shared environment.

This *might not* be freeform roleplay. Agents must choose **one concrete action per turn** via tool calls, and the environment enforces hard constraints.


> [!NOTE]   
> Any and all open source contributions are welcome. If the moderator(s) feel(s) that they are useful to ***AgentSim-R***, then they will be merged accordingly. Thank You
---

## 1) Technical setup

### Model / inference
AgentSim-R expects a local `llama-server` compatible endpoint.

Example:
```bash
llama-server -m /path/to/model.gguf -c 262144 --parallel 1 --slot-save-path ./cache
```

Key points:
- Context is configured for large windows (`CONTEXT_SIZE=262144` in `python/config.py`).
- **Per-agent slot save/restore** is enabled (KV-cache persistence) using `cache/agent_{id}.bin`.
- Generation settings are currently set in `python/prompting.py` (`temperature`, `top_p`, `repeat_penalty`, etc.).

### Run
From repo root:
```bash
python python/sim.py
```

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

No text is allowed after `</tool_call>`.

Tool schemas are described in `tools.json` and enforced by the engine.

---

## 3) Determinism note (research honesty)

- The Python simulation logic is largely deterministic given a fixed seed (movement graph, passive updates, etc.).
- **Overall runs are not guaranteed deterministic** because LLM sampling depends on inference server behavior and generation randomness unless your server is configured to be fully deterministic.

---

## 4) Repository layout (modularized)

The project keeps stable import paths while using a modular internal structure:

- `python/tools.py`: **facade** re-exporting tool execution + catalogs from modular code
- `python/utils.py`: **facade** re-exporting prompting + server call functions
- `python/prompting.py`: compact observation prompt builder + llama-server request + slot save/restore
- `python/core.py`: time utilities (clock formatting, market hours)

Tool engine is modular:
- `python/tooling/execute.py`: dispatcher + registry
- `python/tooling/parsing.py`: XML tool-call parser (regex compiled once)
- `python/tooling/catalogs.py`: item + vehicle catalogs + workplace mappings
- `python/tooling/navigation.py`: shortest-route distance on a coarse road grid (A*)
- `python/tooling/scenarios.py`: scenario pools (~30 per role) with recency control
- `python/tooling/helpers.py`: canonicalization, reachability, busy checks, etc.
- `python/tooling/death.py`: death/estate logic
- `python/tooling/handlers/*.py`: handlers grouped by domain

---

## 5) World model (imaginary world, hardcoded boundaries)

The village is represented as a continuous coordinate plane (0..5000m on both axes), with hardcoded 3D location boxes (buildings, parks, etc.) and interactables.

- Locations + bounding boxes: `python/locations.py`
- Each location also has an **entrance point** (door anchor).
- Agents can be “Outside” or inside a location box.

### Outside-door rule
`move_to(place=...)` moves to the **outside entrance area**, not directly inside.

To enter a building:
- use `walk` until you cross into the building’s boundary.

This prevents “teleport into building” and supports realistic closed-door behavior.

---

## 6) Scheduling model (parallel-by-busy_until)

Simulation is event-driven:
- each agent has `busy_until`
- the scheduler always picks the next available agent (smallest `busy_until`)
- passive “hourly ticks” are applied whenever simulated time advances

This approximates parallel action: one agent can be busy for hours while others continue acting.

---

## 7) Movement + pathing (Python DSA, shortest-route)

Movement distance is computed using an “infrastructure-aware” approximation:
- a coarse road grid over the 5km×5km plane
- shortest path via **A\*** on a 4-neighbor grid
- “tail/head connectors” from true coordinates to nearest road node

Let:
- grid spacing be \( s = 250 \) meters
- \(d_{tail}\) be distance from start to nearest road node
- \(d_{grid}\) be A\* shortest path length on the road grid
- \(d_{head}\) be distance from destination road node to destination point

Then route distance is:
\[
d = d_{tail} + d_{grid} + d_{head}
\]

This is implemented in `python/tooling/navigation.py`.

---

## 8) Vehicles (asset-based, fuel-per-km)

Agents have a **vehicle asset** (default: Scooter). Vehicles are not inventory items.

Rules:
- An agent can ride only if within **100m** of their parked vehicle.
- Riding has:
  - time cost based on route distance and vehicle speed
  - fuel cost based on route distance in km
  - small energy cost

If an agent cannot afford fuel, movement falls back to walking (no fuel cost).

Vehicle parameters live in `python/tooling/catalogs.py`:

- Scooter default speed ≈ 45 km/h = 12.5 m/s
- Fuel costs are simplified to a single $/km parameter.

Vehicles are purchased only inside `Vehicle_Dealership` during open hours.

---

## 9) Core state variables

Each agent maintains explicit numeric state (bounded):
- `health` ∈ [0, 100]
- `energy` ∈ [0, 100]
- `hydration` ∈ [0, 100]
- `hunger` ∈ [0, 100]
- `stress` ∈ [0, 100]
- `happiness` ∈ [0, 100]
- `education` ∈ [0, 100]
- `relationships` ∈ [0, 25]
- plus money, wage, inventory, holdings, etc.

---

## 10) Passive dynamics (math models)

Passive updates occur once per simulated hour.

### 10.1 Happiness model
Relationships are scaled:
\[
R_{scaled} = \min\left(100,\; \frac{\text{relationships}}{5}\cdot 100\right)
\]

Happiness target:
\[
H^* = 0.3\cdot \text{health} \;+\; 0.3\cdot R_{scaled} \;+\; 0.4\cdot 100 \cdot \tanh\!\left(\frac{\text{money}}{\text{expenses} + \varepsilon}\right)
\]
with \(\varepsilon = 1\).

Update:
\[
\text{happiness}_{t+1} = \mathrm{clamp}_{0,100}\Big(0.7\cdot \text{happiness}_t + 0.3\cdot H^*\Big)
\]

### 10.2 Stress model
Relationship tension components:
\[
\text{loneliness} = \max(0, 3-\text{relationships})^2
\]
\[
\text{crowding} = \max(0, \text{relationships}-10)\cdot 2
\]
\[
\text{rel\_tension} = w_1(\text{loneliness}+\text{crowding})
\]
where \(w_1=1\).

Financial pressure:
\[
\text{fin\_pressure} = w_2 \cdot \frac{\text{expenses}}{\max(0,\text{money}) + 1}
\]
where \(w_2=2\).

Market anxiety (only when shares owned and price drops):
\[
\text{market\_anxiety} \propto w_3 \cdot |\Delta P| \cdot \frac{\text{position\_value}}{\max(0,\text{money})+1}
\]
with \(w_3=0.5\).

Base stress target:
\[
\Psi^* = \frac{\text{rel\_tension} + \text{fin\_pressure} + \text{market\_anxiety}}
{1 + \alpha\cdot \text{happiness} + \beta\cdot \text{hourly\_wage}}
\]
where \(\alpha=0.01,\; \beta=0.001\).

Hydration scaling:
- if hydration < 30: \(\Psi^* \leftarrow 1.1\Psi^*\)
- if hydration < 15: \(\Psi^* \leftarrow 1.25\Psi^*\)

Debt penalty:
- if money < 0: multiply by 1.5

Update:
\[
\text{stress}_{t+1} = \mathrm{clamp}_{0,100}\Big(0.7\cdot \text{stress}_t + 0.3\cdot \Psi^*\cdot \text{debt\_penalty}\Big)
\]

### 10.3 Health model
Age factor:
\[
A = e^{0.02\cdot \text{age}}
\]

Energy penalty:
- 0 if energy > 10
- 0.5 otherwise (then multiplied in formula as \(10\cdot 0.5\))

Dehydration penalty:
\[
D =
\begin{cases}
(20-\text{hydration})\cdot 0.2 & \text{if hydration}<20 \\
0 & \text{otherwise}
\end{cases}
\]

Health delta:
\[
\Delta \text{health} =
\Big(
-\big(0.5\cdot \text{stress} + 0.3\cdot \text{hunger} + 10\cdot \text{energy\_penalty} + D\big)
+ 0.1\cdot \text{happiness}
\Big)\cdot A \cdot 0.02
\]

Update:
\[
\text{health}_{t+1} = \mathrm{clamp}_{0,100}(\text{health}_t + \Delta\text{health})
\]

Starvation damage (if hunger = 100 for consecutive hours):
\[
\text{health} \leftarrow \text{health} - \min(32,\; 2^{h})
\]

Dehydration damage (if hydration = 0 for consecutive hours):
\[
\text{health} \leftarrow \text{health} - \min(16,\; 1.5^{d})
\]

If health ≤ 0: agent dies and becomes lootable estate.

### 10.4 Hunger / hydration drift
Per simulated hour:
- hunger increases by:
  - +5 if awake
  - +0.5 if sleeping
- hydration decreases by:
  - −4 if awake
  - −1.5 if sleeping
- energy decreases by:
  - −2 if awake (sleep restores energy via sleep tool)

Emergency auto-consumption triggers at critical thresholds and consumes:
held item → inventory → emergency buy (if affordable).

---

## 11) Work + education tasks (anti-farming)

Work/study are multi-step tasks:
1) initiate (`work_job` / `get_education`)
2) `pick_item` required prop (task-only prop)
3) `interact_with` MCQ answer (A/B/C)

Rules:
- You must be **inside** the correct building to start.
- Task steps are locked: you cannot run unrelated tools mid-task.
- A hard failure cap exists (3 failures cancels the task).
- Scenario pools are role-specific and ~30 deep with recency control.

Pay model (work):
\[
\text{pay} = \text{hourly\_wage} \cdot \text{hours} \cdot \frac{\text{market\_price}}{100}
\]
and half pay if incorrect.

Education model:
- education +5, wage +5 if correct
- education +1, wage +1 if incorrect
- tuition charged up front:
  - baseline 2000
  - masters 4000
  - phd 8000
  - student discount caps tuition at 150

---

## 12) Stock market model

Market open:
- Mon–Fri 09:30–16:00

Price updates hourly during open hours:
\[
P_{t+1} = P_t \cdot \exp\Big((\mu-\tfrac{1}{2}\sigma^2) + \sigma \epsilon_t\Big)\cdot \text{impact}
\]
with impact based on net volume that hour.

Defensive behavior:
- invalid prices reset to 100
- hard clamp to a sane range (floor and ceiling)

Orders placed when closed are queued.

---

## 13) Taxes

A midnight tax is applied, but low-cash agents are exempt:
- if money < 200: no tax
- else: subtract TAX_AMOUNT

This prevents immediate negative spirals for poor agents (e.g., students).

---

## 14) Logging (research-friendly, non-exploding)

By default, logs store:
- pre/post state snapshots
- tool name/args/result
- prompt hash + char count
- summarized message previews (not full system prompt + full chat history)

To log full prompts/messages (large):
```bash
LOG_FULL_MESSAGES=1 python python/sim.py
```

This was added because logging full system prompt + full history every turn causes massive disk usage and makes analysis painful.

---

## 15) Notes on prompt design (why it’s compact)
The per-turn observation is intentionally small (clock, location/coords, needs, money, held/inv count, visible objects/doors, nearby people, vehicle proximity, market line, task hint). The model can “think”, but must output exactly one tool call.

---