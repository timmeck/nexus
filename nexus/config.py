"""Nexus configuration."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "nexus.db"
STATIC_DIR = BASE_DIR / "nexus" / "dashboard" / "static"

HOST = "0.0.0.0"
PORT = 9500

# Trust defaults
INITIAL_TRUST_SCORE = 0.5
TRUST_DECAY = 0.01
TRUST_REWARD = 0.05
TRUST_PENALTY = 0.10
MIN_TRUST = 0.0
MAX_TRUST = 1.0

# Heartbeat timeout (seconds)
HEARTBEAT_TIMEOUT = 60

# Router defaults
DEFAULT_STRATEGY = "best"  # best | cheapest | fastest

# Default request timeout (seconds)
DEFAULT_TIMEOUT = 30.0

# Per-capability timeout overrides (seconds)
# Capabilities not listed here use DEFAULT_TIMEOUT
timeout_overrides: dict[str, float] = {
    "deep_research": 120.0,
    "code_generation": 90.0,
    "embedding": 60.0,
}
