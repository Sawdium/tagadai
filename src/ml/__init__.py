"""
ML training module for TagadAI.

Provides neural network training infrastructure with:
- K-fold cross-validation
- AI version management
- Arena for version battles
- GPU parallelization
"""

from .model import WinPredictor
from .dataset import FightDataset
from .trainer import KFoldTrainer
from .version import AIVersion, VersionRegistry
from .arena import Arena

__all__ = [
    "WinPredictor",
    "FightDataset",
    "KFoldTrainer",
    "AIVersion",
    "VersionRegistry",
    "Arena",
]
