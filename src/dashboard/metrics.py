"""
Metrics collection and storage for training visualization.
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Optional, Callable
from collections import deque
import json


@dataclass
class TrainingMetrics:
    """Current state of training metrics."""

    # Fight generation
    fights_generated: int = 0
    fights_target: int = 0
    fights_per_second: float = 0.0
    team1_wins: int = 0
    team2_wins: int = 0
    draws: int = 0

    # Training
    epoch: int = 0
    total_epochs: int = 0
    step: int = 0
    total_steps: int = 0
    train_loss: float = 0.0
    val_loss: float = 0.0
    val_accuracy: float = 0.0
    learning_rate: float = 0.001

    # Timing
    elapsed_seconds: float = 0.0
    eta_seconds: float = 0.0

    # Status
    phase: str = "idle"  # idle, generating, training, evaluating, done
    status_message: str = ""

    def to_dict(self) -> dict:
        return {
            "fights": {
                "generated": self.fights_generated,
                "target": self.fights_target,
                "per_second": round(self.fights_per_second, 2),
                "team1_wins": self.team1_wins,
                "team2_wins": self.team2_wins,
                "draws": self.draws,
                "win_rate": round(self.team1_wins / max(1, self.fights_generated) * 100, 1),
            },
            "training": {
                "epoch": self.epoch,
                "total_epochs": self.total_epochs,
                "step": self.step,
                "total_steps": self.total_steps,
                "train_loss": round(self.train_loss, 6),
                "val_loss": round(self.val_loss, 6),
                "val_accuracy": round(self.val_accuracy * 100, 2),
                "learning_rate": self.learning_rate,
            },
            "timing": {
                "elapsed": self.elapsed_seconds,
                "eta": self.eta_seconds,
                "elapsed_formatted": self._format_time(self.elapsed_seconds),
                "eta_formatted": self._format_time(self.eta_seconds),
            },
            "status": {
                "phase": self.phase,
                "message": self.status_message,
            },
        }

    @staticmethod
    def _format_time(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds // 60:.0f}m {seconds % 60:.0f}s"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours:.0f}h {minutes:.0f}m"


@dataclass
class HistoryPoint:
    """A single point in the training history."""

    timestamp: float
    step: int
    train_loss: Optional[float] = None
    val_loss: Optional[float] = None
    val_accuracy: Optional[float] = None


class MetricsCollector:
    """Collects and manages training metrics with history."""

    def __init__(self, history_size: int = 1000):
        self.metrics = TrainingMetrics()
        self.history: deque[HistoryPoint] = deque(maxlen=history_size)
        self.start_time: Optional[float] = None
        self._lock = threading.Lock()
        self._subscribers: list[Callable[[dict], None]] = []

    def start(self, phase: str = "generating", target_fights: int = 0, total_epochs: int = 0):
        """Start a new training session."""
        with self._lock:
            self.metrics = TrainingMetrics()
            self.metrics.phase = phase
            self.metrics.fights_target = target_fights
            self.metrics.total_epochs = total_epochs
            self.start_time = time.time()
            self.history.clear()
        self._notify()

    def update_fights(
        self,
        generated: int,
        team1_wins: int = 0,
        team2_wins: int = 0,
        draws: int = 0,
    ):
        """Update fight generation progress."""
        with self._lock:
            self.metrics.fights_generated = generated
            self.metrics.team1_wins = team1_wins
            self.metrics.team2_wins = team2_wins
            self.metrics.draws = draws

            if self.start_time:
                elapsed = time.time() - self.start_time
                self.metrics.elapsed_seconds = elapsed
                if elapsed > 0:
                    self.metrics.fights_per_second = generated / elapsed
                    if self.metrics.fights_target > 0:
                        remaining = self.metrics.fights_target - generated
                        self.metrics.eta_seconds = remaining / max(0.1, self.metrics.fights_per_second)
        self._notify()

    def update_training(
        self,
        epoch: int,
        step: int,
        train_loss: float,
        val_loss: Optional[float] = None,
        val_accuracy: Optional[float] = None,
        total_steps: int = 0,
    ):
        """Update training progress."""
        with self._lock:
            self.metrics.epoch = epoch
            self.metrics.step = step
            self.metrics.train_loss = train_loss
            self.metrics.total_steps = total_steps

            if val_loss is not None:
                self.metrics.val_loss = val_loss
            if val_accuracy is not None:
                self.metrics.val_accuracy = val_accuracy

            if self.start_time:
                self.metrics.elapsed_seconds = time.time() - self.start_time

            # Add to history
            self.history.append(
                HistoryPoint(
                    timestamp=time.time(),
                    step=step,
                    train_loss=train_loss,
                    val_loss=val_loss,
                    val_accuracy=val_accuracy,
                )
            )
        self._notify()

    def set_phase(self, phase: str, message: str = ""):
        """Update the current phase."""
        with self._lock:
            self.metrics.phase = phase
            self.metrics.status_message = message
        self._notify()

    def set_learning_rate(self, lr: float):
        """Update learning rate."""
        with self._lock:
            self.metrics.learning_rate = lr
        self._notify()

    def get_metrics(self) -> dict:
        """Get current metrics as dict."""
        with self._lock:
            metrics = self.metrics.to_dict()

        # Include NN metrics if available
        try:
            from .managers.nn_training import nn_training_manager
            metrics["nn"] = nn_training_manager.get_state()
        except ImportError:
            pass

        return metrics

    def get_history(self) -> list[dict]:
        """Get training history as list of dicts."""
        with self._lock:
            return [
                {
                    "step": h.step,
                    "train_loss": h.train_loss,
                    "val_loss": h.val_loss,
                    "val_accuracy": h.val_accuracy,
                }
                for h in self.history
            ]

    def subscribe(self, callback: Callable[[dict], None]):
        """Subscribe to metric updates."""
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[dict], None]):
        """Unsubscribe from metric updates."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def _notify(self):
        """Notify all subscribers of updates."""
        data = self.get_metrics()
        for callback in self._subscribers:
            try:
                callback(data)
            except Exception:
                pass


# Global collector instance
collector = MetricsCollector()
