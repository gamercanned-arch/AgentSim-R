# AgentSim-R - Agent Simulation (Research)

## Overview

AgentSim-R is a village-scale, agent-based simulation framework where language-model agents act under explicit constraints: time, money, energy, health, proximity, open hours, inventory limits, and world state.

The goal is not pure freeform roleplay. The goal is to observe emergent social, economic, and behavioral patterns when agents are forced to make grounded decisions in a shared environment.

Key properties:

- **Event-driven simulation** via per-agent `busy_until`
- **Explicit world geometry** with 3D locations and interactables
- **Finite inventory and finite village stock**
- **Health, hunger, energy, stress, happiness, education, and relationship dynamics**
- **Multi-step work/study tasks**
- **Rolling memory summarization** to preserve long-term context
- **Stock market with market hours, queued orders, and trade impact**
- **Detailed per-turn logging of model inputs and outputs**

---

## Important note on determinism

The Python-side simulation uses seeded randomness where applicable, but the overall system is **not guaranteed deterministic across runs** because model generation depends on the external inference server and sampling settings.

So:

- Python/NumPy randomness is seeded
- simulation logic is rule-based
- but LLM outputs may still vary between runs unless your inference stack is configured for deterministic generation

---

## Repository structure

```text
/prompts
  alex.txt
  common_prompt.txt
  ethan.txt
  jamie.txt
  jordan.txt
  mia.txt
  taylor.txt
  template.jinja

/python
  __init__.py
  config.py
  locations.py
  logger.py
  scheduler.py
  sim.py
  state.py
  tools.py
  utils.py

tools.json
README.md
requirements.txt
```

---

## Running the simulation

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Start `llama-server`

Example:

```bash
llama-server -m /path/to/model.gguf -c 131072 --parallel 1 --slot-save-path ./cache
```

Adjust flags and paths as needed for your system and hardware.

### 3. Run the simulation

Preferred command from repo root:

```bash
python python/sim.py
```

Equivalent alternative:

```bash
cd python
python sim.py
```

---

## Prompting and tool-call format

The simulation uses **XML-only** tool calling.

Agents must return exactly one tool call in this format:

```xml
<tool_call>
<function=tool_name>
<parameter=param_name>
value
</parameter>
</function>
</tool_call>
```

JSON-in-tag tool calls are **not supported**.

Prompt construction uses:

1. `prompts/common_prompt.txt`
2. persona prompt, e.g. `prompts/alex.txt`
3. dynamic simulation rules
4. rolling memory summary, when available

---

## Simulation architecture

The simulation is event-driven.

Each agent has a `busy_until` timestamp. At each scheduler step:

1. the next available alive agent is selected
2. passive hourly world updates are applied as time advances
3. a prompt is built for that agent
4. the LLM emits exactly one tool call
5. the tool is executed
6. the tool’s time cost advances that agent’s schedule

This means agents operate conceptually in parallel, even though execution is serialized through the scheduler.

---

## World model

The village is a continuous 3D coordinate space.

### Location types

- public institutions and social areas:
  - Hospital
  - School
  - Office_FedEx
  - Startup_Sowl
  - Store_A
  - Store_B
  - Market
  - Park_Central
  - Cafe
  - Library
  - Gym
  - Village_Square

- real purchasable home lots:
  - Small Apartment lots
  - Apartment units with floor assignments
  - House lots
  - Luxury House estates

Each agent also has a human-facing home alias:

- `Home_Alex`
- `Home_Jamie`
- etc.

These aliases resolve to the agent’s **currently assigned physical home lot**.

So buying a new home changes where `move_to(home)` actually goes.

---

## Open hours and access rules

Many places enforce open/closed hours.

Additionally:

- `work_job` requires being near the correct workplace
- `get_education` requires being near School or Library
- `seek_medicalcare` requires being near Hospital
- `change_status` requires being near the target person

If a requested work or study duration would extend past closing time, the action fails with feedback telling the agent to choose a shorter duration.

### Current workplace mapping

- Alex / developer / tech / startup / founder -> `Startup_Sowl`
- Jamie / nurse / doctor -> `Hospital`
- Jordan / delivery / driver / fedex -> `Office_FedEx`
- Mia / teacher / tutor -> `School`
- Ethan / founder / startup -> `Startup_Sowl`

---

## Purchasing model

Item buying is intentionally **abstract village-wide purchasing**, not store-location gated.

That means:

- `buy_item` does **not** require being physically inside a store
- `eat_food` may buy food directly from village stock if not already held/in inventory

However, purchases still obey:

- village stock limits
- affordability
- inventory capacity
- item existence

All spending updates both:

- `expenses` (rolling recent spending memory)
- `total_expenses` (lifetime accumulated spending)

Taxes are also counted as expenses.

---

## Core agent state

Each agent maintains explicit state such as:

- `health`
- `energy`
- `hunger`
- `stress`
- `happiness`
- `education`
- `relationships`
- `relationships_status`
- `relationship_partner`
- `money`
- `expenses`
- `total_expenses`
- `hourly_wage`
- `shares_owned`
- `inventory`
- `currently_holding`
- `beliefs`
- `home_location`
- `current_home_type`
- `task_state`
- `current_activity`
- `is_sleeping`

---

## Main formulas

### Happiness

Happiness is updated passively using health, relationship strength, and financial comfort:

```text
rel_scaled = min(100, (relationships / 5) * 100)

happiness_target =
    0.3 * health
  + 0.3 * rel_scaled
  + 0.4 * 100 * tanh(money / (expenses + eps))

happiness_next = clamp(0, 100, 0.7 * happiness + 0.3 * happiness_target)
```

### Stress

Stress uses relationship tension, financial pressure, and market anxiety:

```text
loneliness = max(0, 3 - relationships)^2
crowding   = max(0, relationships - 10) * 2
rel_tension = loneliness + crowding

fin_pressure = 2 * (expenses / (max(0, money) + 1))

market_anxiety depends on:
- owned shares
- recent negative price movement
- current position value

stress_target =
    (rel_tension + fin_pressure + market_anxiety)
    / (1 + 0.01 * happiness + 0.001 * hourly_wage)

stress_next = clamp(0, 100, 0.7 * stress + 0.3 * stress_target * debt_penalty)
```

### Health

Health changes passively as a function of stress, hunger, energy pressure, happiness, and age:

```text
delta_health =
    (-(0.5 * stress + 0.3 * hunger + energy_penalty * 10) + 0.1 * happiness)
    * exp(0.02 * age)
    * 0.02
```

If hunger reaches 100, starvation damage escalates over time.

---

## Sleep and availability

Sleep is explicit.

Sleeping agents:

- recover energy
- reduce stress
- are marked as Do Not Disturb
- cannot be talked to, called successfully, attacked, or made to overhear conversations
- do not gain `awake_hours` while sleeping
- do not suffer the normal passive energy drain while sleeping

Sleeping outside home is weaker than sleeping at home:

- outside sleep recovery is capped
- but it will not reduce already-high energy

---

## Relationships

The social model is intentionally lightweight.

- `relationships` is a scalar used by the happiness/stress formulas
- social actions slightly improve it
- hostile actions can reduce it
- `relationships_status` stores labels like `single` or `dating`
- `relationship_partner` stores who that status refers to

This is simpler than a full per-person sentiment graph, but more meaningful than a single global status string alone.

---

## Work and education system

`work_job` and `get_education` are interactive multi-step tasks.

### Flow

1. start the task
2. use `pick_item` to grab the required scenario prop
3. use `interact_with` to answer the scenario

### Task rules

- agents cannot perform unrelated actions mid-task
- failed mid-task steps still consume time
- after 3 failed attempts, the task is cancelled
- temporary task props do not destroy real held items
- if hands are full and inventory is full, the agent is told to drop something

### Education

`get_education`:

- checks proximity to School or Library
- checks institution open hours
- checks that requested duration fits before closing
- charges tuition before the study task begins
- raises education and wage on completion

Supported tuition tiers:

- default education: $2000
- master's: $4000
- PhD / doctorate: $8000

---

## Inventory, holding, and ground items

Agents have:

- a limited inventory
- one currently held item

### `pick_item`

Can pick up from:

- inventory
- nearby dropped ground items
- nearby corpse loot

### `drop_item`

Drops a held or named inventory item onto the ground.

Rules:

- the dropper cannot re-pick the same dropped item for 1 hour
- another agent may pick it up earlier
- if someone else picks it up, the original dropper is notified

---

## Hobby system

Agents can use `do_hobby` with valid hobby items such as:

- `Book`
- `Art Supplies`
- `Notebook`

This reduces stress and increases happiness.

It works with both:

- held items
- items in inventory

Invalid items are rejected.

---

## Food and item realism

`eat_food` only works on actual food items.

Agents cannot eat arbitrary non-food items.

Food can be:

- consumed from hand
- consumed from inventory
- bought directly from village stock if available

Spoilage is modeled for old stored food.

---

## Movement and interaction rules

### `move_to`

- uses distance-based travel time
- drains energy based on distance
- respects open hours
- respects locked-home access rules

### `walk`

- moves 30m in the requested direction
- respects open hours when stepping into buildings
- prevents invalid “walk off the building” transitions from elevated positions

### `interact_with`

- supports person or object interaction
- object interaction requires:
  - same location
  - same floor / Z level tolerance
- nonexistent objects fail instead of silently succeeding

---

## Person-to-person interaction distances

Current hard limits:

| Tool | Distance |
|------|----------|
| `talk_to` | 50m |
| `interact_with` (person) | 20m |
| `attack_person` | 20m |
| `change_status` | 30m |
| `give_item` | 20m |
| `give_money` | 20m |
| `work_job` workplace proximity | 150m |
| `get_education` proximity | 150m |
| `seek_medicalcare` proximity | 150m |

---

## Market system

The stock market is only open on:

- **Monday-Friday**
- **09:30-16:00**

### Price model

While the market is open, price updates use:

- geometric Brownian motion
- trade-flow impact based on net volume that period

### Orders

- buys/sells placed while closed are queued
- queued orders execute during market-open processing
- cost basis is updated correctly on queued buys
- `last_known_price` resets correctly when a position is fully sold

### Death and shares

If an agent dies while holding shares:

- their shares are liquidated at the current market price
- proceeds are added to the estate/corpse loot

---

## Death, corpse loot, and estate behavior

When an agent dies:

- they stop acting
- they stop paying tax
- they stop processing market orders
- their held non-task item is preserved into their estate
- their stock position is liquidated into cash
- their cache file is no longer needed
- a corpse/estate record is left at the death location

### Loot behavior

Corpse loot persists until collected.

A living agent who comes within **300m** automatically scavenges:

- as many items as inventory capacity allows
- all available estate cash

Agents can also manually pick up corpse items at close range using `pick_item`.

---

## Housing system

Housing is both economic **and** spatial.

### Home tiers

- Small Apartment
- Apartment
- House
- Luxury House

### Purchase behavior

Buying a home:

- sells the current home at 70% of catalog value
- assigns a new vacant lot of the requested type
- changes the physical location of the agent’s home alias
- blocks re-buying the same home type
- fails if no vacant lot of that type exists

Apartment homes are real assigned units/floors, not just abstract labels.

---

## Rolling memory and context management

The system includes rolling summarization to control prompt growth.

### Policy

Before generating the **31st assistant response** for an agent:

- the oldest 20 completed action cycles are compressed
- the newest 10 cycles remain verbatim
- one evolving rolling summary is kept
- that summary is inserted into the **first system prompt**, not as a mid-history system message

If summarization fails, the simulation continues safely using fallback behavior.

A final context guard also stops the simulation if prompt growth becomes too large even after summarization.

---

## Logging

The simulation logs both inputs and outputs.

Per turn, logging includes:

- wall-clock timestamp
- simulation time
- notifications shown to the agent
- prompt/messages sent to the model
- raw model output
- parsed tool name and arguments
- tool result
- success/failure
- time cost
- pre-state snapshot
- post-state snapshot

Files are written under `logs/`, and logs/cache are cleaned at startup.

---

## Available tools

| Tool | Purpose |
|------|---------|
| `talk_to` | In-person conversation |
| `call_person` | Phone call |
| `interact_with` | Person/object interaction or task answer |
| `change_status` | Update beliefs/goals or relationship status |
| `attack_person` | Physical aggression |
| `move_to` | Travel to a named place |
| `walk` | Move locally by direction |
| `sleep` | Recover energy and become unavailable |
| `buy_item` | Buy item or home |
| `eat_food` | Eat held/inventory/stock food |
| `do_hobby` | Reduce stress using hobby items |
| `pick_item` | Hold an item or pick up nearby ground/corpse loot |
| `drop_item` | Drop a held or inventory item |
| `give_item` | Give an item to a nearby person |
| `give_money` | Give money to a nearby person |
| `work_job` | Begin interactive work task |
| `get_education` | Begin interactive study task |
| `seek_medicalcare` | Restore health near Hospital |
| `buy_stock` | Buy shares |
| `sell_stock` | Sell shares |

---

## Default starting agents

| Name | Role | Age | Wage | Starting Cash | Starting Home Type |
|------|------|-----|------|---------------|--------------------|
| Alex | Developer at Sowl | 28 | $50 | $5000 | Small Apartment |
| Jamie | Nurse | 35 | $60 | $6000 | Apartment |
| Taylor | Student | 21 | $20 | $20 | Small Apartment |
| Jordan | Delivery Driver | 39 | $20 | $2000 | Apartment |
| Mia | Teacher | 41 | $35 | $3500 | House |
| Ethan | Founder | 30 | $100 | $10000 | Luxury House |

Each is assigned a real physical home lot at startup.

---

## Notes for prompt and persona authors

Persona files live in `prompts/` and are loaded by lowercase agent filename, e.g.:

- `alex.txt`
- `jamie.txt`
- `mia.txt`

The common prompt is loaded from:

- `prompts/common_prompt.txt`

If you edit prompting behavior, keep the XML tool-call format consistent across:

- `common_prompt.txt`
- `tools.json`
- any future docs or examples

---

## Current design tradeoffs

A few things are intentionally simplified:

- purchasing is abstract rather than store-location-gated
- relationship modeling is scalar, not a full per-person social graph
- work/study scenarios use lightweight MCQ-style tasks
- market realism is partial, not institution-grade finance simulation

This is deliberate. The system prioritizes **consistent simulation constraints** and **inspectable behavior** over maximal realism in every subsystem.

---

## License

See `LICENSE`.