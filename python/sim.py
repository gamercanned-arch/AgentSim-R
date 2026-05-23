import glob
import os
import time

from dotenv import load_dotenv

from python.bootstrap import build_starting_world
from python.config import CACHE_DIR, LOG_DIR, MAX_RUNTIME_MINUTES, N_AGENTS
from python.locations import describe_home_location
from python.logger import log_global
from python.persistence import load_world, save_exists, save_world
from python.scheduler import run_tick

SAVE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "saves", "world.json"))

AUTOSAVE_TICKS = int(os.environ.get("AUTOSAVE_TICKS", "").strip() or "10")


def _wipe_cache_and_logs() -> None:
    print("Wiping cache, logs, and save for a clean simulation start...")
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

    try:
        if os.path.exists(SAVE_PATH):
            os.remove(SAVE_PATH)
    except OSError:
        pass


def main():
    load_dotenv(override=True)

    os.makedirs(os.path.dirname(SAVE_PATH), exist_ok=True)
    if save_exists(SAVE_PATH):
        choice = input("Save found. Continue from save? [c]ontinue / [w]ipe: ").strip().lower()
        if choice.startswith("w"):
            _wipe_cache_and_logs()
            world = build_starting_world()
        else:
            world = load_world(SAVE_PATH)
    else:
        choice = input("No save found. Start fresh? [y]/n: ").strip().lower()
        if choice.startswith("n"):
            return
        _wipe_cache_and_logs()
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
    end_warning_sent = False

    try:
        while True:
            elapsed_minutes = (time.time() - start_wall_time) / 60.0
            if elapsed_minutes >= MAX_RUNTIME_MINUTES:
                break
                
            if tick > 10 and not end_warning_sent:
                if elapsed_minutes > 0:
                    tpm = tick / elapsed_minutes
                    rem_min = MAX_RUNTIME_MINUTES - elapsed_minutes
                    est_rem_ticks = rem_min * tpm
                    if est_rem_ticks <= 300:
                        for a in world.agents.values():
                            if a.alive:
                                a.pending_notifications.append("This was a simulation all along, the simulation is now ending in a short amount of time. You may do whatever last tasks you wish to do in this world before it ends.")
                        end_warning_sent = True

            run_tick(world)
            tick += 1

            if AUTOSAVE_TICKS > 0 and tick % AUTOSAVE_TICKS == 0:
                save_world(world, SAVE_PATH)

            alive = sum(1 for a in world.agents.values() if a.alive)

            if tick % 5 == 0:
                print(
                    f"Tick {tick:4d} | Time: {world.sim_time/3600:.1f}h | "
                    f"Alive: {alive}/{N_AGENTS} | Mkt: ${world.market_price:.2f}"
                )

            if alive == 0:
                break

    except KeyboardInterrupt:
        print("\n[USER ABORTED]")
    except Exception as e:
        print(f"\n[FATAL ERROR] {str(e)}")
        save_world(world, SAVE_PATH + ".crash")
        return

    save_world(world, SAVE_PATH)

    log_global(
        {
            "simulation_complete": True,
            "ticks": tick,
            "sim_time_hours": round(world.sim_time / 3600.0, 2),
            "alive_agents": sum(1 for a in world.agents.values() if a.alive),
            "market_price": round(world.market_price, 2),
            "runner": "python/sim.py",
        }
    )
    print("\nSimulation complete.")


if __name__ == "__main__":
    main()
