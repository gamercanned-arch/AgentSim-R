import os

N_AGENTS = 6
MAX_NEW_TOKENS = 5000
CONTEXT_SIZE = 131072

PASSIVE_TICK_SECONDS = 3600.0
RANDOM_SEED = 42

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")
TOOLS_PATH = os.path.join(BASE_DIR, "tools.json")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

STOCK_MU = 0.0005
STOCK_SIGMA = 0.015
IMPACT_FACTOR = 0.00005

CHARS_PER_TOKEN = 4
CONTEXT_FILL_RATIO = 0.90
SIM_HOURS_PER_YEAR = 8760

MAX_RUNTIME_MINUTES = float(os.environ.get("MAX_RUNTIME_MINUTES", 600.0))

MAX_INVENTORY = 20
TAX_AMOUNT = 50.0
LLAMA_CLI_PATH = os.environ.get("LLAMA_CLI_PATH", "llama-cli")
SUMMARIZER_MODEL_PATH = os.environ.get("SUMMARIZER_MODEL_PATH", "models/qwen3.5-0.8b.gguf")

MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 30
MARKET_CLOSE_HOUR = 16
MARKET_CLOSE_MINUTE = 0

SUMMARY_TRIGGER_CYCLES = 30
SUMMARY_COMPRESS_CYCLES = 20
SUMMARY_KEEP_CYCLES = 10

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

SUMMARIZER_PROMPT_TEMPLATE = """System: Compress the following logs into a dense, third-person summary. Focus only on major plot points, relationship changes, long-term goals, and financial/health impacts.
Example 1 Input:
[USER: Moved to Hospital. RESULT: Travelled to Hospital. USER: Used seek_medicalcare. RESULT: Health restored to 100, Money -$50.]
Example 1 Output:
Agent travelled to the hospital and spent $50 to fully restore their health.
Example 2 Input:
[USER: Talked to Alex "I hate you". RESULT: Alex stress increased. USER: Attacked Alex. RESULT: Dealt 15 damage. USER: Moved to Home. RESULT: Travelled Home.]
Example 2 Output:
Agent verbally insulted Alex, escalated to physical violence dealing 15 damage, and then fled back home.
Actual Input:
{text_chunk}
Actual Output:"""