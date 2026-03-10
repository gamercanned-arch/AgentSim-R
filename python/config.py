import os

SERVER_URL = "http://localhost:8080/completion"
_SERVER_BASE = SERVER_URL.rsplit("/", 1)[0]
TOKENIZE_URL = _SERVER_BASE + "/tokenize"

N_AGENTS = 6
MAX_NEW_TOKENS = 150
PASSIVE_TICK_SECONDS = 3600.0
RANDOM_SEED = 42
BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR     = os.path.join(BASE_DIR, "logs")
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")
TOOLS_PATH  = os.path.join(BASE_DIR, "tools.json")
STOCK_MU      = 0.0005   # GBM drift
STOCK_SIGMA   = 0.015    # GBM volatility
IMPACT_FACTOR = 0.0002   # price impact per net share traded (linear multiplier)

CONTEXT_SIZE       = 262_144   # tokens — must match --ctx-size in llama-server
CHARS_PER_TOKEN    = 4         # fallback approximation when tokenizer unavailable
CONTEXT_FILL_RATIO = 0.90      # stop at 90% full to leave headroom

SIM_HOURS_PER_YEAR = 8760      # 365 × 24 — used for agent aging