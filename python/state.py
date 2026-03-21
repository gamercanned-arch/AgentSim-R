from dataclasses import dataclass, field
from typing import Dict, List, Any

@dataclass
class AgentState:
    id: int
    name: str
    age: int
    health:    float = 100.0
    energy:    float = 100.0
    happiness: float =  50.0
    stress:    float =  20.0
    hunger:    float =  30.0
    education: float =  50.0
    relationships:        int = 2
    relationships_status: str = "single"
    beliefs:              str = "Neutral"
    money:         float = 500.0
    hourly_wage:   float =  20.0   
    job:           str   = "None"
    expenses:      float =   0.0   
    total_expenses: float =  0.0   
    shares_owned:     int   = 0
    last_known_price: float = 0.0   
    
    location: str   = "Home"
    x:        float =   0.0
    y:        float =   0.0
    z:        float =   0.0

    starvation_hours: int = 0
    awake_hours:      int = 0
    caffeine_level:   int = 0
    social_fulfillment: float = 50.0
    fail_counter:     int = 0
    
    alive:            bool  = True
    failed_calls:     int   = 0
    busy_until:       float = 0.0   
    hours_lived:      int   = 0     
    owned_locations: List[str] = field(default_factory=list)
    current_home:    str       = ""
    
    inventory:       List[Dict[str, Any]] = field(default_factory=list)
    currently_holding: Dict[str, Any]     = None
    
    pending_notifications: List[str] = field(default_factory=list)
    pending_status_requests: Dict[str, str] = field(default_factory=dict)
    pending_market_orders: List[Dict[str, Any]] = field(default_factory=list)
    
    task_state: str = "idle" 
    pending_task_data: Dict[str, Any] = field(default_factory=dict)

    # Background Summarizer Thread Locks
    pending_summary: str = None
    is_summarizing: bool = False

    first_turn: bool = True
    total_prompt_tokens: int = 0
    social_cooldowns: Dict[str, float] = field(default_factory=dict)
    system_prompt: str = ""
    chat_history: List[Dict[str, str]] = field(default_factory=list)
    last_action_result: str = "None (First turn)"
    last_parse_error: bool = False

class WorldState:
    def __init__(self):
        self.agents:       Dict[int, AgentState] = {}
        self.sim_time:     float = 0.0 
        self.market_price: float = 100.0
        self.last_passive: float = 0.0
        self.net_volume_this_period: int = 0
        self.price_history: List[float] = [100.0]
        self.weather: str = "Sunny"
        self.global_news: List[str] = []
        self.store_inventory: Dict[str, int] = {}
        self.last_restock_time: float = 0.0