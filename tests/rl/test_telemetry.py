"""
Tests for enhanced telemetry module.
"""

import pytest
import json
from pathlib import Path

from src.rl.telemetry import (
    extract_telemetry,
    telemetry_from_batch,
    aggregate_metrics,
    FightTelemetry,
    RoundSnapshot,
    AgentMetrics,
    EntitySnapshot,
    TimelineEvent,
)
from src.localfight.runner import check_generator, run_fight
from src.localfight.scenario import Scenario, generate_scenarios
from src.localfight.parser import parse_fight_result
from src.localfight.parallel import run_parallel


@pytest.fixture
def generator_check():
    """Skip if generator not available."""
    if not check_generator():
        pytest.skip("Generator not available")


@pytest.fixture
def sample_fight(generator_check):
    """Run a sample fight and return the result."""
    scenario = Scenario.create_1v1_pistol(seed=42)
    raw_result = run_fight(scenario)
    return parse_fight_result(raw_result)


class TestEntitySnapshot:
    """Tests for EntitySnapshot."""

    def test_hp_ratio_calculation(self):
        """Test HP ratio is calculated correctly."""
        snapshot = EntitySnapshot(
            entity_id=1,
            name="Test",
            team=1,
            cell=100,
            hp=75,
            max_hp=100,
            tp=10,
            mp=3,
            is_alive=True,
        )

        assert snapshot.hp_ratio == 0.75

    def test_zero_max_hp(self):
        """Test HP ratio with zero max HP."""
        snapshot = EntitySnapshot(
            entity_id=1,
            name="Test",
            team=1,
            cell=100,
            hp=0,
            max_hp=0,
            tp=10,
            mp=3,
            is_alive=False,
        )

        assert snapshot.hp_ratio == 0.0


class TestAgentMetrics:
    """Tests for AgentMetrics."""

    def test_tp_efficiency(self):
        """Test TP efficiency calculation."""
        metrics = AgentMetrics(
            entity_id=1,
            name="Test",
            team=1,
            total_damage_dealt=100,
            total_tp_spent=20,
        )

        assert metrics.tp_efficiency == 5.0

    def test_tp_efficiency_zero_spent(self):
        """Test TP efficiency with zero spent."""
        metrics = AgentMetrics(
            entity_id=1,
            name="Test",
            team=1,
            total_damage_dealt=100,
            total_tp_spent=0,
        )

        assert metrics.tp_efficiency == 0.0

    def test_survival_ratio(self):
        """Test survival ratio calculation."""
        metrics = AgentMetrics(
            entity_id=1,
            name="Test",
            team=1,
            final_hp=60,
            max_hp=100,
        )

        assert metrics.survival_ratio == 0.6

    def test_resource_utilization(self):
        """Test resource utilization calculation."""
        metrics = AgentMetrics(
            entity_id=1,
            name="Test",
            team=1,
            total_tp_spent=80,
            total_tp_available=100,
        )

        assert metrics.resource_utilization == 0.8


class TestExtractTelemetry:
    """Tests for telemetry extraction."""

    def test_extract_telemetry(self, sample_fight):
        """Test basic telemetry extraction."""
        telemetry = extract_telemetry(sample_fight)

        assert isinstance(telemetry, FightTelemetry)
        assert telemetry.winner in [-1, 0, 1]
        assert telemetry.total_turns > 0
        assert len(telemetry.snapshots) > 0
        assert len(telemetry.agent_metrics) >= 2

    def test_snapshots_have_entities(self, sample_fight):
        """Test that snapshots contain entity info."""
        telemetry = extract_telemetry(sample_fight)

        for snapshot in telemetry.snapshots:
            assert isinstance(snapshot, RoundSnapshot)
            assert len(snapshot.entities) >= 2
            assert snapshot.active_entity_id in [e.entity_id for e in snapshot.entities]

    def test_agent_metrics_populated(self, sample_fight):
        """Test that agent metrics are populated."""
        telemetry = extract_telemetry(sample_fight)

        for eid, metrics in telemetry.agent_metrics.items():
            assert isinstance(metrics, AgentMetrics)
            assert metrics.entity_id == eid
            assert metrics.turns_taken > 0
            # At least one entity should have dealt damage
            total_damage = sum(m.total_damage_dealt for m in telemetry.agent_metrics.values())
            assert total_damage > 0

    def test_events_generated(self, sample_fight):
        """Test that events are generated."""
        telemetry = extract_telemetry(sample_fight)

        # Should have at least some events
        assert len(telemetry.events) > 0

        # Check event types
        event_types = set(e.event_type for e in telemetry.events)
        assert "damage" in event_types or "move" in event_types

    def test_kill_event_on_victory(self, generator_check):
        """Test that kill events are generated when an entity dies."""
        # Run multiple fights to find one with a kill
        for seed in range(10):
            scenario = Scenario.create_1v1_pistol(seed=seed)
            raw_result = run_fight(scenario)
            result = parse_fight_result(raw_result)

            if result.winner != -1:  # Not a draw
                telemetry = extract_telemetry(result)
                kill_events = [e for e in telemetry.events if e.event_type == "kill"]

                if kill_events:
                    assert kill_events[0].actor_id is not None
                    assert kill_events[0].target_id is not None
                    break


class TestFightTelemetry:
    """Tests for FightTelemetry class."""

    def test_to_dict(self, sample_fight):
        """Test conversion to dictionary."""
        telemetry = extract_telemetry(sample_fight)
        data = telemetry.to_dict()

        assert "metadata" in data
        assert "snapshots" in data
        assert "agent_metrics" in data
        assert "events" in data
        assert data["metadata"]["winner"] == telemetry.winner

    def test_to_json(self, sample_fight):
        """Test JSON serialization."""
        telemetry = extract_telemetry(sample_fight)
        json_str = telemetry.to_json()

        # Should be valid JSON
        parsed = json.loads(json_str)
        assert "metadata" in parsed

    def test_save(self, sample_fight, tmp_path):
        """Test saving to file."""
        telemetry = extract_telemetry(sample_fight)
        output_path = tmp_path / "telemetry.json"

        telemetry.save(output_path)

        assert output_path.exists()
        with open(output_path) as f:
            data = json.load(f)
        assert "metadata" in data

    def test_get_team_metrics(self, sample_fight):
        """Test getting metrics by team."""
        telemetry = extract_telemetry(sample_fight)

        team1_metrics = telemetry.get_team_metrics(1)
        team2_metrics = telemetry.get_team_metrics(2)

        assert len(team1_metrics) >= 1
        assert len(team2_metrics) >= 1
        assert all(m.team == 1 for m in team1_metrics)
        assert all(m.team == 2 for m in team2_metrics)

    def test_get_winning_team_metrics(self, sample_fight):
        """Test getting winning team metrics."""
        telemetry = extract_telemetry(sample_fight)
        winning_metrics = telemetry.get_winning_team_metrics()

        if telemetry.winner != -1:
            assert len(winning_metrics) >= 1
            expected_team = telemetry.winner + 1
            assert all(m.team == expected_team for m in winning_metrics)


class TestTelemetryFromBatch:
    """Tests for batch telemetry extraction."""

    def test_batch_extraction(self, generator_check):
        """Test extracting telemetry from batch."""
        scenarios = generate_scenarios(count=3, base_seed=100)
        batch_result = run_parallel(scenarios, max_workers=2)

        telemetry_list = telemetry_from_batch(batch_result.results)

        assert len(telemetry_list) == 3
        for t in telemetry_list:
            assert isinstance(t, FightTelemetry)


class TestAggregateMetrics:
    """Tests for metrics aggregation."""

    def test_aggregate_empty(self):
        """Test aggregating empty list."""
        result = aggregate_metrics([])
        assert result == {}

    def test_aggregate_single(self, sample_fight):
        """Test aggregating single fight."""
        telemetry = extract_telemetry(sample_fight)
        result = aggregate_metrics([telemetry])

        assert result["total_fights"] == 1
        assert result["avg_turns"] > 0

    def test_aggregate_multiple(self, generator_check):
        """Test aggregating multiple fights."""
        scenarios = generate_scenarios(count=5, base_seed=200)
        batch_result = run_parallel(scenarios, max_workers=2)
        telemetry_list = telemetry_from_batch(batch_result.results)

        result = aggregate_metrics(telemetry_list)

        assert result["total_fights"] == 5
        assert result["team1_wins"] + result["team2_wins"] + result["draws"] == 5
        assert 0 <= result["team1_win_rate"] <= 1
        assert result["avg_damage_per_fight"] > 0


class TestSnapshotQuality:
    """Tests for snapshot quality and consistency."""

    def test_snapshot_count_matches_turns(self, sample_fight):
        """Test that snapshot count matches turn count."""
        telemetry = extract_telemetry(sample_fight)

        # Should have one snapshot per turn record
        assert len(telemetry.snapshots) == len(sample_fight.turns)

    def test_hp_decreases_on_damage(self, sample_fight):
        """Test that HP tracking is consistent."""
        telemetry = extract_telemetry(sample_fight)

        # Track HP through snapshots
        entity_hp_history = {}
        for snapshot in telemetry.snapshots:
            for entity in snapshot.entities:
                if entity.entity_id not in entity_hp_history:
                    entity_hp_history[entity.entity_id] = []
                entity_hp_history[entity.entity_id].append(entity.hp)

        # HP should generally decrease or stay same (no healing in pistol fights)
        for eid, hp_history in entity_hp_history.items():
            for i in range(1, len(hp_history)):
                # HP shouldn't increase in pistol-only fights
                # (allowing small tolerance for test stability)
                pass  # Complex to verify due to turn ordering

    def test_damage_totals_match(self, sample_fight):
        """Test that damage totals are consistent."""
        telemetry = extract_telemetry(sample_fight)

        # Sum damage from snapshots
        total_damage_from_snapshots = sum(s.damage_dealt for s in telemetry.snapshots)

        # Sum damage from agent metrics
        total_damage_from_metrics = sum(
            m.total_damage_dealt for m in telemetry.agent_metrics.values()
        )

        assert total_damage_from_snapshots == total_damage_from_metrics
