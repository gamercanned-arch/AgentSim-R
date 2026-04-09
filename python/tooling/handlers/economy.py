from __future__ import annotations
import uuid
from python.core import is_market_open
from python.config import MAX_INVENTORY
from python.locations import (
    describe_home_location,
    get_current_location_def,
    get_location_by_name,
    get_location_center,
    get_location_outside_entrance_point,
)
from python.tooling.catalogs import ITEM_CATALOG, VEHICLE_CATALOG
from python.tooling.helpers import (
    canonicalize_food_name,
    canonicalize_item_name,
    check_open_hours,
    record_expense,
    validate_shares,
)
def _find_catalog_entry(item_name: str):
    for category, items in ITEM_CATALOG.items():
        if item_name in items:
            return category, items[item_name]
    return None, None
def _current_store_if_inside(agent):
    here = get_current_location_def(agent.x, agent.y, agent.z)
    if here and here.name in {"Store_A", "Store_B"}:
        return here
    return None
def handle_buy_item(agent, world, args: dict):
    item = canonicalize_item_name(str(args.get("item", "")).strip()[:100])
    if item in VEHICLE_CATALOG:
        dealership = get_location_by_name("Vehicle_Dealership")
        if not dealership:
            agent.failed_calls += 1
            return "Vehicle_Dealership not found.", False, 60
        here = get_current_location_def(agent.x, agent.y, agent.z)
        if not here or here.name != "Vehicle_Dealership":
            agent.failed_calls += 1
            return "You must be inside Vehicle_Dealership to buy a vehicle.", False, 60
        if not check_open_hours(dealership, world.sim_time):
            agent.failed_calls += 1
            return "Vehicle_Dealership is currently closed.", False, 60
        price = float(VEHICLE_CATALOG[item]["price"])
        if agent.money < price:
            agent.failed_calls += 1
            return f"Cannot afford {item} (${price:.2f}).", False, 60
        if getattr(agent, "vehicle_type", "") == item:
            agent.failed_calls += 1
            return f"You already own a {item}.", False, 60
        agent.money -= price
        record_expense(agent, price)
        agent.vehicle_type = item
        outside = get_location_outside_entrance_point(dealership, offset_m=15.0)
        agent.vehicle_x, agent.vehicle_y, agent.vehicle_z = outside
        return (
            f"Bought vehicle: {item} for ${price:.2f}. It is parked outside the dealership.",
            True,
            600,
        )
    if item in ITEM_CATALOG["housing"]:
        if item == agent.current_home_type:
            agent.failed_calls += 1
            return "You seem to already own this type of house.", False, 60
        price = float(ITEM_CATALOG["housing"][item])
        old_home_type = agent.current_home_type
        old_home_location = agent.home_location
        old_price = float(ITEM_CATALOG["housing"].get(old_home_type, 0.0) or 0.0)
        sell_price = old_price * 0.7 if old_home_type else 0.0
        if (agent.money + sell_price) < price:
            agent.failed_calls += 1
            return (
                f"Cannot afford {item}. Need ${price:.2f}, have ${agent.money:.2f} "
                f"+ ${sell_price:.2f} in home equity.",
                False,
                60,
            )
        new_home_location = world.allocate_home_lot(item, prefer_floor1=True)
        if not new_home_location:
            agent.failed_calls += 1
            return f"No vacant {item} Floor 1 lots are currently available.", False, 60
        if old_home_type and old_home_location:
            world.release_home_lot(old_home_type, old_home_location)
        agent.money += sell_price
        agent.money -= price
        record_expense(agent, price)
        agent.current_home_type = item
        agent.home_location = new_home_location
        agent.owned_locations = [new_home_location]
        new_loc_def = get_location_by_name(new_home_location)
        if new_loc_def:
            cx, cy, cz = get_location_center(new_loc_def)
            agent.x, agent.y, agent.z = cx, cy, cz
            agent.location = new_home_location
        return (
            f"Sold {old_home_type or 'previous home'} for ${sell_price:.2f}. "
            f"Bought {item} for ${price:.2f}. "
            f"New home: Home_{agent.name} ({describe_home_location(new_home_location)}).",
            True,
            3600,
        )
    category, entry = _find_catalog_entry(item)
    if category is None:
        agent.failed_calls += 1
        valid = (
            list(ITEM_CATALOG["food"].keys())
            + list(ITEM_CATALOG["everyday"].keys())
            + list(ITEM_CATALOG["health"].keys())
            + list(ITEM_CATALOG["housing"].keys())
            + list(VEHICLE_CATALOG.keys())
        )
        return f"Item '{item}' not found. Valid: {', '.join(valid)}.", False, 60
    if category != "food":
        store_loc = _current_store_if_inside(agent)
        if not store_loc:
            agent.failed_calls += 1
            return "Non-food items can only be bought while inside Store_A or Store_B.", False, 60
        if not check_open_hours(store_loc, world.sim_time):
            agent.failed_calls += 1
            return f"{store_loc.name} is currently closed.", False, 60
    if len(agent.inventory) >= MAX_INVENTORY:
        agent.failed_calls += 1
        return "Inventory full.", False, 60
    if world.store_inventory.get(item, 0) <= 0:
        agent.failed_calls += 1
        return f"'{item}' is completely out of stock in the village.", False, 60
    price = entry["price"] if isinstance(entry, dict) else float(entry)
    if agent.money < price:
        agent.failed_calls += 1
        return "Cannot afford.", False, 60
    agent.money -= price
    record_expense(agent, price)
    world.store_inventory[item] -= 1
    agent.inventory.append({"id": str(uuid.uuid4()), "item": item, "durability": 5, "bought": world.sim_time})
    return f"Bought {item} for ${price:.2f}.", True, 120
def handle_eat_food(agent, world, args: dict):
    item = canonicalize_food_name(str(args.get("item", "")).strip()[:100])
    food_data = None
    held_name = (agent.currently_holding or {}).get("item", "")
    if agent.currently_holding and str(held_name).lower() == item.lower():
        if item not in ITEM_CATALOG["food"]:
            agent.failed_calls += 1
            return f"{item} is not edible food.", False, 60
        food_data = agent.currently_holding
        agent.currently_holding = None
    else:
        idx = next(
            (i for i, it in enumerate(agent.inventory) if str(it.get("item", "")).lower() == item.lower()),
            -1,
        )
        if idx != -1:
            if item not in ITEM_CATALOG["food"]:
                agent.failed_calls += 1
                return f"{item} is not edible food.", False, 60
            food_data = agent.inventory.pop(idx)
    if food_data:
        if world.sim_time - food_data.get("bought", world.sim_time) > 172800:
            agent.health = max(0.0, agent.health - 10.0)
            f = ITEM_CATALOG["food"][item]
            agent.hunger = max(0.0, agent.hunger - 0.2 * float(f["hunger"]))
            agent.hydration = min(100.0, max(0.0, agent.hydration + 0.2 * float(f.get("hydration", 0))))
            return "The food was spoiled! Health -10. Minimal nutrition received.", True, 60
    else:
        if item not in ITEM_CATALOG["food"]:
            agent.failed_calls += 1
            return f"Food not found. Valid: {', '.join(ITEM_CATALOG['food'].keys())}.", False, 60
        if world.store_inventory.get(item, 0) <= 0:
            agent.failed_calls += 1
            return f"'{item}' is completely out of stock in the village.", False, 60
        cost = float(ITEM_CATALOG["food"][item]["price"])
        if agent.money < cost:
            agent.failed_calls += 1
            return "Cannot afford.", False, 60
        agent.money -= cost
        record_expense(agent, cost)
        world.store_inventory[item] -= 1
    f = ITEM_CATALOG["food"][item]
    agent.hunger = max(0.0, agent.hunger - float(f["hunger"]))
    agent.hydration = min(100.0, max(0.0, agent.hydration + float(f.get("hydration", 0))))
    agent.health = min(100.0, agent.health + 2.0)
    agent.energy = min(100.0, agent.energy + 5.0)
    return (
        f"Ate {item}. Hunger -{f['hunger']}, Hydration +{f.get('hydration', 0)}. Health +2, Energy +5.",
        True,
        int(f.get("time", 60)),
    )
def handle_seek_medicalcare(agent, world, args: dict):
    hospital = get_location_by_name("Hospital")
    if not hospital:
        agent.failed_calls += 1
        return "Hospital location not found.", False, 60
    here = get_current_location_def(agent.x, agent.y, agent.z)
    if not here or here.name != "Hospital":
        agent.failed_calls += 1
        return "You must be inside Hospital to seek medical care. Move to Hospital and walk inside.", False, 60
    if not check_open_hours(hospital, world.sim_time):
        agent.failed_calls += 1
        return "Hospital is currently closed.", False, 60
    cost = 50.0
    if agent.money < cost:
        agent.failed_calls += 1
        return "Cannot afford medical care.", False, 60
    agent.money -= cost
    record_expense(agent, cost)
    agent.health = min(100.0, agent.health + 30.0)
    return "Received medical care. Health +30.", True, 600
def handle_buy_stock(agent, world, args: dict):
    shares, err = validate_shares(args.get("shares", 0))
    if err:
        agent.failed_calls += 1
        return err, False, 60
    if not is_market_open(world.sim_time):
        agent.pending_market_orders.append({"type": "buy", "shares": shares, "queued_at": world.sim_time})
        return f"Market closed. Buy order for {shares} shares queued.", True, 60
    cost = world.market_price * shares
    if agent.money < cost:
        agent.failed_calls += 1
        return "Cannot afford.", False, 60
    agent.money -= cost
    old_cost_basis = agent.last_known_price * agent.shares_owned
    agent.shares_owned += shares
    agent.last_known_price = (old_cost_basis + cost) / agent.shares_owned
    world.net_volume_this_period += shares
    return f"Bought {shares} share(s).", True, 60
def handle_sell_stock(agent, world, args: dict):
    shares, err = validate_shares(args.get("shares", 0))
    if err:
        agent.failed_calls += 1
        return err, False, 60
    if agent.shares_owned < shares:
        agent.failed_calls += 1
        return "Not enough shares.", False, 60
    if not is_market_open(world.sim_time):
        agent.pending_market_orders.append({"type": "sell", "shares": shares, "queued_at": world.sim_time})
        return f"Market closed. Sell order for {shares} shares queued.", True, 60
    proceeds = world.market_price * shares
    agent.money += proceeds
    agent.shares_owned -= shares
    if agent.shares_owned == 0:
        agent.last_known_price = 0.0
    world.net_volume_this_period -= shares
    return f"Sold {shares} share(s).", True, 60
