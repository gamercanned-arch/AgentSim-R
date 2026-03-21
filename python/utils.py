import json
import os
import urllib.request
import urllib.error
import jinja2
import subprocess

from config import (PROMPTS_DIR, TOOLS_PATH, MAX_NEW_TOKENS, CHARS_PER_TOKEN, LLAMA_CLI_PATH, SUMMARIZER_MODEL_PATH, SUMMARIZER_PROMPT_TEMPLATE)
from locations import get_distance_3d, get_current_location_def
from tools import ITEM_CATALOG

SERVER_URL = "http://127.0.0.1:8080"
jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader(PROMPTS_DIR))

def _get_time_strings(sim_time: float, return_date=True):
    total_minutes = int(sim_time // 60)
    hour = (total_minutes // 60) % 24
    minute = total_minutes % 60
    day = (total_minutes // 1440) + 1
    if return_date: return f"Day {day}, {hour:02d}:{minute:02d}"
    return hour, minute

def is_market_open(sim_time: float) -> bool:
    h, m = _get_time_strings(sim_time, False)
    if h > 9 or (h == 9 and m >= 30):
        if h < 16: return True
    return False

def trigger_summarizer(agent):
    if len(agent.chat_history) > 22:
        turn_1 = agent.chat_history[:2]
        chunk = agent.chat_history[2:22]
        remainder = agent.chat_history[22:]
        text_chunk = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in chunk])
        
        prompt = SUMMARIZER_PROMPT_TEMPLATE.format(text_chunk=text_chunk)
        
        try:
            res = subprocess.run([LLAMA_CLI_PATH, "-m", SUMMARIZER_MODEL_PATH, "-p", prompt, "-n", "150", "--log-disable"], 
                                 capture_output=True, text=True, timeout=30)
            summary = res.stdout.strip()
        except Exception as e:
            summary = "Summary generation failed."

        agent.chat_history = turn_1 + [{"role": "system", "content": f"[ROLLING MEMORY]: {summary}"}] + remainder

def build_messages(agent_id: int, world, notifications: str, failed_calls: int) -> list:
    agent = world.agents[agent_id]
    trigger_summarizer(agent) 

    if not agent.system_prompt:
        role = ""
        fpath = os.path.join(PROMPTS_DIR, f"{agent.name}.txt")
        if os.path.exists(fpath):
            with open(fpath, encoding="utf-8") as f: role = f.read().strip()
        
        agent.system_prompt = (
            "You are a simulation agent.\nRULES:\n"
            "- Tools cost time. Reply EXACTLY with one <tool_call>.\n"
            "- Protect your Health, Energy, and Finances.\n"
            "- Working/Studying is a 3-step interactive process: 1. Call work_job. 2. Use pick_item to grab the required tool. 3. Use interact_with to answer the scenario.\n"
            "- Use the change_status tool to save your long-term goals into your Beliefs.\n"
            f"- Your Role: {role}\n"
        )

    prox = []
    for o in world.agents.values():
        if o.alive and o.id != agent.id:
            d = get_distance_3d((agent.x, agent.y, agent.z), (o.x, o.y, o.z))
            if d < 100:
                is_busy = (o.busy_until > world.sim_time) or (o.task_state != "idle")
                act = "BUSY: Do Not Disturb" if is_busy else "Available"
                held = f" [Holding {o.currently_holding['item']}]" if o.currently_holding else ""
                prox.append(f"{o.name} ({d:.0f}m) [{act}]{held}")
    
    loc_def = get_current_location_def(agent.x, agent.y, agent.z)
    vision = ""
    if loc_def and loc_def.interactables:
        visible_objs = []
        for obj in loc_def.interactables:
            if abs(obj['z'] - agent.z) < 2:
                if "target_z" in obj: 
                    visible_objs.append(f"{obj['name']} (leads to Z={obj['target_z']})")
                else: 
                    visible_objs.append(obj['name'])
        if visible_objs: vision = "Vision: " + ", ".join(visible_objs)

    inv_str = ", ".join([i['item'] for i in agent.inventory]) or "Empty"
    held_str = agent.currently_holding['item'] if agent.currently_holding else "Nothing"
    news = " | ".join(world.global_news[-3:]) if world.global_news else "None"

    user_msg = f"""[RESULT]: {agent.last_action_result}

[STATE]
Time: {_get_time_strings(world.sim_time)} | Weather: {world.weather}
Loc: {agent.location} (Z={agent.z})
{vision}
Health: {agent.health:.1f} | Energy: {agent.energy:.1f} | Hunger: {agent.hunger:.1f} | Stress: {agent.stress:.1f}
Money: ${agent.money:.2f}
Held: {held_str} | Inv: [{inv_str}]
Beliefs/Goals: {agent.beliefs}

[ENV]
Nearby: {', '.join(prox) or 'None'}
News: {news}
Notifs: {notifications}
"""
    agent.chat_history.append({"role": "user", "content": user_msg})
    return [{"role": "system", "content": agent.system_prompt}] + agent.chat_history

def call_server(messages: list, agent_id: int) -> tuple:
    with open(TOOLS_PATH, encoding="utf-8") as f: tools_list = json.load(f)["tools"]
    template = jinja_env.get_template("template.jinja")
    prompt_text = template.render(messages=messages, tools=tools_list, add_generation_prompt=True)
    
    req = urllib.request.Request(f"{SERVER_URL}/completion", data=json.dumps({
        "prompt": prompt_text, "n_predict": MAX_NEW_TOKENS, "temperature": 0.7, 
        "top_p": 0.95, "stop": ["<|im_end|>"]
    }).encode('utf-8'), headers={'Content-Type': 'application/json'})
    
    try:
        with urllib.request.urlopen(req) as res:
            res_data = json.loads(res.read().decode('utf-8'))
            out = res_data.get("content", "").strip()
            if not out.startswith("<think>"): out = f"<think>\n{out}"
            return out, 0, 0
    except Exception as e: return f"[SERVER ERROR] {e}", 0, 0