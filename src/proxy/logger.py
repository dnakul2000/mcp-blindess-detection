"""SQLite logging for MCP proxy sessions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite

if TYPE_CHECKING:
    from types import TracebackType

    from src.proxy.parser import ParsedMessage, ToolSchema

_CREATE_TABLES_SQL = """\
CREATE TABLE IF NOT EXISTS proxy_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('client_to_server', 'server_to_client')),
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

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
INSERT OR IGNORE INTO schema_version (rowid, version) VALUES (1, 2);
"""


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 with microsecond precision."""
    return datetime.now(tz=UTC).isoformat(timespec="microseconds")


class ProxyLogger:
    """Async SQLite logger for MCP proxy sessions.

    Provides structured logging of JSON-RPC messages, tool schemas,
    and LLM adapter request/response pairs into a single SQLite database.

    Usage::

        async with ProxyLogger("experiment.db") as logger:
            await logger.log_message("client_to_server", parsed_msg)
    """

    def __init__(
        self,
        db_path: str | Path,
        commit_every: int = 1,
    ) -> None:
        """Initialise the proxy logger.

        Args:
            db_path: Path to the SQLite database file. Created if it
                does not exist with 0o600 permissions.
            commit_every: Number of inserts between automatic commits.
                Use 1 for immediate commits (e.g. in tests).
        """
        self._db_path = Path(db_path)
        self.session_id: str = str(uuid.uuid4())
        self._db: aiosqlite.Connection | None = None
        self._commit_every: int = commit_every
        self._uncommitted: int = 0

    async def initialize(self) -> None:
        """Create database tables if they do not exist.

        Opens the database connection and sets file permissions to 0o600
        on first creation.
        """
        is_new = not self._db_path.exists()
        self._db = await aiosqlite.connect(str(self._db_path))
        # Set WAL mode and busy_timeout so concurrent writers (proxy
        # subprocess + agent loop) can coexist.  WAL allows concurrent
        # reads during writes; busy_timeout retries on SQLITE_BUSY.
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=10000")
        await self._db.executescript(_CREATE_TABLES_SQL)
        await self._db.commit()
        if is_new:
            self._db_path.chmod(0o600)

    async def close(self) -> None:
        """Close the database connection, flushing any uncommitted writes."""
        if self._db is not None:
            if self._uncommitted > 0:
                await self._db.commit()
                self._uncommitted = 0
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> ProxyLogger:
        """Enter async context: initialize the database."""
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context: close the database."""
        await self.close()

    def _get_db(self) -> aiosqlite.Connection:
        """Return the active database connection or raise."""
        if self._db is None:
            msg = "ProxyLogger not initialized — call initialize() or use as async context manager"
            raise RuntimeError(msg)
        return self._db

    async def _maybe_commit(self) -> None:
        """Commit if enough inserts have accumulated since the last commit."""
        self._uncommitted += 1
        if self._uncommitted >= self._commit_every:
            await self._get_db().commit()
            self._uncommitted = 0

    async def log_message(
        self,
        direction: str,
        parsed_message: ParsedMessage,
    ) -> None:
        """Log a JSON-RPC message to the proxy_messages table.

        Args:
            direction: Either 'client_to_server' or 'server_to_client'.
            parsed_message: The parsed message to log.
        """
        import json

        from src.proxy.hasher import hash_content

        db = self._get_db()
        raw_str = parsed_message.raw.decode("utf-8", errors="replace")
        content_hash = hash_content(raw_str)
        message_json: str | None = None
        if parsed_message.parsed is not None:
            message_json = json.dumps(parsed_message.parsed, sort_keys=True)

        await db.execute(
            """INSERT INTO proxy_messages
               (session_id, timestamp, direction, message_type, method,
                message_json, content_hash, parse_error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                self.session_id,
                _now_iso(),
                direction,
                parsed_message.message_type,
                parsed_message.method,
                message_json,
                content_hash,
                1 if parsed_message.parse_error else 0,
            ),
        )
        await self._maybe_commit()

    async def log_tool_schema(
        self,
        tool_schema: ToolSchema,
        list_call_seq: int,
    ) -> None:
        """Log a tool schema to the proxy_tool_schemas table.

        Args:
            tool_schema: The extracted tool schema to log.
            list_call_seq: The sequence number of the tools/list call
                that produced this schema.
        """
        db = self._get_db()
        await db.execute(
            """INSERT INTO proxy_tool_schemas
               (session_id, timestamp, tool_name, description,
                description_hash, input_schema_json, input_schema_hash,
                list_call_sequence_number)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                self.session_id,
                _now_iso(),
                tool_schema.name,
                tool_schema.description,
                tool_schema.description_hash,
                tool_schema.input_schema_json,
                tool_schema.input_schema_hash,
                list_call_seq,
            ),
        )
        await self._maybe_commit()

    async def log_adapter_request(
        self,
        provider: str,
        model: str,
        translated_tools: str,
        request_json: str,
    ) -> None:
        """Log an LLM adapter request to the adapter_requests table.

        Args:
            provider: The LLM provider name (e.g. 'anthropic', 'openai').
            model: The model identifier.
            translated_tools: JSON string of the tool schemas as sent to the LLM.
            request_json: JSON string of the full request payload.
        """
        db = self._get_db()
        await db.execute(
            """INSERT INTO adapter_requests
               (session_id, timestamp, provider, model,
                translated_tools_json, request_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                self.session_id,
                _now_iso(),
                provider,
                model,
                translated_tools,
                request_json,
            ),
        )
        await self._maybe_commit()

    async def log_adapter_response(
        self,
        provider: str,
        model: str,
        response_json: str,
        tool_calls_json: str | None,
        classification: str | None,
        iteration_number: int | None = None,
    ) -> None:
        """Log an LLM adapter response to the adapter_responses table.

        Args:
            provider: The LLM provider name.
            model: The model identifier.
            response_json: JSON string of the full response payload.
            tool_calls_json: JSON string of extracted tool calls, or None.
            classification: Compliance classification label, or None.
            iteration_number: The agent loop iteration that produced this response.
        """
        db = self._get_db()
        await db.execute(
            """INSERT INTO adapter_responses
               (session_id, timestamp, provider, model,
                response_json, tool_calls_json, compliance_classification,
                iteration_number)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                self.session_id,
                _now_iso(),
                provider,
                model,
                response_json,
                tool_calls_json,
                classification,
                iteration_number,
            ),
        )
        await self._maybe_commit()
