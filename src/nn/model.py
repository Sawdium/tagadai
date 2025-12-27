"""
Neural network model for action scoring.

Simple MLP that takes (state_features, action_features) and outputs a score.
Designed to be easily exportable to LeekScript.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F

from .features import FeatureExtractor


class ActionScoringMLP(nn.Module):
    """
    MLP for scoring (state, action) pairs.

    Architecture: concat(state, action) → Dense → ReLU → Dense → ReLU → Dense → score

    Designed to be small enough to run in LeekScript:
    - ~57 input features
    - 32 hidden units (layer 1)
    - 16 hidden units (layer 2)
    - 1 output (score)

    Total parameters: ~2,500
    """

    def __init__(
        self,
        state_dim: int = 23,
        action_dim: int = 34,
        hidden1: int = 32,
        hidden2: int = 16,
    ):
        super().__init__()

        input_dim = state_dim + action_dim

        self.fc1 = nn.Linear(input_dim, hidden1)
        self.fc2 = nn.Linear(hidden1, hidden2)
        self.fc3 = nn.Linear(hidden2, 1)

        # Store dimensions for export
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.hidden1 = hidden1
        self.hidden2 = hidden2

    def forward(
        self,
        state: torch.Tensor,
        action: torch.Tensor,
    ) -> torch.Tensor:
        """
        Forward pass.

        Args:
            state: (batch, state_dim) state features
            action: (batch, action_dim) action features

        Returns:
            (batch,) scores
        """
        x = torch.cat([state, action], dim=-1)
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = self.fc3(x)
        return x.squeeze(-1)

    def score_actions(
        self,
        state: torch.Tensor,
        actions: list[torch.Tensor],
    ) -> torch.Tensor:
        """
        Score multiple actions for the same state.

        Args:
            state: (state_dim,) single state
            actions: list of (action_dim,) action tensors

        Returns:
            (num_actions,) scores
        """
        # Expand state to match number of actions
        num_actions = len(actions)
        states = state.unsqueeze(0).expand(num_actions, -1)
        actions_batch = torch.stack(actions)

        return self.forward(states, actions_batch)

    def get_weights(self) -> dict:
        """
        Get weights as numpy arrays for export.

        Returns dict with:
            W1, b1: Layer 1 weights/bias
            W2, b2: Layer 2 weights/bias
            W3, b3: Output layer weights/bias
        """
        return {
            'W1': self.fc1.weight.detach().cpu().numpy(),
            'b1': self.fc1.bias.detach().cpu().numpy(),
            'W2': self.fc2.weight.detach().cpu().numpy(),
            'b2': self.fc2.bias.detach().cpu().numpy(),
            'W3': self.fc3.weight.detach().cpu().numpy(),
            'b3': self.fc3.bias.detach().cpu().numpy(),
        }

    @staticmethod
    def from_weights(weights: dict) -> 'ActionScoringMLP':
        """Create model from weight dict."""
        hidden1 = weights['W1'].shape[0]
        hidden2 = weights['W2'].shape[0]
        input_dim = weights['W1'].shape[1]

        # Infer dimensions
        state_dim = 23  # Default
        action_dim = input_dim - state_dim

        model = ActionScoringMLP(
            state_dim=state_dim,
            action_dim=action_dim,
            hidden1=hidden1,
            hidden2=hidden2,
        )

        model.fc1.weight.data = torch.tensor(weights['W1'])
        model.fc1.bias.data = torch.tensor(weights['b1'])
        model.fc2.weight.data = torch.tensor(weights['W2'])
        model.fc2.bias.data = torch.tensor(weights['b2'])
        model.fc3.weight.data = torch.tensor(weights['W3'])
        model.fc3.bias.data = torch.tensor(weights['b3'])

        return model


class RankingLoss(nn.Module):
    """
    Ranking loss for training action scoring.

    Given positive and negative examples, learn to rank positives higher.
    """

    def __init__(self, margin: float = 1.0):
        super().__init__()
        self.margin = margin

    def forward(
        self,
        scores: torch.Tensor,
        labels: torch.Tensor,
    ) -> torch.Tensor:
        """
        Compute ranking loss.

        For simplicity, we use binary cross-entropy with logits.
        The model should predict high scores for label=1, low for label=0.
        """
        return F.binary_cross_entropy_with_logits(scores, labels)
