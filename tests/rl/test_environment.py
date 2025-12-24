"""
Tests for the LeekWars RL environment.
"""

import pytest
import numpy as np

from src.rl.spaces import (
    ObservationSpace,
    ActionSpace,
    Observation,
    EntityObservation,
    FieldObservation,
    ACTIONS,
)
from src.rl.rewards import (
    RewardCalculator,
    RewardConfig,
    FightOutcome,
    AGGRESSIVE_REWARDS,
    DEFENSIVE_REWARDS,
)


class TestObservationSpace:
    """Tests for observation space."""

    def test_observation_dimension(self):
        """Test observation has correct dimension."""
        assert Observation.get_dimension() == 14

    def test_observation_to_array(self):
        """Test observation converts to numpy array."""
        obs = Observation(
            self_obs=EntityObservation(
                hp_ratio=0.8,
                tp=8,
                mp=2,
                cell=100,
                is_alive=True,
            ),
            enemy_obs=EntityObservation(
                hp_ratio=0.5,
                tp=10,
                mp=3,
                cell=300,
                is_alive=True,
            ),
            field_obs=FieldObservation(
                turn_number=10,
                round_number=5,
                max_turns=64,
                distance_to_enemy=15,
            ),
        )

        arr = obs.to_array()

        assert isinstance(arr, np.ndarray)
        assert arr.shape == (14,)
        assert arr.dtype == np.float32
        # Check values are normalized (0-1 range)
        assert np.all(arr >= 0.0)
        assert np.all(arr <= 1.0)

    def test_observation_from_fight_state(self):
        """Test creating observation from fight state."""
        obs = ObservationSpace.from_fight_state(
            my_hp=80,
            my_max_hp=100,
            my_tp=8,
            my_mp=2,
            my_cell=100,
            enemy_hp=50,
            enemy_max_hp=100,
            enemy_tp=10,
            enemy_mp=3,
            enemy_cell=300,
            turn_number=10,
            round_number=5,
            max_turns=64,
            distance=15,
        )

        assert obs.self_obs.hp_ratio == 0.8
        assert obs.enemy_obs.hp_ratio == 0.5
        assert obs.field_obs.turn_number == 10


class TestActionSpace:
    """Tests for action space."""

    def test_action_count(self):
        """Test we have expected number of actions."""
        space = ActionSpace()
        assert space.n_actions == 16

    def test_get_action(self):
        """Test getting action by ID."""
        space = ActionSpace()

        action = space.get_action(0)
        assert action.name == "move_toward"
        assert action.category == "move"

        action = space.get_action(4)
        assert action.name == "attack_weapon"
        assert action.category == "attack"

    def test_get_action_invalid(self):
        """Test invalid action ID raises error."""
        space = ActionSpace()

        with pytest.raises(ValueError):
            space.get_action(100)

    def test_get_actions_by_category(self):
        """Test filtering actions by category."""
        space = ActionSpace()

        move_actions = space.get_actions_by_category("move")
        assert len(move_actions) == 4

        attack_actions = space.get_actions_by_category("attack")
        assert len(attack_actions) == 4

    def test_sample(self):
        """Test random action sampling."""
        space = ActionSpace()

        for _ in range(100):
            action = space.sample()
            assert 0 <= action < space.n_actions

    def test_mask_invalid(self):
        """Test action masking."""
        space = ActionSpace()

        # Only movement valid
        valid_mask = np.array([1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        probs = space.mask_invalid(valid_mask)

        assert probs.sum() == pytest.approx(1.0)
        assert probs[0] == pytest.approx(0.25)
        assert probs[4] == 0.0


class TestRewardCalculator:
    """Tests for reward calculation."""

    def test_win_reward(self):
        """Test winning gives positive reward."""
        calc = RewardCalculator()

        outcome = FightOutcome(
            won=True,
            is_draw=False,
            total_damage_dealt=100,
            total_damage_taken=50,
            turns_survived=10,
            total_turns=15,
            kills=1,
            total_tp_spent=50,
            total_mp_spent=20,
            total_tp_available=100,
            total_mp_available=30,
            final_hp=50,
            initial_hp=100,
            enemy_final_hp=0,
            enemy_initial_hp=100,
        )

        reward = calc.calculate(outcome)
        assert reward > 0

    def test_loss_reward(self):
        """Test losing gives negative reward."""
        calc = RewardCalculator()

        outcome = FightOutcome(
            won=False,
            is_draw=False,
            total_damage_dealt=30,
            total_damage_taken=100,
            turns_survived=5,
            total_turns=10,
            kills=0,
            total_tp_spent=25,
            total_mp_spent=10,
            total_tp_available=50,
            total_mp_available=15,
            final_hp=0,
            initial_hp=100,
            enemy_final_hp=70,
            enemy_initial_hp=100,
        )

        reward = calc.calculate(outcome)
        assert reward < 0

    def test_draw_reward(self):
        """Test draw gives small positive reward."""
        calc = RewardCalculator()

        outcome = FightOutcome(
            won=False,
            is_draw=True,
            total_damage_dealt=50,
            total_damage_taken=50,
            turns_survived=64,
            total_turns=64,
            kills=0,
            total_tp_spent=100,
            total_mp_spent=50,
            total_tp_available=100,
            total_mp_available=50,
            final_hp=50,
            initial_hp=100,
            enemy_final_hp=50,
            enemy_initial_hp=100,
        )

        reward = calc.calculate(outcome)
        # Draw reward is positive but modest
        assert reward > -50

    def test_aggressive_rewards(self):
        """Test aggressive reward config."""
        calc = RewardCalculator(AGGRESSIVE_REWARDS)

        outcome = FightOutcome(
            won=True,
            is_draw=False,
            total_damage_dealt=150,
            total_damage_taken=30,
            turns_survived=5,
            total_turns=5,
            kills=1,
            total_tp_spent=40,
            total_mp_spent=10,
            total_tp_available=50,
            total_mp_available=15,
            final_hp=70,
            initial_hp=100,
            enemy_final_hp=0,
            enemy_initial_hp=100,
        )

        reward = calc.calculate(outcome)
        # High damage should give high reward with aggressive config
        assert reward > 150

    def test_step_reward(self):
        """Test per-step reward calculation."""
        calc = RewardCalculator()

        # Good turn: high damage, low cost
        reward = calc.calculate_step_reward(
            damage_dealt=30,
            damage_taken=10,
            tp_spent=3,
            mp_spent=2,
            got_kill=False,
        )
        assert reward > 0

        # Bad turn: low damage, high cost
        reward = calc.calculate_step_reward(
            damage_dealt=5,
            damage_taken=40,
            tp_spent=8,
            mp_spent=3,
            got_kill=False,
        )
        assert reward < 0


class TestRewardConfig:
    """Tests for reward configuration."""

    def test_default_config(self):
        """Test default reward values."""
        config = RewardConfig()

        assert config.win_reward == 100.0
        assert config.loss_reward == -80.0
        assert config.draw_reward == 10.0

    def test_custom_config(self):
        """Test custom reward configuration."""
        config = RewardConfig(
            win_reward=200.0,
            loss_reward=-50.0,
            damage_dealt_per_hp=0.5,
        )

        assert config.win_reward == 200.0
        assert config.loss_reward == -50.0
        assert config.damage_dealt_per_hp == 0.5


# Integration test that requires the generator
class TestEnvironmentIntegration:
    """Integration tests for the full environment."""

    @pytest.fixture
    def check_generator(self):
        """Skip if generator not available."""
        from src.localfight.runner import check_generator
        if not check_generator():
            pytest.skip("Generator not available")

    def test_env_creation(self, check_generator):
        """Test environment can be created."""
        from src.rl.environment import LeekWarsEnv

        env = LeekWarsEnv()
        assert env is not None
        assert env._obs_space.dim == 14
        assert env._action_space.n_actions == 16

    def test_env_reset(self, check_generator):
        """Test environment reset."""
        from src.rl.environment import LeekWarsEnv

        env = LeekWarsEnv(seed=42)
        obs, info = env.reset()

        assert isinstance(obs, np.ndarray)
        assert obs.shape == (14,)
        assert "episode" in info
        assert info["episode"] == 1

    def test_env_step(self, check_generator):
        """Test environment step (runs full fight)."""
        from src.rl.environment import LeekWarsEnv

        env = LeekWarsEnv(seed=42)
        obs, info = env.reset()

        # Take action (runs fight)
        obs, reward, terminated, truncated, info = env.step(0)

        assert isinstance(obs, np.ndarray)
        assert isinstance(reward, float)
        assert terminated is True  # Fight always terminates
        assert truncated is False
        assert "won" in info
        assert "total_turns" in info

    def test_env_deterministic(self, check_generator):
        """Test same seed produces same result."""
        from src.rl.environment import LeekWarsEnv

        # Run twice with same seed
        results = []
        for _ in range(2):
            env = LeekWarsEnv(seed=12345)
            env.reset()
            _, reward, _, _, info = env.step(0)
            results.append((reward, info["won"], info["total_turns"]))

        # Results should be identical
        assert results[0] == results[1]

    def test_env_render(self, check_generator):
        """Test environment rendering."""
        from src.rl.environment import LeekWarsEnv

        env = LeekWarsEnv(seed=42, render_mode="ansi")
        env.reset()
        env.step(0)

        output = env.render()
        assert output is not None
        assert "Fight Result" in output
