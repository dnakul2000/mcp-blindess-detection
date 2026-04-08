"""Tests for src.proxy.__main__."""

from __future__ import annotations

import pytest

from src.proxy.__main__ import _parse_args


def test_parse_args_with_separator() -> None:
    db, cmd = _parse_args(["--db", "my.db", "--", "uv", "run", "echo"])
    assert db == "my.db"
    assert cmd == ["uv", "run", "echo"]


def test_parse_args_without_separator() -> None:
    db, cmd = _parse_args(["uv", "run", "echo"])
    assert db == "experiment.db"
    assert cmd == ["uv", "run", "echo"]


def test_parse_args_db_without_separator() -> None:
    db, cmd = _parse_args(["--db", "my.db", "uv", "run", "echo"])
    assert db == "my.db"
    assert cmd == ["uv", "run", "echo"]


def test_parse_args_default_db() -> None:
    db, cmd = _parse_args(["--", "some", "command"])
    assert db == "experiment.db"
    assert cmd == ["some", "command"]


def test_parse_args_empty_exits() -> None:
    with pytest.raises(SystemExit):
        _parse_args([])


def test_parse_args_separator_only_exits() -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--"])


def test_parse_args_pre_separator_extra_args() -> None:
    """Extra args before -- with --db extracted are ignored."""
    db, cmd = _parse_args(["--db", "test.db", "extra", "--", "server"])
    assert db == "test.db"
    assert cmd == ["server"]
