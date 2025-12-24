"""
Gymnasium-compatible environment for LeekWars RL training.

Wraps the local fight runner to provide a standard RL interface.
"""

from dataclasses import dataclass, field
from typing import Any, Optional, Tuple
import numpy as np

try:
    import gymnasium as gym
    from gymnasium import spaces
    HAS_GYMNASIUM = True
except ImportError:
    HAS_GYMNASIUM = False

from ..localfight.runner import run_fight, check_generator, RunnerError
from ..localfight.scenario import Scenario, LeekConfig, MapConfig, ITEM_PISTOL
from ..localfight.parser import (
    parse_fight_result,
    FightResult,
    ActionType,
)
from .spaces import ObservationSpace, ActionSpace, Observation
from .rewards import RewardCalculator, RewardConfig, FightOutcome


@dataclass
class EnvConfig:
    """Configuration for the LeekWars environment."""

    # AI paths (relative to generator directory)
    agent_ai: str = "test/ai/simple.leek"
    opponent_ai: str = "test/ai/simple.leek"

    # Leek stats
    agent_level: int = 1
    agent_life: int = 100
    agent_strength: int = 0
    agent_tp: int = 10
    agent_mp: int = 3

    opponent_level: int = 1
    opponent_life: int = 100
    opponent_strength: int = 0
    opponent_tp: int = 10
    opponent_mp: int = 3

    # Equipment (ITEM IDs)
    agent_weapons: list[int] = field(default_factory=lambda: [ITEM_PISTOL])
    opponent_weapons: list[int] = field(default_factory=lambda: [ITEM_PISTOL])

    # Fight settings
    max_turns: int = 64
    map_width: int = 17
    map_height: int = 17

    # Execution
    timeout: float = 30.0
    nocache: bool = True


@dataclass
class EpisodeInfo:
    """Information about a completed episode."""

    won: bool
    is_draw: bool
    total_turns: int
    damage_dealt: int
    damage_taken: int
    final_hp: int
    enemy_final_hp: int
    execution_time_ns: int
    fight_result: Optional[FightResult] = None


class LeekWarsEnv:
    """
    Gymnasium-compatible environment for LeekWars combat.

    This environment runs complete fights and returns the outcome.
    It's designed for episodic RL where each episode is one fight.

    Note: This is a "one-shot" environment - step() runs the entire
    fight and returns the final outcome. For turn-by-turn control,
    a different approach using custom LeekScript AI would be needed.
    """

    metadata = {"render_modes": ["human", "ansi"]}

    def __init__(
        self,
        config: Optional[EnvConfig] = None,
        reward_config: Optional[RewardConfig] = None,
        seed: Optional[int] = None,
        render_mode: Optional[str] = None,
    ):
        """
        Initialize the LeekWars environment.

        Args:
            config: Environment configuration
            reward_config: Reward shaping configuration
            seed: Random seed for reproducibility
            render_mode: How to render ("human", "ansi", or None)
        """
        self.config = config or EnvConfig()
        self.reward_calc = RewardCalculator(reward_config)
        self._seed = seed
        self._rng = np.random.default_rng(seed)
        self.render_mode = render_mode

        # Spaces
        self._obs_space = ObservationSpace()
        self._action_space = ActionSpace()

        # Episode state
        self._episode_count = 0
        self._last_result: Optional[FightResult] = None
        self._last_info: Optional[EpisodeInfo] = None

        # Validate generator is available
        if not check_generator():
            raise RuntimeError(
                "LeekWars generator not available. "
                "Make sure the JAR is built in .cache/leek-wars-generator/"
            )

    @property
    def observation_space(self) -> "spaces.Box":
        """Return the observation space."""
        return self._obs_space.get_gym_space()

    @property
    def action_space(self) -> "spaces.Discrete":
        """Return the action space."""
        return self._action_space.get_gym_space()

    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[dict] = None,
    ) -> Tuple[np.ndarray, dict]:
        """
        Reset the environment for a new episode.

        Args:
            seed: Optional seed for this episode
            options: Optional reset options

        Returns:
            Initial observation and info dict
        """
        if seed is not None:
            self._seed = seed
            self._rng = np.random.default_rng(seed)

        self._episode_count += 1
        self._last_result = None
        self._last_info = None

        # Create initial observation (start of fight)
        initial_obs = Observation(
            self_obs=self._obs_space.from_fight_state(
                my_hp=self.config.agent_life,
                my_max_hp=self.config.agent_life,
                my_tp=self.config.agent_tp,
                my_mp=self.config.agent_mp,
                my_cell=0,  # Will be set by fight
                enemy_hp=self.config.opponent_life,
                enemy_max_hp=self.config.opponent_life,
                enemy_tp=self.config.opponent_tp,
                enemy_mp=self.config.opponent_mp,
                enemy_cell=100,  # Approximate
                turn_number=0,
                round_number=0,
                max_turns=self.config.max_turns,
                distance=15,  # Typical starting distance
            ).self_obs,
            enemy_obs=self._obs_space.from_fight_state(
                my_hp=self.config.opponent_life,
                my_max_hp=self.config.opponent_life,
                my_tp=self.config.opponent_tp,
                my_mp=self.config.opponent_mp,
                my_cell=100,
                enemy_hp=self.config.agent_life,
                enemy_max_hp=self.config.agent_life,
                enemy_tp=self.config.agent_tp,
                enemy_mp=self.config.agent_mp,
                enemy_cell=0,
                turn_number=0,
                round_number=0,
                max_turns=self.config.max_turns,
                distance=15,
            ).self_obs,
            field_obs=self._obs_space.from_fight_state(
                my_hp=100, my_max_hp=100, my_tp=10, my_mp=3, my_cell=0,
                enemy_hp=100, enemy_max_hp=100, enemy_tp=10, enemy_mp=3, enemy_cell=100,
                turn_number=0, round_number=0, max_turns=64, distance=15
            ).field_obs,
        )

        info = {
            "episode": self._episode_count,
            "seed": self._seed,
        }

        return initial_obs.to_array(), info

    def step(
        self,
        action: int,
    ) -> Tuple[np.ndarray, float, bool, bool, dict]:
        """
        Execute an action (run a complete fight).

        In this episodic environment, step() runs the entire fight
        and returns the outcome. The action parameter can influence
        the agent's strategy but the fight itself is atomic.

        Args:
            action: Action to take (influences strategy)

        Returns:
            observation: Final state observation
            reward: Shaped reward for the episode
            terminated: True (fights always terminate)
            truncated: False (handled by generator)
            info: Episode information
        """
        # Generate fight seed (convert to Python int for JSON serialization)
        fight_seed = int(self._rng.integers(0, 2**31))

        # Create scenario
        scenario = self._create_scenario(fight_seed, action)

        # Run fight
        try:
            raw_result = run_fight(
                scenario,
                timeout=self.config.timeout,
                nocache=self.config.nocache,
            )
            result = parse_fight_result(raw_result)
            self._last_result = result

        except RunnerError as e:
            # Fight failed - return penalty
            obs = np.zeros(self._obs_space.dim, dtype=np.float32)
            return obs, -100.0, True, True, {"error": str(e)}

        # Extract outcome
        info = self._extract_episode_info(result)
        self._last_info = info

        # Calculate reward
        outcome = self._create_outcome(result, info)
        reward = self.reward_calc.calculate(outcome)

        # Create final observation
        final_obs = self._create_final_observation(result, info)

        # Render if requested
        if self.render_mode == "human":
            self.render()

        return final_obs.to_array(), reward, True, False, vars(info)

    def render(self) -> Optional[str]:
        """Render the last fight result."""
        if self._last_info is None:
            return None

        info = self._last_info
        result_str = "WIN" if info.won else ("DRAW" if info.is_draw else "LOSS")

        output = (
            f"=== Fight Result ===\n"
            f"Outcome: {result_str}\n"
            f"Turns: {info.total_turns}\n"
            f"Damage Dealt: {info.damage_dealt}\n"
            f"Damage Taken: {info.damage_taken}\n"
            f"Final HP: {info.final_hp} (enemy: {info.enemy_final_hp})\n"
            f"Execution: {info.execution_time_ns / 1e6:.1f}ms\n"
        )

        if self.render_mode == "human":
            print(output)

        return output

    def close(self):
        """Clean up resources."""
        pass

    def _create_scenario(self, seed: int, action: int) -> Scenario:
        """Create a fight scenario based on config and action."""
        # Random starting positions (convert to Python int for JSON)
        cell1 = int(self._rng.integers(50, 200))
        cell2 = int(self._rng.integers(400, 560))

        agent = LeekConfig(
            id=1,
            name="Agent",
            farmer=1,
            team=1,
            ai=self.config.agent_ai,
            level=self.config.agent_level,
            life=self.config.agent_life,
            strength=self.config.agent_strength,
            tp=self.config.agent_tp,
            mp=self.config.agent_mp,
            weapons=self.config.agent_weapons,
            cell=cell1,
        )

        opponent = LeekConfig(
            id=2,
            name="Opponent",
            farmer=2,
            team=2,
            ai=self.config.opponent_ai,
            level=self.config.opponent_level,
            life=self.config.opponent_life,
            strength=self.config.opponent_strength,
            tp=self.config.opponent_tp,
            mp=self.config.opponent_mp,
            weapons=self.config.opponent_weapons,
            cell=cell2,
        )

        map_config = MapConfig(
            width=self.config.map_width,
            height=self.config.map_height,
        )

        return Scenario(
            team1=[agent],
            team2=[opponent],
            map=map_config,
            random_seed=seed,
            max_turns=self.config.max_turns,
        )

    def _extract_episode_info(self, result: FightResult) -> EpisodeInfo:
        """Extract episode information from fight result."""
        # Determine winner (team1 is agent)
        won = result.winner == 0
        is_draw = result.winner == -1

        # Sum damage from turns
        damage_dealt = sum(t.damage_dealt for t in result.turns if t.entity_id == 1)
        damage_taken = sum(t.damage_taken for t in result.turns if t.entity_id == 1)

        # Track HP through fight
        agent_hp = self.config.agent_life
        enemy_hp = self.config.opponent_life

        for turn in result.turns:
            if turn.entity_id == 1:
                agent_hp = max(0, agent_hp - turn.damage_taken)
                enemy_hp = max(0, enemy_hp - turn.damage_dealt)
            else:
                enemy_hp = max(0, enemy_hp - turn.damage_taken)
                agent_hp = max(0, agent_hp - turn.damage_dealt)

        return EpisodeInfo(
            won=won,
            is_draw=is_draw,
            total_turns=result.duration,
            damage_dealt=damage_dealt,
            damage_taken=damage_taken,
            final_hp=agent_hp,
            enemy_final_hp=enemy_hp,
            execution_time_ns=result.execution_time,
            fight_result=result,
        )

    def _create_outcome(self, result: FightResult, info: EpisodeInfo) -> FightOutcome:
        """Create FightOutcome for reward calculation."""
        # Count agent's turns
        agent_turns = [t for t in result.turns if t.entity_id == 1]
        total_tp_spent = sum(t.start_tp - t.end_tp for t in agent_turns)
        total_mp_spent = sum(t.start_mp - t.end_mp for t in agent_turns)
        total_tp_available = len(agent_turns) * self.config.agent_tp
        total_mp_available = len(agent_turns) * self.config.agent_mp

        # Check for kills
        kills = 1 if info.won and info.enemy_final_hp == 0 else 0

        return FightOutcome(
            won=info.won,
            is_draw=info.is_draw,
            total_damage_dealt=info.damage_dealt,
            total_damage_taken=info.damage_taken,
            turns_survived=len(agent_turns),
            total_turns=info.total_turns,
            kills=kills,
            total_tp_spent=total_tp_spent,
            total_mp_spent=total_mp_spent,
            total_tp_available=total_tp_available,
            total_mp_available=total_mp_available,
            final_hp=info.final_hp,
            initial_hp=self.config.agent_life,
            enemy_final_hp=info.enemy_final_hp,
            enemy_initial_hp=self.config.opponent_life,
        )

    def _create_final_observation(
        self,
        result: FightResult,
        info: EpisodeInfo,
    ) -> Observation:
        """Create final observation from fight result."""
        # Get last known positions from turns
        agent_cell = 0
        enemy_cell = 100

        for turn in result.turns:
            for action in turn.actions:
                if action.action_type == ActionType.MOVE_TO and action.target_cell:
                    if turn.entity_id == 1:
                        agent_cell = action.target_cell
                    else:
                        enemy_cell = action.target_cell

        distance = abs(agent_cell - enemy_cell)

        return ObservationSpace.from_fight_state(
            my_hp=info.final_hp,
            my_max_hp=self.config.agent_life,
            my_tp=0,  # End of fight
            my_mp=0,
            my_cell=agent_cell,
            enemy_hp=info.enemy_final_hp,
            enemy_max_hp=self.config.opponent_life,
            enemy_tp=0,
            enemy_mp=0,
            enemy_cell=enemy_cell,
            turn_number=info.total_turns,
            round_number=info.total_turns,
            max_turns=self.config.max_turns,
            distance=distance,
        )


# Convenience function for quick environment creation
def make_env(
    agent_ai: str = "test/ai/simple.leek",
    opponent_ai: str = "test/ai/simple.leek",
    seed: Optional[int] = None,
    render_mode: Optional[str] = None,
) -> LeekWarsEnv:
    """
    Create a LeekWars environment with default settings.

    Args:
        agent_ai: Path to agent's AI file
        opponent_ai: Path to opponent's AI file
        seed: Random seed
        render_mode: Render mode

    Returns:
        Configured LeekWarsEnv
    """
    config = EnvConfig(
        agent_ai=agent_ai,
        opponent_ai=opponent_ai,
    )
    return LeekWarsEnv(config=config, seed=seed, render_mode=render_mode)
