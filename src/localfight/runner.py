"""
Fight runner for local execution.

Executes fight scenarios using the LeekWars Java generator
and captures the output.
"""

import json
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Optional

from .scenario import Scenario
from src.common.config import MIN_JAVA_VERSION, get_paths

# Path to the generator (uses centralized config)
_paths = get_paths()
GENERATOR_DIR = _paths.generator_dir
GENERATOR_JAR = _paths.generator_jar


class RunnerError(Exception):
    """Error during fight execution."""

    pass


# ---------------------------------------------------------------- compile cache
#
# The generator caches compiled AIs on disk (`ai/AI_<hash>.class` next to a
# `.sig` sidecar, JavaCompiler.java). The class name is a hash of the AI's
# path and the signature covers the mtimes of the whole include tree, so a
# cached class is only reused for the same tree, unchanged -- different
# scenarios, seeds and builds all hit. Measured on a Claudius/Claudias fight:
# 10.3s with --nocache, 3.4s cached (compile 5.3s -> 0). The old default of
# --nocache was throwing that away on every fight.
#
# The one hazard is the first compile: two JVMs asked to compile the SAME
# path at the SAME time both write `AI_<hash>.class`, and the loser can read
# a half-written file. So the first fight of each AI path in this process
# runs holding a per-path lock; once it has returned, the class is on disk
# and every later fight on that path proceeds freely. Paths are locked in
# sorted order so a fight needing two unwarmed paths cannot deadlock against
# another needing the same two.

_warm_lock = threading.Lock()
_warmed: set[str] = set()
_path_locks: dict[str, threading.Lock] = {}


def _scenario_ai_paths(scenario_dict: dict) -> list[str]:
    """AI paths of every entity in a generator scenario dict."""
    paths = []
    for team in scenario_dict.get("entities", []):
        for entity in team:
            ai = entity.get("ai") or entity.get("ai_path")
            if ai:
                paths.append(str(ai))
    return paths


@contextmanager
def _compile_guard(ai_paths: Iterable[str], nocache: bool):
    """Hold the per-path lock for every AI path not yet compiled by this process."""
    held: list[tuple[str, threading.Lock]] = []
    if not nocache:
        for path in sorted(set(ai_paths)):
            with _warm_lock:
                if path in _warmed:
                    continue
                lock = _path_locks.setdefault(path, threading.Lock())
            lock.acquire()
            with _warm_lock:
                warmed = path in _warmed
            if warmed:
                # Someone finished it while we waited.
                lock.release()
            else:
                held.append((path, lock))
    ok = False
    try:
        yield
        ok = True
    finally:
        for path, lock in held:
            if ok:
                with _warm_lock:
                    _warmed.add(path)
            lock.release()


def forget_warm_cache() -> None:
    """Reset the compile guard (an AI tree was rewritten under a path this process already warmed)."""
    with _warm_lock:
        _warmed.clear()


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
    nocache: bool = False,
) -> dict:
    """
    Run a single fight scenario and return the result.

    Args:
        scenario: The fight scenario to run
        timeout: Maximum execution time in seconds
        nocache: If True, bypass the generator's on-disk compile cache. Only
            useful when debugging the cache itself: it is keyed by AI path and
            invalidated by source mtime, so varied scenarios are safe with it.

    Returns:
        Parsed JSON output from the generator

    Raises:
        RunnerError: If the fight fails to execute
    """
    # Write scenario to temp file
    scenario_dict = scenario.to_dict()
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        f.write(json.dumps(scenario_dict, indent=2))
        scenario_path = Path(f.name)

    try:
        cmd = _build_command(scenario_path, nocache)

        # Execute
        with _compile_guard(_scenario_ai_paths(scenario_dict), nocache):
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
    nocache: bool = False,
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
        ai_paths = _scenario_ai_paths(json.loads(scenario_json))

        with _compile_guard(ai_paths, nocache):
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
