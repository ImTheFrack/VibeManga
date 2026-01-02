"""
Test suite for Phase 2, Step 1: CLI Modularization.

This test verifies that the CLI structure is correctly refactored, 
commands are registered, and base utilities function as expected.
"""

import pytest
import os
from pathlib import Path
from click.testing import CliRunner
import click

# Import the main entry point
from vibe_manga.vibe_manga.main import cli
from vibe_manga.vibe_manga.cli import base

class TestCLIInfrastructure:
    """Test the main CLI entry point and command registration."""

    def test_cli_group(self):
        """Verify that the entry point is a Click Group."""
        assert isinstance(cli, click.Group)

    def test_command_registration(self):
        """Verify that all expected commands are registered."""
        expected_commands = {
            "scrape", "match", "grab", "pull", "pullcomplete",
            "tree", "show", "dedupe", "stats",
            "metadata", "hydrate", "rename", "categorize"
        }
        registered_commands = set(cli.commands.keys())
        
        # Check that all expected commands are present
        missing = expected_commands - registered_commands
        assert not missing, f"Missing commands: {missing}"
        
        # Check that no unexpected commands are present
        extra = registered_commands - expected_commands
        assert not extra, f"Unexpected commands found: {extra}"


class TestCLIBaseUtilities:
    """Test shared CLI utilities in base.py."""

    def test_console_instance(self):
        """Verify the global console object is configured."""
        from rich.console import Console
        assert isinstance(base.console, Console)

    def test_get_library_root_from_config(self, monkeypatch, tmp_path):
        """Test retrieving library root from configuration."""
        # Mock the configuration to return a specific path
        def mock_get_config():
            class MockConfig:
                library_path = tmp_path
                manga_library_root = None
            return MockConfig()

        monkeypatch.setattr("vibe_manga.vibe_manga.cli.base.get_config", mock_get_config)
        
        root = base.get_library_root()
        assert root == tmp_path

    def test_get_library_root_from_env_fallback(self, monkeypatch, tmp_path):
        """Test retrieving library root from env var fallback."""
        # Mock config to return None (simulating missing config values)
        def mock_get_config():
            class MockConfig:
                library_path = None
                manga_library_root = None
            return MockConfig()

        monkeypatch.setattr("vibe_manga.vibe_manga.cli.base.get_config", mock_get_config)
        monkeypatch.setenv("MANGA_LIBRARY_ROOT", str(tmp_path))
        
        root = base.get_library_root()
        assert root == tmp_path

    def test_get_library_root_failure(self, monkeypatch):
        """Test that get_library_root exits if no path is found."""
        def mock_get_config():
            class MockConfig:
                library_path = None
                manga_library_root = None
            return MockConfig()

        monkeypatch.setattr("vibe_manga.vibe_manga.cli.base.get_config", mock_get_config)
        monkeypatch.delenv("MANGA_LIBRARY_ROOT", raising=False)
        
        # Should exit with code 1
        with pytest.raises(SystemExit) as excinfo:
            base.get_library_root()
        assert excinfo.value.code == 1


class TestCommandsSmoke:
    """Smoke tests for individual CLI commands."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    @pytest.mark.parametrize("command_name", [
        "scrape", "match", "grab", "pull", "pullcomplete",
        "tree", "show", "dedupe", "stats",
        "metadata", "hydrate", "rename", "categorize"
    ])
    def test_command_help(self, runner, command_name):
        """Test that each command can display its help message."""
        # We invoke via the main cli group to ensure registration is correct
        result = runner.invoke(cli, [command_name, "--help"])
        
        assert result.exit_code == 0, f"Command '{command_name} --help' failed with exit code {result.exit_code}. Output:\n{result.output}"
        assert "Usage:" in result.output
        # Basic check to ensure the help text corresponds to the command
        assert command_name in result.output or command_name.capitalize() in result.output

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
