"""Tests for src/proxy/logger.py — async SQLite logging."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import aiosqlite

from src.proxy.logger import ProxyLogger
from src.proxy.parser import ParsedMessage, ToolSchema

if TYPE_CHECKING:
    from pathlib import Path

# ISO 8601 with timezone, e.g. 2026-04-01T12:00:00.000000+00:00
_ISO8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+\+00:00$")


async def test_creates_tables(tmp_db: Path) -> None:
    """ProxyLogger.initialize creates all four expected tables."""
    async with ProxyLogger(tmp_db) as logger:
        db = logger._get_db()  # noqa: SLF001
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
        )
        tables = {row[0] for row in await cursor.fetchall()}

    expected = {"proxy_messages", "proxy_tool_schemas", "adapter_requests", "adapter_responses"}
    assert expected.issubset(tables)


async def test_log_message(tmp_db: Path) -> None:
    """log_message inserts a row into proxy_messages with correct fields."""
    msg = ParsedMessage(
        raw=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
        message_type="request",
        method="tools/list",
        msg_id=1,
        parsed={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        parse_error=False,
    )
    async with ProxyLogger(tmp_db) as logger:
        await logger.log_message("client_to_server", msg)

    async with aiosqlite.connect(str(tmp_db)) as db:
        cursor = await db.execute("SELECT * FROM proxy_messages")
        rows = list(await cursor.fetchall())

    assert len(rows) == 1
    row = rows[0]
    # Columns: id, session_id, timestamp, direction, message_type, method,
    #          message_json, content_hash, parse_error
    assert row[3] == "client_to_server"
    assert row[4] == "request"
    assert row[5] == "tools/list"
    assert row[8] == 0  # parse_error


async def test_log_tool_schema(tmp_db: Path) -> None:
    """log_tool_schema inserts a row into proxy_tool_schemas with correct fields."""
    schema = ToolSchema(
        name="echo",
        description="Echo a message",
        description_hash="abc123",
        input_schema_json='{"type":"object"}',
        input_schema_hash="def456",
    )
    async with ProxyLogger(tmp_db) as logger:
        await logger.log_tool_schema(schema, list_call_seq=1)

    async with aiosqlite.connect(str(tmp_db)) as db:
        cursor = await db.execute("SELECT * FROM proxy_tool_schemas")
        rows = list(await cursor.fetchall())

    assert len(rows) == 1
    row = rows[0]
    # Columns: id, session_id, timestamp, tool_name, description,
    #          description_hash, input_schema_json, input_schema_hash,
    #          list_call_sequence_number
    assert row[3] == "echo"
    assert row[4] == "Echo a message"
    assert row[5] == "abc123"
    assert row[6] == '{"type":"object"}'
    assert row[7] == "def456"
    assert row[8] == 1


async def test_log_adapter_request(tmp_db: Path) -> None:
    """log_adapter_request inserts a row into adapter_requests."""
    async with ProxyLogger(tmp_db) as logger:
        await logger.log_adapter_request(
            provider="anthropic",
            model="claude-opus-4-6",
            translated_tools='[{"name":"echo"}]',
            request_json='{"messages":[]}',
        )

    async with aiosqlite.connect(str(tmp_db)) as db:
        cursor = await db.execute("SELECT * FROM adapter_requests")
        rows = list(await cursor.fetchall())

    assert len(rows) == 1
    row = rows[0]
    # Columns: id, session_id, timestamp, provider, model,
    #          translated_tools_json, request_json
    assert row[3] == "anthropic"
    assert row[4] == "claude-opus-4-6"
    assert row[5] == '[{"name":"echo"}]'
    assert row[6] == '{"messages":[]}'


async def test_log_adapter_response(tmp_db: Path) -> None:
    """log_adapter_response inserts a row into adapter_responses."""
    async with ProxyLogger(tmp_db) as logger:
        await logger.log_adapter_response(
            provider="openai",
            model="gpt-5.4",
            response_json='{"choices":[]}',
            tool_calls_json='[{"name":"echo"}]',
            classification="silent_refusal",
        )

    async with aiosqlite.connect(str(tmp_db)) as db:
        cursor = await db.execute("SELECT * FROM adapter_responses")
        rows = list(await cursor.fetchall())

    assert len(rows) == 1
    row = rows[0]
    # Columns: id, session_id, timestamp, provider, model,
    #          response_json, tool_calls_json, compliance_classification
    assert row[3] == "openai"
    assert row[4] == "gpt-5.4"
    assert row[5] == '{"choices":[]}'
    assert row[6] == '[{"name":"echo"}]'
    assert row[7] == "silent_refusal"


async def test_session_id_consistent(tmp_db: Path) -> None:
    """session_id remains the same across multiple log calls."""
    msg = ParsedMessage(
        raw=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
        message_type="request",
        method="tools/list",
        msg_id=1,
        parsed={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        parse_error=False,
    )
    async with ProxyLogger(tmp_db) as logger:
        await logger.log_message("client_to_server", msg)
        await logger.log_message("server_to_client", msg)
        expected_sid = logger.session_id

    async with aiosqlite.connect(str(tmp_db)) as db:
        cursor = await db.execute("SELECT session_id FROM proxy_messages")
        rows = list(await cursor.fetchall())

    assert len(rows) == 2
    assert rows[0][0] == expected_sid
    assert rows[1][0] == expected_sid


async def test_timestamp_format(tmp_db: Path) -> None:
    """Logged timestamps match ISO 8601 format with timezone offset."""
    msg = ParsedMessage(
        raw=b'{"jsonrpc":"2.0","id":1,"method":"initialize"}',
        message_type="request",
        method="initialize",
        msg_id=1,
        parsed={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        parse_error=False,
    )
    async with ProxyLogger(tmp_db) as logger:
        await logger.log_message("client_to_server", msg)

    async with aiosqlite.connect(str(tmp_db)) as db:
        cursor = await db.execute("SELECT timestamp FROM proxy_messages")
        rows = list(await cursor.fetchall())

    assert len(rows) == 1
    assert _ISO8601_RE.match(rows[0][0]), f"Timestamp does not match ISO 8601: {rows[0][0]}"


async def test_batched_commit_on_close(tmp_db: Path) -> None:
    """Uncommitted writes are flushed when close() is called with commit_every > 1."""
    msg = ParsedMessage(
        raw=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
        message_type="request",
        method="tools/list",
        msg_id=1,
        parsed={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        parse_error=False,
    )
    # Use commit_every=100 so the single insert is not auto-committed.
    async with ProxyLogger(tmp_db, commit_every=100) as logger:
        await logger.log_message("client_to_server", msg)
        # At this point _uncommitted == 1, not yet committed.

    # After context manager exit (close()), the row should be committed.
    async with aiosqlite.connect(str(tmp_db)) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM proxy_messages")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 1


async def test_maybe_commit_triggers_at_threshold(tmp_db: Path) -> None:
    """_maybe_commit commits exactly when _uncommitted reaches commit_every."""
    # Use commit_every=2 so the second insert triggers a commit.
    logger = ProxyLogger(tmp_db, commit_every=2)
    await logger.initialize()

    msg = ParsedMessage(
        raw=b'{"jsonrpc":"2.0","id":1,"method":"test"}',
        message_type="request",
        method="test",
        msg_id=1,
        parsed={"jsonrpc": "2.0", "id": 1, "method": "test"},
        parse_error=False,
    )
    await logger.log_message("client_to_server", msg)
    # First insert: _uncommitted=1, no commit yet.
    assert logger._uncommitted == 1  # noqa: SLF001

    await logger.log_message("client_to_server", msg)
    # Second insert: _uncommitted reached 2, committed and reset.
    assert logger._uncommitted == 0  # noqa: SLF001

    await logger.close()
