"""
Neural Network training infrastructure for LeekWars AI.

This module provides:
- Item property extraction (items.py)
- State/Action feature extraction (features.py)
- Fight replay for training data (replay.py)
- PyTorch dataset and model (dataset.py, model.py)
- Training loop (train.py)
- Export to LeekScript (export.py)

Usage:
    # Train model on low-level solo fights
    python -m src.nn.train --max-level 40 --epochs 50 --limit 1000

    # Export to LeekScript
    python -m src.nn.export --model data/nn/model.pt --output tagadann/NN
"""

from .items import ItemProperties, get_item_properties
from .features import FeatureExtractor, StateFeatures, ActionFeatures
from .replay import FightReplayer, TrainingExample
from .dataset import ActionScoringDataset, load_dataset
from .model import ActionScoringMLP, RankingLoss
from .train import train
from .export import export_all, export_to_leekscript

__all__ = [
    'ItemProperties',
    'get_item_properties',
    'FeatureExtractor',
    'StateFeatures',
    'ActionFeatures',
    'FightReplayer',
    'TrainingExample',
    'ActionScoringDataset',
    'load_dataset',
    'ActionScoringMLP',
    'RankingLoss',
    'train',
    'export_all',
    'export_to_leekscript',
]
