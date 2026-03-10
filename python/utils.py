import json
import os
import requests

from config import (
    SERVER_URL, TOKENIZE_URL, PROMPTS_DIR, TOOLS_PATH,
    MAX_NEW_TOKENS, CHARS_PER_TOKEN,
)
from locations import get_distance, LOCATIONS


def count_tokens(text: str) -> int:
    try:
        resp = requests.post(
            TOKENIZE_URL,
            json={"content": text},
            timeout=5,
        )
        resp.raise_for_status()
        tokens = resp.json().get("tokens", [])
        return len(tokens)
    except Exception:
        return len(text) // CHARS_PER_TOKEN


def _market_summary(world) -> str:
    price   = world.market_price
    history = world.price_history

    window    = history[-6:] if len(history) >= 6 else history[:]
    trend_str = "  ".join(f"${p:.2f}" for p in window)

    if len(window) >= 2:
        delta    = window[-1] - window[0]
        pct      = (delta / window[0]) * 100.0 if window[0] != 0 else 0.0
        sign     = "▲" if delta >= 0 else "▼"
        momentum = f"{sign} {abs(pct):.2f}% over last {len(window)} hours"
    else:
        momentum = "insufficient history"

    return (
        f"Current price : ${price:.2f}\n"
        f"Recent closes : {trend_str}\n"
        f"Momentum      : {momentum}"
    )


def build_prompt(agent_id: int, world, notifications: str, failed_calls: int) -> str:

    common = ""
    common_path = os.path.join(PROMPTS_DIR, "common_prompt.txt")
    if os.path.exists(common_path):
        with open(common_path, encoding="utf-8") as f:
            common = f.read().strip()

    # role prompt
    agent = world.agents[agent_id]
    role  = ""
    for candidate in (agent.name.lower(), agent.name, agent.name.capitalize()):
        fpath = os.path.join(PROMPTS_DIR, f"{candidate}.txt")
        if os.path.exists(fpath):
            with open(fpath, encoding="utf-8") as f:
                role = f.read().strip()
            break

    # nearby agents
    proximity_list = []
    for other_id, other in world.agents.items():
        if other_id != agent_id and other.alive:
            dist = get_distance((agent.x, agent.y), (other.x, other.y))
            if dist < 200:
                proximity_list.append(f"{other.name} ({dist:.0f}m)")
    proximity = ", ".join(proximity_list) if proximity_list else "None nearby"

    # property summary
    if agent.owned_locations:
        property_info = "Owned: " + ", ".join(agent.owned_locations)
        if agent.current_home:
            property_info += f", Home: {agent.current_home}"
    else:
        property_info = "Owned: None"

    # portfolio summary
    if agent.shares_owned > 0:
        position_value  = agent.shares_owned * world.market_price
        unrealised_gain = (world.market_price - agent.last_known_price) * agent.shares_owned
        gain_str        = (
            f"+${unrealised_gain:.2f}" if unrealised_gain >= 0
            else f"-${abs(unrealised_gain):.2f}"
        )
        portfolio_info = (
            f"Shares: {agent.shares_owned} "
            f"(value ${position_value:.2f}, unrealised P&L {gain_str})"
        )
    else:
        portfolio_info = "Shares: none"

    # pending relationship requests
    pending_reqs = [f"{k.capitalize()} wants to be '{v}'" for k, v in agent.pending_status_requests.items()]
    pending_str = ", ".join(pending_reqs) if pending_reqs else "None"

    # inventory & memory
    inventory_str = (
        ", ".join(f"{k}×{v}" for k, v in agent.inventory.items() if v > 0)
        or "empty"
    )
    memory_str = " → ".join(agent.last_3_actions[-3:]) if agent.last_3_actions else "none yet"

    # time of day
    hour_of_day = int((world.sim_time / 3600) % 24)

    # metrics
    metrics = (
        f"Health={agent.health:.1f}, Energy={agent.energy:.1f}, Happiness={agent.happiness:.1f}, "
        f"Stress={agent.stress:.1f}, Hunger={agent.hunger:.1f}, "
        f"Education={agent.education:.1f}, Relationships={agent.relationships}, "
        f"Money=${agent.money:.2f}, Job={agent.job}, "
        f"Wage=${agent.hourly_wage:.2f}/hr, Age={agent.age}"
    )

    dead_agents = [a.name for a in world.agents.values() if not a.alive]
    if dead_agents:
        verb = "has" if len(dead_agents) == 1 else "have"
        dead_info = f"Note: {', '.join(dead_agents)} {verb} died."
    else:
        dead_info = ""

    market_block = _market_summary(world)
    prompt = f"""{common}
{role}

=== YOUR CURRENT STATE ===
{metrics}
Location:      {agent.location}
{property_info}
{portfolio_info}
Pending Relationship Requests: {pending_str}
Nearby people: {proximity}
Hour of day:   {hour_of_day:02d}:00
Notifications: {notifications}
{dead_info}
Inventory:     {inventory_str}
Recent actions:{memory_str}

=== STOCK MARKET ===
{market_block}

=== ITEM & LOCATION CATALOG (EXACT names only) ===

FOOD (buy_item or eat_food):
  Coffee, Sandwich, Meal, Pizza, Salad, Burger, Soda, Water, Snacks

EVERYDAY ACTIONS (buy_item or sleep):
  Items: Toothbrush, Shampoo, Soap, Clothes, Phone charger, Bus ticket,
         Metro card, Notebook, Pen, Backpack, Umbrella, Socks, Underwear, Towel
  sleep — sleeps for specified hours to restore energy (default 8)

HEALTH (buy_item — consumed immediately):
  Medicine, Vitamins, Gym membership, Bandages, First aid kit, Sunscreen

ENTERTAINMENT (buy_item — consumed immediately):
  Movie ticket, Video game, Book, Streaming subscription,
  Music subscription, Concert ticket, Board game, Puzzle

ELECTRONICS (buy_item):
  Laptop, Tablet, Smart TV, Smartphone, Headphones, Smartwatch, Camera, Speaker

LUXURY (buy_item):
  Watch, Jewelry, Designer bag, Gaming PC, Sunglasses, Perfume

TRANSPORTATION (buy_item):
  Bicycle, Used Car, New Car, Luxury Car, Motorcycle, Scooter

HOUSING (buy_item — moves you in):
  Small Apartment, Apartment, Large Apartment,
  Small House, House, Luxury House, Mansion, Beach House, Cabin

SERVICES (buy_item — consumed immediately):
  Haircut, Laundry, Cleaning service, Taxi ride, Uber ride

VALID LOCATIONS (move_to):
  Home_Alex, Home_Jamie, Home_Taylor, Home_Jordan, Home_Mia, Home_Ethan,
  Hospital, School, Office_FedEx, Startup_Sowl,
  Store_A, Store_B, Market, Bank,
  Park_Central, Cafe, Library, Gym, Theater, Bar, Village_Square,
  Post_Office, Police_Station, Workshop, Art_Studio

WALKING (walk):
  Directions: north, south, east, west, northeast, northwest, southeast, southwest
  Moves 30m in the chosen direction. Updates your position and snaps to nearby location.

STOCK TRADING:
  buy_stock  — buy N shares at current market price
  sell_stock — sell N shares at current market price
"""

    if agent.first_turn or failed_calls >= 3:
        with open(TOOLS_PATH, encoding="utf-8") as f:
            tools = json.load(f)["tools"]
        prompt += f"""
=== AVAILABLE TOOLS ===
{json.dumps(tools, indent=2)}

IMPORTANT: Reply with EXACTLY ONE tool call:
<tool_call>{{"name": "tool_name", "arguments": {{"param1": "value1"}}}}</tool_call>

Do NOT write anything outside the tags.
Consider your stats, energy, location, money, hunger, stress, proximity, inventory, portfolio, and personality.
"""
        agent.first_turn = False

    return prompt


def call_server(prompt: str) -> str:
    payload = {
        "prompt":         prompt,
        "n_predict":      MAX_NEW_TOKENS,
        "temperature":    0.7,
        "top_p":          0.95,
        "top_k":          20,
        "repeat_penalty": 1.1,
    }
    try:
        resp = requests.post(SERVER_URL, json=payload, timeout=90)
        resp.raise_for_status()
        return resp.json()["content"].strip()
    except Exception as e:
        return f"[SERVER ERROR] {str(e)}"