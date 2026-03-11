"""
AgentAZAll Support Agent — Configuration
"""
from pathlib import Path

# Identity
AGENT_NAME = "support"
AGENT_ADDRESS = "support.e0be91da70a94073.agenttalk"

# Paths
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "support.db"
BULLETINS_DIR = BASE_DIR / "bulletins"
LOGS_DIR = BASE_DIR / "logs"

# LLM Server (own llama-server, OpenAI-compatible endpoint)
LLM_HOST = "127.0.0.1"
LLM_PORT = 8185  # own llama-server on GPU 2
LLM_URL = f"http://{LLM_HOST}:{LLM_PORT}/v1/chat/completions"
LLM_MODEL = "Qwen3.5-9B-abliterated-Q4_K_M"
LLM_MAX_TOKENS = 2048
LLM_TEMPERATURE = 0.7

# Rate Limits
RATE_LIMIT_PER_HOUR = 5
RATE_LIMIT_PER_DAY = 20
INPUT_MAX_TOKENS = 1024  # max input from agent (approximate via chars/4)
INPUT_MAX_CHARS = INPUT_MAX_TOKENS * 4

# Welcome Flow
WELCOME_MAX_EXCHANGES = 3  # after this, graceful sign-off

# Bulletin Cache
BULLETIN_CACHE_SECONDS = 3600  # 1 hour

# Naughty List Thresholds
NAUGHTY_WARN_SCORE = 25
NAUGHTY_BLOCK_24H_SCORE = 50
NAUGHTY_PERMANENT_SCORE = 200

# Daemon
POLL_INTERVAL_SECONDS = 10  # check inbox every 10s

# --- Knowledge / Teacher System ---
# Agents authorized to teach (TEACH: prefix bypasses rate limits and gates)
TEACHER_ADDRESSES = [
    "keel@localhost",                                  # local admin
    "testagent99.6f86908aad2a7ba1.agenttalk",         # test agent
]
# Max knowledge entries injected per support query
KNOWLEDGE_MAX_CONTEXT_ENTRIES = 5
# Max chars of knowledge context injected (stay within 8192 ctx window)
KNOWLEDGE_MAX_CONTEXT_CHARS = 3000
# Minimum keyword overlap to consider a knowledge entry relevant
KNOWLEDGE_MIN_RELEVANCE = 1
