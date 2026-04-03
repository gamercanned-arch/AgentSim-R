import glob
import os
import time

from python.bootstrap import build_starting_world
from python.config import CACHE_DIR, LOG_DIR, MAX_RUNTIME_MINUTES, N_AGENTS
from python.locations import describe_home_location
from python.logger import log_global
from python.scheduler import run_tick


def main():
    print("Sweeping old cache and log files for a clean simulation start...")

    for f in glob.glob(os.path.join(CACHE_DIR, "*.bin")):
        try:
            os.remove(f)
        except OSError:
            pass

    for f in glob.glob(os.path.join(LOG_DIR, "*.*")):
        try:
            os.remove(f)
        except OSError:
            pass

    world = build_starting_world()

    for agent in world.agents.values():
        print(
            f"Initialized {agent.name:>6s} | Job: {agent.job:<15s} | "
            f"Home: Home_{agent.name} ({describe_home_location(agent.home_location)}) | "
            f"Cash: ${agent.money:.2f} | Vehicle: {agent.vehicle_type}"
        )

    print(f"\nAgentSim-R starting...\nTime limit: {MAX_RUNTIME_MINUTES}m")

    tick = 0
    start_wall_time = time.time()

    try:
        while True:
            elapsed_minutes = (time.time() - start_wall_time) / 60.0
            if elapsed_minutes >= MAX_RUNTIME_MINUTES:
                break

            context_full = run_tick(world)
            tick += 1

            alive = sum(1 for a in world.agents.values() if a.alive)

            if tick % 5 == 0:
                print(
                    f"Tick {tick:4d} | Time: {world.sim_time/3600:.1f}h | "
                    f"Alive: {alive}/{N_AGENTS} | Mkt: ${world.market_price:.2f}"
                )

            if alive == 0 or context_full:
                break

    except KeyboardInterrupt:
        print("\n[USER ABORTED]")
    except Exception as e:
        print(f"\n[FATAL ERROR] {str(e)}")

    log_global(
        {
            "simulation_complete": True,
            "ticks": tick,
            "sim_time_hours": round(world.sim_time / 3600.0, 2),
            "alive_agents": sum(1 for a in world.agents.values() if a.alive),
            "market_price": round(world.market_price, 2),
        }
    )
    print("\nSimulation complete.")


if __name__ == "__main__":
    main()