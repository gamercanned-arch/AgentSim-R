from __future__ import annotations
import json
import os
from dataclasses import asdict, fields, is_dataclass
from typing import Any, Dict
from python.state import AgentState, WorldState

SAVE_VERSION = 1


def _load_json_file(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _load_json_with_tmp_fallback(path: str) -> Dict[str, Any]:
    try:
        return _load_json_file(path)
    except (OSError, json.JSONDecodeError, ValueError):
        tmp_path = path + ".tmp"
        if os.path.exists(tmp_path):
            return _load_json_file(tmp_path)
        raise


def _move_or_copy_tree(src: str, dst: str, *, require_src_removed: bool = False) -> bool:
    import shutil

    if not os.path.exists(src):
        return False
    try:
        if os.path.exists(dst):
            shutil.rmtree(dst)
        os.rename(src, dst)
        return True
    except OSError:
        try:
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            try:
                shutil.rmtree(src)
            except OSError:
                if require_src_removed:
                    return False
            return True
        except OSError:
            return False


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
        "_status_cooldowns",
        "summary_text",
        "summary_turns_summarized",
        "_summary_checked_at_time",
        "_transit_meta",
        "_work_meta",
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
    for field_name in ("inventory", "pending_notifications", "chat_history",
                       "pending_market_orders", "pending_task_data",
                       "pending_status_requests", "active_task_entities",
                       "recent_scenarios", "voicemail_inbox"):
        if getattr(agent, field_name, None) is None:
            default = {} if field_name in ("pending_task_data", "pending_status_requests",
                                           "active_task_entities", "recent_scenarios") else []
            setattr(agent, field_name, default)

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
            "last_tax_day": int(world.last_tax_day),
            "token_usage": dict(world.token_usage),
        },
        "agents": [_agent_to_dict(a) for a in world.agents.values()],
    }


def world_from_dict(payload: Dict[str, Any]) -> WorldState:
    version = payload.get("version", 0)
    if version != SAVE_VERSION:
        print(f"[WARNING] Save version mismatch: file has v{version}, code expects v{SAVE_VERSION}")
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
    w.vacant_home_lots = {
        str(home_type): list(names or [])
        for home_type, names in dict(wblk.get("vacant_home_lots", w.vacant_home_lots)).items()
    }
    w.ground_items = list(wblk.get("ground_items", []))
    w.corpse_estates = list(wblk.get("corpse_estates", []))
    w.pending_deliveries = list(wblk.get("pending_deliveries", []))
    w.last_tax_day = int(wblk.get("last_tax_day", 0))
    w.token_usage = dict(wblk.get("token_usage", {}))

    w.agents = {}
    for ad in payload.get("agents", []) or []:
        agent = _agent_from_dict(dict(ad))
        w.agents[int(agent.id)] = agent

    return w


def save_world(world: WorldState, path: str = "saves/world.json") -> None:
    import shutil
    final_save_dir = os.path.dirname(os.path.abspath(path))
    parent_dir = os.path.dirname(final_save_dir)
    save_dir_name = os.path.basename(final_save_dir)
    
    # 1. Prepare tmp directory next to the final save directory
    tmp_save_dir = os.path.join(parent_dir, save_dir_name + ".tmp")
    if os.path.exists(tmp_save_dir):
        try:
            shutil.rmtree(tmp_save_dir)
        except OSError:
            pass
    os.makedirs(tmp_save_dir, exist_ok=True)
    
    # 2. Write all files into tmp_save_dir
    tmp_world_path = os.path.join(tmp_save_dir, os.path.basename(path))
    data = world_to_dict(world)
    with open(tmp_world_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        
    for agent in world.agents.values():
        hist_path = os.path.join(tmp_save_dir, f"agent_history_{agent.id}.json")
        hist_data = {
            "system_prompt": agent.system_prompt,
            "chat_history": agent.chat_history,
            "summary_text": getattr(agent, "summary_text", ""),
            "summary_turns_summarized": getattr(agent, "summary_turns_summarized", 0),
            "_popped_turns_pending_summary": getattr(agent, "_popped_turns_pending_summary", [])
        }
        with open(hist_path, "w", encoding="utf-8") as f:
            json.dump(hist_data, f, ensure_ascii=False, indent=2, default=str)
            
    # 3. Perform atomic directory swap
    old_save_dir = os.path.join(parent_dir, save_dir_name + ".old")
    if os.path.exists(old_save_dir):
        try:
            shutil.rmtree(old_save_dir)
        except OSError:
            pass

    moved_old = False
    if os.path.exists(final_save_dir):
        moved_old = _move_or_copy_tree(final_save_dir, old_save_dir, require_src_removed=True)
        if not moved_old:
            raise RuntimeError(f"Failed to stage existing save directory {final_save_dir} -> {old_save_dir}")

    moved_new = _move_or_copy_tree(tmp_save_dir, final_save_dir)
    if not moved_new:
        if moved_old and not os.path.exists(final_save_dir):
            _move_or_copy_tree(old_save_dir, final_save_dir)
        raise RuntimeError(f"Failed to promote save directory {tmp_save_dir} -> {final_save_dir}")

    # 4. Clean up old_save_dir only after the new save is safely in place.
    if os.path.exists(old_save_dir):
        try:
            shutil.rmtree(old_save_dir)
        except OSError:
            pass


def _heal_save_dir(path: str) -> None:
    import shutil
    final_save_dir = os.path.dirname(os.path.abspath(path))
    parent_dir = os.path.dirname(final_save_dir)
    save_dir_name = os.path.basename(final_save_dir)
    
    tmp_save_dir = os.path.join(parent_dir, save_dir_name + ".tmp")
    old_save_dir = os.path.join(parent_dir, save_dir_name + ".old")
    
    if os.path.exists(final_save_dir):
        return

    if _move_or_copy_tree(tmp_save_dir, final_save_dir):
        return

    if _move_or_copy_tree(old_save_dir, final_save_dir):
        return

    if os.path.exists(old_save_dir):
        try:
            shutil.copytree(old_save_dir, final_save_dir)
        except OSError:
            pass


def load_world(path: str = "saves/world.json") -> WorldState:
    _heal_save_dir(path)
    payload = _load_json_with_tmp_fallback(path)
    world = world_from_dict(payload)

    # Load agent histories side-cars
    save_dir = os.path.dirname(os.path.abspath(path))
    for agent in world.agents.values():
        hist_path = os.path.join(save_dir, f"agent_history_{agent.id}.json")
        if os.path.exists(hist_path):
            try:
                hist_data = _load_json_with_tmp_fallback(hist_path)
            except (OSError, json.JSONDecodeError, ValueError):
                hist_data = {}
            agent.system_prompt = hist_data.get("system_prompt", "")
            agent.chat_history = hist_data.get("chat_history", [])
            agent.summary_text = hist_data.get("summary_text", "")
            agent.summary_turns_summarized = hist_data.get("summary_turns_summarized", 0)
            agent._popped_turns_pending_summary = hist_data.get("_popped_turns_pending_summary", [])
                
    return world


def save_exists(path: str = "saves/world.json") -> bool:
    _heal_save_dir(path)
    return os.path.exists(path)
