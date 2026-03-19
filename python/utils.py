import json
import os
import subprocess
import tempfile
import jinja2
import re

from config import (PROMPTS_DIR, TOOLS_PATH, MAX_NEW_TOKENS, CHARS_PER_TOKEN, CONTEXT_SIZE)
from locations import get_distance, LOCATIONS
from tools import ITEM_CATALOG

LLAMA_CLI_PATH = "/content/llama.cpp/build/bin/llama-cli"
MODEL_PATH = "/content/models/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf"

jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader(PROMPTS_DIR))

def raise_exception(msg):
    raise ValueError(msg)
jinja_env.globals['raise_exception'] = raise_exception

def count_tokens(text: str) -> int:
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
                common = re.sub(r'You MUST reply with EXACTLY ONE tool call.*?</tool_call>', '', common, flags=re.DOTALL)

        for candidate in (agent.name.lower(), agent.name, agent.name.capitalize()):
            fpath = os.path.join(PROMPTS_DIR, f"{candidate}.txt")
            if os.path.exists(fpath):
                with open(fpath, encoding="utf-8") as f:
                    role = f.read().strip()
                break

        agent.system_prompt = f"{common}\n\n{role}".strip()

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
    
    valid_places = ", ".join(sorted(LOCATIONS.keys()))
    valid_foods = ", ".join(sorted([k for k in ITEM_CATALOG["food"].keys()]))
    valid_items = ", ".join(sorted([k for cat, items in ITEM_CATALOG.items() for k in items.keys() if cat != "food"]))

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
{_market_summary(world)}

=== REFERENCE MENUS ===
Valid Locations (for move_to): {valid_places}
Food Menu (for eat_food): {valid_foods}
Item Catalog (for buy_item): {valid_items}"""

    if failed_calls > 0 and getattr(agent, 'last_parse_error', False):
        user_message_content += "\n\n[SYSTEM WARNING]: Your previous output failed to parse. Make sure to use the <tool_call><function=...><parameter=...></parameter></function></tool_call> format exactly."

    agent.chat_history.append({"role": "user", "content": user_message_content})

    return [{"role": "system", "content": agent.system_prompt}] + agent.chat_history


def call_server(messages: list) -> tuple:
    with open(TOOLS_PATH, encoding="utf-8") as f:
        tools_list = json.load(f)["tools"]

    template = jinja_env.get_template("template.jinja")
    prompt_text = template.render(
        messages=messages,
        tools=tools_list,
        add_generation_prompt=True
    )
    
    with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8") as f:
        f.write(prompt_text)
        temp_path = f.name
        
    cmd = [
        LLAMA_CLI_PATH,
        "-m", MODEL_PATH,
        "-c", str(CONTEXT_SIZE),      
        "-n", str(MAX_NEW_TOKENS),    
        "--temp", "0.7",
        "--top-p", "0.95",
        "-ngl", "999",                
        "--flash-attn",               
        "-ctk", "q8_0",               
        "-ctv", "q8_0",               
        "-f", temp_path,              
        "--no-display-prompt",        
        "--log-disable"               
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout.strip()
        output = output.replace("<|im_end|>", "").strip()
        
        if not output.startswith("<think>"):
            output = f"<think>\n{output}"
        
        prompt_tokens = len(prompt_text) // CHARS_PER_TOKEN
        gen_tokens = len(output) // CHARS_PER_TOKEN
        
        return output, prompt_tokens, gen_tokens
        
    except subprocess.CalledProcessError as e:
        # LOUD CRASH CAPTURE
        error_msg = f"[SERVER ERROR] CLI Failed (Return Code {e.returncode}):\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}"
        return error_msg, 0, 0
    except Exception as e:
        return f"[SERVER ERROR] System Exception: {str(e)}", 0, 0
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)