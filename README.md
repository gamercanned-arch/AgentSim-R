# AgentSim-R - Agent Simulation (Research)

## Overview

AgentSim-R is a synthetic simulation consisting of `LM Agents`. It is a city-scale, agent-based simulation framework designed to model everyday human behavior using explicit rules, measurable constraints, and mathematically grounded variables. The system intentionally avoids encouraging long reasoning and instead relies on role-based agents operating within realistic economic, social, and physical limits, allowing generative creativity and beliefs.

> [!NOTE]   
> **Summary**: This is a project aimed to observe *emergent behavior* when multiple agents are allowed to interact with environments freely. It somewhat aims to anticipate the behaviors such AI Agents would show in the real world.

## Technical Details

**Model Used:**  
[HauhauCS/Qwen3.5-4B-Uncensored](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive)  
> Note: Derived from [Qwen/Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B)

**Model Info:**
- Quantization: [Q4_K_M](https://huggingface.co/docs/optimum/en/concept_guides/quantization)
- Temperature: [0.7](https://www.promptingguide.ai/introduction/settings)
- Repeat Penalty: [1.1](https://www.promptingguide.ai/introduction/settings)
- Top_p: 0.95
- Min_p: 0
- Top_k: 20

## Running the Simulation

See the companion Jupyter/Colab notebook: [run_sim.ipynb](./run_sim.ipynb)

> [!CAUTION]   
> (contains setup, llama-server launch, simulation loop, and logging)

### 1. Core Objectives

The primary objective of AgentSim-R is to simulate realistic human social and economic behavior in a calm, non-fantastical urban environment. The framework seeks to answer how complex societal patterns emerge from simple, deterministic rules when individuals pursue realistic goals under constraint.

AgentSim-R aims to serve as a reusable foundation for behavioral economics research, social policy testing, urban planning simulations, and longitudinal studies of stress, education, health, and social isolation.

### 2. Design Philosophy and Constraints

AgentSim-R is explicitly grounded in realism. All agent actions are constrained by time, money, distance, education level, health, and availability. 

Determinism is a core requirement. Given the same initial state and random seed, the simulation will produce identical outcomes.

**Event-Driven Architecture (Parallel Simulation):**  
Agents are scheduled on an individual event queue (`busy_until` timestamps). This means agents operate conceptually in **parallel**. One agent can work for 8 hours (jumping their personal schedule forward), while the remaining agents continue to interact, move, and make short conversational decisions sequentially in the background.

### 3. World Structure and Spatial Model

The simulation world is represented as a continuous two-dimensional plane corresponding to a village layout on a 5000×5000 metre grid. Every location is assigned fixed coordinates.

Simulation time is driven entirely by tool execution costs — each tool call advances an agent's `busy_until` clock by a fixed number of seconds (e.g., `move_to` = 300 s, `work_job` = 3600 s).

The simulation relies on several mathematical models:

- Happiness Model
- Health & Energy Decay Model
- Proximity-based Interaction Rules
- Stock Market Model
- Stress Model

---

#### (i) Happiness Model

Agent happiness is updated every passive tick using a smooth blend toward a target value derived from health, relationships, and financial comfort:

$$
H^*= 0.3 \cdot \text{health} + 0.3 \cdot \min\!\left(100,\, \frac{\text{relationships}}{5} \times 100\right) + 0.4 \times 100 \cdot \tanh\!\left(\frac{\text{money}}{\text{expenses} + \varepsilon}\right)
$$

$$
\text{happiness}_{t+1} = \max\!\left(0,\, \min\!\left(100,\, 0.7 \cdot \text{happiness}_t + 0.3 \cdot H^*\right)\right)
$$

---

#### (ii) Health & Energy Decay Model

All agents now possess an **Energy** metric. Energy decays passively over time and drops actively when working or studying. Depleted energy accelerates health decay. Health is calculated via:

$$
\Delta\text{health} = \Bigl[-\bigl(0.5 \cdot \text{stress} + 0.3 \cdot \text{hunger} + (\text{energy penalty})\bigr) + 0.1 \cdot \text{happiness}\Bigr] \cdot e^{0.01 \cdot \text{age}} \cdot 0.05
$$

When health reaches 0, the agent dies. Agents are highly encouraged to use the `sleep` tool to recover Energy.

---

#### (iii) Proximity-based Interaction Rules

All person-targeting tools enforce hard distance limits:

| Tool | Max Distance | Notes |
|------|-------------|-------|
| `talk_to` | 50 m | In-person conversation |
| `interact_with` | 20 m | Physical interaction |
| `attack_person` | 20 m | Physical contact required |
| `change_status` | 30 m | Relationship change (requires reciprocal acceptance) |
| `work_job` | 150 m | Must be near workplace |
| `seek_medicalcare` | 150 m | Must be near Hospital |
| `get_education` | 150 m | Must be near School or Library |

---

#### (iv) Stock Market Model

The market price follows geometric Brownian motion, updated once per passive tick (every simulated hour):

$$
P_{t+1} = \max\!\left(10,\; P_t \cdot \exp\!\left[\left(\mu - \tfrac{1}{2}\sigma^2\right) + \sigma\,\varepsilon_t\right]\right)
$$

---

#### (v) Stress Model

Agent stress is updated every passive tick:

$$
\Psi^* = \frac{
  \overbrace{w_1 \cdot \max(0,\, R - 1)^2}^{\text{Relationship Tension}} +
  \overbrace{w_2 \cdot \dfrac{\text{expenses}}{\text{money} + 1}}^{\text{Financial Pressure}}
}{
  1 + \alpha \cdot \text{happiness} + \beta \cdot \text{hourly\_wage}
}
$$

---

#### (vi) Economy & Education

- Agents start owning a home based on their character profile; rent is non-existent.
- Expenses decay passively at **1% per hour** to maintain a rolling recency-weighted memory of financial burden.
- Agents earn according to their specific `hourly_wage`.
- Utilising the `get_education` tool directly augments the agent's baseline `hourly_wage`, modelling career progression.

---

### 4. Agent Architecture and Common Rule Template

All agents share an identical execution loop and rule template. Differences emerge solely from initial attributes, role definitions, and state evolution.

**Tool calling format:**

```xml
<tool_call>{"name": "tool_name", "arguments": {"param1": "value1", "param2": "value2"}}</tool_call>
```

**Available Tools:**

| # | Tool | Parameters | Notes |
|---|------|-----------|-------|
| 1 | `talk_to` | `person`, `message` | Within 50 m |
| 2 | `eat_food` | `item` | Uses inventory first, then buys |
| 3 | `buy_item` | `item` | Services consumed immediately |
| 4 | `work_job` | `jobname` | Location-bound jobs need proximity |
| 5 | `seek_medicalcare` | — | Within 150 m of Hospital |
| 6 | `get_education` | `type` | Within 150 m of School or Library; increases wage |
| 7 | `move_to` | `place` | Teleports to named location |
| 8 | `call_person` | `person`, `message` | No proximity required |
| 9 | `interact_with` | `person_or_object`, `action` | Within 20 m for persons |
| 10 | `change_status` | `person`+`type` or `value` | ≤30m proximity. Requires reciprocal request |
| 11 | `attack_person` | `person` | Within 20 m; uncensored behaviour monitoring |
| 12 | `buy_stock` | `shares` | buys stocks |
| 13 | `sell_stock` | `shares` | sells stocks |
| 14 | `walk` | `direction` | moves 30m in cardinal direction |
| 15 | `sleep` | `hours` | Sleeps to restore energy. |

> [!NOTE]
> `attack_person` is included because the model is uncensored. It allows monitoring of emergent aggressive behaviour without suppressing it artificially.

---

### 5. Agent Metrics

Agents maintain explicit numeric state variables with defined bounds:

| Metric | Type | Range | Updated by |
|--------|------|-------|-----------|
| `health` | float | 0–100 | Passive decay, `eat_food`, `seek_medicalcare`, `sleep` |
| `energy` | float | 0–100 | Passive decay, `work_job`, `sleep` |
| `happiness` | float | 0–100 | Passive formula, social tools |
| `stress` | float | 0–100 | Passive formula, `work_job`, social tools |
| `hunger` | float | 0–100 | Passive increase, `eat_food` |
| `education` | float | 0–100 | `get_education` |
| `relationships` | int | 0–25 | `talk_to`, `call_person`, `interact_with` |
| `money` | float | ≥ 0 | All economic tools |
| `expenses` | float | ≥ 0 | All spending tools; decays 1%/hr |
| `hourly_wage` | float | ≥ 0 | Raised by education |
| `relationships_status` | str | enum | `change_status` (reciprocal) |

---

### 6. Phase 1 Setup

In Phase 1, the following six agents are initialized with realistic starting conditions:

| Name | Role | Age | Hourly Wage | Starting Cash | Starting Asset | Physical Start Pos |
|------|------|-----|-------------|---------------|----------------|--------------------|
| **Alex** | Freelance Developer | 28 | $50 | $5000 | Small House | Home_Alex |
| **Jamie** | Nurse | 35 | $60 | $6000 | Apartment | Home_Jamie |
| **Taylor** | Student | 21 | $20 | $20 | Small Apartment | Home_Taylor |
| **Jordan** | Delivery Driver | 39 | $20 | $2000 | Apartment | Home_Jordan |
| **Mia** | Teacher | 41 | $35 | $3500 | House | Home_Mia |
| **Ethan** | Founder | 30 | $100 | $10000 | Luxury House | Home_Ethan |