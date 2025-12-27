"""
Fight replay for extracting training data.

Replays fight action logs to:
1. Reconstruct state at each decision point
2. Identify the action that was taken
3. Generate (state, action, label) training examples

Training approach:
- Positive examples: actions that were taken (label=1)
- Negative examples: synthetic alternatives (label=0)
  - Different action types (if took weapon, generate chip/move/end as negatives)
  - Randomly modified consequences
"""

from dataclasses import dataclass, field
from typing import Iterator, Optional
import json
import random

from .features import EntityState, StateFeatures, ActionFeatures, FeatureExtractor
from .items import get_item_properties, get_move_properties, get_end_properties
from src.scraper.item_mappings import WEAPONS, CHIPS


# Action type constants
ACTION_START_FIGHT = 0
ACTION_DEATH = 5
ACTION_NEW_TURN = 6
ACTION_LEEK_TURN = 7
ACTION_END_TURN = 8
ACTION_SUMMON = 9
ACTION_MOVE_TO = 10
ACTION_USE_CHIP = 12
ACTION_SET_WEAPON = 13
ACTION_USE_WEAPON = 16
ACTION_LIFE_LOST = 101
ACTION_LIFE_GAIN = 103
ACTION_ADD_EFFECT = 301


@dataclass
class TrainingExample:
    """A single training example: state + action features with label."""

    fight_id: int
    turn: int
    entity_id: int  # Who made the decision

    # Features
    state_features: list[float]
    action_features: list[float]

    # Label: 1.0 if this action was taken, 0.0 otherwise
    label: float

    # Metadata for debugging
    action_type: str = ""  # 'weapon', 'chip', 'move', 'end'
    item_id: Optional[int] = None
    won: bool = False


@dataclass
class ReplayState:
    """Mutable state during fight replay."""

    turn: int = 0
    current_entity: int = -1
    winner: int = 0

    # Entity states by ID
    entities: dict[int, EntityState] = field(default_factory=dict)

    # Current entity's resources this turn
    current_tp: int = 0
    current_mp: int = 0
    current_cell: int = 0

    # Current weapon equipped
    current_weapon: Optional[int] = None

    # Actions taken this turn (for generating alternatives)
    turn_actions: list[dict] = field(default_factory=list)


class FightReplayer:
    """
    Replays a fight to extract training examples.

    For each decision point, generates:
    - Positive example: the action that was actually taken (label=1)
    - Negative examples: alternative actions that could have been taken (label=0)
    """

    def __init__(self, feature_extractor: Optional[FeatureExtractor] = None):
        self.fe = feature_extractor or FeatureExtractor()

    def replay_fight(
        self,
        fight_id: int,
        fight_data: dict,
        our_entity_id: Optional[int] = None,
        generate_negatives: bool = True,
        max_negatives_per_action: int = 3,
    ) -> Iterator[TrainingExample]:
        """
        Replay a fight and generate training examples.

        Args:
            fight_id: Fight ID for metadata
            fight_data: Full fight data dict
            our_entity_id: If specified, only generate examples for this entity
            generate_negatives: Whether to generate negative examples
            max_negatives_per_action: Max negative examples per positive

        Yields:
            TrainingExample for each decision point
        """
        # Parse fight structure
        inner_data = fight_data.get('data', {})
        actions = inner_data.get('actions', [])
        leeks_raw = inner_data.get('leeks', [])
        winner = fight_data.get('winner', 0)

        if not actions:
            return

        # Build entity map
        if isinstance(leeks_raw, dict):
            leeks = leeks_raw
        else:
            leeks = {str(l.get('id')): l for l in leeks_raw}

        # Initialize state
        state = ReplayState()
        state.winner = winner

        # Initialize entity states
        for eid_str, leek in leeks.items():
            try:
                eid = int(eid_str)
            except ValueError:
                continue

            # Skip non-leek entities (chests, etc.)
            if leek.get('level', 0) >= 100:
                continue

            es = EntityState(
                entity_id=eid,
                life=leek.get('life', 100),
                total_life=leek.get('life', 100),
                tp=leek.get('tp', 10),
                mp=leek.get('pm', 3),
                strength=leek.get('strength', 0) or leek.get('force', 0),
                magic=leek.get('magic', 0),
                agility=leek.get('agility', 0),
                resistance=leek.get('resistance', 0),
                wisdom=leek.get('wisdom', 0),
                science=leek.get('science', 0),
                frequency=leek.get('frequency', 0),
                cell=leek.get('cellPos', 0),
            )
            state.entities[eid] = es

        # Need exactly 2 entities for 1v1
        entity_ids = list(state.entities.keys())
        if len(entity_ids) != 2:
            return

        # Process actions
        for action in actions:
            if not isinstance(action, list) or not action:
                continue

            action_type = action[0]

            if action_type == ACTION_NEW_TURN:
                if len(action) > 1:
                    state.turn = action[1]
                state.turn_actions = []

            elif action_type == ACTION_LEEK_TURN:
                if len(action) >= 2:
                    state.current_entity = action[1]
                    es = state.entities.get(state.current_entity)
                    if es:
                        state.current_tp = action[2] if len(action) > 2 else es.tp
                        state.current_mp = action[3] if len(action) > 3 else es.mp
                        state.current_cell = es.cell
                        state.current_weapon = None
                        state.turn_actions = []

                        # Update is_self/is_enemy
                        for eid, ent in state.entities.items():
                            ent.is_self = (eid == state.current_entity)
                            ent.is_enemy = (eid != state.current_entity)

            elif action_type == ACTION_SET_WEAPON:
                if len(action) >= 2:
                    state.current_weapon = action[1]

            elif action_type == ACTION_MOVE_TO:
                if len(action) >= 3:
                    entity_id = action[1]
                    dest_cell = action[2]

                    if our_entity_id is None or entity_id == our_entity_id:
                        yield from self._generate_examples(
                            fight_id, state, 'move', None, dest_cell,
                            generate_negatives, max_negatives_per_action
                        )

                    # Update state
                    es = state.entities.get(entity_id)
                    if es:
                        es.cell = dest_cell
                    if entity_id == state.current_entity:
                        state.current_cell = dest_cell
                        path = action[3] if len(action) > 3 else []
                        state.current_mp -= len(path)

            elif action_type == ACTION_USE_WEAPON:
                if len(action) >= 2:
                    target_cell = action[1]

                    if our_entity_id is None or state.current_entity == our_entity_id:
                        yield from self._generate_examples(
                            fight_id, state, 'weapon', state.current_weapon, target_cell,
                            generate_negatives, max_negatives_per_action
                        )

                    if state.current_weapon and state.current_weapon in WEAPONS:
                        cost = WEAPONS[state.current_weapon].get('cost', 3)
                        state.current_tp -= cost

            elif action_type == ACTION_USE_CHIP:
                if len(action) >= 3:
                    chip_id = action[1]
                    target_cell = action[2]

                    if our_entity_id is None or state.current_entity == our_entity_id:
                        yield from self._generate_examples(
                            fight_id, state, 'chip', chip_id, target_cell,
                            generate_negatives, max_negatives_per_action
                        )

                    if chip_id in CHIPS:
                        cost = CHIPS[chip_id].get('cost', 3)
                        state.current_tp -= cost

            elif action_type == ACTION_END_TURN:
                if len(action) >= 2:
                    entity_id = action[1]
                    if our_entity_id is None or entity_id == our_entity_id:
                        yield from self._generate_examples(
                            fight_id, state, 'end', None, 0,
                            generate_negatives, max_negatives_per_action
                        )

            elif action_type == ACTION_LIFE_LOST:
                if len(action) >= 3:
                    entity_id = action[1]
                    damage = action[2]
                    es = state.entities.get(entity_id)
                    if es:
                        es.life = max(0, es.life - damage)

            elif action_type == ACTION_LIFE_GAIN:
                if len(action) >= 3:
                    entity_id = action[1]
                    heal = action[2]
                    es = state.entities.get(entity_id)
                    if es:
                        es.life = min(es.total_life, es.life + heal)

    def _get_enemy_state(self, state: ReplayState) -> Optional[EntityState]:
        """Get the enemy entity state."""
        for eid, es in state.entities.items():
            if eid != state.current_entity:
                return es
        return None

    def _get_self_state(self, state: ReplayState) -> Optional[EntityState]:
        """Get current entity state."""
        return state.entities.get(state.current_entity)

    def _generate_examples(
        self,
        fight_id: int,
        state: ReplayState,
        action_type: str,  # 'move', 'weapon', 'chip', 'end'
        item_id: Optional[int],
        target_cell: int,
        generate_negatives: bool,
        max_negatives: int,
    ) -> Iterator[TrainingExample]:
        """Generate positive and negative examples for an action."""
        self_state = self._get_self_state(state)
        enemy_state = self._get_enemy_state(state)

        if not self_state or not enemy_state:
            return

        # Update with current resources
        self_state.tp = state.current_tp
        self_state.mp = state.current_mp

        # Extract state features (shared across all examples for this decision)
        state_features = self.fe.extract_state_features(
            self_state, enemy_state, state.turn
        )

        # Generate positive example for the action that was taken
        action_features = self._extract_action_features(
            action_type, item_id, target_cell, self_state, enemy_state
        )

        yield TrainingExample(
            fight_id=fight_id,
            turn=state.turn,
            entity_id=state.current_entity,
            state_features=state_features.to_vector(),
            action_features=action_features.to_vector(),
            label=1.0,
            action_type=action_type,
            item_id=item_id,
        )

        # Generate negative examples if requested
        if generate_negatives:
            yield from self._generate_negatives(
                fight_id, state, state_features, action_type, item_id,
                self_state, enemy_state, max_negatives
            )

    def _extract_action_features(
        self,
        action_type: str,
        item_id: Optional[int],
        target_cell: int,
        self_state: EntityState,
        enemy_state: EntityState,
    ) -> ActionFeatures:
        """Extract action features for a given action."""
        # Estimate consequences based on action type
        damage = 0.0
        heal = 0.0
        shield = 0.0
        poison = 0.0
        tp_cost = 0
        mp_cost = 0
        cell_after = self_state.cell

        if action_type == 'weapon':
            damage = self_state.strength * 0.5
            if item_id and item_id in WEAPONS:
                tp_cost = WEAPONS[item_id].get('cost', 3)
        elif action_type == 'chip':
            if item_id and item_id in CHIPS:
                chip_info = CHIPS[item_id]
                chip_type = chip_info.get('type', 1)
                tp_cost = chip_info.get('cost', 3)

                if chip_type == 1:  # damage
                    damage = self_state.magic * 0.3
                elif chip_type == 2:  # heal
                    heal = self_state.magic * 0.3
                elif chip_type == 4:  # shield
                    shield = self_state.magic * 0.2
                elif chip_type == 6:  # poison
                    poison = self_state.magic * 0.5
        elif action_type == 'move':
            cell_after = target_cell
            # Estimate MP cost based on distance
            mp_cost = abs(target_cell - self_state.cell) // 18 + 1
            mp_cost = min(mp_cost, self_state.mp)

        return self.fe.extract_action_features(
            action_type=action_type,
            item_id=item_id,
            target_cell=target_cell,
            self_state=self_state,
            enemy_state=enemy_state,
            damage_dealt=damage,
            heal_done=heal,
            shield_added=shield,
            poison_applied=poison,
            tp_cost=tp_cost,
            mp_cost=mp_cost,
            cell_after=cell_after,
        )

    def _generate_negatives(
        self,
        fight_id: int,
        state: ReplayState,
        state_features: StateFeatures,
        taken_type: str,
        taken_item: Optional[int],
        self_state: EntityState,
        enemy_state: EntityState,
        max_negatives: int,
    ) -> Iterator[TrainingExample]:
        """Generate negative examples - actions NOT taken."""
        negatives_generated = 0
        action_types = ['move', 'weapon', 'chip', 'end']

        # Generate negatives for different action types
        for alt_type in action_types:
            if negatives_generated >= max_negatives:
                break

            # Skip if same as taken action type (to avoid very similar negatives)
            if alt_type == taken_type:
                continue

            # Generate a synthetic alternative
            if alt_type == 'move':
                # Random cell movement
                alt_cell = random.randint(0, 612)
                action_features = self._extract_action_features(
                    'move', None, alt_cell, self_state, enemy_state
                )
            elif alt_type == 'weapon':
                # Use a random low-level weapon
                low_level_weapons = [1, 2, 4, 5]  # pistol, machine_gun, shotgun, magnum
                alt_weapon = random.choice(low_level_weapons)
                action_features = self._extract_action_features(
                    'weapon', alt_weapon, enemy_state.cell, self_state, enemy_state
                )
            elif alt_type == 'chip':
                # Use a random low-level chip
                low_level_chips = [1, 6, 12, 15, 19, 24]  # bandage, shock, pebble, ice, helmet, protein
                alt_chip = random.choice(low_level_chips)
                # Target depends on chip type
                chip_info = CHIPS.get(alt_chip, {})
                if chip_info.get('type') in [2, 4, 5]:  # heal, shield, buff -> self
                    alt_target = self_state.cell
                else:
                    alt_target = enemy_state.cell
                action_features = self._extract_action_features(
                    'chip', alt_chip, alt_target, self_state, enemy_state
                )
            else:  # end
                action_features = self._extract_action_features(
                    'end', None, 0, self_state, enemy_state
                )

            yield TrainingExample(
                fight_id=fight_id,
                turn=state.turn,
                entity_id=state.current_entity,
                state_features=state_features.to_vector(),
                action_features=action_features.to_vector(),
                label=0.0,  # Negative example
                action_type=alt_type,
                item_id=None,
            )
            negatives_generated += 1


def extract_training_data(
    db,
    fight_type: int = 0,
    max_level: int = 40,
    limit: Optional[int] = None,
) -> Iterator[TrainingExample]:
    """
    Extract training data from database.

    Args:
        db: FightDatabase instance (unused, connects directly)
        fight_type: Fight type (0=solo)
        max_level: Maximum leek level
        limit: Maximum fights to process

    Yields:
        TrainingExample for each decision point
    """
    import sqlite3
    from src.scraper.db import DEFAULT_DB_PATH

    replayer = FightReplayer()

    conn = sqlite3.connect(DEFAULT_DB_PATH)
    cur = conn.cursor()

    query = '''
        SELECT f.fight_id, f.json_data
        FROM fights f
        WHERE f.fight_type = ?
        AND f.context = 2
        AND f.team1_levels <= ?
        AND f.team2_levels <= ?
    '''
    params = [fight_type, max_level, max_level]

    if limit:
        query += ' LIMIT ?'
        params.append(limit)

    cur.execute(query, params)

    for fight_id, json_data in cur:
        if isinstance(json_data, str):
            data = json.loads(json_data)
        else:
            data = json_data

        yield from replayer.replay_fight(fight_id, data)

    conn.close()
