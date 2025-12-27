"""
Training state management.
"""

import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from src.common.config import get_paths


# Checkpoints directory
_paths = get_paths()
CHECKPOINTS_DIR = _paths.checkpoints_dir
CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)

# Optional ML imports
try:
    from ...ml.version import VersionRegistry
    from ...ml.arena import Arena
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    VersionRegistry = None
    Arena = None


class TrainingConfig(BaseModel):
    fights: int = 50000
    epochs: int = 50
    batch_size: int = 256
    learning_rate: float = 0.001
    k_folds: int = 5
    patience: int = 5


class TrainingManager:
    """Manages training state and control."""

    def __init__(self):
        self.is_running = False
        self.is_paused = False
        self.current_config: Optional[TrainingConfig] = None
        self.training_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused by default

    def start(self, config: TrainingConfig, metrics) -> dict:
        """Start training with given configuration."""
        if self.is_running:
            return {"success": False, "error": "Training already in progress"}

        self.current_config = config
        self.is_running = True
        self.is_paused = False
        self._stop_event.clear()
        self._pause_event.set()

        # Start training in background thread
        self.training_thread = threading.Thread(
            target=self._run_training,
            args=(config, metrics),
            daemon=True
        )
        self.training_thread.start()

        return {"success": True, "message": "Training started"}

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

    def save_checkpoint(self) -> dict:
        """Save current training state."""
        if not self.is_running and not self.current_config:
            return {"success": False, "error": "No training state to save"}

        # Generate checkpoint name
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"checkpoint-{timestamp}"

        # TODO: Implement actual checkpoint saving with model state
        checkpoint_path = CHECKPOINTS_DIR / f"{name}.pt"

        return {"success": True, "name": name, "path": str(checkpoint_path)}

    def _run_training(self, config: TrainingConfig, metrics):
        """Run the training loop (called in background thread)."""
        try:
            # Import here to avoid circular imports
            from ...localfight.runner import run_fight
            from ...localfight.scenario import Scenario
            from ...localfight.parser import parse_fight_result, extract_training_data

            metrics.start(
                phase="generating",
                target_fights=config.fights,
                total_epochs=config.epochs
            )

            # Phase 1: Generate fights
            training_data = []
            team1_wins = 0
            team2_wins = 0
            draws = 0

            for i in range(config.fights):
                # Check for stop
                if self._stop_event.is_set():
                    break

                # Check for pause
                self._pause_event.wait()

                try:
                    # Generate a fight
                    scenario = Scenario.create_1v1_pistol(
                        seed=i,
                        ai1="test/ai/simple.leek",
                        ai2="test/ai/simple.leek"
                    )
                    result = run_fight(scenario)
                    parsed = parse_fight_result(result)

                    # Track wins
                    if parsed.winner == 1:
                        team1_wins += 1
                    elif parsed.winner == 2:
                        team2_wins += 1
                    else:
                        draws += 1

                    # Extract training data
                    examples = extract_training_data(parsed)
                    training_data.extend([e.__dict__ for e in examples])

                    # Update metrics
                    metrics.update_fights(
                        generated=i + 1,
                        team1_wins=team1_wins,
                        team2_wins=team2_wins,
                        draws=draws
                    )

                except Exception as e:
                    print(f"Fight {i} failed: {e}")
                    continue

            if self._stop_event.is_set():
                metrics.set_phase("stopped", "Training stopped by user")
                return

            # Phase 2: Train model
            metrics.set_phase("training", "Training neural network...")

            if ML_AVAILABLE and training_data:
                from ...ml.trainer import KFoldTrainer

                trainer = KFoldTrainer(
                    k=config.k_folds,
                    epochs=config.epochs,
                    batch_size=config.batch_size,
                    learning_rate=config.learning_rate,
                    early_stopping_patience=config.patience
                )

                # Progress callback
                def on_progress(**kwargs):
                    if self._stop_event.is_set():
                        return
                    self._pause_event.wait()

                    if 'epoch' in kwargs:
                        metrics.update_training(
                            epoch=kwargs.get('epoch', 0),
                            step=kwargs.get('fold', 1) * config.epochs + kwargs.get('epoch', 0),
                            train_loss=kwargs.get('train_loss', 0),
                            val_loss=kwargs.get('val_loss', 0),
                            val_accuracy=kwargs.get('val_accuracy', 0),
                            total_steps=config.k_folds * config.epochs
                        )
                    elif 'phase' in kwargs:
                        metrics.set_phase(kwargs.get('phase', ''), kwargs.get('message', ''))

                trainer.set_progress_callback(on_progress)

                # Run training
                result, model = trainer.train(training_data)

                metrics.set_phase("done", f"Complete! Accuracy: {result.mean_accuracy*100:.1f}%")

            else:
                metrics.set_phase("done", "Training complete (no ML module)")

        except Exception as e:
            metrics.set_phase("error", str(e))
            print(f"Training error: {e}")

        finally:
            self.is_running = False
            self.is_paused = False


# Global training manager
training_manager = TrainingManager()
