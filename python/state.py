import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from python.locations import get_home_lots_inventory


@dataclass
class AgentState:
    id: int
    name: str
    age: int

    health: float = 100.0
    energy: float = 100.0
    hydration: float = 70.0
    happiness: float = 50.0
    stress: float = 20.0
    hunger: float = 30.0
    education: float = 50.0

    relationships: float = 2.0
    relationships_status: str = "single"
    relationship_partner: str = ""
    beliefs: str = "Neutral"

    money: float = 500.0
    hourly_wage: float = 20.0
    job: str = "None"
    expenses: float = 0.0
    total_expenses: float = 0.0
    shares_owned: int = 0
    last_known_price: float = 0.0

    location: str = "Outside"
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    starvation_hours: int = 0
    dehydration_hours: int = 0
    awake_hours: int = 0
    hours_lived: int = 0
    caffeine_level: int = 0
    social_fulfillment: float = 50.0
    fail_counter: int = 0
    failed_calls: int = 0
    total_prompt_tokens: int = 0

    alive: bool = True
    busy_until: float = 0.0
    is_sleeping: bool = False
    current_activity: str = "idle"

    owned_locations: List[str] = field(default_factory=list)
    current_home_type: str = ""
    home_location: str = ""
    inventory: List[Dict[str, Any]] = field(default_factory=list)
    currently_holding: Optional[Dict[str, Any]] = None

    pending_notifications: List[str] = field(default_factory=list)
    pending_status_requests: Dict[str, str] = field(default_factory=dict)
    pending_market_orders: List[Dict[str, Any]] = field(default_factory=list)

    task_state: str = "idle"
    pending_task_data: Dict[str, Any] = field(default_factory=dict)

    active_task_entities: Dict[str, Any] = field(default_factory=dict)
    recent_scenarios: Dict[str, List[str]] = field(default_factory=dict)

    vehicle_type: str = "Scooter"
    vehicle_x: float = 0.0
    vehicle_y: float = 0.0
    vehicle_z: float = 0.0

    voicemail_inbox: List[Dict[str, Any]] = field(default_factory=list)

    first_turn: bool = True
    social_cooldowns: Dict[str, float] = field(default_factory=dict)
    system_prompt: str = ""
    chat_history: List[Dict[str, str]] = field(default_factory=list)
    last_action_result: str = "None (First turn)"
    last_parse_error: bool = False


class WorldState:
    def __init__(self):
        self.agents: Dict[int, AgentState] = {}
        self.sim_time: float = 0.0
        self.market_price: float = 100.0
        self.last_passive: float = 0.0
        self.net_volume_this_period: int = 0
        self.price_history: List[float] = [100.0]
        self.weather: str = "Sunny"
        self.global_news: List[str] = []
        self.store_inventory: Dict[str, int] = {}
        self.last_restock_time: float = 0.0
        self.last_market_tick: float = 0.0
        self.vacant_home_lots: Dict[str, List[str]] = get_home_lots_inventory()
        self.ground_items: List[Dict[str, Any]] = []
        self.corpse_estates: List[Dict[str, Any]] = []
        self.pending_deliveries: List[Dict[str, Any]] = []

    def allocate_home_lot(self, home_type: str, prefer_floor1: bool = False) -> Optional[str]:
        available = self.vacant_home_lots.get(home_type, [])
        if not available:
            return None

        if prefer_floor1:
            floor1_candidates = [
                name for name in available
                if ("_Floor_1" in name) or ("_Floor_" not in name)
            ]
            if floor1_candidates:
                choice = random.choice(floor1_candidates)
                available.remove(choice)
                return choice

        choice = random.choice(available)
        available.remove(choice)
        return choice

    def release_home_lot(self, home_type: str, home_location: str) -> None:
        if not home_type or not home_location:
            return
        bucket = self.vacant_home_lots.setdefault(home_type, [])
        if home_location not in bucket:
            bucket.append(home_location)
            bucket.sort()
