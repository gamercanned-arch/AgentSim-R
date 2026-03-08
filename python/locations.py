# Fixed location coordinates for determinism
# Using a 5000x5000 meter grid
LOCATIONS = {
    # Homes (starting locations)
    "Home_Alex": (500, 800),
    "Home_Jamie": (1200, 1500),
    "Home_Taylor": (800, 2200),
    "Home_Jordan": (2500, 1800),
    "Home_Mia": (3200, 2400),
    "Home_Ethan": (4100, 3100),
    # Public facilities
    "Hospital": (2500, 2500),
    "School": (1800, 3200),
    # Workplaces
    "Office_FedEx": (3000, 1200),
    "Startup_Sowl": (4500, 3500),
    # Commercial
    "Store_A": (1500, 1000),
    "Store_B": (2800, 2100),
    "Market": (2200, 2800),
    "Bank": (2600, 1900),
    # Recreation
    "Park_Central": (2000, 2000),
    "Cafe": (1700, 1700),
    "Library": (2300, 3000),
    "Gym": (3100, 2800),
    "Theater": (3500, 2200),
    "Bar": (3800, 2000),
    "Workshop": (1200, 3500),
    "Art_Studio": (4000, 2800),
    # Services
    "Post_Office": (2700, 1600),
    "Police_Station": (2400, 2200),
    "Village_Square": (2000, 2000),
    # Purchasable Housing (can be bought via buy_item)
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

def get_distance(p1: tuple, p2: tuple) -> float:
    return ((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)**0.5