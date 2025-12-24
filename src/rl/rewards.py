"""
Reward shaping for LeekWars RL training.

Provides configurable reward functions that incentivize
both winning and efficient play.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class RewardConfig:
    """Configuration for reward calculation."""

    # Win/loss rewards
    win_reward: float = 100.0
    loss_reward: float = -80.0
    draw_reward: float = 10.0

    # Per-damage rewards
    damage_dealt_per_hp: float = 0.1
    damage_taken_per_hp: float = -0.15

    # Survival bonus
    survival_bonus_per_turn: float = 0.5

    # Efficiency bonuses
    efficiency_multiplier: float = 1.0  # Bonus for high damage/TP ratio
    overkill_penalty: float = -0.05     # Penalty for wasted damage

    # Resource management
    tp_unused_penalty: float = -0.02    # Penalty for unused TP at turn end
    mp_unused_penalty: float = -0.01    # Penalty for unused MP at turn end

    # Kill bonus
    kill_bonus: float = 20.0            # Bonus for eliminating an enemy

    # Time pressure (encourages faster wins)
    time_decay: float = 0.99            # Multiplier per turn for win reward


@dataclass
class FightOutcome:
    """Outcome data for reward calculation."""

    # Result
    won: bool
    is_draw: bool

    # Damage
    total_damage_dealt: int
    total_damage_taken: int

    # Combat stats
    turns_survived: int
    total_turns: int
    kills: int

    # Resource usage
    total_tp_spent: int
    total_mp_spent: int
    total_tp_available: int
    total_mp_available: int

    # HP
    final_hp: int
    initial_hp: int
    enemy_final_hp: int
    enemy_initial_hp: int


class RewardCalculator:
    """
    Calculates shaped rewards from fight outcomes.

    The reward function combines:
    - Win/loss terminal reward
    - Damage dealt/taken during fight
    - Survival bonus
    - Efficiency bonuses for resource usage
    """

    def __init__(self, config: Optional[RewardConfig] = None):
        self.config = config or RewardConfig()

    def calculate(self, outcome: FightOutcome) -> float:
        """
        Calculate total reward from fight outcome.

        Args:
            outcome: Fight outcome data

        Returns:
            Total shaped reward
        """
        reward = 0.0

        # Terminal reward (with time decay)
        if outcome.won:
            time_factor = self.config.time_decay ** outcome.total_turns
            reward += self.config.win_reward * time_factor
        elif outcome.is_draw:
            reward += self.config.draw_reward
        else:
            reward += self.config.loss_reward

        # Damage rewards
        reward += outcome.total_damage_dealt * self.config.damage_dealt_per_hp
        reward += outcome.total_damage_taken * self.config.damage_taken_per_hp

        # Survival bonus
        reward += outcome.turns_survived * self.config.survival_bonus_per_turn

        # Kill bonus
        reward += outcome.kills * self.config.kill_bonus

        # Efficiency bonus (damage per TP spent)
        if outcome.total_tp_spent > 0:
            efficiency = outcome.total_damage_dealt / outcome.total_tp_spent
            # Normalize: typical damage is ~15-25 per TP for pistol
            normalized_efficiency = efficiency / 20.0
            efficiency_bonus = (normalized_efficiency - 1.0) * self.config.efficiency_multiplier * 10
            reward += efficiency_bonus

        # Overkill penalty (damage beyond killing)
        if outcome.won and outcome.enemy_final_hp == 0:
            overkill = max(0, outcome.total_damage_dealt - outcome.enemy_initial_hp)
            reward += overkill * self.config.overkill_penalty

        # Resource management penalties
        if outcome.total_tp_available > 0:
            tp_wasted = outcome.total_tp_available - outcome.total_tp_spent
            reward += tp_wasted * self.config.tp_unused_penalty

        if outcome.total_mp_available > 0:
            mp_wasted = outcome.total_mp_available - outcome.total_mp_spent
            reward += mp_wasted * self.config.mp_unused_penalty

        return reward

    def calculate_step_reward(
        self,
        damage_dealt: int,
        damage_taken: int,
        tp_spent: int,
        mp_spent: int,
        got_kill: bool = False,
    ) -> float:
        """
        Calculate intermediate reward for a single step/turn.

        Args:
            damage_dealt: Damage dealt this turn
            damage_taken: Damage taken this turn
            tp_spent: TP used this turn
            mp_spent: MP used this turn
            got_kill: Whether this turn resulted in a kill

        Returns:
            Step reward
        """
        reward = 0.0

        # Damage rewards
        reward += damage_dealt * self.config.damage_dealt_per_hp
        reward += damage_taken * self.config.damage_taken_per_hp

        # Kill bonus
        if got_kill:
            reward += self.config.kill_bonus

        # Efficiency for this turn
        if tp_spent > 0:
            efficiency = damage_dealt / tp_spent
            normalized = efficiency / 20.0
            reward += (normalized - 1.0) * self.config.efficiency_multiplier

        # Small survival bonus
        reward += self.config.survival_bonus_per_turn

        return reward

    def get_terminal_reward(self, won: bool, is_draw: bool, total_turns: int) -> float:
        """Get just the terminal (win/loss/draw) reward."""
        if won:
            time_factor = self.config.time_decay ** total_turns
            return self.config.win_reward * time_factor
        elif is_draw:
            return self.config.draw_reward
        else:
            return self.config.loss_reward


# Pre-configured reward schemes
AGGRESSIVE_REWARDS = RewardConfig(
    win_reward=150.0,
    loss_reward=-100.0,
    damage_dealt_per_hp=0.2,
    damage_taken_per_hp=-0.1,
    efficiency_multiplier=0.5,
)

DEFENSIVE_REWARDS = RewardConfig(
    win_reward=100.0,
    loss_reward=-50.0,
    damage_dealt_per_hp=0.05,
    damage_taken_per_hp=-0.3,
    survival_bonus_per_turn=1.0,
)

BALANCED_REWARDS = RewardConfig()  # Default config
