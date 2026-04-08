"""Tests for src.gui.routes.results."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:
    from httpx import AsyncClient

_EMPTY_LIST = {"items": [], "total": 0, "pages": 1}
_EMPTY_META = {
    "experiment_id": "exp1",
    "run_number": 1,
    "config": {},
    "hypothesis": "H3",
    "variant": "direct",
    "provider": "ollama",
    "model": "llama3.2",
    "db_exists": False,
}


async def test_list_all(client: AsyncClient) -> None:
    with patch(
        "src.gui.routes.results.list_experiments", new_callable=AsyncMock, return_value=_EMPTY_LIST
    ):
        resp = await client.get("/results")
    assert resp.status_code == 200


async def test_run_detail(client: AsyncClient) -> None:
    with patch(
        "src.gui.routes.results.get_run_metadata", new_callable=AsyncMock, return_value=_EMPTY_META
    ):
        resp = await client.get("/results/exp1/run/1")
    assert resp.status_code == 200


async def test_messages_partial(client: AsyncClient) -> None:
    with patch(
        "src.gui.routes.results.get_messages", new_callable=AsyncMock, return_value=_EMPTY_LIST
    ):
        resp = await client.get("/htmx/results/exp1/run/1/messages")
    assert resp.status_code == 200


async def test_message_detail_partial(client: AsyncClient) -> None:
    msg = {
        "id": 1,
        "session_id": "s1234567890ab",
        "timestamp": "2025-01-01T00:00:00",
        "direction": "client_to_server",
        "message_type": "request",
        "method": "tools/list",
        "message_json": '{"jsonrpc":"2.0"}',
        "message_pretty": '{\n  "jsonrpc": "2.0"\n}',
        "content_hash": "abc123",
        "parse_error": 0,
    }
    with patch(
        "src.gui.routes.results.get_message_detail", new_callable=AsyncMock, return_value=msg
    ):
        resp = await client.get("/htmx/results/exp1/run/1/message/1")
    assert resp.status_code == 200


async def test_schemas_partial(client: AsyncClient) -> None:
    with patch("src.gui.routes.results.get_tool_schemas", new_callable=AsyncMock, return_value=[]):
        resp = await client.get("/htmx/results/exp1/run/1/schemas")
    assert resp.status_code == 200


async def test_adapter_partial(client: AsyncClient) -> None:
    with patch("src.gui.routes.results.get_adapter_pairs", new_callable=AsyncMock, return_value=[]):
        resp = await client.get("/htmx/results/exp1/run/1/adapter")
    assert resp.status_code == 200


async def test_events_partial(client: AsyncClient) -> None:
    with patch(
        "src.gui.routes.results.get_run_events",
        new_callable=AsyncMock,
        return_value={
            "schema_mutations": [],
            "undeclared_params": [],
            "injection_patterns": [],
            "anomalous_calls": [],
        },
    ):
        resp = await client.get("/htmx/results/exp1/run/1/events")
    assert resp.status_code == 200
