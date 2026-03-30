# AgentSim-R — Agent Simulation (Research)

AgentSim-R is a synthetic “imaginary world” simulation of multiple LLM-driven agents acting under explicit constraints: time, money, energy, hunger, hydration, open hours, proximity, inventory limits, and inventory/hand state. The goal is to study **emergent behavior** (economic, social, and survival dynamics) when agents must make grounded decisions in a shared environment.

This is not freeform roleplay. Agents must choose **one concrete action per turn** via tool calls, and the environment enforces hard constraints.

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
- **Per-agent slot save/restore** is enabled using `cache/agent_{id}.bin`.
- Generation settings are currently set in `python/prompting.py` (`temperature`, `top_p`, `repeat_penalty`, etc.).

### Run
From repo root:
```bash
python python/sim.py
```

### Prompt extraction / debugging
To dump the full rendered prompt for every starting agent:
```bash
python extract_prompt.py
```

This writes all prompts to:
```bash
prompt.log
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

Important contract notes:
- `move_to` accepts **named places only**, such as `Library`, `Store_A`, `Startup_Sowl`, or `Home_Taylor`.
- Coordinates shown in observations are **read-only telemetry** and are never valid tool inputs.
- The engine tolerates **loose normalized names**, so inputs like `Startup Sowl` or `Office FedEx` are accepted and canonicalized.
- `pick_item` is for:
  - picking up a nearby dropped ground item, or
  - picking up the required task prop during an active work/study task
- `hold_item` is for:
  - moving an inventory item into your hand, or
  - storing your held item back into inventory with values like `store`, `none`, `unequip`, or `put away`
- Corpse estate loot is **automatic** when an agent gets close enough; agents do not manually loot corpses item-by-item.

---

## 3) Determinism note (research honesty)

- The Python simulation logic is largely deterministic given a fixed seed (movement graph, passive updates, scenario selection constraints, etc.).
- **Overall runs are not guaranteed deterministic** because LLM sampling depends on inference server behavior and generation randomness unless your server is configured to be fully deterministic.
- If the `llama-server` slot/KV cache is invalidated, agents do **not** lose their simulation memory, because the source of truth is still the Python-side prompt state (`system_prompt`, `chat_history`, and current world state). Cache loss mainly affects speed and recomputation cost.

---

## 4) Repository layout (modularized)

The project keeps stable import paths while using a modular internal structure:

- `python/tools.py`: facade re-exporting tool execution + catalogs from modular code
- `python/utils.py`: facade re-exporting prompting + server call functions
- `python/prompting.py`: compact observation prompt builder + llama-server request + slot save/restore
- `python/core.py`: time/date utilities and market-hours logic

Tool engine is modular:
- `python/tooling/execute.py`: dispatcher + registry
- `python/tooling/parsing.py`: XML tool-call parser
- `python/tooling/catalogs.py`: item + vehicle catalogs + workplace mappings
- `python/tooling/navigation.py`: shortest-route distance on a coarse road grid (A*)
- `python/tooling/scenarios.py`: scenario pools with recency control
- `python/tooling/helpers.py`: canonicalization, reachability, busy checks, etc.
- `python/tooling/death.py`: death/estate logic
- `python/tooling/handlers/*.py`: handlers grouped by domain

---

## 5) World model (imaginary world, hardcoded boundaries)

The village is represented as a continuous coordinate plane (`0..5000m` on both axes), with hardcoded 3D location boxes (buildings, parks, outdoor spaces, homes, and interactables).

Primary files:
- Locations + bounding boxes: `python/locations.py`
- Each location also has an **entrance point**
- Agents can be “Outside” or inside a location box

Public world locations currently include:
- `Hospital`
- `School`
- `Office_FedEx`
- `Startup_Sowl`
- `Store_A`
- `Store_B`
- `Market`
- `Park_Central`
- `Cafe`
- `Library`
- `Gym`
- `Village_Square`
- `Farm`
- `Mall`
- `Lake`
- `Vehicle_Dealership`

### Roofed-building outside-door rule
For **roofed buildings**, `move_to(place=...)` moves to the **outside entrance area**, not directly inside.

To enter a roofed building:
- use `walk` until you cross into the building’s boundary

This prevents “teleport into building” and supports realistic closed-door behavior.

### Open-air locations
For **open-air locations** such as parks, squares, lakes, and similar spaces:
- `move_to` places the agent **directly there**
- there is no separate outside-door step

### Home aliases
Agents should use friendly home aliases such as:
- `Home_Alex`
- `Home_Taylor`

They should not use internal location IDs like:
- `SmallApartment_Maple_Unit_1_Floor_1`

### Simulation date/time
The simulation now uses a **real calendar start date**:
- **Monday, 30-03-2026 08:00**

Prompts/logs use real date formatting instead of arbitrary synthetic labels like `Day 1`.

---

## 6) Scheduling model (parallel-by-busy_until)

Simulation is event-driven:
- each agent has `busy_until`
- the scheduler always picks the next available agent (smallest `busy_until`)
- passive “hourly ticks” are applied whenever simulated time advances

This approximates parallel action: one agent can be busy for hours while others continue acting.

---

## 7) Movement + pathing (Python DSA, shortest-route)

Movement distance is computed using an infrastructure-aware approximation:
- a coarse road grid over the `5km × 5km` plane
- shortest path via **A\*** on a 4-neighbor grid
- connector distance from true coordinates to nearest road nodes

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

### Coordinate rule
Coordinates are shown to agents for awareness and realism, but:
- they are **not valid action parameters**
- `move_to` must use **named places only**

---

## 8) Vehicles (asset-based, fuel-per-km)

Agents have a **vehicle asset** (default: Scooter). Vehicles are not inventory items.

Rules:
- An agent can ride only if within **100m** of their parked vehicle
- Riding has:
  - time cost based on route distance and vehicle speed
  - fuel cost based on route distance in km
  - small energy cost
- If an agent cannot afford fuel, movement falls back to walking

Vehicle parameters live in `python/tooling/catalogs.py`.

Examples:
- Scooter default speed ≈ `12.5 m/s`
- Fuel costs are simplified to a single `$ / km` parameter

Vehicles can be purchased only:
- while **inside** `Vehicle_Dealership`
- during dealership open hours

For cleaner early-game and ownership behavior:
- starting agents are initialized into floor-1 homes
- home allocation currently prefers floor-1 homes where available

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
- plus money, wage, inventory, holdings, vehicle state, pending tasks, etc.

Prompts surface a compact but useful subset, including:
- real date/time
- health
- hunger
- energy
- hydration
- stress
- happiness
- nearby people
- visible objects
- nearby location open/closed status
- active task details
- inventory count shown as current/max

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
- 0.5 otherwise

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

If health ≤ 0: agent dies and becomes a lootable estate.

### 10.4 Hunger / hydration drift
Per simulated hour:
- hunger increases by:
  - +5 if awake
  - +0.5 if sleeping
- hydration decreases by:
  - −4 if awake
  - −1.5 if sleeping
- energy decreases by:
  - −2 if awake

Emergency auto-consumption triggers at critical thresholds and can consume:
- held food/drink
- inventory food/drink
- emergency purchase from village food stock if affordable

---

## 11) Work + education tasks (anti-farming)

Work/study are multi-step tasks:
1. initiate (`work_job` / `get_education`)
2. `pick_item` required task prop
3. `interact_with` MCQ answer (`A` / `B` / `C`)

Rules:
- You must be **inside** the correct building to start
- Task steps are locked: you cannot run unrelated tools mid-task
- A hard failure cap exists (3 failures cancels the task)
- Scenario pools are role-specific and built to provide **at least 30 genuinely unique scenarios per role**
- Prompt observations now show the full active MCQ question and choices during the answer step

### Energy / duration cap
Work and study duration is capped at:
- **1 to 10 hours**

This keeps required energy consistent with the agent’s `[0,100]` energy bound.

### Pay model (work)
\[
\text{pay} = \text{hourly\_wage} \cdot \text{hours} \cdot \frac{\text{market\_price}}{100}
\]

Half pay if incorrect.

### Education model
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
- hard clamp to a sane range

Orders placed when closed are queued.

---

## 13) Taxes

A midnight tax is applied, but low-cash agents are exempt:
- if money < `TAX_EXEMPT_BELOW_CASH` (currently 200): no tax
- else: subtract `TAX_AMOUNT`

This prevents immediate negative spirals for poor agents, such as students.

---

## 14) Economy / shopping rules

### Food
Food can be bought abstractly from village stock from anywhere, if:
- in stock
- affordable

This supports emergency survival and simpler baseline behavior.

### Non-food items
Everyday and health items require being:
- **inside** `Store_A` or `Store_B`

### Vehicles
Vehicles require being:
- **inside** `Vehicle_Dealership`

### Housing
Homes are still purchased via `buy_item` if the agent can afford the upgrade.

---

## 15) Corpse estates / auto-loot

When an agent dies:
- their shares are liquidated
- their inventory and money become a corpse estate at the death location
- nearby living agents can automatically recover estate loot and cash when close enough

This is implemented through:
- death handling in `python/tooling/death.py`
- auto-loot handling in `python/tooling/handlers/inventory_loot.py`

Agents do **not** manually search corpse items one-by-one.

---

## 16) Logging (research-friendly, non-exploding)

By default, logs store:
- pre/post state snapshots
- tool name/args/result
- prompt hash + char count
- summarized message previews

To log full prompts/messages:
```bash
LOG_FULL_MESSAGES=1 python python/sim.py
```

This exists because logging full prompt+history every turn causes massive disk usage.

---

## 17) Notes on prompt design

The per-turn observation is intentionally compact and action-biased. It includes:
- real calendar date/time
- current location and coordinates
- nearby people
- visible objects
- nearby entrances
- nearby public location open/closed info
- key needs/state
- held item / inventory count
- market line
- task hint / question if active
- last tool result
- notifications

The model may “think” inside `<think>...</think>`, but it must output exactly one tool call.

---

## 18) Contributing

Open source contributions are welcome.

Good contribution candidates include:
- new locations
- better scenario pools
- improved prompt compactness
- stricter tool parsing
- richer economic/social rules
- bug fixes in movement, inventory, or world consistency
- better logging/analysis tooling

Please keep contributions aligned with the project’s core constraint:
- agents must remain **grounded**
- tools should remain **enforceable**
- behavior should remain **research-auditable**

---

## 19) Acknowledgements

AgentSim-R is built in the open, and open source contributions are appreciated.

Acknowledgements:
- Thanks to everyone who contributes code, bug reports, ideas, testing feedback, scenario content, documentation, and simulation-design improvements.
- Thanks to the open-source tooling ecosystem that makes local inference, prompt templating, and experimentation practical.
- Thanks in advance to future contributors helping improve realism, consistency, and research usefulness across the project.

If your contribution meaningfully improves AgentSim-R, it may be merged and reflected in the evolving project history.

---

## 20) License

Modified MIT License. See `LICENSE`.