import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class LocationDef:
    name: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float
    has_roof: bool
    open_time: float
    close_time: float
    interactables: List[Dict] = field(default_factory=list)


PUBLIC_LOCATIONS_3D = [
    LocationDef(
        name="Hospital",
        x_min=2480.0, x_max=2550.0,
        y_min=2480.0, y_max=2550.0,
        z_min=0.0, z_max=20.0,
        has_roof=True, open_time=0.0, close_time=24.0,
        interactables=[
            {"name": "Reception Desk", "z": 0},
            {"name": "Waiting Chairs", "z": 0},
            {"name": "Vending Machine", "z": 0},
            {"name": "Staircase_Up", "z": 0, "target_z": 5},
            {"name": "Hospital Bed", "z": 5},
            {"name": "MRI Machine", "z": 5},
            {"name": "Staircase_Down", "z": 5, "target_z": 0}
        ]
    ),
    LocationDef(
        name="School",
        x_min=1780.0, x_max=1850.0,
        y_min=3180.0, y_max=3250.0,
        z_min=0.0, z_max=10.0,
        has_roof=True, open_time=7.0, close_time=18.0,
        interactables=[
            {"name": "Lockers", "z": 0},
            {"name": "Whiteboard", "z": 0},
            {"name": "Teacher Desk", "z": 0},
            {"name": "Student Desks", "z": 0}
        ]
    ),
    LocationDef(
        name="Office_FedEx",
        x_min=2980.0, x_max=3050.0,
        y_min=1180.0, y_max=1250.0,
        z_min=0.0, z_max=5.0,
        has_roof=True, open_time=6.0, close_time=20.0,
        interactables=[
            {"name": "Sorting Belt", "z": 0},
            {"name": "Forklift", "z": 0},
            {"name": "Loading Dock", "z": 0},
            {"name": "Coffee Machine", "z": 0}
        ]
    ),
    LocationDef(
        name="Startup_Sowl",
        x_min=4480.0, x_max=4550.0,
        y_min=3480.0, y_max=3550.0,
        z_min=0.0, z_max=15.0,
        has_roof=True, open_time=8.0, close_time=22.0,
        interactables=[
            {"name": "Ping Pong Table", "z": 0},
            {"name": "Espresso Machine", "z": 0},
            {"name": "Elevator", "z": 0, "target_z": 10},
            {"name": "Server Rack", "z": 10},
            {"name": "Standing Desk", "z": 10},
            {"name": "Elevator", "z": 10, "target_z": 0}
        ]
    ),
    LocationDef(
        name="Store_A",
        x_min=1480.0, x_max=1520.0,
        y_min=980.0, y_max=1020.0,
        z_min=0.0, z_max=5.0,
        has_roof=True, open_time=8.0, close_time=22.0,
        interactables=[
            {"name": "Cash Register", "z": 0},
            {"name": "Display Shelves", "z": 0},
            {"name": "Shopping Cart", "z": 0}
        ]
    ),
    LocationDef(
        name="Store_B",
        x_min=2780.0, x_max=2820.0,
        y_min=2080.0, y_max=2120.0,
        z_min=0.0, z_max=5.0,
        has_roof=True, open_time=8.0, close_time=22.0,
        interactables=[
            {"name": "Cash Register", "z": 0},
            {"name": "Display Shelves", "z": 0},
            {"name": "Shopping Cart", "z": 0}
        ]
    ),
    LocationDef(
        name="Market",
        x_min=2150.0, x_max=2250.0,
        y_min=2750.0, y_max=2850.0,
        z_min=0.0, z_max=5.0,
        has_roof=False, open_time=6.0, close_time=18.0,
        interactables=[
            {"name": "Produce Stand", "z": 0},
            {"name": "Cashbox", "z": 0},
            {"name": "Wooden Crates", "z": 0}
        ]
    ),
    LocationDef(
        name="Park_Central",
        x_min=1900.0, x_max=2100.0,
        y_min=1900.0, y_max=2100.0,
        z_min=0.0, z_max=0.0,
        has_roof=False, open_time=0.0, close_time=24.0,
        interactables=[
            {"name": "Park Bench", "z": 0},
            {"name": "Oak Tree", "z": 0},
            {"name": "Trash Can", "z": 0},
            {"name": "Fountain", "z": 0}
        ]
    ),
    LocationDef(
        name="Cafe",
        x_min=1680.0, x_max=1720.0,
        y_min=1680.0, y_max=1720.0,
        z_min=0.0, z_max=5.0,
        has_roof=True, open_time=6.0, close_time=20.0,
        interactables=[
            {"name": "Espresso Machine", "z": 0},
            {"name": "Cash Register", "z": 0},
            {"name": "Cozy Armchair", "z": 0},
            {"name": "Patio Table", "z": 0}
        ]
    ),
    LocationDef(
        name="Library",
        x_min=2280.0, x_max=2330.0,
        y_min=2980.0, y_max=3030.0,
        z_min=0.0, z_max=15.0,
        has_roof=True, open_time=9.0, close_time=21.0,
        interactables=[
            {"name": "Reading Table", "z": 0},
            {"name": "Bookshelf", "z": 0},
            {"name": "Librarian Desk", "z": 0},
            {"name": "Public Computer", "z": 0}
        ]
    ),
    LocationDef(
        name="Gym",
        x_min=3080.0, x_max=3130.0,
        y_min=2780.0, y_max=2830.0,
        z_min=0.0, z_max=10.0,
        has_roof=True, open_time=5.0, close_time=23.0,
        interactables=[
            {"name": "Treadmill", "z": 0},
            {"name": "Dumbbell Rack", "z": 0},
            {"name": "Bench Press", "z": 0},
            {"name": "Water Cooler", "z": 0}
        ]
    ),
    LocationDef(
        name="Village_Square",
        x_min=2120.0, x_max=2220.0,
        y_min=1900.0, y_max=2000.0,
        z_min=0.0, z_max=0.0,
        has_roof=False, open_time=0.0, close_time=24.0,
        interactables=[
            {"name": "Statue", "z": 0},
            {"name": "Streetlamp", "z": 0},
            {"name": "Notice Board", "z": 0}
        ]
    ),
]


HOME_LOCATION_META: Dict[str, Dict] = {}
HOME_LOTS_BY_TYPE: Dict[str, List[str]] = {
    "Small Apartment": [],
    "Apartment": [],
    "House": [],
    "Luxury House": [],
}


def _home_interactables(home_type: str, floor: int = 0) -> List[Dict]:
    if home_type == "Small Apartment":
        return [
            {"name": "Bed", "z": floor},
            {"name": "Kitchenette", "z": floor},
            {"name": "Study Desk", "z": floor},
            {"name": "Bookshelf", "z": floor},
        ]
    if home_type == "Apartment":
        return [
            {"name": "Bed", "z": floor},
            {"name": "Dining Table", "z": floor},
            {"name": "TV", "z": floor},
            {"name": "Desk", "z": floor},
        ]
    if home_type == "House":
        return [
            {"name": "Bed", "z": floor},
            {"name": "Fridge", "z": floor},
            {"name": "Couch", "z": floor},
            {"name": "Dining Table", "z": floor},
        ]
    return [
        {"name": "King Bed", "z": floor},
        {"name": "Home Theater", "z": floor},
        {"name": "Minibar", "z": floor},
        {"name": "Safe", "z": floor},
    ]


def _register_home_lot(
    name: str,
    home_type: str,
    label: str,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    z_min: float,
    z_max: float,
    floor: int,
) -> LocationDef:
    HOME_LOCATION_META[name] = {
        "type": home_type,
        "label": label,
        "floor": floor,
    }
    HOME_LOTS_BY_TYPE[home_type].append(name)
    return LocationDef(
        name=name,
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
        z_min=z_min,
        z_max=z_max,
        has_roof=True,
        open_time=0.0,
        close_time=24.0,
        interactables=_home_interactables(home_type, int(z_min)),
    )


HOME_LOCATIONS_3D: List[LocationDef] = []

# Small Apartments: 2 towers x 3 floors
small_towers = [
    ("Maple", 760.0, 2180.0),
    ("Cedar", 860.0, 2180.0),
]
unit_num = 1
for tower_name, base_x, base_y in small_towers:
    for floor_idx in range(3):
        z0 = float(floor_idx * 5)
        name = f"SmallApartment_{tower_name}_Unit_{unit_num}_Floor_{floor_idx + 1}"
        label = f"Small Apartment Unit {unit_num}, Floor {floor_idx + 1}"
        HOME_LOCATIONS_3D.append(
            _register_home_lot(
                name=name,
                home_type="Small Apartment",
                label=label,
                x_min=base_x,
                x_max=base_x + 22.0,
                y_min=base_y,
                y_max=base_y + 22.0,
                z_min=z0,
                z_max=z0 + 4.5,
                floor=floor_idx + 1,
            )
        )
        unit_num += 1

# Apartments: 2 towers x 3 floors
apt_towers = [
    ("Oak", 1120.0, 1440.0),
    ("River", 2460.0, 1740.0),
]
unit_num = 1
for tower_name, base_x, base_y in apt_towers:
    for floor_idx in range(3):
        z0 = float(floor_idx * 5)
        name = f"Apartment_{tower_name}_Unit_{unit_num}_Floor_{floor_idx + 1}"
        label = f"Apartment Unit {unit_num}, Floor {floor_idx + 1}"
        HOME_LOCATIONS_3D.append(
            _register_home_lot(
                name=name,
                home_type="Apartment",
                label=label,
                x_min=base_x,
                x_max=base_x + 26.0,
                y_min=base_y,
                y_max=base_y + 26.0,
                z_min=z0,
                z_max=z0 + 4.5,
                floor=floor_idx + 1,
            )
        )
        unit_num += 1

# Houses
house_coords = [
    (3160.0, 2360.0),
    (3240.0, 2360.0),
    (3320.0, 2360.0),
    (3160.0, 2440.0),
    (3240.0, 2440.0),
    (3320.0, 2440.0),
]
for idx, (base_x, base_y) in enumerate(house_coords, start=1):
    name = f"House_Lot_{idx}"
    label = f"House Lot {idx}"
    HOME_LOCATIONS_3D.append(
        _register_home_lot(
            name=name,
            home_type="House",
            label=label,
            x_min=base_x,
            x_max=base_x + 28.0,
            y_min=base_y,
            y_max=base_y + 28.0,
            z_min=0.0,
            z_max=6.0,
            floor=1,
        )
    )

# Luxury Houses
lux_coords = [
    (4040.0, 3040.0),
    (4140.0, 3040.0),
    (4240.0, 3040.0),
    (4040.0, 3160.0),
    (4140.0, 3160.0),
    (4240.0, 3160.0),
]
for idx, (base_x, base_y) in enumerate(lux_coords, start=1):
    name = f"LuxuryHouse_Estate_{idx}"
    label = f"Luxury House Estate {idx}"
    HOME_LOCATIONS_3D.append(
        _register_home_lot(
            name=name,
            home_type="Luxury House",
            label=label,
            x_min=base_x,
            x_max=base_x + 36.0,
            y_min=base_y,
            y_max=base_y + 36.0,
            z_min=0.0,
            z_max=10.0,
            floor=1,
        )
    )

LOCATIONS_3D = PUBLIC_LOCATIONS_3D + HOME_LOCATIONS_3D


def get_distance_3d(p1: tuple, p2: tuple) -> float:
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2 + (p1[2] - p2[2]) ** 2)


def get_location_by_name(name: str) -> Optional[LocationDef]:
    for loc in LOCATIONS_3D:
        if loc.name.lower() == name.lower():
            return loc
    return None


def get_location_center(loc: LocationDef) -> tuple:
    return (
        (loc.x_min + loc.x_max) / 2.0,
        (loc.y_min + loc.y_max) / 2.0,
        loc.z_min,
    )


def is_point_in_loc(x: float, y: float, z: float, loc: LocationDef) -> bool:
    return (
        (loc.x_min <= x <= loc.x_max)
        and (loc.y_min <= y <= loc.y_max)
        and (loc.z_min <= z <= loc.z_max)
    )


def get_current_location_def(x: float, y: float, z: float) -> Optional[LocationDef]:
    for loc in LOCATIONS_3D:
        if is_point_in_loc(x, y, z, loc):
            return loc
    return None


def is_home_location(name: str) -> bool:
    return name in HOME_LOCATION_META


def get_home_type_for_location(name: str) -> Optional[str]:
    meta = HOME_LOCATION_META.get(name)
    return meta["type"] if meta else None


def describe_home_location(name: str) -> str:
    meta = HOME_LOCATION_META.get(name)
    if not meta:
        return name.replace("_", " ")
    return meta["label"]


def get_home_lots_inventory() -> Dict[str, List[str]]:
    return {home_type: list(names) for home_type, names in HOME_LOTS_BY_TYPE.items()}


def humanize_location_name(name: str) -> str:
    if not name:
        return "Unknown"
    if is_home_location(name):
        return describe_home_location(name)
    return name.replace("_", " ")


def get_location_label(name: str) -> str:
    return humanize_location_name(name)


def get_location_entrance_point(loc: LocationDef) -> tuple:
    """Get the entrance point inside the location (center at z_min)."""
    return get_location_center(loc)


def get_location_outside_entrance_point(loc: LocationDef, offset_m: float = 20.0) -> tuple:
    """Get the outside entrance point, offset from the center towards the outside."""
    cx, cy, cz = get_location_center(loc)
    # Simple offset towards negative y (assuming front entrance)
    return (cx, cy - offset_m, cz)