"""
Centralized path and configuration management for TagadAI.

All project paths should be accessed through this module.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

# The generator is built with `sourceCompatibility = 25`, so its classes are
# class-file version 69 and refuse to load on an older JVM.
MIN_JAVA_VERSION = 25


@lru_cache(maxsize=None)
def java_version(java_bin: Path) -> int:
    """
    Feature version of a Java executable (e.g. 25), or 0 if it can't be read.

    `java -version` writes to stderr and formats the version as "25.0.4" on
    modern JDKs and "1.8.0_452" on Java 8, so the leading number is enough to
    reject anything older than we need.
    """
    try:
        proc = subprocess.run(
            [str(java_bin), "-version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return 0

    match = re.search(r'version "(\d+)', proc.stderr or proc.stdout)
    return int(match.group(1)) if match else 0


def get_project_root() -> Path:
    """Get the project root directory."""
    # This file is at src/common/config.py, so root is 3 levels up
    return Path(__file__).parent.parent.parent


@dataclass
class ProjectPaths:
    """
    All project paths in one place.

    Supports environment variable overrides:
    - TAGADAI_DATA_DIR: Override data directory location
    """

    root: Path

    @property
    def data_dir(self) -> Path:
        """Main data directory."""
        override = os.getenv("TAGADAI_DATA_DIR")
        if override:
            return Path(override)
        return self.root / "data"

    @property
    def fights_log_dir(self) -> Path:
        """Fight logs directory (for tools/fight.py)."""
        return self.data_dir / "fights"

    @property
    def database_path(self) -> Path:
        """SQLite database for scraped fights."""
        return self.data_dir / "fights.db"

    @property
    def generator_dir(self) -> Path:
        """Local fight generator directory."""
        override = os.getenv("TAGADAI_GENERATOR_DIR")
        if override:
            return Path(override)
        return self.root / ".cache" / "leek-wars-generator"

    @property
    def generator_jar(self) -> Path:
        """Path to the generator JAR file."""
        return self.generator_dir / "generator.jar"

    @property
    def toolchain_dir(self) -> Path:
        """Downloaded build/run toolchain (JDK, Gradle) for the generator."""
        return self.root / ".cache" / "toolchain"

    @property
    def java_bin(self) -> Optional[Path]:
        """
        Java executable able to run the generator (needs Java 25+).

        Resolution order: TAGADAI_JAVA_HOME, the JDK unpacked under
        .cache/toolchain, JAVA_HOME, then `java` on PATH. Returns None if
        no candidate is new enough.
        """
        for candidate in self._java_candidates():
            if candidate.exists() and java_version(candidate) >= MIN_JAVA_VERSION:
                return candidate
        return None

    def _java_candidates(self):
        override = os.getenv("TAGADAI_JAVA_HOME")
        if override:
            yield Path(override) / "bin" / "java"

        # JDKs unpacked by scripts/setup_generator.sh, newest version first.
        for jdk in sorted(self.toolchain_dir.glob("jdk-*"), reverse=True):
            yield jdk / "bin" / "java"

        java_home = os.getenv("JAVA_HOME")
        if java_home:
            yield Path(java_home) / "bin" / "java"

        on_path = shutil.which("java")
        if on_path:
            yield Path(on_path)

    @classmethod
    def default(cls) -> "ProjectPaths":
        """Get default project paths."""
        return cls(root=get_project_root())


# Singleton instance for convenience
_paths: Optional[ProjectPaths] = None


def get_paths() -> ProjectPaths:
    """Get the project paths singleton."""
    global _paths
    if _paths is None:
        _paths = ProjectPaths.default()
    return _paths
