"""Tests for src.gui.services.db_service."""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite
import pytest

_CREATE_TABLES = """
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
    session_id TEXT NOT NULL DEFAULT '',
    tool_name TEXT NOT NULL,
    description TEXT,
    description_hash TEXT,
    input_schema_json TEXT,
    input_schema_hash TEXT,
    list_call_sequence_number INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS adapter_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL DEFAULT '',
    provider TEXT,
    model TEXT,
    translated_tools_json TEXT,
    request_json TEXT
);
CREATE TABLE IF NOT EXISTS adapter_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL DEFAULT '',
    provider TEXT,
    model TEXT,
    response_json TEXT,
    tool_calls_json TEXT,
    classification TEXT,
    iteration_number INTEGER DEFAULT 1,
    manual_override TEXT
);
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
INSERT INTO schema_version VALUES (2);
"""


@pytest.fixture
def results_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a results directory and patch the module constant."""
    rd = tmp_path / "results"
    rd.mkdir()
    monkeypatch.setattr("src.gui.services.db_service.RESULTS_DIR", rd)
    return rd


async def _create_experiment(
    results_dir: Path,
    exp_id: str = "exp001",
    run_number: int = 1,
    *,
    populate: bool = True,
) -> Path:
    """Helper: create experiment directory with optional DB + config."""
    run_dir = results_dir / exp_id / f"run_{run_number}"
    run_dir.mkdir(parents=True)

    config = {
        "experiment_id": exp_id,
        "hypothesis": "H3",
        "variant": "direct",
        "provider": "ollama",
        "model": "llama3.2",
    }
    (run_dir / "config.json").write_text(json.dumps(config))

    db_path = run_dir / "experiment.db"
    if populate:
        async with aiosqlite.connect(str(db_path)) as db:
            await db.executescript(_CREATE_TABLES)
            await db.execute(
                "INSERT INTO proxy_messages (session_id, timestamp, direction, message_type, method, message_json, content_hash) VALUES (?,?,?,?,?,?,?)",
                (
                    "s1",
                    "2025-01-01T00:00:00",
                    "client_to_server",
                    "request",
                    "tools/list",
                    '{"jsonrpc":"2.0","method":"tools/list","id":1}',
                    "abc123",
                ),
            )
            await db.execute(
                "INSERT INTO proxy_tool_schemas (session_id, tool_name, description, description_hash, input_schema_json, input_schema_hash, list_call_sequence_number) VALUES (?,?,?,?,?,?,?)",
                ("s1", "echo", "Echo tool", "h1", '{"properties":{}}', "h2", 1),
            )
            await db.execute(
                "INSERT INTO adapter_requests (session_id, timestamp, provider, model, translated_tools_json, request_json) VALUES (?,?,?,?,?,?)",
                ("s1", "2025-01-01T00:00:01", "ollama", "llama3.2", "[]", '{"model":"llama3.2"}'),
            )
            await db.execute(
                "INSERT INTO adapter_responses (session_id, timestamp, provider, model, response_json, tool_calls_json, iteration_number) VALUES (?,?,?,?,?,?,?)",
                ("s1", "2025-01-01T00:00:02", "ollama", "llama3.2", '{"content":"hello"}', None, 1),
            )
            await db.commit()

    return db_path


# ---------------------------------------------------------------------------
# _find_db
# ---------------------------------------------------------------------------


async def test_find_db_direct_path(results_dir: Path) -> None:
    from src.gui.services.db_service import _find_db

    await _create_experiment(results_dir)
    found = _find_db("exp001", 1)
    assert found is not None
    assert found.name == "experiment.db"


async def test_find_db_not_found(results_dir: Path) -> None:
    from src.gui.services.db_service import _find_db

    assert _find_db("nonexistent", 1) is None


async def test_find_db_fallback(results_dir: Path) -> None:
    from src.gui.services.db_service import _find_db

    # Create DB in an unexpected location but still under results with exp_id in path.
    nested = results_dir / "exp002" / "nested"
    nested.mkdir(parents=True)
    (nested / "experiment.db").touch()
    found = _find_db("exp002", 99)
    assert found is not None


# ---------------------------------------------------------------------------
# _find_config
# ---------------------------------------------------------------------------


async def test_find_config_exists(results_dir: Path) -> None:
    from src.gui.services.db_service import _find_config

    await _create_experiment(results_dir)
    config = _find_config("exp001", 1)
    assert config["hypothesis"] == "H3"


def test_find_config_missing(results_dir: Path) -> None:
    from src.gui.services.db_service import _find_config

    assert _find_config("nope", 1) == {}


# ---------------------------------------------------------------------------
# list_experiments
# ---------------------------------------------------------------------------


async def test_list_experiments_empty(results_dir: Path) -> None:
    from src.gui.services.db_service import list_experiments

    # Empty results dir.
    result = await list_experiments()
    assert result["total"] == 0


async def test_list_experiments_no_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.gui.services.db_service import list_experiments

    monkeypatch.setattr("src.gui.services.db_service.RESULTS_DIR", tmp_path / "nonexistent")
    result = await list_experiments()
    assert result == {"items": [], "total": 0, "pages": 0}


async def test_list_experiments_with_data(results_dir: Path) -> None:
    from src.gui.services.db_service import list_experiments

    await _create_experiment(results_dir, "exp001")
    result = await list_experiments()
    assert result["total"] == 1
    assert result["items"][0]["experiment_id"] == "exp001"
    assert result["items"][0]["hypothesis"] == "H3"


async def test_list_experiments_compliance_from_agent_result(results_dir: Path) -> None:
    from src.gui.services.db_service import list_experiments

    await _create_experiment(results_dir, "exp002")
    agent_result = {"compliance": "full_execution", "final_response": "done"}
    (results_dir / "exp002" / "run_1" / "agent_result.json").write_text(json.dumps(agent_result))
    result = await list_experiments()
    assert result["items"][0]["compliance"] == "full_execution"


async def test_list_experiments_corrupt_agent_result(results_dir: Path) -> None:
    from src.gui.services.db_service import list_experiments

    await _create_experiment(results_dir, "exp003")
    (results_dir / "exp003" / "run_1" / "agent_result.json").write_text("not-json")
    result = await list_experiments()
    assert result["items"][0]["compliance"] == "unknown"


async def test_list_experiments_no_run_dirs(results_dir: Path) -> None:
    from src.gui.services.db_service import list_experiments

    (results_dir / "empty_exp").mkdir()
    result = await list_experiments()
    assert result["total"] == 0


# ---------------------------------------------------------------------------
# get_run_metadata
# ---------------------------------------------------------------------------


async def test_get_run_metadata(results_dir: Path) -> None:
    from src.gui.services.db_service import get_run_metadata

    await _create_experiment(results_dir)
    meta = await get_run_metadata("exp001", 1)
    assert meta["db_exists"] is True
    assert meta["message_count"] == 1
    assert meta["hypothesis"] == "H3"


async def test_get_run_metadata_no_db(results_dir: Path) -> None:
    from src.gui.services.db_service import get_run_metadata

    meta = await get_run_metadata("nonexistent", 1)
    assert meta["db_exists"] is False
    assert "message_count" not in meta


async def test_get_run_metadata_with_error(results_dir: Path) -> None:
    from src.gui.services.db_service import get_run_metadata

    await _create_experiment(results_dir)
    (results_dir / "exp001" / "run_1" / "error.txt").write_text("something broke")
    meta = await get_run_metadata("exp001", 1)
    assert meta["error"] == "something broke"


async def test_get_run_metadata_with_result(results_dir: Path) -> None:
    from src.gui.services.db_service import get_run_metadata

    await _create_experiment(results_dir)
    (results_dir / "exp001" / "run_1" / "agent_result.json").write_text(
        json.dumps({"final_response": "done"})
    )
    meta = await get_run_metadata("exp001", 1)
    assert meta["result"]["final_response"] == "done"


# ---------------------------------------------------------------------------
# get_messages
# ---------------------------------------------------------------------------


async def test_get_messages_no_db(results_dir: Path) -> None:
    from src.gui.services.db_service import get_messages

    result = await get_messages("nonexistent", 1)
    assert result == {"items": [], "total": 0, "pages": 0}


async def test_get_messages_with_data(results_dir: Path) -> None:
    from src.gui.services.db_service import get_messages

    await _create_experiment(results_dir)
    result = await get_messages("exp001", 1)
    assert result["total"] == 1
    assert result["items"][0]["direction"] == "client_to_server"


async def test_get_messages_with_filters(results_dir: Path) -> None:
    from src.gui.services.db_service import get_messages

    await _create_experiment(results_dir)
    result = await get_messages("exp001", 1, direction="client_to_server", method="tools/list")
    assert result["total"] == 1

    result = await get_messages("exp001", 1, direction="server_to_client")
    assert result["total"] == 0


# ---------------------------------------------------------------------------
# get_message_detail
# ---------------------------------------------------------------------------


async def test_get_message_detail_found(results_dir: Path) -> None:
    from src.gui.services.db_service import get_message_detail

    await _create_experiment(results_dir)
    msg = await get_message_detail("exp001", 1, 1)
    assert msg["method"] == "tools/list"
    assert "message_pretty" in msg


async def test_get_message_detail_not_found(results_dir: Path) -> None:
    from src.gui.services.db_service import get_message_detail

    await _create_experiment(results_dir)
    msg = await get_message_detail("exp001", 1, 999)
    assert msg == {}


async def test_get_message_detail_no_db(results_dir: Path) -> None:
    from src.gui.services.db_service import get_message_detail

    msg = await get_message_detail("nope", 1, 1)
    assert msg == {}


async def test_get_message_detail_invalid_json(results_dir: Path) -> None:
    from src.gui.services.db_service import get_message_detail

    # Create experiment with bad JSON in message_json.
    run_dir = results_dir / "expbad" / "run_1"
    run_dir.mkdir(parents=True)
    db_path = run_dir / "experiment.db"
    async with aiosqlite.connect(str(db_path)) as db:
        await db.executescript(_CREATE_TABLES)
        await db.execute(
            "INSERT INTO proxy_messages (session_id, timestamp, direction, message_type, method, message_json, content_hash) VALUES (?,?,?,?,?,?,?)",
            (
                "s1",
                "2025-01-01",
                "client_to_server",
                "request",
                "tools/list",
                "not-valid-json",
                "h1",
            ),
        )
        await db.commit()

    msg = await get_message_detail("expbad", 1, 1)
    assert msg.get("message_pretty") == "not-valid-json"


# ---------------------------------------------------------------------------
# get_tool_schemas
# ---------------------------------------------------------------------------


async def test_get_tool_schemas(results_dir: Path) -> None:
    from src.gui.services.db_service import get_tool_schemas

    await _create_experiment(results_dir)
    schemas = await get_tool_schemas("exp001", 1)
    assert len(schemas) == 1
    assert schemas[0]["tool_name"] == "echo"


async def test_get_tool_schemas_no_db(results_dir: Path) -> None:
    from src.gui.services.db_service import get_tool_schemas

    assert await get_tool_schemas("nope", 1) == []


# ---------------------------------------------------------------------------
# get_adapter_pairs
# ---------------------------------------------------------------------------


async def test_get_adapter_pairs(results_dir: Path) -> None:
    from src.gui.services.db_service import get_adapter_pairs

    await _create_experiment(results_dir)
    pairs = await get_adapter_pairs("exp001", 1)
    assert len(pairs) == 1
    assert pairs[0]["request"]["provider"] == "ollama"
    assert pairs[0]["response"] is not None


async def test_get_adapter_pairs_no_db(results_dir: Path) -> None:
    from src.gui.services.db_service import get_adapter_pairs

    assert await get_adapter_pairs("nope", 1) == []


async def test_get_adapter_pairs_pretty_print(results_dir: Path) -> None:
    from src.gui.services.db_service import get_adapter_pairs

    # Create experiment with JSON fields that can be pretty-printed.
    run_dir = results_dir / "expp" / "run_1"
    run_dir.mkdir(parents=True)
    db_path = run_dir / "experiment.db"
    async with aiosqlite.connect(str(db_path)) as db:
        await db.executescript(_CREATE_TABLES)
        await db.execute(
            "INSERT INTO adapter_requests (session_id, timestamp, provider, model, translated_tools_json, request_json) VALUES (?,?,?,?,?,?)",
            ("s1", "2025-01-01", "ollama", "l", '{"key":"val"}', '{"req":true}'),
        )
        await db.execute(
            "INSERT INTO adapter_responses (session_id, timestamp, provider, model, response_json, tool_calls_json, iteration_number) VALUES (?,?,?,?,?,?,?)",
            ("s1", "2025-01-01", "ollama", "l", '{"resp":true}', '[{"name":"echo"}]', 1),
        )
        await db.commit()

    pairs = await get_adapter_pairs("expp", 1)
    assert "request_json_pretty" in pairs[0]["request"]
    assert "response_json_pretty" in pairs[0]["response"]
    assert "tool_calls_json_pretty" in pairs[0]["response"]


async def test_get_adapter_pairs_bad_json(results_dir: Path) -> None:
    from src.gui.services.db_service import get_adapter_pairs

    run_dir = results_dir / "expbj" / "run_1"
    run_dir.mkdir(parents=True)
    db_path = run_dir / "experiment.db"
    async with aiosqlite.connect(str(db_path)) as db:
        await db.executescript(_CREATE_TABLES)
        await db.execute(
            "INSERT INTO adapter_requests (session_id, timestamp, provider, model, translated_tools_json, request_json) VALUES (?,?,?,?,?,?)",
            ("s1", "2025-01-01", "ollama", "l", "bad-json", "bad-json"),
        )
        await db.execute(
            "INSERT INTO adapter_responses (session_id, timestamp, provider, model, response_json, tool_calls_json, iteration_number) VALUES (?,?,?,?,?,?,?)",
            ("s1", "2025-01-01", "ollama", "l", "bad-json", "bad-json", 1),
        )
        await db.commit()

    pairs = await get_adapter_pairs("expbj", 1)
    # Should not crash; pretty-print keys should be absent.
    assert "request_json_pretty" not in pairs[0]["request"]
