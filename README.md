# AgentSim-R — Agent Simulation (Research)

AgentSim-R is a synthetic "imaginary world" simulation of multiple LLM-driven agents acting under explicit constraints: **time, money, energy, hunger, hydration, open hours, proximity, inventory limits, and inventory/hand state**. The goal is to study **emergent behavior** (economic, social, and survival dynamics) when agents must make grounded decisions in a shared environment.

This is not freeform roleplay. Agents must choose **one concrete action per turn** via tool calls, and the environment enforces hard constraints.

> [!NOTE]
> **Summary**: This project is aimed at observing *emergent behavior* when multiple agents interact in a shared environment with enforceable rules. It is designed to be research-auditable and grounded, not "creative RP".

---

## 1) Technical setup

### Model / inference
AgentSim-R expects a local `llama-server` compatible endpoint.

Example:

```bash
llama-server -m /path/to/model.gguf -c 262144 --parallel 1 --slot-save-path ./cache
````

Key points:

* Context is configured for large windows (`CONTEXT_SIZE=262144` in `python/config.py`).
* **Per-agent slot save/restore** is enabled using `cache/agent_{id}.bin`.
* Generation settings are configured in `python/prompting.py` (`temperature`, `top_p`, `repeat_penalty`, etc.).

### Install

```bash
pip install -r requirements.txt
```

### Run

From repo root:

```bash
python python/sim.py
```

### Prompt extraction / debugging

To dump the fully rendered prompt for each starting agent:

```bash
python extract_t1.py
```

This writes to:

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

**No text is allowed after `</tool_call>`.**

Tool schemas are described in `tools.json` and enforced by the engine.

Important contract notes:

* `move_to` accepts **named places only**, such as `Library`, `Store_A`, `Startup_Sowl`, or `Home_Taylor`.
* Coordinates shown in observations are **read-only telemetry** and are never valid tool inputs.
* The engine tolerates loose name variants, e.g. `Startup Sowl` → `Startup_Sowl`.
* Roofed-building rule: `move_to(place=...)` takes you to the **outside entrance area**; use `walk` to enter.
* Corpse estate loot is automatic when close enough; do not manually loot item-by-item.

---

## 3) Determinism note (research honesty)

* The simulation logic is largely deterministic given a fixed seed (movement graph, passive updates, scenario selection constraints, etc.).
* **Overall runs are not guaranteed deterministic** because LLM sampling depends on inference server behavior and generation randomness unless your server is configured to be fully deterministic.
* Slot/KV cache loss does **not** erase simulation memory; the source of truth is still Python-side prompt state (`system_prompt`, `chat_history`, and current world state). Cache loss mainly affects speed.

---

## 4) Repository layout (modularized)

Stable import paths + modular internals:

* `python/tools.py`: facade re-exporting tool execution + catalogs
* `python/utils.py`: facade re-exporting prompting + server call functions
* `python/prompting.py`: compact observation prompt builder + llama-server call + slot save/restore
* `python/core.py`: time/date utilities + market-hours logic

Tool engine:

* `python/tooling/execute.py`: dispatcher + registry
* `python/tooling/parsing.py`: XML tool-call parser
* `python/tooling/catalogs.py`: item + vehicle catalogs + workplace mappings
* `python/tooling/navigation.py`: shortest-route distance on a coarse road grid (A*)
* `python/tooling/scenarios.py`: scenario pools with recency control
* `python/tooling/helpers.py`: canonicalization, reachability, busy checks, etc.
* `python/tooling/death.py`: death/estate logic
* `python/tooling/handlers/*.py`: domain handlers

---

## 5) World model (imaginary world, hardcoded boundaries)

The village is a continuous coordinate plane (`0..5000m` on both x and y), with hardcoded 3D location boxes (buildings, parks, outdoor spaces, homes, and interactables).

Primary files:

* Locations + bounding boxes: `python/locations.py`
* Each location has an entrance point
* Agents are either "Outside" or inside a location box

Public locations include:

* `Hospital`, `School`, `Office_FedEx`, `Startup_Sowl`
* `Store_A`, `Store_B`, `Market`
* `Park_Central`, `Cafe`, `Library`, `Gym`, `Village_Square`
* `Farm`, `Mall`, `Lake`, `Vehicle_Dealership`

### Home aliases

Agents should use home aliases:

* `Home_Alex`, `Home_Taylor`, etc.

Agents should not use internal location IDs like:

* `SmallApartment_Maple_Unit_1_Floor_1`

### Simulation date/time

The simulation starts on:

* **Monday, 30-03-2026 08:00**

Prompts/logs use real date formatting.

---

## 6) Scheduling model (parallel-by-busy_until)

The simulation is event-driven:

* each agent has a `busy_until` timestamp
* the scheduler always picks the next available agent
* passive "hourly ticks" apply when simulated time advances

This approximates parallel action: one agent can be busy for hours while others continue acting.

---

## 7) Movement + pathing (Python DSA, shortest-route)

Movement distance is computed with an infrastructure-aware approximation:

* a coarse road grid over the $5\text{km} \times 5\text{km}$ plane
* shortest path via **A*** on a 4-neighbor grid
* connector distance from real coordinates to nearest road nodes

Let:

* grid spacing be $s = 250$ meters
* $d_{\text{tail}}$ be distance from start to nearest road node
* $d_{\text{grid}}$ be $A^*$ path length on the road grid
* $d_{\text{head}}$ be distance from destination road node to destination point

Then:

$$
d = d_{\text{tail}} + d_{\text{grid}} + d_{\text{head}}
$$

Implemented in `python/tooling/navigation.py`.

---

## 8) Vehicles (asset-based, fuel-per-km)

Agents have a **vehicle asset** (default: Scooter). Vehicles are not inventory items.

Rules:

* ride only if within **100m** of the parked vehicle
* time cost depends on vehicle speed and route distance
* fuel cost is simplified as **$ per km**
* if fuel is unaffordable, movement falls back to walking (a notification is generated)

Vehicle parameters live in `python/tooling/catalogs.py`.

---

## 9) Core state variables (bounded)

Key numeric state (bounded unless noted):

* `health` ∈ [0, 100]
* `energy` ∈ [0, 100]
* `hydration` ∈ [0, 100]
* `hunger` ∈ [0, 100]
* `stress` ∈ [0, 100]
* `happiness` ∈ [0, 100]
* `education` ∈ [0, 100]
* `relationships` ∈ [0, 25]
* `money` (float; can go negative in some scenarios)
* `hourly_wage`, `expenses`, `inventory`, `held item`, etc.

The prompt surfaces a compact subset including:

* time/date
* location + "inside/outside"
* needs + money
* nearby people + visible objects
* nearby open/closed info
* task instructions (if active)
* voicemail summary
* notifications (drip-fed)

---

## 10) Passive dynamics (math models)

Passive updates occur once per simulated hour.

### 10.1 Happiness model

Relationships scaling:

$$
R_{\text{scaled}} = \min!\left(100,; \frac{\text{relationships}}{5}\cdot 100\right)
$$

Happiness target:

$$
H^* = 0.3\cdot \text{health} + 0.3\cdot R_{\text{scaled}} + 0.4\cdot 100 \cdot \tanh!\left(\frac{\text{money}}{\text{expenses} + \varepsilon}\right)
$$

with $\varepsilon = 1$.

Update:

$$
\text{happiness}*{t+1} = \mathrm{clamp}*{[0,100]}!\left(0.7\cdot \text{happiness}_t + 0.3\cdot H^*\right)
$$

#### 10.2 Stress model

Relationship tension components:
$$
\text{loneliness} = \max(0, 3 - \text{relationships})^2
$$
$$
\text{crowding} = \max(0, \text{relationships} - 10) \cdot 2
$$
$$
\text{rel}_{\text{tension}} = w_1 (\text{loneliness} + \text{crowding}) \quad \text{where } w_1 = 1
$$

Financial pressure:
$$
\text{fin}_{\text{pressure}} = w_2 \cdot \frac{\text{expenses}}{\max(0, \text{money}) + 1} \quad \text{where } w_2 = 2
$$

Market anxiety (only when shares are owned and price drops):
$$
\text{market}_{\text{anxiety}} \propto w_3 \cdot |\Delta P| \cdot \frac{\text{position_value}}{\max(0, \text{money}) + 1} \quad \text{where } w_3 = 0.5
$$

Base stress target:
$$
\Psi^* = \frac{\text{rel}_{\text{tension}} + \text{fin}_{\text{pressure}} + \text{market}_{\text{anxiety}}}{1 + \alpha \cdot \text{happiness} + \beta \cdot \text{hourly_wage}}
$$
where $\alpha = 0.01$, $\beta = 0.001$.

Hydration scaling (only when awake):
- if hydration < 30: $\Psi^* \leftarrow 1.1 \Psi^*$
- if hydration < 15: $\Psi^* \leftarrow 1.25 \Psi^*$

Debt penalty:
- if money < 0: multiply stress target by 1.5

Update:
$$
\text{stress}_{t+1} = \mathrm{clamp}_{[0,100]}\left(0.7 \cdot \text{stress}_t + 0.3 \cdot \Psi^* \cdot \text{debt_penalty}\right)
$$

### 10.3 Health model

Age factor:

$$
A = e^{0.02\cdot \text{age}}
$$

Energy penalty:

* `0` if energy > 10
* `0.5` otherwise

Dehydration penalty:

$$
D =
\begin{cases}
(20-\text{hydration})\cdot 0.2 & \text{if hydration} < 20 \
0 & \text{otherwise}
\end{cases}
$$

Health delta:

$$
\Delta \text{health}$$
====================   
$$
\Big(
-\big(0.5\cdot \text{stress} + 0.3\cdot \text{hunger} + 10\cdot \text{energy_penalty} + D\big)

* 0.1\cdot \text{happiness}
  \Big)\cdot A \cdot 0.02
  $$

Update:

$$
\text{health}*{t+1} = \mathrm{clamp}*{[0,100]}!\left(\text{health}_t + \Delta\text{health}\right)
$$

Starvation damage (if hunger = 100 for consecutive hours):

$$
\text{health} \leftarrow \text{health} - \min(32,; 2^{h})
$$

Dehydration damage (if hydration = 0 for consecutive hours):

$$
\text{health} \leftarrow \text{health} - \min(16,; 1.5^{d})
$$

If health ≤ 0: agent dies and becomes a lootable estate.

### 10.4 Hunger / hydration drift + emergency auto-consumption

Per simulated hour:

* hunger increases by:

  * $+5$ if awake
  * $+0.5$ if sleeping
* hydration decreases by:

  * $-4$ if awake
  * $-1.5$ if sleeping
* energy decreases by:

  * $-2$ if awake

Emergency triggers:

* if awake and hunger ≥ 90 → attempt emergency consume/buy
* if awake and hydration ≤ 12 → attempt emergency drink/buy

---

## 11) Work + education tasks (anti-farming)

Work/study are multi-step tasks:

1. initiate (`work_job` / `get_education`)
2. `pick_item` required task prop
3. `interact_with` MCQ answer (`A` / `B` / `C`)

Rules:

* must be **inside** the correct building to start
* task steps are locked: unrelated tools are blocked mid-task
* after 3 failures, the task cancels
* scenario pools are role-specific (>= 30 unique scenarios per role)

#### Energy / duration cap

Work and study duration is capped:
- 1 to 10 hours

#### Pay model (work)

$$
\text{pay} = \text{hourly_wage} \cdot \text{hours} \cdot \frac{\text{market_price}}{100}
$$

Half pay if incorrect.

#### Education model

- education +5 and wage +5 if correct
- education +1 and wage +1 if incorrect
- tuition charged up front:
  - baseline 2000
  - masters 4000
  - phd 8000
- student discount caps tuition at 150

---

## 12) Stock market model

Market open:

* Mon–Fri 09:30–16:00

Price updates hourly during open hours:

$$
P_{t+1} = P_t \cdot \exp!\Big((\mu-\tfrac{1}{2}\sigma^2) + \sigma \epsilon_t\Big)\cdot \text{impact}
$$

Impact is based on net volume that hour; prices are clamped to a sane range.

Orders placed when closed are queued and executed during open hours.

---

## 13) Taxes

A midnight tax is applied, but low-cash agents are exempt:

* if money < `TAX_EXEMPT_BELOW_CASH` (200): no tax
* else: subtract `TAX_AMOUNT`

---

## 14) Social: voicemail + missed interactions + queued delivery

Social rules:

* `call_person`: if target is busy or sleeping → call goes to **voicemail** (persisted). Otherwise the target gets a real-time call notification.
* `talk_to`: if target is busy/sleeping → initiator fails but target receives a **missed interaction** notification.
* `give_item` / `give_money`: if target is busy/sleeping → transfer is **queued** and escrowed immediately, then delivered once the target becomes available.

  * If queued item delivery arrives but recipient inventory is full → delivery cancels and returns to sender (or drops at sender in rare full-inventory edge cases).

---

## 15) Notifications (drip-fed)

Notifications can accumulate while an agent is busy. To keep prompts usable:

* only a limited number of notifications are shown per turn
* the rest remain queued and a count is shown: "Queued notifications remaining: N"

---

## 16) Logging

Logs are JSONL (one JSON object per line) and include:

* pre/post agent state snapshots
* tool name/args/result
* prompt hash + prompt char count
* structured `system_prompt` + `user_observation` fields
* optional full messages via `LOG_FULL_MESSAGES=1`

Enable full prompt/messages logging:

```bash
LOG_FULL_MESSAGES=1 python python/sim.py
```

---

## 17) Tools

Tools are defined in `tools.json` and enforced by the engine. Current set includes:

* `talk_to(person, message)`
* `call_person(person, message)`
* `change_status(person, type, value)`  (belief update or relationship request/accept)
* `give_item(person, item)`
* `give_money(person, amount)`
* `attack_person(person)`
* `move_to(place)`
* `walk(direction)`
* `buy_item(item)`
* `eat_food(item)`
* `sleep(hours)`
* `do_hobby(item)`
* `work_job(jobname, hours)`
* `get_education(type, hours)`
* `seek_medicalcare()`
* `interact_with(person_or_object, action)`
* `pick_item(item_name)`
* `hold_item(item_name)`
* `drop_item(item_name)`
* `buy_stock(shares)`
* `sell_stock(shares)`

---

## 18) Phase 1 starting agents

Default initialization (see `python/sim.py`):

| Name   | Role            | Age | Hourly Wage | Starting Cash | Home Type       |
| ------ | --------------- | --- | ----------- | ------------- | --------------- |
| Alex   | developer       | 28  | $50         | $5000         | Small Apartment |
| Jamie  | nurse           | 35  | $60         | $6000         | Apartment       |
| Taylor | student         | 21  | $20         | $20           | Small Apartment |
| Jordan | delivery driver | 39  | $20         | $2000         | Apartment       |
| Mia    | teacher         | 41  | $35         | $3500         | House           |
| Ethan  | founder         | 30  | $100        | $10000        | Luxury House    |

Homes are allocated from vacant lots; initialization prefers floor-1 homes when available.

---

## 19) License

**Modified MIT** License. See `LICENSE`.