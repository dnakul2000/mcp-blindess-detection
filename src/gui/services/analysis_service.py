"""Analysis service wrapping src/analysis modules."""

from __future__ import annotations

from typing import Any

from src.gui.config import RESULTS_DIR


async def get_dashboard_data() -> dict[str, Any]:
    """Get aggregate data for the dashboard.

    Groups per-run summaries by experiment_id so the dashboard shows one
    row per experiment with worst-case compliance and average metrics.
    """
    from src.analysis.aggregate import ExperimentSummary, aggregate_results

    if not RESULTS_DIR.exists():
        return {
            "total": 0,
            "total_runs": 0,
            "compliance_counts": {},
            "avg_detection_rate": 0.0,
            "avg_delta": 0,
            "recent": [],
        }

    summaries = await aggregate_results(RESULTS_DIR)

    # Per-run compliance counts (for the donut chart — each run is a data point).
    compliance_counts: dict[str, int] = {}
    for s in summaries:
        compliance_counts[s.compliance] = compliance_counts.get(s.compliance, 0) + 1

    avg_detection = sum(s.detection_rate for s in summaries) / len(summaries) if summaries else 0.0
    avg_delta = sum(s.observability_delta for s in summaries) / len(summaries) if summaries else 0

    # Group runs by experiment_id for the "Recent Experiments" table.
    grouped: dict[str, list[ExperimentSummary]] = {}
    for s in summaries:
        grouped.setdefault(s.experiment_id, []).append(s)

    level_priority = {
        "full_execution": 0,
        "partial_compliance": 1,
        "instruction_leakage": 2,
        "silent_refusal": 3,
        "no_data": 4,
    }

    recent: list[dict[str, Any]] = []
    for exp_id, runs in grouped.items():
        first = runs[0]
        worst_compliance = min(runs, key=lambda r: level_priority.get(r.compliance, 99))
        avg_det = sum(r.detection_rate for r in runs) / len(runs)
        avg_obs = sum(r.observability_delta for r in runs) / len(runs)
        recent.append(
            {
                "experiment_id": exp_id,
                "hypothesis": first.hypothesis,
                "variant": first.variant,
                "provider": first.provider,
                "model": first.model,
                "compliance": worst_compliance.compliance,
                "detection_rate": avg_det,
                "observability_delta": avg_obs,
                "runs": len(runs),
            }
        )

    # Sort by experiment directory mtime (newest first).
    recent.sort(
        key=lambda e: (
            (RESULTS_DIR / e["experiment_id"]).stat().st_mtime
            if (RESULTS_DIR / e["experiment_id"]).exists()
            else 0
        ),
        reverse=True,
    )

    return {
        "total": len(grouped),
        "total_runs": len(summaries),
        "compliance_counts": compliance_counts,
        "avg_detection_rate": round(avg_detection, 4),
        "avg_delta": round(avg_delta, 2),
        "recent": recent[:20],
    }


async def get_run_events(exp_id: str, run_number: int) -> dict[str, Any]:
    """Get detected security events for a specific run."""
    from src.gui.services.db_service import _find_db

    db_path = _find_db(exp_id, run_number)
    if not db_path:
        return {
            "schema_mutations": [],
            "undeclared_params": [],
            "injection_patterns": [],
            "anomalous_calls": [],
        }

    from src.analysis.events import (
        detect_anomalous_calls,
        detect_injection_patterns,
        detect_schema_mutations,
        detect_undeclared_params,
    )

    schema_mutations = await detect_schema_mutations(db_path)
    undeclared_params = await detect_undeclared_params(db_path)
    injection_patterns = await detect_injection_patterns(db_path)
    anomalous_calls = await detect_anomalous_calls(db_path, expected_tools=set())

    return {
        "schema_mutations": [
            {
                "tool_name": e.tool_name,
                "old_hash": e.old_hash[:12],
                "new_hash": e.new_hash[:12],
                "old_description": e.old_description,
                "new_description": e.new_description,
                "timestamp": e.timestamp,
                "visibility": e.visibility.value,
            }
            for e in schema_mutations
        ],
        "undeclared_params": [
            {
                "tool_name": e.tool_name,
                "declared": e.declared_params,
                "actual": e.actual_params,
                "undeclared": e.undeclared_params,
                "timestamp": e.timestamp,
                "visibility": e.visibility.value,
            }
            for e in undeclared_params
        ],
        "injection_patterns": [
            {
                "response_text": e.response_text[:200],
                "matched_patterns": e.matched_patterns,
                "timestamp": e.timestamp,
                "visibility": e.visibility.value,
            }
            for e in injection_patterns
        ],
        "anomalous_calls": [
            {
                "tool_name": e.tool_name,
                "arguments": e.arguments,
                "timestamp": e.timestamp,
                "visibility": e.visibility.value,
            }
            for e in anomalous_calls
        ],
    }


async def get_compliance_heatmap() -> dict[str, Any]:
    """Build heatmap data: model x variant compliance matrix."""
    from src.analysis.aggregate import aggregate_results

    if not RESULTS_DIR.exists():
        return {"models": [], "variants": [], "cells": {}}

    summaries = await aggregate_results(RESULTS_DIR)

    models = sorted({s.model for s in summaries})
    variants = sorted({s.variant for s in summaries})

    cells: dict[str, dict[str, str]] = {}
    for model in models:
        cells[model] = {}
        for variant in variants:
            matching = [s for s in summaries if s.model == model and s.variant == variant]
            if matching:
                # Use most severe compliance
                priority = {
                    "full_execution": 0,
                    "partial_compliance": 1,
                    "instruction_leakage": 2,
                    "silent_refusal": 3,
                }
                worst = min(matching, key=lambda s: priority.get(s.compliance, 99))
                cells[model][variant] = worst.compliance
            else:
                cells[model][variant] = "no_data"

    return {"models": models, "variants": variants, "cells": cells}


async def get_detection_rate_chart() -> dict[str, Any]:
    """Build Chart.js config for detection rate by provider."""
    from src.analysis.aggregate import aggregate_results

    if not RESULTS_DIR.exists():
        return _empty_chart("Detection Rate by Provider")

    summaries = await aggregate_results(RESULTS_DIR)
    providers = sorted({s.provider for s in summaries})

    rates = []
    for p in providers:
        matching = [s for s in summaries if s.provider == p]
        avg = sum(s.detection_rate for s in matching) / len(matching) if matching else 0
        rates.append(round(avg * 100, 1))

    return {
        "type": "bar",
        "data": {
            "labels": providers,
            "datasets": [
                {
                    "label": "Detection Rate (%)",
                    "data": rates,
                    "backgroundColor": "#2563eb",
                    "borderRadius": 4,
                    "maxBarThickness": 60,
                }
            ],
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "scales": {
                "y": {"beginAtZero": True, "max": 100, "title": {"display": True, "text": "%"}},
            },
            "plugins": {"legend": {"display": False}},
        },
    }


async def get_delta_chart() -> dict[str, Any]:
    """Build Chart.js config for observability delta by provider."""
    from src.analysis.aggregate import aggregate_results

    if not RESULTS_DIR.exists():
        return _empty_chart("Observability Delta")

    summaries = await aggregate_results(RESULTS_DIR)
    providers = sorted({s.provider for s in summaries})

    proxy_counts = []
    client_counts = []
    for p in providers:
        matching = [s for s in summaries if s.provider == p]
        avg_delta = sum(s.observability_delta for s in matching) / len(matching) if matching else 0
        avg_rate = sum(s.detection_rate for s in matching) / len(matching) if matching else 0
        # Approximate proxy and client event counts
        proxy_est = avg_delta / (1 - avg_rate) if avg_rate < 1 else avg_delta
        client_est = proxy_est * avg_rate
        proxy_counts.append(round(proxy_est, 1))
        client_counts.append(round(client_est, 1))

    return {
        "type": "bar",
        "data": {
            "labels": providers,
            "datasets": [
                {
                    "label": "Proxy Events (ground truth)",
                    "data": proxy_counts,
                    "backgroundColor": "#7c3aed",
                    "borderRadius": 4,
                    "maxBarThickness": 40,
                },
                {
                    "label": "Client Events (detected)",
                    "data": client_counts,
                    "backgroundColor": "#d4d4d8",
                    "borderRadius": 4,
                    "maxBarThickness": 40,
                },
            ],
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "scales": {
                "y": {"beginAtZero": True, "title": {"display": True, "text": "Events"}},
            },
            "plugins": {"legend": {"position": "bottom"}},
        },
    }


def _empty_chart(title: str) -> dict[str, Any]:
    """Return an empty Chart.js configuration."""
    return {
        "type": "bar",
        "data": {"labels": [], "datasets": []},
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "plugins": {
                "title": {"display": True, "text": f"No data yet — {title}"},
            },
        },
    }
