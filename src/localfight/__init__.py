"""
Offline fight execution via the LeekWars Java generator.

Runs fights locally with no fight cost and no rate limit: smoke-testing
tagadalive after a refactor, and bulk data generation.

`python -m src.tools.localfight` is the CLI on top of this. The generator's
quirks (weapon vs item ids, 0-based winner, op budget from `cores`, AI path
resolution) are documented in src/localfight/README.md.
"""

from .scenario import LeekConfig, Scenario, MapConfig, generate_scenarios
from .runner import run_fight, check_generator
from .parser import parse_fight_result, extract_training_data, FightResult, TrainingExample
from .parallel import ParallelRunner, BatchResult, BatchBuilder, run_parallel

__all__ = [
    "LeekConfig",
    "Scenario",
    "MapConfig",
    "generate_scenarios",
    "run_fight",
    "check_generator",
    "parse_fight_result",
    "extract_training_data",
    "FightResult",
    "TrainingExample",
    "ParallelRunner",
    "BatchResult",
    "BatchBuilder",
    "run_parallel",
]
