# AgentSim-R - Agent Simulation (Research)
## Overview
AgentSim-R is a synthetic simulation consisting of `LM Agents`. It is a city-scale, agent-based simulation framework designed to model everyday human behavior using explicit rules, measurable constraints, and mathematically grounded variables. The system intentionally avoids encouraging long reasoning and instead relies on role-based agents operating within realistic economic, social, and physical limits, allowing generative creativity and beliefs.

---

> **Summary**: This is a project aimed to observe *emergent behavior* when multiple agents are allowed to interact with environments freely. It somewhat aims to anticipate the behaviors such AI Agents would show in the real world.

---

## Technical Details:

Model Used:
[HauhauCS/Qwen3.5-4B-Uncensored](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive)
> Note: Derived from [Qwen/Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B)
Model Info:
- [Q4_K_M](https://huggingface.co/docs/optimum/en/concept_guides/quantization)
- Temperature: [0.7](https://www.promptingguide.ai/introduction/settings)
- Repeat Penalty: [1.1](https://www.promptingguide.ai/introduction/settings)
- Top_p: 0.95
- Min_p: 0
- Top_k: 20




### 1. Core Objectives

The primary objective of AgentSim-R is to simulate realistic human social and economic behavior in a calm, non-fantastical urban environment. The framework seeks to answer how complex societal patterns emerge from simple, deterministic rules when individuals pursue realistic goals under constraint.

The system is designed for scientific analysis, replayability, and scalability. Every decision made by an agent must be explainable through its internal state, available tools, and environmental context, action is driven by hidden reasoning, probabilistic text generation, or subjective interpretation.

AGENT-SIM aims to serve as a reusable foundation for behavioral economics research, social policy testing, urban planning simulations, and longitudinal studies of stress, education, health, and social isolation.

---

### 2. Design Philosophy and Constraints

AgentSim-R is explicitly grounded in realism. All agent actions are constrained by time, money, distance, education level, health, and availability. The framework rejects any concept of agents having awareness of being simulated or possessing abstract beliefs not derived from direct experience.

Determinism is a core requirement. Given the same initial state and random seed, the simulation will produce identical outcomes. Randomness is only introduced through mathematically defined stochastic processes such as bounded noise, Poisson-distributed events, or market volatility.


---

### 3. World Structure and Spatial Model

The simulation world is represented as a continuous two-dimensional plane corresponding to a city
layout. Every location is assigned fixed coordinates expressed in meters or latitude-longitude pairs.
Examples of locations include homes, offices, hospitals, schools, stores, and public spaces.

The simulation relies on several mathematical models for it's functioning.

These include:
- Happiness Decay Model
- Health Decay Model
- Proximity-based Interaction Rule
- Stock Market Model
- Stress Model

---
---
$\big(i\big)$. Happines Decay Model

Agent happiness is determined with a rigid mathematical model:

$$\text{happiness} = \left( 0.3 \cdot \text{health} + 0.3 \cdot \frac{\text{relationships}}{5} + 0.4 \cdot \tanh\left(\frac{\text{money}}{\text{expenses}}\right) \right)\tag{..I}$$

*money denotes the money the agent currently has*<br>
*max_income denotes the money the agent earns*<br>
*relationships denotes the relationships (excluding friends) an agent has*

---
$\big(ii\big)$. Health Decay Model

Agent health is determind by the following rigid mathematical model:
$$\Delta_{health} = -(0.5 \cdot stress + 0.3 \cdot hunger) \cdot e^{0.1 \cdot age} \tag{..II}$$

---
$\big(iii\big)$. Proximity-based Interaction rule

Agent position is represented as a coordinate pair: $$x, y$$ Distance between two agents or an agent and
a location is computed using Euclidean distance: $$distance = \sqrt{(x1 - x2)^2 + (y1 - y2)^2} \tag{..III}$$
All proximity-based interactions rely strictly on this calculation $(..III)$
<br>
Proximit-Based Interactions :
(For `talk_to`):
$$
interaction = \begin{cases}
 \text allowed, if distance \leq 50 \\
 \text prohibited, if distance \neq \leq 50
 \end{cases} 
$$
<br>
(for `interact_with`):

$$
interaction = \begin{cases}
\text allowed, if distacne \leq 20 \\
\text prohibited, if distance \neq \leq 20
\end{cases}
$$

---
$\big(iv\big)$. Stock Market Model 

The stock market has a sophisticated mathematical model:
$$ P_{t+1} = P_{t} \cdot exp \Bigg ( \Big( \mu - 0.5 \sigma_{t}^{2}\Big) + \sigma_{t} \epsilon_{t} \Bigg ) + Impact \big(trade_{t}\big) \tag{..IV}$$

where:

$\displaystyle P_{t+1}$ is the `Price` at the new time step <br>
$\displaystyle P_{t}$ is the `Price` at the current time step <br>
$exp$ ensures that the price grows/shrinks by **percentage** rather than fixed dollars. It also keeps the price from *hitting zero* <br>
$\mu$ Is a drift function, ensuring long-term trend.  If $\mu = 0.05$, the stock naturally wants to go up 5% over time (like a Bull Market). <br>
$\sigma_t$ Represents Volatility. A high $\sigma_t$ means the price swings wildly; a low one means it’s stable. <br>
$\epsilon_{t}$ Represents *Noise*. This is a random number (usually from a Normal Distribution) representing random events. <br>
$Impact (\cdots)$ Represents Market Impact. How much the price moves specifically because you traded. <br>

---
$\big(v\big)$. Stress Model
Agent stress is represented by:
$$\Psi = \frac{ \overbrace{w_1(R-1)^2}^{\text{Relationship Tension}} + \overbrace{w_2 \left( \frac{\text{Expenses}}{\text{Money} + 1} \right)}^{\text{Financial Pressure}} + \overbrace{w_3 \cdot \mathbb{1}_{\text{inv}} \cdot \max(0, P_t - P_{t+1})}^{\text{Market Anxiety}} }{ \underbrace{1 + \alpha \cdot \text{Happiness} + \beta \cdot \text{Max\_Income}}_{\text{Stress Buffer}}}\tag{..V}$$


---
---
<br>

---

### 4. Agent Architecture and Common Rule Template

All agents share an identical execution loop and rule template. Differences in behavior emerge solely from initial attributes, role definitions, and state evolution over time.

Each simulation tick follows a *similar* order: perception of environment, evaluation of needs, validation of tool preconditions, execution of one tool action, and deterministic state update.

No agent is allowed to bypass tool constraints or directly modify its state. All changes must occur through validated tool execution.

Tool calling:

```XML
<tool_call><function={function}><parameter={parameter}>...</parameter></function></tool_call>
```

**Tool Types** :
> 1. `talk_to`
- {person}  
> 2. `eat_food`
- {item}
> 3. `buy_item`
- {item} 
> 4. `work_job`
- {jobname}  
> 5. `seek_medicalcare`
- -  
> 6. `get_education`
- {type}
> 7. `move_to`
- {place} 
> 8. `call_person`
- {person}
> 9. `interact_with`
- {person}<br>
$or$<br>
- {object}
> 10. `change_status`
- {relationship_status}<br>
- - {type}, {person}
$or$
- {belief}D


---

### 5. Agents maintain explicit numeric metrics including health, money, education level, hunger, stress,

Happiness, work status, and relationship status. Each metric has defined bounds and update rules.

**All Metrics** :

1. `Happiness`
2. `Stress`
3. `Health`
4. `Education`
5. `Work Status`
6. `Hunger`
7. `Relationships`
8. `Beliefs`

---

### 5. Memory and Logging System

Every agent action, reasoning, and event is logged with timestamps and spatial context.<br>
This enables full replay, auditing, and longitudinal analysis.

---

### 6. Known Caveats and Risks

The primary risk is oversimplification of human psychology. While constraints are realistic, internal cognition is abstracted into numeric metrics.

Calibration of probabilities and weights is critical. Poor calibration can lead to unrealistic stagnation or chaos.

---

### 7. Scalability and Performance

> Phase 1:
- 6 Agents
- 256k Native Context Length
- 1 Simulated City
- Defined Roles, by a human.

> **Note**: Phase 2 and 3 are to be added soon. <br> Phase 2 will scale to $\sim250$ Agents. <br> Phase 3 is expected to scale to $\sim10,000$ 




