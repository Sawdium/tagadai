"""
NN Training management for dashboard integration.

Manages training of ActionScoringMLP from scraped fight data.
"""

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from collections import deque

from pydantic import BaseModel

from src.common.config import get_paths

# Get paths
_paths = get_paths()
NN_DIR = Path("data/nn")
NN_DIR.mkdir(parents=True, exist_ok=True)


class NNTrainingConfig(BaseModel):
    """Configuration for NN training."""
    max_level: int = 40
    fight_limit: Optional[int] = None
    epochs: int = 50
    batch_size: int = 64
    learning_rate: float = 0.001
    hidden1: int = 32
    hidden2: int = 16
    early_stopping_patience: int = 10


class NNTrainingState:
    """Current state of NN training."""

    def __init__(self):
        self.phase: str = "idle"  # idle, loading, training, done, error
        self.status_message: str = ""
        self.train_examples: int = 0
        self.val_examples: int = 0
        self.epoch: int = 0
        self.total_epochs: int = 0
        self.train_loss: float = 0.0
        self.val_loss: float = 0.0
        self.val_accuracy: float = 0.0
        self.best_val_loss: float = float('inf')
        self.best_epoch: int = 0
        self.learning_rate: float = 0.001
        self.epoch_time: float = 0.0
        self.total_time: float = 0.0
        self.eta_seconds: float = 0.0
        self.model_params: int = 0

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "status_message": self.status_message,
            "train_examples": self.train_examples,
            "val_examples": self.val_examples,
            "epoch": self.epoch,
            "total_epochs": self.total_epochs,
            "train_loss": round(self.train_loss, 6),
            "val_loss": round(self.val_loss, 6),
            "val_accuracy": round(self.val_accuracy * 100, 2),
            "best_val_loss": round(self.best_val_loss, 6) if self.best_val_loss != float('inf') else 0.0,
            "best_epoch": self.best_epoch,
            "learning_rate": self.learning_rate,
            "epoch_time": round(self.epoch_time, 2),
            "total_time": round(self.total_time, 2),
            "eta_seconds": round(self.eta_seconds, 1),
            "model_params": self.model_params,
        }


class NNTrainingManager:
    """Manages NN training lifecycle."""

    def __init__(self):
        self.is_running = False
        self.is_paused = False
        self.current_config: Optional[NNTrainingConfig] = None
        self.training_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused by default

        # State
        self.state = NNTrainingState()
        self.history: deque = deque(maxlen=500)

        # Model reference for saving/exporting
        self._model = None
        self._start_time: Optional[float] = None

    def start(self, config: NNTrainingConfig, metrics_collector) -> dict:
        """Start NN training with given configuration."""
        if self.is_running:
            return {"success": False, "error": "Training already in progress"}

        self.current_config = config
        self.is_running = True
        self.is_paused = False
        self._stop_event.clear()
        self._pause_event.set()

        # Reset state
        self.state = NNTrainingState()
        self.state.total_epochs = config.epochs
        self.history.clear()
        self._start_time = time.time()

        # Start training in background thread
        self.training_thread = threading.Thread(
            target=self._run_training,
            args=(config, metrics_collector),
            daemon=True
        )
        self.training_thread.start()

        return {"success": True, "message": "NN training started"}

    def pause(self) -> dict:
        """Pause/resume training."""
        if not self.is_running:
            return {"success": False, "error": "No training in progress"}

        if self.is_paused:
            self._pause_event.set()
            self.is_paused = False
            return {"success": True, "paused": False}
        else:
            self._pause_event.clear()
            self.is_paused = True
            return {"success": True, "paused": True}

    def stop(self) -> dict:
        """Stop training."""
        if not self.is_running:
            return {"success": False, "error": "No training in progress"}

        self._stop_event.set()
        self._pause_event.set()  # Unpause so thread can exit

        # Wait for thread to finish
        if self.training_thread:
            self.training_thread.join(timeout=5.0)

        self.is_running = False
        self.is_paused = False

        return {"success": True, "message": "Training stopped"}

    def save_model(self, name: Optional[str] = None) -> dict:
        """Save current model."""
        if self._model is None:
            return {"success": False, "error": "No model to save"}

        try:
            import torch

            if name is None:
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                name = f"model-{timestamp}"

            path = NN_DIR / f"{name}.pt"
            torch.save(self._model.state_dict(), path)

            return {"success": True, "name": name, "path": str(path)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def load_model(self, path: str) -> dict:
        """Load a model for export."""
        try:
            import torch
            from src.nn.model import ActionScoringMLP

            model_path = Path(path)
            if not model_path.exists():
                return {"success": False, "error": "Model file not found"}

            # Create model with default dims (will be overwritten)
            model = ActionScoringMLP()
            model.load_state_dict(torch.load(model_path))
            model.eval()

            self._model = model
            self.state.model_params = sum(p.numel() for p in model.parameters())

            return {"success": True, "path": str(model_path), "params": self.state.model_params}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def export_leekscript(self, output_dir: str = "tagadann/NN") -> dict:
        """Export model to LeekScript."""
        if self._model is None:
            return {"success": False, "error": "No model loaded"}

        try:
            from src.nn.export import export_all

            paths = export_all(self._model, output_dir)
            return {"success": True, "files": paths}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_models(self) -> list[dict]:
        """List saved models."""
        models = []
        for path in NN_DIR.glob("*.pt"):
            stat = path.stat()
            models.append({
                "name": path.stem,
                "path": str(path),
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            })
        models.sort(key=lambda x: x["created_at"], reverse=True)
        return models

    def delete_model(self, name: str) -> dict:
        """Delete a saved model."""
        path = NN_DIR / f"{name}.pt"
        if path.exists():
            path.unlink()
            return {"success": True}
        return {"success": False, "error": "Model not found"}

    def get_data_info(self) -> dict:
        """Get info about available training data."""
        try:
            import sqlite3
            from src.scraper.db import DEFAULT_DB_PATH

            conn = sqlite3.connect(DEFAULT_DB_PATH)
            cur = conn.cursor()

            # Count fights by type and level
            cur.execute('''
                SELECT
                    fight_type,
                    COUNT(*) as count,
                    AVG(team1_levels) as avg_level
                FROM fights
                WHERE context = 2
                GROUP BY fight_type
            ''')

            type_stats = {}
            for row in cur.fetchall():
                type_name = {0: "solo", 1: "farmer", 2: "team"}.get(row[0], f"type_{row[0]}")
                type_stats[type_name] = {
                    "count": row[1],
                    "avg_level": round(row[2] or 0, 1)
                }

            # Count low-level solo fights
            cur.execute('''
                SELECT COUNT(*)
                FROM fights
                WHERE fight_type = 0
                AND context = 2
                AND team1_levels <= 40
                AND team2_levels <= 40
            ''')
            low_level_count = cur.fetchone()[0]

            conn.close()

            return {
                "success": True,
                "types": type_stats,
                "low_level_solo": low_level_count,
                "db_path": str(DEFAULT_DB_PATH)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_state(self) -> dict:
        """Get current training state."""
        return self.state.to_dict()

    def get_history(self) -> list[dict]:
        """Get training history."""
        return list(self.history)

    def _run_training(self, config: NNTrainingConfig, metrics_collector):
        """Run the NN training loop (called in background thread)."""
        try:
            import torch
            from torch.utils.data import DataLoader
            from torch.optim import Adam
            from torch.optim.lr_scheduler import ReduceLROnPlateau

            from src.nn.dataset import load_dataset, collate_fn
            from src.nn.model import ActionScoringMLP, RankingLoss

            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

            # Phase 1: Load data
            self.state.phase = "loading"
            self.state.status_message = f"Loading data (max_level={config.max_level})..."

            train_ds, val_ds = load_dataset(
                fight_type=0,
                max_level=config.max_level,
                limit=config.fight_limit,
                train_ratio=0.8,
            )

            self.state.train_examples = len(train_ds)
            self.state.val_examples = len(val_ds)
            self.state.status_message = f"Loaded {len(train_ds) + len(val_ds)} examples"

            if self._stop_event.is_set():
                self.state.phase = "stopped"
                return

            train_loader = DataLoader(
                train_ds,
                batch_size=config.batch_size,
                shuffle=True,
                collate_fn=collate_fn,
            )
            val_loader = DataLoader(
                val_ds,
                batch_size=config.batch_size,
                shuffle=False,
                collate_fn=collate_fn,
            )

            # Phase 2: Create model
            model = ActionScoringMLP(
                state_dim=23,
                action_dim=34,
                hidden1=config.hidden1,
                hidden2=config.hidden2,
            ).to(device)

            self.state.model_params = sum(p.numel() for p in model.parameters())
            self._model = model

            # Training setup
            criterion = RankingLoss()
            optimizer = Adam(model.parameters(), lr=config.learning_rate)
            scheduler = ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=5)

            best_val_loss = float('inf')
            best_epoch = 0
            patience_counter = 0

            # Phase 3: Training loop
            self.state.phase = "training"
            self.state.status_message = "Training..."

            for epoch in range(config.epochs):
                if self._stop_event.is_set():
                    break

                self._pause_event.wait()

                epoch_start = time.time()

                # Train epoch
                model.train()
                total_loss = 0.0
                num_batches = 0

                for state_batch, action_batch, label_batch in train_loader:
                    if self._stop_event.is_set():
                        break

                    state_batch = state_batch.to(device)
                    action_batch = action_batch.to(device)
                    label_batch = label_batch.to(device)

                    optimizer.zero_grad()
                    scores = model(state_batch, action_batch)
                    loss = criterion(scores, label_batch)
                    loss.backward()
                    optimizer.step()

                    total_loss += loss.item()
                    num_batches += 1

                train_loss = total_loss / max(num_batches, 1)

                # Validate
                model.eval()
                val_loss_sum = 0.0
                correct = 0
                total = 0

                with torch.no_grad():
                    for state_batch, action_batch, label_batch in val_loader:
                        state_batch = state_batch.to(device)
                        action_batch = action_batch.to(device)
                        label_batch = label_batch.to(device)

                        scores = model(state_batch, action_batch)
                        loss = criterion(scores, label_batch)

                        val_loss_sum += loss.item()

                        preds = (scores > 0).float()
                        correct += (preds == label_batch).sum().item()
                        total += label_batch.size(0)

                val_loss = val_loss_sum / max(len(val_loader), 1)
                val_accuracy = correct / max(total, 1)

                scheduler.step(val_loss)

                epoch_time = time.time() - epoch_start
                total_time = time.time() - self._start_time
                remaining_epochs = config.epochs - epoch - 1
                eta = epoch_time * remaining_epochs

                # Update state
                self.state.epoch = epoch + 1
                self.state.train_loss = train_loss
                self.state.val_loss = val_loss
                self.state.val_accuracy = val_accuracy
                self.state.learning_rate = optimizer.param_groups[0]['lr']
                self.state.epoch_time = epoch_time
                self.state.total_time = total_time
                self.state.eta_seconds = eta

                # Track best
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    best_epoch = epoch + 1
                    self.state.best_val_loss = best_val_loss
                    self.state.best_epoch = best_epoch
                    patience_counter = 0

                    # Save best model
                    torch.save(model.state_dict(), NN_DIR / "best_model.pt")
                else:
                    patience_counter += 1

                # Add to history
                self.history.append({
                    "epoch": epoch + 1,
                    "train_loss": train_loss,
                    "val_loss": val_loss,
                    "val_accuracy": val_accuracy,
                    "learning_rate": self.state.learning_rate,
                })

                # Early stopping
                if patience_counter >= config.early_stopping_patience:
                    self.state.status_message = f"Early stopping at epoch {epoch + 1}"
                    break

            if self._stop_event.is_set():
                self.state.phase = "stopped"
                self.state.status_message = "Training stopped by user"
            else:
                # Load best model
                model.load_state_dict(torch.load(NN_DIR / "best_model.pt"))
                self._model = model

                self.state.phase = "done"
                self.state.status_message = f"Done! Best val loss: {best_val_loss:.4f} at epoch {best_epoch}"

        except Exception as e:
            self.state.phase = "error"
            self.state.status_message = str(e)
            import traceback
            traceback.print_exc()

        finally:
            self.is_running = False
            self.is_paused = False


# Global manager instance
nn_training_manager = NNTrainingManager()
