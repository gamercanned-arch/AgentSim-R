import hashlib
import math
import os
import random
import re
import time
import uuid
from datetime import datetime, timezone
import numpy as np
from python.config import (
    BASE_STORE_INVENTORY,
    CONTEXT_FILL_RATIO,
    CONTEXT_SIZE,
    IMPACT_CLAMP_HI,
    IMPACT_CLAMP_LO,
    IMPACT_FACTOR,
    JUMP_PROB_PER_HOUR,
    JUMP_SIGMA,
    MARKET_TICK_SECONDS,
    MAX_INVENTORY,
    MAX_NEW_TOKENS,
    PASSIVE_TICK_SECONDS,
    STOCK_MU,
    STOCK_SIGMA,
    TAX_EXEMPT_BELOW_CASH,
    DROP_REPICKUP_COOLDOWN,
)
from python.core import next_market_open_time
from python.logger import log_global, log_io, log_turn, snapshot_agent
from python.tools import execute_tool, parse_tool_calls, try_auto_collect_loot
from python.utils import (
    build_messages,
    call_server,
    estimate_prompt_tokens,
    get_time_string,
    is_market_open,
    render_prompt,
)

def _ensure_agent_schema(agent) -> None:
    if not hasattr(agent, "hydration"):
        agent.hydration = 70.0
    if not hasattr(agent, "dehydration_hours"):
        agent.dehydration_hours = 0
    if not hasattr(agent, "vehicle_type"):
        agent.vehicle_type = "Scooter"
    if not hasattr(agent, "vehicle_x"):
        agent.vehicle_x = getattr(agent, "x", 0.0)
    if not hasattr(agent, "vehicle_y"):
        agent.vehicle_y = getattr(agent, "y", 0.0)
    if not hasattr(agent, "vehicle_z"):
        agent.vehicle_z = getattr(agent, "z", 0.0)
    if not hasattr(agent, "recent_scenarios") or agent.recent_scenarios is None:
        agent.recent_scenarios = {}
    if not hasattr(agent, "active_task_entities") or agent.active_task_entities is None:
        agent.active_task_entities = {}
    if not hasattr(agent, "voicemail_inbox") or agent.voicemail_inbox is None:
        agent.voicemail_inbox = []
    if getattr(agent, "z", 0.0) != 0.0:
        agent.z = 0.0
    if hasattr(agent, "vehicle_z") and getattr(agent, "vehicle_z", 0.0) != 0.0:
        agent.vehicle_z = 0.0

def _sha16(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()[
        :16
    ]

def _peek_notifications_for_prompt(
    agent, max_count: int = 12, max_chars: int = 1800
) -> tuple[list[str], int]:
    pending = list(getattr(agent, "pending_notifications", []) or [])
    shown = []
    total = 0
    for n in pending:
        if len(shown) >= max_count:
            break
        n = str(n)
        if total + len(n) + 1 > max_chars and shown:
            allowed = max_chars - total - 1
            if allowed > 10:
                shown.append(n[:allowed] + "...")
                total += allowed + 3
            break
        shown.append(n)
        total += len(n) + 1
    remaining = max(0, len(pending) - len(shown))
    return shown, remaining

def _consume_notifications(agent, count: int) -> None:
    if (
        not hasattr(agent, "pending_notifications")
        or agent.pending_notifications is None
    ):
        agent.pending_notifications = []
    if count <= 0:
        return
    del agent.pending_notifications[:count]

def _drop_ground_item(
    world, x: float, y: float, z: float, item_data: dict, dropper_id: int | None = None
) -> None:
    if not hasattr(world, "ground_items") or world.ground_items is None:
        world.ground_items = []
    world.ground_items.append(
        {
            "id": str(uuid.uuid4()),
            "item": item_data.get("item", "Unknown"),
            "durability": item_data.get("durability", 5),
            "bought": item_data.get("bought", world.sim_time),
            "x": float(x),
            "y": float(y),
            "z": 0.0,
            "dropper_id": int(dropper_id) if dropper_id is not None else -1,
            "repickup_block_until": float(world.sim_time + DROP_REPICKUP_COOLDOWN),
        }
    )

def _find_sender_estate(world, sender_id: int | None):
    if sender_id is None:
        return None
    for estate in getattr(world, "corpse_estates", []) or []:
        if estate.get("source_agent_id") == sender_id:
            return estate
    return None

def _return_escrow_money(world, sender, sender_id: int | None, amount: float) -> None:
    if amount <= 0:
        return
    if sender and sender.alive:
        sender.money += amount
        sender.pending_notifications.append(
            f"Queued transfer cancelled (recipient unavailable). Refunded ${amount:.2f}."
        )
        return
    estate = _find_sender_estate(world, sender_id)
    if estate is not None:
        estate["money"] = round(float(estate.get("money", 0.0)) + float(amount), 2)
        return
    world.global_news.append(
        f"Unclaimed escrowed money ${amount:.2f} was preserved in the world ledger."
    )
    world.global_news = world.global_news[-20:]

def _return_escrow_item(
    world,
    sender,
    sender_id: int | None,
    item: dict,
    fallback_xyz: tuple[float, float, float],
    target_name: str = "Unknown"
) -> None:
    if not isinstance(item, dict):
        return
    if sender and sender.alive:
        if len(sender.inventory) < MAX_INVENTORY:
            sender.inventory.append(item)
            sender.pending_notifications.append(
                f"Return to Sender, unable to deliver {item.get('item')} to {target_name}. Their inventory was full or they were unavailable."
            )
        else:
            _drop_ground_item(
                world, sender.x, sender.y, sender.z, item, dropper_id=sender.id
            )
            sender.pending_notifications.append(
                f"Return to Sender, unable to deliver {item.get('item')} to {target_name}. Your inventory was full, so the item was dropped on the ground at your feet."
            )
        return
    estate = _find_sender_estate(world, sender_id)
    if estate is not None:
        estate.setdefault("items", []).append(item)
        return
    _drop_ground_item(
        world, fallback_xyz[0], fallback_xyz[1], fallback_xyz[2], item, dropper_id=-1
    )

def _process_pending_deliveries(world, current_time: float) -> None:
    deliveries = getattr(world, "pending_deliveries", None) or []
    if not deliveries:
        return
    new_deliveries = []
    for d in deliveries:
        kind = d.get("kind")
        from_id = d.get("from_id")
        to_id = d.get("to_id")
        sender = world.agents.get(from_id) if isinstance(from_id, int) else None
        target = world.agents.get(to_id) if isinstance(to_id, int) else None
        fallback_xyz = (float(d.get("x", 0.0)), float(d.get("y", 0.0)), 0.0)
        target_name = target.name if target else "Unknown"
        
        if not target or not target.alive:
            if kind == "money":
                amt = float(d.get("amount", 0.0))
                _return_escrow_money(world, sender, from_id, amt)
            elif kind == "item":
                item = d.get("item", None)
                _return_escrow_item(world, sender, from_id, item, fallback_xyz, target_name)
            continue
            
        if target.is_sleeping:
            new_deliveries.append(d)
            continue
            
        if kind == "money":
            amt = float(d.get("amount", 0.0))
            target.money += amt
            target.pending_notifications.append(
                f"Received queued money transfer: ${amt:.2f}."
            )
            if sender and sender.alive:
                sender.pending_notifications.append(
                    f"Queued money transfer delivered to {target.name}: ${amt:.2f}."
                )
            continue
            
        if kind == "item":
            item = d.get("item", None)
            if not isinstance(item, dict):
                continue
            if len(target.inventory) >= MAX_INVENTORY:
                _return_escrow_item(world, sender, from_id, item, fallback_xyz, target.name)
                target.pending_notifications.append(
                    f"A queued item delivery from {sender.name if sender else 'Unknown'} was cancelled because your inventory was full."
                )
                continue
            target.inventory.append(item)
            target.pending_notifications.append(
                f"Received queued item delivery: {item.get('item', 'Unknown')}."
            )
            if sender and sender.alive:
                sender.pending_notifications.append(
                    f"Queued item delivery delivered to {target.name}: {item.get('item', 'Unknown')}."
                )
            continue
    world.pending_deliveries = new_deliveries

def _ensure_market_clock(world) -> None:
    if not hasattr(world, "last_market_tick"):
        world.last_market_tick = world.sim_time
    if world.last_market_tick <= 0.0:
        world.last_market_tick = world.sim_time

def _advance_market_to(world, new_time: float) -> None:
    _ensure_market_clock(world)
    if new_time <= world.last_market_tick:
        return
    while world.last_market_tick < new_time:
        if not is_market_open(world.last_market_tick):
            nxt = next_market_open_time(world.last_market_tick)
            if nxt > new_time:
                world.last_market_tick = new_time
                return
            world.last_market_tick = float(nxt)
            _process_market_queues(world, sim_time=world.last_market_tick)
            continue
        next_tick = world.last_market_tick + MARKET_TICK_SECONDS
        if next_tick > new_time:
            world.last_market_tick = new_time
            return
        world.last_market_tick = next_tick
        _process_market_queues(world, sim_time=world.last_market_tick)
        _update_market_price(
            world, sim_time=world.last_market_tick, dt_seconds=MARKET_TICK_SECONDS
        )

def _sanitize_chat_history(text: str, max_chars: int = 2400) -> str:
    s = "" if text is None else str(text)
    s = s.replace("\x00", "")
    s = re.sub(r"[\r\t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    if len(s) > max_chars:
        s = s[: max_chars - 20] + f"... ({len(s)} chars)"
    return s

def _tool_history_text(result: str, max_chars: int = 1200) -> str:
    s = "" if result is None else str(result).strip()
    if len(s) > max_chars:
        s = s[: max_chars - 20] + f"... ({len(s)} chars)"
    return s

def _commit_history(
    agent, user_text: str, assistant_text: str, tool_result: str
) -> None:
    # DO NOT STRIP <think> blocks, LLM needs continuity
    safe_assistant = _sanitize_chat_history(assistant_text, max_chars=2400)
    agent.chat_history.append({"role": "user", "content": user_text})
    agent.chat_history.append({"role": "assistant", "content": safe_assistant})
    steps = list(getattr(agent, "_last_api_tool_steps", []) or [])
    if not steps:
        steps = [{"name": "unknown", "result": tool_result}]
    for st in steps:
        name = str(st.get("name", "") or "unknown").strip() or "unknown"
        res = _tool_history_text(st.get("result", tool_result))
        agent.chat_history.append(
            {"role": "tool", "content": f"RESULT ({name}): {res}"}
        )
    agent._last_api_tool_steps = []

def _pop_oldest_turn(agent) -> bool:
    if not agent.chat_history:
        return False
    while agent.chat_history and agent.chat_history[0].get("role") != "user":
        agent.chat_history.pop(0)
    if not agent.chat_history:
        return False
    agent.chat_history.pop(0)
    while agent.chat_history and agent.chat_history[0].get("role") != "user":
        agent.chat_history.pop(0)
    return True

def _build_trimmed_messages(agent, world, notifications_text: str, context_limit: int):
    base_msgs = build_messages(agent.id, world, notifications_text)
    base_prompt_text = render_prompt(base_msgs)
    base_estimated_tokens = estimate_prompt_tokens(
        base_msgs, prompt_text=base_prompt_text
    )
    
    if base_estimated_tokens + MAX_NEW_TOKENS >= context_limit:
        agent.chat_history.clear()
        trimmed_msgs = build_messages(agent.id, world, notifications_text)
        trimmed_prompt_text = render_prompt(trimmed_msgs)
        trimmed_estimated_tokens = estimate_prompt_tokens(
            trimmed_msgs, prompt_text=trimmed_prompt_text
        )
        
        if trimmed_estimated_tokens + MAX_NEW_TOKENS >= context_limit:
            from python.config import CHARS_PER_TOKEN
            overflow = (trimmed_estimated_tokens + MAX_NEW_TOKENS) - context_limit
            chars_to_remove = int(overflow * CHARS_PER_TOKEN) + 200
            
            # "just summarize it bro"
            # Instead of blindly amputating the tail (which destroys critical schemas and catalogs),
            # we ask the LLM to compress the rules. If it's absurdly large (e.g. from the test suite), reset.
            if len(agent.system_prompt) > 100_000:
                agent.system_prompt = "" 
            else:
                compression_msgs = [
                    {"role": "system", "content": "You are a compression engine. Summarize the following system rules densely, but YOU MUST KEEP ALL XML tool schemas, location hours, and catalog prices perfectly intact."},
                    {"role": "user", "content": agent.system_prompt}
                ]
                compressed, _, _ = call_server(compression_msgs, agent.id)
                if compressed and "[SERVER ERROR]" not in compressed:
                    agent.system_prompt = compressed + "\n[System prompt compressed due to context limits]"
                else:
                    # Fallback middle-slice if server fails: preserves head (Tools) and tail (Catalogs).
                    sp = agent.system_prompt
                    if len(sp) > chars_to_remove:
                        mid = len(sp) // 2
                        half = chars_to_remove // 2
                        agent.system_prompt = sp[:mid - half] + "\n...[Rules Compressed]...\n" + sp[mid + half:]

            final_msgs = build_messages(agent.id, world, notifications_text)
            final_prompt_text = render_prompt(final_msgs)
            
            # Forcefully clamp the estimated tokens so `run_tick` permits generation
            final_estimated = min(
                estimate_prompt_tokens(final_msgs, prompt_text=final_prompt_text),
                context_limit - MAX_NEW_TOKENS - 10
            )
            return final_msgs, final_prompt_text, final_estimated
            
    return base_msgs, base_prompt_text, base_estimated_tokens

def _get_raw_llm_fields(agent_id: int, processed: str) -> tuple[str, str, str, str]:
    raw_provider = ""
    raw_model = ""
    raw_content = processed
    raw_reasoning = ""
    if hasattr(call_server, "get_last_raw"):
        try:
            meta = call_server.get_last_raw(agent_id)  # type: ignore[attr-defined]
            raw_provider = str(meta.get("provider", "") or "")
            raw_model = str(meta.get("model", "") or "")
            raw_content = str(meta.get("content", processed) or processed)
            raw_reasoning = str(meta.get("reasoning", "") or "")
            return raw_provider, raw_model, raw_content, raw_reasoning
        except Exception:
            pass
    meta_map = getattr(call_server, "last_raw", None)
    if isinstance(meta_map, dict):
        meta = meta_map.get(int(agent_id), {}) or {}
        raw_provider = str(meta.get("provider", "") or "")
        raw_model = str(meta.get("model", "") or "")
        raw_content = str(meta.get("content", processed) or processed)
        raw_reasoning = str(meta.get("reasoning", "") or "")
        return raw_provider, raw_model, raw_content, raw_reasoning
    return raw_provider, raw_model, raw_content, raw_reasoning

def run_tick(world) -> bool:
    while True:
        alive_agents = [a for a in world.agents.values() if a.alive]
        if not alive_agents:
            return False
        agent = min(alive_agents, key=lambda a: (a.busy_until, a.id))
        _ensure_agent_schema(agent)
        if agent.busy_until > world.sim_time:
            world.sim_time = agent.busy_until
            _advance_market_to(world, world.sim_time)
        while world.sim_time - world.last_passive >= PASSIVE_TICK_SECONDS:
            world.last_passive += PASSIVE_TICK_SECONDS
            _advance_market_to(world, world.last_passive)
            _update_weather(world)
            _restock_if_needed(world)
            _apply_midnight_taxes(world, world.last_passive)
            for a in list(world.agents.values()):
                if not a.alive:
                    continue
                _ensure_agent_schema(a)
                try_auto_collect_loot(a, world)
                _apply_passive_updates(a, world, world.last_passive)
            for a in world.agents.values():
                _ensure_agent_schema(a)
                _refresh_agent_activity(a, world.last_passive)
            _process_pending_deliveries(world, world.last_passive)
        alive_agents = [a for a in world.agents.values() if a.alive]
        if not alive_agents:
            return False
        ready_agents = [a for a in alive_agents if a.busy_until <= world.sim_time]
        if ready_agents:
            agent = min(ready_agents, key=lambda a: (a.busy_until, a.id))
            _ensure_agent_schema(agent)
            break
            
    _refresh_agent_activity(agent, world.sim_time)
    try_auto_collect_loot(agent, world)
    _process_pending_deliveries(world, world.sim_time)
    
    shown_lines, remaining_count = _peek_notifications_for_prompt(
        agent, max_count=12, max_chars=1800
    )
    notifications_text = "\n".join(shown_lines).strip()
    if remaining_count > 0:
        notifications_text = (
            notifications_text + "\n" if notifications_text else ""
        ) + f"(Queued notifications remaining: {remaining_count})"
        
    context_limit = int(CONTEXT_SIZE * CONTEXT_FILL_RATIO)
    msgs, prompt_text, estimated_tokens = _build_trimmed_messages(
        agent, world, notifications_text, context_limit
    )
    prompt_hash = _sha16(prompt_text)
    prompt_chars = len(prompt_text)
    
    if estimated_tokens + MAX_NEW_TOKENS >= context_limit:
        agent.last_action_result = "Prompt still exceeds context limit after aggressive trimming."
        agent.busy_until = max(world.sim_time, agent.busy_until) + 60
        log_global(
            {
                "event": "context_limit_reached_after_trim",
                "agent": agent.name,
                "agent_id": agent.id,
                "sim_time": world.sim_time,
                "sim_time_str": get_time_string(world.sim_time),
                "estimated_prompt_tokens": estimated_tokens,
                "generation_reserve": MAX_NEW_TOKENS,
                "context_limit": context_limit,
                "prompt_hash": prompt_hash,
                "prompt_chars": prompt_chars,
            }
        )
        world.sim_time = agent.busy_until
        return False
        
    pre_state = snapshot_agent(agent)

    try:
        processed_out, prompt_tokens, gen_tokens = call_server(
            msgs, agent.id, prompt_text=prompt_text
        )
    except Exception as e:
        processed_out = f"[SERVER ERROR] {e}"
        prompt_tokens, gen_tokens = 0, 0

    raw_provider, raw_model, raw_content, raw_reasoning = _get_raw_llm_fields(
        agent.id, processed_out
    )
    current_user_text = (
        msgs[-1]["content"] if msgs and msgs[-1].get("role") == "user" else ""
    )

    log_io(
        agent.name,
        world.sim_time,
        msgs,
        raw_content,
        prompt_hash=prompt_hash,
        prompt_chars=prompt_chars,
        raw_provider=raw_provider,
        raw_model=raw_model,
        raw_reasoning=raw_reasoning,
        processed_output=processed_out,
    )
    agent.total_prompt_tokens += int(prompt_tokens)
    parsed_calls, parse_error = parse_tool_calls(processed_out)
    if parse_error:
        parsed_tool = parse_error
        parsed_args = {}
    elif len(parsed_calls) == 1:
        parsed_tool, parsed_args = parsed_calls[0]
    else:
        parsed_tool = [name for name, _ in parsed_calls]
        parsed_args = [args for _, args in parsed_calls]
        
    res, suc, cost = execute_tool(processed_out, agent.id, world)
    agent.last_action_result = res
    if agent.alive:
        _commit_history(agent, current_user_text, processed_out, res)
        agent.busy_until = max(world.sim_time, agent.busy_until) + max(0, int(cost))
        
    if suc:
        _consume_notifications(agent, len(shown_lines))
        agent.fail_counter = 0
    else:
        agent.fail_counter += 1
        
    _refresh_agent_activity(agent, world.sim_time)
    post_state = snapshot_agent(agent)
    log_turn(
        agent=agent,
        sim_time=world.sim_time,
        notifications=notifications_text,
        messages=msgs,
        raw_output=raw_content,
        raw_provider=raw_provider,
        raw_model=raw_model,
        raw_reasoning=raw_reasoning,
        processed_output=processed_out,
        parsed_tool=parsed_tool,
        parsed_args=parsed_args,
        result=res,
        success=suc,
        cost=int(cost),
        pre_state=pre_state,
        post_state=post_state,
        prompt_hash=prompt_hash,
        prompt_chars=prompt_chars,
        notifications_shown=shown_lines,
        notifications_remaining=remaining_count,
    )
    return False

def _refresh_agent_activity(agent, current_time: float) -> None:
    if not agent.alive:
        agent.current_activity = "dead"
        return
    if agent.is_sleeping and current_time >= agent.busy_until:
        sleep_duration_hours = max(
            0.0,
            (
                float(agent.busy_until)
                - float(getattr(agent, "_sleep_start", agent.busy_until))
            )
            / 3600.0,
        )
        if sleep_duration_hours > 0:
            from python.locations import get_current_location_def
            loc = get_current_location_def(agent.x, agent.y, agent.z)
            is_home_sleep = bool(loc and loc.name == agent.home_location)
            energy_rate = 10.0 if is_home_sleep else 6.0
            stress_rate = 2.0 if is_home_sleep else 1.0
            agent.energy = min(100.0, agent.energy + energy_rate * sleep_duration_hours)
            agent.stress = max(0.0, agent.stress - stress_rate * sleep_duration_hours)
        agent.is_sleeping = False
        
    if (
        not agent.is_sleeping
        and agent.task_state == "idle"
        and agent.busy_until <= current_time
        and agent.current_activity != "dead"
    ):
        agent.current_activity = "idle"
        
        if hasattr(agent, "_transit_meta"):
            delattr(agent, "_transit_meta")
        if hasattr(agent, "_work_meta"):
            delattr(agent, "_work_meta")

def _process_market_queues(world, sim_time: float) -> None:
    if not is_market_open(sim_time):
        return
    for agent in world.agents.values():
        if not agent.alive or not agent.pending_market_orders:
            continue
        remaining = []
        for order in agent.pending_market_orders:
            shares = int(order.get("shares", 0))
            if shares <= 0:
                continue
            if order["type"] == "buy":
                cost = world.market_price * shares
                if agent.money >= cost:
                    old_cost_basis = agent.last_known_price * agent.shares_owned
                    agent.money -= cost
                    agent.shares_owned += shares
                    agent.last_known_price = (
                        old_cost_basis + cost
                    ) / agent.shares_owned
                    world.net_volume_this_period += shares
                    agent.pending_notifications.append(
                        f"MARKET: Queued buy executed at ${world.market_price:.4f} for {shares} share(s)."
                    )
                else:
                    agent.pending_notifications.append(f"MARKET: Queued buy for {shares} shares failed (insufficient funds).")
            elif order["type"] == "sell":
                if agent.shares_owned >= shares:
                    proceeds = world.market_price * shares
                    agent.money += proceeds
                    agent.shares_owned -= shares
                    if agent.shares_owned == 0:
                        agent.last_known_price = 0.0
                    world.net_volume_this_period -= shares
                    agent.pending_notifications.append(
                        f"MARKET: Queued sell executed at ${world.market_price:.4f} for {shares} share(s)."
                    )
                else:
                    agent.pending_notifications.append(
                        f"MARKET: Queued sell for {shares} shares failed (insufficient shares)."
                    )
        agent.pending_market_orders = remaining

def _update_market_price(world, sim_time: float, dt_seconds: float) -> None:
    p = world.market_price
    if not isinstance(p, (int, float)) or not math.isfinite(p) or p <= 0:
        world.market_price = 100.0
    if is_market_open(sim_time):
        dt_hours = float(dt_seconds) / 3600.0
        shock = np.random.normal()
        gbm_multiplier = math.exp(
            (STOCK_MU - 0.5 * (STOCK_SIGMA**2)) * dt_hours
            + STOCK_SIGMA * math.sqrt(dt_hours) * shock
        )
        if random.random() < (1.0 - math.exp(-JUMP_PROB_PER_HOUR * dt_hours)):
            j = np.random.normal(0.0, JUMP_SIGMA)
            gbm_multiplier *= math.exp(j)
        impact_multiplier = 1.0 + (IMPACT_FACTOR * world.net_volume_this_period)
        impact_multiplier = min(
            IMPACT_CLAMP_HI, max(IMPACT_CLAMP_LO, impact_multiplier)
        )
        new_price = world.market_price * gbm_multiplier * impact_multiplier
        world.market_price = max(10.0, min(1000.0, round(new_price, 4)))
        
        # Government Bailout if crashes
        if world.market_price < 10.0:
            world.market_price = 10.0
            world.global_news.append("Government bailout! Market reset to $10.00.")
            world.global_news = world.global_news[-20:]
            
        world.price_history.append(round(world.market_price, 4))
        if len(world.price_history) > 2016:
            world.price_history.pop(0)
        world.net_volume_this_period = 0

def _update_weather(world) -> None:
    old_weather = world.weather
    if random.random() < 0.05:
        world.weather = random.choice(["Sunny", "Rain", "Snow", "Cloudy"])
    if world.weather != old_weather and world.weather in ["Rain", "Snow"]:
        for agent in world.agents.values():
            if not agent.alive:
                continue
            from python.locations import get_current_location_def
            loc = get_current_location_def(agent.x, agent.y, agent.z)
            if not loc or not loc.has_roof:
                agent.pending_notifications.append(
                    f"It started to {world.weather.lower()}. {world.weather} falls onto your skin."
                )

def _restock_if_needed(world) -> None:
    if world.sim_time - world.last_restock_time >= (7 * 24 * 3600):
        world.store_inventory = dict(BASE_STORE_INVENTORY)
        world.last_restock_time = world.sim_time
        world.global_news.append("Village stores have been restocked for the week.")
        world.global_news = world.global_news[-20:]

def _apply_midnight_taxes(world, tick_time: float) -> None:
    current_day = int(float(tick_time)) // 86400
    if not hasattr(world, "last_tax_day"):
        world.last_tax_day = current_day
        return
    last_tax_day = int(getattr(world, "last_tax_day"))
    if current_day <= last_tax_day:
        return
    for _day in range(last_tax_day + 1, current_day + 1):
        for agent in world.agents.values():
            if not agent.alive:
                continue
            if agent.money < TAX_EXEMPT_BELOW_CASH:
                continue
                
            # Progressive tax scale
            if agent.money > 5000:
                rate = 0.15
            elif agent.money > 1000:
                rate = 0.10
            else:
                rate = 0.05
                
            tax_amount = round(agent.money * rate, 2)
            if tax_amount <= 0:
                continue
            agent.money -= tax_amount
            agent.expenses += tax_amount
            agent.total_expenses += tax_amount
            agent.pending_notifications.append(
                f"Tax deducted: ${tax_amount:.2f} ({rate * 100:.0f}%)"
            )
    world.last_tax_day = current_day

def _apply_passive_updates(agent, world, current_time: float) -> None:
    if not agent.alive:
        return
    if not hasattr(agent, "hydration"):
        agent.hydration = 70.0
    if not hasattr(agent, "dehydration_hours"):
        agent.dehydration_hours = 0
        
    # Clean expired voicemails
    if hasattr(agent, "voicemail_inbox") and agent.voicemail_inbox:
        agent.voicemail_inbox = [vm for vm in agent.voicemail_inbox if (current_time - vm.get("time", current_time)) <= 48 * 3600]

    is_sleeping_now = agent.is_sleeping and agent.busy_until > current_time
    agent.hours_lived += 1
    if not is_sleeping_now:
        agent.awake_hours += 1
    agent.expenses *= 0.99
    
    # Needs Drift (Before Emergency Check)
    agent.hydration = max(0.0, agent.hydration - (1.5 if is_sleeping_now else 4.0))
    hunger_gain = 0.5 if is_sleeping_now else 5.0
    agent.hunger = min(100.0, agent.hunger + hunger_gain)
    
    # Task state prevents passive energy drain
    if not is_sleeping_now and agent.task_state == "idle":
        agent.energy = max(0.0, agent.energy - 2.0)
        
    # Weather Drain
    from python.locations import get_current_location_def
    loc_def = get_current_location_def(agent.x, agent.y, agent.z)
    is_outside = not loc_def or not loc_def.has_roof
    if is_outside and world.weather in ["Rain", "Snow"] and not is_sleeping_now:
        agent.happiness = max(0.0, agent.happiness - 2.0)
        agent.energy = max(0.0, agent.energy - 1.0)
        if world.weather == "Snow":
            agent.health = max(0.0, agent.health - 1.0)
            
    # Emergency Check
    if not is_sleeping_now and agent.hunger >= 90.0:
        _attempt_emergency_consume(agent, world, mode="hunger")
    if not is_sleeping_now and agent.hydration <= 12.0:
        _attempt_emergency_consume(agent, world, mode="thirst")

    # Mental Math
    eps = 1.0
    rel_scaled = min(100.0, (agent.relationships / 5.0) * 100.0)
    happiness_target = (
        0.3 * agent.health
        + 0.3 * rel_scaled
        + 0.4 * 100.0 * math.tanh(agent.money / (agent.expenses + eps))
    )
    agent.happiness = max(
        0.0, min(100.0, agent.happiness * 0.7 + happiness_target * 0.3)
    )
    w1, w2, w3 = 1.0, 2.0, 0.5
    alpha, beta = 0.01, 0.001
    loneliness = max(0.0, 3.0 - agent.relationships) ** 2
    crowding = max(0.0, agent.relationships - 10.0) * 2.0
    rel_tension = w1 * (loneliness + crowding)
    money_floor = max(0.0, agent.money)
    fin_pressure = w2 * (agent.expenses / (money_floor + 1.0))
    market_anxiety = 0.0
    if agent.shares_owned > 0 and len(world.price_history) >= 2:
        price_change = world.price_history[-1] - world.price_history[-2]
        if price_change < 0:
            position_value = agent.shares_owned * world.market_price
            market_anxiety = (
                w3 * abs(price_change) * (position_value / (money_floor + 1.0))
            )
    stress_target = (rel_tension + fin_pressure + market_anxiety) / (
        1.0 + alpha * agent.happiness + beta * agent.hourly_wage
    )
    if agent.hydration < 30.0 and not is_sleeping_now:
        stress_target *= 1.1
    if agent.hydration < 15.0 and not is_sleeping_now:
        stress_target *= 1.25
    stress_penalty = 1.5 if agent.money < 0 else 1.0
    agent.stress = max(
        0.0, min(100.0, agent.stress * 0.7 + (stress_target * stress_penalty) * 0.3)
    )
    
    # Health base Delta
    age_factor = math.exp(0.02 * agent.age)
    energy_penalty = 0.0 if agent.energy > 10.0 else 0.5
    dehydration_penalty = 0.0
    if agent.hydration < 20.0:
        dehydration_penalty = (20.0 - agent.hydration) * 0.2
    delta_h = (
        (
            -(
                0.5 * agent.stress
                + 0.3 * agent.hunger
                + energy_penalty * 10.0
                + dehydration_penalty
            )
            + 0.1 * agent.happiness
        )
        * age_factor
        * 0.02
    )
    agent.health += delta_h
    
    # Starvation/Dehydration Damage (Before Clamp)
    if agent.hunger >= 100.0:
        agent.starvation_hours += 1
        agent.health -= min(32.0, 2**agent.starvation_hours)
    else:
        agent.starvation_hours = 0
        
    if agent.hydration <= 0.0:
        agent.dehydration_hours += 1
        agent.health -= min(16.0, 1.5**agent.dehydration_hours)
    else:
        agent.dehydration_hours = 0
        
    # Clamp Health
    agent.health = max(0.0, min(100.0, agent.health))
    
    # Death Check
    if agent.health <= 0.0:
        from python.tools import kill_agent
        kill_agent(agent, world, cause="passive health collapse")

def _attempt_emergency_consume(agent, world, mode: str = "hunger") -> None:
    from python.tools import ITEM_CATALOG
    if mode == "thirst":
        preferred = {"Water", "Coffee"}
        available = [
            item for item in preferred if world.store_inventory.get(item, 0) > 0
        ]
    else:
        available = [
            item
            for item, data in ITEM_CATALOG["food"].items()
            if data.get("hunger", 0) > 0 and world.store_inventory.get(item, 0) > 0
        ]
        
    def _is_safe_food(item_data) -> bool:
        return (world.sim_time - item_data.get("bought", world.sim_time)) <= 172800

    if mode == "thirst":
        if agent.currently_holding and agent.currently_holding.get("item") in {
            "Water",
            "Coffee",
        } and agent.currently_holding.get("id") != "job_prop" and _is_safe_food(agent.currently_holding):
            held = agent.currently_holding
            fstats = ITEM_CATALOG["food"][held["item"]]
            agent.currently_holding = None
            agent.hunger = max(0.0, agent.hunger - fstats["hunger"])
            agent.hydration = min(100.0, agent.hydration + fstats.get("hydration", 0))
            agent.pending_notifications.append(
                f"Auto-consumed held {held['item']} due to critical thirst."
            )
            return
    else:
        if (
            agent.currently_holding
            and agent.currently_holding.get("item") in ITEM_CATALOG["food"]
        ) and agent.currently_holding.get("id") != "job_prop" and _is_safe_food(agent.currently_holding):
            held_name = agent.currently_holding["item"]
            if ITEM_CATALOG["food"][held_name].get("hunger", 0) > 0:
                held = agent.currently_holding
                fstats = ITEM_CATALOG["food"][held["item"]]
                agent.currently_holding = None
                agent.hunger = max(0.0, agent.hunger - fstats["hunger"])
                agent.hydration = min(
                    100.0, agent.hydration + fstats.get("hydration", 0)
                )
                agent.pending_notifications.append(
                    f"Auto-consumed held {held['item']} due to critical hunger."
                )
                return
                
    idx = -1
    for i, item in enumerate(agent.inventory):
        name = item["item"]
        if name not in ITEM_CATALOG["food"] or item.get("id") == "job_prop":
            continue
        if not _is_safe_food(item):
            continue
        if mode == "thirst" and name not in {"Water", "Coffee"}:
            continue
        if mode == "hunger" and ITEM_CATALOG["food"][name].get("hunger", 0) <= 0:
            continue
        idx = i
        break
        
    if idx != -1:
        eaten = agent.inventory.pop(idx)
        fstats = ITEM_CATALOG["food"][eaten["item"]]
        agent.hunger = max(0.0, agent.hunger - fstats["hunger"])
        agent.hydration = min(100.0, agent.hydration + fstats.get("hydration", 0))
        agent.pending_notifications.append(
            f"Auto-consumed {eaten['item']} due to critical {mode}."
        )
        return
        
    affordable = [
        f for f in available if agent.money >= ITEM_CATALOG["food"][f]["price"]
    ]
    if affordable:
        chosen = min(affordable, key=lambda f: ITEM_CATALOG["food"][f]["price"])
        cost = ITEM_CATALOG["food"][chosen]["price"]
        agent.money -= cost
        agent.expenses += cost
        agent.total_expenses += cost
        fstats = ITEM_CATALOG["food"][chosen]
        agent.hunger = max(0.0, agent.hunger - fstats["hunger"])
        agent.hydration = min(100.0, agent.hydration + fstats.get("hydration", 0))
        world.store_inventory[chosen] -= 1
        agent.pending_notifications.append(
            f"Auto-bought emergency {chosen} (${cost:.2f}) due to critical {mode}."
        )
    else:
        agent.pending_notifications.append(
            f"Critical {mode}! Cannot afford any emergency consumables and have no safe food."
        )

def _apply_interruption_rollback(agent, world) -> None:
    if not agent.alive or getattr(agent, "is_sleeping", False):
        return

    current_time = float(world.sim_time)
    interrupted = False

    if agent.current_activity == "moving" and hasattr(agent, "_transit_meta"):
        meta = getattr(agent, "_transit_meta")
        start_time = meta["start_time"]
        total_time = meta["total_time"]
        ratio = max(0.0, min(1.0, (current_time - start_time) / max(1.0, total_time)))
        
        sx, sy, sz = meta["start_xyz"]
        ex, ey, ez = meta["end_xyz"]
        
        agent.x = sx + (ex - sx) * ratio
        agent.y = sy + (ey - sy) * ratio
        agent.z = sz + (ez - sz) * ratio
        agent.location = "Outside"
        
        agent.energy = min(100.0, agent.energy + meta["energy_cost"] * (1.0 - ratio))
        if meta["fuel_cost"] > 0:
            agent.money += meta["fuel_cost"] * (1.0 - ratio)
            
        delattr(agent, "_transit_meta")
        agent.current_activity = "idle"
        agent.busy_until = current_time
        interrupted = True

    elif getattr(agent, "task_state", "idle") != "idle":
        from python.tooling.handlers.workstudy import _clear_task_state
        _clear_task_state(agent, world, current_time)
        agent.busy_until = min(float(agent.busy_until), current_time)
        interrupted = True

    elif agent.current_activity in ("working", "studying") and hasattr(agent, "_work_meta"):
        meta = getattr(agent, "_work_meta")
        start_time = meta["start_time"]
        total_time = meta["total_time"]
        ratio = max(0.0, min(1.0, (current_time - start_time) / max(1.0, total_time)))
        
        agent.money -= meta.get("pay", 0.0) * (1.0 - ratio)
        agent.education = max(0.0, agent.education - meta.get("edu_gain", 0.0) * (1.0 - ratio))
        agent.hourly_wage = max(0.0, agent.hourly_wage - meta.get("wage_gain", 0.0) * (1.0 - ratio))
        agent.energy = min(100.0, agent.energy + meta.get("energy_spent", 0.0) * (1.0 - ratio))
        
        delattr(agent, "_work_meta")
        agent.current_activity = "idle"
        agent.busy_until = current_time
        interrupted = True

    elif float(agent.busy_until) > current_time:
        agent.busy_until = current_time
        if agent.current_activity not in ("idle", "dead"):
            agent.current_activity = "idle"
        interrupted = True

    if interrupted:
        agent.pending_notifications.append("URGENT: Your activity was interrupted by a social interaction!")