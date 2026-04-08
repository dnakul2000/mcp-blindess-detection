"""Tests for src.servers.__main__."""

from __future__ import annotations

from unittest.mock import patch


def test_servers_main_calls_echo_main() -> None:
    with patch("src.servers.echo.main") as mock_main:
        # Re-importing the module triggers the top-level main() call.
        import importlib

        import src.servers.__main__

        importlib.reload(src.servers.__main__)
        mock_main.assert_called()
