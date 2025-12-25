"""
LeekWars fight scraper.

Politely downloads fight data from the LeekWars API.
"""

import os
import time
import threading
import requests
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Callable
import logging

from dotenv import load_dotenv

from .db import FightDatabase

logger = logging.getLogger(__name__)


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

    API_BASE = "https://leekwars.com/api"

    # Fight types
    TYPE_SOLO = 0
    TYPE_FARMER = 1
    TYPE_TEAM = 2

    # Context types
    CONTEXT_TEST = 0
    CONTEXT_CHALLENGE = 1
    CONTEXT_GARDEN = 2
    CONTEXT_TOURNAMENT = 3

    # Tournament exploration
    TOURNAMENT_START_ID = 108000  # Known valid tournament ID (December 2025)
    TOURNAMENT_SEARCH_STEP = 100  # Step for binary search
    LOW_LEVEL_THRESHOLD = 200  # Levels below this are "low level"

    # Strategy thresholds
    LOW_LEVEL_STRATEGY_THRESHOLD = 0.30  # Use low-level winner strategy when level 301 ratio >= this

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
        self.fight_types = fight_types  # None means all
        self.skip_test_fights = skip_test_fights
        self.min_duration = min_duration

        # Threading
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused by default

        # Statistics
        self.stats = ScraperStats()
        self._request_times: list[float] = []

        # Session for connection pooling
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "TagadAI/1.0 (ML Training Data Collection)"

        # Authentication
        self._token: Optional[str] = None
        self._authenticated = False

        # Auto-login if credentials available
        self._try_auto_login()

    def _try_auto_login(self):
        """Try to authenticate using environment credentials."""
        load_dotenv()
        login = os.getenv("LEEKWARS_LOGIN")
        password = os.getenv("LEEKWARS_PASSWORD")

        if login and password:
            try:
                self.login(login, password)
            except Exception as e:
                logger.warning(f"Auto-login failed: {e}")

    def login(self, login: str, password: str) -> dict:
        """Authenticate with LeekWars API."""
        response = self._session.post(
            f"{self.API_BASE}/farmer/login-token",
            data={"login": login, "password": password}
        )
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            raise ValueError(f"Login failed: {data.get('error')}")

        self._token = data.get("token")
        if self._token:
            self._session.headers["Authorization"] = f"Bearer {self._token}"
            self._authenticated = True
            logger.info(f"Authenticated as {data.get('farmer', {}).get('login', 'unknown')}")

        return data

    @property
    def is_authenticated(self) -> bool:
        """Check if scraper is authenticated."""
        return self._authenticated

    def _rate_limit(self):
        """Wait for rate limit."""
        self._pause_event.wait()  # Block if paused
        time.sleep(self.delay)

    def _request(self, endpoint: str, retries: int = 3) -> Optional[dict]:
        """Make a rate-limited API request with retries."""
        if self._stop_event.is_set():
            return None

        url = f"{self.API_BASE}/{endpoint}"

        for attempt in range(retries):
            if self._stop_event.is_set():
                return None

            self.stats.requests_made += 1
            start = time.time()

            try:
                response = self._session.get(url, timeout=30)
                elapsed = time.time() - start

                # Track request times
                self._request_times.append(elapsed)
                if len(self._request_times) > 100:
                    self._request_times.pop(0)
                self.stats.avg_request_time = sum(self._request_times) / len(self._request_times)

                if response.status_code == 200:
                    data = response.json()
                    if "error" in data:
                        self.stats.last_error = f"API: {data.get('error')}"
                        logger.warning(f"API error for {endpoint}: {data.get('error')}")
                        return None
                    return data
                elif response.status_code == 429:
                    # Rate limited - back off more aggressively
                    self.stats.rate_limit_hits += 1
                    wait = max(10, self.delay * (4 ** attempt))  # More aggressive backoff, min 10s
                    self.stats.rate_limited_until = time.time() + wait
                    self.stats.last_error = f"Rate limited (429)"
                    self.stats.current_action = f"Rate limited! Waiting {wait:.0f}s..."
                    logger.warning(f"Rate limited (hit #{self.stats.rate_limit_hits}), waiting {wait}s...")
                    time.sleep(wait)
                    self.stats.rate_limited_until = None
                    continue
                elif response.status_code == 401:
                    # 401 can mean auth required OR resource doesn't exist/restricted
                    try:
                        data = response.json()
                        # API returns either {"error": "msg"} or just "msg" string
                        if isinstance(data, str):
                            # Plain string error like "fight_with_secret_trophy"
                            self.stats.last_error = f"API: {data}"
                            return None
                        elif isinstance(data, dict) and "error" in data:
                            # Dict with error key like {"error": "no_such_tournament"}
                            self.stats.last_error = f"API: {data.get('error')}"
                            return None
                    except Exception:
                        pass
                    # No parseable error - actual auth issue
                    if not self._authenticated:
                        logger.warning(f"HTTP 401 for {endpoint} - not authenticated")
                    else:
                        logger.warning(f"HTTP 401 for {endpoint} - token may have expired")
                    self.stats.last_error = f"HTTP 401 - auth required"
                    return {"_auth_required": True}  # Special marker to skip
                elif response.status_code >= 500:
                    # Server error - retry
                    wait = self.delay * (2 ** attempt)
                    self.stats.last_error = f"Server error {response.status_code}"
                    self.stats.current_action = f"Server error, retry in {wait:.0f}s..."
                    logger.warning(f"Server error {response.status_code}, retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                else:
                    # Client error (404, 403, etc) - don't retry
                    self.stats.last_error = f"HTTP {response.status_code}"
                    logger.warning(f"HTTP {response.status_code} for {endpoint}")
                    return None

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                # Network error - retry with backoff
                wait = self.delay * (2 ** attempt)
                self.stats.last_error = str(e)
                logger.warning(f"Network error for {endpoint}, retrying in {wait}s: {e}")
                time.sleep(wait)
                continue

            except Exception as e:
                # Unexpected error - don't retry
                self.stats.last_error = str(e)
                logger.error(f"Request failed for {endpoint}: {e}")
                return None

            finally:
                self._rate_limit()

        self.stats.last_error = f"All {retries} retries failed"
        logger.error(f"All {retries} retries failed for {endpoint}")
        return None

    def discover_top_players(self, count: int = 50) -> list[tuple[str, int, int]]:
        """
        Discover top players from the ranking.

        Returns list of (player_type, player_id, talent) tuples.
        """
        self.stats.current_action = "Discovering top players..."
        players = []

        # Get home ranking (top 10 leeks + farmers)
        data = self._request("ranking/get-home-ranking")
        if data:
            for leek in data.get("leeks", []):
                players.append(("leek", leek["id"], leek.get("talent", 0)))
            for farmer in data.get("farmers", []):
                players.append(("farmer", farmer["id"], farmer.get("talent", 0)))

        # Could add more ranking pages here if needed
        # For now, top 10 of each is a good start

        self.stats.players_discovered = len(players)
        return players[:count]

    def scrape_player_history(self, player_type: str, player_id: int, talent: int = 0):
        """Scrape fight history for a player and add to queue."""
        if self.db.is_player_scraped(player_type, player_id):
            logger.debug(f"Already scraped {player_type}:{player_id}")
            return

        self.stats.current_action = f"Getting history for {player_type} {player_id}..."

        endpoint = f"history/get-{player_type}-history/{player_id}"
        data = self._request(endpoint)

        if data and "fights" in data:
            fight_ids = []
            for fight in data["fights"]:
                fight_id = fight.get("id")
                fight_type = fight.get("type")

                # Filter by fight type if specified
                if self.fight_types is not None and fight_type not in self.fight_types:
                    continue

                if fight_id:
                    fight_ids.append(fight_id)

            if fight_ids:
                # Higher talent = higher priority
                priority = talent // 100
                source = f"{player_type}:{player_id}"
                added = self.db.add_to_queue(fight_ids, source, priority)
                if added > 0:
                    logger.info(f"Queued {added}/{len(fight_ids)} new fights from {source}")
                else:
                    logger.debug(f"No new fights from {source} ({len(fight_ids)} already downloaded)")

            self.db.mark_player_scraped(player_type, player_id, talent)
            self.stats.queue_size = self.db.queue_size()

    def download_fight(self, fight_id: int) -> Optional[bool]:
        """
        Download a single fight.

        Returns:
            True: Successfully downloaded and saved
            False: Skipped permanently (test fight, too short, etc) - remove from queue
            None: Failed (network error, pending) - keep in queue for retry
        """
        if self.db.has_fight(fight_id):
            self.stats.fights_skipped += 1
            return False  # Already have it, remove from queue

        self.stats.current_action = f"Downloading fight {fight_id}..."
        self.stats.last_fight_id = fight_id

        data = self._request(f"fight/get/{fight_id}")

        if data is None:
            # Request failed (network error) - keep in queue for retry
            self.stats.fights_failed += 1
            return None

        # Check for auth required marker - skip permanently
        if isinstance(data, dict) and data.get("_auth_required"):
            logger.info(f"Fight {fight_id} requires auth, skipping permanently")
            self.stats.fights_skipped += 1
            return False  # Remove from queue permanently

        # Verify it's a complete fight
        if data.get("winner", -1) == -1:
            logger.debug(f"Fight {fight_id} still pending, moving to back of queue")
            self.db.delay_in_queue(fight_id)  # Move to back so we try other fights
            return False  # Treat as skipped for now, removed from front of queue

        # Skip test fights if configured
        context = data.get("context", -1)
        if self.skip_test_fights and context == self.CONTEXT_TEST:
            logger.debug(f"Fight {fight_id} is a test fight, skipping")
            self.stats.fights_skipped += 1
            return False  # Permanently skip, remove from queue

        # Check duration (from actions in nested data)
        fight_data = data.get("data", {})
        duration = 0
        for action in fight_data.get("actions", []):
            if isinstance(action, list) and len(action) >= 2 and action[0] == 6:
                duration = max(duration, action[1])

        if duration < self.min_duration:
            logger.debug(f"Fight {fight_id} too short ({duration} turns), skipping")
            self.stats.fights_skipped += 1
            return False  # Permanently skip, remove from queue

        if self.db.save_fight(fight_id, data):
            self.stats.fights_downloaded += 1
            self.stats.total_in_db = self.db.get_stats()["total_fights"]
            self.stats.last_error = None  # Clear error on success

            # Extract leek observations and discover new leeks
            self._process_fight_leeks(fight_id, data)

            return True

        # Save failed for some reason
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
            # Get outer leek info
            outer = real_id_to_outer.get(leek_id, {})
            if not outer:
                continue

            name = outer.get("name")
            if not name:
                continue

            # Get inner leek with stats
            inner = name_to_inner.get(name, {})

            level = inner.get("level", 0) or outer.get("level", 0)
            farmer_id = outer.get("farmer", 0) or inner.get("farmer", 0)

            # Calculate total stats from inner leek
            total_stats = sum([
                inner.get("strength", 0),
                inner.get("agility", 0),
                inner.get("wisdom", 0),
                inner.get("resistance", 0),
                inner.get("magic", 0),
                inner.get("science", 0),
            ])

            # Win rate from this single observation
            team = inner.get("team", 0)
            won = 1.0 if winner == team else 0.0

            # Calculate priority score
            priority = self.db.calculate_priority_score(level, total_stats, won)

            # Add to discovery queue
            self.db.add_to_discovery_queue(
                leek_id=leek_id,
                farmer_id=farmer_id,
                level=level,
                priority_score=priority,
                discovered_in_fight=fight_id
            )

    def find_latest_tournament_id(self) -> int:
        """Find the latest valid tournament ID using binary search."""
        self.stats.current_action = "Finding latest tournament..."

        # Start from known good ID and search forward
        low = self.TOURNAMENT_START_ID
        high = low + 10000  # Search up to 10000 ahead

        # Helper to check if response is valid
        def is_valid(data):
            return data and "error" not in data and not data.get("_auth_required")

        # First, find an upper bound that doesn't exist
        while True:
            data = self._request(f"tournament/get/{high}")
            if not is_valid(data):
                break
            high += 1000
            if high > 200000:  # Safety limit
                break

        # Binary search for the latest valid ID
        latest = low
        while low <= high:
            mid = (low + high) // 2
            data = self._request(f"tournament/get/{mid}")
            if is_valid(data):
                latest = mid
                low = mid + 1
            else:
                high = mid - 1

        return latest

    def explore_tournament(self, tournament_id: int) -> int:
        """
        Explore a tournament and add participants to discovery queue.
        Returns number of leeks/farmers found.

        Handles all tournament types:
        - solo: Extract leek IDs directly (level in name)
        - farmer: Extract farmer IDs, scrape their histories
        - team: Extract farmer IDs from team compositions
        """
        if self.db.is_tournament_explored(tournament_id):
            return 0

        self.stats.current_action = f"Exploring tournament {tournament_id}..."

        data = self._request(f"tournament/get/{tournament_id}")
        if data is None or "error" in data or data.get("_auth_required"):
            return 0

        tournament_type = data.get("type", "unknown")
        tournament_date = data.get("date", 0)

        # Calculate priority boost based on level 301 ratio
        level_301_ratio = self.db.get_level_301_ratio()
        low_level_boost = 100 if level_301_ratio > 0.5 else 50

        found_count = 0
        low_level_count = 0

        if tournament_type == "solo":
            # Solo tournaments: extract leek IDs with levels
            leeks_found = set()
            for round_name, matches in data.get("rounds", {}).items():
                for match in matches:
                    for contestant in match.get("contestants", []):
                        leek_id = contestant.get("id")
                        if not leek_id or leek_id in leeks_found:
                            continue

                        leeks_found.add(leek_id)

                        # Extract level from name like "Chara (300)"
                        name = contestant.get("name", "")
                        level_match = re.search(r"\((\d+)\)", name)
                        level = int(level_match.group(1)) if level_match else 301

                        if level < self.LOW_LEVEL_THRESHOLD:
                            low_level_count += 1

                        # Won a match = higher priority
                        won = contestant.get("win", False)

                        # Calculate priority with boost for low-level if needed
                        base_priority = 50 if won else 25
                        if level < self.LOW_LEVEL_THRESHOLD and level_301_ratio > 0.5:
                            priority = base_priority + low_level_boost + (self.LOW_LEVEL_THRESHOLD - level)
                        else:
                            priority = base_priority

                        # Add to discovery queue
                        self.db.add_to_discovery_queue(
                            leek_id=leek_id,
                            farmer_id=0,
                            level=level,
                            priority_score=priority,
                            discovered_in_fight=0
                        )

            found_count = len(leeks_found)

        elif tournament_type in ("farmer", "team"):
            # Farmer/team tournaments: extract farmer IDs and scrape their histories
            # This discovers their leeks indirectly through fight data
            farmers_found = set()
            for round_name, matches in data.get("rounds", {}).items():
                for match in matches:
                    for contestant in match.get("contestants", []):
                        farmer_id = contestant.get("id")
                        if not farmer_id or farmer_id in farmers_found:
                            continue

                        farmers_found.add(farmer_id)

                        # Scrape farmer history immediately (adds fights to queue)
                        # This will discover their leeks from their fight history
                        won = contestant.get("win", False)
                        talent = 100 if won else 50  # Rough priority based on tournament success
                        self.scrape_player_history("farmer", farmer_id, talent)

            found_count = len(farmers_found)
            # For farmer/team, we don't know individual leek levels yet
            low_level_count = 0

        # Mark tournament as explored
        self.db.mark_tournament_explored(
            tournament_id, tournament_type, tournament_date,
            found_count, low_level_count
        )

        logger.info(f"Tournament {tournament_id} ({tournament_type}): found {found_count} {'leeks' if tournament_type == 'solo' else 'farmers'}")
        return found_count

    def explore_tournaments_backward(self, count: int = 10) -> int:
        """
        Explore tournaments going backward in time.
        Returns total leeks discovered.
        """
        # Find the minimum tournament ID we've explored (to continue going backward)
        with self.db._connect() as conn:
            cursor = conn.execute("SELECT MIN(tournament_id) FROM tournament_exploration")
            row = cursor.fetchone()
            min_explored = row[0] if row and row[0] else None

        if min_explored is None:
            # First time - start from latest
            start_id = self.find_latest_tournament_id()
        else:
            # Continue backward from minimum explored ID
            start_id = min_explored - 1

        total_leeks = 0
        explored = 0

        # Explore tournaments going backward
        tournament_id = start_id
        while explored < count and tournament_id > 0 and not self._stop_event.is_set():
            if not self.db.is_tournament_explored(tournament_id):
                leeks = self.explore_tournament(tournament_id)
                total_leeks += leeks
                explored += 1

            tournament_id -= 1

        return total_leeks

    def find_low_level_tournament_winners(self, count: int = 10) -> list[tuple[int, int, bool]]:
        """
        Find winners of low-level solo tournaments.

        Explores solo tournaments and returns leek IDs of winners with levels below threshold.
        Returns list of (leek_id, level, is_winner) tuples.
        """
        self.stats.current_action = "Finding low-level tournament winners..."

        winners = []

        # Find the minimum tournament ID we've explored
        with self.db._connect() as conn:
            cursor = conn.execute("SELECT MIN(tournament_id) FROM tournament_exploration")
            row = cursor.fetchone()
            min_explored = row[0] if row and row[0] else None

        if min_explored is None:
            start_id = self.find_latest_tournament_id()
        else:
            start_id = min_explored - 1

        explored = 0
        tournament_id = start_id

        while len(winners) < count and tournament_id > 0 and not self._stop_event.is_set():
            if self.db.is_tournament_explored(tournament_id):
                tournament_id -= 1
                continue

            self.stats.current_action = f"Checking tournament {tournament_id} for low-level winners..."

            data = self._request(f"tournament/get/{tournament_id}")
            if data is None or "error" in data or data.get("_auth_required"):
                tournament_id -= 1
                continue

            tournament_type = data.get("type", "unknown")
            tournament_date = data.get("date", 0)

            # Only process solo tournaments for individual leek levels
            if tournament_type != "solo":
                # Still mark as explored but don't extract low-level winners
                self.db.mark_tournament_explored(
                    tournament_id, tournament_type, tournament_date, 0, 0
                )
                tournament_id -= 1
                explored += 1
                continue

            # Find the winner (they progress through rounds)
            # In tournament data, we look for contestants who won their final match
            all_leeks = {}
            max_round = 0
            final_round_name = None

            for round_name, matches in data.get("rounds", {}).items():
                # Parse round number (e.g., "round_3" -> 3, "finale" -> 999)
                if round_name == "finale":
                    round_num = 999
                elif round_name.startswith("round_"):
                    try:
                        round_num = int(round_name.split("_")[1])
                    except (ValueError, IndexError):
                        round_num = 0
                else:
                    round_num = 0

                if round_num > max_round:
                    max_round = round_num
                    final_round_name = round_name

                for match in matches:
                    for contestant in match.get("contestants", []):
                        if contestant is None:
                            continue
                        leek_id = contestant.get("id")
                        if not leek_id:
                            continue

                        # Extract level from name like "Chara (300)"
                        name = contestant.get("name", "")
                        level_match = re.search(r"\((\d+)\)", name)
                        level = int(level_match.group(1)) if level_match else 301

                        won = contestant.get("win", False)
                        round_reached = round_num

                        if leek_id not in all_leeks or round_reached > all_leeks[leek_id]["round"]:
                            all_leeks[leek_id] = {
                                "level": level,
                                "won_last": won,
                                "round": round_reached,
                            }

            # Find tournament winners (won their final match)
            tournament_winners = [
                (leek_id, info["level"])
                for leek_id, info in all_leeks.items()
                if info["won_last"] and info["round"] == max_round
            ]

            # Prioritize low-level winners
            low_level_winners = [
                (leek_id, level, True)
                for leek_id, level in tournament_winners
                if level < self.LOW_LEVEL_THRESHOLD
            ]

            low_level_count = sum(1 for _, info in all_leeks.items() if info["level"] < self.LOW_LEVEL_THRESHOLD)

            if low_level_winners:
                winners.extend(low_level_winners)
                logger.info(f"Tournament {tournament_id}: found {len(low_level_winners)} low-level winners")

            # Mark tournament as explored
            self.db.mark_tournament_explored(
                tournament_id, tournament_type, tournament_date,
                len(all_leeks), low_level_count
            )

            tournament_id -= 1
            explored += 1

        return winners[:count]

    def scrape_low_level_winners(self, count: int = 5) -> int:
        """
        Find and scrape fight histories of low-level tournament winners.

        This is the primary strategy for collecting diverse training data.
        Returns number of new leeks queued for scraping.
        """
        self.stats.current_action = "Scraping low-level tournament winners..."

        winners = self.find_low_level_tournament_winners(count=count * 2)  # Find more than needed

        queued = 0
        for leek_id, level, is_winner in winners:
            if queued >= count:
                break

            if self.db.is_player_scraped("leek", leek_id):
                continue

            self.stats.current_action = f"Scraping winner leek {leek_id} (lvl {level})..."

            # Add to discovery queue with high priority (tournament winners are good data)
            priority = 200 + (self.LOW_LEVEL_THRESHOLD - level)  # Lower level = higher priority
            self.db.add_to_discovery_queue(
                leek_id=leek_id,
                farmer_id=0,
                level=level,
                priority_score=priority,
                discovered_in_fight=0
            )

            # Immediately scrape their history
            self.scrape_player_history("leek", leek_id, talent=priority)
            queued += 1

        return queued

    def _run_loop(self):
        """Main scraper loop."""
        self.stats.status = ScraperStatus.RUNNING
        self.stats.started_at = datetime.now().isoformat()

        try:
            # Strategy selection based on level 301 ratio
            # Default: Low-level winner strategy (prioritize diverse training data)
            # Fallback: Top player strategy (when we need more high-level data)

            level_301_ratio = self.db.get_level_301_ratio()
            use_low_level_strategy = level_301_ratio >= self.LOW_LEVEL_STRATEGY_THRESHOLD
            self.stats.level_301_ratio = level_301_ratio

            if use_low_level_strategy:
                logger.info(f"Using LOW-LEVEL WINNER strategy (level 301 ratio: {level_301_ratio:.1%})")
                self.stats.current_strategy = "low_level_winners"
                self.stats.current_action = "Strategy: Low-level tournament winners"

                # Phase 1: Find and scrape low-level tournament winners
                if not self._stop_event.is_set():
                    queued = self.scrape_low_level_winners(count=10)
                    logger.info(f"Queued {queued} low-level tournament winners")
            else:
                logger.info(f"Using TOP PLAYER strategy (level 301 ratio: {level_301_ratio:.1%} < {self.LOW_LEVEL_STRATEGY_THRESHOLD:.0%})")
                self.stats.current_strategy = "top_players"
                self.stats.current_action = "Strategy: Top players (need more level 301)"

                # Phase 1: Discover top players (old strategy)
                if not self._stop_event.is_set():
                    players = self.discover_top_players()

                    # Phase 2: Get their histories
                    for player_type, player_id, talent in players:
                        if self._stop_event.is_set():
                            break
                        self.scrape_player_history(player_type, player_id, talent)

            # Phase 3: Download fights from queue + snowball discovery
            while not self._stop_event.is_set():
                # Peek at next fight (don't remove from queue yet)
                fight_id = self.db.peek_from_queue()

                if fight_id is None:
                    # Fight queue empty - check discovery queue for new leeks
                    discovered = self.db.peek_from_discovery_queue()
                    if discovered:
                        leek_id, farmer_id, level = discovered
                        self.stats.current_action = f"Discovered leek {leek_id} (lvl {level}), getting history..."
                        self.scrape_player_history("leek", leek_id, talent=0)
                        # Remove from discovery queue only after successful scrape
                        self.db.remove_from_discovery_queue(leek_id)
                        continue

                    # Both queues empty - re-evaluate strategy and find more leeks
                    level_301_ratio = self.db.get_level_301_ratio()
                    self.stats.level_301_ratio = level_301_ratio
                    use_low_level_strategy = level_301_ratio >= self.LOW_LEVEL_STRATEGY_THRESHOLD
                    self.stats.current_strategy = "low_level_winners" if use_low_level_strategy else "top_players"

                    if use_low_level_strategy:
                        self.stats.current_action = "Finding more low-level tournament winners..."
                        queued = self.scrape_low_level_winners(count=5)
                        if queued > 0:
                            logger.info(f"Queued {queued} more low-level winners")
                            continue
                    else:
                        # Fallback to general tournament exploration
                        self.stats.current_action = "Exploring tournaments for more leeks..."
                        leeks_found = self.explore_tournaments_backward(count=5)
                        if leeks_found > 0:
                            continue

                    # No new leeks found, update stats and wait briefly
                    self.db.update_level_stats()
                    time.sleep(5)
                    continue

                # Try to download
                # Returns: True=downloaded, False=skipped permanently, None=retry later
                result = self.download_fight(fight_id)
                if result is not None:
                    # Remove from queue if downloaded (True) or permanently skipped (False)
                    self.db.remove_from_queue(fight_id)
                # If result is None (failed), keep in queue for retry

                self.stats.queue_size = self.db.queue_size()

                # Update DB size and level stats periodically
                if self.stats.fights_downloaded % 10 == 0:
                    stats = self.db.get_stats()
                    self.stats.db_size_mb = stats["db_size_mb"]

                if self.stats.fights_downloaded % 100 == 0:
                    self.db.update_level_stats()

                # Periodic queue cleanup (every 500 downloads)
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
        self._pause_event.set()  # Unpause so thread can exit

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
