"""
Scraper status and statistics models.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ScraperStatus(Enum):
    """Scraper status."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class ScraperStats:
    """Real-time scraper statistics."""
    status: ScraperStatus = ScraperStatus.IDLE
    fights_downloaded: int = 0
    fights_skipped: int = 0  # Already in DB
    fights_failed: int = 0
    players_discovered: int = 0
    queue_size: int = 0
    total_in_db: int = 0
    db_size_mb: float = 0.0
    current_action: str = "Idle"
    current_strategy: str = "unknown"  # "low_level_winners" or "top_players"
    level_301_ratio: float = 0.0
    last_fight_id: Optional[int] = None
    last_error: Optional[str] = None
    started_at: Optional[str] = None
    requests_made: int = 0
    avg_request_time: float = 0.0
    rate_limit_hits: int = 0
    rate_limited_until: Optional[float] = None  # Unix timestamp
