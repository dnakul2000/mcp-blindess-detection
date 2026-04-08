"""Result aggregation across multiple experiment runs.

Scans a directory of experiment databases, runs event detection and compliance
classification on each, and produces summary exports in CSV and JSON.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

import aiosqlite

if TYPE_CHECKING:
    from pathlib import Path
import pandas as pd

from src.analysis.compliance import classify_compliance
from src.analysis.delta import compute_delta


@dataclass(frozen=True)
class ExperimentSummary:
    """Aggregated summary for a single experiment run."""

    experiment_id: str
    hypothesis: str
    variant: str
    provider: str
    model: str
    compliance: str
    detection_rate: float
    observability_delta: int


async def _extract_metadata(
    db_path: Path,
) -> tuple[str, str, str, str]:
    """Extract experiment metadata from adapter_requests.

    Args:
        db_path: Path to an experiment SQLite database.

    Returns:
        Tuple of (hypothesis, variant, provider, model).
    """
    hypothesis = "unknown"
    variant = "unknown"
    provider = "unknown"
    model = "unknown"

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Get provider and model from the first adapter_requests row.
        query = "SELECT provider, model FROM adapter_requests LIMIT 1"
        async with db.execute(query) as cursor:
            row = await cursor.fetchone()
            if row:
                provider = row["provider"] or "unknown"
                model = row["model"] or "unknown"

        # Infer hypothesis and variant from proxy_messages tool names.
        tool_query = "SELECT DISTINCT tool_name FROM proxy_tool_schemas"
        async with db.execute(tool_query) as cursor:
            tool_names: list[str] = [r["tool_name"] async for r in cursor if r["tool_name"]]

        for name in tool_names:
            if "shadow" in name.lower():
                hypothesis = "H2"
                variant = "control" if "control" in name.lower() else "treatment"
                break
            if "inject" in name.lower() or "response" in name.lower():
                hypothesis = "H3"
                variant = "control" if "control" in name.lower() else "treatment"
                break

    return hypothesis, variant, provider, model


async def aggregate_results(results_dir: Path) -> list[ExperimentSummary]:
    """Aggregate results from all experiment databases in a directory.

    For each ``experiment.db`` file found (recursively), runs event detection,
    compliance classification, and delta computation to build a summary.

    Args:
        results_dir: Directory containing experiment.db files (searched
            recursively).

    Returns:
        List of experiment summaries, one per database found.
    """
    summaries: list[ExperimentSummary] = []
    db_files = sorted(results_dir.rglob("experiment.db"))

    for db_path in db_files:
        experiment_id = db_path.parent.name or db_path.stem

        hypothesis, variant, provider, model = await _extract_metadata(db_path)
        compliance_results = await classify_compliance(db_path)
        delta_result = await compute_delta(db_path)

        # Use the most severe compliance level across all sessions.
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
            compliance_str = worst.level.value
        else:
            compliance_str = "no_data"

        summaries.append(
            ExperimentSummary(
                experiment_id=experiment_id,
                hypothesis=hypothesis,
                variant=variant,
                provider=provider,
                model=model,
                compliance=compliance_str,
                detection_rate=delta_result.detection_rate,
                observability_delta=delta_result.observability_delta,
            ),
        )

    return summaries


def export_csv(summaries: list[ExperimentSummary], output_path: Path) -> None:
    """Write experiment summaries to a CSV file.

    Args:
        summaries: List of experiment summaries to export.
        output_path: Path for the output CSV file.
    """
    if not summaries:
        output_path.write_text("", encoding="utf-8")
        return

    df = pd.DataFrame([asdict(s) for s in summaries])
    df.to_csv(output_path, index=False)


def export_summary_json(
    summaries: list[ExperimentSummary],
    output_path: Path,
) -> None:
    """Write top-level experiment statistics as JSON.

    Produces a JSON object with total experiment count, per-hypothesis
    breakdowns, per-provider breakdowns, and overall detection rate.

    Args:
        summaries: List of experiment summaries to export.
        output_path: Path for the output JSON file.
    """
    if not summaries:
        output_path.write_text("{}", encoding="utf-8")
        return

    total = len(summaries)
    avg_detection_rate = sum(s.detection_rate for s in summaries) / total
    avg_delta = sum(s.observability_delta for s in summaries) / total

    by_hypothesis: dict[str, int] = {}
    by_provider: dict[str, int] = {}
    by_compliance: dict[str, int] = {}

    for s in summaries:
        by_hypothesis[s.hypothesis] = by_hypothesis.get(s.hypothesis, 0) + 1
        by_provider[s.provider] = by_provider.get(s.provider, 0) + 1
        by_compliance[s.compliance] = by_compliance.get(s.compliance, 0) + 1

    output = {
        "total_experiments": total,
        "average_detection_rate": round(avg_detection_rate, 4),
        "average_observability_delta": round(avg_delta, 2),
        "by_hypothesis": by_hypothesis,
        "by_provider": by_provider,
        "by_compliance": by_compliance,
        "summaries": [asdict(s) for s in summaries],
    }

    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
