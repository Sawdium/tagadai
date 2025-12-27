"""
Common utilities for TagadAI.

This module provides shared functionality used across tools:
- LeekWarsAPI: Unified API client
- Credentials: Centralized credential management
- Paths: Project path configuration
- Errors: Custom exception types
- FightParser: Parse and format API fight results
"""

from .api import LeekWarsAPI
from .config import ProjectPaths, get_project_root
from .credentials import load_credentials
from .errors import (
    TagadAIError,
    APIError,
    AuthenticationError,
    FightError,
    ConfigError,
)
from .fight_parser import (
    FightSummary,
    parse_fight,
    format_summary,
    # Action constants
    ACTION_START_FIGHT,
    ACTION_USE_WEAPON,
    ACTION_USE_CHIP,
    ACTION_NEW_TURN,
    ACTION_LEEK_TURN,
    ACTION_END_TURN,
    ACTION_MOVE_TO,
    ACTION_SET_WEAPON,
    ACTION_TP_LOST,
    ACTION_LIFE_LOST,
    ACTION_MP_LOST,
    ACTION_LIFE_WIN,
    ACTION_DEATH,
    ACTION_SAY,
    ACTION_DEBUG,
    ACTION_DEBUG_W,
    ACTION_DEBUG_E,
    ERROR_DESCRIPTIONS,
)

__all__ = [
    # API
    "LeekWarsAPI",
    # Config
    "ProjectPaths",
    "get_project_root",
    # Credentials
    "load_credentials",
    # Errors
    "TagadAIError",
    "APIError",
    "AuthenticationError",
    "FightError",
    "ConfigError",
    # Fight parsing
    "FightSummary",
    "parse_fight",
    "format_summary",
    "ACTION_START_FIGHT",
    "ACTION_USE_WEAPON",
    "ACTION_USE_CHIP",
    "ACTION_NEW_TURN",
    "ACTION_LEEK_TURN",
    "ACTION_END_TURN",
    "ACTION_MOVE_TO",
    "ACTION_SET_WEAPON",
    "ACTION_TP_LOST",
    "ACTION_LIFE_LOST",
    "ACTION_MP_LOST",
    "ACTION_LIFE_WIN",
    "ACTION_DEATH",
    "ACTION_SAY",
    "ACTION_DEBUG",
    "ACTION_DEBUG_W",
    "ACTION_DEBUG_E",
    "ERROR_DESCRIPTIONS",
]
