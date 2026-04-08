"""Tests for src/proxy/parser.py — JSON-RPC message parsing."""

from __future__ import annotations

import json

from src.proxy.parser import extract_tool_schemas, parse_jsonrpc, parse_jsonrpc_batch


def test_parse_request() -> None:
    """A tools/list request is classified correctly."""
    raw = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    msg = parse_jsonrpc(raw)

    assert msg.message_type == "request"
    assert msg.method == "tools/list"
    assert msg.msg_id == 1
    assert msg.parse_error is False
    assert msg.parsed is not None


def test_parse_response() -> None:
    """A result response is classified correctly."""
    raw = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}).encode()
    msg = parse_jsonrpc(raw)

    assert msg.message_type == "response"
    assert msg.msg_id == 1
    assert msg.method is None
    assert msg.parse_error is False


def test_parse_notification() -> None:
    """An initialized notification is classified correctly."""
    raw = json.dumps({"jsonrpc": "2.0", "method": "initialized"}).encode()
    msg = parse_jsonrpc(raw)

    assert msg.message_type == "notification"
    assert msg.method == "initialized"
    assert msg.msg_id is None
    assert msg.parse_error is False


def test_parse_malformed() -> None:
    """Malformed input sets parse_error and preserves raw bytes."""
    raw = b"not json"
    msg = parse_jsonrpc(raw)

    assert msg.parse_error is True
    assert msg.raw == raw
    assert msg.parsed is None


def test_extract_tool_schemas() -> None:
    """extract_tool_schemas returns correct ToolSchema list from a tools/list response."""
    message: dict[str, object] = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [
                {
                    "name": "echo",
                    "description": "Echo a message",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                    },
                },
                {
                    "name": "read_file",
                    "description": "Read a file",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                },
            ],
        },
    }
    schemas = extract_tool_schemas(message)

    assert len(schemas) == 2
    assert schemas[0].name == "echo"
    assert schemas[0].description == "Echo a message"
    assert schemas[0].description_hash  # non-empty
    assert schemas[0].input_schema_json  # non-empty
    assert schemas[0].input_schema_hash  # non-empty
    assert schemas[1].name == "read_file"


def test_extract_empty_tools() -> None:
    """extract_tool_schemas returns empty list when tools array is empty."""
    message: dict[str, object] = {"result": {"tools": []}}
    schemas = extract_tool_schemas(message)

    assert schemas == []


def test_parse_batch_request() -> None:
    """parse_jsonrpc handles a JSON-RPC batch (array) without crashing."""
    batch = json.dumps(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call"},
        ]
    ).encode()
    msg = parse_jsonrpc(batch)
    # Returns first element classified, not a parse error.
    assert msg.parse_error is False
    assert msg.message_type == "request"
    assert msg.method == "tools/list"


def test_parse_batch_returns_all() -> None:
    """parse_jsonrpc_batch splits a batch into individual messages."""
    batch = json.dumps(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call"},
        ]
    ).encode()
    messages = parse_jsonrpc_batch(batch)
    assert len(messages) == 2
    assert messages[0].method == "tools/list"
    assert messages[1].method == "tools/call"


def test_parse_batch_single_message() -> None:
    """parse_jsonrpc_batch returns a single-element list for a non-batch message."""
    raw = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    messages = parse_jsonrpc_batch(raw)
    assert len(messages) == 1
    assert messages[0].method == "tools/list"
