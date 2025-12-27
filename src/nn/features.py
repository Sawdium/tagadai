"""
State and Action feature extraction for NN input.

Features are designed to:
1. Be normalizable (0-1 or similar range)
2. Generalize across different levels/items
3. Capture the essential decision-making information
"""

from dataclasses import dataclass, field
from typing import Optional
import math

from .items import ItemProperties, get_item_properties, get_move_properties, get_end_properties


@dataclass
class EntityState:
    """State of a single entity (leek/bulb)."""

    entity_id: int = 0
    is_self: bool = False
    is_ally: bool = False
    is_enemy: bool = False

    # Vitals
    life: int = 0
    total_life: int = 1  # Avoid division by zero
    tp: int = 0
    mp: int = 0

    # Stats
    strength: int = 0
    magic: int = 0
    agility: int = 0
    resistance: int = 0
    wisdom: int = 0
    science: int = 0
    frequency: int = 0

    # Position
    cell: int = 0

    # Effects (simplified)
    has_poison: bool = False
    has_shield: bool = False
    poison_damage: int = 0
    shield_value: int = 0


@dataclass
class StateFeatures:
    """
    Context features shared across all action evaluations.

    These describe the current fight state independent of any specific action.
    """

    # Self state (normalized)
    self_hp_ratio: float = 1.0  # life / total_life
    self_tp_norm: float = 0.5   # tp / 20
    self_mp_norm: float = 0.5   # mp / 10
    self_str_norm: float = 0.0  # strength / 500
    self_mgc_norm: float = 0.0  # magic / 500
    self_agi_norm: float = 0.0  # agility / 500
    self_rst_norm: float = 0.0  # resistance / 500

    # Enemy state (normalized)
    enemy_hp_ratio: float = 1.0
    enemy_tp_norm: float = 0.5
    enemy_mp_norm: float = 0.5
    enemy_str_norm: float = 0.0
    enemy_mgc_norm: float = 0.0

    # Relative position
    distance_norm: float = 0.5  # distance / 20

    # Danger assessment
    danger_current_norm: float = 0.0  # current danger / total_life
    danger_best_norm: float = 0.0     # best danger / total_life
    danger_ratio: float = 1.0         # current / best (1.0 if at best)

    # Status effects
    self_has_poison: float = 0.0
    self_has_shield: float = 0.0
    enemy_has_poison: float = 0.0
    enemy_has_shield: float = 0.0

    # Turn info
    turn_norm: float = 0.0  # turn / 64

    # Tactical flags
    can_kill_this_turn: float = 0.0   # enemy HP < max possible damage
    at_risk: float = 0.0              # could die next enemy turn

    def to_vector(self) -> list[float]:
        """Convert to feature vector."""
        return [
            self.self_hp_ratio,
            self.self_tp_norm,
            self.self_mp_norm,
            self.self_str_norm,
            self.self_mgc_norm,
            self.self_agi_norm,
            self.self_rst_norm,
            self.enemy_hp_ratio,
            self.enemy_tp_norm,
            self.enemy_mp_norm,
            self.enemy_str_norm,
            self.enemy_mgc_norm,
            self.distance_norm,
            self.danger_current_norm,
            self.danger_best_norm,
            self.danger_ratio,
            self.self_has_poison,
            self.self_has_shield,
            self.enemy_has_poison,
            self.enemy_has_shield,
            self.turn_norm,
            self.can_kill_this_turn,
            self.at_risk,
        ]

    @staticmethod
    def vector_size() -> int:
        return 23


@dataclass
class ActionFeatures:
    """
    Features specific to a single action candidate.

    Combined with StateFeatures for the full NN input.
    """

    # Item properties (from items.py)
    item_props: ItemProperties = field(default_factory=ItemProperties)

    # Action consequences
    damage_dealt_norm: float = 0.0      # damage / enemy total_life
    damage_dealt_ratio: float = 0.0     # damage / enemy current_life (kill potential)
    heal_done_norm: float = 0.0         # heal / self total_life
    shield_added_norm: float = 0.0      # shield / self total_life
    poison_applied_norm: float = 0.0    # poison_total / enemy total_life

    # Resource costs
    tp_cost_ratio: float = 0.0  # tp_cost / current_tp
    mp_cost_ratio: float = 0.0  # mp_cost / current_mp

    # Positional consequences
    danger_after_norm: float = 0.0     # danger at new position / self total_life
    danger_delta_norm: float = 0.0     # (danger_after - danger_before) / self total_life
    distance_after_norm: float = 0.5   # distance to enemy after action / 20
    distance_delta_norm: float = 0.0   # (distance_after - distance_before) / 20

    # Tactical flags
    is_kill: float = 0.0        # will this kill the enemy?
    is_self_target: float = 0.0 # targeting self (buff/heal)
    will_die_after: float = 0.0 # danger_after >= self life

    def to_vector(self) -> list[float]:
        """Convert to feature vector (including item properties)."""
        return (
            self.item_props.to_vector() +
            [
                self.damage_dealt_norm,
                self.damage_dealt_ratio,
                self.heal_done_norm,
                self.shield_added_norm,
                self.poison_applied_norm,
                self.tp_cost_ratio,
                self.mp_cost_ratio,
                self.danger_after_norm,
                self.danger_delta_norm,
                self.distance_after_norm,
                self.distance_delta_norm,
                self.is_kill,
                self.is_self_target,
                self.will_die_after,
            ]
        )

    @staticmethod
    def vector_size() -> int:
        return ItemProperties.vector_size() + 14  # 20 + 14 = 34


class FeatureExtractor:
    """
    Extracts features from fight state for NN input.

    This is the Python equivalent of what will run in LeekScript.
    """

    def extract_state_features(
        self,
        self_state: EntityState,
        enemy_state: EntityState,
        turn: int = 1,
        danger_current: float = 0.0,
        danger_best: float = 0.0,
        max_damage_possible: float = 0.0,
    ) -> StateFeatures:
        """
        Extract state features from current fight state.

        Args:
            self_state: Current entity state
            enemy_state: Enemy entity state
            turn: Current turn number
            danger_current: Incoming damage at current position
            danger_best: Best achievable danger
            max_damage_possible: Maximum damage we can deal this turn
        """
        sf = StateFeatures()

        # Self state
        sf.self_hp_ratio = self_state.life / max(self_state.total_life, 1)
        sf.self_tp_norm = self_state.tp / 20.0
        sf.self_mp_norm = self_state.mp / 10.0
        sf.self_str_norm = self_state.strength / 500.0
        sf.self_mgc_norm = self_state.magic / 500.0
        sf.self_agi_norm = self_state.agility / 500.0
        sf.self_rst_norm = self_state.resistance / 500.0

        # Enemy state
        sf.enemy_hp_ratio = enemy_state.life / max(enemy_state.total_life, 1)
        sf.enemy_tp_norm = enemy_state.tp / 20.0
        sf.enemy_mp_norm = enemy_state.mp / 10.0
        sf.enemy_str_norm = enemy_state.strength / 500.0
        sf.enemy_mgc_norm = enemy_state.magic / 500.0

        # Distance
        distance = self._cell_distance(self_state.cell, enemy_state.cell)
        sf.distance_norm = distance / 20.0

        # Danger
        tl = max(self_state.total_life, 1)
        sf.danger_current_norm = danger_current / tl
        sf.danger_best_norm = danger_best / tl
        if danger_best > 0:
            sf.danger_ratio = danger_current / danger_best
        else:
            sf.danger_ratio = 1.0 if danger_current == 0 else 2.0

        # Status effects
        sf.self_has_poison = 1.0 if self_state.has_poison else 0.0
        sf.self_has_shield = 1.0 if self_state.has_shield else 0.0
        sf.enemy_has_poison = 1.0 if enemy_state.has_poison else 0.0
        sf.enemy_has_shield = 1.0 if enemy_state.has_shield else 0.0

        # Turn
        sf.turn_norm = turn / 64.0

        # Tactical
        sf.can_kill_this_turn = 1.0 if max_damage_possible >= enemy_state.life else 0.0
        sf.at_risk = 1.0 if danger_current >= self_state.life else 0.0

        return sf

    def extract_action_features(
        self,
        action_type: str,  # 'weapon', 'chip', 'move', 'end'
        item_id: Optional[int],
        target_cell: int,
        self_state: EntityState,
        enemy_state: EntityState,
        # Consequences (computed externally or estimated)
        damage_dealt: float = 0.0,
        heal_done: float = 0.0,
        shield_added: float = 0.0,
        poison_applied: float = 0.0,
        tp_cost: int = 0,
        mp_cost: int = 0,
        danger_after: float = 0.0,
        danger_before: float = 0.0,
        cell_after: int = 0,
    ) -> ActionFeatures:
        """
        Extract action features for a single action candidate.
        """
        af = ActionFeatures()

        # Item properties
        if action_type == 'weapon':
            af.item_props = get_item_properties(item_id, is_weapon=True)
        elif action_type == 'chip':
            af.item_props = get_item_properties(item_id, is_weapon=False)
        elif action_type == 'move':
            af.item_props = get_move_properties()
        else:  # end
            af.item_props = get_end_properties()

        # Consequences (normalized)
        enemy_tl = max(enemy_state.total_life, 1)
        self_tl = max(self_state.total_life, 1)

        af.damage_dealt_norm = damage_dealt / enemy_tl
        if enemy_state.life > 0:
            af.damage_dealt_ratio = damage_dealt / enemy_state.life
        else:
            af.damage_dealt_ratio = 0.0
        af.heal_done_norm = heal_done / self_tl
        af.shield_added_norm = shield_added / self_tl
        af.poison_applied_norm = poison_applied / enemy_tl

        # Resource costs
        if self_state.tp > 0:
            af.tp_cost_ratio = tp_cost / self_state.tp
        if self_state.mp > 0:
            af.mp_cost_ratio = mp_cost / self_state.mp

        # Positional consequences
        af.danger_after_norm = danger_after / self_tl
        af.danger_delta_norm = (danger_after - danger_before) / self_tl

        distance_before = self._cell_distance(self_state.cell, enemy_state.cell)
        distance_after = self._cell_distance(cell_after or self_state.cell, enemy_state.cell)
        af.distance_after_norm = distance_after / 20.0
        af.distance_delta_norm = (distance_after - distance_before) / 20.0

        # Tactical flags
        af.is_kill = 1.0 if damage_dealt >= enemy_state.life else 0.0
        af.is_self_target = 1.0 if target_cell == self_state.cell else 0.0
        af.will_die_after = 1.0 if danger_after >= self_state.life else 0.0

        return af

    def combine_features(
        self,
        state: StateFeatures,
        action: ActionFeatures,
    ) -> list[float]:
        """Combine state and action features into single vector."""
        return state.to_vector() + action.to_vector()

    @staticmethod
    def total_feature_size() -> int:
        """Total size of combined feature vector."""
        return StateFeatures.vector_size() + ActionFeatures.vector_size()  # 23 + 34 = 57

    def _cell_distance(self, cell1: int, cell2: int) -> int:
        """
        Compute distance between two cells on LeekWars hexagonal grid.

        The grid is 18 columns x 18 rows with alternating row offsets.
        """
        if cell1 < 0 or cell2 < 0:
            return 20  # Invalid cells

        # Convert cell ID to coordinates
        # LeekWars uses a specific grid layout
        x1, y1 = cell1 % 18, cell1 // 18
        x2, y2 = cell2 % 18, cell2 // 18

        # Simple manhattan-ish distance for now
        # Real distance would need hex grid calculation
        return abs(x2 - x1) + abs(y2 - y1)
