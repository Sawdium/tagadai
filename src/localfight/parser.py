"""
Output parser for fight results.

Extracts structured data from generator output for analysis
and ML training.
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class ActionType(IntEnum):
    """Action types from the generator output."""

    START_FIGHT = 0
    DEATH = 5
    NEW_TURN = 6
    LEEK_TURN = 7
    END_TURN = 8
    MOVE_TO = 10
    SET_WEAPON = 13
    USE_WEAPON = 16
    USE_CHIP = 17
    LIFE_LOST = 101
    LIFE_GAIN = 103
    SAY = 203
    AI_ERROR = 1002


@dataclass
class EntityState:
    """State of an entity at a point in time."""

    entity_id: int
    cell: int
    hp: int
    max_hp: int
    tp: int
    mp: int


@dataclass
class TurnAction:
    """A single action taken during a turn."""

    action_type: ActionType
    entity_id: Optional[int] = None
    target_cell: Optional[int] = None
    damage: Optional[int] = None
    path: Optional[list[int]] = None
    success: Optional[bool] = None


@dataclass
class TurnRecord:
    """Record of a single turn in the fight."""

    turn_number: int
    entity_id: int
    start_tp: int
    start_mp: int
    end_tp: int
    end_mp: int
    actions: list[TurnAction] = field(default_factory=list)
    damage_dealt: int = 0
    damage_taken: int = 0
    cells_moved: int = 0


@dataclass
class FightResult:
    """Parsed result of a fight."""

    # Outcome
    winner: int  # 0=team1, 1=team2, -1=draw
    duration: int  # Number of turns

    # Timing (nanoseconds)
    analyze_time: int
    compilation_time: int
    execution_time: int

    # Entity info
    entities: list[dict]

    # Turn-by-turn records
    turns: list[TurnRecord]

    # Raw data
    raw_actions: list[list]

    # Seed for reproducibility (if available)
    seed: Optional[int] = None

    @property
    def team1_won(self) -> bool:
        return self.winner == 0

    @property
    def team2_won(self) -> bool:
        return self.winner == 1

    @property
    def is_draw(self) -> bool:
        return self.winner == -1


def parse_fight_result(result: dict) -> FightResult:
    """
    Parse raw generator output into structured FightResult.

    Args:
        result: Raw JSON dict from generator

    Returns:
        Structured FightResult
    """
    fight = result.get("fight", {})
    raw_actions = fight.get("actions", [])

    # Parse turns from action log
    turns = _parse_turns(raw_actions)

    return FightResult(
        winner=result.get("winner", -1),
        duration=result.get("duration", 0),
        analyze_time=result.get("analyze_time", 0),
        compilation_time=result.get("compilation_time", 0),
        execution_time=result.get("execution_time", 0),
        entities=fight.get("leeks", []),
        turns=turns,
        raw_actions=raw_actions,
        seed=result.get("random_seed"),
    )


def _parse_turns(actions: list[list]) -> list[TurnRecord]:
    """Parse action log into turn records."""
    turns = []
    current_turn: Optional[TurnRecord] = None
    turn_number = 1

    for action in actions:
        if not action:
            continue

        action_type = action[0]

        if action_type == ActionType.NEW_TURN:
            turn_number = action[1] if len(action) > 1 else turn_number + 1

        elif action_type == ActionType.LEEK_TURN:
            # Start of entity's turn
            entity_id = action[1] if len(action) > 1 else 0
            current_turn = TurnRecord(
                turn_number=turn_number,
                entity_id=entity_id,
                start_tp=10,  # Default, updated by END_TURN
                start_mp=3,
                end_tp=10,
                end_mp=3,
                actions=[],
            )

        elif action_type == ActionType.END_TURN:
            # End of entity's turn
            if current_turn is not None:
                if len(action) > 2:
                    current_turn.end_tp = action[2]
                if len(action) > 3:
                    current_turn.end_mp = action[3]
                turns.append(current_turn)
                current_turn = None

        elif action_type == ActionType.MOVE_TO:
            if current_turn is not None:
                path = action[3] if len(action) > 3 else []
                current_turn.actions.append(
                    TurnAction(
                        action_type=ActionType.MOVE_TO,
                        entity_id=action[1] if len(action) > 1 else None,
                        target_cell=action[2] if len(action) > 2 else None,
                        path=path,
                    )
                )
                current_turn.cells_moved += len(path)

        elif action_type == ActionType.USE_WEAPON:
            if current_turn is not None:
                current_turn.actions.append(
                    TurnAction(
                        action_type=ActionType.USE_WEAPON,
                        target_cell=action[1] if len(action) > 1 else None,
                        success=action[2] == 1 if len(action) > 2 else None,
                    )
                )

        elif action_type == ActionType.LIFE_LOST:
            if current_turn is not None and len(action) > 2:
                entity_id = action[1]
                damage = action[2]
                # Check if it's damage dealt or taken
                if entity_id != current_turn.entity_id:
                    current_turn.damage_dealt += damage
                else:
                    current_turn.damage_taken += damage

    return turns


@dataclass
class TrainingExample:
    """A single training example for ML."""

    # State before action
    my_hp: int
    my_cell: int
    my_tp: int
    my_mp: int
    enemy_hp: int
    enemy_cell: int
    distance: int
    turn_number: int

    # Outcome (label)
    won: bool


def extract_training_data(result: FightResult) -> list[TrainingExample]:
    """
    Extract ML training examples from a fight result.

    For Phase 8: Simple state → win prediction.

    Returns one example per turn showing the state at turn start
    and whether that entity eventually won.
    """
    examples = []

    # Determine winner entity IDs
    # winner=0 means team1, winner=1 means team2
    # entities have team field (1 or 2)
    winning_team = result.winner + 1 if result.winner >= 0 else -1

    # Track entity positions through the fight
    # This is simplified - we'd need full state tracking for real ML
    entity_cells: dict[int, int] = {}
    entity_hp: dict[int, int] = {}

    # Initialize from entity info
    for entity in result.entities:
        eid = entity.get("id", 0)
        entity_cells[eid] = entity.get("cellPos", 0)
        entity_hp[eid] = entity.get("life", 100)

    for turn in result.turns:
        entity_id = turn.entity_id

        # Find enemy (assumes 1v1 with entity IDs 0 and 1)
        enemy_id = 1 - entity_id

        # Get current state
        my_cell = entity_cells.get(entity_id, 0)
        enemy_cell = entity_cells.get(enemy_id, 0)

        # Simple distance (not exact cell distance)
        distance = abs(my_cell - enemy_cell)

        # Determine if this entity won
        entity_team = 1 if entity_id == 0 else 2  # Simplified
        won = entity_team == winning_team

        examples.append(
            TrainingExample(
                my_hp=entity_hp.get(entity_id, 100),
                my_cell=my_cell,
                my_tp=turn.start_tp,
                my_mp=turn.start_mp,
                enemy_hp=entity_hp.get(enemy_id, 100),
                enemy_cell=enemy_cell,
                distance=distance,
                turn_number=turn.turn_number,
                won=won,
            )
        )

        # Update state based on turn actions
        for action in turn.actions:
            if action.action_type == ActionType.MOVE_TO and action.target_cell:
                entity_cells[entity_id] = action.target_cell

        # Update HP based on damage
        entity_hp[entity_id] = max(0, entity_hp.get(entity_id, 100) - turn.damage_taken)
        entity_hp[enemy_id] = max(0, entity_hp.get(enemy_id, 100) - turn.damage_dealt)

    return examples
