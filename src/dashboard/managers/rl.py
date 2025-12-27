"""
RL scenario execution state management.
"""

import threading
from pathlib import Path
from typing import Optional

from pydantic import BaseModel


# RL imports
try:
    from ...rl.scenarios import load_yaml, ScenarioRunner
    from ...rl.telemetry import extract_telemetry, aggregate_metrics, telemetry_from_batch
    from ...localfight.scenario import Scenario
    from ...localfight.runner import run_fight, check_generator
    from ...localfight.parser import parse_fight_result
    RL_AVAILABLE = True
except ImportError:
    RL_AVAILABLE = False

    def check_generator():
        return False


class DuelConfig(BaseModel):
    bot1: str = "test/ai/simple.leek"
    bot2: str = "test/ai/simple.leek"
    seed: Optional[int] = None


class ScenarioRunConfig(BaseModel):
    yaml_path: str
    max_workers: Optional[int] = None


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
