"""Tests for src/analysis/aggregate.py — result aggregation and export."""

from __future__ import annotations

import csv
import json
from typing import TYPE_CHECKING

import aiosqlite

from src.analysis.aggregate import (
    ExperimentSummary,
    aggregate_results,
    export_csv,
    export_summary_json,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Database setup helper — minimal schema + data for aggregate_results
# ---------------------------------------------------------------------------

_CREATE_TABLES_SQL = """\
CREATE TABLE IF NOT EXISTS proxy_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    direction TEXT NOT NULL,
    message_type TEXT,
    method TEXT,
    message_json TEXT,
    content_hash TEXT,
    parse_error INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS proxy_tool_schemas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    tool_name TEXT,
    description TEXT,
    description_hash TEXT,
    input_schema_json TEXT,
    input_schema_hash TEXT,
    list_call_sequence_number INTEGER
);

CREATE TABLE IF NOT EXISTS adapter_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    translated_tools_json TEXT,
    request_json TEXT
);

CREATE TABLE IF NOT EXISTS adapter_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    response_json TEXT,
    tool_calls_json TEXT,
    compliance_classification TEXT,
    manual_override TEXT,
    iteration_number INTEGER
);
"""


async def _create_experiment_db(db_path: Path, provider: str, model: str) -> None:
    """Create a minimal experiment.db with adapter data for aggregation."""
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_CREATE_TABLES_SQL)

        # adapter_requests row so _extract_metadata can find provider/model.
        await db.execute(
            """INSERT INTO adapter_requests
               (session_id, timestamp, provider, model,
                translated_tools_json, request_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("sess1", "2026-01-01T00:00:00", provider, model, "[]", "{}"),
        )

        # adapter_responses row so classify_compliance has data.
        await db.execute(
            """INSERT INTO adapter_responses
               (session_id, timestamp, provider, model,
                response_json, tool_calls_json, compliance_classification)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "sess1",
                "2026-01-01T00:01:00",
                provider,
                model,
                json.dumps({"content": [{"text": "The weather is sunny."}]}),
                None,
                None,
            ),
        )

        await db.commit()


# ---------------------------------------------------------------------------
# Tests — export_csv
# ---------------------------------------------------------------------------


def test_export_csv(tmp_path: Path) -> None:
    """export_csv writes summaries to a readable CSV file."""
    summaries = [
        ExperimentSummary(
            experiment_id="abc123",
            run_number=1,
            hypothesis="H3",
            variant="direct",
            provider="ollama",
            model="llama3.2",
            compliance="silent_refusal",
            detection_rate=0.0,
            observability_delta=3,
        ),
        ExperimentSummary(
            experiment_id="def456",
            run_number=1,
            hypothesis="H2",
            variant="shadow",
            provider="anthropic",
            model="claude-opus-4-20250514",
            compliance="full_execution",
            detection_rate=0.25,
            observability_delta=2,
        ),
    ]
    csv_path = tmp_path / "results.csv"
    export_csv(summaries, csv_path)

    assert csv_path.exists()
    text = csv_path.read_text(encoding="utf-8")
    assert "abc123" in text
    assert "def456" in text

    # Parse as CSV and verify columns.
    reader = csv.DictReader(text.splitlines())
    rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["hypothesis"] == "H3"
    assert rows[1]["provider"] == "anthropic"


def test_export_csv_empty(tmp_path: Path) -> None:
    """export_csv with empty list writes an empty file."""
    csv_path = tmp_path / "empty.csv"
    export_csv([], csv_path)
    assert csv_path.exists()
    assert csv_path.read_text(encoding="utf-8") == ""


# ---------------------------------------------------------------------------
# Tests — export_summary_json
# ---------------------------------------------------------------------------


def test_export_summary_json(tmp_path: Path) -> None:
    """export_summary_json produces valid JSON with expected structure."""
    summaries = [
        ExperimentSummary(
            experiment_id="aaa",
            run_number=1,
            hypothesis="H3",
            variant="direct",
            provider="ollama",
            model="llama3.2",
            compliance="silent_refusal",
            detection_rate=0.0,
            observability_delta=5,
        ),
        ExperimentSummary(
            experiment_id="bbb",
            run_number=1,
            hypothesis="H3",
            variant="encoded",
            provider="ollama",
            model="llama3.2",
            compliance="full_execution",
            detection_rate=0.5,
            observability_delta=1,
        ),
    ]
    json_path = tmp_path / "summary.json"
    export_summary_json(summaries, json_path)

    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))

    assert data["total_experiments"] == 2
    assert "average_detection_rate" in data
    assert "average_observability_delta" in data
    assert "by_hypothesis" in data
    assert "by_provider" in data
    assert "by_compliance" in data
    assert "summaries" in data
    assert len(data["summaries"]) == 2
    assert data["by_hypothesis"]["H3"] == 2


def test_export_summary_json_empty(tmp_path: Path) -> None:
    """export_summary_json with empty list writes '{}'."""
    json_path = tmp_path / "empty.json"
    export_summary_json([], json_path)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data == {}


# ---------------------------------------------------------------------------
# Tests — aggregate_results
# ---------------------------------------------------------------------------


async def test_aggregate_empty_dir(tmp_path: Path) -> None:
    """aggregate_results on a directory with no experiment.db returns []."""
    result = await aggregate_results(tmp_path)
    assert result == []


async def test_aggregate_single_db(tmp_path: Path) -> None:
    """aggregate_results finds and summarises a single experiment.db."""
    run_dir = tmp_path / "exp_001" / "run_1"
    run_dir.mkdir(parents=True)
    db_path = run_dir / "experiment.db"
    await _create_experiment_db(db_path, provider="ollama", model="llama3.2")

    # Write config.json alongside the DB (matches runner behavior).
    config = {
        "experiment_id": "exp_001",
        "hypothesis": "H3",
        "variant": "direct",
        "provider": "ollama",
        "model": "llama3.2",
        "run_number": 1,
    }
    (run_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")

    summaries = await aggregate_results(tmp_path)

    assert len(summaries) == 1
    s = summaries[0]
    assert isinstance(s, ExperimentSummary)
    assert s.provider == "ollama"
    assert s.model == "llama3.2"
    assert s.experiment_id == "exp_001"
    assert s.run_number == 1
    assert s.hypothesis == "H3"
    assert s.variant == "direct"


async def test_aggregate_multiple_dbs(tmp_path: Path) -> None:
    """aggregate_results handles multiple experiment.db files."""
    for i, (provider, model) in enumerate(
        [("ollama", "llama3.2"), ("anthropic", "claude-opus-4-20250514")],
    ):
        run_dir = tmp_path / f"exp_{i}" / "run_1"
        run_dir.mkdir(parents=True)
        db_path = run_dir / "experiment.db"
        await _create_experiment_db(db_path, provider=provider, model=model)

    summaries = await aggregate_results(tmp_path)

    assert len(summaries) == 2
    providers = {s.provider for s in summaries}
    assert "ollama" in providers
    assert "anthropic" in providers
