import random
from python.config import N_AGENTS
from python.state import WorldState, AgentState
from python.scheduler import run_tick
from python.logger import log_global

def main():
    world = WorldState()
    names = ["Alex", "Jamie", "Taylor", "Jordan", "Mia", "Ethan"]
    ages = [28, 35, 21, 39, 41, 30]
    for i in range(N_AGENTS):
        agent = AgentState(i, names[i], ages[i])
        agent.x = random.uniform(0, 5000)
        agent.y = random.uniform(0, 5000)
        agent.money = 300 + random.uniform(0, 2000)  # Random starting wealth
        world.agents[i] = agent

    print("Starting AgentSim-R simulation (Phase 1 - Village)")

    tick = 0
    while True:
        run_tick(world)
        tick += 1
        if tick % 10 == 0:
            print(f"Tick {tick} | Sim time: {world.sim_time / 3600:.1f} hours | Alive: {sum(1 for a in world.agents.values() if a.alive)}")
        
        # Simple stop after 100 ticks for testing
        if tick > 100:
            print("Reached test limit. Stopping.")
            break

if __name__ == "__main__":
    main()