# AgentSim-R — Agent Simulation (Research)

AgentSim-R is a synthetic “imaginary world” simulation of multiple LLM-driven agents acting under explicit constraints: **time, money, energy, hunger, hydration, open hours, proximity, inventory limits, and inventory/hand state**. The goal is to study **emergent behavior** (economic, social, and survival dynamics) when agents must make grounded decisions in a shared environment.

This is not freeform roleplay. Agents must choose **one concrete action per turn** via tool calls, and the environment enforces hard constraints.

> [!NOTE]
> **Summary**: This project aims to observe *emergent behavior* when multiple LLM agents interact with a shared environment under enforceable constraints (movement, money, needs, schedules, and tool contracts). It is designed to be research-auditable rather than “creative RP”.

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
- Generation settings are set in `python/prompting.py` (`temperature`, `top_p`, `repeat_penalty`, etc.).

### Run
From repo root:
```bash
python python/sim.py
```

### Prompt extraction / debugging
To dump the full rendered prompt for every starting agent:
```bash
python extract_t1.py
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

Stable import paths + modular internals:

- `python/tools.py`: facade re-exporting tool execution + catalogs from modular code
- `python/utils.py`: facade re-exporting prompting + server call functions
- `python/prompting.py`: observation prompt builder + llama-server request + slot save/restore
- `python/core.py`: time/date utilities + market-hours logic

Tool engine:
- `python/tooling/execute.py`: dispatcher + registry
- `python/tooling/parsing.py`: XML tool-call parser
- `python/tooling/catalogs.py`: item + vehicle catalogs + workplace mappings
- `python/tooling/navigation.py`: shortest-route distance (A* on coarse road grid)
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

### Open-air locations
For **open-air locations** (parks, lakes, squares):
- `move_to` places the agent **directly there**
- no separate outside-door step

### Home aliases
Agents should use friendly home aliases such as:
- `Home_Alex`
- `Home_Taylor`

They should not use internal location IDs like:
- `SmallApartment_Maple_Unit_1_Floor_1`

### Simulation date/time
The simulation uses a real calendar start date:
- **Monday, 30-03-2026 08:00**

Prompts/logs use real date formatting.

---

## 6) Scheduling model (parallel-by-busy_until)

Simulation is event-driven:
- each agent has `busy_until`
- the scheduler always picks the next available agent (smallest `busy_until`)
- passive “hourly ticks” are applied whenever simulated time advances

This approximates parallel action: one agent can be busy for hours while others continue acting.

---

## 7) Movement + pathing (shortest-route distance)

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
$$
d = d_{tail} + d_{grid} + d_{head}
$$

Implemented in `python/tooling/navigation.py`.

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
- If an agent cannot afford fuel, movement falls back to walking (with a notification)

Vehicle parameters live in `python/tooling/catalogs.py`.

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
- plus money, wage, inventory, holdings, vehicle state, pending tasks, queued orders, voicemail, etc.

Prompts surface a compact but useful subset, including:
- real date/time
- health/hunger/energy/hydration/stress/happiness
- nearby people, visible objects
- nearby location open/closed status
- active task details
- inventory count
- voicemail preview
- notifications (drip-fed)

---

## 10) Passive dynamics (math models)

Passive updates occur once per simulated hour (`PASSIVE_TICK_SECONDS = 3600`).

### 10.1 Happiness model
Relationships are scaled:
$$
R_{scaled} = \min\left(100,\; \frac{\text{relationships}}{5}\cdot 100\right)
$$

Happiness target:
$$
H^* = 0.3\cdot \text{health} \;+\; 0.3\cdot R_{scaled} \;+\; 0.4\cdot 100 \cdot \tanh\!\left(\frac{\text{money}}{\text{expenses} + \varepsilon}\right)
$$
with \(\varepsilon = 1\).

Update:
$$
\text{happiness}_{t+1} = \mathrm{clamp}_{0,100}\Big(0.7\cdot \text{happiness}_t + 0.3\cdot H^*\Big)
$$

### 10.2 Stress model
Relationship tension components:
$$
\text{loneliness} = \max(0, 3-\text{relationships})^2
$$
$$
\text{crowding} = \max(0, \text{relationships}-10)\cdot 2
$$
$$
\text{rel\_tension} = w_1(\text{loneliness}+\text{crowding})
$$
where \(w_1=1\).

Financial pressure:
$$
\text{fin\_pressure} = w_2 \cdot \frac{\text{expenses}}{\max(0,\text{money}) + 1}
$$
where \(w_2=2\).

Market anxiety (only when shares owned and price drops):
$$
\text{market\_anxiety} \propto w_3 \cdot |\Delta P| \cdot \frac{\text{position\_value}}{\max(0,\text{money})+1}
$$
with \(w_3=0.5\).

Base stress target:
$$
\Psi^* = \frac{\text{rel\_tension} + \text{fin\_pressure} + \text{market\_anxiety}}
{1 + \alpha\cdot \text{happiness} + \beta\cdot \text{hourly\_wage}}
$$
where \(\alpha=0.01,\; \beta=0.001\).

Hydration scaling:
- if hydration < 30: \(\Psi^* \leftarrow 1.1\Psi^*\)
- if hydration < 15: \(\Psi^* \leftarrow 1.25\Psi^*\)

Debt penalty:
- if money < 0: multiply by 1.5

Update:
$$
\text{stress}_{t+1} = \mathrm{clamp}_{0,100}\Big(0.7\cdot \text{stress}_t + 0.3\cdot \Psi^*\cdot \text{debt\_penalty}\Big)
$$

### 10.3 Health model
Age factor:
$$
A = e^{0.02\cdot \text{age}}
$$

Energy penalty:
- 0 if energy > 10
- 0.5 otherwise

Dehydration penalty:
$$
D =
\begin{cases}
(20-\text{hydration})\cdot 0.2 & \text{if hydration}<20 \\
0 & \text{otherwise}
\end{cases}
$$

Health delta:
$$
\Delta \text{health} =
\Big(
-\big(0.5\cdot \text{stress} + 0.3\cdot \text{hunger} + 10\cdot \text{energy\_penalty} + D\big)
+ 0.1\cdot \text{happiness}
\Big)\cdot A \cdot 0.02
$$

Update:
$$
\text{health}_{t+1} = \mathrm{clamp}_{0,100}(\text{health}_t + \Delta\text{health})
$$

Starvation damage (if hunger = 100 for consecutive hours):
$$
\text{health} \leftarrow \text{health} - \min(32,\; 2^{h})
$$

Dehydration damage (if hydration = 0 for consecutive hours):
$$
\text{health} \leftarrow \text{health} - \min(16,\; 1.5^{d})
$$

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
- Scenario pools are role-specific with >= 30 unique scenarios per role
- Observation shows the active MCQ question and choices during the answer step

### Energy / duration cap
Work and study duration is capped:
- **1 to 10 hours**

### Pay model (work)
$$
\text{pay} = \text{hourly\_wage} \cdot \text{hours} \cdot \frac{\text{market\_price}}{100}
$$
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
$$
P_{t+1} = P_t \cdot \exp\Big((\mu-\tfrac{1}{2}\sigma^2) + \sigma \epsilon_t\Big)\cdot \text{impact}
$$

Impact is based on net volume that hour; invalid prices reset to 100 and prices are clamped.

Orders placed when closed are queued and executed during open hours.

---

## 13) Taxes

A midnight tax is applied, but low-cash agents are exempt:
- if money < `TAX_EXEMPT_BELOW_CASH` (200): no tax
- else: subtract `TAX_AMOUNT`

---

## 14) Economy / shopping rules

### Food
Food can be bought abstractly from village stock from anywhere, if:
- in stock
- affordable

### Non-food items
Everyday and health items require being:
- **inside** `Store_A` or `Store_B`

### Vehicles
Vehicles require being:
- **inside** `Vehicle_Dealership`

### Housing
Homes are purchased via `buy_item` if the agent can afford the upgrade.

---

## 15) Corpse estates / auto-loot

When an agent dies:
- their shares are liquidated
- their inventory and money become a corpse estate at the death location
- nearby living agents can automatically recover estate loot when close enough

Agents do **not** manually loot corpse items one-by-one.

---

## 16) Social: voicemail + missed-interaction + queued delivery

Social actions obey availability rules:
- If a call target is busy/sleeping, the call goes to **voicemail**, stored persistently on the recipient (shown in observations).
- If an in-person interaction target is busy/sleeping, the target receives a **missed interaction** notification.
- `give_item` / `give_money` can be **queued** if recipient is busy/sleeping (escrowed immediately), then delivered when the recipient becomes available.
- If queued item delivery would arrive but recipient inventory is full, delivery is cancelled and returned to sender (or dropped at sender in rare full-inventory edge cases).

---

## 17) Logging

Logs are JSONL (one JSON object per line) and include:
- pre/post agent state snapshots
- tool name/args/result
- prompt hash + char count
- structured `system_prompt` + last `user_observation` (plus optional full messages)

To store full prompt/messages:
```bash
LOG_FULL_MESSAGES=1 python python/sim.py
```

---

## 18) Tools (current)
Tools are defined in `tools.json` and implemented in `python/tooling/handlers/*`.

Current tool list:
- `talk_to(person, message)`
- `call_person(person, message)`
- `change_status(person, type, value)`
- `give_item(person, item)`
- `give_money(person, amount)`
- `attack_person(person)`
- `move_to(place)`
- `walk(direction)`
- `buy_item(item)`
- `eat_food(item)`
- `sleep(hours)`
- `do_hobby(item)`
- `work_job(jobname, hours)`
- `get_education(type, hours)`
- `seek_medicalcare()`
- `interact_with(person_or_object, action)`
- `pick_item(item_name)`
- `hold_item(item_name)`
- `drop_item(item_name)`
- `buy_stock(shares)`
- `sell_stock(shares)`

---

## 19) Phase 1 starting agents

Default initialization (see `python/sim.py`):
| Name | Role | Age | Hourly Wage | Starting Cash | Starting Home Type |
|------|------|-----|-------------|---------------|--------------------|
| Alex | developer | 28 | $50 | $5000 | Small Apartment |
| Jamie | nurse | 35 | $60 | $6000 | Apartment |
| Taylor | student | 21 | $20 | $20 | Small Apartment |
| Jordan | delivery driver | 39 | $20 | $2000 | Apartment |
| Mia | teacher | 41 | $35 | $3500 | House |
| Ethan | founder | 30 | $100 | $10000 | Luxury House |

Homes are allocated from vacant lots; initialization prefers floor-1 homes when available.

---

## 20) License
MIT License. See `LICENSE`.