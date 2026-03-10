import random
import numpy as np

from config import N_AGENTS, RANDOM_SEED, CONTEXT_SIZE, CONTEXT_FILL_RATIO
from state import WorldState, AgentState
from scheduler import run_tick
from locations import LOCATIONS
from logger import log_global


# Initial baseline states for each agent's role
_STARTING_PROFILES = {
    "Alex":   {"wage": 50,  "money": 5000,  "home": "Small House"},
    "Jamie":  {"wage": 60,  "money": 6000,  "home": "Apartment"},
    "Taylor": {"wage": 20,  "money": 20,    "home": "Small Apartment"},
    "Jordan": {"wage": 20,  "money": 2000,  "home": "Apartment"},
    "Mia":    {"wage": 35,  "money": 3500,  "home": "House"},
    "Ethan":  {"wage": 100, "money": 10000, "home": "Luxury House"},
}


def main():
    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)

    world = WorldState()

    names = ["Alex", "Jamie", "Taylor", "Jordan", "Mia", "Ethan"]
    ages  = [28,      35,      21,       39,       41,    30]

    for i in range(N_AGENTS):
        agent = AgentState(i, names[i], ages[i])
        prof  = _STARTING_PROFILES[names[i]]
        
        # Economic asset assignment
        home_item = prof["home"]
        agent.current_home = home_item
        agent.owned_locations.append(home_item)
        
        # Physical world assignment
        home_loc_name = f"Home_{names[i]}"
        agent.location = home_loc_name
        agent.x, agent.y = LOCATIONS.get(home_loc_name, (0.0, 0.0))
        
        agent.hourly_wage = prof["wage"]
        agent.money       = prof["money"]
        
        # Staggered initialization so they don't all act at identically t=0
        agent.busy_until = random.uniform(0, 60)

        world.agents[i]  = agent

    context_limit = int(CONTEXT_SIZE * CONTEXT_FILL_RATIO)
    print(
        f"AgentSim-R Phase 1 – starting simulation\n"
        f"Context limit: {CONTEXT_SIZE:,} tokens "
        f"(stopping at {CONTEXT_FILL_RATIO*100:.0f}% = {context_limit:,} tokens)"
    )

    tick  = 0
    alive = N_AGENTS

    while True:
        context_full = run_tick(world)
        tick += 1

        alive = sum(1 for a in world.agents.values() if a.alive)

        # progress report every 25 turns taken
        if tick % 25 == 0:
            max_tokens = max(a.total_prompt_tokens for a in world.agents.values())
            pct = (max_tokens / context_limit) * 100.0
            print(
                f"Tick {tick:4d} | "
                f"Sim time: {world.sim_time/3600:.1f}h | "
                f"Alive: {alive}/{N_AGENTS} | "
                f"Market: ${world.market_price:.2f} | "
                f"Context: {pct:.1f}% of allowed limit"
            )

        if alive == 0:
            print("All agents have died. Ending simulation.")
            break

        if context_full:
            print(
                f"Context window approaching full after {tick} ticks "
                f"({world.sim_time/3600:.1f} sim-hours). Ending simulation."
            )
            break

    # final token usage report
    print("\n=== Final Token Usage ===")
    for agent in world.agents.values():
        pct = (agent.total_prompt_tokens / CONTEXT_SIZE) * 100.0
        print(
            f"  {agent.name:8s}: {agent.total_prompt_tokens:>8,} tokens "
            f"({pct:.1f}% of total max context)"
        )

    log_global({
        "simulation_complete": True,
        "ticks":               tick,
        "alive":               alive,
        "sim_time_hours":      round(world.sim_time / 3600, 2),
        "final_market_price":  round(world.market_price, 2),
        "price_history":       world.price_history,
        "financial_summary": {
            a.name: {"money": round(a.money, 2), "total_expenses": round(a.total_expenses, 2)}
            for a in world.agents.values()
        },
        "token_usage": {
            a.name: a.total_prompt_tokens
            for a in world.agents.values()
        },
    })
    print(f"\nSimulation complete. Ticks: {tick}, Alive: {alive}")


if __name__ == "__main__":
    main()