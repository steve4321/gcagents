"""Centralized constants for GCAgents — replaces scattered magic numbers."""

# ── Scheduler ──────────────────────────────────────────────────────────────
QA_CANCEL_THRESHOLD = 3          # consecutive QA failures before cancel decision
MAX_INSTRUCTIONS_PER_TICK = 5    # instructions processed per scheduler tick
LAYER1_MAX_RETRIES = 2           # Layer 1 retry attempts before escalation
LLM_MAX_RETRIES = 3             # LLM call retry attempts
LLM_BACKOFF_MAX_SECONDS = 30    # max exponential backoff delay
LLM_DEFAULT_MAX_TOKENS = 4096   # default max_tokens for LLM calls
LLM_DEFAULT_TEMPERATURE = 0.7   # default temperature for LLM calls

# ── Field Truncation Lengths ──────────────────────────────────────────────
TRUNC_ERROR = 500               # error message max length
TRUNC_FEEDBACK_TEXT = 5000       # feedback text max length
TRUNC_RAW_ANALYSIS = 50000       # raw analysis max length
TRUNC_CHANGELOG = 2000           # changelog max length
TRUNC_AI_ANALYSIS = 2000         # AI analysis max length
TRUNC_LLM_PROMPT_ERROR = 2000   # build error in LLM prompt max length
TRUNC_FEEDBACK_PROMPT = 1000     # feedback text in LLM prompt

# ── Market Scan Limits ────────────────────────────────────────────────────
MAX_SIGNALS_PER_BATCH = 20       # market signals per batch insert
MAX_FEED_ENTRIES = 20            # RSS/API entries per source
MAX_TREND_RESULTS = 30           # X/Twitter trend results
MAX_YOUTUBE_SEARCH = 10          # YouTube search result cap

# ── Fetcher Throttling (seconds) ─────────────────────────────────────────
REDDIT_REQUEST_INTERVAL = 2.0    # seconds between Reddit requests
APPSTORE_REQUEST_INTERVAL = 4.0  # seconds between App Store requests

# ── Source Score Defaults ─────────────────────────────────────────────────
DEFAULT_SOURCE_SCORE = 0.5       # fallback score when no data available
LOW_CONFIDENCE_SCORE = 0.2       # score when minimal data available

# ── Build ─────────────────────────────────────────────────────────────────
NPM_INSTALL_TIMEOUT = 120        # seconds for npm install
NPM_BUILD_TIMEOUT = 120          # seconds for npm build
