"""
Parallel fight execution for faster data generation.

Uses ThreadPoolExecutor to run multiple fights concurrently,
maximizing CPU utilization for batch scenarios.
"""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Optional, List, Any
import time

from .runner import run_fight, RunnerError
from .scenario import Scenario
from .parser import parse_fight_result, FightResult


@dataclass
class BatchResult:
    """Result of a batch fight execution."""

    results: List[FightResult]
    errors: List[tuple[int, str]]  # (index, error message)
    total_time: float  # seconds
    fights_per_second: float

    @property
    def success_count(self) -> int:
        return len(self.results)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def total_count(self) -> int:
        return self.success_count + self.error_count

    @property
    def success_rate(self) -> float:
        if self.total_count == 0:
            return 0.0
        return self.success_count / self.total_count


@dataclass
class FightTask:
    """A single fight task for the executor."""

    index: int
    scenario: Scenario
    timeout: float = 30.0
    nocache: bool = True


class ParallelRunner:
    """
    Runs multiple fights in parallel using ThreadPoolExecutor.

    Automatically scales to available CPU cores for maximum throughput.
    """

    def __init__(
        self,
        max_workers: Optional[int] = None,
        timeout: float = 30.0,
        nocache: bool = True,
    ):
        """
        Initialize the parallel runner.

        Args:
            max_workers: Maximum concurrent fights (default: CPU count)
            timeout: Timeout per fight in seconds
            nocache: Disable AI caching (recommended for varied scenarios)
        """
        self.max_workers = max_workers or max(1, os.cpu_count() or 4)
        self.timeout = timeout
        self.nocache = nocache

    def run_batch(
        self,
        scenarios: List[Scenario],
        progress_callback: Optional[Callable[[int, int, Optional[FightResult]], None]] = None,
    ) -> BatchResult:
        """
        Run a batch of fight scenarios in parallel.

        Args:
            scenarios: List of scenarios to execute
            progress_callback: Optional callback(completed, total, result) for progress updates

        Returns:
            BatchResult with all results and errors
        """
        if not scenarios:
            return BatchResult(
                results=[],
                errors=[],
                total_time=0.0,
                fights_per_second=0.0,
            )

        start_time = time.time()
        results: List[Optional[FightResult]] = [None] * len(scenarios)
        errors: List[tuple[int, str]] = []
        completed = 0

        # Create tasks
        tasks = [
            FightTask(
                index=i,
                scenario=scenario,
                timeout=self.timeout,
                nocache=self.nocache,
            )
            for i, scenario in enumerate(scenarios)
        ]

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_task = {
                executor.submit(self._execute_task, task): task
                for task in tasks
            }

            # Collect results as they complete
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                completed += 1

                try:
                    result = future.result()
                    results[task.index] = result

                    if progress_callback:
                        progress_callback(completed, len(scenarios), result)

                except Exception as e:
                    errors.append((task.index, str(e)))

                    if progress_callback:
                        progress_callback(completed, len(scenarios), None)

        total_time = time.time() - start_time
        successful_results = [r for r in results if r is not None]

        return BatchResult(
            results=successful_results,
            errors=errors,
            total_time=total_time,
            fights_per_second=len(scenarios) / total_time if total_time > 0 else 0.0,
        )

    def run_single(self, scenario: Scenario) -> FightResult:
        """
        Run a single fight (convenience method).

        Args:
            scenario: The scenario to execute

        Returns:
            Parsed fight result

        Raises:
            RunnerError: If the fight fails
        """
        raw_result = run_fight(
            scenario,
            timeout=self.timeout,
            nocache=self.nocache,
        )
        return parse_fight_result(raw_result)

    def _execute_task(self, task: FightTask) -> FightResult:
        """Execute a single fight task."""
        raw_result = run_fight(
            task.scenario,
            timeout=task.timeout,
            nocache=task.nocache,
        )
        return parse_fight_result(raw_result)


class BatchBuilder:
    """
    Builder for creating batches of fight scenarios.

    Provides a fluent interface for configuring batch runs.
    """

    def __init__(self):
        self.scenarios: List[Scenario] = []
        self._max_workers: Optional[int] = None
        self._timeout: float = 30.0
        self._nocache: bool = True
        self._progress_callback: Optional[Callable] = None

    def add_scenario(self, scenario: Scenario) -> "BatchBuilder":
        """Add a single scenario to the batch."""
        self.scenarios.append(scenario)
        return self

    def add_scenarios(self, scenarios: List[Scenario]) -> "BatchBuilder":
        """Add multiple scenarios to the batch."""
        self.scenarios.extend(scenarios)
        return self

    def with_workers(self, max_workers: int) -> "BatchBuilder":
        """Set maximum parallel workers."""
        self._max_workers = max_workers
        return self

    def with_timeout(self, timeout: float) -> "BatchBuilder":
        """Set per-fight timeout in seconds."""
        self._timeout = timeout
        return self

    def with_cache(self, use_cache: bool = True) -> "BatchBuilder":
        """Enable or disable AI caching."""
        self._nocache = not use_cache
        return self

    def with_progress(
        self,
        callback: Callable[[int, int, Optional[FightResult]], None],
    ) -> "BatchBuilder":
        """Set progress callback."""
        self._progress_callback = callback
        return self

    def run(self) -> BatchResult:
        """Execute the batch and return results."""
        runner = ParallelRunner(
            max_workers=self._max_workers,
            timeout=self._timeout,
            nocache=self._nocache,
        )
        return runner.run_batch(self.scenarios, self._progress_callback)


def run_parallel(
    scenarios: List[Scenario],
    max_workers: Optional[int] = None,
    timeout: float = 30.0,
    progress_callback: Optional[Callable[[int, int, Optional[FightResult]], None]] = None,
) -> BatchResult:
    """
    Convenience function to run fights in parallel.

    Args:
        scenarios: List of scenarios to execute
        max_workers: Maximum concurrent fights (default: CPU count)
        timeout: Timeout per fight in seconds
        progress_callback: Optional progress callback

    Returns:
        BatchResult with all results
    """
    runner = ParallelRunner(max_workers=max_workers, timeout=timeout)
    return runner.run_batch(scenarios, progress_callback)
