SERVER_URL = "http://localhost:8080/completion"  
N_AGENTS = 6  
CTX_SIZE = 262144  
MAX_NEW_TOKENS = 150  
PASSIVE_TICK_SECONDS = 15.0  
  
import os  
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  
  
LOG_DIR = os.path.join(BASE_DIR, "logs")  
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")  
TOOLS_PATH = os.path.join(BASE_DIR, "tools.json")  
