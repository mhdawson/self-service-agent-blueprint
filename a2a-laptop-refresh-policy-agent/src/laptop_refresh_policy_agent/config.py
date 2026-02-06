"""Configuration for the Laptop Refresh Policy Agent."""

import os
from pathlib import Path

# Server configuration
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8001"))

# Logging configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Policy configuration
REFRESH_INTERVAL_YEARS = int(os.getenv("REFRESH_INTERVAL_YEARS", "10"))

# Agent card path
AGENT_CARD_PATH = Path(__file__).parent / "agent_card.json"
