"""
SQLite database for storing scraped fight data.

This module is split into focused repositories:
- base.py: Connection handling
- schema.py: Schema definitions and migrations
- models.py: Data classes
- fights.py: Fight storage and retrieval
- queue.py: Queue management
- players.py: Player tracking
- leeks.py: Leek observations and discovery
- analytics.py: Statistics and analytics
- tournaments.py: Tournament exploration
- metadata.py: Metadata extraction
"""

from pathlib import Path
from typing import Optional, Iterator

from .base import DatabaseConnection, DEFAULT_DB_PATH, DATA_FRESHNESS_CUTOFF
from .schema import init_schema, run_migrations
from .models import FightRecord
from .fights import FightRepository
from .queue import QueueRepository
from .players import PlayerRepository
from .leeks import LeekRepository
from .analytics import AnalyticsRepository
from .tournaments import TournamentRepository
from .metadata import MetadataRepository


class FightDatabase(DatabaseConnection):
    """SQLite database for fight storage.

    This class provides the same interface as the original monolithic class
    but delegates to focused repository classes internally.
    """

    def __init__(self, db_path: Optional[Path] = None):
        super().__init__(db_path)
        self._init_db()

        # Initialize repositories with connection function
        self._fights = FightRepository(self._connect)
        self._queue = QueueRepository(self._connect)
        self._players = PlayerRepository(self._connect)
        self._analytics = AnalyticsRepository(self._connect, self.db_path)
        self._tournaments = TournamentRepository(self._connect)
        self._metadata = MetadataRepository(self._connect)

        # Leeks needs references to analytics methods for priority calculation
        self._leeks = LeekRepository(
            self._connect,
            get_level_bracket_counts_fn=self._analytics.get_level_bracket_counts,
            get_level_301_ratio_fn=self._analytics.get_level_301_ratio
        )

    def _init_db(self):
        """Initialize database schema."""
        with self._connect() as conn:
            init_schema(conn)
            run_migrations(conn)

    # ==================== Fight Operations ====================

    def has_fight(self, fight_id: int) -> bool:
        return self._fights.has_fight(fight_id)

    def save_fight(self, fight_id: int, data: dict) -> bool:
        return self._fights.save_fight(fight_id, data)

    def get_fight(self, fight_id: int) -> Optional[FightRecord]:
        return self._fights.get_fight(fight_id)

    def iter_fights(
        self,
        fight_type: Optional[int] = None,
        context: Optional[int] = None,
        min_levels: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> Iterator[FightRecord]:
        return self._fights.iter_fights(fight_type, context, min_levels, limit)

    # ==================== Queue Operations ====================

    def add_to_queue(self, fight_ids: list[int], source: str, priority: int = 0) -> int:
        return self._queue.add_to_queue(fight_ids, source, priority)

    def peek_from_queue(self) -> Optional[int]:
        return self._queue.peek_from_queue()

    def remove_from_queue(self, fight_id: int):
        return self._queue.remove_from_queue(fight_id)

    def delay_in_queue(self, fight_id: int):
        return self._queue.delay_in_queue(fight_id)

    def pop_from_queue(self) -> Optional[int]:
        return self._queue.pop_from_queue()

    def queue_size(self) -> int:
        return self._queue.queue_size()

    def cleanup_queue(self) -> dict:
        return self._queue.cleanup_queue()

    # ==================== Player Operations ====================

    def mark_player_scraped(self, player_type: str, player_id: int, talent: int = 0):
        return self._players.mark_player_scraped(player_type, player_id, talent)

    def is_player_scraped(self, player_type: str, player_id: int) -> bool:
        return self._players.is_player_scraped(player_type, player_id)

    def set_state(self, key: str, value: str):
        return self._players.set_state(key, value)

    def get_state(self, key: str, default: str = "") -> str:
        return self._players.get_state(key, default)

    # ==================== Leek Operations ====================

    def extract_and_save_leek_observations(self, fight_id: int, fight_data: dict) -> list[int]:
        return self._leeks.extract_and_save_leek_observations(fight_id, fight_data)

    def add_to_discovery_queue(
        self,
        leek_id: int,
        farmer_id: int,
        level: int,
        priority_score: float,
        discovered_in_fight: int
    ):
        return self._leeks.add_to_discovery_queue(leek_id, farmer_id, level, priority_score, discovered_in_fight)

    def peek_from_discovery_queue(self) -> Optional[tuple[int, int, int]]:
        return self._leeks.peek_from_discovery_queue()

    def remove_from_discovery_queue(self, leek_id: int):
        return self._leeks.remove_from_discovery_queue(leek_id)

    def pop_from_discovery_queue(self) -> Optional[tuple[int, int, int]]:
        return self._leeks.pop_from_discovery_queue()

    def get_leek_stats(self, leek_id: int) -> Optional[dict]:
        return self._leeks.get_leek_stats(leek_id)

    def get_level_stats(self, level: int) -> Optional[dict]:
        return self._leeks.get_level_stats(level)

    def update_level_stats(self):
        return self._leeks.update_level_stats()

    def calculate_priority_score(self, level: int, total_stats: int, win_rate: float) -> float:
        return self._leeks.calculate_priority_score(level, total_stats, win_rate)

    # ==================== Analytics Operations ====================

    def get_stats(self) -> dict:
        return self._analytics.get_stats()

    def get_level_distribution(self, fight_type: Optional[int] = None) -> list[dict]:
        return self._analytics.get_level_distribution(fight_type)

    def get_stats_by_level(self, level: int, fight_type: Optional[int] = None) -> dict:
        return self._analytics.get_stats_by_level(level, fight_type)

    def get_popular_builds(self, level: int, fight_type: Optional[int] = None, limit: int = 5) -> list[dict]:
        return self._analytics.get_popular_builds(level, fight_type, limit)

    def get_fight_type_distribution(self) -> dict:
        return self._analytics.get_fight_type_distribution()

    def get_context_distribution(self) -> dict:
        return self._analytics.get_context_distribution()

    def get_level_301_ratio(self) -> float:
        return self._analytics.get_level_301_ratio()

    def get_level_bracket_counts(self) -> dict:
        return self._analytics.get_level_bracket_counts()

    def get_fight_date_distribution(self, bucket: str = "month") -> list[dict]:
        return self._analytics.get_fight_date_distribution(bucket)

    def get_fight_date_range(self) -> dict:
        return self._analytics.get_fight_date_range()

    def get_data_freshness_stats(self) -> dict:
        return self._analytics.get_data_freshness_stats()

    # ==================== Tournament Operations ====================

    def is_tournament_explored(self, tournament_id: int) -> bool:
        return self._tournaments.is_tournament_explored(tournament_id)

    def mark_tournament_explored(
        self,
        tournament_id: int,
        tournament_type: str,
        tournament_date: int,
        leeks_found: int,
        low_level_leeks: int
    ):
        return self._tournaments.mark_tournament_explored(
            tournament_id, tournament_type, tournament_date, leeks_found, low_level_leeks
        )

    def get_tournament_exploration_stats(self) -> dict:
        return self._tournaments.get_tournament_exploration_stats()

    def get_last_explored_tournament_id(self) -> Optional[int]:
        return self._tournaments.get_last_explored_tournament_id()

    # ==================== Metadata Operations ====================

    def save_fight_metadata(self, metadata_list: list[dict]) -> int:
        return self._metadata.save_fight_metadata(metadata_list)

    def get_metadata_extraction_progress(self) -> dict:
        return self._metadata.get_metadata_extraction_progress()

    def set_metadata_extraction_state(self, key: str, value: str):
        return self._metadata.set_metadata_extraction_state(key, value)

    def get_fights_needing_metadata(self, batch_size: int = 100) -> list[tuple[int, dict]]:
        return self._metadata.get_fights_needing_metadata(batch_size)

    def get_equipment_usage_by_level(
        self,
        fight_type: Optional[int] = None,
        min_sample_size: int = 10,
    ) -> dict[str, dict]:
        return self._metadata.get_equipment_usage_by_level(fight_type, min_sample_size)

    def get_metadata_stats(self) -> dict:
        return self._metadata.get_metadata_stats()

    def get_equipment_cooccurrence(
        self,
        level_bucket: Optional[str] = None,
        fight_type: Optional[int] = None,
        min_cooccurrence: int = 10,
    ) -> dict:
        return self._metadata.get_equipment_cooccurrence(level_bucket, fight_type, min_cooccurrence)


# Backwards compatibility exports
__all__ = ['FightDatabase', 'FightRecord', 'DEFAULT_DB_PATH', 'DATA_FRESHNESS_CUTOFF']
