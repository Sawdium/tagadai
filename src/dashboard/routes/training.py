"""
Training and checkpoint API routes.
"""

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from src.common.config import get_paths
from ..managers.training import TrainingConfig, training_manager

# Optional ML imports
try:
    from ...ml.version import VersionRegistry
    from ...ml.arena import Arena
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    VersionRegistry = None
    Arena = None


_paths = get_paths()
CHECKPOINTS_DIR = _paths.checkpoints_dir


class MatchRequest(BaseModel):
    version1_id: str
    version2_id: str
    n_games: int = 100


def register_training_routes(app: FastAPI, metrics_collector):
    """Register training-related routes."""

    @app.post("/api/training/start")
    async def start_training(config: TrainingConfig):
        """Start a new training run."""
        return training_manager.start(config, metrics_collector)

    @app.post("/api/training/pause")
    async def pause_training():
        """Pause/resume training."""
        return training_manager.pause()

    @app.post("/api/training/stop")
    async def stop_training():
        """Stop training."""
        result = training_manager.stop()
        if result["success"]:
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
                "accuracy": 0.0,
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
        return {"success": True, "name": checkpoint_id}

    @app.delete("/api/checkpoints/{checkpoint_id}")
    async def delete_checkpoint(checkpoint_id: str):
        """Delete a checkpoint."""
        path = CHECKPOINTS_DIR / f"{checkpoint_id}.pt"
        if path.exists():
            path.unlink()
        return {"success": True}

    # Version management
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
