"""
YAML-based scenario configuration for batch experiments.

Provides declarative scenario definitions for reproducible
and configurable RL training runs.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, List, Union
import yaml

from ..localfight.scenario import (
    Scenario,
    LeekConfig,
    MapConfig,
    ITEM_PISTOL,
    ITEM_MACHINE_GUN,
    ITEM_SHOTGUN,
    ITEM_LASER,
    ITEM_MAGNUM,
)
from ..localfight.parallel import ParallelRunner, BatchResult


# Weapon name to item ID mapping
WEAPON_ITEMS = {
    "pistol": ITEM_PISTOL,
    "machine_gun": ITEM_MACHINE_GUN,
    "shotgun": ITEM_SHOTGUN,
    "laser": ITEM_LASER,
    "magnum": ITEM_MAGNUM,
}


@dataclass
class BotConfig:
    """Configuration for a single bot in a scenario."""

    name: str = "Bot"
    ai_path: str = "test/ai/simple.leek"
    team: int = 1

    # Stats
    level: int = 1
    life: int = 100
    strength: int = 0
    agility: int = 0
    resistance: int = 0
    tp: int = 10
    mp: int = 3

    # Equipment
    weapons: List[str] = field(default_factory=lambda: ["pistol"])

    # Position (optional)
    cell: Optional[int] = None

    # Metadata for analysis
    metadata: dict = field(default_factory=dict)

    def to_leek_config(self, entity_id: int, farmer_id: int) -> LeekConfig:
        """Convert to LeekConfig for the generator."""
        weapon_items = [
            WEAPON_ITEMS.get(w.lower(), ITEM_PISTOL)
            for w in self.weapons
        ]

        return LeekConfig(
            id=entity_id,
            name=self.name,
            farmer=farmer_id,
            team=self.team,
            ai=self.ai_path,
            level=self.level,
            life=self.life,
            strength=self.strength,
            agility=self.agility,
            resistance=self.resistance,
            tp=self.tp,
            mp=self.mp,
            weapons=weapon_items,
            cell=self.cell,
        )


@dataclass
class ScenarioConfig:
    """Configuration for a single scenario."""

    name: str
    description: str = ""
    repetitions: int = 1
    seed: Optional[int] = None

    # Bots (team 1 and team 2)
    bots: List[BotConfig] = field(default_factory=list)

    # Fight config
    max_turns: int = 64
    map_width: int = 17
    map_height: int = 17

    def generate_scenarios(self) -> List[Scenario]:
        """Generate Scenario objects for this config."""
        scenarios = []

        # Split bots by team
        team1_bots = [b for b in self.bots if b.team == 1]
        team2_bots = [b for b in self.bots if b.team == 2]

        if not team1_bots or not team2_bots:
            raise ValueError(f"Scenario '{self.name}' must have bots on both teams")

        for rep in range(self.repetitions):
            # Generate seed for this repetition
            rep_seed = None
            if self.seed is not None:
                rep_seed = self.seed + rep

            # Create leek configs
            team1 = []
            team2 = []
            entity_id = 1

            for bot in team1_bots:
                team1.append(bot.to_leek_config(entity_id, farmer_id=1))
                entity_id += 1

            for bot in team2_bots:
                team2.append(bot.to_leek_config(entity_id, farmer_id=2))
                entity_id += 1

            # Create map
            map_config = MapConfig(
                width=self.map_width,
                height=self.map_height,
            )

            scenarios.append(Scenario(
                team1=team1,
                team2=team2,
                map=map_config,
                random_seed=rep_seed,
                max_turns=self.max_turns,
            ))

        return scenarios


@dataclass
class BatchConfig:
    """Configuration for a batch of scenarios."""

    log_dir: str = "logs"
    scenarios: List[ScenarioConfig] = field(default_factory=list)

    # Execution settings
    max_workers: Optional[int] = None
    timeout: float = 30.0

    def get_all_scenarios(self) -> List[Scenario]:
        """Generate all scenarios from all configs."""
        all_scenarios = []
        for config in self.scenarios:
            all_scenarios.extend(config.generate_scenarios())
        return all_scenarios


def parse_bot_config(data: dict) -> BotConfig:
    """Parse a bot configuration from YAML data."""
    return BotConfig(
        name=data.get("name", "Bot"),
        ai_path=data.get("path", data.get("ai_path", "test/ai/simple.leek")),
        team=data.get("team", 1),
        level=data.get("level", 1),
        life=data.get("life", 100),
        strength=data.get("strength", 0),
        agility=data.get("agility", 0),
        resistance=data.get("resistance", 0),
        tp=data.get("tp", 10),
        mp=data.get("mp", 3),
        weapons=data.get("weapons", ["pistol"]),
        cell=data.get("cell"),
        metadata=data.get("metadata", {}),
    )


def parse_scenario_config(data: dict) -> ScenarioConfig:
    """Parse a scenario configuration from YAML data."""
    bots = [parse_bot_config(b) for b in data.get("bots", [])]

    # Handle config sub-object
    config = data.get("config", {})

    return ScenarioConfig(
        name=data.get("name", "unnamed"),
        description=data.get("description", ""),
        repetitions=data.get("repetitions", 1),
        seed=data.get("seed"),
        bots=bots,
        max_turns=config.get("max_turns", data.get("max_turns", 64)),
        map_width=config.get("map_width", data.get("map_width", 17)),
        map_height=config.get("map_height", data.get("map_height", 17)),
    )


def parse_batch_config(data: dict) -> BatchConfig:
    """Parse a batch configuration from YAML data."""
    scenarios = [
        parse_scenario_config(s)
        for s in data.get("scenarios", [])
    ]

    return BatchConfig(
        log_dir=data.get("log_dir", "logs"),
        scenarios=scenarios,
        max_workers=data.get("max_workers"),
        timeout=data.get("timeout", 30.0),
    )


def load_yaml(path: Union[str, Path]) -> BatchConfig:
    """
    Load a batch configuration from a YAML file.

    Args:
        path: Path to the YAML file

    Returns:
        Parsed BatchConfig
    """
    path = Path(path)

    with open(path, "r") as f:
        data = yaml.safe_load(f)

    return parse_batch_config(data)


def load_yaml_string(yaml_string: str) -> BatchConfig:
    """
    Load a batch configuration from a YAML string.

    Args:
        yaml_string: YAML content as string

    Returns:
        Parsed BatchConfig
    """
    data = yaml.safe_load(yaml_string)
    return parse_batch_config(data)


@dataclass
class ScenarioResult:
    """Result of running a scenario batch."""

    scenario_name: str
    batch_result: BatchResult
    config: ScenarioConfig


class ScenarioRunner:
    """
    Runs scenarios defined in YAML configuration.

    Handles parallel execution and result aggregation.
    """

    def __init__(
        self,
        config: BatchConfig,
        progress_callback: Optional[callable] = None,
    ):
        """
        Initialize the scenario runner.

        Args:
            config: Batch configuration
            progress_callback: Optional callback for progress updates
        """
        self.config = config
        self.progress_callback = progress_callback
        self.runner = ParallelRunner(
            max_workers=config.max_workers,
            timeout=config.timeout,
        )

    def run(self) -> List[ScenarioResult]:
        """
        Run all scenarios in the configuration.

        Returns:
            List of results for each scenario
        """
        results = []

        for scenario_config in self.config.scenarios:
            scenarios = scenario_config.generate_scenarios()

            batch_result = self.runner.run_batch(
                scenarios,
                progress_callback=self.progress_callback,
            )

            results.append(ScenarioResult(
                scenario_name=scenario_config.name,
                batch_result=batch_result,
                config=scenario_config,
            ))

        return results

    def run_flat(self) -> BatchResult:
        """
        Run all scenarios as a single flat batch.

        Returns:
            Combined BatchResult for all scenarios
        """
        all_scenarios = self.config.get_all_scenarios()

        return self.runner.run_batch(
            all_scenarios,
            progress_callback=self.progress_callback,
        )


def run_yaml(
    path: Union[str, Path],
    progress_callback: Optional[callable] = None,
) -> List[ScenarioResult]:
    """
    Convenience function to run scenarios from a YAML file.

    Args:
        path: Path to YAML file
        progress_callback: Optional progress callback

    Returns:
        List of scenario results
    """
    config = load_yaml(path)
    runner = ScenarioRunner(config, progress_callback)
    return runner.run()
