"""
FastAPI server for the training dashboard.
"""

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from .metrics import collector, MetricsCollector

# Static files directory
STATIC_DIR = Path(__file__).parent / "static"

# Checkpoints directory
CHECKPOINTS_DIR = Path(__file__).parent.parent.parent / "models" / "checkpoints"
CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)

# Optional ML imports (may not be installed)
try:
    from ..ml.version import VersionRegistry
    from ..ml.arena import Arena
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    VersionRegistry = None
    Arena = None

# Scraper imports
try:
    from ..scraper import FightScraper, FightDatabase, get_scraper
    SCRAPER_AVAILABLE = True
except ImportError:
    SCRAPER_AVAILABLE = False
    get_scraper = None

# RL imports
try:
    from ..rl.scenarios import load_yaml, ScenarioRunner, ScenarioConfig
    from ..rl.telemetry import extract_telemetry, aggregate_metrics, telemetry_from_batch
    from ..localfight.parallel import ParallelRunner, run_parallel
    from ..localfight.scenario import Scenario
    from ..localfight.runner import run_fight, check_generator
    from ..localfight.parser import parse_fight_result
    RL_AVAILABLE = True
except ImportError:
    RL_AVAILABLE = False


class TrainingConfig(BaseModel):
    fights: int = 50000
    epochs: int = 50
    batch_size: int = 256
    learning_rate: float = 0.001
    k_folds: int = 5
    patience: int = 5


class MatchRequest(BaseModel):
    version1_id: str
    version2_id: str
    n_games: int = 100


class ScraperConfig(BaseModel):
    delay: float = 1.0


class DuelConfig(BaseModel):
    bot1: str = "test/ai/simple.leek"
    bot2: str = "test/ai/simple.leek"
    seed: Optional[int] = None


class ScenarioRunConfig(BaseModel):
    yaml_path: str
    max_workers: Optional[int] = None


# RL state management
class RLManager:
    """Manages RL scenario execution state."""

    def __init__(self):
        self.is_running = False
        self.current_scenario: Optional[str] = None
        self.progress = {"completed": 0, "total": 0, "fights_per_sec": 0.0}
        self.results: list = []
        self.telemetry: list = []
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def run_duel(self, config: DuelConfig) -> dict:
        """Run a single duel and return results."""
        if not RL_AVAILABLE:
            return {"error": "RL module not available"}

        if not check_generator():
            return {"error": "Generator not available"}

        import random
        seed = config.seed if config.seed is not None else random.randint(0, 2**31)

        try:
            scenario = Scenario.create_1v1_pistol(
                seed=seed,
                ai1=config.bot1,
                ai2=config.bot2,
            )
            raw_result = run_fight(scenario)
            result = parse_fight_result(raw_result)
            telemetry = extract_telemetry(result)

            return {
                "success": True,
                "seed": seed,
                "winner": result.winner,
                "duration": result.duration,
                "execution_time_ms": result.execution_time / 1e6,
                "telemetry": telemetry.to_dict(),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def start_scenario(self, yaml_path: str, max_workers: Optional[int] = None) -> dict:
        """Start running a scenario file."""
        if not RL_AVAILABLE:
            return {"success": False, "error": "RL module not available"}

        if self.is_running:
            return {"success": False, "error": "Scenario already running"}

        if not Path(yaml_path).exists():
            return {"success": False, "error": f"File not found: {yaml_path}"}

        self.is_running = True
        self.current_scenario = yaml_path
        self._stop_event.clear()
        self.results = []
        self.telemetry = []
        self.progress = {"completed": 0, "total": 0, "fights_per_sec": 0.0}

        self._thread = threading.Thread(
            target=self._run_scenario,
            args=(yaml_path, max_workers),
            daemon=True
        )
        self._thread.start()

        return {"success": True, "message": f"Started scenario: {yaml_path}"}

    def _run_scenario(self, yaml_path: str, max_workers: Optional[int]):
        """Background thread for scenario execution."""
        import time
        try:
            config = load_yaml(yaml_path)
            if max_workers:
                config.max_workers = max_workers

            all_scenarios = config.get_all_scenarios()
            self.progress["total"] = len(all_scenarios)

            start_time = time.time()

            def progress_callback(completed, total, result):
                if self._stop_event.is_set():
                    return
                elapsed = time.time() - start_time
                self.progress["completed"] = completed
                self.progress["fights_per_sec"] = completed / elapsed if elapsed > 0 else 0

            runner = ScenarioRunner(config, progress_callback=progress_callback)
            results = runner.run()

            # Extract telemetry from all results
            for scenario_result in results:
                self.results.append({
                    "name": scenario_result.scenario_name,
                    "success_count": scenario_result.batch_result.success_count,
                    "error_count": scenario_result.batch_result.error_count,
                    "total_time": scenario_result.batch_result.total_time,
                })
                self.telemetry.extend(
                    telemetry_from_batch(scenario_result.batch_result.results)
                )

        except Exception as e:
            self.results.append({"error": str(e)})
        finally:
            self.is_running = False

    def stop_scenario(self) -> dict:
        """Stop running scenario."""
        if not self.is_running:
            return {"success": False, "error": "No scenario running"}

        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)

        self.is_running = False
        return {"success": True, "message": "Scenario stopped"}

    def get_status(self) -> dict:
        """Get current RL status."""
        return {
            "is_running": self.is_running,
            "current_scenario": self.current_scenario,
            "progress": self.progress,
            "results_count": len(self.results),
            "rl_available": RL_AVAILABLE,
            "generator_available": check_generator() if RL_AVAILABLE else False,
        }

    def get_results(self) -> dict:
        """Get scenario results and aggregated metrics."""
        if not self.telemetry:
            return {"results": self.results, "aggregate": {}}

        return {
            "results": self.results,
            "aggregate": aggregate_metrics(self.telemetry),
        }


# Global RL manager
rl_manager = RLManager()


# Training state management
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

    def start(self, config: TrainingConfig, metrics: MetricsCollector) -> dict:
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

    def _run_training(self, config: TrainingConfig, metrics: MetricsCollector):
        """Run the training loop (called in background thread)."""
        try:
            # Import here to avoid circular imports
            from ..localfight.runner import run_fight
            from ..localfight.scenario import Scenario
            from ..localfight.parser import parse_fight_result, extract_training_data

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
                from ..ml.trainer import KFoldTrainer

                trainer = KFoldTrainer(
                    k=config.k_folds,
                    epochs=config.epochs,
                    batch_size=config.batch_size,
                    learning_rate=config.learning_rate,
                    early_stopping_patience=config.patience
                )

                # Progress callback - accepts variable kwargs from trainer
                def on_progress(**kwargs):
                    if self._stop_event.is_set():
                        return
                    self._pause_event.wait()

                    # Handle different callback types
                    if 'epoch' in kwargs:
                        # Training progress update
                        metrics.update_training(
                            epoch=kwargs.get('epoch', 0),
                            step=kwargs.get('fold', 1) * config.epochs + kwargs.get('epoch', 0),
                            train_loss=kwargs.get('train_loss', 0),
                            val_loss=kwargs.get('val_loss', 0),
                            val_accuracy=kwargs.get('val_accuracy', 0),
                            total_steps=config.k_folds * config.epochs
                        )
                    elif 'phase' in kwargs:
                        # Phase change notification
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


def create_app(metrics: Optional[MetricsCollector] = None) -> FastAPI:
    """Create the FastAPI application."""

    # Use provided collector or global
    mc = metrics or collector

    # Connected WebSocket clients
    clients: list[WebSocket] = []

    # Background task reference
    broadcast_task = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Lifespan context manager for startup/shutdown events."""
        nonlocal broadcast_task

        # Startup: Create background task for broadcasting updates
        async def broadcast_updates():
            """Broadcast metrics to all connected clients."""
            while True:
                if clients:
                    data = mc.get_metrics()
                    disconnected = []
                    for client in clients:
                        try:
                            await client.send_json(data)
                        except Exception:
                            disconnected.append(client)
                    for client in disconnected:
                        if client in clients:
                            clients.remove(client)
                await asyncio.sleep(0.5)  # Update every 500ms

        broadcast_task = asyncio.create_task(broadcast_updates())
        yield
        # Shutdown: Cancel the background task
        if broadcast_task:
            broadcast_task.cancel()
            try:
                await broadcast_task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title="TagadAI Training Dashboard", lifespan=lifespan)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Serve the main dashboard page."""
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/metrics")
    async def get_metrics():
        """Get current training metrics."""
        return mc.get_metrics()

    @app.get("/api/history")
    async def get_history():
        """Get training history."""
        return mc.get_history()

    # Training control endpoints
    @app.post("/api/training/start")
    async def start_training(config: TrainingConfig):
        """Start a new training run."""
        return training_manager.start(config, mc)

    @app.post("/api/training/pause")
    async def pause_training():
        """Pause/resume training."""
        return training_manager.pause()

    @app.post("/api/training/stop")
    async def stop_training():
        """Stop training."""
        result = training_manager.stop()
        if result["success"]:
            # Auto-save checkpoint
            checkpoint = training_manager.save_checkpoint()
            result["checkpoint"] = checkpoint.get("name")
        return result

    @app.post("/api/training/checkpoint")
    async def save_checkpoint():
        """Save current checkpoint."""
        return training_manager.save_checkpoint()

    @app.get("/api/training/status")
    async def get_training_status():
        """Get training status."""
        return {
            "is_running": training_manager.is_running,
            "is_paused": training_manager.is_paused,
            "config": training_manager.current_config.model_dump() if training_manager.current_config else None
        }

    # Checkpoint management
    @app.get("/api/checkpoints")
    async def list_checkpoints():
        """List all checkpoints."""
        checkpoints = []
        for path in CHECKPOINTS_DIR.glob("*.pt"):
            stat = path.stat()
            checkpoints.append({
                "id": path.stem,
                "name": path.stem,
                "path": str(path),
                "accuracy": 0.0,  # TODO: Store accuracy in checkpoint
                "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            })
        checkpoints.sort(key=lambda x: x["created_at"], reverse=True)
        return {"checkpoints": checkpoints}

    @app.post("/api/checkpoints/{checkpoint_id}/load")
    async def load_checkpoint(checkpoint_id: str):
        """Load a checkpoint."""
        path = CHECKPOINTS_DIR / f"{checkpoint_id}.pt"
        if not path.exists():
            return {"success": False, "error": "Checkpoint not found"}

        # TODO: Actually load the checkpoint
        return {"success": True, "name": checkpoint_id}

    @app.delete("/api/checkpoints/{checkpoint_id}")
    async def delete_checkpoint(checkpoint_id: str):
        """Delete a checkpoint."""
        path = CHECKPOINTS_DIR / f"{checkpoint_id}.pt"
        if path.exists():
            path.unlink()
        return {"success": True}

    # Version management endpoints
    @app.get("/api/versions")
    async def get_versions():
        """Get all AI versions."""
        if not ML_AVAILABLE:
            return {"error": "ML module not available", "versions": []}
        registry = VersionRegistry()
        versions = registry.list_versions(sort_by="elo_rating")
        return {
            "versions": [v.to_dict() for v in versions],
            "stats": registry.get_stats(),
        }

    @app.get("/api/versions/{version_id}")
    async def get_version(version_id: str):
        """Get a specific version."""
        if not ML_AVAILABLE:
            return {"error": "ML module not available"}
        registry = VersionRegistry()
        version = registry.get_version(version_id)
        if version is None:
            return {"error": "Version not found"}
        return version.to_dict()

    @app.delete("/api/versions/{version_id}")
    async def delete_version(version_id: str):
        """Delete a version."""
        if not ML_AVAILABLE:
            return {"error": "ML module not available"}
        registry = VersionRegistry()
        success = registry.delete_version(version_id)
        return {"success": success}

    # Arena endpoints
    @app.get("/api/arena/leaderboard")
    async def get_leaderboard():
        """Get arena leaderboard."""
        if not ML_AVAILABLE:
            return {"error": "ML module not available", "leaderboard": []}
        registry = VersionRegistry()
        arena = Arena(registry)
        return {"leaderboard": arena.get_leaderboard(limit=20)}

    @app.get("/api/arena/head-to-head/{v1_id}/{v2_id}")
    async def get_head_to_head(v1_id: str, v2_id: str):
        """Get head-to-head prediction."""
        if not ML_AVAILABLE:
            return {"error": "ML module not available"}
        registry = VersionRegistry()
        arena = Arena(registry)
        return arena.get_head_to_head(v1_id, v2_id)

    @app.get("/api/system/gpu")
    async def get_gpu_info():
        """Get GPU information."""
        try:
            import torch
            return {
                "cuda_available": torch.cuda.is_available(),
                "device_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
                "devices": [
                    {
                        "index": i,
                        "name": torch.cuda.get_device_name(i),
                        "memory_total": torch.cuda.get_device_properties(i).total_memory,
                    }
                    for i in range(torch.cuda.device_count())
                ] if torch.cuda.is_available() else [],
            }
        except ImportError:
            return {"cuda_available": False, "error": "PyTorch not installed"}

    # Scraper endpoints
    @app.get("/api/scraper/status")
    async def get_scraper_status():
        """Get scraper status and statistics."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available", "status": "unavailable"}
        scraper = get_scraper()
        return scraper.get_stats()

    @app.post("/api/scraper/start")
    async def start_scraper(config: ScraperConfig):
        """Start the scraper."""
        if not SCRAPER_AVAILABLE:
            return {"success": False, "error": "Scraper module not available"}

        from ..scraper import FightScraper, FightDatabase

        # Create new scraper with config
        global _scraper
        from ..scraper import scraper as scraper_module
        scraper_module._scraper = FightScraper(
            delay=config.delay,
        )
        scraper = get_scraper()

        if scraper.is_running():
            return {"success": False, "error": "Scraper already running"}

        success = scraper.start()
        return {"success": success, "message": "Scraper started" if success else "Failed to start"}

    @app.post("/api/scraper/stop")
    async def stop_scraper():
        """Stop the scraper."""
        if not SCRAPER_AVAILABLE:
            return {"success": False, "error": "Scraper module not available"}
        scraper = get_scraper()
        scraper.stop()
        return {"success": True, "message": "Scraper stopped"}

    @app.post("/api/scraper/pause")
    async def pause_scraper():
        """Pause/resume the scraper."""
        if not SCRAPER_AVAILABLE:
            return {"success": False, "error": "Scraper module not available"}
        scraper = get_scraper()
        if scraper.stats.status.value == "paused":
            scraper.resume()
            return {"success": True, "paused": False}
        else:
            scraper.pause()
            return {"success": True, "paused": True}

    @app.post("/api/scraper/delay")
    async def set_scraper_delay(request: Request):
        """Update scraper delay live (no restart needed)."""
        if not SCRAPER_AVAILABLE:
            return {"success": False, "error": "Scraper module not available"}
        try:
            body = await request.json()
            delay = float(body.get("delay", 1.0))
            if delay < 0.1:
                return {"success": False, "error": "Delay must be >= 0.1 seconds"}
            if delay > 60:
                return {"success": False, "error": "Delay must be <= 60 seconds"}
            scraper = get_scraper()
            old_delay = scraper.delay
            scraper.delay = delay
            return {"success": True, "old_delay": old_delay, "new_delay": delay}
        except (ValueError, TypeError) as e:
            return {"success": False, "error": f"Invalid delay value: {e}"}

    @app.get("/api/scraper/database")
    async def get_scraper_database_stats():
        """Get detailed database statistics."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}
        scraper = get_scraper()
        return scraper.db.get_stats()

    @app.get("/api/scraper/analytics/levels")
    async def get_level_distribution(fight_type: Optional[int] = None):
        """Get observation counts per level."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}
        scraper = get_scraper()
        return {
            "distribution": scraper.db.get_level_distribution(fight_type),
            "fight_types": scraper.db.get_fight_type_distribution(),
        }

    @app.get("/api/scraper/analytics/level/{level}")
    async def get_level_stats(level: int, fight_type: Optional[int] = None):
        """Get detailed stats for a specific level."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}
        scraper = get_scraper()
        return {
            "stats": scraper.db.get_stats_by_level(level, fight_type),
            "builds": scraper.db.get_popular_builds(level, fight_type),
        }

    @app.get("/api/scraper/analytics/overview")
    async def get_analytics_overview():
        """Get overview analytics data."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}
        scraper = get_scraper()
        return {
            "fight_types": scraper.db.get_fight_type_distribution(),
            "contexts": scraper.db.get_context_distribution(),
            "level_distribution": scraper.db.get_level_distribution(),
        }

    @app.get("/api/scraper/analytics/exploration")
    async def get_exploration_stats():
        """Get tournament exploration and level distribution stats."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}
        scraper = get_scraper()
        tournament_stats = scraper.db.get_tournament_exploration_stats()
        level_brackets = scraper.db.get_level_bracket_counts()
        level_301_ratio = scraper.db.get_level_301_ratio()

        return {
            "tournaments": tournament_stats,
            "level_brackets": level_brackets,
            "level_301_ratio": round(level_301_ratio, 3),
        }

    @app.get("/api/scraper/analytics/dates")
    async def get_date_distribution(bucket: str = "month"):
        """Get fight counts grouped by date."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}
        if bucket not in ("day", "week", "month"):
            bucket = "month"
        scraper = get_scraper()
        return {
            "distribution": scraper.db.get_fight_date_distribution(bucket),
            "date_range": scraper.db.get_fight_date_range(),
            "freshness": scraper.db.get_data_freshness_stats(),
        }

    # Metadata extraction endpoints
    @app.get("/api/metadata/status")
    async def get_metadata_status():
        """Get metadata extraction progress and stats."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}
        scraper = get_scraper()
        return {
            "progress": scraper.db.get_metadata_extraction_progress(),
            "stats": scraper.db.get_metadata_stats(),
        }

    @app.post("/api/metadata/extract")
    async def extract_metadata(batch_size: int = 500, max_batches: int = 10):
        """Extract metadata for fights that don't have it yet."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}

        from ..scraper.metadata import extract_fight_metadata

        scraper = get_scraper()
        total_saved = 0
        batches_processed = 0

        for _ in range(max_batches):
            fights = scraper.db.get_fights_needing_metadata(batch_size=batch_size)
            if not fights:
                break

            for fight_id, fight_data in fights:
                metadata = extract_fight_metadata(fight_id, fight_data)
                if metadata:
                    saved = scraper.db.save_fight_metadata([m.to_dict() for m in metadata])
                    total_saved += saved

            batches_processed += 1

            # Update state
            if fights:
                scraper.db.set_metadata_extraction_state('last_fight_id', str(fights[-1][0]))
                scraper.db.set_metadata_extraction_state('last_extraction_time',
                    datetime.now().isoformat())

        return {
            "batches_processed": batches_processed,
            "records_saved": total_saved,
            "progress": scraper.db.get_metadata_extraction_progress(),
        }

    @app.get("/api/metadata/equipment")
    async def get_equipment_usage(fight_type: Optional[int] = None, min_sample: int = 10):
        """Get equipment usage statistics by level bucket."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}

        from ..scraper.metadata import get_weapon_name, get_chip_name

        scraper = get_scraper()
        raw_data = scraper.db.get_equipment_usage_by_level(
            fight_type=fight_type,
            min_sample_size=min_sample
        )

        # Add names to IDs
        result = {}
        for bucket, data in raw_data.items():
            result[bucket] = {
                "sample_size": data["sample_size"],
                "weapons": {
                    str(w): {
                        "name": get_weapon_name(int(w)),
                        "count": info["count"],
                        "pct": info["pct"]
                    }
                    for w, info in data["weapons"].items()
                },
                "chips": {
                    str(c): {
                        "name": get_chip_name(int(c)),
                        "count": info["count"],
                        "pct": info["pct"]
                    }
                    for c, info in data["chips"].items()
                },
            }

        return {
            "by_level": result,
            "fight_type": fight_type,
            "min_sample": min_sample,
        }

    @app.get("/api/metadata/cooccurrence")
    async def get_equipment_cooccurrence(
        level_bucket: Optional[str] = None,
        fight_type: Optional[int] = None,
        min_cooccurrence: int = 10,
        item_type: Optional[str] = None,  # 'weapon', 'chip', or None for both
    ):
        """Get equipment co-occurrence matrix for builds analysis."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}

        from ..scraper.item_mappings import get_weapon_name, get_chip_name

        scraper = get_scraper()
        raw_data = scraper.db.get_equipment_cooccurrence(
            level_bucket=level_bucket,
            fight_type=fight_type,
            min_cooccurrence=min_cooccurrence,
        )

        # Filter by item type if specified
        items = raw_data.get("items", [])
        matrix = raw_data.get("matrix", [])
        counts = raw_data.get("counts", {})

        if item_type:
            prefix = "W:" if item_type == "weapon" else "C:"
            indices = [i for i, item in enumerate(items) if item.startswith(prefix)]
            items = [items[i] for i in indices]
            matrix = [[matrix[i][j] for j in indices] for i in indices]
            counts = {k: v for k, v in counts.items() if k.startswith(prefix)}

        # Add readable names
        named_items = []
        for item in items:
            if item.startswith("W:"):
                weapon_id = int(item[2:])
                named_items.append({
                    "id": item,
                    "type": "weapon",
                    "name": get_weapon_name(weapon_id),
                })
            elif item.startswith("C:"):
                chip_id = int(item[2:])
                named_items.append({
                    "id": item,
                    "type": "chip",
                    "name": get_chip_name(chip_id),
                })

        return {
            "items": named_items,
            "matrix": matrix,
            "counts": {k: v for k, v in counts.items()},
            "level_bucket": level_bucket,
            "fight_type": fight_type,
            "min_cooccurrence": min_cooccurrence,
        }

    @app.get("/api/metadata/clusters")
    async def get_build_clusters(
        n_clusters: int = 6,
        level_min: int = 1,
        level_max: int = 301,
    ):
        """Get build archetype clusters based on stat distributions."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}

        try:
            from ..scraper.clustering import cluster_builds
            from ..scraper.item_mappings import get_chip_name, get_weapon_name

            db_path = Path(__file__).parent.parent.parent / "data" / "fights.db"
            result = cluster_builds(
                db_path,
                n_clusters=n_clusters,
                level_min=level_min,
                level_max=level_max,
            )

            if 'error' in result:
                return result

            # Add readable names to equipment
            for cluster in result['clusters']:
                cluster['top_chips'] = [
                    {'id': cid, 'name': get_chip_name(cid), 'count': cnt}
                    for cid, cnt in cluster['top_chips']
                ]
                cluster['top_weapons'] = [
                    {'id': wid, 'name': get_weapon_name(wid), 'count': cnt}
                    for wid, cnt in cluster['top_weapons']
                ]

            return result

        except ImportError as e:
            return {"error": f"Missing dependency: {e}. Install scikit-learn."}
        except Exception as e:
            return {"error": str(e)}

    @app.get("/api/metadata/clusters/evolution")
    async def get_cluster_evolution(
        n_clusters: int = 6,
    ):
        """Get cluster distribution evolution across levels."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}

        try:
            from ..scraper.clustering import cluster_builds, get_stat_vectors
            from ..scraper.item_mappings import get_chip_name, get_weapon_name
            import numpy as np
            from sklearn.cluster import KMeans
            from sklearn.preprocessing import StandardScaler

            db_path = Path(__file__).parent.parent.parent / "data" / "fights.db"

            # Get all stat vectors with metadata
            stat_matrix, metadata = get_stat_vectors(db_path, level_min=1, level_max=301, min_total_stats=50)

            if len(stat_matrix) < n_clusters:
                return {"error": f"Not enough samples ({len(stat_matrix)})"}

            # Cluster all data
            scaler = StandardScaler()
            stat_scaled = scaler.fit_transform(stat_matrix)
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            labels = kmeans.fit_predict(stat_scaled)

            # Determine archetype names for each cluster - more specific naming
            stat_names = ['Str', 'Agi', 'Mag', 'Res']
            archetypes = {}
            for cluster_id in range(n_clusters):
                centroid = stat_matrix[labels == cluster_id].mean(axis=0)
                # Sort stats to find top 2
                sorted_stats = sorted(enumerate(centroid), key=lambda x: -x[1])
                top_idx, top_val = sorted_stats[0]
                second_idx, second_val = sorted_stats[1]

                # Name based on distribution
                if top_val > 0.7:
                    # Pure build (>70% in one stat)
                    archetypes[cluster_id] = f"Pure {stat_names[top_idx]}"
                elif top_val > 0.45 and second_val > 0.25:
                    # Hybrid build
                    archetypes[cluster_id] = f"{stat_names[top_idx]}/{stat_names[second_idx]}"
                elif top_val > 0.4:
                    # Focused build
                    archetypes[cluster_id] = f"{stat_names[top_idx]} Focus"
                else:
                    # Balanced
                    archetypes[cluster_id] = f"Balanced"

            # Define level buckets
            buckets = [
                (1, 25), (26, 50), (51, 75), (76, 100),
                (101, 125), (126, 150), (151, 175), (176, 200),
                (201, 225), (226, 250), (251, 275), (276, 300), (301, 301)
            ]

            # Compute distribution per bucket
            evolution = []
            for level_min, level_max in buckets:
                bucket_mask = np.array([
                    level_min <= m['level'] <= level_max
                    for m in metadata
                ])
                bucket_labels = labels[bucket_mask]
                total = len(bucket_labels)

                if total == 0:
                    continue

                label_str = f"{level_min}-{level_max}" if level_min != level_max else str(level_min)
                bucket_data = {
                    'level_range': label_str,
                    'total': total,
                    'clusters': {}
                }

                for cluster_id in range(n_clusters):
                    count = int((bucket_labels == cluster_id).sum())
                    pct = round(count / total * 100, 1)
                    bucket_data['clusters'][archetypes[cluster_id]] = {
                        'count': count,
                        'pct': pct
                    }

                evolution.append(bucket_data)

            # Assign colors to archetypes dynamically based on dominant stat
            base_colors = {
                'Str': ['#f85149', '#ff7b72', '#ffa198'],  # Reds
                'Agi': ['#3fb950', '#7ee787', '#a5d6a7'],  # Greens
                'Mag': ['#a371f7', '#d2a8ff', '#e0c3fc'],  # Purples
                'Res': ['#d29922', '#f0b429', '#ffd54f'],  # Yellows/Golds
            }
            archetype_colors = {}
            stat_counters = {'Str': 0, 'Agi': 0, 'Mag': 0, 'Res': 0}

            for archetype in set(archetypes.values()):
                # Find dominant stat in name
                for stat in ['Str', 'Agi', 'Mag', 'Res']:
                    if stat in archetype:
                        idx = stat_counters[stat] % len(base_colors[stat])
                        archetype_colors[archetype] = base_colors[stat][idx]
                        stat_counters[stat] += 1
                        break
                else:
                    archetype_colors[archetype] = '#8b949e'  # Gray for balanced

            return {
                'evolution': evolution,
                'archetypes': list(set(archetypes.values())),
                'archetype_colors': archetype_colors,
                'sample_count': len(stat_matrix),
                'n_clusters': n_clusters,
            }

        except ImportError as e:
            return {"error": f"Missing dependency: {e}. Install scikit-learn."}
        except Exception as e:
            import traceback
            return {"error": str(e), "traceback": traceback.format_exc()}

    @app.get("/api/metadata/insights")
    async def get_build_insights():
        """Generate auto-insights from build data."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}

        try:
            from ..scraper.clustering import get_stat_vectors
            import numpy as np
            from sklearn.cluster import KMeans
            from sklearn.preprocessing import StandardScaler

            db_path = Path(__file__).parent.parent.parent / "data" / "fights.db"
            stat_matrix, metadata = get_stat_vectors(db_path, level_min=1, level_max=301, min_total_stats=50)

            if len(stat_matrix) < 10:
                return {"insights": [], "error": "Not enough data"}

            insights = []

            # 1. Analyze stat distribution by level ranges
            low_level = [m for m in metadata if m['level'] <= 50]
            mid_level = [m for m in metadata if 100 <= m['level'] <= 150]
            high_level = [m for m in metadata if m['level'] >= 250]

            # Find dominant stat at each level range
            def get_dominant_stat(leeks):
                if not leeks:
                    return None, 0
                avg_str = np.mean([l['strength'] for l in leeks])
                avg_agi = np.mean([l['agility'] for l in leeks])
                avg_mag = np.mean([l['magic'] for l in leeks])
                avg_res = np.mean([l['resistance'] for l in leeks])
                total = avg_str + avg_agi + avg_mag + avg_res
                if total == 0:
                    return None, 0
                stats = {'Strength': avg_str/total, 'Agility': avg_agi/total,
                         'Magic': avg_mag/total, 'Resistance': avg_res/total}
                dominant = max(stats, key=stats.get)
                return dominant, stats[dominant]

            if low_level:
                stat, pct = get_dominant_stat(low_level)
                if stat and pct > 0.35:
                    insights.append({
                        'type': 'level_trend',
                        'icon': '📊',
                        'text': f'{stat} dominates early game ({pct*100:.0f}% of stats at level 1-50)'
                    })

            if high_level:
                stat, pct = get_dominant_stat(high_level)
                if stat:
                    insights.append({
                        'type': 'level_trend',
                        'icon': '🎯',
                        'text': f'High-level meta favors {stat} ({pct*100:.0f}% at level 250+)'
                    })

            # 2. Find when Magic becomes viable
            for threshold in [50, 75, 100, 125, 150]:
                magic_leeks = [m for m in metadata if m['level'] >= threshold and m['magic'] > m['strength'] and m['magic'] > m['agility']]
                if len(magic_leeks) >= 20:
                    insights.append({
                        'type': 'emergence',
                        'icon': '✨',
                        'text': f'Magic builds emerge around level {threshold}'
                    })
                    break

            # 3. Rarest build type
            scaler = StandardScaler()
            stat_scaled = scaler.fit_transform(stat_matrix)
            kmeans = KMeans(n_clusters=6, random_state=42, n_init=10)
            labels = kmeans.fit_predict(stat_scaled)

            cluster_sizes = np.bincount(labels, minlength=6)
            rarest_cluster = int(np.argmin(cluster_sizes))
            rarest_size = cluster_sizes[rarest_cluster]
            rarest_pct = rarest_size / len(labels) * 100

            if rarest_pct < 5:
                # Identify what makes it rare
                rarest_centroid = stat_matrix[labels == rarest_cluster].mean(axis=0)
                stat_names = ['Strength', 'Agility', 'Magic', 'Resistance']
                dominant = stat_names[int(np.argmax(rarest_centroid))]
                insights.append({
                    'type': 'rarity',
                    'icon': '💎',
                    'text': f'{dominant}-focused builds are rare ({rarest_pct:.1f}% of players)'
                })

            # 4. Most popular build
            popular_cluster = int(np.argmax(cluster_sizes))
            popular_pct = cluster_sizes[popular_cluster] / len(labels) * 100
            popular_centroid = stat_matrix[labels == popular_cluster].mean(axis=0)
            stat_names = ['Strength', 'Agility', 'Magic', 'Resistance']
            dominant = stat_names[int(np.argmax(popular_centroid))]
            insights.append({
                'type': 'popular',
                'icon': '🏆',
                'text': f'{dominant} is the most popular stat ({popular_pct:.0f}% of builds)'
            })

            # 5. Sample size info
            insights.append({
                'type': 'info',
                'icon': '📈',
                'text': f'Analysis based on {len(metadata):,} unique leek builds'
            })

            return {"insights": insights}

        except Exception as e:
            import traceback
            return {"error": str(e), "insights": []}

    # RL endpoints
    @app.get("/api/rl/status")
    async def get_rl_status():
        """Get RL module status."""
        return rl_manager.get_status()

    @app.post("/api/rl/duel")
    async def run_duel(config: DuelConfig):
        """Run a single duel fight."""
        return rl_manager.run_duel(config)

    @app.get("/api/rl/scenarios")
    async def list_scenarios():
        """List available scenario files."""
        scenarios_dir = Path(__file__).parent.parent.parent / "scenarios"
        if not scenarios_dir.exists():
            return {"scenarios": []}

        scenarios = []
        for path in scenarios_dir.glob("*.yml"):
            scenarios.append({
                "name": path.stem,
                "path": str(path),
                "filename": path.name,
            })
        return {"scenarios": scenarios}

    @app.post("/api/rl/scenario/run")
    async def run_scenario(config: ScenarioRunConfig):
        """Start running a scenario file."""
        return rl_manager.start_scenario(config.yaml_path, config.max_workers)

    @app.post("/api/rl/scenario/stop")
    async def stop_scenario():
        """Stop running scenario."""
        return rl_manager.stop_scenario()

    @app.get("/api/rl/scenario/progress")
    async def get_scenario_progress():
        """Get current scenario progress."""
        return {
            "is_running": rl_manager.is_running,
            "progress": rl_manager.progress,
            "current_scenario": rl_manager.current_scenario,
        }

    @app.get("/api/rl/results")
    async def get_rl_results():
        """Get scenario results and metrics."""
        return rl_manager.get_results()

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for real-time updates."""
        await websocket.accept()
        clients.append(websocket)

        try:
            # Send initial state
            await websocket.send_json(mc.get_metrics())

            # Keep connection alive and handle incoming messages
            while True:
                try:
                    # Wait for messages (or just keep alive)
                    data = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=30.0
                    )
                    # Handle ping/pong
                    if data == "ping":
                        await websocket.send_text("pong")
                except asyncio.TimeoutError:
                    # Send heartbeat
                    await websocket.send_json(mc.get_metrics())
        except WebSocketDisconnect:
            pass
        finally:
            if websocket in clients:
                clients.remove(websocket)

    # Mount static files
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


# Default app instance
app = create_app()


def run_server(host: str = "127.0.0.1", port: int = 8080):
    """Run the dashboard server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
