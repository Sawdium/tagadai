"""
Reinforcement Learning environment for LeekWars.

Provides a Gymnasium-compatible environment for training RL agents
on LeekWars combat scenarios.
"""

from .environment import LeekWarsEnv
from .rewards import RewardCalculator, RewardConfig
from .spaces import ObservationSpace, ActionSpace
from .scenarios import (
    load_yaml,
    load_yaml_string,
    run_yaml,
    ScenarioRunner,
    ScenarioConfig,
    BatchConfig,
    BotConfig,
)
from .telemetry import (
    extract_telemetry,
    telemetry_from_batch,
    aggregate_metrics,
    FightTelemetry,
    RoundSnapshot,
    AgentMetrics,
    EntitySnapshot,
    TimelineEvent,
)

__all__ = [
    "LeekWarsEnv",
    "RewardCalculator",
    "RewardConfig",
    "ObservationSpace",
    "ActionSpace",
    "load_yaml",
    "load_yaml_string",
    "run_yaml",
    "ScenarioRunner",
    "ScenarioConfig",
    "BatchConfig",
    "BotConfig",
    "extract_telemetry",
    "telemetry_from_batch",
    "aggregate_metrics",
    "FightTelemetry",
    "RoundSnapshot",
    "AgentMetrics",
    "EntitySnapshot",
    "TimelineEvent",
]
