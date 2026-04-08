"""Extended tests for experiments/runner.py — execution paths."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from experiments.runner import (
    ExperimentConfig,
    RunResult,
    _create_provider,
    _save_agent_result,
    load_configs_from_json,
    run_batch,
    run_experiment,
    run_single,
)
from src.client.agent import AgentResult
from src.client.providers.base import ToolCall

# ---------------------------------------------------------------------------
# _save_agent_result
# ---------------------------------------------------------------------------


def test_save_agent_result(tmp_path: Path) -> None:
    result = AgentResult(
        final_response="done",
        tool_calls_made=[ToolCall(tool_name="echo", arguments={"message": "hi"})],
        iterations=2,
        operator_log=["tool=echo args={} result=hi"],
    )
    _save_agent_result(tmp_path, result)
    out = json.loads((tmp_path / "agent_result.json").read_text())
    assert out["final_response"] == "done"
    assert out["iterations"] == 2
    assert len(out["tool_calls_made"]) == 1


# ---------------------------------------------------------------------------
# _create_provider — additional providers
# ---------------------------------------------------------------------------


def test_create_provider_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    from src.client.providers.anthropic import AnthropicAdapter

    p = _create_provider("anthropic")
    assert isinstance(p, AnthropicAdapter)


def test_create_provider_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from src.client.providers.openai_compat import OpenAICompatAdapter

    p = _create_provider("openai")
    assert isinstance(p, OpenAICompatAdapter)
    assert p.provider_name == "openai"


def test_create_provider_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    from src.client.providers.openai_compat import OpenAICompatAdapter

    p = _create_provider("openrouter")
    assert isinstance(p, OpenAICompatAdapter)
    assert p.provider_name == "openrouter"


def test_create_provider_google(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "gk-test")
    from src.client.providers.google import GoogleAdapter

    p = _create_provider("google")
    assert isinstance(p, GoogleAdapter)


# ---------------------------------------------------------------------------
# run_single
# ---------------------------------------------------------------------------


async def test_run_single_success(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("What is the weather?")

    config = ExperimentConfig(
        hypothesis="H3",
        variant="direct",
        server_module="src.servers.echo",
        provider="ollama",
        model="llama3.2",
        prompt_file=str(prompt_file),
        experiment_id="test_run",
    )

    mock_agent_result = AgentResult(final_response="The weather is fine.")

    with patch("experiments.runner.AgentLoop") as MockAgentLoop:
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=mock_agent_result)
        MockAgentLoop.return_value = mock_instance

        result = await run_single(config, 1, tmp_path)

    assert isinstance(result, RunResult)
    assert result.success is True
    assert result.error is None
    assert result.run_number == 1
    # Config should be saved.
    config_path = tmp_path / "test_run" / "run_1" / "config.json"
    assert config_path.exists()


async def test_run_single_failure(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("test")

    config = ExperimentConfig(
        hypothesis="H3",
        variant="direct",
        server_module="src.servers.echo",
        provider="ollama",
        model="llama3.2",
        prompt_file=str(prompt_file),
        experiment_id="fail_run",
    )

    with patch("experiments.runner.AgentLoop") as MockAgentLoop:
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(side_effect=RuntimeError("connection refused"))
        MockAgentLoop.return_value = mock_instance

        result = await run_single(config, 1, tmp_path)

    assert result.success is False
    assert "RuntimeError" in (result.error or "")
    # Error file should be saved.
    error_path = tmp_path / "fail_run" / "run_1" / "error.txt"
    assert error_path.exists()


async def test_run_single_timeout(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("test")

    config = ExperimentConfig(
        hypothesis="H3",
        variant="direct",
        server_module="src.servers.echo",
        provider="ollama",
        model="llama3.2",
        prompt_file=str(prompt_file),
        experiment_id="timeout_run",
        env_vars={"RUN_TIMEOUT": "0.001"},
    )

    with patch("experiments.runner.AgentLoop") as MockAgentLoop:
        mock_instance = MagicMock()

        async def slow_run(_prompt: str) -> AgentResult:
            import asyncio

            await asyncio.sleep(10)
            return AgentResult(final_response="never reached")

        mock_instance.run = slow_run
        MockAgentLoop.return_value = mock_instance

        result = await run_single(config, 1, tmp_path)

    assert result.success is True  # Timeout is handled gracefully, not an error.
    # The agent result should indicate timeout.
    result_path = tmp_path / "timeout_run" / "run_1" / "agent_result.json"
    assert result_path.exists()


async def test_run_single_env_vars_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("test")

    monkeypatch.delenv("TEST_ENV_VAR", raising=False)

    config = ExperimentConfig(
        hypothesis="H3",
        variant="direct",
        server_module="src.servers.echo",
        provider="ollama",
        model="llama3.2",
        prompt_file=str(prompt_file),
        experiment_id="env_test",
        env_vars={"TEST_ENV_VAR": "set_during_run"},
    )

    with patch("experiments.runner.AgentLoop") as MockAgentLoop:
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=AgentResult(final_response="done"))
        MockAgentLoop.return_value = mock_instance

        await run_single(config, 1, tmp_path)

    # Env var should be cleaned up.
    assert "TEST_ENV_VAR" not in os.environ


# ---------------------------------------------------------------------------
# run_experiment
# ---------------------------------------------------------------------------


async def test_run_experiment(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("test")

    config = ExperimentConfig(
        hypothesis="H3",
        variant="direct",
        server_module="src.servers.echo",
        provider="ollama",
        model="llama3.2",
        prompt_file=str(prompt_file),
        experiment_id="exp_test",
        repetitions=2,
    )

    with patch("experiments.runner.AgentLoop") as MockAgentLoop:
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=AgentResult(final_response="done"))
        MockAgentLoop.return_value = mock_instance

        results = await run_experiment(config, tmp_path)

    assert len(results) == 2
    assert all(r.success for r in results)


# ---------------------------------------------------------------------------
# run_batch
# ---------------------------------------------------------------------------


async def test_run_batch(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("test")

    configs = [
        ExperimentConfig(
            hypothesis="H3",
            variant="direct",
            server_module="src.servers.echo",
            provider="ollama",
            model="llama3.2",
            prompt_file=str(prompt_file),
            experiment_id="batch1",
            repetitions=1,
        ),
        ExperimentConfig(
            hypothesis="H2",
            variant="shadow",
            server_module="src.servers.shadow_params",
            provider="ollama",
            model="llama3.2",
            prompt_file=str(prompt_file),
            experiment_id="batch2",
            repetitions=1,
        ),
    ]

    with patch("experiments.runner.AgentLoop") as MockAgentLoop:
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=AgentResult(final_response="done"))
        MockAgentLoop.return_value = mock_instance

        results = await run_batch(configs, tmp_path)

    assert len(results) == 2


# ---------------------------------------------------------------------------
# load_configs edge cases
# ---------------------------------------------------------------------------


def test_load_configs_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        load_configs_from_json(Path("/nonexistent/config.json"))


def test_load_configs_invalid_json(tmp_path: Path) -> None:
    f = tmp_path / "bad.json"
    f.write_text('"just a string"')
    with pytest.raises(ValueError, match="Expected a JSON object or array"):
        load_configs_from_json(f)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_runner_main(tmp_path: Path) -> None:
    from experiments.runner import main

    config_data = {
        "hypothesis": "H3",
        "variant": "direct",
        "server_module": "src.servers.echo",
        "provider": "ollama",
        "model": "llama3.2",
        "prompt_file": "experiments/prompts/weather_query.txt",
        "repetitions": 1,
    }
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config_data))

    with (
        patch(
            "sys.argv",
            ["runner", "--config", str(config_file), "--results-dir", str(tmp_path / "results")],
        ),
        patch("experiments.runner.asyncio") as mock_asyncio,
    ):
        mock_asyncio.run = MagicMock()
        main()
        mock_asyncio.run.assert_called_once()


def test_runner_main_verbose(tmp_path: Path) -> None:
    from experiments.runner import main

    config_data = {
        "hypothesis": "H3",
        "variant": "direct",
        "server_module": "src.servers.echo",
        "provider": "ollama",
        "model": "llama3.2",
        "prompt_file": "experiments/prompts/weather_query.txt",
        "repetitions": 1,
    }
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config_data))

    with (
        patch(
            "sys.argv",
            [
                "runner",
                "--config",
                str(config_file),
                "--results-dir",
                str(tmp_path / "results"),
                "--verbose",
            ],
        ),
        patch("experiments.runner.asyncio") as mock_asyncio,
    ):
        mock_asyncio.run = MagicMock()
        main()
        mock_asyncio.run.assert_called_once()
