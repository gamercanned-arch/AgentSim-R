import json
import random
import re
import uuid
from state import WorldState
from locations import get_distance_3d, get_location_by_name, LOCATIONS_3D, get_current_location_def
from config import MAX_INVENTORY

ITEM_CATALOG = {
    "food": {
        "Snacks": {"price": 4, "hunger": 10, "time": 60, "caffeine": 0},
        "Water": {"price": 2, "hunger": 5, "time": 60, "caffeine": 0},
        "Coffee": {"price": 5, "hunger": 5, "time": 120, "caffeine": 1},
        "Sandwich": {"price": 10, "hunger": 30, "time": 600, "caffeine": 0},
        "Pizza": {"price": 15, "hunger": 45, "time": 1200, "caffeine": 0},
        "Premium Meal": {"price": 25, "hunger": 80, "time": 1800, "caffeine": 0},
    },
    "everyday": {"Toothbrush": 5, "Clothes": 50, "Book": 20, "Art Supplies": 40, "Notebook": 5},
    "housing": {"Small Apartment": 75_000, "Apartment": 120_000, "House": 400_000, "Luxury House": 750_000},
    "health": {"Medicine": 12, "Vitamins": 25, "First aid kit": 30},
}

JOB_FLAVORS = {
    "tech": {"pick": "Laptop", "obj": "Computer", "q": "Server crashed due to OOM. A) Restart server, B) Optimize memory, C) Download more RAM.", "ans": "B"},
    "startup": {"pick": "Pitch Deck", "obj": "Investor", "q": "Investor asks about churn rate. A) Lie, B) Explain retention strategy, C) Cry.", "ans": "B"},
    "founder": {"pick": "Pitch Deck", "obj": "Investor", "q": "Investor asks about churn rate. A) Lie, B) Explain retention strategy, C) Cry.", "ans": "B"},
    "nurse": {"pick": "Stethoscope", "obj": "Patient", "q": "Patient has high BP. A) Give adrenaline, B) Administer beta-blockers, C) Ignore.", "ans": "B"},
    "doctor": {"pick": "Stethoscope", "obj": "Patient", "q": "Patient has high BP. A) Give adrenaline, B) Administer beta-blockers, C) Ignore.", "ans": "B"},
    "teacher": {"pick": "Marker", "obj": "Whiteboard", "q": "Student asks for help with fractions. A) Ignore them, B) Explain visually, C) Give detention.", "ans": "B"},
    "tutor": {"pick": "Marker", "obj": "Whiteboard", "q": "Student asks for help with fractions. A) Ignore them, B) Explain visually, C) Give detention.", "ans": "B"},
    "delivery": {"pick": "Scanner", "obj": "Box", "q": "Label is torn. A) Guess address, B) Return to depot for relabeling, C) Throw in trash.", "ans": "B"},
    "driver": {"pick": "Scanner", "obj": "Box", "q": "Label is torn. A) Guess address, B) Return to depot for relabeling, C) Throw in trash.", "ans": "B"},
    "fedex": {"pick": "Scanner", "obj": "Box", "q": "Label is torn. A) Guess address, B) Return to depot for relabeling, C) Throw in trash.", "ans": "B"},
    "freelance": {"pick": "Coffee", "obj": "IDE", "q": "Client wants 10 extra features today. A) Agree, B) Negotiate scope, C) Block client.", "ans": "B"},
    "developer": {"pick": "Coffee", "obj": "IDE", "q": "Client wants 10 extra features today. A) Agree, B) Negotiate scope, C) Block client.", "ans": "B"},
    "generic": {"pick": "Notepad", "obj": "Desk", "q": "A mundane task appears. A) Procrastinate, B) Complete it efficiently, C) Complain.", "ans": "B"},
    "education": {"pick": "Textbook", "obj": "Exam", "q": "What is the powerhouse of the cell? A) Nucleus, B) Mitochondria, C) Ribosome.", "ans": "B"}
}

def parse_tool_call(tool_call_str: str) -> tuple:
    try:
        clean_str = re.sub(r'<think>.*?</think>', '', tool_call_str, flags=re.DOTALL)
        matches = list(re.finditer(r'<tool_call>(.*?)</tool_call>', clean_str, re.DOTALL))
        if not matches: return "Parse error: No <tool_call> tags found.", {}
        block = matches[-1].group(1)
        func_match = re.search(r'<function=([^>]+)>(.*?)</function>', block, re.DOTALL)
        if not func_match: return "Parse error: No <function=name> tag found.", {}
        name = func_match.group(1).strip()
        params_block = func_match.group(2)
        args = {}
        param_matches = re.finditer(r'<parameter=([^>]+)>(.*?)</parameter>', params_block, re.DOTALL)
        for p in param_matches: args[p.group(1).strip()] = p.group(2).strip()
        return name, args
    except Exception as e:
        return f"Parse error: {e}", {}

def _check_open_hours(loc: tuple, current_time: float) -> bool:
    if not loc: return True
    hour = (current_time // 3600) % 24
    if loc.open_time == loc.close_time: return True
    if loc.open_time <= loc.close_time: return loc.open_time <= hour < loc.close_time
    else: return hour >= loc.open_time or hour < loc.close_time

def _has_item(agent, item_name):
    for i, it in enumerate(agent.inventory):
        if it["item"].lower() == item_name.lower(): return i
    return -1

def _is_busy(target_agent, current_time):
    return target_agent.busy_until > current_time or target_agent.task_state != "idle"

def _validate_shares(raw) -> tuple:
    try:
        val = float(raw)
        if not val.is_integer(): return 0, "Shares must be a whole number."
        shares = int(val)
        if shares <= 0: return 0, "Shares must be > zero."
        return shares, None
    except: return 0, "Invalid number of shares."

def execute_tool(tool_call_str: str, agent_id: int, world: WorldState) -> tuple:
    name, args = parse_tool_call(tool_call_str)
    if isinstance(name, str) and name.startswith("Parse error"): return name, False, 60
    if not name: return "Parse error: No tool name.", False, 60

    agent = world.agents.get(agent_id)
    if not agent or not agent.alive: return "Agent inactive.", False, 0
    time_cost = 300

    if agent.task_state != "idle" and name not in ["interact_with", "pick_item"]:
        agent.fail_counter += 1
        return "You are in a task. You must use `pick_item` or `interact_with` to proceed!", False, 60

    # ── sleep ────────────────────────────────────────────────────────
    if name == "sleep":
        hours = max(1.0, min(12.0, float(args.get("hours", 8))))
        time_cost = int(hours * 3600)
        loc_def = get_current_location_def(agent.x, agent.y, agent.z)
        is_home = (loc_def and loc_def.name == f"Home_{agent.name}")
        
        agent.awake_hours = 0
        cap = 100.0 if is_home else 60.0
        agent.energy = min(cap, agent.energy + (hours * 10.0))
        agent.stress = max(0.0, agent.stress - (hours * 2.0))
        
        msg = f"Slept {hours:.1f}h. Energy: {agent.energy:.1f}. Do Not Disturb active."
        if not is_home: msg += " (Poor sleep outside home: capped at 60%)."
        return msg, True, time_cost

    # ── move_to & walk ───────────────────────────────────────────────
    if name == "move_to":
        place = str(args.get("place", ""))[:50]
        if place.lower() in ["house", "home"]: place = f"Home_{agent.name}"
        
        target_loc = get_location_by_name(place)
        if not target_loc: return f"Unknown place: '{place}'.", False, 60

        if place.startswith("Home_") and place != f"Home_{agent.name}":
            owner_name = place.split("_")[1]
            owner = next((a for a in world.agents.values() if a.name == owner_name), None)
            if owner and get_current_location_def(owner.x, owner.y, owner.z) != target_loc:
                return f"{owner_name} is not home. Door is locked.", False, 60

        if not _check_open_hours(target_loc, world.sim_time):
            return f"{place} is currently closed.", False, 60

        target_coords = ((target_loc.x_min + target_loc.x_max)/2, (target_loc.y_min + target_loc.y_max)/2, target_loc.z_min)
        dist = get_distance_3d((agent.x, agent.y, agent.z), target_coords)
        
        energy_drain = dist * 0.005
        if agent.energy < energy_drain:
            return f"Too exhausted to travel {dist:.0f}m. Need {energy_drain:.1f} Energy.", False, 60

        agent.energy -= energy_drain
        time_cost = int(dist / 1.5) 
        agent.x, agent.y, agent.z = target_coords
        agent.location = place
        
        occupants = sum(1 for a in world.agents.values() if a.location == place)
        msg = f"Travelled to {place} (-{energy_drain:.1f} Energy)."
        if occupants > 3: msg += " It's crowded here."
        return msg, True, time_cost

    if name == "walk":
        direction = str(args.get("direction", "")).strip().lower()
        delta = {"north": (0,30), "south": (0,-30), "east": (30,0), "west": (-30,0), 
                 "northeast": (21,21), "northwest": (-21,21), "southeast": (21,-21), "southwest": (-21,-21)}.get(direction)
        if not delta: return "Invalid direction.", False, 60
        agent.x = max(0, min(5000, agent.x + delta[0]))
        agent.y = max(0, min(5000, agent.y + delta[1]))
        
        loc_def = get_current_location_def(agent.x, agent.y, agent.z)
        agent.location = loc_def.name if loc_def else "Outside"
        return f"Walked {direction}. Location updated to: {agent.location}.", True, 60

    # ── pick_item / unequip ──────────────────────────────────────────
    if name == "pick_item":
        item = args.get("item_name", "")
        if item.lower() in ["none", "store", "unequip", "put away", ""]:
            if agent.currently_holding:
                agent.inventory.append(agent.currently_holding)
                held_name = agent.currently_holding['item']
                agent.currently_holding = None
                return f"Stored {held_name} back in inventory.", True, 30
            return "You aren't holding anything to store.", False, 30

        if agent.task_state == "job_pick":
            flavor = agent.pending_task_data["flavor"]
            if item.lower() != flavor["pick"].lower():
                return f"You need to pick_item '{flavor['pick']}' to do your job.", False, 30
            
            agent.currently_holding = {"id": "job_prop", "item": flavor["pick"], "durability": 99}
            agent.task_state = "job_mcq"
            return f"[WORK] You grab the {flavor['pick']}. Scenario: {flavor['q']} Use `interact_with(person_or_object='{flavor['obj']}', action='A, B, or C')`", True, 60
        
        idx = _has_item(agent, item)
        if idx == -1: return f"Item {item} not in inventory.", False, 60
        if agent.currently_holding:
            agent.inventory.append(agent.currently_holding)
        agent.currently_holding = agent.inventory.pop(idx)
        return f"Now holding {item} in hand.", True, 30

    # ── work_job / get_education (INTERACTIVE EXAMS) ─────────────────
    if name in ["work_job", "get_education"]:
        if agent.task_state != "idle": return "Already doing a task.", False, 60
        job_raw = args.get("jobname", "generic") if name == "work_job" else "education"
        hours = float(args.get("hours", 8) if name == "work_job" else 8)
        
        if agent.energy < (hours * 10): 
            return f"Need {hours*10} energy to work {hours}h. Have {agent.energy:.1f}.", False, 60
        
        matched_flavor = JOB_FLAVORS["generic"]
        if name == "get_education":
            matched_flavor = JOB_FLAVORS["education"]
        else:
            for k, v in JOB_FLAVORS.items():
                if k in job_raw.lower():
                    matched_flavor = v
                    break
                    
        agent.task_state = "job_pick"
        agent.pending_task_data = {"type": name, "hours": hours, "flavor": matched_flavor}
        return f"[SCENARIO INITIATED] Shift started as {job_raw}. To begin, use `pick_item('{matched_flavor['pick']}')` from your workspace.", True, 60

    # ── interact_with / change_status ─────────────────────────────────
    if name == "interact_with":
        target = str(args.get("person_or_object", ""))
        action = str(args.get("action", ""))
        
        if agent.task_state == "job_mcq":
            flavor = agent.pending_task_data["flavor"]
            if target.lower() != flavor["obj"].lower():
                return f"You must interact_with '{flavor['obj']}' to complete the task.", False, 60
                
            if agent.currently_holding and agent.currently_holding.get("id") == "job_prop":
                agent.currently_holding = None
            agent.task_state = "idle"
            
            data = agent.pending_task_data
            time_cost = int(data["hours"] * 3600)
            agent.energy -= data["hours"] * 10
            
            correct = flavor["ans"].lower() in action.lower()
            if data["type"] == "get_education":
                agent.education = min(100, agent.education + (5 if correct else 1))
                agent.hourly_wage += (5.0 if correct else 1.0)
                return f"Exam finished. Correct? {correct}. Wage increased. Time passed: {data['hours']}h. DND active.", True, time_cost
            else:
                pay = agent.hourly_wage * data["hours"] * (world.market_price/100.0) 
                if not correct: pay *= 0.5
                agent.money += pay
                return f"Task resolved. Client satisfied? {correct}. Earned ${pay:.2f}. Time passed: {data['hours']}h. DND active.", True, time_cost

        target_agent = next((a for a in world.agents.values() if a.name.lower() == target.lower() and a.alive), None)
        if target_agent:
            if _is_busy(target_agent, world.sim_time): return f"{target_agent.name} is currently busy/sleeping (DND).", False, 60
            if get_distance_3d((agent.x, agent.y, agent.z), (target_agent.x, target_agent.y, target_agent.z)) > 20: return "Too far.", False, 60
            target_agent.pending_notifications.append(f"{agent.name} interacted with you ({action}).")
            return f"Interacted with {target}.", True, 60

        loc = get_current_location_def(agent.x, agent.y, agent.z)
        if loc:
            for obj in loc.interactables:
                if obj["name"].lower() == target.lower():
                    if "target_z" in obj:
                        agent.z = obj["target_z"]
                        return f"Used {target}. Moved to floor Z={agent.z}.", True, 60
                    else:
                        return f"Used {target} ({action}).", True, 60
                    
        return f"Interacted with object {target}.", True, 60

    if name == "change_status":
        value = str(args.get("value", ""))
        person = str(args.get("person", ""))
        rel_type = str(args.get("type", ""))
        
        if value:
            agent.beliefs = value
            return f"Belief/Goal updated to: \"{value}\".", True, 30
        
        if person and rel_type:
            target = next((a for a in world.agents.values() if a.name.lower() == person.lower() and a.alive), None)
            if not target: return f"Person '{person}' not found.", False, 60
            req_key = person.lower()
            if agent.pending_status_requests.get(req_key) == rel_type.lower():
                agent.relationships_status = rel_type.lower()
                target.relationships_status = rel_type.lower()
                del agent.pending_status_requests[req_key]
                target.pending_notifications.append(f"{agent.name} accepted status: {rel_type}.")
                return f"Status with {person} changed to: {rel_type}.", True, 30
            else:
                target.pending_status_requests[agent.name.lower()] = rel_type.lower()
                target.pending_notifications.append(f"{agent.name} wants status: {rel_type}.")
                return f"Requested status change to '{rel_type}' with {person}.", True, 30
        return "Invalid parameters.", False, 60

    # ── SOCIAL / AGGRESSION TOOLS (DND ENFORCED) ──────────────────────
    if name == "attack_person":
        t_name = str(args.get("person", ""))
        target = next((a for a in world.agents.values() if a.name.lower() == t_name.lower() and a.alive), None)
        if not target: return "Target not found.", False, 60
        if _is_busy(target, world.sim_time): return f"{target.name} is securely locked away working or sleeping. Cannot attack.", False, 60
        if get_distance_3d((agent.x, agent.y, agent.z), (target.x, target.y, target.z)) > 20: return "Too far.", False, 60
        
        damage = random.uniform(5, 25)
        target.health -= damage
        target.stress += 15
        if target.busy_until > world.sim_time: target.busy_until = world.sim_time 
        target.task_state = "idle"
        if target.currently_holding and target.currently_holding.get("id") == "job_prop": target.currently_holding = None
        target.pending_notifications.append(f"URGENT: {agent.name} attacked you! Action interrupted.")
        
        if target.health <= 0:
            target.alive = False
            if target.currently_holding and target.currently_holding.get("id") != "job_prop":
                target.inventory.append(target.currently_holding)
                
            closest = min([a for a in world.agents.values() if a.alive and a.id != target.id], 
                          key=lambda a: get_distance_3d((a.x, a.y, a.z), (target.x, target.y, target.z)), default=None)
            if closest and get_distance_3d((closest.x, closest.y, closest.z), (target.x, target.y, target.z)) < 100:
                closest.inventory.extend(target.inventory)
                closest.money += target.money
                closest.pending_notifications.append(f"You scavenged ${target.money:.2f} and items from {target.name}'s body.")
            from logger import log_death
            log_death(target)
            return f"Killed {t_name}.", True, 60
        return f"Attacked {t_name}.", True, 60

    if name == "talk_to":
        t_name = str(args.get("person", "")); msg = str(args.get("message", ""))
        target = next((a for a in world.agents.values() if a.name.lower() == t_name.lower() and a.alive), None)
        if not target: return "Target not found.", False, 60
        if _is_busy(target, world.sim_time): return f"{target.name} is currently working or sleeping (DND).", False, 60
        if get_distance_3d((agent.x, agent.y, agent.z), (target.x, target.y, target.z)) > 50: return "Cannot reach target.", False, 60
        
        agent.social_fulfillment = min(100.0, agent.social_fulfillment + 10)
        target.pending_notifications.append(f"{agent.name} said: {msg}")
        for a in world.agents.values():
            if a.alive and a.id not in (agent.id, target.id) and get_distance_3d((a.x, a.y, a.z), (agent.x, agent.y, agent.z)) <= 50:
                a.pending_notifications.append(f"Overheard {agent.name} say to {t_name}: '{msg}'")
        return f"Talked to {t_name}.", True, 60
        
    if name == "call_person":
        t_name = str(args.get("person", "")); msg = str(args.get("message", ""))
        target = next((a for a in world.agents.values() if a.name.lower() == t_name.lower() and a.alive), None)
        if not target: return "Target not found.", False, 60
        if _is_busy(target, world.sim_time): return f"Call to {target.name} went straight to voicemail (DND).", False, 60
        target.pending_notifications.append(f"Phone Call from {agent.name}: {msg}")
        return f"Called {t_name}.", True, 60

    if name == "give_item":
        t_name = str(args.get("person", "")); item_name = str(args.get("item", ""))
        target = next((a for a in world.agents.values() if a.name.lower() == t_name.lower() and a.alive), None)
        if not target: return "Target not found.", False, 60
        if _is_busy(target, world.sim_time): return f"{target.name} is busy (DND).", False, 60
        if get_distance_3d((agent.x, agent.y, agent.z), (target.x, target.y, target.z)) > 20: return "Too far.", False, 60
        if len(target.inventory) >= MAX_INVENTORY: return f"{target.name}'s inventory is full.", False, 60
        
        idx = _has_item(agent, item_name)
        if idx == -1: return f"You don't have {item_name}.", False, 60
        item_data = agent.inventory.pop(idx)
        target.inventory.append(item_data)
        target.pending_notifications.append(f"{agent.name} gave you {item_name}.")
        agent.social_fulfillment = min(100.0, agent.social_fulfillment + 15)
        return f"Gave {item_name} to {t_name}.", True, 60

    if name == "give_money":
        t_name = str(args.get("person", ""))
        try: amount = float(args.get("amount", 0))
        except: amount = 0.0
        if amount <= 0: return "Invalid amount.", False, 60
        if agent.money < amount: return "Not enough money.", False, 60
        target = next((a for a in world.agents.values() if a.name.lower() == t_name.lower() and a.alive), None)
        if not target: return "Target not found.", False, 60
        if _is_busy(target, world.sim_time): return f"{target.name} is busy (DND).", False, 60
        if get_distance_3d((agent.x, agent.y, agent.z), (target.x, target.y, target.z)) > 20: return "Too far.", False, 60
        agent.money -= amount
        target.money += amount
        target.pending_notifications.append(f"{agent.name} gave you ${amount:.2f}.")
        agent.social_fulfillment = min(100.0, agent.social_fulfillment + 15)
        return f"Gave ${amount:.2f} to {t_name}.", True, 60

    # ── FINITE ITEM MANAGEMENT & MARKET ───────────────────────────────
    if name == "buy_item":
        item = str(args.get("item", ""))[:50]
        if item in ITEM_CATALOG.get("housing", {}):
            price = ITEM_CATALOG["housing"][item]
            if agent.money < price: return "Cannot afford housing.", False, 60
            agent.money -= price
            agent.owned_locations.append(item)
            agent.current_home = item
            return f"Bought {item}. Moved in.", True, 3600
        
        if len(agent.inventory) >= MAX_INVENTORY: return "Inventory full.", False, 60
        if world.store_inventory.get(item, 0) <= 0: return f"'{item}' is completely out of stock in the village.", False, 60

        price = 0
        for cat, items in ITEM_CATALOG.items():
            if item in items and cat != "housing":
                price = items[item]["price"] if isinstance(items[item], dict) else items[item]
                break
        if not price: return f"Item '{item}' not found.", False, 60
        if agent.money < price: return "Cannot afford.", False, 60
        
        agent.money -= price
        world.store_inventory[item] -= 1
        agent.inventory.append({"id": str(uuid.uuid4()), "item": item, "durability": 5, "bought": world.sim_time})
        return f"Bought {item} for ${price}.", True, 120

    if name == "eat_food":
        item = str(args.get("item", ""))[:50]
        idx = _has_item(agent, item)
        if idx != -1:
            food_data = agent.inventory.pop(idx)
            if world.sim_time - food_data.get("bought", 0) > 172800:
                agent.health -= 10
                return "The food was spoiled! Health -10.", True, 60
        else:
            if item not in ITEM_CATALOG["food"]: return "Food not found.", False, 60
            if world.store_inventory.get(item, 0) <= 0: return f"'{item}' is completely out of stock in the village.", False, 60
            cost = ITEM_CATALOG["food"][item]["price"]
            if agent.money < cost: return "Cannot afford.", False, 60
            agent.money -= cost
            world.store_inventory[item] -= 1

        f_stats = ITEM_CATALOG["food"].get(item, {"hunger": 20, "time": 600, "caffeine": 0})
        agent.hunger = max(0.0, agent.hunger - f_stats["hunger"])
        agent.caffeine_level += f_stats["caffeine"]
        return f"Ate {item}. Hunger reduced.", True, f_stats["time"]

    if name == "do_hobby":
        item = str(args.get("item", ""))[:50]
        idx = _has_item(agent, item)
        if idx == -1: return f"You don't have {item}.", False, 60
        agent.stress = max(0.0, agent.stress - 15)
        agent.happiness = min(100.0, agent.happiness + 10)
        agent.inventory[idx]["durability"] -= 1
        msg = f"Enjoyed hobby with {item}. Stress fell."
        if agent.inventory[idx]["durability"] <= 0:
            agent.inventory.pop(idx)
            msg += f" {item} wore out."
        return msg, True, 3600

    if name == "buy_stock":
        shares, err = _validate_shares(args.get("shares", 0))
        if err: return err, False, 60
        from utils import is_market_open
        if not is_market_open(world.sim_time):
            agent.pending_market_orders.append({"type": "buy", "shares": shares})
            return f"Market closed. Buy order for {shares} queued.", True, 60
        cost = world.market_price * shares
        if agent.money < cost: return "Cannot afford.", False, 60
        agent.money -= cost
        old_cost = agent.last_known_price * agent.shares_owned
        agent.shares_owned += shares
        agent.last_known_price = (old_cost + cost) / agent.shares_owned
        world.net_volume_this_period += shares
        return f"Bought {shares} share(s).", True, 60

    if name == "sell_stock":
        shares, err = _validate_shares(args.get("shares", 0))
        if err: return err, False, 60
        if agent.shares_owned < shares: return "Not enough shares.", False, 60
        from utils import is_market_open
        if not is_market_open(world.sim_time):
            agent.pending_market_orders.append({"type": "sell", "shares": shares})
            return f"Market closed. Sell order for {shares} queued.", True, 60
        proceeds = world.market_price * shares
        agent.money += proceeds
        agent.shares_owned -= shares
        if agent.shares_owned == 0: agent.last_known_price = 0.0
        world.net_volume_this_period -= shares
        return f"Sold {shares} share(s).", True, 60

    if name == "seek_medicalcare":
        cost = 50.0
        if agent.money < cost: return "Cannot afford medical care.", False, 60
        agent.money -= cost
        agent.health = min(100.0, agent.health + 30.0)
        return "Received medical care. Health restored.", True, 600

    return f"Tool {name} not found.", False, 60