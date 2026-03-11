from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class AgentState:
    id: int
    name: str
    age: int
    # core stats (clamped 0–100 at all update sites)
    health:    float = 100.0
    energy:    float = 100.0
    happiness: float =  50.0
    stress:    float =  20.0
    hunger:    float =  30.0
    education: float =  50.0
    # social
    relationships:        int = 2
    relationships_status: str = "single"
    beliefs:              str = "Neutral"
    # economy
    money:         float = 500.0
    hourly_wage:   float =  20.0   # Current earning rate per hour
    job:           str   = "None"
    expenses:      float =   0.0   # rolling spend, decays 5%/hr
    total_expenses: float =  0.0   # lifetime spend tracker
    # stock portfolio
    shares_owned:     int   = 0
    last_known_price: float = 0.0   # weighted-average cost basis (0 when no position)
    # world position
    location: str   = "Home"
    x:        float =   0.0
    y:        float =   0.0
    # lifecycle
    alive:            bool  = True
    failed_calls:     int   = 0
    last_action_time: float = 0.0
    busy_until:       float = 0.0   # Event-driven schedule tracker
    hours_lived:      int   = 0     # passive ticks survived — drives aging
    # property
    owned_locations: List[str] = field(default_factory=list)
    current_home:    str       = ""
    inventory:       Dict[str, int] = field(default_factory=dict)
    last_3_actions:  List[str]      = field(default_factory=list)
    pending_notifications: List[str] = field(default_factory=list)
    pending_status_requests: Dict[str, str] = field(default_factory=dict)
    first_turn: bool = True
    total_prompt_tokens: int = 0
    social_cooldowns: Dict[str, float] = field(default_factory=dict)
    
    # Context & Memory trackers
    system_prompt: str = ""
    chat_history: List[Dict[str, str]] = field(default_factory=list)
    last_action_result: str = "None (First turn)"


class WorldState:
    def __init__(self):
        self.agents:       Dict[int, AgentState] = {}
        self.sim_time:     float = 0.0
        self.market_price: float = 100.0
        self.last_passive: float = 0.0
        self.net_volume_this_period: int = 0
        self.price_history: List[float] = [100.0]