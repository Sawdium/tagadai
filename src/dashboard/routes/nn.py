"""
Neural Network training API routes.
"""

from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

from ..managers.nn_training import NNTrainingConfig, nn_training_manager


class SaveModelRequest(BaseModel):
    name: Optional[str] = None


class LoadModelRequest(BaseModel):
    path: str


class ExportRequest(BaseModel):
    output_dir: str = "tagadann/NN"


def register_nn_routes(app: FastAPI, metrics_collector):
    """Register NN training routes."""

    @app.post("/api/nn/start")
    async def start_nn_training(config: NNTrainingConfig):
        """Start NN training."""
        return nn_training_manager.start(config, metrics_collector)

    @app.post("/api/nn/pause")
    async def pause_nn_training():
        """Pause/resume NN training."""
        return nn_training_manager.pause()

    @app.post("/api/nn/stop")
    async def stop_nn_training():
        """Stop NN training."""
        return nn_training_manager.stop()

    @app.get("/api/nn/status")
    async def get_nn_status():
        """Get NN training status."""
        return {
            "is_running": nn_training_manager.is_running,
            "is_paused": nn_training_manager.is_paused,
            "config": nn_training_manager.current_config.model_dump() if nn_training_manager.current_config else None,
            "state": nn_training_manager.get_state()
        }

    @app.get("/api/nn/metrics")
    async def get_nn_metrics():
        """Get current NN training metrics."""
        return nn_training_manager.get_state()

    @app.get("/api/nn/history")
    async def get_nn_history():
        """Get NN training history."""
        return {"history": nn_training_manager.get_history()}

    @app.post("/api/nn/save")
    async def save_nn_model(request: SaveModelRequest):
        """Save current model."""
        return nn_training_manager.save_model(request.name)

    @app.post("/api/nn/load")
    async def load_nn_model(request: LoadModelRequest):
        """Load a model."""
        return nn_training_manager.load_model(request.path)

    @app.post("/api/nn/export")
    async def export_nn_model(request: ExportRequest):
        """Export model to LeekScript."""
        return nn_training_manager.export_leekscript(request.output_dir)

    @app.get("/api/nn/models")
    async def list_nn_models():
        """List saved models."""
        return {"models": nn_training_manager.list_models()}

    @app.delete("/api/nn/models/{name}")
    async def delete_nn_model(name: str):
        """Delete a saved model."""
        return nn_training_manager.delete_model(name)

    @app.get("/api/nn/data-info")
    async def get_nn_data_info():
        """Get information about available training data."""
        return nn_training_manager.get_data_info()
