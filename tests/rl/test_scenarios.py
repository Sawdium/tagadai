"""
Tests for YAML scenario configuration.
"""

import pytest
from pathlib import Path

from src.rl.scenarios import (
    load_yaml,
    load_yaml_string,
    parse_bot_config,
    parse_scenario_config,
    parse_batch_config,
    BotConfig,
    ScenarioConfig,
    BatchConfig,
    ScenarioRunner,
    run_yaml,
)
from src.localfight.runner import check_generator


@pytest.fixture
def generator_check():
    """Skip if generator not available."""
    if not check_generator():
        pytest.skip("Generator not available")


@pytest.fixture
def sample_yaml():
    """Sample YAML configuration for testing."""
    return """
log_dir: "test_logs"

scenarios:
  - name: "test_scenario"
    description: "A test scenario"
    repetitions: 2
    seed: 42
    bots:
      - name: "Bot1"
        path: "test/ai/simple.leek"
        team: 1
        weapons: ["pistol"]
      - name: "Bot2"
        path: "test/ai/simple.leek"
        team: 2
        weapons: ["pistol"]
    config:
      max_turns: 32
"""


class TestBotConfig:
    """Tests for BotConfig parsing."""

    def test_parse_minimal(self):
        """Test parsing minimal bot config."""
        data = {"name": "TestBot", "team": 1}
        bot = parse_bot_config(data)

        assert bot.name == "TestBot"
        assert bot.team == 1
        assert bot.level == 1
        assert bot.life == 100
        assert bot.weapons == ["pistol"]

    def test_parse_full(self):
        """Test parsing full bot config."""
        data = {
            "name": "FullBot",
            "path": "custom/ai.leek",
            "team": 2,
            "level": 50,
            "life": 300,
            "strength": 100,
            "agility": 50,
            "tp": 15,
            "mp": 6,
            "weapons": ["magnum", "laser"],
            "metadata": {"role": "tank"},
        }
        bot = parse_bot_config(data)

        assert bot.name == "FullBot"
        assert bot.ai_path == "custom/ai.leek"
        assert bot.team == 2
        assert bot.level == 50
        assert bot.life == 300
        assert bot.strength == 100
        assert bot.weapons == ["magnum", "laser"]
        assert bot.metadata == {"role": "tank"}

    def test_to_leek_config(self):
        """Test conversion to LeekConfig."""
        bot = BotConfig(
            name="TestLeek",
            ai_path="test/ai.leek",
            team=1,
            level=10,
            life=150,
        )
        leek = bot.to_leek_config(entity_id=1, farmer_id=1)

        assert leek.name == "TestLeek"
        assert leek.ai == "test/ai.leek"
        assert leek.team == 1
        assert leek.level == 10
        assert leek.life == 150


class TestScenarioConfig:
    """Tests for ScenarioConfig parsing."""

    def test_parse_scenario(self):
        """Test parsing scenario config."""
        data = {
            "name": "test",
            "description": "Test scenario",
            "repetitions": 3,
            "seed": 100,
            "bots": [
                {"name": "A", "team": 1},
                {"name": "B", "team": 2},
            ],
            "config": {"max_turns": 48},
        }
        config = parse_scenario_config(data)

        assert config.name == "test"
        assert config.description == "Test scenario"
        assert config.repetitions == 3
        assert config.seed == 100
        assert len(config.bots) == 2
        assert config.max_turns == 48

    def test_generate_scenarios(self):
        """Test generating scenarios from config."""
        config = ScenarioConfig(
            name="test",
            repetitions=3,
            seed=42,
            bots=[
                BotConfig(name="A", team=1),
                BotConfig(name="B", team=2),
            ],
        )

        scenarios = config.generate_scenarios()

        assert len(scenarios) == 3
        # Seeds should be 42, 43, 44
        assert scenarios[0].random_seed == 42
        assert scenarios[1].random_seed == 43
        assert scenarios[2].random_seed == 44

    def test_generate_scenarios_no_seed(self):
        """Test generating scenarios without seed."""
        config = ScenarioConfig(
            name="test",
            repetitions=2,
            seed=None,
            bots=[
                BotConfig(name="A", team=1),
                BotConfig(name="B", team=2),
            ],
        )

        scenarios = config.generate_scenarios()

        assert len(scenarios) == 2
        assert scenarios[0].random_seed is None
        assert scenarios[1].random_seed is None

    def test_missing_team_raises_error(self):
        """Test that missing team raises error."""
        config = ScenarioConfig(
            name="test",
            bots=[BotConfig(name="A", team=1)],  # Only team 1
        )

        with pytest.raises(ValueError, match="must have bots on both teams"):
            config.generate_scenarios()


class TestBatchConfig:
    """Tests for BatchConfig parsing."""

    def test_parse_batch(self, sample_yaml):
        """Test parsing batch config from YAML."""
        config = load_yaml_string(sample_yaml)

        assert config.log_dir == "test_logs"
        assert len(config.scenarios) == 1
        assert config.scenarios[0].name == "test_scenario"

    def test_get_all_scenarios(self, sample_yaml):
        """Test getting all scenarios."""
        config = load_yaml_string(sample_yaml)
        scenarios = config.get_all_scenarios()

        # 1 scenario with 2 repetitions
        assert len(scenarios) == 2


class TestLoadYaml:
    """Tests for YAML loading functions."""

    def test_load_yaml_string(self, sample_yaml):
        """Test loading from string."""
        config = load_yaml_string(sample_yaml)

        assert isinstance(config, BatchConfig)
        assert len(config.scenarios) == 1

    def test_load_yaml_file(self, tmp_path, sample_yaml):
        """Test loading from file."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text(sample_yaml)

        config = load_yaml(yaml_file)

        assert isinstance(config, BatchConfig)
        assert len(config.scenarios) == 1

    def test_load_sample_scenarios(self):
        """Test loading the sample scenarios file."""
        sample_path = Path(__file__).parent.parent.parent / "scenarios" / "sample_scenarios.yml"
        if not sample_path.exists():
            pytest.skip("Sample scenarios file not found")

        config = load_yaml(sample_path)

        assert isinstance(config, BatchConfig)
        assert len(config.scenarios) >= 1


class TestScenarioRunner:
    """Tests for ScenarioRunner."""

    def test_runner_creation(self, sample_yaml):
        """Test creating a runner."""
        config = load_yaml_string(sample_yaml)
        runner = ScenarioRunner(config)

        assert runner.config == config
        assert runner.runner is not None

    def test_run_scenarios(self, generator_check, sample_yaml):
        """Test running scenarios."""
        config = load_yaml_string(sample_yaml)
        runner = ScenarioRunner(config)

        results = runner.run()

        assert len(results) == 1
        assert results[0].scenario_name == "test_scenario"
        assert results[0].batch_result.success_count == 2

    def test_run_flat(self, generator_check, sample_yaml):
        """Test running all scenarios as flat batch."""
        config = load_yaml_string(sample_yaml)
        runner = ScenarioRunner(config)

        result = runner.run_flat()

        assert result.success_count == 2

    def test_run_with_progress(self, generator_check, sample_yaml):
        """Test running with progress callback."""
        config = load_yaml_string(sample_yaml)
        callbacks = []
        runner = ScenarioRunner(
            config,
            progress_callback=lambda c, t, r: callbacks.append((c, t)),
        )

        runner.run()

        assert len(callbacks) == 2  # 2 repetitions


class TestRunYaml:
    """Tests for run_yaml convenience function."""

    def test_run_yaml(self, generator_check, tmp_path, sample_yaml):
        """Test running YAML file."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text(sample_yaml)

        results = run_yaml(yaml_file)

        assert len(results) == 1
        assert results[0].batch_result.success_count == 2


class TestSampleFiles:
    """Tests for sample scenario files."""

    def test_sample_scenarios_parseable(self):
        """Test that sample_scenarios.yml is parseable."""
        sample_path = Path(__file__).parent.parent.parent / "scenarios" / "sample_scenarios.yml"
        if not sample_path.exists():
            pytest.skip("Sample file not found")

        config = load_yaml(sample_path)

        assert len(config.scenarios) >= 1
        for scenario in config.scenarios:
            assert scenario.name
            assert len(scenario.bots) >= 2

    def test_training_batch_parseable(self):
        """Test that training_batch.yml is parseable."""
        training_path = Path(__file__).parent.parent.parent / "scenarios" / "training_batch.yml"
        if not training_path.exists():
            pytest.skip("Training batch file not found")

        config = load_yaml(training_path)

        assert len(config.scenarios) >= 1
        assert config.max_workers == 4

    def test_run_sample_scenarios(self, generator_check):
        """Test running sample scenarios file."""
        sample_path = Path(__file__).parent.parent.parent / "scenarios" / "sample_scenarios.yml"
        if not sample_path.exists():
            pytest.skip("Sample file not found")

        results = run_yaml(sample_path)

        assert len(results) >= 1
        for result in results:
            assert result.batch_result.success_count > 0
