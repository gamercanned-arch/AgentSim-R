import math
from dataclasses import dataclass, field
from typing import List, Dict

@dataclass
class LocationDef:
    name: str
    x_min: float; x_max: float
    y_min: float; y_max: float
    z_min: float; z_max: float
    has_roof: bool
    open_time: float 
    close_time: float
    interactables: List[Dict] = field(default_factory=list)

LOCATIONS_3D = [
    LocationDef("Home_Alex", 500, 520, 800, 820, 0, 5, True, 0.0, 24.0, [
        {"name": "Bed", "z": 0}, {"name": "Fridge", "z": 0}, {"name": "Computer Desk", "z": 0}, {"name": "Couch", "z": 0}
    ]),
    LocationDef("Home_Jamie", 1200, 1220, 1500, 1520, 0, 5, True, 0.0, 24.0, [
        {"name": "Bed", "z": 0}, {"name": "Dining Table", "z": 0}, {"name": "Bookshelf", "z": 0}, {"name": "TV", "z": 0}
    ]),
    LocationDef("Home_Taylor", 800, 820, 2200, 2220, 0, 10, True, 0.0, 24.0, [
        {"name": "Couch", "z": 0}, {"name": "TV", "z": 0}, {"name": "Staircase_Up", "z": 0, "target_z": 5},
        {"name": "Bed", "z": 5}, {"name": "Study Desk", "z": 5}, {"name": "Staircase_Down", "z": 5, "target_z": 0}
    ]),
    LocationDef("Home_Jordan", 2500, 2520, 1800, 1820, 0, 5, True, 0.0, 24.0, [
        {"name": "Bed", "z": 0}, {"name": "Fridge", "z": 0}, {"name": "Recliner", "z": 0}, {"name": "TV", "z": 0}
    ]),
    LocationDef("Home_Mia", 3200, 3220, 2400, 2420, 0, 5, True, 0.0, 24.0, [
        {"name": "Bed", "z": 0}, {"name": "Art Easel", "z": 0}, {"name": "Dining Table", "z": 0}, {"name": "Plants", "z": 0}
    ]),
    LocationDef("Home_Ethan", 4100, 4130, 3100, 3130, 0, 15, True, 0.0, 24.0, [
        {"name": "Home Theater", "z": 0}, {"name": "Minibar", "z": 0}, {"name": "Elevator", "z": 0, "target_z": 10},
        {"name": "King Bed", "z": 10}, {"name": "Safe", "z": 10}, {"name": "Elevator", "z": 10, "target_z": 0}
    ]),
    LocationDef("Hospital", 2480, 2550, 2480, 2550, 0, 20, True, 0.0, 24.0, [
        {"name": "Reception Desk", "z": 0}, {"name": "Waiting Chairs", "z": 0}, {"name": "Vending Machine", "z": 0}, 
        {"name": "Staircase_Up", "z": 0, "target_z": 5}, {"name": "Hospital Bed", "z": 5}, {"name": "MRI Machine", "z": 5}, {"name": "Staircase_Down", "z": 5, "target_z": 0}
    ]),
    LocationDef("School", 1780, 1850, 3180, 3250, 0, 10, True, 7.0, 18.0, [
        {"name": "Lockers", "z": 0}, {"name": "Whiteboard", "z": 0}, {"name": "Teacher Desk", "z": 0}, {"name": "Student Desks", "z": 0}
    ]),
    LocationDef("Office_FedEx", 2980, 3050, 1180, 1250, 0, 5, True, 6.0, 20.0, [
        {"name": "Sorting Belt", "z": 0}, {"name": "Forklift", "z": 0}, {"name": "Loading Dock", "z": 0}, {"name": "Coffee Machine", "z": 0}
    ]),
    LocationDef("Startup_Sowl", 4480, 4550, 3480, 3550, 0, 15, True, 8.0, 22.0, [
        {"name": "Ping Pong Table", "z": 0}, {"name": "Espresso Machine", "z": 0}, {"name": "Elevator", "z": 0, "target_z": 10},
        {"name": "Server Rack", "z": 10}, {"name": "Standing Desk", "z": 10}, {"name": "Elevator", "z": 10, "target_z": 0}
    ]),
    LocationDef("Store_A", 1480, 1520, 980, 1020, 0, 5, True, 8.0, 22.0, [
        {"name": "Cash Register", "z": 0}, {"name": "Display Shelves", "z": 0}, {"name": "Shopping Cart", "z": 0}
    ]),
    LocationDef("Store_B", 2780, 2820, 2080, 2120, 0, 5, True, 8.0, 22.0, [
        {"name": "Cash Register", "z": 0}, {"name": "Display Shelves", "z": 0}, {"name": "Shopping Cart", "z": 0}
    ]),
    LocationDef("Market", 2150, 2250, 2750, 2850, 0, 5, False, 6.0, 18.0, [
        {"name": "Produce Stand", "z": 0}, {"name": "Cashbox", "z": 0}, {"name": "Wooden Crates", "z": 0}
    ]),
    LocationDef("Park_Central", 1900, 2100, 1900, 2100, 0, 0, False, 0.0, 24.0, [
        {"name": "Park Bench", "z": 0}, {"name": "Oak Tree", "z": 0}, {"name": "Trash Can", "z": 0}, {"name": "Fountain", "z": 0}
    ]),
    LocationDef("Cafe", 1680, 1720, 1680, 1720, 0, 5, True, 6.0, 20.0, [
        {"name": "Espresso Machine", "z": 0}, {"name": "Cash Register", "z": 0}, {"name": "Cozy Armchair", "z": 0}, {"name": "Patio Table", "z": 0}
    ]),
    LocationDef("Library", 2280, 2330, 2980, 3030, 0, 15, True, 9.0, 21.0, [
        {"name": "Reading Table", "z": 0}, {"name": "Bookshelf", "z": 0}, {"name": "Librarian Desk", "z": 0}, {"name": "Public Computer", "z": 0}
    ]),
    LocationDef("Gym", 3080, 3130, 2780, 2830, 0, 10, True, 5.0, 23.0, [
        {"name": "Treadmill", "z": 0}, {"name": "Dumbbell Rack", "z": 0}, {"name": "Bench Press", "z": 0}, {"name": "Water Cooler", "z": 0}
    ]),
    LocationDef("Village_Square", 2000, 2100, 1900, 2000, 0, 0, False, 0.0, 24.0, [
        {"name": "Statue", "z": 0}, {"name": "Streetlamp", "z": 0}, {"name": "Notice Board", "z": 0}
    ]),
]

def get_distance_3d(p1: tuple, p2: tuple) -> float:
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2 + (p1[2]-p2[2])**2)

def get_location_by_name(name: str) -> LocationDef:
    for loc in LOCATIONS_3D:
        if loc.name.lower() == name.lower(): return loc
    return None

def is_point_in_loc(x, y, z, loc: LocationDef) -> bool:
    return (loc.x_min <= x <= loc.x_max) and (loc.y_min <= y <= loc.y_max) and (loc.z_min <= z <= loc.z_max)

def get_current_location_def(x, y, z) -> LocationDef:
    for loc in LOCATIONS_3D:
        if is_point_in_loc(x, y, z, loc): return loc
    return None