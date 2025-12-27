"""
PyTorch Dataset for training the action scoring network.
"""

from dataclasses import dataclass
from typing import Optional, Iterator
import json
import sqlite3
import random

import torch
from torch.utils.data import Dataset, IterableDataset

from .replay import TrainingExample, FightReplayer
from .features import FeatureExtractor
from src.scraper.db import DEFAULT_DB_PATH


class ActionScoringDataset(Dataset):
    """
    In-memory dataset for action scoring.

    Loads all examples into memory for fast training.
    """

    def __init__(
        self,
        examples: list[TrainingExample],
        balance_classes: bool = True,
    ):
        """
        Args:
            examples: List of training examples
            balance_classes: If True, undersample to balance positive/negative
        """
        self.examples = examples

        if balance_classes:
            self._balance_classes()

        # Pre-compute tensors
        self.state_features = torch.tensor(
            [ex.state_features for ex in self.examples],
            dtype=torch.float32
        )
        self.action_features = torch.tensor(
            [ex.action_features for ex in self.examples],
            dtype=torch.float32
        )
        self.labels = torch.tensor(
            [ex.label for ex in self.examples],
            dtype=torch.float32
        )

    def _balance_classes(self):
        """Undersample majority class to balance dataset."""
        positive = [ex for ex in self.examples if ex.label > 0.5]
        negative = [ex for ex in self.examples if ex.label <= 0.5]

        if len(positive) == 0 or len(negative) == 0:
            return

        # Undersample majority
        if len(positive) < len(negative):
            negative = random.sample(negative, len(positive))
        else:
            positive = random.sample(positive, len(negative))

        self.examples = positive + negative
        random.shuffle(self.examples)

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        return (
            self.state_features[idx],
            self.action_features[idx],
            self.labels[idx],
        )


class FightIterableDataset(IterableDataset):
    """
    Streaming dataset that loads fights on-demand.

    Better for large datasets that don't fit in memory.
    """

    def __init__(
        self,
        fight_type: int = 0,
        max_level: int = 40,
        limit: Optional[int] = None,
        shuffle_fights: bool = True,
    ):
        self.fight_type = fight_type
        self.max_level = max_level
        self.limit = limit
        self.shuffle_fights = shuffle_fights
        self.replayer = FightReplayer()

    def __iter__(self) -> Iterator[tuple[torch.Tensor, torch.Tensor, torch.Tensor]]:
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
        params = [self.fight_type, self.max_level, self.max_level]

        if self.limit:
            query += ' LIMIT ?'
            params.append(self.limit)

        cur.execute(query, params)
        fights = cur.fetchall()
        conn.close()

        if self.shuffle_fights:
            random.shuffle(fights)

        for fight_id, json_data in fights:
            if isinstance(json_data, str):
                data = json.loads(json_data)
            else:
                data = json_data

            for ex in self.replayer.replay_fight(fight_id, data):
                state = torch.tensor(ex.state_features, dtype=torch.float32)
                action = torch.tensor(ex.action_features, dtype=torch.float32)
                label = torch.tensor(ex.label, dtype=torch.float32)
                yield state, action, label


def load_dataset(
    fight_type: int = 0,
    max_level: int = 40,
    limit: Optional[int] = None,
    train_ratio: float = 0.8,
) -> tuple[ActionScoringDataset, ActionScoringDataset]:
    """
    Load and split dataset into train/val.

    Args:
        fight_type: 0 for solo fights
        max_level: Maximum leek level
        limit: Maximum fights to load
        train_ratio: Fraction for training

    Returns:
        (train_dataset, val_dataset)
    """
    from .replay import extract_training_data

    print(f"Loading examples from fights (type={fight_type}, max_level={max_level})...")
    examples = list(extract_training_data(None, fight_type, max_level, limit))
    print(f"Loaded {len(examples)} examples")

    # Split
    random.shuffle(examples)
    split_idx = int(len(examples) * train_ratio)
    train_examples = examples[:split_idx]
    val_examples = examples[split_idx:]

    print(f"Train: {len(train_examples)}, Val: {len(val_examples)}")

    train_ds = ActionScoringDataset(train_examples, balance_classes=False)
    val_ds = ActionScoringDataset(val_examples, balance_classes=False)

    return train_ds, val_ds


def collate_fn(
    batch: list[tuple[torch.Tensor, torch.Tensor, torch.Tensor]]
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Collate function for DataLoader."""
    states = torch.stack([b[0] for b in batch])
    actions = torch.stack([b[1] for b in batch])
    labels = torch.stack([b[2] for b in batch])
    return states, actions, labels
