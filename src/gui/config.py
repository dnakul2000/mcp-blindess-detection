"""GUI configuration settings."""

from __future__ import annotations

from pathlib import Path

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
PROMPTS_DIR = PROJECT_ROOT / "experiments" / "prompts"

# GUI paths
GUI_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = GUI_DIR / "templates"
STATIC_DIR = GUI_DIR / "static"

# Server settings
HOST = "127.0.0.1"
PORT = 8420

# Key storage
KEY_STORE_DIR = Path.home() / ".mcp-blindness"
KEY_STORE_PATH = KEY_STORE_DIR / "keys.json"
