"""Proxy transparency validation suite.

Verifies the transparent proxy does not modify, add, remove, or reorder
any messages flowing between client and server. Three-test suite run
before every experiment batch.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers — mirror the patterns in test_proxy.py
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def _start_echo_server() -> asyncio.subprocess.Process:
    """Start the echo MCP server directly (no proxy)."""
    return await asyncio.create_subprocess_exec(
        "uv",
        "run",
        "python",
        "-m",
        "src.servers.echo",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(_PROJECT_ROOT),
    )


async def _start_proxied_echo(db_path: Path) -> asyncio.subprocess.Process:
    """Start the proxy wrapping the echo server."""
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
        cwd=str(_PROJECT_ROOT),
    )


async def _send_jsonrpc(
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
    return json.loads(response_line)


async def _send_notification(
    proc: asyncio.subprocess.Process,
    msg: dict[str, object],
) -> None:
    """Send a JSON-RPC notification (no response expected)."""
    assert proc.stdin is not None
    line = json.dumps(msg) + "\n"
    proc.stdin.write(line.encode())
    await proc.stdin.drain()


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    """Close stdin and wait for the process to exit."""
    assert proc.stdin is not None
    proc.stdin.close()
    try:
        await asyncio.wait_for(proc.wait(), timeout=10.0)
    except TimeoutError:
        proc.kill()
        await proc.wait()


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
    """Full init handshake: initialize + initialized notification."""
    resp = await _send_jsonrpc(proc, _init_request())
    await _send_notification(proc, _initialized_notification())
    await asyncio.sleep(0.1)
    return resp


def _canonical_json(obj: object) -> str:
    """Deterministic JSON serialisation for comparison."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Sequence used across multiple tests — init + tools/list + tools/call
# ---------------------------------------------------------------------------


async def _run_standard_sequence(
    proc: asyncio.subprocess.Process,
) -> list[dict[str, object]]:
    """Run init, tools/list, tools/call and return list of responses."""
    responses: list[dict[str, object]] = []
    responses.append(await _do_initialize(proc))
    responses.append(await _send_jsonrpc(proc, _tools_list_request()))
    responses.append(
        await _send_jsonrpc(proc, _tools_call_request("echo", {"message": "hello"})),
    )
    return responses


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def proxy_db(tmp_path: Path) -> Path:
    """Temporary database path for the proxy."""
    return tmp_path / "transparency.db"


async def test_byte_level_comparison(proxy_db: Path) -> None:
    """Responses via proxy match direct responses when parsed as JSON.

    Whitespace may differ (the proxy does not guarantee byte-identical
    formatting), but the semantic JSON content must be identical.
    """
    # Direct
    direct_proc = await _start_echo_server()
    try:
        direct_responses = await _run_standard_sequence(direct_proc)
    finally:
        await _terminate(direct_proc)

    # Via proxy
    proxy_proc = await _start_proxied_echo(proxy_db)
    try:
        proxy_responses = await _run_standard_sequence(proxy_proc)
    finally:
        await _terminate(proxy_proc)

    assert len(direct_responses) == len(proxy_responses)
    for direct, proxied in zip(direct_responses, proxy_responses, strict=True):
        assert _canonical_json(direct) == _canonical_json(proxied)


async def test_hash_comparison(proxy_db: Path) -> None:
    """SHA-256 of canonical JSON responses matches with and without proxy."""
    messages: list[dict[str, object]] = [
        _tools_call_request("echo", {"message": f"msg-{i}"}, msg_id=10 + i) for i in range(5)
    ]

    # Direct
    direct_proc = await _start_echo_server()
    try:
        await _do_initialize(direct_proc)
        await _send_jsonrpc(direct_proc, _tools_list_request())
        direct_hashes = []
        for msg in messages:
            resp = await _send_jsonrpc(direct_proc, msg)
            direct_hashes.append(_sha256(_canonical_json(resp)))
    finally:
        await _terminate(direct_proc)

    # Via proxy
    proxy_proc = await _start_proxied_echo(proxy_db)
    try:
        await _do_initialize(proxy_proc)
        await _send_jsonrpc(proxy_proc, _tools_list_request())
        proxy_hashes = []
        for msg in messages:
            resp = await _send_jsonrpc(proxy_proc, msg)
            proxy_hashes.append(_sha256(_canonical_json(resp)))
    finally:
        await _terminate(proxy_proc)

    assert direct_hashes == proxy_hashes


async def test_echo_roundtrip(proxy_db: Path) -> None:
    """10 echo requests through the proxy all return the expected text."""
    proc = await _start_proxied_echo(proxy_db)
    try:
        await _do_initialize(proc)
        await _send_jsonrpc(proc, _tools_list_request())

        for i in range(10):
            payload = f"roundtrip-{i}"
            resp = await _send_jsonrpc(
                proc,
                _tools_call_request("echo", {"message": payload}, msg_id=100 + i),
            )
            result = resp.get("result", {})
            assert isinstance(result, dict)
            content = result.get("content", [])
            assert isinstance(content, list)
            assert len(content) > 0
            text = content[0].get("text", "")
            assert payload in text
    finally:
        await _terminate(proc)


async def test_proxy_no_extra_messages(proxy_db: Path) -> None:
    """Proxy does not add, remove, or reorder messages.

    For each request that expects a response (has an 'id'), exactly one
    response should come back.  The number of responses should equal the
    number of requests.
    """
    requests_with_id: list[dict[str, object]] = [
        _init_request(),
        _tools_list_request(msg_id=2),
        _tools_call_request("echo", {"message": "a"}, msg_id=3),
        _tools_call_request("echo", {"message": "b"}, msg_id=4),
        _tools_call_request("echo", {"message": "c"}, msg_id=5),
    ]

    proc = await _start_proxied_echo(proxy_db)
    try:
        # Send init + notification first
        init_resp = await _send_jsonrpc(proc, requests_with_id[0])
        await _send_notification(proc, _initialized_notification())
        await asyncio.sleep(0.1)

        responses = [init_resp]
        for req in requests_with_id[1:]:
            resp = await _send_jsonrpc(proc, req)
            responses.append(resp)
    finally:
        await _terminate(proc)

    # Each request had an 'id'; each response should echo it back.
    sent_ids = [r["id"] for r in requests_with_id]
    received_ids = [r.get("id") for r in responses]
    assert sent_ids == received_ids
    assert len(responses) == len(requests_with_id)


async def test_proxy_no_content_modification(proxy_db: Path) -> None:
    """For every request, proxied result JSON is identical to direct result."""
    requests_after_init: list[dict[str, object]] = [
        _tools_list_request(msg_id=2),
        _tools_call_request("echo", {"message": "alpha"}, msg_id=3),
        _tools_call_request("echo", {"message": "beta"}, msg_id=4),
    ]

    # Direct
    direct_proc = await _start_echo_server()
    try:
        await _do_initialize(direct_proc)
        direct_results = []
        for req in requests_after_init:
            resp = await _send_jsonrpc(direct_proc, req)
            direct_results.append(resp)
    finally:
        await _terminate(direct_proc)

    # Proxied
    proxy_proc = await _start_proxied_echo(proxy_db)
    try:
        await _do_initialize(proxy_proc)
        proxy_results = []
        for req in requests_after_init:
            resp = await _send_jsonrpc(proxy_proc, req)
            proxy_results.append(resp)
    finally:
        await _terminate(proxy_proc)

    for direct, proxied in zip(direct_results, proxy_results, strict=True):
        assert _canonical_json(direct) == _canonical_json(proxied)
