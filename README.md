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
>(contains setup, llama-server launch, simulation loop, and logging)

### 1. Core Objectives

The primary objective of AgentSim-R is to simulate realistic human social and economic behavior in a calm, non-fantastical urban environment. The framework seeks to answer how complex societal patterns emerge from simple, deterministic rules when individuals pursue realistic goals under constraint.

The system is designed for scientific analysis, replayability, and scalability. Every decision made by an agent must be explainable through its internal state, available tools, and environmental context. Action is driven by hidden reasoning, probabilistic text generation, or subjective interpretation.

AgentSim-R aims to serve as a reusable foundation for behavioral economics research, social policy testing, urban planning simulations, and longitudinal studies of stress, education, health, and social isolation.

### 2. Design Philosophy and Constraints

AgentSim-R is explicitly grounded in realism. All agent actions are constrained by time, money, distance, education level, health, and availability. The framework rejects any concept of agents having awareness of being simulated or possessing abstract beliefs not derived from direct experience.

Determinism is a core requirement. Given the same initial state and random seed, the simulation will produce identical outcomes. Randomness is only introduced through mathematically defined stochastic processes such as bounded noise, Poisson-distributed events, or market volatility.

### 3. World Structure and Spatial Model

The simulation world is represented as a continuous two-dimensional plane corresponding to a city layout. Every location is assigned fixed coordinates (expressed in meters or latitude-longitude pairs). Examples of locations include homes, offices, hospitals, schools, stores, and public spaces.

The simulation relies on several mathematical models:

- Happiness Model
- Health Decay Model
- Proximity-based Interaction Rule
- Stock Market Model
- Stress Model

#### (i) Happiness Model

Agent happiness is determined with a rigid mathematical model:

$$
\text{happiness} = 0.3 \cdot \text{health} + 0.3 \cdot \frac{\text{relationships}}{5} + 0.4 \cdot \tanh\left( \frac{\text{money}}{\text{expenses} + \epsilon} \right)
$$

- *money* — current cash held by the agent
- *expenses* — typical or recent outflow (small ε ≈ 1 prevents division by zero)
- *relationships* — number of meaningful ties (excluding casual friends; divided by 5 for normalization, assuming ~25 max)

> Expenses are determined by money spent by agent(s), on things.

#### (ii) Health Decay Model

Agent health updates according to:

$$    
\Delta \text{health} = \left[ - (0.5 \cdot \text{stress} + 0.3 \cdot \text{hunger}) + 0.1\text{happiness} \right] \cdot e^{0.1 \cdot \text{age}}
$$ <br>
(small baseline recovery from rest/sleep; clamped ≥ 0)

> [!NOTE]   
> Tool `seek_medicalcare` adjusts health for an amount of money.

#### (iii) Proximity-based Interaction Rule

Agent position is a coordinate pair $(x, y)$. Distance is Euclidean:

$$
\text{distance} = \sqrt{(x_1 - x_2)^2 + (y_1 - y_2)^2}
$$

Interactions are strictly distance-dependent:

For `talk_to`:

$$
\text{interaction} =
\begin{cases}
\text{allowed}  & \text{if distance} \leq 50 \\
\text{prohibited} & \text{otherwise}
\end{cases}
$$

For `interact_with`:

$$
\text{interaction} =
\begin{cases}
\text{allowed}  & \text{if distance} \leq 20 \\
\text{prohibited} & \text{otherwise}
\end{cases}
$$

#### (iv) Stock Market Model

The stock follows geometric Brownian motion with impact:

$$
P_{t+1} = P_t \cdot \exp\left( \left( \mu - \frac{1}{2} \sigma_t^2 \right) + \sigma_t \epsilon_t \right) + \text{Impact}(\text{trade}_t)
$$

where:
- $P_{t+1}$ — price at the new time step
- $P_t$ — price at the current time step
- $\exp$ ensures percentage-based growth/decline and prevents hitting zero
- $\mu$ — drift (e.g. 0.05 for 5% long-term growth, bull market tendency)
- $\sigma_t$ — volatility (higher = wilder swings)
- $\epsilon_t \sim \mathcal{N}(0,1)$ — standard normal noise for random events
- $\text{Impact}(\cdot)$ — small price adjustment from net trading volume

#### (v) Stress Model

Agent stress $\Psi$ is:

$$
\Psi = \frac{
  \overbrace{w_1 (R-1)^2}^{\text{Relationship Tension}} +
  \overbrace{w_2 \left( \frac{\text{Expenses}}{\text{Money} + 1} \right)}^{\text{Financial Pressure}} +
  \overbrace{w_3 \cdot \mathbb{1}_{\text{inv}} \cdot \max(0, P_t - P_{t+1})}^{\text{Market Anxiety (losses only)}}
}{
  1 + \alpha \cdot \text{Happiness} + \beta \cdot \text{Max Income}
}
$$

- $\mathbb{1}_{\text{inv}}$ — indicator (1 if agent has investments, 0 otherwise)
- Market anxiety only on perceived losses

### 4. Agent Architecture and Common Rule Template

All agents share an identical execution loop and rule template. Differences emerge solely from initial attributes, role definitions, and state evolution.

Each tick follows: perception → needs evaluation → tool precondition validation → one tool execution → deterministic state update.

No agent may bypass constraints or directly modify state — all changes occur via validated tools.

**Tool calling format:**

```xml
<tool_call>{"name": "tool_name", "arguments": {"param1": "value1", "param2": "value2"}}</tool_call>
```

**Available Tools:**
1. `talk_to`
- {person}
2. `eat_food`
- {item}
3. `buy_item`
- {item}
4. `work_job`
- {jobname}
5. `seek_medicalcare`
- — (no parameters)
6. `get_education`
-  {type}
7. `move_to`
- {place}
8. `call_person`
- {person}
9. `interact_with`
- {person} <br> $or$ <br>
- {object}
10. `change_status`
- {relationship_status}
- - {type}, {person} <br>
$or$
- {belief}
11. `attack_person`
- {person}
> Since the models are uncensored, the `attack_person` tool helps to monitor dangerous behavior among the agents.

### 5. Agent Metrics

Agents maintain explicit numeric state variables with defined bounds and update rules:

1. `Happiness`
2. `Stress`
3. `Health`
4. `Education`
5. `Work Status`
6. `Hunger`
7. `Relationships`
8. `Beliefs`

### 6. Memory and Logging System

Every action, reasoning trace, and event is logged with timestamps and spatial context — enabling full replay, auditing, and longitudinal analysis.

### 7. Known Caveats and Risks

- Oversimplification of human psychology (cognition abstracted into numeric metrics).
- Calibration of weights/probabilities is critical — poor tuning can cause stagnation or chaotic collapse.

> [!WARNING]   
> Such LM agents are subject to oversimplification of actual Agents (trained via RL) but this is a fun experiment designed to "see" what would happen in such a scenario, as more and more developers emerge and enthusiasts get into AI, it is not hard to imagine that people would give everyday Language Models (LLMs/SLMs or perhaps VLMs) the power to autonomously control robots.

### 8. Scalability and Performance

| Phase |    Agents    |     Scale      |                Notes                      |
|-------|--------------|----------------|-------------------------------------------|
| 1     | 6            | Village-Scale  | 256k context, 1 city, human-defined roles |
| 2     | ~250         | City-Scale     |               Planned                     |
| 3     | ~10,000      | Country-Scale  |               Planned                     |

---

---
---


---

### 9. Phase 1

In Phase 1, the following six agents are initialized with realistic starting conditions:

|     Name     |         Role         |  Age |     Education    |                      Work Status                      |              Key Attributes                |
|--------------|----------------------|------|------------------|-------------------------------------------------------|--------------------------------------------|
|   **Alex**   |  Freelance Developer |  28  | High School (CS) |        Unemployed, Income: $40/hr, Freelancing        |      Hobbies: Coding, Building apps        |
|  **Jamie**   |         Nurse        |  35  | 12 (BSc Nursing) | Employed as a nurse at the hospital, Salary: $60k/year|            Stress: Medium                  |
|   **Taylor** |        Student       |  21  |   High school    |           Unemployed, Pursuing: Psychology            |      Goal: Get job in mental health        |
|  **Jordan**  |   Delivery Driver    |  39  |       12         | Employed as a Delivery Person at FedEx, Salary: $20/hr|        Stress: High due to hours           |
|    **Mia**   |  Teacher (part-time) |  41  |  12 + Master’s   |  Part-time employed at the school, Income: $35k/year  |           Interested in Drawing            |
|   **Ethan**  | Tech Startup Founder |  30  |   Gradute (CS)   |      Employed at his own Startup, 'Sowl', $5400/week    | Side gig: builds apps, High risk tolerance |

> Roles define default behaviors and goals. Agents start with realistic starting states and evolve over time through tool use and events. A tool call is encouraged at every turn to bootstrap interaction.






