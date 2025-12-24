"""
Tests for the RL CLI tool.
"""

import pytest
import subprocess
import sys
from pathlib import Path


@pytest.fixture
def project_root():
    """Get project root directory."""
    return Path(__file__).parent.parent.parent


def run_cli(*args, timeout=60):
    """Run the RL CLI with given arguments."""
    cmd = [sys.executable, "-m", "src.tools.rl"] + list(args)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=Path(__file__).parent.parent.parent,
    )
    return result


class TestRLCLI:
    """Tests for RL CLI commands."""

    def test_help(self):
        """Test --help flag."""
        result = run_cli("--help")
        assert result.returncode == 0
        assert "duel" in result.stdout
        assert "scenario" in result.stdout
        assert "env" in result.stdout

    def test_duel_help(self):
        """Test duel --help."""
        result = run_cli("duel", "--help")
        assert result.returncode == 0
        assert "--seed" in result.stdout
        assert "--bot1" in result.stdout

    def test_scenario_help(self):
        """Test scenario --help."""
        result = run_cli("scenario", "--help")
        assert result.returncode == 0
        assert "--workers" in result.stdout
        assert "--summary" in result.stdout

    def test_env_help(self):
        """Test env --help."""
        result = run_cli("env", "--help")
        assert result.returncode == 0
        assert "--episodes" in result.stdout
        assert "--agent" in result.stdout

    def test_duel_basic(self):
        """Test basic duel command."""
        result = run_cli("duel", "--seed", "42")
        assert result.returncode == 0
        assert "Result" in result.stdout
        assert "Duration" in result.stdout

    def test_duel_with_telemetry(self):
        """Test duel with telemetry flag."""
        result = run_cli("duel", "--seed", "42", "--telemetry")
        assert result.returncode == 0
        assert "Telemetry" in result.stdout
        assert "Damage dealt" in result.stdout

    def test_scenario_basic(self, project_root):
        """Test basic scenario command."""
        yaml_file = project_root / "scenarios" / "sample_scenarios.yml"
        if not yaml_file.exists():
            pytest.skip("Sample scenarios file not found")

        result = run_cli("scenario", str(yaml_file), "--quiet", timeout=120)
        assert result.returncode == 0
        assert "Results" in result.stdout

    def test_scenario_with_summary(self, project_root, tmp_path):
        """Test scenario with summary output."""
        yaml_file = project_root / "scenarios" / "sample_scenarios.yml"
        if not yaml_file.exists():
            pytest.skip("Sample scenarios file not found")

        summary_file = tmp_path / "summary.json"
        result = run_cli(
            "scenario",
            str(yaml_file),
            "--quiet",
            "--summary", str(summary_file),
            timeout=120,
        )
        assert result.returncode == 0
        assert summary_file.exists()

    def test_env_basic(self):
        """Test basic env command."""
        result = run_cli("env", "--episodes", "1", "--seed", "42", "--quiet")
        assert result.returncode == 0
        assert "Summary" in result.stdout
        assert "Episodes" in result.stdout

    def test_env_multiple_episodes(self):
        """Test env with multiple episodes."""
        result = run_cli("env", "--episodes", "3", "--seed", "42")
        assert result.returncode == 0
        assert "Episode 1/3" in result.stdout
        assert "Episode 3/3" in result.stdout
        assert "Wins:" in result.stdout

    def test_duel_deterministic(self):
        """Test that same seed produces same result."""
        result1 = run_cli("duel", "--seed", "12345")
        result2 = run_cli("duel", "--seed", "12345")

        assert result1.returncode == 0
        assert result2.returncode == 0

        # Extract duration from output
        def extract_duration(output):
            for line in output.split("\n"):
                if "Duration:" in line:
                    return line.strip()
            return None

        assert extract_duration(result1.stdout) == extract_duration(result2.stdout)
