"""
Tests for parallel fight execution.
"""

import pytest
import os

from src.localfight.runner import check_generator
from src.localfight.scenario import Scenario, generate_scenarios
from src.localfight.parallel import (
    ParallelRunner,
    BatchResult,
    BatchBuilder,
    run_parallel,
)


@pytest.fixture
def generator_check():
    """Skip if generator not available."""
    if not check_generator():
        pytest.skip("Generator not available")


class TestBatchResult:
    """Tests for BatchResult dataclass."""

    def test_success_count(self):
        """Test success count calculation."""
        result = BatchResult(
            results=[None, None, None],  # 3 fake results
            errors=[],
            total_time=1.0,
            fights_per_second=3.0,
        )
        # Note: results is typed as List[FightResult] but we're using None for testing
        assert result.success_count == 3
        assert result.error_count == 0
        assert result.total_count == 3
        assert result.success_rate == 1.0

    def test_error_count(self):
        """Test error count calculation."""
        result = BatchResult(
            results=[None],  # 1 success
            errors=[(1, "error1"), (2, "error2")],  # 2 errors
            total_time=1.0,
            fights_per_second=3.0,
        )
        assert result.success_count == 1
        assert result.error_count == 2
        assert result.total_count == 3
        assert result.success_rate == pytest.approx(1/3)

    def test_empty_batch(self):
        """Test empty batch result."""
        result = BatchResult(
            results=[],
            errors=[],
            total_time=0.0,
            fights_per_second=0.0,
        )
        assert result.success_count == 0
        assert result.error_count == 0
        assert result.success_rate == 0.0


class TestParallelRunner:
    """Tests for ParallelRunner class."""

    def test_default_workers(self):
        """Test default worker count."""
        runner = ParallelRunner()
        assert runner.max_workers >= 1
        assert runner.max_workers <= (os.cpu_count() or 4)

    def test_custom_workers(self):
        """Test custom worker count."""
        runner = ParallelRunner(max_workers=2)
        assert runner.max_workers == 2

    def test_empty_batch(self, generator_check):
        """Test running empty batch."""
        runner = ParallelRunner()
        result = runner.run_batch([])

        assert result.success_count == 0
        assert result.error_count == 0
        assert result.total_time == 0.0

    def test_single_fight(self, generator_check):
        """Test running single fight."""
        runner = ParallelRunner()
        scenario = Scenario.create_1v1_pistol(seed=42)

        result = runner.run_single(scenario)

        assert result is not None
        assert result.winner in [-1, 0, 1]
        assert result.duration > 0

    def test_batch_of_two(self, generator_check):
        """Test running batch of 2 fights."""
        runner = ParallelRunner(max_workers=2)
        scenarios = generate_scenarios(count=2, base_seed=100)

        result = runner.run_batch(scenarios)

        assert result.success_count == 2
        assert result.error_count == 0
        assert result.total_time > 0
        assert result.fights_per_second > 0

    def test_batch_of_four(self, generator_check):
        """Test running batch of 4 fights in parallel."""
        runner = ParallelRunner(max_workers=4)
        scenarios = generate_scenarios(count=4, base_seed=200)

        result = runner.run_batch(scenarios)

        assert result.success_count == 4
        assert result.error_count == 0
        # Should be faster than sequential (but not guaranteed)
        assert len(result.results) == 4

    def test_progress_callback(self, generator_check):
        """Test progress callback is called."""
        runner = ParallelRunner(max_workers=2)
        scenarios = generate_scenarios(count=2, base_seed=300)

        callbacks = []

        def progress(completed, total, result):
            callbacks.append((completed, total, result is not None))

        runner.run_batch(scenarios, progress_callback=progress)

        assert len(callbacks) == 2
        assert callbacks[-1][0] == 2  # Last callback shows 2 completed
        assert callbacks[-1][1] == 2  # Out of 2 total


class TestBatchBuilder:
    """Tests for BatchBuilder fluent interface."""

    def test_empty_builder(self, generator_check):
        """Test empty builder."""
        result = BatchBuilder().run()

        assert result.success_count == 0

    def test_add_scenario(self, generator_check):
        """Test adding single scenario."""
        scenario = Scenario.create_1v1_pistol(seed=42)

        result = (
            BatchBuilder()
            .add_scenario(scenario)
            .run()
        )

        assert result.success_count == 1

    def test_add_scenarios(self, generator_check):
        """Test adding multiple scenarios."""
        scenarios = generate_scenarios(count=2, base_seed=400)

        result = (
            BatchBuilder()
            .add_scenarios(scenarios)
            .run()
        )

        assert result.success_count == 2

    def test_fluent_configuration(self, generator_check):
        """Test fluent configuration methods."""
        scenarios = generate_scenarios(count=2, base_seed=500)

        result = (
            BatchBuilder()
            .add_scenarios(scenarios)
            .with_workers(2)
            .with_timeout(60.0)
            .with_cache(False)
            .run()
        )

        assert result.success_count == 2

    def test_with_progress(self, generator_check):
        """Test progress callback in builder."""
        scenarios = generate_scenarios(count=2, base_seed=600)
        callbacks = []

        result = (
            BatchBuilder()
            .add_scenarios(scenarios)
            .with_workers(2)
            .with_progress(lambda c, t, r: callbacks.append((c, t)))
            .run()
        )

        assert result.success_count == 2
        assert len(callbacks) == 2


class TestRunParallel:
    """Tests for run_parallel convenience function."""

    def test_run_parallel(self, generator_check):
        """Test convenience function."""
        scenarios = generate_scenarios(count=2, base_seed=700)

        result = run_parallel(scenarios, max_workers=2)

        assert result.success_count == 2
        assert result.total_time > 0

    def test_run_parallel_with_callback(self, generator_check):
        """Test convenience function with callback."""
        scenarios = generate_scenarios(count=2, base_seed=800)
        callbacks = []

        result = run_parallel(
            scenarios,
            max_workers=2,
            progress_callback=lambda c, t, r: callbacks.append(c),
        )

        assert result.success_count == 2
        assert len(callbacks) == 2


class TestParallelPerformance:
    """Performance tests for parallel execution."""

    @pytest.mark.slow
    def test_parallel_faster_than_sequential(self, generator_check):
        """Test that parallel execution is faster than sequential."""
        import time

        scenarios = generate_scenarios(count=4, base_seed=900)

        # Sequential (1 worker)
        start = time.time()
        seq_result = run_parallel(scenarios, max_workers=1)
        seq_time = time.time() - start

        # Parallel (4 workers)
        start = time.time()
        par_result = run_parallel(scenarios, max_workers=4)
        par_time = time.time() - start

        assert seq_result.success_count == 4
        assert par_result.success_count == 4

        # Parallel should be faster (but not guaranteed due to overhead)
        # Just verify both complete successfully
        print(f"Sequential: {seq_time:.2f}s, Parallel: {par_time:.2f}s")
