"""
RL scenario execution API routes.
"""

from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

from ..managers.rl import rl_manager, DuelConfig, ScenarioRunConfig


class DuelRequest(BaseModel):
    bot1: str = "test/ai/simple.leek"
    bot2: str = "test/ai/simple.leek"
    seed: Optional[int] = None


class ScenarioRequest(BaseModel):
    yaml_path: str
    max_workers: Optional[int] = None


def register_rl_routes(app: FastAPI):
    """Register RL-related routes."""

    @app.get("/api/rl/status")
    async def get_rl_status():
        """Get RL system status."""
        return rl_manager.get_status()

    @app.post("/api/rl/duel")
    async def run_duel(request: DuelRequest):
        """Run a single duel between two bots."""
        config = DuelConfig(
            bot1=request.bot1,
            bot2=request.bot2,
            seed=request.seed,
        )
        return rl_manager.run_duel(config)

    @app.post("/api/rl/scenario/run")
    async def run_scenario(request: ScenarioRequest):
        """Start running a scenario file."""
        return rl_manager.start_scenario(
            request.yaml_path,
            max_workers=request.max_workers,
        )

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

    @app.get("/api/rl/scenarios")
    async def list_scenarios():
        """List available scenario files."""
        scenarios_dir = Path(__file__).parent.parent.parent.parent / "scenarios"
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
