"""
Local fight system for ML training.

Uses the LeekWars Java generator to run fights locally
and collect training data for neural networks.
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
