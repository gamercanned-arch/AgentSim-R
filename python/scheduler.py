from concurrent.futures import ThreadPoolExecutor
import random
from python.utils import build_prompt, call_server
from python.tools import execute_tool
from python.logger import log_agent
from python.config import PASSIVE_TICK_SECONDS

def run_tick(world):
    # For Phase 1: simple round-robin (parallelism later)
    # No real graph yet — add in Phase 2

    for agent_id in range(len(world.agents)):
        agent = world.agents[agent_id]
        if not agent.alive:
            continue

        notifications = "No recent events."  # TODO: real notifications later

        prompt = build_prompt(agent_id, world, notifications, agent.failed_calls)
        generated = call_server(prompt)

        result, success = execute_tool(generated, agent_id, world)

        log_entry = {
            "prompt": prompt,
            "generated": generated,
            "tool_result": result,
            "success": success,
            "metrics": {
                "health": agent.health,
                "happiness": agent.happiness,
                "money": agent.money
            }
        }
        log_agent(agent_id, log_entry)

        # Random action time
        delta = 10 + 110 * random.random() if "talk" in generated.lower() or "interact" in generated.lower() else 30 + 150 * random.random()
        world.sim_time += delta
        agent.last_action_time = world.sim_time

        if not success:
            agent.failed_calls += 1
        else:
            agent.failed_calls = 0

        # Passive updates
        if world.sim_time - world.last_passive >= PASSIVE_TICK_SECONDS:
            for a in world.agents.values():
                if not a.alive:
                    continue
                a.hunger += 0.8
                a.stress += 0.3 * (1 - a.happiness / 100)
                delta_health = (-0.5 * a.stress - 0.3 * a.hunger + 0.1 * a.happiness) * (2.71828 ** (0.1 * a.age))
                a.health = max(0, a.health + delta_health)
                if a.health <= 0:
                    a.alive = False
                    print(f"Agent {a.name} died. Simulation ending.")
                    exit(0)
            world.last_passive = world.sim_time