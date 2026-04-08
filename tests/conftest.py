"""Shared fixtures for MCP Detection Blindness test suite."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Yield a temporary path for an SQLite database file."""
    return tmp_path / "test_experiment.db"


@pytest.fixture
def echo_server_command() -> list[str]:
    """Return the command to start the echo MCP server."""
    return ["uv", "run", "python", "-m", "src.servers.echo"]
