import json
import random
import re
from state import WorldState
from locations import get_distance, LOCATIONS

# ── item catalog ─────────────────────────────────────────────────────

ITEM_CATALOG = {
    "food": {
        "Coffee": 5, "Sandwich": 8, "Meal": 15, "Pizza": 12,
        "Salad": 10, "Burger": 9, "Soda": 3, "Water": 2, "Snacks": 6,
    },
    "everyday": {
        "Toothbrush": 5, "Shampoo": 8, "Soap": 4, "Clothes": 50,
        "Phone charger": 20, "Bus ticket": 3, "Metro card": 25,
        "Notebook": 5, "Pen": 2, "Backpack": 40, "Umbrella": 15,
        "Socks": 10, "Underwear": 15, "Towel": 12,
    },
    "entertainment": {
        "Movie ticket": 15, "Video game": 60, "Book": 18,
        "Streaming subscription": 15, "Music subscription": 10,
        "Concert ticket": 80, "Board game": 30, "Puzzle": 20,
    },
    "health": {
        "Medicine": 12, "Vitamins": 25, "Gym membership": 50,
        "Bandages": 8, "First aid kit": 30, "Sunscreen": 15,
    },
    "housing": {
        "Small Apartment": 75_000,  "Apartment": 120_000,
        "Large Apartment": 200_000, "Small House": 250_000,
        "House": 400_000,           "Luxury House": 750_000,
        "Mansion": 1_500_000,       "Beach House": 500_000,
        "Cabin": 150_000,
    },
    "transportation": {
        "Bicycle": 300,       "Used Car": 15_000,  "New Car": 35_000,
        "Luxury Car": 80_000, "Motorcycle": 10_000, "Scooter": 2_500,
    },
    "luxury": {
        "Watch": 500, "Jewelry": 1_500, "Designer bag": 2_000,
        "Gaming PC": 3_000, "Sunglasses": 250, "Perfume": 80,
    },
    "electronics": {
        "Laptop": 1_200, "Tablet": 600,   "Smart TV": 800,
        "Smartphone": 900, "Headphones": 200, "Smartwatch": 350,
        "Camera": 700, "Speaker": 150,
    },
    "services": {
        "Haircut": 25, "Laundry": 15, "Cleaning service": 60,
        "Taxi ride": 25, "Uber ride": 30,
    },
}

CONSUMABLE_EFFECTS = {
    "Haircut":                {"happiness": +3},
    "Laundry":                {"happiness": +2},
    "Cleaning service":       {"happiness": +4, "stress": -3},
    "Taxi ride":              {"happiness": +1},
    "Uber ride":              {"happiness": +1},
    "Medicine":               {"health": +10, "stress": -2},
    "Vitamins":               {"health": +5,  "happiness": +1},
    "Gym membership":         {"health": +8,  "stress": -5, "happiness": +5},
    "Bandages":               {"health": +8},
    "First aid kit":          {"health": +15, "stress": -2},
    "Sunscreen":              {"health": +2,  "happiness": +1},
    "Movie ticket":           {"happiness": +5, "stress": -3},
    "Video game":             {"happiness": +4, "stress": -2},
    "Book":                   {"happiness": +3, "stress": -1},
    "Streaming subscription": {"happiness": +3, "stress": -1},
    "Music subscription":     {"happiness": +2, "stress": -1},
    "Concert ticket":         {"happiness": +8, "stress": -5},
    "Board game":             {"happiness": +4, "stress": -2},
    "Puzzle":                 {"happiness": +3, "stress": -1},
}

HOUSE_LOCATIONS = {
    "Small Apartment": "Apartment_Small",
    "Apartment":       "Apartment_Medium",
    "Large Apartment": "Apartment_Large",
    "Small House":     "House_Small",
    "House":           "House_Medium",
    "Luxury House":    "House_Luxury",
    "Mansion":         "Estate_Mansion",
    "Beach House":     "House_Beach",
    "Cabin":           "House_Cabin",
}

SOCIAL_COOLDOWN = 600.0

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))

def get_item_price(item_name: str) -> tuple:
    for category, items in ITEM_CATALOG.items():
        if item_name in items:
            base = items[item_name]
            if category == "housing":
                price = float(base) * random.uniform(0.97, 1.03)
            else:
                price = base * random.uniform(0.9, 1.1)
            return price, category, item_name
    return 0.0, "", ""

def is_housing_item(item_name: str) -> bool:
    return item_name in HOUSE_LOCATIONS

def is_consumable_item(item_name: str) -> bool:
    return item_name in CONSUMABLE_EFFECTS

def get_house_location(item_name: str) -> tuple:
    loc_name = HOUSE_LOCATIONS.get(item_name)
    if loc_name and loc_name in LOCATIONS:
        return LOCATIONS[loc_name]
    return None

def _record_expense(agent, amount: float) -> None:
    agent.expenses       += amount
    agent.total_expenses += amount

def _validate_shares(raw) -> tuple:
    try:
        val = float(raw)
        if not val.is_integer():
            return 0, "Shares must be a whole number."
        shares = int(val)
        if shares <= 0:
            return 0, "Shares must be greater than zero."
        return shares, None
    except (ValueError, TypeError):
        return 0, "Invalid number of shares."

def _check_social_cooldown(agent, target_name: str, sim_time: float) -> bool:
    key  = target_name.lower()
    last = agent.social_cooldowns.get(key, -SOCIAL_COOLDOWN)
    if sim_time - last >= SOCIAL_COOLDOWN:
        agent.social_cooldowns[key] = sim_time
        return True
    return False

def parse_tool_call(tool_call_str: str) -> tuple:
    try:
        # 1. Isolate the <tool_call> block, safely ignoring <think> or surrounding text
        call_match = re.search(r'<tool_call>(.*?)</tool_call>', tool_call_str, re.DOTALL)
        if not call_match:
            return "Parse error: No <tool_call> tags found.", {}
            
        block = call_match.group(1)
        
        # 2. Extract the function name
        func_match = re.search(r'<function=([^>]+)>(.*?)</function>', block, re.DOTALL)
        if not func_match:
            return "Parse error: No <function=name> tag found.", {}
        
        name = func_match.group(1).strip()
        params_block = func_match.group(2)
        
        # 3. Extract the parameters
        args = {}
        param_matches = re.finditer(r'<parameter=([^>]+)>(.*?)</parameter>', params_block, re.DOTALL)
        for p in param_matches:
            p_name = p.group(1).strip()
            p_value = p.group(2).strip()
            args[p_name] = p_value
            
        return name, args
    except Exception as e:
        return f"Parse error: {e}", {}


# ── tool execution ───────────────────────────────────────────────────

def execute_tool(tool_call_str: str, agent_id: int, world: WorldState) -> tuple:
    name, args = parse_tool_call(tool_call_str)
    if isinstance(name, str) and name.startswith("Parse error"):
        return name, False, 60
    if not name:
        return "No tool name found.", False, 60

    agent = world.agents.get(agent_id)
    if not agent or not agent.alive:
        return "Agent inactive.", False, 0

    time_costs = {
        "move_to":          300,
        "walk":              60,
        "buy_item":         120,
        "eat_food":          60,
        "work_job":        3600,
        "talk_to":          300,
        "interact_with":    180,
        "seek_medicalcare": 600,
        "get_education":   3600,
        "call_person":       60,
        "change_status":     30,
        "attack_person":     60,
        "buy_stock":         60,
        "sell_stock":        60,
        "sleep":          28800,
    }
    
    time_cost = time_costs.get(name, 300)
    agent.last_action_time = world.sim_time + time_cost

    # ── sleep ────────────────────────────────────────────────────────
    if name == "sleep":
        hours = args.get("hours", 8)
        try:
            hours = float(hours)
        except (ValueError, TypeError):
            hours = 8.0
        hours = max(1.0, min(12.0, hours))
        sleep_cost = int(hours * 3600)
        
        agent.energy = min(100.0, agent.energy + (hours * 10.0))
        agent.stress = max(0.0, agent.stress - (hours * 2.0))
        agent.health = min(100.0, agent.health + (hours * 1.0))
        
        return (
            f"Slept for {hours:.1f} hours. "
            f"Energy: {agent.energy:.1f}, Health: {agent.health:.1f}."
        ), True, sleep_cost

    # ── move_to ──────────────────────────────────────────────────────
    if name == "move_to":
        place = str(args.get("place", ""))[:50]
        if not place:
            return "No place specified.", False, 60
        if place not in LOCATIONS:
            return f"Unknown place: '{place}'. Check VALID LOCATIONS list.", False, 60
        agent.location   = place
        agent.x, agent.y = LOCATIONS[place]
        return f"Moved to {place}.", True, time_cost

    # ── walk ─────────────────────────────────────────────────────────
    if name == "walk":
        direction = str(args.get("direction", "")).strip().lower()[:20]
        diag = 30.0 / (2 ** 0.5)
        direction_map = {
            "north":     ( 0,      30),
            "south":     ( 0,     -30),
            "east":      ( 30,      0),
            "west":      (-30,      0),
            "northeast": ( diag,  diag),
            "northwest": (-diag,  diag),
            "southeast": ( diag, -diag),
            "southwest": (-diag, -diag),
        }
        delta = direction_map.get(direction)
        if delta is None:
            valid = ", ".join(sorted(direction_map.keys()))
            return f"Invalid direction: '{direction}'. Valid: {valid}.", False, 60

        new_x = _clamp(agent.x + delta[0], 0.0, 5000.0)
        new_y = _clamp(agent.y + delta[1], 0.0, 5000.0)
        agent.x, agent.y = new_x, new_y

        nearest_name = agent.location
        nearest_dist = float("inf")
        for loc_name, loc_coords in LOCATIONS.items():
            d = get_distance((new_x, new_y), loc_coords)
            if d < nearest_dist:
                nearest_dist = d
                nearest_name = loc_name

        if nearest_dist <= 50:
            agent.location = nearest_name
        else:
            agent.location = f"Near {nearest_name} ({nearest_dist:.0f}m away)"

        return (
            f"Walked {direction}. Position: ({new_x:.0f}, {new_y:.0f}). "
            f"Location: {agent.location}."
        ), True, time_cost

    # ── buy_item ─────────────────────────────────────────────────────
    if name == "buy_item":
        item = str(args.get("item", ""))[:50]
        if not item:
            return "No item specified.", False, 60

        price, category, _ = get_item_price(item)
        if price == 0:
            return f"Unknown item: '{item}'. Check ITEM CATALOG.", False, 60
        if agent.money < price:
            return (
                f"Not enough money to buy {item}. "
                f"Need ${price:.2f}, have ${agent.money:.2f}."
            ), False, 60

        if is_housing_item(item):
            sell_price = 0.0
            old_home   = agent.current_home
            if old_home:
                old_price, _, _ = get_item_price(old_home)
                sell_price = old_price * 0.7
                agent.money += sell_price
                if old_home in agent.owned_locations:
                    agent.owned_locations.remove(old_home)

            agent.money -= price
            _record_expense(agent, price)
            agent.owned_locations.append(item)
            agent.current_home = item

            coords = get_house_location(item)
            if coords:
                agent.x, agent.y = coords
                agent.location = HOUSE_LOCATIONS[item]

            prefix = f"Sold {old_home} for ${sell_price:.2f}. " if sell_price > 0 else ""
            return (
                f"{prefix}Purchased {item} for ${price:.2f}. "
                f"Moved to {agent.location}."
            ), True, time_cost

        if is_consumable_item(item):
            agent.money -= price
            _record_expense(agent, price)
            effects = CONSUMABLE_EFFECTS.get(item, {})
            agent.happiness = _clamp(agent.happiness + effects.get("happiness", 0))
            agent.stress    = _clamp(agent.stress    + effects.get("stress",    0))
            agent.health    = _clamp(agent.health    + effects.get("health",    0))
            return (
                f"Used {item} (${price:.2f}). "
                f"Health: {agent.health:.1f}, Happiness: {agent.happiness:.1f}, "
                f"Stress: {agent.stress:.1f}. Money: ${agent.money:.2f}."
            ), True, time_cost

        agent.money -= price
        _record_expense(agent, price)
        agent.inventory[item] = agent.inventory.get(item, 0) + 1
        return (
            f"Bought {item} for ${price:.2f}. "
            f"Inventory: {agent.inventory[item]}×{item}. "
            f"Money: ${agent.money:.2f}."
        ), True, time_cost

    # ── buy_stock ────────────────────────────────────────────────────
    if name == "buy_stock":
        shares, err = _validate_shares(args.get("shares", 0))
        if err:
            return err, False, 60

        price_per_share = world.market_price
        total_cost      = price_per_share * shares
        if agent.money < total_cost:
            return (
                f"Cannot afford {shares} share(s). "
                f"Cost: ${total_cost:.2f}, have ${agent.money:.2f}."
            ), False, 60

        agent.money -= total_cost
        _record_expense(agent, total_cost)

        old_cost_basis = agent.last_known_price * agent.shares_owned
        agent.shares_owned += shares
        agent.last_known_price = (old_cost_basis + total_cost) / agent.shares_owned

        world.net_volume_this_period += shares

        return (
            f"Bought {shares} share(s) at ${price_per_share:.2f} each "
            f"(total ${total_cost:.2f}). "
            f"Holdings: {agent.shares_owned} share(s). "
            f"Money: ${agent.money:.2f}."
        ), True, time_cost

    # ── sell_stock ───────────────────────────────────────────────────
    if name == "sell_stock":
        shares, err = _validate_shares(args.get("shares", 0))
        if err:
            return err, False, 60
        if agent.shares_owned < shares:
            return (
                f"You only own {agent.shares_owned} share(s), "
                f"cannot sell {shares}."
            ), False, 60

        price_per_share = world.market_price
        proceeds        = price_per_share * shares
        gain            = proceeds - (agent.last_known_price * shares)

        agent.money        += proceeds
        agent.shares_owned -= shares
        if agent.shares_owned == 0:
            agent.last_known_price = 0.0

        world.net_volume_this_period -= shares

        gain_str = f"+${gain:.2f}" if gain >= 0 else f"-${abs(gain):.2f}"
        return (
            f"Sold {shares} share(s) at ${price_per_share:.2f} each "
            f"(proceeds ${proceeds:.2f}, P&L {gain_str}). "
            f"Holdings: {agent.shares_owned} share(s). "
            f"Money: ${agent.money:.2f}."
        ), True, time_cost

    # ── eat_food ─────────────────────────────────────────────────────
    if name == "eat_food":
        item = str(args.get("item", ""))[:50]
        if not item:
            return "No food item specified.", False, 60

        food_menu = ITEM_CATALOG.get("food", {})
        if item not in food_menu:
            return (
                f"'{item}' is not a food item. "
                f"Available: {', '.join(food_menu.keys())}."
            ), False, 60

        if agent.inventory.get(item, 0) > 0:
            agent.inventory[item] -= 1
            source = "from inventory"
            cost   = 0.0
        else:
            cost = food_menu[item] * random.uniform(0.9, 1.1)
            if agent.money < cost:
                return (
                    f"No {item} in inventory and cannot afford it "
                    f"(${cost:.2f}). Have ${agent.money:.2f}."
                ), False, 60
            agent.money -= cost
            _record_expense(agent, cost)
            source = f"purchased (${cost:.2f})"

        hunger_reduction = {
            "Coffee": 5, "Soda": 10, "Water": 10, "Snacks": 15,
            "Sandwich": 25, "Salad": 30, "Burger": 35,
            "Pizza": 40,   "Meal": 50,
        }.get(item, 20)

        agent.hunger = max(0.0,   agent.hunger - hunger_reduction)
        agent.health = min(100.0, agent.health + 2.0)
        agent.energy = min(100.0, agent.energy + 5.0)

        msg = (
            f"Ate {item} ({source}). "
            f"Hunger: {agent.hunger:.1f}, Health: {agent.health:.1f}."
        )
        if cost > 0:
            msg += f" Money: ${agent.money:.2f}."
        return msg, True, time_cost

    # ── work_job ─────────────────────────────────────────────────────
    if name == "work_job":
        if agent.energy < 10.0:
            return "Too tired to work. Please use sleep tool to restore energy.", False, 60
            
        jobname = str(args.get("jobname", ""))[:50]
        if not jobname:
            return "No job specified.", False, 60

        job_lower = jobname.lower()
        hours_worked = time_cost / 3600.0
        pay = agent.hourly_wage * hours_worked

        workplace_map = {
            "nurse":    "Hospital",     "doctor":    "Hospital",
            "medical":  "Hospital",     "teacher":   "School",
            "tutor":    "School",       "education": "School",
            "delivery": "Office_FedEx", "driver":    "Office_FedEx",
            "fedex":    "Office_FedEx", "startup":   "Startup_Sowl",
            "founder":  "Startup_Sowl", "tech":      "Startup_Sowl",
        }
        required_place = None
        for key, place in workplace_map.items():
            if key in job_lower:
                required_place = place
                break

        if required_place and required_place in LOCATIONS:
            dist = get_distance((agent.x, agent.y), LOCATIONS[required_place])
            if dist > 150:
                return (
                    f"Must be near {required_place} to work as {jobname} "
                    f"({dist:.0f}m away)."
                ), False, 60

        agent.job    = jobname
        agent.money += pay
        agent.stress  = min(100.0, agent.stress  + 5.0)
        agent.hunger  = min(100.0, agent.hunger  + 10.0)
        agent.energy  = max(0.0, agent.energy - 15.0)

        return (
            f"Worked as {jobname} for {hours_worked:.1f}h. Earned ${pay:.2f}. "
            f"Money: ${agent.money:.2f}, Energy: {agent.energy:.1f}, Stress: {agent.stress:.1f}."
        ), True, time_cost

    # ── attack_person ────────────────────────────────────────────────
    if name == "attack_person":
        target_name = str(args.get("person", ""))[:50]
        if not target_name:
            return "No target specified.", False, 60

        target_agent = next(
            (a for a in world.agents.values()
             if a.name.lower() == target_name.lower() and a.alive),
            None,
        )
        if target_agent is None:
            return f"Target '{target_name}' not found or not alive.", False, 60
        if target_agent.id == agent.id:
            return "You cannot attack yourself.", False, 60

        dist = get_distance((agent.x, agent.y), (target_agent.x, target_agent.y))
        if dist > 20:
            return f"Target too far ({dist:.0f}m). Must be within 20m.", False, 60

        damage = random.uniform(5, 25)
        target_agent.health = max(0.0,   target_agent.health - damage)
        target_agent.stress = min(100.0, target_agent.stress + 15.0)
        agent.stress        = min(100.0, agent.stress        + 10.0)

        target_agent.pending_notifications.append(
            f"{agent.name} attacked you! ({damage:.1f} damage)"
        )

        result_msg = (
            f"Attacked {target_name}, dealt {damage:.1f} damage. "
            f"Their health: {target_agent.health:.1f}."
        )
        if target_agent.health <= 0:
            target_agent.alive = False
            from logger import log_death, log_global
            log_death(target_agent)
            log_global({
                "event":     "agent_death",
                "agent":     target_agent.name,
                "killed_by": agent.name,
                "sim_time":  world.sim_time,
            })
            result_msg += " TARGET DIED!"

        return result_msg, True, time_cost

    # ── talk_to ──────────────────────────────────────────────────────
    if name == "talk_to":
        target_name = str(args.get("person", ""))[:50]
        message     = str(args.get("message", "")).strip()[:300]  # sanitize & cap length

        if not target_name:
            return "No person specified.", False, 60
        if not message:
            return "Must provide a non-empty 'message'.", False, 60

        target_agent = next(
            (a for a in world.agents.values()
             if a.name.lower() == target_name.lower() and a.alive),
            None,
        )
        if target_agent is None:
            return f"'{target_name}' not found or not alive.", False, 60
        if target_agent.id == agent.id:
            return "You cannot talk to yourself.", False, 60

        dist = get_distance((agent.x, agent.y), (target_agent.x, target_agent.y))
        if dist > 50:
            return f"{target_name} is too far ({dist:.0f}m). Must be within 50m.", False, 60

        msg_lower = message.lower()
        if any(w in msg_lower for w in ["help", "sorry", "thanks", "please"]):
            happiness_delta, target_stress_delta = 4, 0
        elif any(w in msg_lower for w in ["insult", "hate", "stupid", "shut up"]):
            happiness_delta, target_stress_delta = -5, 10
        else:
            happiness_delta, target_stress_delta = 1, 0

        if happiness_delta >= 0:
            agent.stress = max(0.0, agent.stress - 2.0)
        else:
            agent.stress = min(100.0, agent.stress + 5.0)

        agent.happiness        = _clamp(agent.happiness        + happiness_delta)
        target_agent.happiness = _clamp(target_agent.happiness + happiness_delta)
        target_agent.stress    = _clamp(target_agent.stress    + target_stress_delta)

        rel_changed = False
        if _check_social_cooldown(agent, target_name, world.sim_time):
            rel_changed = True
            if happiness_delta > 0:
                agent.relationships        = min(25, agent.relationships + 1)
                target_agent.relationships = min(25, target_agent.relationships + 1)
            elif happiness_delta < 0:
                agent.relationships        = max(0, agent.relationships - 1)
                target_agent.relationships = max(0, target_agent.relationships - 1)

        target_agent.pending_notifications.append(
            f"{agent.name} said to you: \"{message}\""
        )
        
        cooldown_msg = "" if rel_changed else " (Relationship unchanged: too soon since last interaction)."
        return (
            f"Talked to {target_name}: \"{message}\". "
            f"Happiness: {agent.happiness:.1f}.{cooldown_msg}"
        ), True, time_cost

    # ── seek_medicalcare ─────────────────────────────────────────────
    if name == "seek_medicalcare":
        hospital_pos = LOCATIONS.get("Hospital")
        if hospital_pos:
            dist = get_distance((agent.x, agent.y), hospital_pos)
            if dist > 150:
                return (
                    f"Must be near Hospital to seek medical care "
                    f"({dist:.0f}m away). Use move_to first."
                ), False, 60

        cost = 50.0
        if agent.money < cost:
            return (
                f"Cannot afford medical care. "
                f"Need ${cost:.2f}, have ${agent.money:.2f}."
            ), False, 60

        agent.money  -= cost
        _record_expense(agent, cost)
        agent.health  = min(100.0, agent.health  + 30.0)
        agent.stress  = max(0.0,   agent.stress  - 10.0)

        return (
            f"Received medical care. "
            f"Health: {agent.health:.1f}, Stress: {agent.stress:.1f}, "
            f"Money: ${agent.money:.2f}."
        ), True, time_cost

    # ── get_education ────────────────────────────────────────────────
    if name == "get_education":
        if agent.energy < 10.0:
            return "Too tired to study. Please sleep.", False, 60

        edu_type = str(args.get("type", "")).strip()[:50]
        if not edu_type:
            return "No education type specified.", False, 60

        edu_lower = edu_type.lower()

        formal_keywords = [
            "high", "bachelor", "college", "university",
            "master", "phd", "doctorate",
        ]
        required_place = (
            "School" if any(k in edu_lower for k in formal_keywords) else "Library"
        )
        if required_place in LOCATIONS:
            dist = get_distance((agent.x, agent.y), LOCATIONS[required_place])
            if dist > 150:
                return (
                    f"Must be near {required_place} for {edu_type} "
                    f"({dist:.0f}m away). Use move_to first."
                ), False, 60

        edu_costs = {
            "high_school":   500, "highschool":     500, "high": 500,
            "bachelors":    2000, "bachelor": 2000, "college":        2000, "university": 2500,
            "masters":      4000, "master":         4000,
            "phd":          8000, "doctorate":      8000,
            "technical":    1000, "certification":   800,
            "online":        300, "course":          200,
        }

        cost     = 300
        edu_gain = 10
        for edu_key, edu_cost in edu_costs.items():
            if edu_key in edu_lower:
                cost = edu_cost
                if "phd" in edu_key or "doctorate" in edu_key:
                    edu_gain = 30
                elif "master" in edu_key:
                    edu_gain = 25
                elif "bachelor" in edu_key or "college" in edu_key or "university" in edu_key:
                    edu_gain = 20
                elif "high" in edu_key:
                    edu_gain = 15
                break

        if agent.money < cost:
            return (
                f"Cannot afford {edu_type}. "
                f"Need ${cost:.2f}, have ${agent.money:.2f}."
            ), False, 60

        agent.money     -= cost
        _record_expense(agent, cost)
        agent.education  = min(100.0, agent.education + edu_gain)
        agent.energy     = max(0.0, agent.energy - 10.0)

        wage_increase = edu_gain * 0.2
        agent.hourly_wage += wage_increase

        return (
            f"Completed {edu_type}. "
            f"Education: {agent.education:.1f}. "
            f"Wage increased by ${wage_increase:.2f} to ${agent.hourly_wage:.2f}/hr."
        ), True, time_cost

    # ── call_person ──────────────────────────────────────────────────
    if name == "call_person":
        target_name = str(args.get("person", ""))[:50]
        message     = str(args.get("message", "")).strip()[:300]

        if not target_name:
            return "No person specified.", False, 60
        if not message:
            return "Must provide a non-empty 'message'.", False, 60

        target_agent = next(
            (a for a in world.agents.values()
             if a.name.lower() == target_name.lower() and a.alive),
            None,
        )
        if target_agent is None:
            return f"'{target_name}' not found or not alive.", False, 60
        if target_agent.id == agent.id:
            return "You cannot call yourself.", False, 60

        call_cost = 1.0
        if agent.money < call_cost:
            return f"Cannot afford call (${call_cost:.2f}).", False, 60

        agent.money -= call_cost
        _record_expense(agent, call_cost)

        msg_lower = message.lower()
        if any(w in msg_lower for w in ["help", "sorry", "thanks", "please", "love", "miss"]):
            happiness_delta, target_stress_delta = 4, 0
        elif any(w in msg_lower for w in ["hate", "stupid", "shut up", "idiot", "fuck"]):
            happiness_delta, target_stress_delta = -5, 10
        else:
            happiness_delta, target_stress_delta = 1, 0

        if happiness_delta >= 0:
            agent.stress = max(0.0, agent.stress - 3.0)
        else:
            agent.stress = min(100.0, agent.stress + 5.0)

        agent.happiness        = _clamp(agent.happiness        + happiness_delta)
        target_agent.happiness = _clamp(target_agent.happiness + happiness_delta)
        target_agent.stress    = _clamp(target_agent.stress    + target_stress_delta)

        rel_changed = False
        if _check_social_cooldown(agent, target_name, world.sim_time):
            rel_changed = True
            if happiness_delta > 0:
                agent.relationships        = min(25, agent.relationships + 1)
                target_agent.relationships = min(25, target_agent.relationships + 1)
            elif happiness_delta < 0:
                agent.relationships        = max(0, agent.relationships - 1)
                target_agent.relationships = max(0, target_agent.relationships - 1)

        target_agent.pending_notifications.append(
            f"{agent.name} called you: \"{message}\""
        )
        
        cooldown_msg = "" if rel_changed else " (Relationship unchanged: too soon since last interaction)."
        return (
            f"Called {target_name}: \"{message}\". "
            f"Happiness: {agent.happiness:.1f}, Stress: {agent.stress:.1f}.{cooldown_msg}"
        ), True, time_cost

    # ── interact_with ────────────────────────────────────────────────
    if name == "interact_with":
        target = str(args.get("person_or_object", "")).strip()[:50]
        action = str(args.get("action", "generic")).lower()[:50]

        if not target:
            return "No person specified.", False, 60

        target_agent = next(
            (a for a in world.agents.values()
             if a.name.lower() == target.lower() and a.alive),
            None,
        )

        if target_agent:
            if target_agent.id == agent.id:
                return "You cannot interact with yourself.", False, 60

            dist = get_distance((agent.x, agent.y), (target_agent.x, target_agent.y))
            if dist > 20:
                return f"{target} is too far ({dist:.0f}m). Must be within 20m.", False, 60

            speaker_happiness = 2
            target_happiness  = 2
            target_stress     = 0
            notification      = f"{agent.name} interacted with you ({action})."

            if action in ["hug", "hold_hand", "pat_back"]:
                speaker_happiness = 5
                if target_agent.relationships < 3:
                    target_happiness = -5
                    target_stress    = 12
                    notification     = (
                        f"{agent.name} tried to hug/hold you (felt uncomfortable)."
                    )
                else:
                    target_happiness = 5
                    notification     = f"{agent.name} hugged/held you."
            elif action in ["wave", "smile", "high_five"]:
                speaker_happiness = 3
                target_happiness  = 3
                notification      = f"{agent.name} waved/smiled at you."
            elif action in ["stare", "shove", "knock_shoulder"]:
                speaker_happiness = -2
                target_happiness  = -4
                target_stress     = 8
                notification      = f"{agent.name} {action}d you."

            agent.happiness        = _clamp(agent.happiness        + speaker_happiness)
            target_agent.happiness = _clamp(target_agent.happiness + target_happiness)
            target_agent.stress    = _clamp(target_agent.stress    + target_stress)

            rel_changed = False
            if _check_social_cooldown(agent, target, world.sim_time):
                rel_changed = True
                if speaker_happiness > 0 and target_happiness > 0:
                    agent.relationships        = min(25, agent.relationships + 1)
                    target_agent.relationships = min(25, target_agent.relationships + 1)
                elif target_happiness < 0:
                    agent.relationships        = max(0, agent.relationships - 1)
                    target_agent.relationships = max(0, target_agent.relationships - 1)

            target_agent.pending_notifications.append(notification)
            
            cooldown_msg = "" if rel_changed else " (Relationship unchanged: too soon since last interaction)."
            return (
                f"Interacted with {target} ({action}). "
                f"Happiness: {agent.happiness:.1f}.{cooldown_msg}"
            ), True, time_cost

        return f"Could not find '{target}' as a person.", False, 60

    # ── change_status ────────────────────────────────────────────────
    if name == "change_status":
        person   = str(args.get("person", ""))[:50]
        rel_type = str(args.get("type", ""))[:30]
        value    = str(args.get("value", ""))[:100]

        if person and rel_type:
            target_agent = next(
                (a for a in world.agents.values()
                 if a.name.lower() == person.lower() and a.alive),
                None,
            )
            if target_agent is None:
                return f"Person '{person}' not found or not alive.", False, 60

            dist = get_distance((agent.x, agent.y), (target_agent.x, target_agent.y))
            if dist > 30:
                return f"{person} is too far ({dist:.0f}m). Must be within 30m.", False, 60

            valid_statuses = [
                "single", "dating", "married", "divorced",
                "widowed", "engaged", "complicated",
            ]
            if rel_type.lower() not in valid_statuses:
                return f"Invalid status. Valid: {', '.join(valid_statuses)}.", False, 60

            req_key = person.lower()
            target_key = agent.name.lower()

            if agent.pending_status_requests.get(req_key) == rel_type.lower():
                agent.relationships_status = rel_type.lower()
                target_agent.relationships_status = rel_type.lower()
                del agent.pending_status_requests[req_key]
                
                target_agent.pending_notifications.append(
                    f"{agent.name} accepted your relationship status change to: {rel_type}."
                )
                return f"Relationship status with {person} changed to: {rel_type}.", True, time_cost
            else:
                target_agent.pending_status_requests[target_key] = rel_type.lower()
                target_agent.pending_notifications.append(
                    f"{agent.name} wants to change relationship status to: {rel_type}. "
                    f"To accept, use change_status with person='{agent.name}' and type='{rel_type}'. "
                    f"To deny, ignore it."
                )
                return f"Requested status change to '{rel_type}' with {person}. Waiting for them to accept.", True, time_cost

        if value and not rel_type:
            agent.beliefs = value
            return f"Belief updated to: \"{value}\".", True, time_cost

        return "Specify person+type for relationship status, or value for belief.", False, 60

    return f"Tool '{name}' is not implemented.", False, 60