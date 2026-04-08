"""Tests for adapter request/response logging in ProxyLogger."""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiosqlite

from src.proxy.logger import ProxyLogger
from src.proxy.parser import ParsedMessage

if TYPE_CHECKING:
    from pathlib import Path


async def test_adapter_requests_populated(tmp_db: Path) -> None:
    """log_adapter_request should insert a row into adapter_requests."""
    async with ProxyLogger(str(tmp_db)) as logger:
        await logger.log_adapter_request(
            provider="ollama",
            model="llama3.2",
            translated_tools='[{"name":"echo"}]',
            request_json='{"messages":[]}',
        )

    async with aiosqlite.connect(str(tmp_db)) as db:
        cursor = await db.execute("SELECT provider, model FROM adapter_requests")
        rows = await cursor.fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "ollama"
    assert rows[0][1] == "llama3.2"


async def test_adapter_responses_populated(tmp_db: Path) -> None:
    """log_adapter_response should insert a row into adapter_responses."""
    async with ProxyLogger(str(tmp_db)) as logger:
        await logger.log_adapter_response(
            provider="openai",
            model="gpt-4",
            response_json='{"choices":[]}',
            tool_calls_json='[{"name":"echo","arguments":{}}]',
            classification="full_execution",
        )

    async with aiosqlite.connect(str(tmp_db)) as db:
        cursor = await db.execute(
            "SELECT provider, model, compliance_classification FROM adapter_responses",
        )
        rows = await cursor.fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "openai"
    assert rows[0][1] == "gpt-4"
    assert rows[0][2] == "full_execution"


async def test_adapter_tables_coexist_with_proxy(tmp_db: Path) -> None:
    """All four tables should hold data when both proxy and adapter logging is used."""
    async with ProxyLogger(str(tmp_db)) as logger:
        # Log a proxy message.
        parsed = ParsedMessage(
            raw=b'{"jsonrpc":"2.0","method":"echo","id":1}',
            message_type="request",
            method="echo",
            msg_id=1,
            parsed={"jsonrpc": "2.0", "method": "echo", "id": 1},
        )
        await logger.log_message("client_to_server", parsed)

        # Log an adapter request and response.
        await logger.log_adapter_request(
            provider="anthropic",
            model="claude-3",
            translated_tools="[]",
            request_json="{}",
        )
        await logger.log_adapter_response(
            provider="anthropic",
            model="claude-3",
            response_json="{}",
            tool_calls_json=None,
            classification=None,
        )

    async with aiosqlite.connect(str(tmp_db)) as db:
        tables = ["proxy_messages", "proxy_tool_schemas", "adapter_requests", "adapter_responses"]
        counts: dict[str, int] = {}
        for table in tables:
            cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            row = await cursor.fetchone()
            assert row is not None
            counts[table] = row[0]

    # proxy_messages, adapter_requests, adapter_responses each have >= 1 row.
    assert counts["proxy_messages"] >= 1
    assert counts["adapter_requests"] >= 1
    assert counts["adapter_responses"] >= 1
    # proxy_tool_schemas may be 0 (no tools/list logged), but the table exists.


async def test_session_id_links_records(tmp_db: Path) -> None:
    """Proxy message and adapter request from the same logger share session_id."""
    async with ProxyLogger(str(tmp_db)) as logger:
        expected_session_id = logger.session_id

        parsed = ParsedMessage(
            raw=b'{"jsonrpc":"2.0","method":"initialize","id":1}',
            message_type="request",
            method="initialize",
            msg_id=1,
            parsed={"jsonrpc": "2.0", "method": "initialize", "id": 1},
        )
        await logger.log_message("client_to_server", parsed)

        await logger.log_adapter_request(
            provider="google",
            model="gemini-pro",
            translated_tools="[]",
            request_json="{}",
        )

    async with aiosqlite.connect(str(tmp_db)) as db:
        cursor = await db.execute("SELECT session_id FROM proxy_messages")
        proxy_rows = await cursor.fetchall()

        cursor = await db.execute("SELECT session_id FROM adapter_requests")
        adapter_rows = await cursor.fetchall()

    assert len(proxy_rows) == 1
    assert len(adapter_rows) == 1
    assert proxy_rows[0][0] == expected_session_id
    assert adapter_rows[0][0] == expected_session_id
