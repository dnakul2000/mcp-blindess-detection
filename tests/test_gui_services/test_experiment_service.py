"""Tests for src.gui.services.experiment_service."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from experiments.runner import RunResult
from src.gui.services.experiment_service import ExperimentManager, RunningExperiment


def _make_result(exp_id: str = "test", **kwargs: object) -> RunResult:
    defaults = {
        "experiment_id": exp_id,
        "run_number": 1,
        "db_path": Path("/tmp/test.db"),
        "success": True,
        "error": None,
        "duration_seconds": 1.0,
    }
    defaults.update(kwargs)
    return RunResult(**defaults)  # type: ignore[arg-type]


def test_running_experiment_defaults() -> None:
    exp = RunningExperiment(experiment_id="abc", config={})
    assert exp.status == "pending"
    assert exp.log_lines == []
    assert exp.completed_runs == 0
    assert exp.total_runs == 0


def test_get_unknown_returns_none() -> None:
    mgr = ExperimentManager()
    assert mgr.get("nonexistent") is None


def test_list_running_empty() -> None:
    mgr = ExperimentManager()
    assert mgr.list_running() == []


def _make_config(exp_id: str = "test123") -> dict[str, object]:
    return {
        "experiment_id": exp_id,
        "hypothesis": "H3",
        "variant": "direct",
        "server_module": "src.servers.echo",
        "provider": "ollama",
        "model": "llama3.2",
        "prompt_file": "experiments/prompts/test.txt",
        "repetitions": 1,
    }


async def test_launch_creates_experiment(tmp_path: Path) -> None:
    mgr = ExperimentManager()
    config = _make_config("test123")

    with (
        patch(
            "experiments.runner.run_single",
            new_callable=AsyncMock,
            return_value=_make_result("test123"),
        ),
        patch("src.gui.config.RESULTS_DIR", tmp_path),
    ):
        exp_id = mgr.launch(config)
        assert exp_id == "test123"
        await asyncio.sleep(0.1)

        state = mgr.get("test123")
        assert state is not None
        assert state["experiment_id"] == "test123"


async def test_launch_and_list(tmp_path: Path) -> None:
    mgr = ExperimentManager()
    config = _make_config("listtest")

    with (
        patch(
            "experiments.runner.run_single",
            new_callable=AsyncMock,
            return_value=_make_result("listtest"),
        ),
        patch("src.gui.config.RESULTS_DIR", tmp_path),
    ):
        mgr.launch(config)
        listing = mgr.list_running()
        assert len(listing) == 1
        assert listing[0]["experiment_id"] == "listtest"
        await asyncio.sleep(0.1)


async def test_run_success(tmp_path: Path) -> None:
    mgr = ExperimentManager()
    config = _make_config("ok_exp")

    with (
        patch(
            "experiments.runner.run_single",
            new_callable=AsyncMock,
            return_value=_make_result("ok_exp", duration_seconds=2.0),
        ),
        patch("src.gui.config.RESULTS_DIR", tmp_path),
    ):
        mgr.launch(config)
        await asyncio.sleep(0.2)

    state = mgr.get("ok_exp")
    assert state is not None
    assert state["status"] == "completed"
    assert any("OK" in line for line in state["log_lines"])


async def test_run_failure(tmp_path: Path) -> None:
    mgr = ExperimentManager()
    config = _make_config("fail_exp")

    with (
        patch(
            "experiments.runner.run_single",
            new_callable=AsyncMock,
            return_value=_make_result("fail_exp", success=False, error="Timeout"),
        ),
        patch("src.gui.config.RESULTS_DIR", tmp_path),
    ):
        mgr.launch(config)
        await asyncio.sleep(0.2)

    state = mgr.get("fail_exp")
    assert state is not None
    assert any("FAILED" in line for line in state["log_lines"])


async def test_run_exception(tmp_path: Path) -> None:
    mgr = ExperimentManager()
    config = _make_config("exc_exp")

    with (
        patch(
            "experiments.runner.run_single",
            new_callable=AsyncMock,
            side_effect=RuntimeError("connection refused"),
        ),
        patch("src.gui.config.RESULTS_DIR", tmp_path),
    ):
        mgr.launch(config)
        await asyncio.sleep(0.2)

    state = mgr.get("exc_exp")
    assert state is not None
    assert any("ERROR" in line for line in state["log_lines"])


async def test_run_setup_failure(tmp_path: Path) -> None:
    """Experiment status becomes 'failed' when setup raises before the run loop."""
    mgr = ExperimentManager()
    # Missing required keys triggers a KeyError during ExperimentConfig construction.
    config: dict[str, object] = {
        "experiment_id": "setup_fail",
        "hypothesis": "H3",
        # Missing: variant, server_module, provider, model, prompt_file
        "repetitions": 1,
    }

    with patch("src.gui.config.RESULTS_DIR", tmp_path):
        mgr.launch(config)
        await asyncio.sleep(0.2)

    state = mgr.get("setup_fail")
    assert state is not None
    assert state["status"] == "failed"
    assert any("failed" in line.lower() for line in state["log_lines"])
