"""Tests for src.gui.services.analysis_service."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.analysis.aggregate import ExperimentSummary


def _make_summary(**kwargs: object) -> ExperimentSummary:
    defaults = {
        "experiment_id": "exp1",
        "run_number": 1,
        "hypothesis": "H3",
        "variant": "direct",
        "provider": "ollama",
        "model": "llama3.2",
        "compliance": "full_execution",
        "detection_rate": 0.5,
        "observability_delta": 3,
    }
    defaults.update(kwargs)
    return ExperimentSummary(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# get_dashboard_data
# ---------------------------------------------------------------------------


async def test_get_dashboard_data_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.gui.services.analysis_service import get_dashboard_data

    monkeypatch.setattr("src.gui.services.analysis_service.RESULTS_DIR", tmp_path / "nonexistent")
    data = await get_dashboard_data()
    assert data["total"] == 0
    assert data["compliance_counts"] == {}


async def test_get_dashboard_data_with_summaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.gui.services.analysis_service import get_dashboard_data

    rd = tmp_path / "results"
    rd.mkdir()
    monkeypatch.setattr("src.gui.services.analysis_service.RESULTS_DIR", rd)

    summaries = [
        _make_summary(
            experiment_id="exp1",
            compliance="full_execution",
            detection_rate=0.0,
            observability_delta=5,
        ),
        _make_summary(
            experiment_id="exp2",
            compliance="silent_refusal",
            detection_rate=1.0,
            observability_delta=0,
        ),
    ]

    # Create experiment dirs so mtime sorting works.
    (rd / "exp1").mkdir()
    (rd / "exp2").mkdir()

    with patch(
        "src.analysis.aggregate.aggregate_results",
        new_callable=AsyncMock,
        return_value=summaries,
    ):
        data = await get_dashboard_data()

    assert data["total"] == 2  # 2 experiments (grouped)
    assert data["total_runs"] == 2  # 2 individual runs
    assert data["compliance_counts"]["full_execution"] == 1
    assert data["compliance_counts"]["silent_refusal"] == 1
    assert data["avg_detection_rate"] == 0.5
    assert data["avg_delta"] == 2.5


# ---------------------------------------------------------------------------
# get_run_events
# ---------------------------------------------------------------------------


async def test_get_run_events_no_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.gui.services.analysis_service import get_run_events

    monkeypatch.setattr("src.gui.services.analysis_service.RESULTS_DIR", tmp_path / "nonexistent")
    with patch("src.gui.services.db_service._find_db", return_value=None):
        events = await get_run_events("nope", 1)
    assert events["schema_mutations"] == []
    assert events["injection_patterns"] == []


async def test_get_run_events_with_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.analysis.events import (
        AnomalousCallEvent,
        InjectionEvent,
        ParamEvent,
        SchemaEvent,
    )
    from src.gui.services.analysis_service import get_run_events

    db_path = tmp_path / "experiment.db"
    db_path.touch()

    with (
        patch("src.gui.services.db_service._find_db", return_value=db_path),
        patch(
            "src.analysis.events.detect_schema_mutations",
            new_callable=AsyncMock,
            return_value=[
                SchemaEvent(
                    session_id="s1",
                    tool_name="echo",
                    old_hash="aaaaaaaaaaaa0000",
                    new_hash="bbbbbbbbbbbb1111",
                    old_description="old",
                    new_description="new",
                    timestamp="2025-01-01",
                )
            ],
        ),
        patch(
            "src.analysis.events.detect_undeclared_params",
            new_callable=AsyncMock,
            return_value=[
                ParamEvent(
                    session_id="s1",
                    tool_name="weather",
                    declared_params=["city"],
                    actual_params=["city", "exfil"],
                    undeclared_params=["exfil"],
                    timestamp="2025-01-01",
                )
            ],
        ),
        patch(
            "src.analysis.events.detect_injection_patterns",
            new_callable=AsyncMock,
            return_value=[
                InjectionEvent(
                    session_id="s1",
                    response_text="IGNORE PREVIOUS INSTRUCTIONS",
                    matched_patterns=["IGNORE PREVIOUS"],
                    timestamp="2025-01-01",
                )
            ],
        ),
        patch(
            "src.analysis.events.detect_anomalous_calls",
            new_callable=AsyncMock,
            return_value=[
                AnomalousCallEvent(
                    session_id="s1",
                    tool_name="send_email",
                    arguments={"to": "attacker"},
                    timestamp="2025-01-01",
                )
            ],
        ),
    ):
        events = await get_run_events("exp001", 1)

    assert len(events["schema_mutations"]) == 1
    assert len(events["undeclared_params"]) == 1
    assert len(events["injection_patterns"]) == 1
    assert len(events["anomalous_calls"]) == 1


# ---------------------------------------------------------------------------
# get_compliance_heatmap
# ---------------------------------------------------------------------------


async def test_get_compliance_heatmap_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.gui.services.analysis_service import get_compliance_heatmap

    monkeypatch.setattr("src.gui.services.analysis_service.RESULTS_DIR", tmp_path / "nonexistent")
    result = await get_compliance_heatmap()
    assert result == {"models": [], "variants": [], "cells": {}}


async def test_get_compliance_heatmap_with_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.gui.services.analysis_service import get_compliance_heatmap

    rd = tmp_path / "results"
    rd.mkdir()
    monkeypatch.setattr("src.gui.services.analysis_service.RESULTS_DIR", rd)

    summaries = [
        _make_summary(model="llama3.2", variant="direct", compliance="full_execution"),
        _make_summary(model="gpt-4o", variant="direct", compliance="silent_refusal"),
    ]
    with patch(
        "src.analysis.aggregate.aggregate_results",
        new_callable=AsyncMock,
        return_value=summaries,
    ):
        result = await get_compliance_heatmap()

    assert "llama3.2" in result["models"]
    assert "gpt-4o" in result["models"]
    assert result["cells"]["llama3.2"]["direct"] == "full_execution"


# ---------------------------------------------------------------------------
# get_detection_rate_chart
# ---------------------------------------------------------------------------


async def test_get_detection_rate_chart_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.gui.services.analysis_service import get_detection_rate_chart

    monkeypatch.setattr("src.gui.services.analysis_service.RESULTS_DIR", tmp_path / "nonexistent")
    result = await get_detection_rate_chart()
    assert result["data"]["labels"] == []


async def test_get_detection_rate_chart_with_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.gui.services.analysis_service import get_detection_rate_chart

    rd = tmp_path / "results"
    rd.mkdir()
    monkeypatch.setattr("src.gui.services.analysis_service.RESULTS_DIR", rd)

    summaries = [_make_summary(provider="ollama", detection_rate=0.8)]
    with patch(
        "src.analysis.aggregate.aggregate_results",
        new_callable=AsyncMock,
        return_value=summaries,
    ):
        result = await get_detection_rate_chart()

    assert result["type"] == "bar"
    assert result["data"]["labels"] == ["ollama"]
    assert result["data"]["datasets"][0]["data"] == [80.0]


# ---------------------------------------------------------------------------
# get_delta_chart
# ---------------------------------------------------------------------------


async def test_get_delta_chart_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.gui.services.analysis_service import get_delta_chart

    monkeypatch.setattr("src.gui.services.analysis_service.RESULTS_DIR", tmp_path / "nonexistent")
    result = await get_delta_chart()
    assert result["data"]["labels"] == []


async def test_get_delta_chart_with_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.gui.services.analysis_service import get_delta_chart

    rd = tmp_path / "results"
    rd.mkdir()
    monkeypatch.setattr("src.gui.services.analysis_service.RESULTS_DIR", rd)

    summaries = [_make_summary(provider="ollama", detection_rate=0.5, observability_delta=4)]
    with patch(
        "src.analysis.aggregate.aggregate_results",
        new_callable=AsyncMock,
        return_value=summaries,
    ):
        result = await get_delta_chart()

    assert result["type"] == "bar"
    assert len(result["data"]["datasets"]) == 2


async def test_get_delta_chart_rate_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.gui.services.analysis_service import get_delta_chart

    rd = tmp_path / "results"
    rd.mkdir()
    monkeypatch.setattr("src.gui.services.analysis_service.RESULTS_DIR", rd)

    # avg_rate == 1.0 triggers the special branch.
    summaries = [_make_summary(provider="p", detection_rate=1.0, observability_delta=3)]
    with patch(
        "src.analysis.aggregate.aggregate_results",
        new_callable=AsyncMock,
        return_value=summaries,
    ):
        result = await get_delta_chart()

    assert result["data"]["datasets"][0]["data"][0] == 3.0


# ---------------------------------------------------------------------------
# _empty_chart
# ---------------------------------------------------------------------------


def test_empty_chart() -> None:
    from src.gui.services.analysis_service import _empty_chart

    chart = _empty_chart("Test Title")
    assert chart["type"] == "bar"
    assert "No data yet" in chart["options"]["plugins"]["title"]["text"]
