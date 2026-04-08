"""Tests for src.gui.app."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI


def test_create_app_returns_fastapi() -> None:
    with patch("src.gui.services.key_service.load_keys_into_env"):
        from src.gui.app import create_app

        app = create_app()
        assert isinstance(app, FastAPI)


def test_create_app_has_routes() -> None:
    with patch("src.gui.services.key_service.load_keys_into_env"):
        from src.gui.app import create_app

        app = create_app()
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/" in paths
        assert "/experiments" in paths
        assert "/results" in paths
        assert "/analysis" in paths
        assert "/keys" in paths
