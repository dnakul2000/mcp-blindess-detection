"""Experiment orchestration for MCP detection-blindness research.

Loads experiment configurations from JSON files, runs each experiment
through the proxy-wrapped adversarial server with the specified LLM
provider, and collects structured results with timing data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.client.agent import AgentLoop, AgentResult
from src.client.providers.ollama import OllamaAdapter

if TYPE_CHECKING:
    from src.analysis.compliance import ComplianceResult
    from src.client.providers.base import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class ExperimentConfig:
    """Configuration for a single experiment.

    Attributes:
        experiment_id: Unique identifier for this experiment (auto-generated).
        hypothesis: The hypothesis being tested (e.g. "H2", "H3", "control").
        variant: The specific variant of the hypothesis (e.g. "direct_injection").
        server_module: Python module path for the MCP server to run.
        provider: LLM provider identifier (e.g. "ollama", "anthropic").
        model: Model identifier to pass to the provider.
        prompt_file: Path to the file containing the user prompt.
        repetitions: Number of times to repeat this experiment.
        env_vars: Environment variables to set before running the server.
    """

    hypothesis: str
    variant: str
    server_module: str
    provider: str
    model: str
    prompt_file: str
    repetitions: int = 5
    env_vars: dict[str, str] = field(default_factory=dict)
    experiment_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass
class RunResult:
    """Result of a single experiment run.

    Attributes:
        experiment_id: The experiment this run belongs to.
        run_number: Sequential run number within the experiment.
        db_path: Path to the SQLite database for this run.
        success: Whether the run completed without error.
        error: Error message if the run failed, None otherwise.
        duration_seconds: Wall-clock duration of the run in seconds.
    """

    experiment_id: str
    run_number: int
    db_path: Path
    success: bool
    error: str | None
    duration_seconds: float


def _create_provider(provider_name: str) -> LLMProvider:
    """Create an LLM provider adapter by name.

    Args:
        provider_name: Canonical provider name (e.g. "ollama", "anthropic",
            "openai", "google").

    Returns:
        An instantiated LLM provider adapter.

    Raises:
        ValueError: If the provider name is not recognised.
    """
    if provider_name == "ollama":
        return OllamaAdapter()

    if provider_name == "anthropic":
        from src.client.providers.anthropic import AnthropicAdapter

        return AnthropicAdapter(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

    if provider_name in ("openai", "openrouter"):
        from src.client.providers.openai_compat import OpenAICompatAdapter

        if provider_name == "openrouter":
            return OpenAICompatAdapter(
                base_url="https://openrouter.ai/api/v1",
                api_key=os.environ.get("OPENROUTER_API_KEY", ""),
                provider_name_override="openrouter",
            )
        return OpenAICompatAdapter(
            base_url="https://api.openai.com/v1",
            api_key=os.environ.get("OPENAI_API_KEY", ""),
        )

    if provider_name == "google":
        from src.client.providers.google import GoogleAdapter

        return GoogleAdapter(api_key=os.environ.get("GOOGLE_API_KEY", ""))

    msg = f"Unknown provider: {provider_name!r}"
    raise ValueError(msg)


def _read_prompt(prompt_file: str) -> str:
    """Read the user prompt from a text file.

    Args:
        prompt_file: Path to the prompt file, relative to the project root.

    Returns:
        The prompt text with leading/trailing whitespace stripped.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    path = Path(prompt_file)
    if not path.exists():
        msg = f"Prompt file not found: {path}"
        raise FileNotFoundError(msg)
    return path.read_text(encoding="utf-8").strip()


def _save_agent_result(
    output_dir: Path,
    result: AgentResult,
    compliance_results: list[ComplianceResult] | None = None,
) -> None:
    """Save the agent result to a JSON file in the output directory.

    Args:
        output_dir: Directory to write the result file into.
        result: The agent result to serialise.
        compliance_results: Optional compliance classification results
            from post-run analysis.
    """
    # Compute worst-case compliance across all sessions.
    compliance = "no_data"
    if compliance_results:
        level_priority = {
            "full_execution": 0,
            "partial_compliance": 1,
            "instruction_leakage": 2,
            "silent_refusal": 3,
        }
        worst = min(
            compliance_results,
            key=lambda r: level_priority.get(r.level.value, 99),
        )
        compliance = worst.level.value

    data: dict[str, Any] = {
        "final_response": result.final_response,
        "iterations": result.iterations,
        "tool_calls_made": [
            {"tool_name": tc.tool_name, "arguments": tc.arguments} for tc in result.tool_calls_made
        ],
        "operator_log": result.operator_log,
        "compliance": compliance,
        "timed_out": result.timed_out,
    }
    output_file = output_dir / "agent_result.json"
    output_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


async def run_single(
    config: ExperimentConfig,
    run_number: int,
    results_dir: Path,
) -> RunResult:
    """Execute a single experiment run.

    Creates output directory, sets environment variables, constructs the
    proxy-wrapped server command, runs the agent loop, and saves results.

    Args:
        config: The experiment configuration.
        run_number: The sequential run number (1-based).
        results_dir: Root directory for all experiment results.

    Returns:
        A RunResult with timing and success/error information.
    """
    output_dir = results_dir / config.experiment_id / f"run_{run_number}"
    output_dir.mkdir(parents=True, exist_ok=True)

    db_path = output_dir / "experiment.db"

    # Save config to output dir for reproducibility.
    config_out: dict[str, Any] = {
        "experiment_id": config.experiment_id,
        "hypothesis": config.hypothesis,
        "variant": config.variant,
        "server_module": config.server_module,
        "provider": config.provider,
        "model": config.model,
        "prompt_file": config.prompt_file,
        "run_number": run_number,
        "env_vars": config.env_vars,
    }
    (output_dir / "config.json").write_text(
        json.dumps(config_out, indent=2),
        encoding="utf-8",
    )

    # Set environment variables for this run.
    # NOTE: Environment mutations are safe here because experiments run
    # sequentially (see run_experiment / run_batch). The finally block
    # restores original values. Do NOT parallelise without refactoring
    # to use subprocess env dicts.
    original_env: dict[str, str | None] = {}
    for key, value in config.env_vars.items():
        original_env[key] = os.environ.get(key)
        os.environ[key] = value

    start_time = time.monotonic()

    try:
        prompt = _read_prompt(config.prompt_file)
        provider = _create_provider(config.provider)

        # Proxy-wrapped server command:
        # python -m src.proxy --db <db_path> -- uv run python -m <server_module>
        proxy_command = [
            "uv",
            "run",
            "python",
            "-m",
            "src.proxy",
            "--db",
            str(db_path),
            "--",
            "uv",
            "run",
            "python",
            "-m",
            config.server_module,
        ]

        agent = AgentLoop(
            server_command=proxy_command,
            provider=provider,
            model=config.model,
            max_seconds=float(config.env_vars.get("MAX_SECONDS", "120")),
            db_path=str(db_path),
        )

        try:
            agent_result = await asyncio.wait_for(
                agent.run(prompt),
                timeout=float(config.env_vars.get("RUN_TIMEOUT", 180)),
            )
        except TimeoutError:
            agent_result = AgentResult(
                final_response="Run-level timeout reached",
                timed_out=True,
            )
            logger.warning("Run %d timed out at run level", run_number)

        # Run compliance classification on the completed DB.
        compliance_results_list: list[ComplianceResult] = []
        try:
            from src.analysis.compliance import classify_compliance

            compliance_results_list = await classify_compliance(db_path)
        except Exception:  # noqa: BLE001
            logger.warning("Compliance classification failed for run %d", run_number)

        _save_agent_result(output_dir, agent_result, compliance_results_list)

        duration = time.monotonic() - start_time
        return RunResult(
            experiment_id=config.experiment_id,
            run_number=run_number,
            db_path=db_path,
            success=True,
            error=None,
            duration_seconds=round(duration, 3),
        )

    except Exception as exc:  # noqa: BLE001
        duration = time.monotonic() - start_time
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.exception("Run %d failed: %s", run_number, error_msg)

        # Save error details.
        (output_dir / "error.txt").write_text(error_msg, encoding="utf-8")

        return RunResult(
            experiment_id=config.experiment_id,
            run_number=run_number,
            db_path=db_path,
            success=False,
            error=error_msg,
            duration_seconds=round(duration, 3),
        )

    finally:
        # Restore original environment variables.
        for key, original_value in original_env.items():
            if original_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original_value


async def run_experiment(
    config: ExperimentConfig,
    results_dir: Path,
) -> list[RunResult]:
    """Run all repetitions of a single experiment configuration.

    Executes runs sequentially and prints progress to stdout.

    Args:
        config: The experiment configuration.
        results_dir: Root directory for all experiment results.

    Returns:
        List of RunResult instances, one per repetition.
    """
    results: list[RunResult] = []
    total = config.repetitions

    for n in range(1, total + 1):
        print(
            f"Run {n}/{total} — {config.model} — {config.hypothesis}/{config.variant}",
        )
        result = await run_single(config, n, results_dir)
        status = "OK" if result.success else f"FAIL: {result.error}"
        print(f"  -> {status} ({result.duration_seconds:.1f}s)")
        results.append(result)

    return results


async def run_batch(
    configs: list[ExperimentConfig],
    results_dir: Path,
) -> list[RunResult]:
    """Run a batch of experiment configurations sequentially.

    Args:
        configs: List of experiment configurations to execute.
        results_dir: Root directory for all experiment results.

    Returns:
        Flat list of all RunResult instances across all experiments.
    """
    all_results: list[RunResult] = []

    for i, config in enumerate(configs, 1):
        print(
            f"\n=== Experiment {i}/{len(configs)}: "
            f"{config.hypothesis}/{config.variant} "
            f"({config.provider}/{config.model}) ===",
        )
        experiment_results = await run_experiment(config, results_dir)
        all_results.extend(experiment_results)

    # Print summary.
    succeeded = sum(1 for r in all_results if r.success)
    failed = sum(1 for r in all_results if not r.success)
    total_time = sum(r.duration_seconds for r in all_results)
    print(f"\n=== Batch complete: {succeeded} passed, {failed} failed, {total_time:.1f}s total ===")

    return all_results


def load_configs_from_json(json_path: Path) -> list[ExperimentConfig]:
    """Load experiment configurations from a JSON file.

    The file may contain a single config object or a list of config objects.
    Each object must have keys matching ExperimentConfig fields (excluding
    experiment_id which is auto-generated).

    Args:
        json_path: Path to the JSON configuration file.

    Returns:
        List of ExperimentConfig instances.

    Raises:
        FileNotFoundError: If the JSON file does not exist.
        ValueError: If the JSON structure is invalid.
    """
    if not json_path.exists():
        msg = f"Config file not found: {json_path}"
        raise FileNotFoundError(msg)

    raw = json.loads(json_path.read_text(encoding="utf-8"))

    if isinstance(raw, dict):
        raw = [raw]

    if not isinstance(raw, list):
        msg = f"Expected a JSON object or array, got {type(raw).__name__}"
        raise ValueError(msg)

    configs: list[ExperimentConfig] = []
    for item in raw:
        configs.append(
            ExperimentConfig(
                hypothesis=item["hypothesis"],
                variant=item["variant"],
                server_module=item["server_module"],
                provider=item["provider"],
                model=item["model"],
                prompt_file=item["prompt_file"],
                repetitions=item.get("repetitions", 5),
                env_vars=item.get("env_vars", {}),
            ),
        )

    return configs


def main() -> None:
    """Parse command-line arguments and run the experiment batch."""
    parser = argparse.ArgumentParser(
        description="Run MCP detection-blindness experiments",
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to JSON config file (single object or array of objects)",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("results"),
        help="Root directory for experiment results (default: results/)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    configs = load_configs_from_json(args.config)
    print(f"Loaded {len(configs)} experiment config(s) from {args.config}")

    results_dir: Path = args.results_dir
    results_dir.mkdir(parents=True, exist_ok=True)

    results = asyncio.run(run_batch(configs, results_dir))

    # Save batch summary.
    summary_path = results_dir / "batch_summary.json"
    summary = [
        {
            "experiment_id": r.experiment_id,
            "run_number": r.run_number,
            "db_path": str(r.db_path),
            "success": r.success,
            "error": r.error,
            "duration_seconds": r.duration_seconds,
        }
        for r in results
    ]
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Batch summary written to {summary_path}")


if __name__ == "__main__":
    main()
