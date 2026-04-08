"""Tests for src.gui.routes.experiments."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from httpx import AsyncClient


async def test_form_page(client: AsyncClient) -> None:
    with patch("src.gui.routes.experiments.get_key_status", return_value={}):
        resp = await client.get("/experiments")
    assert resp.status_code == 200


async def test_launch_redirects(client: AsyncClient) -> None:
    with patch("src.gui.routes.experiments.experiment_manager") as mock_mgr:
        mock_mgr.launch.return_value = "abc123"
        resp = await client.post(
            "/experiments/launch",
            data={
                "hypothesis": "H3",
                "variant": "direct",
                "provider": "ollama",
                "model": "llama3.2",
                "prompt_file": "test.txt",
                "repetitions": "1",
                "max_seconds": "120",
                "query_timeout": "60",
                "tool_timeout": "30",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 303
    assert "/experiments/" in resp.headers["location"]
    assert "/monitor" in resp.headers["location"]


async def test_monitor_page(client: AsyncClient) -> None:
    with patch("src.gui.routes.experiments.experiment_manager") as mock_mgr:
        mock_mgr.get.return_value = {
            "experiment_id": "abc123",
            "status": "running",
            "log_lines": [],
            "completed_runs": 0,
            "total_runs": 5,
            "config": {
                "hypothesis": "H3",
                "variant": "direct",
                "provider": "ollama",
                "model": "llama3.2",
            },
        }
        resp = await client.get("/experiments/abc123/monitor")
    assert resp.status_code == 200


def test_get_prompt_files_empty(tmp_path: Path) -> None:
    from src.gui.routes.experiments import _get_prompt_files

    with patch("src.gui.routes.experiments.PROMPTS_DIR", tmp_path / "nonexistent"):
        result = _get_prompt_files()
    assert result == []


def test_get_prompt_files_with_files(tmp_path: Path) -> None:
    from src.gui.routes.experiments import _get_prompt_files

    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "test1.txt").touch()
    (prompts / "test2.txt").touch()
    (prompts / "ignore.py").touch()  # not .txt

    with patch("src.gui.routes.experiments.PROMPTS_DIR", prompts):
        result = _get_prompt_files()
    assert result == ["test1.txt", "test2.txt"]


async def test_launch_sets_injection_variant(client: AsyncClient) -> None:
    with patch("src.gui.routes.experiments.experiment_manager") as mock_mgr:
        mock_mgr.launch.return_value = "test"
        await client.post(
            "/experiments/launch",
            data={
                "hypothesis": "H3",
                "variant": "direct",
                "provider": "ollama",
                "model": "llama3.2",
                "prompt_file": "test.txt",
                "repetitions": "1",
                "max_seconds": "120",
                "query_timeout": "60",
                "tool_timeout": "30",
            },
            follow_redirects=False,
        )
        launched_config = mock_mgr.launch.call_args[0][0]
        assert launched_config["env_vars"]["INJECTION_VARIANT"] == "direct"
