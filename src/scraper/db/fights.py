"""
Fight storage and retrieval operations.
"""

import json
import sqlite3
from datetime import datetime
from typing import Optional, Iterator

from .models import FightRecord


class FightRepository:
    """Repository for fight storage and retrieval."""

    def __init__(self, connect_fn):
        self._connect = connect_fn

    def has_fight(self, fight_id: int) -> bool:
        """Check if a fight is already in the database."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM fights WHERE fight_id = ?", (fight_id,)
            )
            return cursor.fetchone() is not None

    def save_fight(self, fight_id: int, data: dict) -> bool:
        """Save a fight to the database. Returns True if saved, False if already exists."""
        if self.has_fight(fight_id):
            return False

        # Extract metadata for filtering
        winner = data.get("winner", -1)
        fight_type = data.get("type", -1)
        context = data.get("context", -1)
        fight_date = data.get("date")

        # Calculate total levels
        team1_levels = sum(l.get("level", 0) for l in data.get("leeks1", []))
        team2_levels = sum(l.get("level", 0) for l in data.get("leeks2", []))

        # Count turns (find max NEW_TURN action)
        duration = 0
        fight_data = data.get("data", {})
        for action in fight_data.get("actions", []):
            if isinstance(action, list) and len(action) >= 2 and action[0] == 6:
                duration = max(duration, action[1])

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO fights
                   (fight_id, json_data, winner, fight_type, context,
                    team1_levels, team2_levels, duration, fight_date, downloaded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fight_id,
                    json.dumps(data),
                    winner,
                    fight_type,
                    context,
                    team1_levels,
                    team2_levels,
                    duration,
                    fight_date,
                    datetime.now().isoformat(),
                ),
            )
        return True

    def get_fight(self, fight_id: int) -> Optional[FightRecord]:
        """Get a specific fight by ID."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM fights WHERE fight_id = ?", (fight_id,)
            )
            row = cursor.fetchone()
            if row:
                return FightRecord(
                    fight_id=row["fight_id"],
                    json_data=json.loads(row["json_data"]),
                    winner=row["winner"],
                    fight_type=row["fight_type"],
                    context=row["context"],
                    team1_levels=row["team1_levels"],
                    team2_levels=row["team2_levels"],
                    duration=row["duration"],
                    fight_date=row["fight_date"] if "fight_date" in row.keys() else None,
                    downloaded_at=row["downloaded_at"],
                )
            return None

    def iter_fights(
        self,
        fight_type: Optional[int] = None,
        context: Optional[int] = None,
        min_levels: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> Iterator[FightRecord]:
        """Iterate over fights with optional filtering."""
        query = "SELECT * FROM fights WHERE 1=1"
        params = []

        if fight_type is not None:
            query += " AND fight_type = ?"
            params.append(fight_type)
        if context is not None:
            query += " AND context = ?"
            params.append(context)
        if min_levels is not None:
            query += " AND (team1_levels + team2_levels) >= ?"
            params.append(min_levels)

        query += " ORDER BY fight_id DESC"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            for row in cursor:
                yield FightRecord(
                    fight_id=row["fight_id"],
                    json_data=json.loads(row["json_data"]),
                    winner=row["winner"],
                    fight_type=row["fight_type"],
                    context=row["context"],
                    team1_levels=row["team1_levels"],
                    team2_levels=row["team2_levels"],
                    duration=row["duration"],
                    fight_date=row["fight_date"] if "fight_date" in row.keys() else None,
                    downloaded_at=row["downloaded_at"],
                )
