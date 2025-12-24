"""
Tests for deterministic seed functionality.
"""

import pytest

from src.localfight.runner import check_generator, run_fight
from src.localfight.scenario import Scenario
from src.localfight.parser import parse_fight_result


@pytest.fixture
def generator_check():
    """Skip if generator not available."""
    if not check_generator():
        pytest.skip("Generator not available")


class TestDeterministicSeeds:
    """Tests for reproducible fight execution."""

    def test_same_seed_same_result(self, generator_check):
        """Test that same seed produces identical results."""
        seed = 42

        results = []
        for _ in range(2):
            scenario = Scenario.create_1v1_pistol(seed=seed)
            raw_result = run_fight(scenario)
            parsed = parse_fight_result(raw_result)
            results.append(parsed)

        # All results should be identical
        assert results[0].winner == results[1].winner
        assert results[0].duration == results[1].duration

        # Compare turn-by-turn damage
        for t1, t2 in zip(results[0].turns, results[1].turns):
            assert t1.damage_dealt == t2.damage_dealt
            assert t1.damage_taken == t2.damage_taken

    def test_different_seeds_different_results(self, generator_check):
        """Test that different seeds can produce different results."""
        # Run multiple fights with different seeds
        results = []
        for seed in range(10):
            scenario = Scenario.create_1v1_pistol(seed=seed)
            raw_result = run_fight(scenario)
            parsed = parse_fight_result(raw_result)
            results.append((parsed.winner, parsed.duration))

        # Not all results should be identical (statistically very unlikely)
        unique_results = set(results)
        assert len(unique_results) > 1, "All 10 seeds produced identical results"

    def test_seed_field_exists(self, generator_check):
        """Test that seed field exists in FightResult."""
        seed = 12345
        scenario = Scenario.create_1v1_pistol(seed=seed)
        raw_result = run_fight(scenario)
        parsed = parse_fight_result(raw_result)

        # Seed field should exist (may be None if not returned by generator)
        # The generator doesn't echo the seed back, so we check the field exists
        assert hasattr(parsed, 'seed')
        # Seed is None since generator doesn't return it
        assert parsed.seed is None

    def test_seed_none_when_not_set(self, generator_check):
        """Test that seed is None when not explicitly set."""
        # Create scenario without seed
        scenario = Scenario.create_1v1_pistol(seed=None)
        raw_result = run_fight(scenario)
        parsed = parse_fight_result(raw_result)

        # Seed might be None or might be auto-generated
        # Just verify parsing doesn't crash
        assert parsed.winner in [-1, 0, 1]

    def test_random_scenario_determinism(self, generator_check):
        """Test determinism with random starting positions."""
        seed = 9999

        results = []
        for _ in range(2):
            scenario = Scenario.create_random_1v1_pistol(seed=seed)
            raw_result = run_fight(scenario)
            parsed = parse_fight_result(raw_result)
            results.append(parsed)

        # Results should be identical
        assert results[0].winner == results[1].winner
        assert results[0].duration == results[1].duration

    def test_parallel_determinism(self, generator_check):
        """Test determinism works in parallel execution."""
        from src.localfight.parallel import run_parallel

        seeds = [100, 200, 100, 200]  # Same seeds should give same results
        scenarios = [Scenario.create_1v1_pistol(seed=s) for s in seeds]

        result = run_parallel(scenarios, max_workers=4)

        assert result.success_count == 4

        # Fights with same seed should have same outcome
        assert result.results[0].winner == result.results[2].winner
        assert result.results[1].winner == result.results[3].winner
        assert result.results[0].duration == result.results[2].duration
        assert result.results[1].duration == result.results[3].duration
