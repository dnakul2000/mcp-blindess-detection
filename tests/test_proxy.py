"""Integration tests for the transparent MCP proxy.

Starts the proxy as a subprocess wrapping the echo server, then communicates
via stdin/stdout to verify JSON-RPC forwarding and SQLite logging.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiosqlite
import pytest


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return a temporary SQLite database path."""
    return tmp_path / "test_proxy.db"


async def _start_proxy(db_path: Path) -> asyncio.subprocess.Process:
    """Start the proxy subprocess wrapping the echo server."""
    return await asyncio.create_subprocess_exec(
        "uv",
        "run",
        "python",
        "-m",
        "src.proxy",
        "--db",
        str(db_path),
        "--",
        "uv",
        "run",
        "python",
        "-m",
        "src.servers.echo",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(Path(__file__).resolve().parent.parent),
    )


async def send_jsonrpc(
    proc: asyncio.subprocess.Process,
    msg: dict[str, object],
) -> dict[str, object]:
    """Send a JSON-RPC message and read the response line."""
    assert proc.stdin is not None
    assert proc.stdout is not None
    line = json.dumps(msg) + "\n"
    proc.stdin.write(line.encode())
    await proc.stdin.drain()
    response_line = await asyncio.wait_for(proc.stdout.readline(), timeout=30.0)
    result: dict[str, object] = json.loads(response_line)
    return result


async def send_notification(proc: asyncio.subprocess.Process, msg: dict[str, object]) -> None:
    """Send a JSON-RPC notification (no response expected)."""
    assert proc.stdin is not None
    line = json.dumps(msg) + "\n"
    proc.stdin.write(line.encode())
    await proc.stdin.drain()


def _init_request() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0.1"},
        },
    }


def _initialized_notification() -> dict[str, object]:
    return {"jsonrpc": "2.0", "method": "notifications/initialized"}


def _tools_list_request(msg_id: int = 2) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": msg_id, "method": "tools/list", "params": {}}


def _tools_call_request(
    tool_name: str,
    arguments: dict[str, object],
    msg_id: int = 3,
) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }


async def _do_initialize(proc: asyncio.subprocess.Process) -> dict[str, object]:
    """Perform the full initialize handshake and return the init response."""
    resp = await send_jsonrpc(proc, _init_request())
    await send_notification(proc, _initialized_notification())
    # Small delay to let the notification propagate.
    await asyncio.sleep(0.1)
    return resp


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    """Close stdin and wait for the proxy to exit."""
    assert proc.stdin is not None
    proc.stdin.close()
    try:
        await asyncio.wait_for(proc.wait(), timeout=10.0)
    except TimeoutError:
        proc.kill()
        await proc.wait()


async def test_proxy_forwards_initialize(db_path: Path) -> None:
    """Proxy forwards initialize request and returns a valid response."""
    proc = await _start_proxy(db_path)
    try:
        resp = await _do_initialize(proc)
        assert resp.get("jsonrpc") == "2.0"
        assert resp.get("id") == 1
        assert "result" in resp
        result = resp["result"]
        assert isinstance(result, dict)
        assert "capabilities" in result
        assert "serverInfo" in result
    finally:
        await _terminate(proc)


async def test_proxy_forwards_tools_list(db_path: Path) -> None:
    """Proxy forwards tools/list and returns the echo tool."""
    proc = await _start_proxy(db_path)
    try:
        await _do_initialize(proc)
        resp = await send_jsonrpc(proc, _tools_list_request())
        assert resp.get("id") == 2
        result = resp.get("result", {})
        assert isinstance(result, dict)
        tools = result.get("tools", [])
        assert isinstance(tools, list)
        tool_names = [t["name"] for t in tools if isinstance(t, dict)]
        assert "echo" in tool_names
    finally:
        await _terminate(proc)


async def test_proxy_forwards_tools_call(db_path: Path) -> None:
    """Proxy forwards tools/call to the echo server and returns the result."""
    proc = await _start_proxy(db_path)
    try:
        await _do_initialize(proc)
        await send_jsonrpc(proc, _tools_list_request())
        resp = await send_jsonrpc(proc, _tools_call_request("echo", {"message": "hello"}))
        assert resp.get("id") == 3
        result = resp.get("result", {})
        assert isinstance(result, dict)
        content = result.get("content", [])
        assert isinstance(content, list)
        assert len(content) > 0
        text = content[0].get("text", "")
        assert "hello" in text
    finally:
        await _terminate(proc)


async def test_proxy_logs_to_sqlite(db_path: Path) -> None:
    """Proxy writes traffic to the proxy_messages table in SQLite."""
    proc = await _start_proxy(db_path)
    try:
        await _do_initialize(proc)
        await send_jsonrpc(proc, _tools_list_request())
        await send_jsonrpc(proc, _tools_call_request("echo", {"message": "test"}))
    finally:
        await _terminate(proc)

    # Allow a moment for WAL flush.
    await asyncio.sleep(0.2)

    async with (
        aiosqlite.connect(str(db_path)) as db,
        db.execute(
            "SELECT COUNT(*) FROM proxy_messages",
        ) as cursor,
    ):
        row = await cursor.fetchone()
        assert row is not None
        count = row[0]
        # At minimum: init request + init response + tools/list req + tools/list resp
        # + tools/call req + tools/call resp + initialized notification = 7
        assert count >= 6, f"Expected at least 6 proxy_messages rows, got {count}"


async def test_proxy_logs_tool_schemas(db_path: Path) -> None:
    """Proxy writes tool schemas to proxy_tool_schemas after tools/list."""
    proc = await _start_proxy(db_path)
    try:
        await _do_initialize(proc)
        await send_jsonrpc(proc, _tools_list_request())
    finally:
        await _terminate(proc)

    await asyncio.sleep(0.2)

    async with aiosqlite.connect(str(db_path)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM proxy_tool_schemas") as cursor:
            rows = list(await cursor.fetchall())
            assert len(rows) >= 1, "Expected at least one tool schema row"
            tool_names = [row["tool_name"] for row in rows]
            assert "echo" in tool_names
