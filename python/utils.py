import requests
import json
from python.config import SERVER_URL, PROMPTS_DIR, TOOLS_PATH, MAX_NEW_TOKENS
from python.locations import get_distance, LOCATIONS
import os

def build_prompt(agent_id: int, world, notifications: str, failed_calls: int) -> str:
    with open(f"{PROMPTS_DIR}/common_prompt.txt", encoding="utf-8") as f:
        common = f.read()
    
    agent_names = ["alex", "jamie", "taylor", "jordan", "mia", "ethan"]
    role_file = f"{PROMPTS_DIR}/{agent_names[agent_id]}.txt"
    role = ""
    if os.path.exists(role_file):
        with open(role_file, encoding="utf-8") as f:
            role = f.read()

    agent = world.agents[agent_id]
    
    # Build proximity list
    proximity_list = []
    for other_id, other in world.agents.items():
        if other_id != agent_id and other.alive:
            dist = get_distance((agent.x, agent.y), (other.x, other.y))
            if dist < 50:
                proximity_list.append(f"{other.name} ({dist:.0f}m)")

    proximity = ", ".join(proximity_list) if proximity_list else "None nearby"
    
    # Build owned property info
    if agent.owned_locations:
        owned = ", ".join(agent.owned_locations)
        property_info = f"Owned: {owned}"
        if agent.current_home:
            property_info += f", Home: {agent.current_home}"
    else:
        property_info = "Owned: None"

    metrics = (
        f"Health={agent.health:.1f}, Happiness={agent.happiness:.1f}, "
        f"Stress={agent.stress:.1f}, Hunger={agent.hunger:.1f}, "
        f"Education={agent.education:.1f}, Relationships={agent.relationships}, "
        f"Money=${agent.money:.2f}, Job={agent.job}, Max Income=${agent.max_income:.2f}"
    )

    prompt = f"{common}\n{role}\n\nCurrent state:\n{metrics}\nLocation: {agent.location}\n{property_info}\nProximity: {proximity}\nSim time: {world.sim_time / 60:.1f} minutes\nNotifications: {notifications}"

    if failed_calls >= 3:
        with open(TOOLS_PATH, encoding="utf-8") as f:
            tools = json.load(f)["tools"]
        prompt += "\n\nIMPORTANT REMINDER: You MUST use exactly this format:\n<tool_call>{\"name\": \"example\", \"arguments\": {\"example\": \"value\"}}</tool_call>\nAvailable tools:\n" + json.dumps(tools, indent=2)

    return prompt

def call_server(prompt: str) -> str:
    payload = {
        "prompt": prompt,
        "n_predict": MAX_NEW_TOKENS,
        "temperature": 0.7,
        "top_p": 0.95,
        "top_k": 20,
        "repeat_penalty": 1.1,
        "grammar": r'root ::= "<tool_call>" json_obj "</tool_call>" json_obj ::= "{" "\"name\":" string "," "\"arguments\":" "{" (key_value ",")* key_value? "}" "}" string ::= "\"[^\"]*\"" key_value ::= string ":" string'
    }
    try:
        resp = requests.post(SERVER_URL, json=payload, timeout=90)
        resp.raise_for_status()
        return resp.json()["content"].strip()
    except Exception as e:
        return f"[SERVER ERROR] {str(e)}"
