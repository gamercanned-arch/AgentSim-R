from __future__ import annotations
import json
import os
from dataclasses import asdict, fields, is_dataclass
from typing import Any, Dict
from python.state import AgentState, WorldState

SAVE_VERSION = 1


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)


def _agent_to_dict(agent: AgentState) -> Dict[str, Any]:
    base = asdict(agent) if is_dataclass(agent) else dict(agent.__dict__)
    
    # DO NOT persist history/prompts in the main world.json to save space
    if "chat_history" in base:
        base["chat_history"] = []
    if "system_prompt" in base:
        base["system_prompt"] = ""

    extras = {}
    for k in (
        "_sleep_start",
        "summary_text",
        "summary_turns_summarized",
        "_summary_checked_at_time",
    ):
        if hasattr(agent, k):
            extras[k] = getattr(agent, k)

    base["_extras"] = extras
    return base


def _agent_from_dict(d: Dict[str, Any]) -> AgentState:
    d = dict(d or {})
    extras = d.pop("_extras", {}) or {}

    allowed = {f.name for f in fields(AgentState)}
    clean: Dict[str, Any] = {}
    unknown: Dict[str, Any] = {}

    for k, v in d.items():
        if k in allowed:
            clean[k] = v
        else:
            unknown[k] = v

    if unknown:
        extras = dict(extras)
        extras.setdefault("unknown_fields", {}).update(unknown)

    agent = AgentState(**clean)
    for k, v in extras.items():
        setattr(agent, k, v)
    return agent


def world_to_dict(world: WorldState) -> Dict[str, Any]:
    return {
        "version": SAVE_VERSION,
        "world": {
            "sim_time": float(world.sim_time),
            "market_price": float(world.market_price),
            "last_passive": float(world.last_passive),
            "net_volume_this_period": int(world.net_volume_this_period),
            "price_history": list(world.price_history),
            "weather": str(world.weather),
            "global_news": list(world.global_news),
            "store_inventory": dict(world.store_inventory),
            "last_restock_time": float(world.last_restock_time),
            "last_market_tick": float(getattr(world, "last_market_tick", 0.0)),
            "vacant_home_lots": dict(world.vacant_home_lots),
            "ground_items": list(world.ground_items),
            "corpse_estates": list(world.corpse_estates),
            "pending_deliveries": list(world.pending_deliveries),
        },
        "agents": [_agent_to_dict(a) for a in world.agents.values()],
    }


def world_from_dict(payload: Dict[str, Any]) -> WorldState:
    w = WorldState()
    wblk = payload.get("world", {}) or {}

    w.sim_time = float(wblk.get("sim_time", 0.0))
    w.market_price = float(wblk.get("market_price", 100.0))
    w.last_passive = float(wblk.get("last_passive", w.sim_time))
    w.net_volume_this_period = int(wblk.get("net_volume_this_period", 0))
    w.price_history = list(wblk.get("price_history", [w.market_price]))
    w.weather = str(wblk.get("weather", "Sunny"))
    w.global_news = list(wblk.get("global_news", []))
    w.store_inventory = dict(wblk.get("store_inventory", {}))
    w.last_restock_time = float(wblk.get("last_restock_time", 0.0))
    w.last_market_tick = float(wblk.get("last_market_tick", w.sim_time))
    w.vacant_home_lots = dict(wblk.get("vacant_home_lots", w.vacant_home_lots))
    w.ground_items = list(wblk.get("ground_items", []))
    w.corpse_estates = list(wblk.get("corpse_estates", []))
    w.pending_deliveries = list(wblk.get("pending_deliveries", []))

    w.agents = {}
    for ad in payload.get("agents", []) or []:
        agent = _agent_from_dict(dict(ad))
        w.agents[int(agent.id)] = agent

    return w


def save_world(world: WorldState, path: str = "saves/world.json") -> None:
    _ensure_dir(path)
    
    # Save main file
    data = world_to_dict(world)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

    # Save agent histories as side-cars
    save_dir = os.path.dirname(os.path.abspath(path))
    for agent in world.agents.values():
        hist_path = os.path.join(save_dir, f"agent_history_{agent.id}.json")
        hist_data = {
            "system_prompt": agent.system_prompt,
            "chat_history": agent.chat_history,
            "summary_text": getattr(agent, "summary_text", ""),
            "summary_turns_summarized": getattr(agent, "summary_turns_summarized", 0)
        }
        with open(hist_path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(hist_data, f, ensure_ascii=False, indent=2)
        os.replace(hist_path + ".tmp", hist_path)


def load_world(path: str = "saves/world.json") -> WorldState:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    world = world_from_dict(payload)

    # Load agent histories side-cars
    save_dir = os.path.dirname(os.path.abspath(path))
    for agent in world.agents.values():
        hist_path = os.path.join(save_dir, f"agent_history_{agent.id}.json")
        if os.path.exists(hist_path):
            with open(hist_path, "r", encoding="utf-8") as f:
                hist_data = json.load(f)
                agent.system_prompt = hist_data.get("system_prompt", "")
                agent.chat_history = hist_data.get("chat_history", [])
                agent.summary_text = hist_data.get("summary_text", "")
                agent.summary_turns_summarized = hist_data.get("summary_turns_summarized", 0)
                
    return world


def save_exists(path: str = "saves/world.json") -> bool:
    return os.path.exists(path)