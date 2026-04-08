"""Observability delta computation for MCP detection blindness experiments.

Compares the number of security-relevant events captured by the transparent
proxy (ground truth) against those visible to the client/operator, producing
a detection rate metric.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from src.analysis.events import (
    SecurityEvent,
    VisibilityTier,
    classify_visibility,
    detect_anomalous_calls,
    detect_injection_patterns,
    detect_schema_mutations,
    detect_undeclared_params,
)

# Keywords used to match client log entries against known event types.
_CLIENT_LOG_KEYWORDS: dict[str, list[str]] = {
    "schema_mutation": ["schema", "mutation", "description changed", "hash"],
    "undeclared_param": ["SHADOW_PARAM", "undeclared", "extra param"],
    "injection_pattern": [
        "injection",
        "IMPORTANT",
        "SYSTEM NOTE",
        "you must",
        "read_file",
    ],
    "anomalous_call": ["unexpected tool", "anomalous", "unknown tool"],
}


@dataclass(frozen=True)
class DeltaResult:
    """Result of comparing proxy-observed events to client-visible events."""

    total_proxy_events: int
    total_client_events: int
    observability_delta: int
    detection_rate: float
    events_by_type: dict[str, int]
    events_by_visibility: dict[str, int]


def _count_client_events(client_log: list[str]) -> int:
    """Count security-relevant events represented in client log lines.

    Uses simple keyword matching: each log line that matches at least one
    keyword from any event category counts as one detected event.

    Args:
        client_log: List of client log line strings.

    Returns:
        Number of log lines that match security event keywords.
    """
    count = 0
    for line in client_log:
        line_lower = line.lower()
        for keywords in _CLIENT_LOG_KEYWORDS.values():
            if any(kw.lower() in line_lower for kw in keywords):
                count += 1
                break  # Count each line at most once.
    return count


async def compute_delta(
    db_path: Path,
    client_log: list[str] | None = None,
) -> DeltaResult:
    """Compute the observability delta between proxy and client.

    Counts all security-relevant events detected by the four event detectors
    (proxy ground truth). If ``client_log`` is provided, counts how many
    events are represented there via keyword matching. The delta is the
    difference between proxy events and client events.

    Args:
        db_path: Path to the experiment SQLite database.
        client_log: Optional list of client log lines. If None, client
            event count defaults to zero (worst-case assumption).

    Returns:
        Delta result with counts, detection rate, and per-type breakdown.
    """
    schema_events = await detect_schema_mutations(db_path)
    param_events = await detect_undeclared_params(db_path)
    injection_events = await detect_injection_patterns(db_path)
    # Use an empty expected set so all calls are counted; callers who need
    # filtered anomalous calls should invoke detect_anomalous_calls directly.
    anomalous_events = await detect_anomalous_calls(db_path, expected_tools=set())

    events_by_type: dict[str, int] = {
        "schema_mutation": len(schema_events),
        "undeclared_param": len(param_events),
        "injection_pattern": len(injection_events),
        "anomalous_call": len(anomalous_events),
    }

    # Classify visibility tiers for all events.
    all_events: list[SecurityEvent] = [
        *schema_events,
        *param_events,
        *injection_events,
        *anomalous_events,
    ]
    classified = classify_visibility(all_events, client_log or [])
    visibility_counts: dict[str, int] = {tier.value: 0 for tier in VisibilityTier}
    for event in classified:
        visibility_counts[event.visibility.value] += 1

    total_proxy = sum(events_by_type.values())
    total_client = _count_client_events(client_log) if client_log else 0
    delta = total_proxy - total_client
    detection_rate = total_client / total_proxy if total_proxy > 0 else 0.0

    return DeltaResult(
        total_proxy_events=total_proxy,
        total_client_events=total_client,
        observability_delta=delta,
        detection_rate=detection_rate,
        events_by_type=events_by_type,
        events_by_visibility=visibility_counts,
    )
