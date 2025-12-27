"""
Queue management operations.
"""

from datetime import datetime
from typing import Optional


class QueueRepository:
    """Repository for fight queue management."""

    def __init__(self, connect_fn):
        self._connect = connect_fn

    def add_to_queue(self, fight_ids: list[int], source: str, priority: int = 0) -> int:
        """
        Add fight IDs to the download queue, skipping already-downloaded fights.
        Returns number of fights actually added.
        """
        if not fight_ids:
            return 0

        with self._connect() as conn:
            # Batch-check which fights already exist in DB
            placeholders = ",".join("?" * len(fight_ids))
            cursor = conn.execute(
                f"SELECT fight_id FROM fights WHERE fight_id IN ({placeholders})",
                fight_ids,
            )
            already_downloaded = set(row[0] for row in cursor)

            # Also check which are already in queue
            cursor = conn.execute(
                f"SELECT fight_id FROM fight_queue WHERE fight_id IN ({placeholders})",
                fight_ids,
            )
            already_queued = set(row[0] for row in cursor)

            # Filter to only new fights
            new_fights = [
                fid for fid in fight_ids
                if fid not in already_downloaded and fid not in already_queued
            ]

            if not new_fights:
                return 0

            now = datetime.now().isoformat()
            conn.executemany(
                """INSERT INTO fight_queue (fight_id, source, priority, added_at)
                   VALUES (?, ?, ?, ?)""",
                [(fid, source, priority, now) for fid in new_fights],
            )
            return len(new_fights)

    def peek_from_queue(self) -> Optional[int]:
        """Get the next fight ID from queue without removing it."""
        with self._connect() as conn:
            cursor = conn.execute(
                """SELECT fight_id FROM fight_queue
                   WHERE fight_id NOT IN (SELECT fight_id FROM fights)
                   ORDER BY priority DESC, added_at ASC
                   LIMIT 1"""
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def remove_from_queue(self, fight_id: int):
        """Remove a fight from the queue (call after successful download)."""
        with self._connect() as conn:
            conn.execute("DELETE FROM fight_queue WHERE fight_id = ?", (fight_id,))

    def delay_in_queue(self, fight_id: int):
        """Move a fight to the back of the queue (for pending fights)."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE fight_queue SET added_at = datetime('now'), priority = -1 WHERE fight_id = ?",
                (fight_id,)
            )

    def pop_from_queue(self) -> Optional[int]:
        """Get and remove the next fight ID from the queue (legacy - prefer peek/remove)."""
        fight_id = self.peek_from_queue()
        if fight_id:
            self.remove_from_queue(fight_id)
        return fight_id

    def queue_size(self) -> int:
        """Get number of fights in queue (excluding already downloaded)."""
        with self._connect() as conn:
            cursor = conn.execute(
                """SELECT COUNT(*) FROM fight_queue
                   WHERE fight_id NOT IN (SELECT fight_id FROM fights)"""
            )
            return cursor.fetchone()[0]

    def cleanup_queue(self) -> dict:
        """Remove stale entries from queues. Returns dict with cleanup counts."""
        with self._connect() as conn:
            # Clean fight queue: remove fights already downloaded
            cursor = conn.execute("""
                DELETE FROM fight_queue
                WHERE fight_id IN (SELECT fight_id FROM fights)
            """)
            fights_removed = cursor.rowcount

            # Clean discovery queue: remove leeks already scraped
            cursor = conn.execute("""
                DELETE FROM leek_discovery_queue
                WHERE leek_id IN (
                    SELECT player_id FROM scraped_players
                    WHERE player_type = 'leek'
                )
            """)
            discovery_removed = cursor.rowcount

            return {
                "fight_queue_cleaned": fights_removed,
                "discovery_queue_cleaned": discovery_removed,
            }
