import os

N_AGENTS = 6
MAX_NEW_TOKENS = 5000          
CONTEXT_SIZE   = 131072        

PASSIVE_TICK_SECONDS = 3600.0
RANDOM_SEED = 42

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR     = os.path.join(BASE_DIR, "logs")
CACHE_DIR   = os.path.join(BASE_DIR, "cache")   
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")
TOOLS_PATH  = os.path.join(BASE_DIR, "tools.json")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

STOCK_MU      = 0.0005   
STOCK_SIGMA   = 0.015    
IMPACT_FACTOR = 0.00005  

CHARS_PER_TOKEN    = 4         
CONTEXT_FILL_RATIO = 0.90      
SIM_HOURS_PER_YEAR = 8760      

MAX_RUNTIME_MINUTES = float(os.environ.get("MAX_RUNTIME_MINUTES", 1440.0))

MAX_INVENTORY = 20
TAX_AMOUNT    = 50.0
LLAMA_CLI_PATH = os.environ.get("LLAMA_CLI_PATH", "llama-cli")
SUMMARIZER_MODEL_PATH = os.environ.get("SUMMARIZER_MODEL_PATH", r"C:\Users\abhik\Downloads\Huihui-Qwen3.5-0.8B-abliterated.Q4_K_M.gguf")

# EDIT THIS TO CHANGE HOW THE SUMMARIZER "THINKS" AND "REMEMBERS"
SUMMARIZER_PROMPT_TEMPLATE = """System: Compress the following logs into a dense, third-person summary. Focus and keep only major plot points, relationship changes, long-term goals, and financial/health impacts.
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