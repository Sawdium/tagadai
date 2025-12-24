"""
Enhanced telemetry for fight analysis and ML training.

Provides rich per-round state snapshots and per-agent metrics
for detailed fight analysis and training signal extraction.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
import json
from pathlib import Path

from ..localfight.parser import FightResult, TurnRecord, ActionType


@dataclass
class EntitySnapshot:
    """Snapshot of an entity's state at a point in time."""

    entity_id: int
    name: str
    team: int
    cell: int
    hp: int
    max_hp: int
    tp: int
    mp: int
    is_alive: bool

    # Derived metrics
    hp_ratio: float = 0.0

    def __post_init__(self):
        self.hp_ratio = self.hp / max(self.max_hp, 1)


@dataclass
class ActionTrace:
    """Trace of a single action."""

    action_type: str
    entity_id: Optional[int]
    target_cell: Optional[int]
    damage: Optional[int]
    success: Optional[bool]
    path: Optional[List[int]] = None

    @classmethod
    def from_turn_action(cls, action) -> "ActionTrace":
        """Create from TurnAction."""
        return cls(
            action_type=action.action_type.name,
            entity_id=action.entity_id,
            target_cell=action.target_cell,
            damage=action.damage,
            success=action.success,
            path=action.path,
        )


@dataclass
class RoundSnapshot:
    """Complete snapshot of a single round in the fight."""

    round_number: int
    turn_number: int  # Overall turn counter
    active_entity_id: int

    # Entity states at start of turn
    entities: List[EntitySnapshot]

    # Actions taken this turn
    actions: List[ActionTrace]

    # Turn metrics
    damage_dealt: int = 0
    damage_taken: int = 0
    cells_moved: int = 0
    tp_spent: int = 0
    mp_spent: int = 0


@dataclass
class AgentMetrics:
    """Aggregated metrics for a single agent across the fight."""

    entity_id: int
    name: str
    team: int

    # Combat stats
    total_damage_dealt: int = 0
    total_damage_taken: int = 0
    total_healing: int = 0
    kills: int = 0

    # Resource usage
    total_tp_spent: int = 0
    total_mp_spent: int = 0
    total_tp_available: int = 0
    total_mp_available: int = 0

    # Movement
    total_cells_moved: int = 0

    # Turn count
    turns_taken: int = 0
    turns_survived: int = 0

    # Final state
    final_hp: int = 0
    max_hp: int = 0
    is_alive: bool = True

    # Efficiency metrics (calculated)
    @property
    def tp_efficiency(self) -> float:
        """Damage per TP spent."""
        if self.total_tp_spent == 0:
            return 0.0
        return self.total_damage_dealt / self.total_tp_spent

    @property
    def survival_ratio(self) -> float:
        """HP remaining as ratio of max."""
        if self.max_hp == 0:
            return 0.0
        return self.final_hp / self.max_hp

    @property
    def resource_utilization(self) -> float:
        """Fraction of available TP actually used."""
        if self.total_tp_available == 0:
            return 0.0
        return self.total_tp_spent / self.total_tp_available


@dataclass
class TimelineEvent:
    """A significant event in the fight timeline."""

    turn: int
    event_type: str  # "damage", "kill", "heal", "move", "effect"
    actor_id: int
    target_id: Optional[int] = None
    value: Optional[int] = None
    description: str = ""


@dataclass
class FightTelemetry:
    """Complete telemetry data for a fight."""

    # Metadata
    seed: Optional[int]
    winner: int  # 0=team1, 1=team2, -1=draw
    total_turns: int
    execution_time_ns: int

    # Per-round snapshots
    snapshots: List[RoundSnapshot]

    # Per-agent metrics
    agent_metrics: Dict[int, AgentMetrics]

    # Timeline
    events: List[TimelineEvent]

    # Raw data reference
    raw_actions: List[List]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "metadata": {
                "seed": self.seed,
                "winner": self.winner,
                "total_turns": self.total_turns,
                "execution_time_ns": self.execution_time_ns,
            },
            "snapshots": [asdict(s) for s in self.snapshots],
            "agent_metrics": {
                str(k): asdict(v) for k, v in self.agent_metrics.items()
            },
            "events": [asdict(e) for e in self.events],
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def save(self, path: Path) -> None:
        """Save telemetry to JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(self.to_json())

    def get_team_metrics(self, team: int) -> List[AgentMetrics]:
        """Get metrics for all agents on a team."""
        return [m for m in self.agent_metrics.values() if m.team == team]

    def get_winning_team_metrics(self) -> List[AgentMetrics]:
        """Get metrics for winning team agents."""
        if self.winner == -1:
            return []
        winning_team = self.winner + 1  # 0->1, 1->2
        return self.get_team_metrics(winning_team)


def extract_telemetry(result: FightResult) -> FightTelemetry:
    """
    Extract rich telemetry from a fight result.

    Args:
        result: Parsed fight result

    Returns:
        Complete telemetry data
    """
    # Initialize entity tracking
    entity_hp: Dict[int, int] = {}
    entity_max_hp: Dict[int, int] = {}
    entity_cells: Dict[int, int] = {}
    entity_names: Dict[int, str] = {}
    entity_teams: Dict[int, int] = {}

    # Initialize from entity info
    for entity in result.entities:
        eid = entity.get("id", 0)
        entity_hp[eid] = entity.get("life", 100)
        entity_max_hp[eid] = entity.get("life", 100)
        entity_cells[eid] = entity.get("cellPos", 0)
        entity_names[eid] = entity.get("name", f"Entity{eid}")
        entity_teams[eid] = entity.get("team", 1)

    # Initialize agent metrics
    agent_metrics = {
        eid: AgentMetrics(
            entity_id=eid,
            name=entity_names[eid],
            team=entity_teams[eid],
            max_hp=entity_max_hp[eid],
            final_hp=entity_hp[eid],
        )
        for eid in entity_hp
    }

    snapshots = []
    events = []
    current_round = 1

    for turn in result.turns:
        entity_id = turn.entity_id

        # Create entity snapshots at turn start
        entity_snapshots = [
            EntitySnapshot(
                entity_id=eid,
                name=entity_names.get(eid, ""),
                team=entity_teams.get(eid, 0),
                cell=entity_cells.get(eid, 0),
                hp=entity_hp.get(eid, 0),
                max_hp=entity_max_hp.get(eid, 100),
                tp=turn.start_tp if eid == entity_id else 10,
                mp=turn.start_mp if eid == entity_id else 3,
                is_alive=entity_hp.get(eid, 0) > 0,
            )
            for eid in entity_hp
        ]

        # Create action traces
        action_traces = [
            ActionTrace.from_turn_action(a)
            for a in turn.actions
        ]

        # Calculate TP/MP spent
        tp_spent = turn.start_tp - turn.end_tp
        mp_spent = turn.start_mp - turn.end_mp

        # Create snapshot
        snapshot = RoundSnapshot(
            round_number=current_round,
            turn_number=turn.turn_number,
            active_entity_id=entity_id,
            entities=entity_snapshots,
            actions=action_traces,
            damage_dealt=turn.damage_dealt,
            damage_taken=turn.damage_taken,
            cells_moved=turn.cells_moved,
            tp_spent=tp_spent,
            mp_spent=mp_spent,
        )
        snapshots.append(snapshot)

        # Update agent metrics
        if entity_id in agent_metrics:
            metrics = agent_metrics[entity_id]
            metrics.total_damage_dealt += turn.damage_dealt
            metrics.total_damage_taken += turn.damage_taken
            metrics.total_tp_spent += tp_spent
            metrics.total_mp_spent += mp_spent
            metrics.total_tp_available += turn.start_tp
            metrics.total_mp_available += turn.start_mp
            metrics.total_cells_moved += turn.cells_moved
            metrics.turns_taken += 1

        # Generate events
        if turn.damage_dealt > 0:
            # Find target (simplified - assumes 1v1)
            target_id = None
            for eid in entity_hp:
                if eid != entity_id:
                    target_id = eid
                    break

            events.append(TimelineEvent(
                turn=turn.turn_number,
                event_type="damage",
                actor_id=entity_id,
                target_id=target_id,
                value=turn.damage_dealt,
                description=f"{entity_names.get(entity_id, 'Unknown')} dealt {turn.damage_dealt} damage",
            ))

        if turn.cells_moved > 0:
            events.append(TimelineEvent(
                turn=turn.turn_number,
                event_type="move",
                actor_id=entity_id,
                value=turn.cells_moved,
                description=f"{entity_names.get(entity_id, 'Unknown')} moved {turn.cells_moved} cells",
            ))

        # Update entity state based on turn
        for action in turn.actions:
            if action.action_type == ActionType.MOVE_TO and action.target_cell:
                entity_cells[entity_id] = action.target_cell

        # Update HP from damage
        for eid in entity_hp:
            if eid == entity_id:
                entity_hp[eid] = max(0, entity_hp[eid] - turn.damage_taken)
            else:
                # Damage to others
                entity_hp[eid] = max(0, entity_hp[eid] - turn.damage_dealt)

        # Check for kills
        for eid in entity_hp:
            if entity_hp[eid] == 0 and agent_metrics[eid].is_alive:
                agent_metrics[eid].is_alive = False
                if eid != entity_id:
                    agent_metrics[entity_id].kills += 1
                    events.append(TimelineEvent(
                        turn=turn.turn_number,
                        event_type="kill",
                        actor_id=entity_id,
                        target_id=eid,
                        description=f"{entity_names.get(entity_id, 'Unknown')} killed {entity_names.get(eid, 'Unknown')}",
                    ))

        current_round = turn.turn_number

    # Finalize agent metrics
    for metrics in agent_metrics.values():
        metrics.final_hp = entity_hp.get(metrics.entity_id, 0)
        metrics.is_alive = metrics.final_hp > 0
        if metrics.is_alive:
            metrics.turns_survived = result.duration

    return FightTelemetry(
        seed=result.seed,
        winner=result.winner,
        total_turns=result.duration,
        execution_time_ns=result.execution_time,
        snapshots=snapshots,
        agent_metrics=agent_metrics,
        events=events,
        raw_actions=result.raw_actions,
    )


def telemetry_from_batch(results: List[FightResult]) -> List[FightTelemetry]:
    """
    Extract telemetry from a batch of fight results.

    Args:
        results: List of fight results

    Returns:
        List of telemetry data
    """
    return [extract_telemetry(r) for r in results]


def aggregate_metrics(telemetry_list: List[FightTelemetry]) -> dict:
    """
    Aggregate metrics across multiple fights.

    Args:
        telemetry_list: List of fight telemetry

    Returns:
        Aggregated statistics
    """
    if not telemetry_list:
        return {}

    total_fights = len(telemetry_list)
    team1_wins = sum(1 for t in telemetry_list if t.winner == 0)
    team2_wins = sum(1 for t in telemetry_list if t.winner == 1)
    draws = sum(1 for t in telemetry_list if t.winner == -1)

    total_damage = sum(
        sum(m.total_damage_dealt for m in t.agent_metrics.values())
        for t in telemetry_list
    )

    avg_turns = sum(t.total_turns for t in telemetry_list) / total_fights

    return {
        "total_fights": total_fights,
        "team1_wins": team1_wins,
        "team2_wins": team2_wins,
        "draws": draws,
        "team1_win_rate": team1_wins / total_fights,
        "team2_win_rate": team2_wins / total_fights,
        "draw_rate": draws / total_fights,
        "total_damage": total_damage,
        "avg_damage_per_fight": total_damage / total_fights,
        "avg_turns": avg_turns,
    }
