"""Tests for src.gui.__main__."""

from __future__ import annotations

from unittest.mock import patch


def test_gui_main_calls_uvicorn() -> None:
    from src.gui.__main__ import main

    with (
        patch("src.gui.__main__.uvicorn") as mock_uvicorn,
        patch("src.gui.__main__.webbrowser") as mock_browser,
    ):
        main()
        mock_browser.open.assert_called_once()
        mock_uvicorn.run.assert_called_once()


def test_gui_main_uses_correct_host_port() -> None:
    from src.gui.__main__ import main
    from src.gui.config import HOST, PORT

    with (
        patch("src.gui.__main__.uvicorn") as mock_uvicorn,
        patch("src.gui.__main__.webbrowser"),
    ):
        main()
        call_kwargs = mock_uvicorn.run.call_args
        assert call_kwargs[1]["host"] == HOST or call_kwargs[0][0] == "src.gui.app:create_app"
        assert call_kwargs[1]["port"] == PORT
