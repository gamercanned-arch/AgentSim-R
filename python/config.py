import os
from dotenv import load_dotenv
load_dotenv(override=True)

N_AGENTS = 6
# With stated server support, set to 262144.
CONTEXT_SIZE = 220000
# Keeps generation bounded; tool calls should be short.
MAX_NEW_TOKENS = 16384
PASSIVE_TICK_SECONDS = 3600.0
RANDOM_SEED = 42
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")
TOOLS_PATH = os.path.join(BASE_DIR, "tools.json") # Relies on execute.py's try/except fallback
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# Market model
STOCK_MU = 0.002
STOCK_SIGMA = 0.05
MARKET_TICK_SECONDS = 300.0 
JUMP_PROB_PER_HOUR = 0.06
JUMP_SIGMA = 0.20
IMPACT_FACTOR = 0.00015
IMPACT_CLAMP_LO = 0.70
IMPACT_CLAMP_HI = 1.30

CHARS_PER_TOKEN = 4
CONTEXT_FILL_RATIO = 0.90
_raw_max_runtime = os.environ.get("MAX_RUNTIME_MINUTES", "").strip() or "600.0"
try:
    MAX_RUNTIME_MINUTES = float(_raw_max_runtime)
except ValueError:
    raise ValueError(f"MAX_RUNTIME_MINUTES must be numeric, got: '{_raw_max_runtime}'")

# Inventory + economy
MAX_INVENTORY = 20
TAX_EXEMPT_BELOW_CASH = 200.0


MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 30
MARKET_CLOSE_HOUR = 16
MARKET_CLOSE_MINUTE = 0


WORKPLACE_MAX_DISTANCE = 150.0
STATUS_MAX_DISTANCE = 30.0
GROUND_PICKUP_RADIUS = 20.0
AUTO_LOOT_RADIUS = 300.0
OBJECT_Z_TOLERANCE = 1.0
DROP_REPICKUP_COOLDOWN = 3600.0

BASE_STORE_INVENTORY = {
    "Snacks": 35 * N_AGENTS,
    "Water": 35 * N_AGENTS,
    "Coffee": 15 * N_AGENTS,
    "Sandwich": 15 * N_AGENTS,
    "Pizza": 8 * N_AGENTS,
    "Premium Meal": 5 * N_AGENTS,
    "Toothbrush": 3 * N_AGENTS,
    "Clothes": 3 * N_AGENTS,
    "Book": 3 * N_AGENTS,
    "Art Supplies": 2 * N_AGENTS,
    "Notebook": 5 * N_AGENTS,
    "Medicine": 8 * N_AGENTS,
    "Vitamins": 8 * N_AGENTS,
    "First aid kit": 3 * N_AGENTS
}
