"""Security-relevant event detection for MCP detection blindness experiments.

Scans the proxy SQLite database for four categories of security events:
schema mutations, undeclared parameters, injection patterns, and anomalous calls.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING

import aiosqlite

if TYPE_CHECKING:
    from pathlib import Path


class VisibilityTier(Enum):
    """Classification of how a security event is surfaced to the operator."""

    UI_VISIBLE = "ui_visible"
    LOG_VISIBLE = "log_visible"
    ABSENT = "absent"


# Patterns that suggest injected instructions in tool responses.
_INJECTION_PATTERNS: list[str] = [
    r"\byou must\b",
    r"\bcall the\b",
    r"\bread_file\b",
    r"\bIMPORTANT\b",
    r"\bSYSTEM NOTE\b",
    r"\bverification\b",
    r"\bsession expired\b",
    r"\bre-authenticate\b",
]

# Base64-like string: length > 20, alphanumeric plus / + =.
_BASE64_PATTERN = r"(?<!\w)[A-Za-z0-9+/=]{21,}(?!\w)"


@dataclass(frozen=True)
class SchemaEvent:
    """A tool schema mutation detected between successive tools/list calls."""

    session_id: str
    tool_name: str
    old_hash: str
    new_hash: str
    old_description: str
    new_description: str
    timestamp: str
    visibility: VisibilityTier = VisibilityTier.ABSENT


@dataclass(frozen=True)
class ParamEvent:
    """An undeclared parameter passed in a tools/call request."""

    session_id: str
    tool_name: str
    declared_params: list[str]
    actual_params: list[str]
    undeclared_params: list[str]
    timestamp: str
    visibility: VisibilityTier = VisibilityTier.ABSENT


@dataclass(frozen=True)
class InjectionEvent:
    """An injection pattern detected in a tool response payload."""

    session_id: str
    response_text: str
    matched_patterns: list[str]
    timestamp: str
    visibility: VisibilityTier = VisibilityTier.ABSENT


@dataclass(frozen=True)
class AnomalousCallEvent:
    """A tools/call targeting a tool not in the expected set."""

    session_id: str
    tool_name: str
    arguments: dict[str, object]
    timestamp: str
    visibility: VisibilityTier = VisibilityTier.ABSENT


# Type alias for any security event.
SecurityEvent = SchemaEvent | ParamEvent | InjectionEvent | AnomalousCallEvent


async def detect_schema_mutations(db_path: Path) -> list[SchemaEvent]:
    """Compare successive proxy_tool_schemas entries for the same tool.

    If description_hash or input_schema_hash differ between consecutive
    list_call_sequence_number values for a tool within a session, emit an event.

    Args:
        db_path: Path to the experiment SQLite database.

    Returns:
        List of schema mutation events found.
    """
    events: list[SchemaEvent] = []
    query = """
        SELECT session_id, tool_name, description, description_hash,
               input_schema_hash, list_call_sequence_number, timestamp
        FROM proxy_tool_schemas
        ORDER BY session_id, tool_name, list_call_sequence_number
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query) as cursor:
            prev: dict[tuple[str, str], aiosqlite.Row] = {}
            async for row in cursor:
                key = (row["session_id"], row["tool_name"])
                if key in prev:
                    old = prev[key]
                    desc_changed = old["description_hash"] != row["description_hash"]
                    schema_changed = old["input_schema_hash"] != row["input_schema_hash"]
                    if desc_changed or schema_changed:
                        events.append(
                            SchemaEvent(
                                session_id=row["session_id"],
                                tool_name=row["tool_name"],
                                old_hash=(
                                    old["description_hash"]
                                    if desc_changed
                                    else old["input_schema_hash"]
                                ),
                                new_hash=(
                                    row["description_hash"]
                                    if desc_changed
                                    else row["input_schema_hash"]
                                ),
                                old_description=old["description"],
                                new_description=row["description"],
                                timestamp=row["timestamp"],
                            ),
                        )
                prev[key] = row
    return events


async def detect_undeclared_params(db_path: Path) -> list[ParamEvent]:
    """Detect tools/call requests that pass undeclared parameters.

    For each ``tools/call`` message in proxy_messages, extract the arguments
    and compare against the most recent proxy_tool_schemas entry for that tool.
    Any key present in arguments but absent from the declared inputSchema
    properties is flagged as undeclared.

    Args:
        db_path: Path to the experiment SQLite database.

    Returns:
        List of undeclared parameter events found.
    """
    events: list[ParamEvent] = []

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Build a lookup of the latest declared schema per (session_id, tool_name).
        schema_lookup: dict[tuple[str, str], list[str]] = {}
        schema_query = """
            SELECT session_id, tool_name, input_schema_json
            FROM proxy_tool_schemas
            ORDER BY list_call_sequence_number ASC
        """
        async with db.execute(schema_query) as cursor:
            async for row in cursor:
                schema_json = row["input_schema_json"]
                try:
                    schema = json.loads(schema_json) if schema_json else {}
                except (json.JSONDecodeError, TypeError):
                    schema = {}
                properties: dict[str, object] = schema.get("properties", {})
                key = (row["session_id"], row["tool_name"])
                schema_lookup[key] = list(properties.keys())

        # Scan tools/call requests from proxy_messages.
        calls_query = """
            SELECT session_id, timestamp, message_json
            FROM proxy_messages
            WHERE method = 'tools/call' AND direction = 'client_to_server'
            ORDER BY timestamp
        """
        async with db.execute(calls_query) as cursor:
            async for row in cursor:
                try:
                    msg = json.loads(row["message_json"])
                except (json.JSONDecodeError, TypeError):
                    continue

                params = msg.get("params", {})
                tool_name: str = params.get("name", "")
                arguments: dict[str, object] = params.get("arguments", {})
                if not tool_name or not arguments:
                    continue

                key = (row["session_id"], tool_name)
                declared = schema_lookup.get(key, [])
                actual = list(arguments.keys())
                undeclared = [p for p in actual if p not in declared]

                if undeclared:
                    events.append(
                        ParamEvent(
                            session_id=row["session_id"],
                            tool_name=tool_name,
                            declared_params=declared,
                            actual_params=actual,
                            undeclared_params=undeclared,
                            timestamp=row["timestamp"],
                        ),
                    )
    return events


async def detect_injection_patterns(db_path: Path) -> list[InjectionEvent]:
    """Scan tool responses for injection patterns.

    Examines server-to-client messages that are tool/call responses for known
    instruction-injection keywords and base64-encoded strings.

    Args:
        db_path: Path to the experiment SQLite database.

    Returns:
        List of injection pattern events found.
    """
    events: list[InjectionEvent] = []
    compiled = [(p, re.compile(p, re.IGNORECASE)) for p in _INJECTION_PATTERNS]
    base64_re = re.compile(_BASE64_PATTERN)

    query = """
        SELECT session_id, timestamp, message_json
        FROM proxy_messages
        WHERE direction = 'server_to_client'
          AND message_type = 'response'
        ORDER BY timestamp
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query) as cursor:
            async for row in cursor:
                try:
                    msg = json.loads(row["message_json"])
                except (json.JSONDecodeError, TypeError):
                    continue

                # Extract text from result.content[].text fields.
                result = msg.get("result", {})
                content_items: list[dict[str, object]] = result.get("content", [])
                texts: list[str] = []
                for item in content_items:
                    if isinstance(item, dict):
                        text_val = item.get("text")
                        if isinstance(text_val, str):
                            texts.append(text_val)

                full_text = "\n".join(texts)
                if not full_text:
                    continue

                matched: list[str] = []
                for pattern_str, pattern_re in compiled:
                    if pattern_re.search(full_text):
                        matched.append(pattern_str)
                if base64_re.search(full_text):
                    matched.append("base64_string")

                if matched:
                    events.append(
                        InjectionEvent(
                            session_id=row["session_id"],
                            response_text=full_text,
                            matched_patterns=matched,
                            timestamp=row["timestamp"],
                        ),
                    )
    return events


async def detect_anomalous_calls(
    db_path: Path,
    expected_tools: set[str],
) -> list[AnomalousCallEvent]:
    """Find tools/call requests targeting tools not in the expected set.

    Args:
        db_path: Path to the experiment SQLite database.
        expected_tools: Set of tool names that are expected for this experiment.

    Returns:
        List of anomalous call events found.
    """
    events: list[AnomalousCallEvent] = []
    query = """
        SELECT session_id, timestamp, message_json
        FROM proxy_messages
        WHERE method = 'tools/call' AND direction = 'client_to_server'
        ORDER BY timestamp
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query) as cursor:
            async for row in cursor:
                try:
                    msg = json.loads(row["message_json"])
                except (json.JSONDecodeError, TypeError):
                    continue

                params = msg.get("params", {})
                tool_name: str = params.get("name", "")
                arguments: dict[str, object] = params.get("arguments", {})

                if tool_name and tool_name not in expected_tools:
                    events.append(
                        AnomalousCallEvent(
                            session_id=row["session_id"],
                            tool_name=tool_name,
                            arguments=arguments,
                            timestamp=row["timestamp"],
                        ),
                    )
    return events


# Keywords indicating the client surfaced an event in the UI.
_UI_VISIBLE_KEYWORDS: list[str] = [
    "WARNING",
    "BLOCKED",
    "DENIED",
    "user notification",
    "UI alert",
]

# Keywords indicating the client logged an event (not shown in UI).
_LOG_VISIBLE_KEYWORDS: dict[str, list[str]] = {
    "schema_mutation": ["schema", "mutation", "description changed", "hash"],
    "undeclared_param": ["SHADOW_PARAM", "undeclared", "extra param"],
    "injection_pattern": ["injection", "IMPORTANT", "SYSTEM NOTE", "you must", "read_file"],
    "anomalous_call": ["unexpected tool", "anomalous", "unknown tool"],
}


def _event_type_key(event: SecurityEvent) -> str:
    """Return the event-type key for log-visible keyword lookup."""
    if isinstance(event, SchemaEvent):
        return "schema_mutation"
    if isinstance(event, ParamEvent):
        return "undeclared_param"
    if isinstance(event, InjectionEvent):
        return "injection_pattern"
    return "anomalous_call"


def classify_visibility(
    events: list[SecurityEvent],
    client_log: list[str],
) -> list[SecurityEvent]:
    """Classify each event's visibility tier based on client log content.

    For each event, checks whether any client log line indicates the event
    was surfaced in the UI (UI_VISIBLE), merely logged (LOG_VISIBLE), or
    not captured at all (ABSENT).

    Args:
        events: List of security events to classify.
        client_log: Client log lines to check against.

    Returns:
        New list of events with updated visibility fields.
    """
    lowered_lines = [line.lower() for line in client_log]

    classified: list[SecurityEvent] = []
    for event in events:
        # Check UI-visible first (takes precedence).
        ui_match = any(kw.lower() in line for line in lowered_lines for kw in _UI_VISIBLE_KEYWORDS)
        if ui_match:
            classified.append(replace(event, visibility=VisibilityTier.UI_VISIBLE))
            continue

        # Check log-visible.
        type_key = _event_type_key(event)
        log_keywords = _LOG_VISIBLE_KEYWORDS.get(type_key, [])
        log_match = any(kw.lower() in line for line in lowered_lines for kw in log_keywords)
        if log_match:
            classified.append(replace(event, visibility=VisibilityTier.LOG_VISIBLE))
            continue

        # Default: absent.
        classified.append(event)

    return classified
