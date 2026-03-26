"""
MAX bot configuration.
Inherits all settings from the parent Telegram bot config
and adds MAX messenger-specific values.
"""
import os
import sys

# Allow importing parent project modules (database, utils_*, etc.)
_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from config import config as _parent_cfg  # noqa: E402 — must come after sys.path fix


# ── MAX-specific settings ──────────────────────────────────────────────────────
MAX_BOT_TOKEN: str = os.environ.get("MAX_BOT_TOKEN", "YOUR_MAX_BOT_TOKEN_HERE")

# Prefix used on callback payloads longer than 256 chars (MAX limit)
MAX_CALLBACK_PAYLOAD_LIMIT: int = 256

# ── Re-export everything from the parent config ───────────────────────────────
# (costs, API keys, TOKEN_PACKAGES, ADMIN_IDS, …)
config = _parent_cfg
