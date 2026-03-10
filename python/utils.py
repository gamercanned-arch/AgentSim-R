import json
import os
import requests

from python.config import (
    SERVER_URL, TOKENIZE_URL, PROMPTS_DIR, TOOLS_PATH,
    MAX_NEW_TOKENS, CHARS_PER_TOKEN,
)
from python.locations import get_distance, LOCATIONS


def count_tokens(text: str) -> int:
    try:
        resp = requests.post(TOKENIZE_URL, json={"content": str(text)}, timeout=5)
        resp.raise_for_status()
        return len(resp.json().get("tokens", []))
    except Exception:
        return len(str(text)) // CHARS_PER_TOKEN


def _market_summary(world) -> str:
    price = world.market_price
    window = world.price_history[-6:] if len(world.price_history) >= 6 else world.price_history[:]
    trend_str = "  ".join(f"${p:.2f}" for p in window)
    if len(window) >= 2:
        delta = window[-1] - window[0]
        pct = (delta / window[0]) * 100.0 if window[0] != 0 else 0.0
        sign = "▲" if delta >= 0 else "▼"
        momentum = f"{sign} {abs(pct):.2f}% over last {len(window)} hours"
    else:
        momentum = "insufficient history"
    return f"Current price : ${price:.2f}\nRecent closes : {trend_str}\nMomentum      : {momentum}"


def build_messages(agent_id: int, world, notifications: str, failed_calls: int) -> list:
    agent = world.agents[agent_id]

    if not agent.system_prompt:
        common, role = "", ""
        common_path = os.path.join(PROMPTS_DIR, "common_prompt.txt")
        if os.path.exists(common_path):
            with open(common_path, encoding="utf-8") as f:
                common = f.read().strip()
                # Strip out the old JSON instruction since Jinja handles XML format now
                common = common.replace("You MUST reply with EXACTLY ONE tool call in this exact format:\n\n<tool_call>{\"name\": \"tool_name\", \"arguments\": {\"param\": \"value\"}}</tool_call>", "")

        for candidate in (agent.name.lower(), agent.name, agent.name.capitalize()):
            fpath = os.path.join(PROMPTS_DIR, f"{candidate}.txt")
            if os.path.exists(fpath):
                with open(fpath, encoding="utf-8") as f:
                    role = f.read().strip()
                break

        agent.system_prompt = f"{common}\n\n{role}"

    proximity_list = []
    for other_id, other in world.agents.items():
        if other_id != agent_id and other.alive:
            dist = get_distance((agent.x, agent.y), (other.x, other.y))
            if dist < 200:
                proximity_list.append(f"{other.name} ({dist:.0f}m)")
    proximity = ", ".join(proximity_list) if proximity_list else "None nearby"

    property_info = "Owned: " + ", ".join(agent.owned_locations) if agent.owned_locations else "Owned: None"
    if agent.current_home: property_info += f", Home: {agent.current_home}"

    inventory_str = ", ".join(f"{k}×{v}" for k, v in agent.inventory.items() if v > 0) or "empty"
    hour_of_day = int((world.sim_time / 3600) % 24)
    pending_reqs = [f"{k.capitalize()} wants to be '{v}'" for k, v in agent.pending_status_requests.items()]
    pending_str = ", ".join(pending_reqs) if pending_reqs else "None"

    user_message_content = f"""Result of previous action: {agent.last_action_result}

=== YOUR CURRENT STATE ===
Health={agent.health:.1f}, Energy={agent.energy:.1f}, Happiness={agent.happiness:.1f}, Stress={agent.stress:.1f}, Hunger={agent.hunger:.1f}
Money=${agent.money:.2f}, Wage=${agent.hourly_wage:.2f}/hr, Job={agent.job}, Education={agent.education:.1f}
Location:      {agent.location}
{property_info}
Nearby people: {proximity}
Hour of day:   {hour_of_day:02d}:00
Notifications: {notifications}
Pending Relationship Requests: {pending_str}
Inventory:     {inventory_str}

=== MARKET ===
{_market_summary(world)}"""

    if failed_calls > 0:
        user_message_content += "\n\n[SYSTEM WARNING]: Your previous output failed to parse. Remember to output exactly one XML <tool_call>."

    agent.chat_history.append({"role": "user", "content": user_message_content})

    return [{"role": "system", "content": agent.system_prompt}] + agent.chat_history


def call_server(messages: list) -> tuple:
    # Load tools array to pass to Jinja
    with open(TOOLS_PATH, encoding="utf-8") as f:
        tools = json.load(f)["tools"]

    payload = {
        "messages": messages,
        "tools": tools,
        "max_tokens": MAX_NEW_TOKENS,
        "temperature": 0.7,
        "top_p": 0.95,
        "stop": ["<|im_end|>"]
    }
    
    try:
        resp = requests.post(SERVER_URL, json=payload, timeout=120)
        resp.raise_for_status()
        
        data = resp.json()
        content = data["choices"][0]["message"].get("content", "").strip()
        usage = data.get("usage", {})
        
        return content, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        
    except Exception as e:
        # Return error string and 0 tokens so the scheduler catches it
        return f"[SERVER ERROR] {str(e)}", 0, 0
    
    try:
        resp = requests.post(SERVER_URL, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"].get("content", "").strip()
    except Exception as e:
        return f"[SERVER ERROR] {str(e)}"