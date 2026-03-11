import os

N_AGENTS = 6
MAX_NEW_TOKENS = 128000      # You can generate up to 128k tokens per turn
PASSIVE_TICK_SECONDS = 3600.0
RANDOM_SEED = 42
BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR     = os.path.join(BASE_DIR, "logs")
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")
TOOLS_PATH  = os.path.join(BASE_DIR, "tools.json")
STOCK_MU      = 0.0005   
STOCK_SIGMA   = 0.015    
IMPACT_FACTOR = 0.0002   

CONTEXT_SIZE       = 262144    # Full 262k context window
CHARS_PER_TOKEN    = 4         
CONTEXT_FILL_RATIO = 0.90      

SIM_HOURS_PER_YEAR = 8760      