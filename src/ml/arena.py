"""
Arena for AI version battles with Elo rating system.
"""

import math
from dataclasses import dataclass
from typing import Optional, Callable
from itertools import combinations

from .version import AIVersion, VersionRegistry


@dataclass
class MatchResult:
    """Result of a match between two versions."""
    version1_id: str
    version2_id: str
    version1_wins: int
    version2_wins: int
    draws: int
    version1_elo_delta: float
    version2_elo_delta: float

    @property
    def total_games(self) -> int:
        return self.version1_wins + self.version2_wins + self.draws

    @property
    def version1_score(self) -> float:
        """Score for v1: 1 for win, 0.5 for draw, 0 for loss."""
        return self.version1_wins + 0.5 * self.draws

    @property
    def version2_score(self) -> float:
        """Score for v2: 1 for win, 0.5 for draw, 0 for loss."""
        return self.version2_wins + 0.5 * self.draws


@dataclass
class TournamentResult:
    """Result of a tournament."""
    matches: list[MatchResult]
    rankings: list[tuple[str, float]]  # (version_id, elo)
    total_games: int


class EloCalculator:
    """
    Elo rating calculator.

    Standard chess Elo with K-factor adjustment.
    """

    def __init__(self, k_factor: float = 32.0):
        self.k_factor = k_factor

    def expected_score(self, rating_a: float, rating_b: float) -> float:
        """Calculate expected score for player A against player B."""
        return 1.0 / (1.0 + math.pow(10, (rating_b - rating_a) / 400.0))

    def calculate_delta(
        self,
        rating_a: float,
        rating_b: float,
        actual_score: float,
        games: int = 1,
    ) -> float:
        """
        Calculate Elo rating change for player A.

        Args:
            rating_a: Current rating of player A
            rating_b: Current rating of player B
            actual_score: Actual score (wins + 0.5*draws) / total_games
            games: Number of games played

        Returns:
            Rating delta for player A
        """
        expected = self.expected_score(rating_a, rating_b)
        return self.k_factor * games * (actual_score - expected)

    def update_ratings(
        self,
        rating_a: float,
        rating_b: float,
        wins_a: int,
        wins_b: int,
        draws: int,
    ) -> tuple[float, float]:
        """
        Update ratings after a match.

        Returns (delta_a, delta_b).
        """
        total_games = wins_a + wins_b + draws
        if total_games == 0:
            return 0.0, 0.0

        score_a = (wins_a + 0.5 * draws) / total_games
        score_b = (wins_b + 0.5 * draws) / total_games

        delta_a = self.calculate_delta(rating_a, rating_b, score_a, total_games)
        delta_b = self.calculate_delta(rating_b, rating_a, score_b, total_games)

        return delta_a, delta_b


class Arena:
    """
    Arena for running battles between AI versions.

    Uses a fight simulator to run matches and updates Elo ratings.
    """

    def __init__(
        self,
        registry: VersionRegistry,
        fight_runner: Optional[Callable] = None,
        k_factor: float = 32.0,
    ):
        """
        Initialize arena.

        Args:
            registry: Version registry for loading models and updating stats
            fight_runner: Function to run fights (version1, version2, n_games) -> (v1_wins, v2_wins, draws)
            k_factor: Elo K-factor
        """
        self.registry = registry
        self.fight_runner = fight_runner
        self.elo = EloCalculator(k_factor)
        self.progress_callback: Optional[Callable] = None

    def set_progress_callback(self, callback: Callable):
        """Set callback for progress updates."""
        self.progress_callback = callback

    def set_fight_runner(self, runner: Callable):
        """Set the fight runner function."""
        self.fight_runner = runner

    def _notify_progress(self, **kwargs):
        """Notify progress callback if set."""
        if self.progress_callback:
            self.progress_callback(**kwargs)

    def run_match(
        self,
        version1_id: str,
        version2_id: str,
        n_games: int = 100,
    ) -> Optional[MatchResult]:
        """
        Run a match between two versions.

        Args:
            version1_id: First version ID
            version2_id: Second version ID
            n_games: Number of games to play

        Returns:
            MatchResult or None if fight_runner not set
        """
        if self.fight_runner is None:
            raise ValueError("Fight runner not set. Call set_fight_runner() first.")

        v1 = self.registry.get_version(version1_id)
        v2 = self.registry.get_version(version2_id)

        if v1 is None or v2 is None:
            return None

        self._notify_progress(
            phase="arena",
            message=f"Running match: {v1.name} vs {v2.name}...",
            match_progress=0,
            total_games=n_games,
        )

        # Run fights
        v1_wins, v2_wins, draws = self.fight_runner(version1_id, version2_id, n_games)

        # Calculate Elo changes
        delta1, delta2 = self.elo.update_ratings(
            v1.elo_rating,
            v2.elo_rating,
            v1_wins,
            v2_wins,
            draws,
        )

        # Update registry
        self.registry.update_arena_stats(version1_id, wins=v1_wins, losses=v2_wins, draws=draws, elo_delta=delta1)
        self.registry.update_arena_stats(version2_id, wins=v2_wins, losses=v1_wins, draws=draws, elo_delta=delta2)

        result = MatchResult(
            version1_id=version1_id,
            version2_id=version2_id,
            version1_wins=v1_wins,
            version2_wins=v2_wins,
            draws=draws,
            version1_elo_delta=delta1,
            version2_elo_delta=delta2,
        )

        self._notify_progress(
            phase="arena",
            message=f"Match complete: {v1.name} {v1_wins}-{v2_wins}-{draws} {v2.name}",
            match_result=result,
        )

        return result

    def run_tournament(
        self,
        version_ids: Optional[list[str]] = None,
        n_games_per_match: int = 100,
    ) -> TournamentResult:
        """
        Run a round-robin tournament between versions.

        Args:
            version_ids: List of version IDs (None = all versions)
            n_games_per_match: Games per match

        Returns:
            TournamentResult
        """
        if version_ids is None:
            version_ids = list(self.registry.versions.keys())

        if len(version_ids) < 2:
            raise ValueError("Need at least 2 versions for a tournament")

        matches = []
        total_matches = len(list(combinations(version_ids, 2)))
        match_num = 0

        self._notify_progress(
            phase="tournament",
            message=f"Starting tournament with {len(version_ids)} versions...",
            total_matches=total_matches,
        )

        # Round-robin matches
        for v1_id, v2_id in combinations(version_ids, 2):
            match_num += 1
            self._notify_progress(
                phase="tournament",
                message=f"Match {match_num}/{total_matches}",
                current_match=match_num,
                total_matches=total_matches,
            )

            result = self.run_match(v1_id, v2_id, n_games_per_match)
            if result:
                matches.append(result)

        # Get final rankings
        rankings = [
            (v_id, self.registry.get_version(v_id).elo_rating)
            for v_id in version_ids
        ]
        rankings.sort(key=lambda x: x[1], reverse=True)

        total_games = sum(m.total_games for m in matches)

        result = TournamentResult(
            matches=matches,
            rankings=rankings,
            total_games=total_games,
        )

        self._notify_progress(
            phase="tournament_complete",
            message=f"Tournament complete! {total_games} games played.",
            tournament_result=result,
        )

        return result

    def challenge_champion(
        self,
        challenger_id: str,
        n_games: int = 100,
    ) -> tuple[MatchResult, bool]:
        """
        Challenge the current champion.

        Args:
            challenger_id: ID of challenger version
            n_games: Number of games to play

        Returns:
            (MatchResult, challenger_won: bool)
        """
        champion = self.registry.get_champion()
        if champion is None:
            raise ValueError("No champion exists yet")

        if champion.id == challenger_id:
            raise ValueError("Challenger is already the champion")

        result = self.run_match(challenger_id, champion.id, n_games)

        # Challenger wins if they won more games
        challenger_won = result.version1_wins > result.version2_wins

        if challenger_won:
            self._notify_progress(
                phase="champion_change",
                message=f"New champion: {self.registry.get_version(challenger_id).name}!",
                new_champion_id=challenger_id,
            )

        return result, challenger_won

    def get_leaderboard(self, limit: int = 10) -> list[dict]:
        """Get leaderboard sorted by Elo rating."""
        versions = self.registry.list_versions(sort_by="elo_rating")[:limit]
        return [
            {
                "rank": i + 1,
                "id": v.id,
                "name": v.name,
                "elo": v.elo_rating,
                "accuracy": v.accuracy,
                "arena_record": f"{v.arena_wins}W/{v.arena_losses}L/{v.arena_draws}D",
                "win_rate": v.arena_win_rate,
            }
            for i, v in enumerate(versions)
        ]

    def get_head_to_head(self, version1_id: str, version2_id: str) -> Optional[dict]:
        """Get head-to-head statistics (would need match history storage)."""
        v1 = self.registry.get_version(version1_id)
        v2 = self.registry.get_version(version2_id)

        if v1 is None or v2 is None:
            return None

        # For now, just return expected win rate based on Elo
        expected = self.elo.expected_score(v1.elo_rating, v2.elo_rating)

        return {
            "version1": {"id": v1.id, "name": v1.name, "elo": v1.elo_rating},
            "version2": {"id": v2.id, "name": v2.name, "elo": v2.elo_rating},
            "expected_v1_win_rate": expected,
            "expected_v2_win_rate": 1 - expected,
        }
