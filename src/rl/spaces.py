"""
Observation and action space definitions for LeekWars RL.

Defines the state representation and action choices available
to RL agents during training.
"""

from dataclasses import dataclass, field
from typing import Any
import numpy as np

try:
    import gymnasium as gym
    from gymnasium import spaces
    HAS_GYMNASIUM = True
except ImportError:
    HAS_GYMNASIUM = False


@dataclass
class EntityObservation:
    """Observation of a single entity (self or enemy)."""

    hp_ratio: float  # 0.0 - 1.0
    tp: int          # Current action points
    mp: int          # Current movement points
    cell: int        # Current cell position (0-612)
    is_alive: bool   # Whether entity is alive


@dataclass
class FieldObservation:
    """Observation of the battlefield state."""

    turn_number: int      # Current turn (1-64)
    round_number: int     # Current round (entities can have multiple turns per round)
    max_turns: int        # Maximum turns before draw
    distance_to_enemy: int  # Cell distance to nearest enemy


@dataclass
class Observation:
    """Complete observation of the fight state."""

    self_obs: EntityObservation
    enemy_obs: EntityObservation  # For 1v1; extend for multi-agent
    field_obs: FieldObservation

    def to_array(self) -> np.ndarray:
        """Convert observation to flat numpy array for neural networks."""
        return np.array([
            # Self state (5 features)
            self.self_obs.hp_ratio,
            self.self_obs.tp / 10.0,  # Normalize TP
            self.self_obs.mp / 5.0,   # Normalize MP
            self.self_obs.cell / 612.0,  # Normalize cell
            float(self.self_obs.is_alive),
            # Enemy state (5 features)
            self.enemy_obs.hp_ratio,
            self.enemy_obs.tp / 10.0,
            self.enemy_obs.mp / 5.0,
            self.enemy_obs.cell / 612.0,
            float(self.enemy_obs.is_alive),
            # Field state (4 features)
            self.field_obs.turn_number / 64.0,
            self.field_obs.round_number / 64.0,
            self.field_obs.distance_to_enemy / 30.0,  # Normalize distance
            self.field_obs.max_turns / 64.0,
        ], dtype=np.float32)

    @classmethod
    def get_dimension(cls) -> int:
        """Return the dimension of the observation array."""
        return 14


class ObservationSpace:
    """
    Defines the observation space for the LeekWars environment.

    The observation includes:
    - Self state: HP ratio, TP, MP, position, alive status
    - Enemy state: Same as self
    - Field state: Turn number, round, distance to enemy
    """

    def __init__(self):
        self.dim = Observation.get_dimension()

    def get_gym_space(self) -> "spaces.Box":
        """Return Gymnasium Box space for the observation."""
        if not HAS_GYMNASIUM:
            raise ImportError("gymnasium is required for gym spaces")

        return spaces.Box(
            low=0.0,
            high=1.0,
            shape=(self.dim,),
            dtype=np.float32,
        )

    @staticmethod
    def from_fight_state(
        my_hp: int,
        my_max_hp: int,
        my_tp: int,
        my_mp: int,
        my_cell: int,
        enemy_hp: int,
        enemy_max_hp: int,
        enemy_tp: int,
        enemy_mp: int,
        enemy_cell: int,
        turn_number: int,
        round_number: int,
        max_turns: int,
        distance: int,
    ) -> Observation:
        """Create observation from fight state values."""
        return Observation(
            self_obs=EntityObservation(
                hp_ratio=my_hp / max(my_max_hp, 1),
                tp=my_tp,
                mp=my_mp,
                cell=my_cell,
                is_alive=my_hp > 0,
            ),
            enemy_obs=EntityObservation(
                hp_ratio=enemy_hp / max(enemy_max_hp, 1),
                tp=enemy_tp,
                mp=enemy_mp,
                cell=enemy_cell,
                is_alive=enemy_hp > 0,
            ),
            field_obs=FieldObservation(
                turn_number=turn_number,
                round_number=round_number,
                max_turns=max_turns,
                distance_to_enemy=distance,
            ),
        )


# Action definitions
@dataclass
class ActionDefinition:
    """Definition of a single action type."""

    id: int
    name: str
    category: str  # "move", "attack", "support", "meta"
    description: str


# Standard action set for LeekWars RL
ACTIONS = [
    # Movement (0-3)
    ActionDefinition(0, "move_toward", "move", "Move toward nearest enemy"),
    ActionDefinition(1, "move_away", "move", "Move away from nearest enemy"),
    ActionDefinition(2, "move_cover", "move", "Move to nearest cover/obstacle"),
    ActionDefinition(3, "hold_position", "move", "Stay in current position"),

    # Attack (4-7)
    ActionDefinition(4, "attack_weapon", "attack", "Use equipped weapon on target"),
    ActionDefinition(5, "attack_chip_damage", "attack", "Use damage chip on target"),
    ActionDefinition(6, "attack_aoe", "attack", "Use area-of-effect ability"),
    ActionDefinition(7, "attack_max_damage", "attack", "Maximize damage output this turn"),

    # Support (8-11)
    ActionDefinition(8, "heal_self", "support", "Heal self if available"),
    ActionDefinition(9, "shield_self", "support", "Apply shield to self"),
    ActionDefinition(10, "buff_self", "support", "Apply buff to self"),
    ActionDefinition(11, "support_ally", "support", "Support nearest ally"),

    # Meta (12-15)
    ActionDefinition(12, "aggressive_turn", "meta", "All-out attack this turn"),
    ActionDefinition(13, "defensive_turn", "meta", "Focus on survival this turn"),
    ActionDefinition(14, "balanced_turn", "meta", "Balance offense and defense"),
    ActionDefinition(15, "skip_turn", "meta", "End turn early, save resources"),
]


class ActionSpace:
    """
    Defines the action space for the LeekWars environment.

    Actions are high-level strategic choices that get translated
    into LeekScript commands by the AI executor.
    """

    def __init__(self, action_set: list[ActionDefinition] = None):
        self.actions = action_set or ACTIONS
        self.n_actions = len(self.actions)

    def get_gym_space(self) -> "spaces.Discrete":
        """Return Gymnasium Discrete space for actions."""
        if not HAS_GYMNASIUM:
            raise ImportError("gymnasium is required for gym spaces")

        return spaces.Discrete(self.n_actions)

    def get_action(self, action_id: int) -> ActionDefinition:
        """Get action definition by ID."""
        if 0 <= action_id < self.n_actions:
            return self.actions[action_id]
        raise ValueError(f"Invalid action ID: {action_id}")

    def get_action_by_name(self, name: str) -> ActionDefinition:
        """Get action definition by name."""
        for action in self.actions:
            if action.name == name:
                return action
        raise ValueError(f"Unknown action: {name}")

    def get_actions_by_category(self, category: str) -> list[ActionDefinition]:
        """Get all actions in a category."""
        return [a for a in self.actions if a.category == category]

    def sample(self) -> int:
        """Sample a random action."""
        return np.random.randint(self.n_actions)

    def mask_invalid(self, valid_mask: np.ndarray) -> np.ndarray:
        """
        Create action probability mask for invalid actions.

        Args:
            valid_mask: Boolean array where True = valid action

        Returns:
            Probability distribution (invalid actions have 0 probability)
        """
        masked = valid_mask.astype(np.float32)
        total = masked.sum()
        if total > 0:
            return masked / total
        # All invalid - uniform distribution
        return np.ones(self.n_actions, dtype=np.float32) / self.n_actions
