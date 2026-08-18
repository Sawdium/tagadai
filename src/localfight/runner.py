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
from src.common.config import MIN_JAVA_VERSION, get_paths

# Path to the generator (uses centralized config)
_paths = get_paths()
GENERATOR_DIR = _paths.generator_dir
GENERATOR_JAR = _paths.generator_jar


class RunnerError(Exception):
    """Error during fight execution."""

    pass


def get_generator_path() -> Path:
    """Get the path to the generator JAR file."""
    if not GENERATOR_JAR.exists():
        raise RunnerError(
            f"Generator JAR not found at {GENERATOR_JAR}. "
            "Run scripts/setup_generator.sh to build the generator."
        )
    return GENERATOR_JAR


def get_java_path() -> Path:
    """Get a Java executable new enough to run the generator."""
    java = _paths.java_bin
    if java is None:
        raise RunnerError(
            f"No Java {MIN_JAVA_VERSION}+ runtime found. The generator is built "
            f"for Java {MIN_JAVA_VERSION} and will not load on an older JVM. "
            "Run scripts/setup_generator.sh to install one, or point "
            "TAGADAI_JAVA_HOME at an existing JDK."
        )
    return java


def _build_command(scenario_path: Path, nocache: bool) -> list[str]:
    """Build the generator command line for a scenario file."""
    cmd = [str(get_java_path()), "-jar", str(get_generator_path())]
    if nocache:
        cmd.append("--nocache")
    cmd.append(str(scenario_path))
    return cmd


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
    # Write scenario to temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        f.write(scenario.to_json())
        scenario_path = Path(f.name)

    try:
        cmd = _build_command(scenario_path, nocache)

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
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        f.write(scenario_json)
        scenario_path = Path(f.name)

    try:
        cmd = _build_command(scenario_path, nocache)

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
    """Check if the generator is available and runnable on this machine."""
    try:
        subprocess.run(
            [str(get_java_path()), "-jar", str(get_generator_path()), "--help"],
            capture_output=True,
            timeout=60,
            cwd=GENERATOR_DIR,
        )
        return True
    except (RunnerError, subprocess.TimeoutExpired, FileNotFoundError):
        return False
