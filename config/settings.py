import os
from pathlib import Path
from dotenv import load_dotenv, set_key

load_dotenv()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Claude API
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# Search defaults
MAX_RESULTS = 20
SUMMARY_LANGUAGE = "English"

# Cookie file for Twikit session persistence
COOKIES_FILE = "cookies.json"
ENV_FILE = ".env"

# Available Claude models shown during onboarding
MODEL_CHOICES = {
    "haiku":  ("claude-haiku-4-5-20251001", "Haiku — fastest & cheapest"),
    "sonnet": ("claude-sonnet-4-6",          "Sonnet — best balance (recommended)"),
    "opus":   ("claude-opus-4-6",            "Opus — most powerful"),
}


def is_configured() -> bool:
    """True when Claude API key and X cookies are both present."""
    return bool(CLAUDE_API_KEY) and Path(COOKIES_FILE).exists()


def save_config(claude_api_key: str, model_id: str) -> None:
    """Persist Claude settings to .env and update in-memory values."""
    global CLAUDE_API_KEY, CLAUDE_MODEL
    set_key(ENV_FILE, "CLAUDE_API_KEY", claude_api_key)
    set_key(ENV_FILE, "CLAUDE_MODEL", model_id)
    CLAUDE_API_KEY = claude_api_key
    CLAUDE_MODEL = model_id
