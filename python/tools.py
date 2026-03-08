import json
import random
import re
from python.state import WorldState
from python.locations import get_distance, LOCATIONS

# Comprehensive item catalog with categories and prices
# Prices are base prices - some variance may be applied
ITEM_CATALOG = {
    # Food items (consumable)
    "food": {
        "Coffee": 5,
        "Sandwich": 8,
        "Meal": 15,
        "Pizza": 12,
        "Salad": 10,
        "Burger": 9,
        "Soda": 3,
        "Water": 2,
        "Snacks": 6,
    },
    # Everyday items (consumable)
    "everyday": {
        "Toothbrush": 5,
        "Shampoo": 8,
        "Soap": 4,
        "Clothes": 50,
        "Phone charger": 20,
        "Bus ticket": 3,
        "Metro card": 25,
        "Notebook": 5,
        "Pen": 2,
        "Backpack": 40,
        "Umbrella": 15,
        "Socks": 10,
        "Underwear": 15,
        "Towel": 12,
    },
    # Entertainment (some subscriptions are recurring)
    "entertainment": {
        "Movie ticket": 15,
        "Video game": 60,
        "Book": 18,
        "Streaming subscription": 15,
        "Music subscription": 10,
        "Concert ticket": 80,
        "Board game": 30,
        "Puzzle": 20,
    },
    # Health items
    "health": {
        "Medicine": 12,
        "Vitamins": 25,
        "Gym membership": 50,
        "Bandages": 8,
        "First aid kit": 30,
        "Sunscreen": 15,
    },
    # Housing (property purchases - major items)
    "housing": {
        "Small Apartment": 75000,
        "Apartment": 120000,
        "Large Apartment": 200000,
        "Small House": 250000,
        "House": 400000,
        "Luxury House": 750000,
        "Mansion": 1500000,
        "Beach House": 500000,
        "Cabin": 150000,
    },
    # Transportation
    "transportation": {
        "Bicycle": 300,
        "Used Car": 15000,
        "New Car": 35000,
        "Luxury Car": 80000,
        "Motorcycle": 10000,
        "Scooter": 2500,
    },
    # Luxury items
    "luxury": {
        "Watch": 500,
        "Jewelry": 1500,
        "Designer bag": 2000,
        "Gaming PC": 3000,
        "Sunglasses": 250,
        "Perfume": 80,
    },
    # Electronics
    "electronics": {
        "Laptop": 1200,
        "Tablet": 600,
        "Smart TV": 800,
        "Smartphone": 900,
        "Headphones": 200,
        "Smartwatch": 350,
        "Camera": 700,
        "Speaker": 150,
    },
    # Services
    "services": {
        "Haircut": 25,
        "Laundry": 15,
        "Cleaning service": 60,
        "Taxi ride": 25,
        "Uber ride": 30,
    },
}

# Housing locations that can be purchased and moved into
HOUSE_LOCATIONS = {
    "Small Apartment": "Apartment_Small",
    "Apartment": "Apartment_Medium", 
    "Large Apartment": "Apartment_Large",
    "Small House": "House_Small",
    "House": "House_Medium",
    "Luxury House": "House_Luxury",
    "Mansion": "Estate_Mansion",
    "Beach House": "House_Beach",
    "Cabin": "House_Cabin",
}

# Default house locations in the city (if not in HOUSE_LOCATIONS)
# These will be added to LOCATIONS when a house is purchased
NEW_HOUSE_LOCATIONS = {
    "Apartment_Small": (600, 900),
    "Apartment_Medium": (700, 1000),
    "Apartment_Large": (800, 1100),
    "House_Small": (900, 1200),
    "House_Medium": (1000, 1300),
    "House_Luxury": (1100, 1400),
    "Estate_Mansion": (1200, 1500),
    "House_Beach": (4800, 4000),
    "House_Cabin": (4200, 3800),
}


def get_item_price(item_name: str) -> tuple[float, str, str]:
    """
    Get the price, category, and type of an item.
    Returns (price, category, item_type) or (0, "", "") if not found.
    """
    for category, items in ITEM_CATALOG.items():
        if item_name in items:
            base_price = items[item_name]
            # Apply small random variance (±10%) for everyday items
            # Housing has fixed price
            if category == "housing":
                price = float(base_price)
            else:
                price = base_price * random.uniform(0.9, 1.1)
            return price, category, item_name
    return 0, "", ""


def is_housing_item(item_name: str) -> bool:
    """Check if an item is a housing/property type."""
    return item_name in HOUSE_LOCATIONS


def get_house_location(item_name: str) -> tuple:
    """Get the location coordinates for a purchased house."""
    if item_name in HOUSE_LOCATIONS:
        loc_name = HOUSE_LOCATIONS[item_name]
        if loc_name in LOCATIONS:
            return LOCATIONS[loc_name]
        elif loc_name in NEW_HOUSE_LOCATIONS:
            return NEW_HOUSE_LOCATIONS[loc_name]
    return None


def parse_tool_call(tool_call_str: str) -> tuple[str, dict]:
    """Parse tool call from LLM output."""
    try:
        # Try to extract JSON from <tool_call> tags
        match = re.search(r'<tool_call>(.*?)</tool_call>', tool_call_str, re.DOTALL)
        if match:
            json_part = match.group(1).strip()
            data = json.loads(json_part)
            name = data.get("name", "")
            args = data.get("arguments", {})
            return name, args
        return "", {}
    except (json.JSONDecodeError, AttributeError) as e:
        return f"Parse error: {str(e)}", {}


def execute_tool(tool_call_str: str, agent_id: int, world: WorldState) -> tuple[str, bool]:
    name, args = parse_tool_call(tool_call_str)
    
    if isinstance(name, str) and name.startswith("Parse error"):
        return name, False
    
    if not name:
        return "No tool name found", False

    agent = world.agents[agent_id]

    if name == "move_to":
        place = args.get("place")
        if place in LOCATIONS:
            agent.location = place
            agent.x, agent.y = LOCATIONS[place]
            return f"Moved to {place}", True
        return f"Unknown place: {place}", False

    if name == "buy_item":
        item = args.get("item")
        if not item:
            return "No item specified", False
        
        # Get item price and category
        price, category, item_type = get_item_price(item)
        if price == 0:
            return f"Unknown item: {item}", False
        
        # Check if this is a housing purchase
        if is_housing_item(item):
            # Check if agent already owns a home
            if agent.current_home:
                # Agent already has a home - warn them
                return (
                    f"WARNING: You already own {agent.current_home}. "
                    f"Buying {item} will replace your current home. "
                    f"Current home: {agent.current_home}, New home: {item}. "
                    f"Confirm by calling buy_item again with the same item if you want to proceed.",
                    False
                )
            
            # Check if agent has enough money
            if agent.money >= price:
                agent.money -= price
                agent.owned_locations.append(item)
                agent.current_home = item
                
                # Move agent to their new home
                house_coords = get_house_location(item)
                if house_coords:
                    agent.x, agent.y = house_coords
                    location_name = HOUSE_LOCATIONS.get(item, f"Home_{item.replace(' ', '_')}")
                    agent.location = location_name
                
                return f"Purchased {item} for ${price:.2f}. You now own {item}. Moved to {agent.location}.", True
            else:
                return f"Not enough money to buy {item}. Need ${price:.2f}, have ${agent.money:.2f}", False
        
        # Regular item purchase
        if agent.money >= price:
            agent.money -= price
            return f"Bought {item} for ${price:.2f}. Remaining: ${agent.money:.2f}", True
        return f"Not enough money for {item}. Need ${price:.2f}, have ${agent.money:.2f}", False

    if name == "attack_person":
        target_name = args.get("person")
        if not target_name:
            return "No target specified", False
        
        # Find target agent
        target_agent = None
        for a in world.agents.values():
            if a.name.lower() == target_name.lower() and a.alive:
                target_agent = a
                break
        
        if target_agent is None:
            return f"Target '{target_name}' not found or not alive", False
        
        # Check proximity (must be within interaction distance)
        attacker = world.agents[agent_id]
        dist = get_distance((attacker.x, attacker.y), (target_agent.x, target_agent.y))
        if dist > 20:
            return f"Target too far away ({dist:.0f}m). Must be within 20m.", False
        
        # Apply damage: random 5-25 health degradation
        damage = random.uniform(5, 25)
        target_agent.health = max(0, target_agent.health - damage)
        
        # Increase stress for both parties
        target_agent.stress = min(100, target_agent.stress + 15)
        attacker.stress = min(100, attacker.stress + 10)
        
        result_msg = f"Attacked {target_name}, dealt {damage:.1f} damage. Target health: {target_agent.health:.1f}"
        
        # Check if target died
        if target_agent.health <= 0:
            target_agent.alive = False
            result_msg += " TARGET DIED!"
        
        return result_msg, True

    if name == "talk_to":
        target_name = args.get("person")
        if not target_name:
            return "No person specified to talk to", False
        
        # Find target agent
        target_agent = None
        for a in world.agents.values():
            if a.name.lower() == target_name.lower() and a.alive:
                target_agent = a
                break
        
        if target_agent is None:
            return f"Person '{target_name}' not found", False
        
        # Check proximity (must be within 50m for talk_to)
        speaker = world.agents[agent_id]
        dist = get_distance((speaker.x, speaker.y), (target_agent.x, target_agent.y))
        if dist > 50:
            return f"{target_name} is too far away ({dist:.0f}m). Must be within 50m to talk.", False
        
        # Talking reduces stress slightly, can improve relationships over time
        speaker.stress = max(0, speaker.stress - 2)
        # Small chance of relationship improvement
        if random.random() < 0.3:
            speaker.relationships = min(10, speaker.relationships + 1)
        
        return f"Had a conversation with {target_name}. Stress: {speaker.stress:.1f}, Relationships: {speaker.relationships}", True

    if name == "eat_food":
        item = args.get("item")
        if not item:
            return "No food item specified", False
        
        # Check if item is in food category
        if item not in ITEM_CATALOG.get("food", {}):
            return f"'{item}' is not a food item. Available: {', '.join(ITEM_CATALOG.get('food', {}).keys())}", False
        
        price = ITEM_CATALOG["food"][item] * random.uniform(0.9, 1.1)
        eater = world.agents[agent_id]
        
        if eater.money < price:
            return f"Not enough money for {item}. Need ${price:.2f}, have ${eater.money:.2f}", False
        
        eater.money -= price
        # Reduce hunger based on item
        hunger_reduction = {
            "Coffee": 5, "Soda": 10, "Water": 10,
            "Snacks": 15, "Sandwich": 25, "Salad": 30,
            "Burger": 35, "Pizza": 40, "Meal": 50
        }.get(item, 20)
        
        eater.hunger = max(0, eater.hunger - hunger_reduction)
        # Small health boost from eating
        eater.health = min(100, eater.health + 2)
        
        return f"Ate {item}. Hunger: {eater.hunger:.1f}, Remaining: ${eater.money:.2f}", True

    if name == "work_job":
        jobname = args.get("jobname")
        if not jobname:
            return "No job specified", False
        
        worker = world.agents[agent_id]
        
        # Define job wages (per work action)
        job_wages = {
            "freelance": 40, "developer": 50, "coding": 45,
            "nurse": 60, "doctor": 100, "medical": 80,
            "delivery": 20, "driver": 25, "fedex": 22,
            "teacher": 35, "tutor": 30, "education": 30,
            "startup": 80, "founder": 100, "tech": 70,
            "psychology": 25, "student": 0, "intern": 15,
            "retail": 18, "store": 18, "barista": 16,
            "builder": 40, "construction": 45
        }
        
        # Find matching job
        wage = 20  # default wage
        job_match = None
        job_lower = jobname.lower()
        for job_key, job_wage in job_wages.items():
            if job_key in job_lower or job_lower in job_key:
                wage = job_wage
                job_match = job_key
                break
        
        worker.job = jobname
        worker.money += wage
        
        # Working increases stress
        worker.stress = min(100, worker.stress + 5)
        # Working increases hunger
        worker.hunger = min(100, worker.hunger + 10)
        
        return f"Worked as {jobname}. Earned ${wage:.2f}. Job: {worker.job}, Money: ${worker.money:.2f}", True

    if name == "seek_medicalcare":
        patient = world.agents[agent_id]
        
        # Medical care costs money but improves health
        cost = 50
        if patient.money < cost:
            return f"Cannot afford medical care. Need ${cost:.2f}, have ${patient.money:.2f}", False
        
        patient.money -= cost
        health_boost = 30
        patient.health = min(100, patient.health + health_boost)
        # Medical care also reduces stress slightly
        patient.stress = max(0, patient.stress - 10)
        
        return f"Received medical care. Health: {patient.health:.1f}, Stress: {patient.stress:.1f}, Paid: ${cost:.2f}", True

    if name == "get_education":
        edu_type = args.get("type")
        if not edu_type:
            return "No education type specified", False
        
        learner = world.agents[agent_id]
        
        # Education costs and improves education level
        edu_costs = {
            "high_school": 500, "highschool": 500,
            "bachelors": 2000, "college": 2000, "university": 2500,
            "masters": 4000, "master": 4000,
            "phd": 8000, "doctorate": 8000,
            "technical": 1000, "certification": 800,
            "online": 300, "course": 200
        }
        
        cost = 300  # default
        edu_gain = 10
        edu_match = None
        edu_lower = edu_type.lower()
        
        for edu_key, edu_cost in edu_costs.items():
            if edu_key in edu_lower or edu_lower in edu_key:
                cost = edu_cost
                edu_match = edu_key
                # Higher education gives more education points
                if "phd" in edu_key or "doctorate" in edu_key:
                    edu_gain = 30
                elif "master" in edu_key:
                    edu_gain = 25
                elif "bachelor" in edu_key or "college" in edu_key:
                    edu_gain = 20
                elif "high" in edu_key:
                    edu_gain = 15
                break
        
        if learner.money < cost:
            return f"Cannot afford {edu_type} education. Need ${cost:.2f}, have ${learner.money:.2f}", False
        
        learner.money -= cost
        learner.education = min(100, learner.education + edu_gain)
        # Better education can lead to better income
        if learner.education > 70:
            learner.max_income = min(10000, learner.max_income * 1.1)
        
        return f"Completed {edu_type} education. Education: {learner.education:.1f}, Max Income: ${learner.max_income:.2f}", True

    if name == "call_person":
        target_name = args.get("person")
        if not target_name:
            return "No person specified to call", False
        
        # Find target agent
        target_agent = None
        for a in world.agents.values():
            if a.name.lower() == target_name.lower() and a.alive:
                target_agent = a
                break
        
        if target_agent is None:
            return f"Person '{target_name}' not found", False
        
        # Calling works regardless of proximity (phone)
        caller = world.agents[agent_id]
        # Small cost for call
        call_cost = 1
        if caller.money < call_cost:
            return f"Cannot afford call (need ${call_cost:.2f})", False
        
        caller.money -= call_cost
        # Calling reduces stress slightly
        caller.stress = max(0, caller.stress - 3)
        
        return f"Called {target_name}. Cost: ${call_cost:.2f}, Stress: {caller.stress:.1f}", True

    if name == "interact_with":
        target = args.get("person_or_object")
        if not target:
            return "No person or object specified", False
        
        agent = world.agents[agent_id]
        
        # Check if target is a person
        target_agent = None
        for a in world.agents.values():
            if a.name.lower() == target.lower() and a.alive:
                target_agent = a
                break
        
        # Check proximity (must be within 20m for interact_with)
        if target_agent:
            dist = get_distance((agent.x, agent.y), (target_agent.x, target_agent.y))
            if dist > 20:
                return f"{target} is too far away ({dist:.0f}m). Must be within 20m.", False
            
            # Person interaction - similar to talk_to but more casual
            agent.stress = max(0, agent.stress - 1)
            agent.happiness = min(100, agent.happiness + 2)
            return f"Interacted with {target}. Happiness: {agent.happiness:.1f}", True
        
        # Check if target is a known location/object
        if target in LOCATIONS:
            # Object/location interaction
            # Map common objects to location types
            location_interactions = {"park": "Park_Central", "cafe": "Cafe", "gym": "Gym", 
                                   "library": "Library", "market": "Market", "store": "Store_A"}
            loc = location_interactions.get(target.lower(), target)
            if loc in LOCATIONS:
                dist = get_distance((agent.x, agent.y), LOCATIONS[loc])
                if dist > 20:
                    return f"{target} is too far away ({dist:.0f}m)", False
                agent.happiness = min(100, agent.happiness + 1)
                return f"Interacted with {target}. Happiness: {agent.happiness:.1f}", True
        
        return f"Could not find '{target}' to interact with", False

    if name == "change_status":
        # change_status can change relationship_status OR belief
        # For relationship: pass person (name) and type (dating/married/etc)
        # For belief: pass value (belief string)
        person = args.get("person")
        value = args.get("value")
        
        agent = world.agents[agent_id]
        
        if person and args.get("type"):
            # Change relationship status
            rel_type = args.get("type")
            valid_statuses = ["single", "dating", "married", "divorced", "widowed", "engaged", "complicated"]
            if rel_type.lower() not in valid_statuses:
                return f"Invalid status. Valid: {', '.join(valid_statuses)}", False
            agent.relationships_status = rel_type
            return f"Changed relationship status to: {rel_type}", True
        
        if value and not args.get("type"):
            # Change belief
            agent.beliefs = value
            return f"Changed belief to: {value}", True
        
        return "Specify either person+type for relationship or value for belief", False

    # Placeholder for other tools
    return f"Tool '{name}' not implemented yet", False
