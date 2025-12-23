"""
AI version management and registry.
"""

import json
import torch
import shutil
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
import uuid

from .model import WinPredictor


@dataclass
class AIVersion:
    """Represents a trained AI version."""

    id: str
    name: str
    created_at: str
    parent_version: Optional[str] = None

    # Training config
    training_fights: int = 0
    epochs: int = 0
    k_folds: int = 5
    batch_size: int = 256
    learning_rate: float = 0.001

    # Model config
    input_dim: int = 9
    hidden_dims: list[int] = field(default_factory=lambda: [64, 32])

    # Performance metrics
    accuracy: float = 0.0
    accuracy_std: float = 0.0
    val_loss: float = 0.0

    # Arena metrics
    elo_rating: float = 1500.0
    arena_wins: int = 0
    arena_losses: int = 0
    arena_draws: int = 0

    # Paths
    model_path: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AIVersion":
        """Create from dictionary."""
        return cls(**data)

    @property
    def arena_games(self) -> int:
        return self.arena_wins + self.arena_losses + self.arena_draws

    @property
    def arena_win_rate(self) -> float:
        if self.arena_games == 0:
            return 0.0
        return self.arena_wins / self.arena_games

    def summary(self) -> str:
        """Get summary string."""
        return (
            f"{self.name} (v{self.id[:8]})\n"
            f"  Accuracy: {self.accuracy*100:.2f}% ± {self.accuracy_std*100:.2f}%\n"
            f"  Elo: {self.elo_rating:.0f}\n"
            f"  Arena: {self.arena_wins}W/{self.arena_losses}L/{self.arena_draws}D"
        )


class VersionRegistry:
    """
    Registry for managing AI versions.

    Stores versions and models in a directory structure:
    models/
    ├── registry.json       # Version metadata
    └── versions/
        ├── abc123/
        │   └── model.pt    # Saved model weights
        └── def456/
            └── model.pt
    """

    def __init__(self, base_path: str = "models"):
        self.base_path = Path(base_path)
        self.versions_path = self.base_path / "versions"
        self.registry_file = self.base_path / "registry.json"

        # Ensure directories exist
        self.versions_path.mkdir(parents=True, exist_ok=True)

        # Load existing registry
        self.versions: dict[str, AIVersion] = {}
        self._load_registry()

    def _load_registry(self):
        """Load registry from disk."""
        if self.registry_file.exists():
            with open(self.registry_file) as f:
                data = json.load(f)
                for v_data in data.get("versions", []):
                    version = AIVersion.from_dict(v_data)
                    self.versions[version.id] = version

    def _save_registry(self):
        """Save registry to disk."""
        data = {
            "versions": [v.to_dict() for v in self.versions.values()],
            "updated_at": datetime.now().isoformat(),
        }
        with open(self.registry_file, "w") as f:
            json.dump(data, f, indent=2)

    def create_version(
        self,
        name: str,
        model: WinPredictor,
        training_fights: int,
        accuracy: float,
        accuracy_std: float,
        val_loss: float,
        epochs: int = 0,
        k_folds: int = 5,
        batch_size: int = 256,
        learning_rate: float = 0.001,
        parent_version: Optional[str] = None,
    ) -> AIVersion:
        """
        Create and save a new AI version.

        Args:
            name: Human-readable name
            model: Trained model to save
            training_fights: Number of fights used for training
            accuracy: Cross-validation accuracy
            accuracy_std: Standard deviation of accuracy
            val_loss: Validation loss
            epochs: Training epochs
            k_folds: Number of CV folds
            batch_size: Batch size used
            learning_rate: Learning rate used
            parent_version: ID of parent version (if any)

        Returns:
            Created AIVersion
        """
        # Generate unique ID
        version_id = str(uuid.uuid4())[:8]

        # Create version directory
        version_dir = self.versions_path / version_id
        version_dir.mkdir(exist_ok=True)

        # Save model
        model_path = version_dir / "model.pt"
        torch.save({
            "state_dict": model.state_dict(),
            "config": model.get_config(),
        }, model_path)

        # Create version record
        version = AIVersion(
            id=version_id,
            name=name,
            created_at=datetime.now().isoformat(),
            parent_version=parent_version,
            training_fights=training_fights,
            epochs=epochs,
            k_folds=k_folds,
            batch_size=batch_size,
            learning_rate=learning_rate,
            input_dim=model.input_dim,
            hidden_dims=model.hidden_dims,
            accuracy=accuracy,
            accuracy_std=accuracy_std,
            val_loss=val_loss,
            model_path=str(model_path),
        )

        # Add to registry
        self.versions[version_id] = version
        self._save_registry()

        return version

    def get_version(self, version_id: str) -> Optional[AIVersion]:
        """Get version by ID."""
        return self.versions.get(version_id)

    def get_version_by_name(self, name: str) -> Optional[AIVersion]:
        """Get version by name (returns latest if multiple)."""
        matches = [v for v in self.versions.values() if v.name == name]
        if not matches:
            return None
        return max(matches, key=lambda v: v.created_at)

    def load_model(self, version_id: str) -> Optional[WinPredictor]:
        """Load model for a version."""
        version = self.versions.get(version_id)
        if version is None:
            return None

        model_path = Path(version.model_path)
        if not model_path.exists():
            return None

        checkpoint = torch.load(model_path, weights_only=True)
        model = WinPredictor.from_config(checkpoint["config"])
        model.load_state_dict(checkpoint["state_dict"])

        return model

    def list_versions(self, sort_by: str = "created_at") -> list[AIVersion]:
        """List all versions, sorted by specified field."""
        versions = list(self.versions.values())

        if sort_by == "created_at":
            versions.sort(key=lambda v: v.created_at, reverse=True)
        elif sort_by == "accuracy":
            versions.sort(key=lambda v: v.accuracy, reverse=True)
        elif sort_by == "elo_rating":
            versions.sort(key=lambda v: v.elo_rating, reverse=True)
        elif sort_by == "name":
            versions.sort(key=lambda v: v.name)

        return versions

    def update_arena_stats(
        self,
        version_id: str,
        wins: int = 0,
        losses: int = 0,
        draws: int = 0,
        elo_delta: float = 0.0,
    ):
        """Update arena statistics for a version."""
        version = self.versions.get(version_id)
        if version:
            version.arena_wins += wins
            version.arena_losses += losses
            version.arena_draws += draws
            version.elo_rating += elo_delta
            self._save_registry()

    def delete_version(self, version_id: str) -> bool:
        """Delete a version and its model files."""
        version = self.versions.get(version_id)
        if version is None:
            return False

        # Delete model directory
        version_dir = self.versions_path / version_id
        if version_dir.exists():
            shutil.rmtree(version_dir)

        # Remove from registry
        del self.versions[version_id]
        self._save_registry()

        return True

    def get_champion(self) -> Optional[AIVersion]:
        """Get the version with highest Elo rating."""
        if not self.versions:
            return None
        return max(self.versions.values(), key=lambda v: v.elo_rating)

    def get_stats(self) -> dict:
        """Get registry statistics."""
        versions = list(self.versions.values())
        return {
            "total_versions": len(versions),
            "champion": self.get_champion().name if self.get_champion() else None,
            "highest_accuracy": max((v.accuracy for v in versions), default=0),
            "highest_elo": max((v.elo_rating for v in versions), default=1500),
            "total_arena_games": sum(v.arena_games for v in versions) // 2,
        }
