"""
Base database connection handling.
"""

import sqlite3
from pathlib import Path
from typing import Optional

from src.common.config import get_paths


# Default database location (uses centralized config)
DEFAULT_DB_PATH = get_paths().database_path

# Data freshness cutoff: Feb 20, 2024 - important gameplay change (item restrictions)
DATA_FRESHNESS_CUTOFF = 1708387200  # 2024-02-20 00:00:00 UTC


class DatabaseConnection:
    """Base class for database connection handling."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        """Create a connection with proper settings for concurrent access."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout=30000;")  # 30 second timeout
        return conn
