"""
LeekWars fight scraper.

Politely downloads fight data from the LeekWars API.
"""

import time
import threading
from datetime import datetime
from typing import Optional
import logging

from .db import FightDatabase
from .stats import ScraperStatus, ScraperStats
from .client import LeekWarsClient
from .discovery import TournamentExplorer, PlayerDiscovery

logger = logging.getLogger(__name__)


class FightScraper:
    """
    LeekWars fight scraper with rate limiting and resumability.

    Features:
    - Polite rate limiting (configurable delay)
    - Automatic discovery of top players
    - Queue-based downloading with priorities
    - Resume capability (state saved in DB)
    - Background thread execution
    - Real-time statistics
    """

    # Fight types
    TYPE_SOLO = 0
    TYPE_FARMER = 1
    TYPE_TEAM = 2

    # Context types
    CONTEXT_TEST = 0
    CONTEXT_CHALLENGE = 1
    CONTEXT_GARDEN = 2
    CONTEXT_TOURNAMENT = 3

    # Strategy thresholds
    LOW_LEVEL_STRATEGY_THRESHOLD = 0.30

    # Fight type priority modifiers (solo boosted, farmer deprioritized)
    FIGHT_TYPE_PRIORITY = {
        TYPE_SOLO: 100,    # Boost solo fights
        TYPE_FARMER: -50,  # Deprioritize farmer fights
        TYPE_TEAM: 0,      # Team fights neutral
    }

    def __init__(
        self,
        db: Optional[FightDatabase] = None,
        delay: float = 1.0,
        fight_types: Optional[list[int]] = None,
        skip_test_fights: bool = True,
        min_duration: int = 0,
    ):
        """
        Initialize the scraper.

        Args:
            db: FightDatabase instance (creates default if None)
            delay: Seconds between API requests
            fight_types: List of fight types to download (None = all)
            skip_test_fights: Skip test fights (context=0), default True
            min_duration: Minimum fight duration in turns (skip short fights)
        """
        self.db = db or FightDatabase()
        self.delay = delay
        self.fight_types = fight_types
        self.skip_test_fights = skip_test_fights
        self.min_duration = min_duration

        # Threading
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused by default

        # Statistics
        self.stats = ScraperStats()

        # API client
        self._client = LeekWarsClient(
            delay=delay,
            stats=self.stats,
            stop_event=self._stop_event,
            pause_event=self._pause_event,
        )
        self._client.try_auto_login()

        # Discovery modules
        self._tournament_explorer = TournamentExplorer(
            self._client, self.db, self.stats
        )
        self._player_discovery = PlayerDiscovery(
            self._client, self.stats
        )

    @property
    def is_authenticated(self) -> bool:
        """Check if scraper is authenticated."""
        return self._client.is_authenticated

    def login(self, login: str, password: str) -> dict:
        """Authenticate with LeekWars API."""
        return self._client.login(login, password)

    def discover_top_players(self, count: int = 50) -> list[tuple[str, int, int]]:
        """Discover top players from the ranking."""
        return self._player_discovery.discover_top_players(count)

    def scrape_player_history(self, player_type: str, player_id: int, talent: int = 0):
        """Scrape fight history for a player and add to queue with type-based priorities."""
        if self.db.is_player_scraped(player_type, player_id):
            logger.debug(f"Already scraped {player_type}:{player_id}")
            return

        self.stats.current_action = f"Getting history for {player_type} {player_id}..."

        endpoint = f"history/get-{player_type}-history/{player_id}"
        data = self._client.request(endpoint)

        if data and "fights" in data:
            # Group fights by type for priority-based queueing
            fights_by_type: dict[int, list[int]] = {}
            for fight in data["fights"]:
                fight_id = fight.get("id")
                fight_type = fight.get("type", 0)

                if self.fight_types is not None and fight_type not in self.fight_types:
                    continue

                if fight_id:
                    if fight_type not in fights_by_type:
                        fights_by_type[fight_type] = []
                    fights_by_type[fight_type].append(fight_id)

            source = f"{player_type}:{player_id}"
            base_priority = talent // 100
            total_added = 0
            total_fights = 0

            # Queue fights with type-based priority modifiers
            for fight_type, fight_ids in fights_by_type.items():
                total_fights += len(fight_ids)
                type_modifier = self.FIGHT_TYPE_PRIORITY.get(fight_type, 0)
                priority = base_priority + type_modifier
                added = self.db.add_to_queue(fight_ids, source, priority)
                total_added += added

            if total_added > 0:
                logger.info(f"Queued {total_added}/{total_fights} new fights from {source}")
            else:
                logger.debug(f"No new fights from {source} ({total_fights} already downloaded)")

            self.db.mark_player_scraped(player_type, player_id, talent)
            self.stats.queue_size = self.db.queue_size()

    def download_fight(self, fight_id: int) -> Optional[bool]:
        """
        Download a single fight.

        Returns:
            True: Successfully downloaded and saved
            False: Skipped permanently (test fight, too short, etc)
            None: Failed (network error, pending) - keep in queue for retry
        """
        if self.db.has_fight(fight_id):
            self.stats.fights_skipped += 1
            return False

        self.stats.current_action = f"Downloading fight {fight_id}..."
        self.stats.last_fight_id = fight_id

        data = self._client.request(f"fight/get/{fight_id}")

        if data is None:
            self.stats.fights_failed += 1
            return None

        # Check for auth required marker
        if isinstance(data, dict) and data.get("_auth_required"):
            logger.info(f"Fight {fight_id} requires auth, skipping permanently")
            self.stats.fights_skipped += 1
            return False

        # Verify it's a complete fight
        if data.get("winner", -1) == -1:
            logger.debug(f"Fight {fight_id} still pending, moving to back of queue")
            self.db.delay_in_queue(fight_id)
            return False

        # Skip test fights if configured
        context = data.get("context", -1)
        if self.skip_test_fights and context == self.CONTEXT_TEST:
            logger.debug(f"Fight {fight_id} is a test fight, skipping")
            self.stats.fights_skipped += 1
            return False

        # Check duration
        fight_data = data.get("data", {})
        duration = 0
        for action in fight_data.get("actions", []):
            if isinstance(action, list) and len(action) >= 2 and action[0] == 6:
                duration = max(duration, action[1])

        if duration < self.min_duration:
            logger.debug(f"Fight {fight_id} too short ({duration} turns), skipping")
            self.stats.fights_skipped += 1
            return False

        if self.db.save_fight(fight_id, data):
            self.stats.fights_downloaded += 1
            self.stats.total_in_db = self.db.get_stats()["total_fights"]
            self.stats.last_error = None

            # Extract leek observations and discover new leeks
            self._process_fight_leeks(fight_id, data)
            return True

        self.stats.fights_failed += 1
        return None

    def _process_fight_leeks(self, fight_id: int, fight_data: dict):
        """Extract leek observations and add newly discovered leeks to queue."""
        new_leeks = self.db.extract_and_save_leek_observations(fight_id, fight_data)

        if not new_leeks:
            return

        # Build name → real_id map from outer leeks
        outer_leeks = fight_data.get("leeks1", []) + fight_data.get("leeks2", [])
        name_to_real_id = {l.get("name"): l.get("id") for l in outer_leeks if l.get("name")}
        real_id_to_outer = {l.get("id"): l for l in outer_leeks if l.get("id")}

        # Build name → inner leek (with stats) map
        data = fight_data.get("data", {})
        name_to_inner = {l.get("name"): l for l in data.get("leeks", []) if l.get("name") and not l.get("summon", False)}

        winner = fight_data.get("winner", -1)

        for leek_id in new_leeks:
            outer = real_id_to_outer.get(leek_id, {})
            if not outer:
                continue

            name = outer.get("name")
            if not name:
                continue

            inner = name_to_inner.get(name, {})

            level = inner.get("level", 0) or outer.get("level", 0)
            farmer_id = outer.get("farmer", 0) or inner.get("farmer", 0)

            total_stats = sum([
                inner.get("strength", 0),
                inner.get("agility", 0),
                inner.get("wisdom", 0),
                inner.get("resistance", 0),
                inner.get("magic", 0),
                inner.get("science", 0),
            ])

            team = inner.get("team", 0)
            won = 1.0 if winner == team else 0.0

            priority = self.db.calculate_priority_score(level, total_stats, won)

            self.db.add_to_discovery_queue(
                leek_id=leek_id,
                farmer_id=farmer_id,
                level=level,
                priority_score=priority,
                discovered_in_fight=fight_id
            )

    def scrape_low_level_winners(self, count: int = 5) -> int:
        """
        Find and scrape fight histories of low-level tournament winners.

        Returns number of new leeks queued for scraping.
        """
        self.stats.current_action = "Scraping low-level tournament winners..."

        winners = self._tournament_explorer.find_low_level_tournament_winners(
            count=count * 2,
            stop_event=self._stop_event
        )

        queued = 0
        for leek_id, level, is_winner in winners:
            if queued >= count:
                break

            if self.db.is_player_scraped("leek", leek_id):
                continue

            self.stats.current_action = f"Scraping winner leek {leek_id} (lvl {level})..."

            priority = 200 + (TournamentExplorer.LOW_LEVEL_THRESHOLD - level)
            self.db.add_to_discovery_queue(
                leek_id=leek_id,
                farmer_id=0,
                level=level,
                priority_score=priority,
                discovered_in_fight=0
            )

            self.scrape_player_history("leek", leek_id, talent=priority)
            queued += 1

        return queued

    def _run_loop(self):
        """Main scraper loop."""
        self.stats.status = ScraperStatus.RUNNING
        self.stats.started_at = datetime.now().isoformat()

        try:
            # Strategy selection based on level 301 ratio
            level_301_ratio = self.db.get_level_301_ratio()
            use_low_level_strategy = level_301_ratio >= self.LOW_LEVEL_STRATEGY_THRESHOLD
            self.stats.level_301_ratio = level_301_ratio

            if use_low_level_strategy:
                # Primary strategy: 2025 solo tournaments with level-bracket sampling
                logger.info(f"Using 2025 SOLO BRACKET strategy (level 301 ratio: {level_301_ratio:.1%})")
                self.stats.current_strategy = "solo_2025_brackets"
                self.stats.current_action = "Strategy: 2025 solo tournaments (level brackets)"

                if not self._stop_event.is_set():
                    # Explore 2025 solo tournaments with level-bracket priority
                    leeks = self._tournament_explorer.explore_solo_tournaments_2025(
                        count=10,
                        target_brackets=[(1, 100), (101, 200), (201, 300)],
                        stop_event=self._stop_event
                    )
                    logger.info(f"Discovered {leeks} leeks from 2025 solo tournaments")

                    # Fallback to low-level winners if needed
                    if leeks == 0 and not self._stop_event.is_set():
                        queued = self.scrape_low_level_winners(count=5)
                        logger.info(f"Fallback: queued {queued} low-level tournament winners")
            else:
                logger.info(f"Using TOP PLAYER strategy (level 301 ratio: {level_301_ratio:.1%})")
                self.stats.current_strategy = "top_players"
                self.stats.current_action = "Strategy: Top players (need more level 301)"

                if not self._stop_event.is_set():
                    players = self.discover_top_players()

                    for player_type, player_id, talent in players:
                        if self._stop_event.is_set():
                            break
                        self.scrape_player_history(player_type, player_id, talent)

            # Phase 3: Download fights from queue + snowball discovery
            while not self._stop_event.is_set():
                fight_id = self.db.peek_from_queue()

                if fight_id is None:
                    # Fight queue empty - check discovery queue
                    discovered = self.db.peek_from_discovery_queue()
                    if discovered:
                        leek_id, farmer_id, level = discovered
                        self.stats.current_action = f"Discovered leek {leek_id} (lvl {level}), getting history..."
                        self.scrape_player_history("leek", leek_id, talent=0)
                        self.db.remove_from_discovery_queue(leek_id)
                        continue

                    # Both queues empty - re-evaluate strategy
                    level_301_ratio = self.db.get_level_301_ratio()
                    self.stats.level_301_ratio = level_301_ratio
                    use_low_level_strategy = level_301_ratio >= self.LOW_LEVEL_STRATEGY_THRESHOLD

                    if use_low_level_strategy:
                        self.stats.current_strategy = "solo_2025_brackets"
                        self.stats.current_action = "Exploring 2025 solo tournaments (level brackets)..."

                        # Try 2025 solo tournaments first
                        leeks_found = self._tournament_explorer.explore_solo_tournaments_2025(
                            count=5,
                            target_brackets=[(1, 100), (101, 200), (201, 300)],
                            stop_event=self._stop_event
                        )
                        if leeks_found > 0:
                            logger.info(f"Discovered {leeks_found} leeks from 2025 solo tournaments")
                            continue

                        # Fallback to low-level winners
                        self.stats.current_action = "Fallback: finding low-level tournament winners..."
                        queued = self.scrape_low_level_winners(count=5)
                        if queued > 0:
                            logger.info(f"Queued {queued} low-level winners (fallback)")
                            continue
                    else:
                        self.stats.current_strategy = "top_players"
                        self.stats.current_action = "Exploring tournaments for more leeks..."
                        leeks_found = self._tournament_explorer.explore_tournaments_backward(
                            count=5,
                            stop_event=self._stop_event,
                            scrape_history_callback=self.scrape_player_history
                        )
                        if leeks_found > 0:
                            continue

                    self.db.update_level_stats()
                    time.sleep(5)
                    continue

                # Try to download
                result = self.download_fight(fight_id)
                if result is not None:
                    self.db.remove_from_queue(fight_id)

                self.stats.queue_size = self.db.queue_size()

                # Update DB size and level stats periodically
                if self.stats.fights_downloaded % 10 == 0:
                    stats = self.db.get_stats()
                    self.stats.db_size_mb = stats["db_size_mb"]

                if self.stats.fights_downloaded % 100 == 0:
                    self.db.update_level_stats()

                if self.stats.fights_downloaded % 500 == 0:
                    self.db.cleanup_queue()

        except Exception as e:
            self.stats.status = ScraperStatus.ERROR
            self.stats.last_error = str(e)
            logger.error(f"Scraper error: {e}")
            raise
        finally:
            if self.stats.status != ScraperStatus.ERROR:
                self.stats.status = ScraperStatus.IDLE
            self.stats.current_action = "Stopped"

    def start(self) -> bool:
        """Start the scraper in a background thread."""
        if self._thread and self._thread.is_alive():
            return False

        self._stop_event.clear()
        self._pause_event.set()

        # Reset stats
        self.stats = ScraperStats()
        self._client.stats = self.stats
        self._tournament_explorer.stats = self.stats
        self._player_discovery.stats = self.stats

        db_stats = self.db.get_stats()
        self.stats.total_in_db = db_stats["total_fights"]
        self.stats.queue_size = db_stats["queue_size"]
        self.stats.db_size_mb = db_stats["db_size_mb"]

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        """Stop the scraper."""
        self.stats.status = ScraperStatus.STOPPING
        self._stop_event.set()
        self._pause_event.set()

        if self._thread:
            self._thread.join(timeout=10)

    def pause(self):
        """Pause the scraper."""
        if self.stats.status == ScraperStatus.RUNNING:
            self._pause_event.clear()
            self.stats.status = ScraperStatus.PAUSED
            self.stats.current_action = "Paused"

    def resume(self):
        """Resume the scraper."""
        if self.stats.status == ScraperStatus.PAUSED:
            self._pause_event.set()
            self.stats.status = ScraperStatus.RUNNING

    def is_running(self) -> bool:
        """Check if scraper is running."""
        return self._thread is not None and self._thread.is_alive()

    def get_stats(self) -> dict:
        """Get current statistics as dict."""
        return {
            "status": self.stats.status.value,
            "fights_downloaded": self.stats.fights_downloaded,
            "fights_skipped": self.stats.fights_skipped,
            "fights_failed": self.stats.fights_failed,
            "players_discovered": self.stats.players_discovered,
            "queue_size": self.stats.queue_size,
            "total_in_db": self.stats.total_in_db,
            "db_size_mb": self.stats.db_size_mb,
            "current_action": self.stats.current_action,
            "current_strategy": self.stats.current_strategy,
            "level_301_ratio": round(self.stats.level_301_ratio, 3),
            "strategy_threshold": self.LOW_LEVEL_STRATEGY_THRESHOLD,
            "last_fight_id": self.stats.last_fight_id,
            "last_error": self.stats.last_error,
            "started_at": self.stats.started_at,
            "requests_made": self.stats.requests_made,
            "avg_request_time": round(self.stats.avg_request_time, 3),
            "delay": self.delay,
            "rate_limit_hits": self.stats.rate_limit_hits,
            "rate_limited_until": self.stats.rate_limited_until,
        }


# Global scraper instance for dashboard
_scraper: Optional[FightScraper] = None


def get_scraper() -> FightScraper:
    """Get or create the global scraper instance."""
    global _scraper
    if _scraper is None:
        _scraper = FightScraper()
    return _scraper
