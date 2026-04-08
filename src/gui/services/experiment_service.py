"""Experiment launch and monitoring service."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RunningExperiment:
    """State for a running or completed experiment."""

    experiment_id: str
    config: dict[str, Any]
    status: str = "pending"  # pending, running, completed, failed
    log_lines: list[str] = field(default_factory=list)
    task: asyncio.Task[None] | None = None
    completed_runs: int = 0
    total_runs: int = 0


class ExperimentManager:
    """Manages experiment lifecycle."""

    def __init__(self) -> None:
        self._experiments: dict[str, RunningExperiment] = {}

    def launch(self, config: dict[str, Any]) -> str:
        """Start an experiment in the background."""
        exp_id = config["experiment_id"]
        exp = RunningExperiment(
            experiment_id=exp_id,
            config=config,
            total_runs=config.get("repetitions", 5),
        )
        self._experiments[exp_id] = exp

        loop = asyncio.get_event_loop()
        exp.task = loop.create_task(self._run(exp))
        return exp_id

    def get(self, experiment_id: str) -> dict[str, Any] | None:
        """Get experiment state as a dict."""
        exp = self._experiments.get(experiment_id)
        if exp is None:
            return None
        return {
            "experiment_id": exp.experiment_id,
            "config": exp.config,
            "status": exp.status,
            "log_lines": exp.log_lines,
            "completed_runs": exp.completed_runs,
            "total_runs": exp.total_runs,
        }

    def list_running(self) -> list[dict[str, Any]]:
        """List all experiments with their status."""
        return [
            {
                "experiment_id": e.experiment_id,
                "status": e.status,
                "completed_runs": e.completed_runs,
                "total_runs": e.total_runs,
            }
            for e in self._experiments.values()
        ]

    async def _run(self, exp: RunningExperiment) -> None:
        """Execute the experiment via the existing runner."""
        from experiments.runner import ExperimentConfig, run_single

        from src.gui.config import RESULTS_DIR

        exp.status = "running"
        config = exp.config
        exp.log_lines.append(
            f"Starting experiment {config['experiment_id']}: "
            f"{config['hypothesis']}/{config['variant']} "
            f"({config['provider']}/{config['model']})"
        )

        experiment_config = ExperimentConfig(
            experiment_id=config["experiment_id"],
            hypothesis=config["hypothesis"],
            variant=config["variant"],
            server_module=config["server_module"],
            provider=config["provider"],
            model=config["model"],
            prompt_file=config["prompt_file"],
            repetitions=config.get("repetitions", 5),
            env_vars=config.get("env_vars", {}),
        )

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        for run_num in range(1, experiment_config.repetitions + 1):
            exp.log_lines.append(
                f"Run {run_num}/{experiment_config.repetitions} — "
                f"{config['provider']}/{config['model']}"
            )

            try:
                result = await run_single(experiment_config, run_num, RESULTS_DIR)
                if result.success:
                    exp.log_lines.append(f"  -> OK ({result.duration_seconds:.1f}s)")
                else:
                    exp.log_lines.append(f"  -> FAILED: {result.error}")
            except Exception as e:  # noqa: BLE001
                exp.log_lines.append(f"  -> ERROR: {e}")
                logger.exception("Run %d failed", run_num)

            exp.completed_runs = run_num

        exp.status = "completed"
        exp.log_lines.append("Experiment complete.")


# Module-level singleton
experiment_manager = ExperimentManager()
