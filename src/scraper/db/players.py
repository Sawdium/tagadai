"""
Player tracking operations.
"""

from datetime import datetime


class PlayerRepository:
    """Repository for player tracking."""

    def __init__(self, connect_fn):
        self._connect = connect_fn

    def mark_player_scraped(self, player_type: str, player_id: int, talent: int = 0):
        """Mark a player as having had their history scraped."""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO scraped_players
                   (player_type, player_id, talent, last_scraped)
                   VALUES (?, ?, ?, ?)""",
                (player_type, player_id, talent, datetime.now().isoformat()),
            )

    def is_player_scraped(self, player_type: str, player_id: int) -> bool:
        """Check if we've already scraped a player's history."""
        with self._connect() as conn:
            cursor = conn.execute(
                """SELECT 1 FROM scraped_players
                   WHERE player_type = ? AND player_id = ?""",
                (player_type, player_id),
            )
            return cursor.fetchone() is not None

    # State management
    def set_state(self, key: str, value: str):
        """Set a scraper state value."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scraper_state (key, value) VALUES (?, ?)",
                (key, value),
            )

    def get_state(self, key: str, default: str = "") -> str:
        """Get a scraper state value."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT value FROM scraper_state WHERE key = ?", (key,)
            )
            row = cursor.fetchone()
            return row[0] if row else default
