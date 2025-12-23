"""
Neural network models for win prediction.
"""

import torch
import torch.nn as nn


class WinPredictor(nn.Module):
    """
    Simple MLP for predicting win probability from game state.

    Input: State features (normalized)
    Output: Win probability [0, 1]
    """

    def __init__(
        self,
        input_dim: int = 9,
        hidden_dims: list[int] = [64, 32],
        dropout: float = 0.2,
    ):
        super().__init__()

        self.input_dim = input_dim
        self.hidden_dims = hidden_dims

        # Build layers
        layers = []
        prev_dim = input_dim

        for hidden_dim in hidden_dims:
            layers.extend([
                nn.Linear(prev_dim, hidden_dim),
                nn.ReLU(),
                nn.Dropout(dropout),
            ])
            prev_dim = hidden_dim

        # Output layer (single logit - no sigmoid for AMP compatibility)
        layers.append(nn.Linear(prev_dim, 1))

        self.network = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass - returns logits for training."""
        return self.network(x).squeeze(-1)

    def forward_probs(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass - returns probabilities for inference."""
        return torch.sigmoid(self.forward(x))

    def predict(self, x: torch.Tensor) -> torch.Tensor:
        """Predict probabilities with no gradients."""
        self.eval()
        with torch.no_grad():
            return self.forward_probs(x)

    def get_config(self) -> dict:
        """Get model configuration for saving."""
        return {
            "input_dim": self.input_dim,
            "hidden_dims": self.hidden_dims,
        }

    @classmethod
    def from_config(cls, config: dict) -> "WinPredictor":
        """Create model from config."""
        return cls(
            input_dim=config["input_dim"],
            hidden_dims=config["hidden_dims"],
        )


class StateEncoder:
    """
    Encode game state into normalized features for the model.

    Phase 8 (1v1 Pistol) features:
    - my_hp_ratio: my_hp / 100
    - my_tp_ratio: my_tp / 10
    - my_mp_ratio: my_mp / 3
    - enemy_hp_ratio: enemy_hp / 100
    - distance_norm: distance / 30
    - hp_advantage: (my_hp - enemy_hp) / 100
    - in_range: 1 if distance <= 7 else 0
    - enemy_in_range: 1 if distance <= 7 else 0
    - turn_progress: turn_number / 64
    """

    # Pistol range
    PISTOL_RANGE = 7
    MAX_HP = 100
    MAX_TP = 10
    MAX_MP = 3
    MAX_DISTANCE = 30
    MAX_TURNS = 64

    @classmethod
    def encode(
        cls,
        my_hp: int,
        my_tp: int,
        my_mp: int,
        enemy_hp: int,
        distance: int,
        turn_number: int,
    ) -> list[float]:
        """Encode state into normalized features."""
        in_range = 1.0 if distance <= cls.PISTOL_RANGE else 0.0

        return [
            my_hp / cls.MAX_HP,
            my_tp / cls.MAX_TP,
            my_mp / cls.MAX_MP,
            enemy_hp / cls.MAX_HP,
            min(distance, cls.MAX_DISTANCE) / cls.MAX_DISTANCE,
            (my_hp - enemy_hp) / cls.MAX_HP,
            in_range,
            in_range,  # Same for enemy in this simple case
            turn_number / cls.MAX_TURNS,
        ]

    @classmethod
    def feature_names(cls) -> list[str]:
        """Get feature names for interpretability."""
        return [
            "my_hp_ratio",
            "my_tp_ratio",
            "my_mp_ratio",
            "enemy_hp_ratio",
            "distance_norm",
            "hp_advantage",
            "in_range",
            "enemy_in_range",
            "turn_progress",
        ]
