"""
K-Fold cross-validation trainer with GPU support.
"""

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from typing import Optional, Callable
from dataclasses import dataclass
import time
import numpy as np

from .model import WinPredictor
from .dataset import FightDataset, FightDataLoader


@dataclass
class FoldResult:
    """Results from training a single fold."""
    fold: int
    train_loss: float
    val_loss: float
    val_accuracy: float
    epochs_trained: int
    best_epoch: int


@dataclass
class KFoldResult:
    """Results from K-fold cross-validation."""
    fold_results: list[FoldResult]
    mean_accuracy: float
    std_accuracy: float
    mean_val_loss: float
    best_fold: int
    total_time: float

    def summary(self) -> str:
        """Get summary string."""
        return (
            f"K-Fold Results ({len(self.fold_results)} folds):\n"
            f"  Accuracy: {self.mean_accuracy*100:.2f}% ± {self.std_accuracy*100:.2f}%\n"
            f"  Val Loss: {self.mean_val_loss:.4f}\n"
            f"  Best Fold: {self.best_fold}\n"
            f"  Time: {self.total_time:.1f}s"
        )


class KFoldTrainer:
    """
    K-Fold cross-validation trainer with GPU support.

    Features:
    - Stratified k-fold splitting
    - Early stopping per fold
    - Mixed precision training
    - Progress callbacks for dashboard
    """

    def __init__(
        self,
        k: int = 5,
        epochs: int = 50,
        batch_size: int = 256,
        learning_rate: float = 0.001,
        early_stopping_patience: int = 5,
        device: Optional[torch.device] = None,
        use_amp: bool = True,
        num_workers: int = 0,
    ):
        self.k = k
        self.epochs = epochs
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.early_stopping_patience = early_stopping_patience
        self.num_workers = num_workers
        self.use_amp = use_amp

        # Setup device
        if device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = device

        # Multi-GPU setup
        self.n_gpus = torch.cuda.device_count() if torch.cuda.is_available() else 0

        # Progress callback
        self.progress_callback: Optional[Callable] = None

    def set_progress_callback(self, callback: Callable):
        """Set callback for progress updates (for dashboard)."""
        self.progress_callback = callback

    def _notify_progress(self, **kwargs):
        """Notify progress callback if set."""
        if self.progress_callback:
            self.progress_callback(**kwargs)

    def train_fold(
        self,
        fold: int,
        train_data: list[dict],
        val_data: list[dict],
        input_dim: int,
    ) -> tuple[FoldResult, WinPredictor]:
        """Train a single fold and return results + model."""

        # Create datasets
        train_dataset = FightDataset(train_data, device=self.device)
        val_dataset = FightDataset(val_data, device=self.device)

        train_loader = FightDataLoader.create(
            train_dataset,
            batch_size=self.batch_size,
            shuffle=True,
            num_workers=self.num_workers,
        )
        val_loader = FightDataLoader.create(
            val_dataset,
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=self.num_workers,
        )

        # Create model
        model = WinPredictor(input_dim=input_dim).to(self.device)

        # Multi-GPU
        if self.n_gpus > 1:
            model = nn.DataParallel(model)

        # Loss and optimizer (BCEWithLogitsLoss is AMP-safe)
        criterion = nn.BCEWithLogitsLoss()
        optimizer = optim.Adam(model.parameters(), lr=self.learning_rate)

        # Mixed precision scaler
        scaler = torch.amp.GradScaler() if self.use_amp and self.device.type == "cuda" else None

        # Training loop with early stopping
        best_val_loss = float("inf")
        best_val_accuracy = 0.0
        best_epoch = 0
        patience_counter = 0
        best_state = None

        for epoch in range(self.epochs):
            # Training
            model.train()
            train_loss = 0.0
            train_batches = 0

            for features, labels in train_loader:
                optimizer.zero_grad()

                if scaler is not None:
                    with torch.amp.autocast(device_type="cuda"):
                        outputs = model(features)
                        loss = criterion(outputs, labels)
                    scaler.scale(loss).backward()
                    scaler.step(optimizer)
                    scaler.update()
                else:
                    outputs = model(features)
                    loss = criterion(outputs, labels)
                    loss.backward()
                    optimizer.step()

                train_loss += loss.item()
                train_batches += 1

            train_loss /= train_batches

            # Validation
            model.eval()
            val_loss = 0.0
            val_correct = 0
            val_total = 0

            with torch.no_grad():
                for features, labels in val_loader:
                    outputs = model(features)
                    loss = criterion(outputs, labels)
                    val_loss += loss.item()

                    # Accuracy (outputs are logits, so threshold is 0)
                    predictions = (outputs > 0).float()
                    val_correct += (predictions == labels).sum().item()
                    val_total += labels.size(0)

            val_loss /= len(val_loader)
            val_accuracy = val_correct / val_total

            # Progress update
            self._notify_progress(
                fold=fold,
                epoch=epoch + 1,
                train_loss=train_loss,
                val_loss=val_loss,
                val_accuracy=val_accuracy,
            )

            # Early stopping check
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_val_accuracy = val_accuracy
                best_epoch = epoch + 1
                patience_counter = 0
                # Save best model state
                if self.n_gpus > 1:
                    best_state = model.module.state_dict().copy()
                else:
                    best_state = {k: v.clone() for k, v in model.state_dict().items()}
            else:
                patience_counter += 1
                if patience_counter >= self.early_stopping_patience:
                    break

        # Restore best model
        if best_state is not None:
            if self.n_gpus > 1:
                model.module.load_state_dict(best_state)
            else:
                model.load_state_dict(best_state)

        # Get base model (unwrap DataParallel)
        final_model = model.module if self.n_gpus > 1 else model

        result = FoldResult(
            fold=fold,
            train_loss=train_loss,
            val_loss=best_val_loss,
            val_accuracy=best_val_accuracy,
            epochs_trained=epoch + 1,
            best_epoch=best_epoch,
        )

        return result, final_model

    def train(
        self,
        data: list[dict],
        stratify: bool = True,
        seed: int = 42,
    ) -> tuple[KFoldResult, WinPredictor]:
        """
        Run K-fold cross-validation.

        Returns KFoldResult and the best model.
        """
        start_time = time.time()

        # Create k-fold splits
        splits = FightDataLoader.create_k_fold_splits(
            data,
            k=self.k,
            stratify=stratify,
            seed=seed,
        )

        # Determine input dimension
        input_dim = FightDataset([data[0]], device=self.device).input_dim

        # Train each fold
        fold_results = []
        best_fold = 0
        best_accuracy = 0.0
        best_model = None

        for i, (train_data, val_data) in enumerate(splits):
            self._notify_progress(
                phase="training",
                message=f"Training fold {i+1}/{self.k}...",
                current_fold=i + 1,
                total_folds=self.k,
            )

            result, model = self.train_fold(i + 1, train_data, val_data, input_dim)
            fold_results.append(result)

            if result.val_accuracy > best_accuracy:
                best_accuracy = result.val_accuracy
                best_fold = i + 1
                best_model = model

        # Calculate aggregate metrics
        accuracies = [r.val_accuracy for r in fold_results]
        val_losses = [r.val_loss for r in fold_results]

        total_time = time.time() - start_time

        kfold_result = KFoldResult(
            fold_results=fold_results,
            mean_accuracy=np.mean(accuracies),
            std_accuracy=np.std(accuracies),
            mean_val_loss=np.mean(val_losses),
            best_fold=best_fold,
            total_time=total_time,
        )

        self._notify_progress(
            phase="done",
            message=kfold_result.summary(),
        )

        return kfold_result, best_model

    def get_device_info(self) -> dict:
        """Get information about available devices."""
        info = {
            "device": str(self.device),
            "cuda_available": torch.cuda.is_available(),
            "n_gpus": self.n_gpus,
            "gpu_names": [],
            "use_amp": self.use_amp,
        }

        if torch.cuda.is_available():
            for i in range(self.n_gpus):
                info["gpu_names"].append(torch.cuda.get_device_name(i))

        return info
