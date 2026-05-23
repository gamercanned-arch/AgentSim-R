from __future__ import annotations

import os
import uuid
from copy import deepcopy

from python.config import CACHE_DIR
from python.logger import log_death


def liquidate_portfolio(agent, world) -> float:
    if agent.shares_owned <= 0:
        return 0.0
    proceeds = agent.shares_owned * world.market_price
    agent.money += proceeds
    world.net_volume_this_period -= agent.shares_owned
    agent.shares_owned = 0
    agent.last_known_price = 0.0
    return float(proceeds)


def delete_agent_cache(agent_id: int) -> None:
    cache_path = os.path.join(CACHE_DIR, f"agent_{agent_id}.bin")
    try:
        if os.path.exists(cache_path):
            os.remove(cache_path)
    except OSError:
        pass


def kill_agent(target, world, cause: str = "unknown") -> None:
    if not target.alive:
        return

    if target.currently_holding and target.currently_holding.get("id") != "job_prop":
        target.inventory.append(target.currently_holding)
    target.currently_holding = None

    pre_death_state = {
        "health": round(target.health, 2),
        "energy": round(target.energy, 2),
        "hydration": round(getattr(target, "hydration", 0.0), 2),
        "happiness": round(target.happiness, 2),
        "stress": round(target.stress, 2),
        "hunger": round(target.hunger, 2),
        "money": round(target.money, 2),
        "location": target.location,
        "x": round(target.x, 2),
        "y": round(target.y, 2),
        "z": round(target.z, 2),
        "inventory": [deepcopy(i) for i in target.inventory],
        "current_home_type": target.current_home_type,
        "home_location": target.home_location,
        "job": target.job,
        "beliefs": target.beliefs,
        "vehicle_type": getattr(target, "vehicle_type", ""),
    }

    liquidated = liquidate_portfolio(target, world)

    estate = {
        "id": str(uuid.uuid4()),
        "source_agent_id": target.id,
        "source_agent_name": target.name,
        "x": float(target.x),
        "y": float(target.y),
        "z": float(target.z),
        "money": round(float(target.money), 2),
        "items": [deepcopy(i) for i in target.inventory],
    }
    world.corpse_estates.append(estate)

    if target.current_home_type and target.home_location:
        world.release_home_lot(target.current_home_type, target.home_location)

    target.owned_locations = []
    target.current_home_type = ""
    target.home_location = ""

    target.inventory.clear()
    target.money = 0.0
    target.pending_market_orders.clear()
    target.pending_notifications.clear()
    target.alive = False
    target.is_sleeping = False
    target.current_activity = "dead"
    target.task_state = "idle"
    target.pending_task_data = {}
    target.active_task_entities = {}

    delete_agent_cache(target.id)
    log_death(
        target,
        cause=cause,
        estate=estate,
        shares_liquidated=liquidated,
        pre_death_state=pre_death_state,
    )
