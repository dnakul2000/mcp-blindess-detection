"""Tests for src.gui.config."""

from __future__ import annotations

from src.gui.config import (
    GUI_DIR,
    HOST,
    KEY_STORE_DIR,
    KEY_STORE_PATH,
    PORT,
    PROJECT_ROOT,
    RESULTS_DIR,
    STATIC_DIR,
    TEMPLATES_DIR,
)


def test_templates_dir_exists() -> None:
    assert TEMPLATES_DIR.exists()
    assert TEMPLATES_DIR.is_dir()


def test_static_dir_exists() -> None:
    assert STATIC_DIR.exists()
    assert STATIC_DIR.is_dir()


def test_gui_dir_contains_templates_and_static() -> None:
    assert TEMPLATES_DIR.parent == GUI_DIR
    assert STATIC_DIR.parent == GUI_DIR


def test_results_dir_under_project() -> None:
    assert RESULTS_DIR.parent == PROJECT_ROOT


def test_server_settings() -> None:
    assert HOST == "127.0.0.1"
    assert PORT == 8420


def test_key_store_path() -> None:
    assert KEY_STORE_PATH.parent == KEY_STORE_DIR
    assert KEY_STORE_PATH.name == "keys.json"
