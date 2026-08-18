"""
Centralized path and configuration management for TagadAI.

All project paths should be accessed through this module.
"""

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


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
    def scenarios_dir(self) -> Path:
        """RL scenarios directory."""
        return self.root / "scenarios"

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
