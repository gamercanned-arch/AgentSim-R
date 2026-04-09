import os

N_AGENTS = 6
# With stated server support, set to 262144.
CONTEXT_SIZE = 262144
# Keeps generation bounded; tool calls should be short.
MAX_NEW_TOKENS = 2048
PASSIVE_TICK_SECONDS = 3600.0
RANDOM_SEED = 42
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")
TOOLS_PATH = os.path.join(BASE_DIR, "tools.json")
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
SIM_HOURS_PER_YEAR = 8760
# Safe casting with fallback for empty strings
MAX_RUNTIME_MINUTES = float(os.environ.get("MAX_RUNTIME_MINUTES", "").strip() or "600.0")

# Inventory + economy
MAX_INVENTORY = 20
TAX_EXEMPT_BELOW_CASH = 200.0
TAX_RATE = 0.05  

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

SUMMARIZER_PROMPT_TEMPLATE = """System: Compress and update the following logs into a dense, compact, third-person summary.

Inputs:
- Existing summary (may be empty):
{existing_summary}

- New turns to incorporate:
{text_chunk}

Instructions:
- Produce a single updated summary that merges prior context with new events.
- Be concise, factual, and information-dense.
- Focus only on:
  • Major actions and outcomes  
  • Relationship changes, interactions, and conflicts  
  • Long-term goals and progress  
  • Financial impacts (money gained/lost)  
  • Health, energy, hunger, hydration, stress, happiness changes  
  • Significant movement, work, or study results  
- Avoid minor or repetitive details.
- Maintain continuity from the existing summary.
- Use clear, natural language (no bullet points, no meta commentary).
- Keep it under 16,000 tokens (~10k words).

Return ONLY the updated summary text."""