"""
Fight runner for local execution.

Executes fight scenarios using the LeekWars Java generator
and captures the output.
"""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .scenario import Scenario

# Path to the generator (relative to project root)
GENERATOR_DIR = Path(__file__).parent.parent.parent / ".cache" / "leek-wars-generator"
GENERATOR_JAR = GENERATOR_DIR / "generator.jar"


class RunnerError(Exception):
    """Error during fight execution."""

    pass


def get_generator_path() -> Path:
    """Get the path to the generator JAR file."""
    if not GENERATOR_JAR.exists():
        raise RunnerError(
            f"Generator JAR not found at {GENERATOR_JAR}. "
            "Run the setup first to build the generator."
        )
    return GENERATOR_JAR


def run_fight(
    scenario: Scenario,
    timeout: float = 30.0,
    nocache: bool = True,
) -> dict:
    """
    Run a single fight scenario and return the result.

    Args:
        scenario: The fight scenario to run
        timeout: Maximum execution time in seconds
        nocache: If True, disable AI caching (recommended for varied scenarios)

    Returns:
        Parsed JSON output from the generator

    Raises:
        RunnerError: If the fight fails to execute
    """
    jar_path = get_generator_path()

    # Write scenario to temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        f.write(scenario.to_json())
        scenario_path = Path(f.name)

    try:
        # Build command
        cmd = ["java", "-jar", str(jar_path)]
        if nocache:
            cmd.append("--nocache")
        cmd.append(str(scenario_path))

        # Execute
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=GENERATOR_DIR,  # Run from generator dir for relative AI paths
        )

        if result.returncode != 0:
            raise RunnerError(
                f"Generator failed with code {result.returncode}:\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )

        # Parse output
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise RunnerError(
                f"Failed to parse generator output as JSON: {e}\n"
                f"stdout: {result.stdout}"
            )

    finally:
        # Clean up temp file
        scenario_path.unlink(missing_ok=True)


def run_fight_raw(
    scenario_json: str,
    timeout: float = 30.0,
    nocache: bool = True,
) -> str:
    """
    Run a fight from raw JSON string and return raw output.

    Lower-level interface for when you already have JSON.
    """
    jar_path = get_generator_path()

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        f.write(scenario_json)
        scenario_path = Path(f.name)

    try:
        cmd = ["java", "-jar", str(jar_path)]
        if nocache:
            cmd.append("--nocache")
        cmd.append(str(scenario_path))

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=GENERATOR_DIR,
        )

        if result.returncode != 0:
            raise RunnerError(
                f"Generator failed with code {result.returncode}:\n"
                f"stderr: {result.stderr}"
            )

        return result.stdout

    finally:
        scenario_path.unlink(missing_ok=True)


def check_generator() -> bool:
    """Check if the generator is available and working."""
    try:
        jar_path = get_generator_path()
        result = subprocess.run(
            ["java", "-jar", str(jar_path), "--help"],
            capture_output=True,
            timeout=10,
            cwd=GENERATOR_DIR,
        )
        return True
    except (RunnerError, subprocess.TimeoutExpired, FileNotFoundError):
        return False
