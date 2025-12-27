"""
SQLite database for storing scraped fight data.

This module has been refactored into the db/ package.
This file provides backwards compatibility for existing imports.
"""

# Re-export everything from the new package
from .db import (
    FightDatabase,
    FightRecord,
    DEFAULT_DB_PATH,
    DATA_FRESHNESS_CUTOFF,
)

__all__ = ['FightDatabase', 'FightRecord', 'DEFAULT_DB_PATH', 'DATA_FRESHNESS_CUTOFF']
