from __future__ import annotations

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
    lines = []
    lines.append("[Catalog - Valid Values for Tools]")
    lines.append("")

    lines.append("## Locations for move_to")
    public_locations = [
        "Hospital", "School", "Office_FedEx", "Startup_Sowl",
        "Store_A", "Store_B", "Market", "Park_Central",
        "Cafe", "Library", "Gym", "Village_Square",
        "Farm", "Mall", "Lake", "Vehicle_Dealership",
    ]
    lines.append("- Public: " + ", ".join(public_locations))
    lines.append("- Homes: Home_<Name> such as Home_Alex or Home_Taylor")
    lines.append("- Use named places only. Coordinates are never valid move_to inputs.")
    lines.append("")

    lines.append("## Buyable Food")
    lines.append("- Food can be bought abstractly from village stock from anywhere if in stock and affordable.")
    for name, data in ITEM_CATALOG["food"].items():
        lines.append(
            f"- {name}: ${data['price']} | Hunger -{data['hunger']} | Hydration +{data.get('hydration', 0)} | Time {int(data.get('time', 60))}s"
        )
    lines.append("")

    lines.append("## Buyable Non-Food Items")
    lines.append("- Everyday and health items must be bought while inside Store_A or Store_B.")
    lines.append("- Everyday:")
    for name, price in ITEM_CATALOG["everyday"].items():
        lines.append(f"  - {name}: ${price}")
    lines.append("- Health:")
    for name, price in ITEM_CATALOG["health"].items():
        lines.append(f"  - {name}: ${price}")
    lines.append("")

    lines.append("## Homes")
    for name, price in ITEM_CATALOG["housing"].items():
        lines.append(f"- {name}: ${price}")
    lines.append("")

    lines.append("## Vehicles")
    lines.append("- Vehicles must be bought while inside Vehicle_Dealership.")
    for name, data in VEHICLE_CATALOG.items():
        lines.append(
            f"- {name}: ${data['price']:.0f} | Speed {data['speed_mps']:.1f} m/s | Fuel ${data['fuel_per_km']:.2f}/km"
        )
    lines.append("")

    lines.append("## Jobs for work_job")
    workplace_to_jobs: dict = {}
    for job, workplace in WORKPLACE_BY_JOB.items():
        workplace_to_jobs.setdefault(workplace, []).append(job)
    for workplace, jobs in workplace_to_jobs.items():
        lines.append(f"- {workplace}: " + ", ".join(jobs))
    lines.append("")

    lines.append("## Hobby Items")
    lines.append("- " + ", ".join(sorted(HOBBY_ITEMS)))
    lines.append("")

    lines.append("## Education Locations")
    lines.append("- " + ", ".join(EDUCATION_LOCATIONS))
    lines.append("")

    lines.append("## Education Tuition")
    lines.append("- Base tuition: $2,000 per session")
    lines.append("- Master's degree: $4,000 per session")
    lines.append("- PhD/Doctorate: $8,000 per session")
    lines.append("- Student discount: Tuition capped at $150 if your job title contains 'student'")

    return "\n".join(lines)