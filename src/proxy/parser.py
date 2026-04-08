"""JSON-RPC message parsing for MCP proxy."""

from __future__ import annotations

import json
from dataclasses import dataclass

from src.proxy.hasher import hash_content


@dataclass
class ParsedMessage:
    """A parsed JSON-RPC message with classification metadata.

    Attributes:
        raw: The original bytes received on the wire.
        message_type: One of 'request', 'response', 'notification', 'error'.
        method: The JSON-RPC method name, if present.
        msg_id: The JSON-RPC message id, if present.
        parsed: The parsed JSON dict, or None on parse failure.
        parse_error: True if the raw bytes could not be parsed as JSON.
    """

    raw: bytes
    message_type: str
    method: str | None = None
    msg_id: int | str | None = None
    parsed: dict[str, object] | None = None
    parse_error: bool = False


@dataclass
class ToolSchema:
    """Extracted tool schema from a tools/list response.

    Attributes:
        name: The tool name.
        description: The tool description text.
        description_hash: SHA-256 hash of the canonical description.
        input_schema_json: The inputSchema serialized as JSON.
        input_schema_hash: SHA-256 hash of the canonical inputSchema JSON.
    """

    name: str
    description: str
    description_hash: str
    input_schema_json: str
    input_schema_hash: str


def _classify_single(data: dict[str, object], raw: bytes) -> ParsedMessage:
    """Classify a single JSON-RPC message dict.

    Args:
        data: Parsed JSON dict for the message.
        raw: The original raw bytes.

    Returns:
        A classified ParsedMessage.
    """
    raw_id = data.get("id")
    msg_id: int | str | None = raw_id if isinstance(raw_id, (int, str)) else None
    method = data.get("method")

    if method is not None and msg_id is not None:
        message_type = "request"
    elif method is not None and msg_id is None:
        message_type = "notification"
    elif msg_id is not None and "error" in data:
        message_type = "error"
    elif msg_id is not None and "result" in data:
        message_type = "response"
    else:
        # Ambiguous — treat as response if it has an id, else notification.
        message_type = "response" if msg_id is not None else "notification"

    return ParsedMessage(
        raw=raw,
        message_type=message_type,
        method=str(method) if method is not None else None,
        msg_id=msg_id,
        parsed=dict(data),
        parse_error=False,
    )


def parse_jsonrpc(raw: bytes) -> ParsedMessage:
    """Parse a line of JSON-RPC into a classified ParsedMessage.

    Classification rules:
    - **Request**: has both ``id`` and ``method``.
    - **Response**: has ``id`` and ``result`` (but no ``method``).
    - **Error**: has ``id`` and ``error`` (but no ``method``).
    - **Notification**: has ``method`` but no ``id``.

    On JSON parse failure the message is returned with ``parse_error=True``
    and the raw bytes preserved.

    Args:
        raw: A single line of bytes from the JSON-RPC stream.

    Returns:
        A ParsedMessage with classification and optional parsed content.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ParsedMessage(
            raw=raw,
            message_type="error",
            parse_error=True,
        )

    if isinstance(data, dict):
        return _classify_single(data, raw)

    # JSON-RPC batch: return the first element classified, with all parsed.
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return _classify_single(first, raw)

    return ParsedMessage(
        raw=raw,
        message_type="error",
        parse_error=True,
    )


def parse_jsonrpc_batch(raw: bytes) -> list[ParsedMessage]:
    """Parse a line of JSON-RPC that may be a batch (JSON array).

    Unlike ``parse_jsonrpc``, this returns a list of one or more messages.
    Batch requests (JSON arrays) are split into individual messages.

    Args:
        raw: A single line of bytes from the JSON-RPC stream.

    Returns:
        A list of ParsedMessage instances.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return [
            ParsedMessage(
                raw=raw,
                message_type="error",
                parse_error=True,
            ),
        ]

    if isinstance(data, dict):
        return [_classify_single(data, raw)]

    if isinstance(data, list):
        messages: list[ParsedMessage] = []
        for item in data:
            if isinstance(item, dict):
                item_raw = json.dumps(item).encode()
                messages.append(_classify_single(item, item_raw))
        return messages if messages else [
            ParsedMessage(raw=raw, message_type="error", parse_error=True),
        ]

    return [
        ParsedMessage(raw=raw, message_type="error", parse_error=True),
    ]


def extract_tool_schemas(message: dict[str, object]) -> list[ToolSchema]:
    """Extract tool schemas from a tools/list JSON-RPC response.

    Expects the message to have ``result.tools`` containing an array of
    tool definitions, each with ``name``, ``description``, and
    ``inputSchema`` fields.

    Args:
        message: A parsed JSON-RPC response dict.

    Returns:
        A list of ToolSchema instances, one per tool in the response.
        Returns an empty list if the expected structure is not found.
    """
    schemas: list[ToolSchema] = []
    result = message.get("result")
    if not isinstance(result, dict):
        return schemas

    tools = result.get("tools")
    if not isinstance(tools, list):
        return schemas

    for tool in tools:
        if not isinstance(tool, dict):
            continue

        name = tool.get("name", "")
        description = tool.get("description", "")
        input_schema = tool.get("inputSchema", {})

        description_str = str(description)
        input_schema_json = json.dumps(input_schema, sort_keys=True, separators=(",", ":"))

        schemas.append(
            ToolSchema(
                name=str(name),
                description=description_str,
                description_hash=hash_content(description_str),
                input_schema_json=input_schema_json,
                input_schema_hash=hash_content(input_schema_json),
            ),
        )

    return schemas
