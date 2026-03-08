from dataclasses import dataclass, field
from typing import Dict, List
from datetime import datetime

@dataclass
class AgentState:
    id: int
    name: str
    age: int
    health: float = 100.0
    happiness: float = 50.0
    stress: float = 20.0
    hunger: float = 30.0
    education: float = 50.0
    relationships: int = 2
    relationships_status: str = "single"  # single, dating, married, etc.
    beliefs: str = "Neutral"
    money: float = 500.0
    max_income: float = 3000.0
    job: str = "None"
    location: str = "Home"
    x: float = 0.0
    y: float = 0.0
    alive: bool = True
    failed_calls: int = 0
    last_action_time: float = 0.0
    owned_locations: List[str] = field(default_factory=list)  # Houses/property owned
    current_home: str = ""  # Primary home location

class WorldState:
    def __init__(self):
        self.agents: Dict[int, AgentState] = {}
        self.sim_time: float = 0.0  # simulated seconds since start
        self.market_price: float = 100.0
        self.last_passive: float = 0.0