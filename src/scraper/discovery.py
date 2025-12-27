"""
Tournament exploration and player discovery.
"""

import re
import logging
from datetime import datetime
from typing import Optional

from .client import LeekWarsClient
from .db import FightDatabase
from .stats import ScraperStats

logger = logging.getLogger(__name__)

# Timestamp for Jan 1, 2025 00:00:00 UTC
YEAR_2025_START = 1735689600


class TournamentExplorer:
    """
    Explores tournaments to discover players and fights.

    Handles:
    - Finding latest tournament ID via binary search
    - Exploring solo, farmer, and team tournaments
    - Prioritizing low-level tournament winners
    """

    # Tournament exploration constants
    TOURNAMENT_START_ID = 108000  # Known valid tournament ID (December 2025)
    TOURNAMENT_SEARCH_STEP = 100  # Step for binary search
    LOW_LEVEL_THRESHOLD = 200  # Levels below this are "low level"

    def __init__(
        self,
        client: LeekWarsClient,
        db: FightDatabase,
        stats: ScraperStats,
    ):
        """
        Initialize the tournament explorer.

        Args:
            client: LeekWars API client
            db: Fight database
            stats: Scraper statistics
        """
        self.client = client
        self.db = db
        self.stats = stats

    def find_latest_tournament_id(self) -> int:
        """Find the latest valid tournament ID using binary search."""
        self.stats.current_action = "Finding latest tournament..."

        # Start from known good ID and search forward
        low = self.TOURNAMENT_START_ID
        high = low + 10000

        def is_valid(data):
            return data and "error" not in data and not data.get("_auth_required")

        # First, find an upper bound that doesn't exist
        while True:
            data = self.client.request(f"tournament/get/{high}")
            if not is_valid(data):
                break
            high += 1000
            if high > 200000:
                break

        # Binary search for the latest valid ID
        latest = low
        while low <= high:
            mid = (low + high) // 2
            data = self.client.request(f"tournament/get/{mid}")
            if is_valid(data):
                latest = mid
                low = mid + 1
            else:
                high = mid - 1

        return latest

    def explore_tournament(self, tournament_id: int, scrape_history_callback=None) -> int:
        """
        Explore a tournament and add participants to discovery queue.

        Args:
            tournament_id: Tournament ID to explore
            scrape_history_callback: Optional callback(player_type, player_id, talent)
                                    for scraping farmer histories

        Returns:
            Number of leeks/farmers found.
        """
        if self.db.is_tournament_explored(tournament_id):
            return 0

        self.stats.current_action = f"Exploring tournament {tournament_id}..."

        data = self.client.request(f"tournament/get/{tournament_id}")
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
            found_count, low_level_count = self._explore_solo_tournament(
                data, low_level_boost, level_301_ratio
            )

        elif tournament_type in ("farmer", "team"):
            found_count = self._explore_farmer_tournament(
                data, scrape_history_callback
            )

        # Mark tournament as explored
        self.db.mark_tournament_explored(
            tournament_id, tournament_type, tournament_date,
            found_count, low_level_count
        )

        entity_type = 'leeks' if tournament_type == 'solo' else 'farmers'
        logger.info(f"Tournament {tournament_id} ({tournament_type}): found {found_count} {entity_type}")
        return found_count

    def _explore_solo_tournament(
        self, data: dict, low_level_boost: int, level_301_ratio: float
    ) -> tuple[int, int]:
        """Extract leeks from solo tournament."""
        leeks_found = set()
        low_level_count = 0

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

                    self.db.add_to_discovery_queue(
                        leek_id=leek_id,
                        farmer_id=0,
                        level=level,
                        priority_score=priority,
                        discovered_in_fight=0
                    )

        return len(leeks_found), low_level_count

    def _explore_farmer_tournament(
        self, data: dict, scrape_history_callback=None
    ) -> int:
        """Extract farmers from farmer/team tournament."""
        farmers_found = set()

        for round_name, matches in data.get("rounds", {}).items():
            for match in matches:
                for contestant in match.get("contestants", []):
                    farmer_id = contestant.get("id")
                    if not farmer_id or farmer_id in farmers_found:
                        continue

                    farmers_found.add(farmer_id)

                    if scrape_history_callback:
                        won = contestant.get("win", False)
                        talent = 100 if won else 50
                        scrape_history_callback("farmer", farmer_id, talent)

        return len(farmers_found)

    def explore_tournaments_backward(self, count: int = 10, stop_event=None, scrape_history_callback=None) -> int:
        """
        Explore tournaments going backward in time.

        Args:
            count: Number of tournaments to explore
            stop_event: Optional event to signal stop
            scrape_history_callback: Optional callback(player_type, player_id, talent)
                                    for scraping farmer histories

        Returns total leeks discovered.
        """
        # Find the minimum tournament ID we've explored
        with self.db._connect() as conn:
            cursor = conn.execute("SELECT MIN(tournament_id) FROM tournament_exploration")
            row = cursor.fetchone()
            min_explored = row[0] if row and row[0] else None

        if min_explored is None:
            start_id = self.find_latest_tournament_id()
        else:
            start_id = min_explored - 1

        total_leeks = 0
        explored = 0

        tournament_id = start_id
        while explored < count and tournament_id > 0:
            if stop_event and stop_event.is_set():
                break

            if not self.db.is_tournament_explored(tournament_id):
                leeks = self.explore_tournament(tournament_id, scrape_history_callback)
                total_leeks += leeks
                explored += 1

            tournament_id -= 1

        return total_leeks

    def explore_solo_tournaments_2025(
        self,
        count: int = 10,
        target_brackets: Optional[list[tuple[int, int]]] = None,
        stop_event=None,
    ) -> int:
        """
        Explore 2025 solo tournaments focusing on specific level brackets.

        Args:
            count: Number of tournaments to explore
            target_brackets: List of (min_level, max_level) tuples to prioritize.
                            Default: [(1, 100), (101, 200), (201, 300)]
            stop_event: Optional event to signal stop

        Returns:
            Number of leeks discovered.
        """
        if target_brackets is None:
            target_brackets = [(1, 100), (101, 200), (201, 300)]

        self.stats.current_action = "Exploring 2025 solo tournaments for level brackets..."

        # Get level bracket counts to determine priority boosts
        bracket_counts = self.db.get_level_bracket_counts()
        total_obs = sum(b.get("count", 0) for b in bracket_counts.values())

        # Calculate scarcity-based priority boost per bracket
        def get_bracket_priority(level: int) -> int:
            """Higher priority for underrepresented brackets."""
            if level <= 50:
                bracket_key = "1-50"
            elif level <= 100:
                bracket_key = "51-100"
            elif level <= 150:
                bracket_key = "101-150"
            elif level <= 200:
                bracket_key = "151-200"
            elif level <= 250:
                bracket_key = "201-250"
            elif level <= 300:
                bracket_key = "251-300"
            else:
                return 0  # No boost for level 301

            bracket_data = bracket_counts.get(bracket_key, {})
            bracket_count = bracket_data.get("count", 0)

            if total_obs == 0:
                return 100

            # Inverse ratio: fewer observations = higher priority
            ratio = bracket_count / total_obs
            if ratio < 0.05:
                return 200  # Very underrepresented
            elif ratio < 0.10:
                return 150  # Underrepresented
            elif ratio < 0.15:
                return 100  # Moderate
            else:
                return 50   # Well represented

        # Find minimum explored tournament
        with self.db._connect() as conn:
            cursor = conn.execute("SELECT MIN(tournament_id) FROM tournament_exploration")
            row = cursor.fetchone()
            min_explored = row[0] if row and row[0] else None

        if min_explored is None:
            start_id = self.find_latest_tournament_id()
        else:
            start_id = min_explored - 1

        total_leeks = 0
        explored = 0
        tournament_id = start_id

        while explored < count and tournament_id > 0:
            if stop_event and stop_event.is_set():
                break

            if self.db.is_tournament_explored(tournament_id):
                tournament_id -= 1
                continue

            self.stats.current_action = f"Checking solo tournament {tournament_id} (2025 brackets)..."

            data = self.client.request(f"tournament/get/{tournament_id}")
            if data is None or "error" in data or data.get("_auth_required"):
                tournament_id -= 1
                continue

            tournament_type = data.get("type", "unknown")
            tournament_date = data.get("date", 0)

            # Skip non-solo tournaments
            if tournament_type != "solo":
                self.db.mark_tournament_explored(
                    tournament_id, tournament_type, tournament_date, 0, 0
                )
                tournament_id -= 1
                explored += 1
                continue

            # Skip pre-2025 tournaments
            if tournament_date < YEAR_2025_START:
                self.db.mark_tournament_explored(
                    tournament_id, tournament_type, tournament_date, 0, 0
                )
                logger.debug(f"Tournament {tournament_id} is from before 2025, skipping")
                tournament_id -= 1
                explored += 1
                continue

            # Extract all leeks from this solo tournament
            leeks_found = set()
            bracket_matches = 0

            for round_name, matches in data.get("rounds", {}).items():
                for match in matches:
                    for contestant in match.get("contestants", []):
                        if contestant is None:
                            continue
                        leek_id = contestant.get("id")
                        if not leek_id or leek_id in leeks_found:
                            continue

                        leeks_found.add(leek_id)

                        # Extract level
                        name = contestant.get("name", "")
                        level_match = re.search(r"\((\d+)\)", name)
                        level = int(level_match.group(1)) if level_match else 301

                        # Check if in target brackets
                        in_target = any(
                            min_lvl <= level <= max_lvl
                            for min_lvl, max_lvl in target_brackets
                        )

                        won = contestant.get("win", False)
                        base_priority = 75 if won else 40

                        # Apply bracket-based priority
                        if in_target:
                            bracket_matches += 1
                            bracket_boost = get_bracket_priority(level)
                            priority = base_priority + bracket_boost
                        else:
                            priority = base_priority

                        self.db.add_to_discovery_queue(
                            leek_id=leek_id,
                            farmer_id=0,
                            level=level,
                            priority_score=priority,
                            discovered_in_fight=0
                        )

            total_leeks += len(leeks_found)

            self.db.mark_tournament_explored(
                tournament_id, tournament_type, tournament_date,
                len(leeks_found), bracket_matches
            )

            if leeks_found:
                logger.info(
                    f"Tournament {tournament_id} (2025 solo): "
                    f"{len(leeks_found)} leeks, {bracket_matches} in target brackets"
                )

            tournament_id -= 1
            explored += 1

        return total_leeks

    def find_low_level_tournament_winners(self, count: int = 10, stop_event=None) -> list[tuple[int, int, bool]]:
        """
        Find winners of low-level solo tournaments.

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

        while len(winners) < count and tournament_id > 0:
            if stop_event and stop_event.is_set():
                break

            if self.db.is_tournament_explored(tournament_id):
                tournament_id -= 1
                continue

            self.stats.current_action = f"Checking tournament {tournament_id} for low-level winners..."

            data = self.client.request(f"tournament/get/{tournament_id}")
            if data is None or "error" in data or data.get("_auth_required"):
                tournament_id -= 1
                continue

            tournament_type = data.get("type", "unknown")
            tournament_date = data.get("date", 0)

            # Only process solo tournaments for individual leek levels
            if tournament_type != "solo":
                self.db.mark_tournament_explored(
                    tournament_id, tournament_type, tournament_date, 0, 0
                )
                tournament_id -= 1
                explored += 1
                continue

            # Find the winner (they progress through rounds)
            all_leeks = {}
            max_round = 0
            final_round_name = None

            for round_name, matches in data.get("rounds", {}).items():
                # Parse round number
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

            self.db.mark_tournament_explored(
                tournament_id, tournament_type, tournament_date,
                len(all_leeks), low_level_count
            )

            tournament_id -= 1
            explored += 1

        return winners[:count]


class PlayerDiscovery:
    """Discovers top players from rankings."""

    def __init__(
        self,
        client: LeekWarsClient,
        stats: ScraperStats,
    ):
        self.client = client
        self.stats = stats

    def discover_top_players(self, count: int = 50) -> list[tuple[str, int, int]]:
        """
        Discover top players from the ranking.

        Returns list of (player_type, player_id, talent) tuples.
        """
        self.stats.current_action = "Discovering top players..."
        players = []

        # Get home ranking (top 10 leeks + farmers)
        data = self.client.request("ranking/get-home-ranking")
        if data:
            for leek in data.get("leeks", []):
                players.append(("leek", leek["id"], leek.get("talent", 0)))
            for farmer in data.get("farmers", []):
                players.append(("farmer", farmer["id"], farmer.get("talent", 0)))

        self.stats.players_discovered = len(players)
        return players[:count]
