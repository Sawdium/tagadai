"""
Tournament exploration tracking.
"""

from datetime import datetime
from typing import Optional


class TournamentRepository:
    """Repository for tournament exploration tracking."""

    def __init__(self, connect_fn):
        self._connect = connect_fn

    def is_tournament_explored(self, tournament_id: int) -> bool:
        """Check if a tournament has been explored."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM tournament_exploration WHERE tournament_id = ?",
                (tournament_id,)
            )
            return cursor.fetchone() is not None

    def mark_tournament_explored(
        self,
        tournament_id: int,
        tournament_type: str,
        tournament_date: int,
        leeks_found: int,
        low_level_leeks: int
    ):
        """Mark a tournament as explored."""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO tournament_exploration
                   (tournament_id, tournament_type, tournament_date, leeks_found,
                    low_level_leeks, explored_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (tournament_id, tournament_type, tournament_date, leeks_found,
                 low_level_leeks, datetime.now().isoformat())
            )

    def get_tournament_exploration_stats(self) -> dict:
        """Get tournament exploration statistics."""
        with self._connect() as conn:
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total_explored,
                    MIN(tournament_date) as oldest_date,
                    MAX(tournament_date) as newest_date,
                    SUM(leeks_found) as total_leeks,
                    SUM(low_level_leeks) as total_low_level
                FROM tournament_exploration
            """)
            row = cursor.fetchone()
            return {
                "tournaments_explored": row[0] or 0,
                "oldest_date": row[1],
                "newest_date": row[2],
                "leeks_from_tournaments": row[3] or 0,
                "low_level_from_tournaments": row[4] or 0,
            }

    def get_last_explored_tournament_id(self) -> Optional[int]:
        """Get the most recently explored tournament ID."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT MAX(tournament_id) FROM tournament_exploration"
            )
            row = cursor.fetchone()
            return row[0] if row and row[0] else None
