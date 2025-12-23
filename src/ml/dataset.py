"""
PyTorch dataset for fight training data.
"""

import torch
from torch.utils.data import Dataset, DataLoader
from typing import Optional
import numpy as np

from .model import StateEncoder


class FightDataset(Dataset):
    """
    Dataset of fight states and outcomes.

    Each sample contains:
    - features: Normalized state features
    - label: 1 if won, 0 if lost
    """

    def __init__(
        self,
        states: list[dict],
        device: Optional[torch.device] = None,
    ):
        """
        Initialize dataset from list of state dicts.

        Each state dict should have:
        - my_hp, my_tp, my_mp: int
        - enemy_hp: int
        - distance: int
        - turn_number: int
        - won: bool
        """
        self.device = device or torch.device("cpu")

        # Encode all states
        features = []
        labels = []

        for state in states:
            encoded = StateEncoder.encode(
                my_hp=state["my_hp"],
                my_tp=state["my_tp"],
                my_mp=state["my_mp"],
                enemy_hp=state["enemy_hp"],
                distance=state["distance"],
                turn_number=state["turn_number"],
            )
            features.append(encoded)
            labels.append(1.0 if state["won"] else 0.0)

        self.features = torch.tensor(features, dtype=torch.float32, device=self.device)
        self.labels = torch.tensor(labels, dtype=torch.float32, device=self.device)

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        return self.features[idx], self.labels[idx]

    @property
    def input_dim(self) -> int:
        return self.features.shape[1]

    @property
    def win_rate(self) -> float:
        return self.labels.mean().item()


class FightDataLoader:
    """
    Helper class to create DataLoaders with proper settings.
    """

    @staticmethod
    def create(
        dataset: FightDataset,
        batch_size: int = 256,
        shuffle: bool = True,
        num_workers: int = 0,
        pin_memory: bool = False,
    ) -> DataLoader:
        """Create a DataLoader for the dataset."""
        return DataLoader(
            dataset,
            batch_size=batch_size,
            shuffle=shuffle,
            num_workers=num_workers,
            pin_memory=pin_memory,
        )

    @staticmethod
    def create_k_fold_splits(
        states: list[dict],
        k: int = 5,
        stratify: bool = True,
        seed: int = 42,
    ) -> list[tuple[list[dict], list[dict]]]:
        """
        Split data into k folds for cross-validation.

        Returns list of (train_states, val_states) tuples.
        """
        rng = np.random.RandomState(seed)

        if stratify:
            # Separate wins and losses for stratified splitting
            wins = [s for s in states if s["won"]]
            losses = [s for s in states if not s["won"]]

            # Shuffle each group
            rng.shuffle(wins)
            rng.shuffle(losses)

            # Split each group into k folds
            win_folds = np.array_split(wins, k)
            loss_folds = np.array_split(losses, k)

            # Combine folds
            folds = []
            for i in range(k):
                fold = list(win_folds[i]) + list(loss_folds[i])
                rng.shuffle(fold)
                folds.append(fold)
        else:
            # Simple random split
            indices = list(range(len(states)))
            rng.shuffle(indices)
            fold_indices = np.array_split(indices, k)
            folds = [[states[i] for i in fold] for fold in fold_indices]

        # Create train/val pairs
        splits = []
        for i in range(k):
            val_data = folds[i]
            train_data = []
            for j in range(k):
                if j != i:
                    train_data.extend(folds[j])
            splits.append((train_data, val_data))

        return splits


def states_from_training_examples(examples: list) -> list[dict]:
    """
    Convert TrainingExample objects to state dicts for the dataset.

    Handles the output from parser.extract_training_data().
    """
    states = []
    for ex in examples:
        states.append({
            "my_hp": ex.my_hp,
            "my_tp": ex.my_tp,
            "my_mp": ex.my_mp,
            "enemy_hp": ex.enemy_hp,
            "distance": ex.distance,
            "turn_number": ex.turn_number,
            "won": ex.won,
        })
    return states
