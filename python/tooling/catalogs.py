from __future__ import annotations

# Central catalogs live here so tools/prompting/scheduler can import without circulars.

ITEM_CATALOG = {
    "food": {
        "Snacks": {"price": 4, "hunger": 10, "hydration": 0, "time": 60, "caffeine": 0},
        "Water": {"price": 2, "hunger": 0, "hydration": 35, "time": 60, "caffeine": 0},
        "Coffee": {"price": 5, "hunger": 0, "hydration": 10, "time": 120, "caffeine": 1},
        "Sandwich": {"price": 10, "hunger": 30, "hydration": 0, "time": 600, "caffeine": 0},
        "Pizza": {"price": 15, "hunger": 45, "hydration": 0, "time": 1200, "caffeine": 0},
        "Premium Meal": {"price": 25, "hunger": 80, "hydration": 0, "time": 1800, "caffeine": 0},
    },
    "everyday": {
        "Toothbrush": 5,
        "Clothes": 50,
        "Book": 20,
        "Art Supplies": 40,
        "Notebook": 5,
    },
    "housing": {
        "Small Apartment": 75_000,
        "Apartment": 120_000,
        "House": 400_000,
        "Luxury House": 750_000,
    },
    "health": {
        "Medicine": 12,
        "Vitamins": 25,
        "First aid kit": 30,
    },
}

HOBBY_ITEMS = {"Book", "Art Supplies", "Notebook"}

VEHICLE_CATALOG = {
    # price: purchase price at Vehicle_Dealership; default Scooter is $0
    # fuel_per_km: $ per km
    # speed_mps: meters per second
    # energy_per_km: small fatigue cost while riding
    "Scooter": {"price": 0.0, "speed_mps": 12.5, "fuel_per_km": 0.05, "energy_per_km": 0.05},
    "E-Bike": {"price": 600.0, "speed_mps": 9.0, "fuel_per_km": 0.01, "energy_per_km": 0.07},
    "Motorcycle": {"price": 3000.0, "speed_mps": 18.0, "fuel_per_km": 0.10, "energy_per_km": 0.06},
    "Car": {"price": 9000.0, "speed_mps": 22.0, "fuel_per_km": 0.20, "energy_per_km": 0.04},
}

WORKPLACE_BY_JOB = {
    "developer": "Startup_Sowl",
    "tech": "Startup_Sowl",
    "startup": "Startup_Sowl",
    "founder": "Startup_Sowl",
    "nurse": "Hospital",
    "doctor": "Hospital",
    "delivery": "Office_FedEx",
    "driver": "Office_FedEx",
    "fedex": "Office_FedEx",
    "teacher": "School",
    "tutor": "School",
}

EDUCATION_LOCATIONS = ["School", "Library"]


def generate_catalog_text() -> str:
    """Generate a human-readable catalog of all items that agents can reference."""
    lines = []
    lines.append("[Catalog - Valid Values for Tools]")
    lines.append("")

    # Locations
    lines.append("## Locations (place for move_to)")
    public_locations = [
        "Hospital", "School", "Office_FedEx", "Startup_Sowl",
        "Store_A", "Store_B", "Market", "Park_Central",
        "Cafe", "Library", "Gym", "Village_Square"
    ]
    lines.append("- Public: " + ", " .join(public_locations))
    lines.append("- Homes: Home_<Name> (e.g., Home_Alex, Home_Taylor, etc.)")
    lines.append("")

    # Items
    lines.append("## Buyable Items (item for buy_item)")
    for category, items in ITEM_CATALOG.items():
        lines.append(f"- {category.title()}:")
        for name, data in items.items():
            if isinstance(data, dict):
                price = data.get("price", "?")
            else:
                price = data
            lines.append(f"  - {name}: ${price}")
    lines.append("")

    # Vehicles
    lines.append("## Vehicles")
    for name, data in VEHICLE_CATALOG.items():
        price = data.get("price", 0)
        lines.append(f"- {name}: ${price:.0f}")
    lines.append("")

    # Jobs
    lines.append("## Jobs (jobname for work_job)")
    workplace_to_jobs: dict = {}
    for job, workplace in WORKPLACE_BY_JOB.items():
        if workplace not in workplace_to_jobs:
            workplace_to_jobs[workplace] = []
        workplace_to_jobs[workplace].append(job)
    for workplace, jobs in workplace_to_jobs.items():
        lines.append(f"- {workplace}: " + ", ".join(jobs))
    lines.append("")

    # Hobby items
    lines.append("## Hobby Items (item for do_hobby)")
    lines.append("- " + ", ".join(sorted(HOBBY_ITEMS)))
    lines.append("")

    # Education
    lines.append("## Education Locations (location for get_education)")
    lines.append("- " + ", ".join(EDUCATION_LOCATIONS))

    return "\n".join(lines)