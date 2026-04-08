"""Transparent MCP proxy core — bidirectional stdio relay with logging."""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

from src.proxy.logger import ProxyLogger
from src.proxy.parser import extract_tool_schemas, parse_jsonrpc


class TransparentProxy:
    """Transparent stdio proxy between an MCP client and an upstream MCP server.

    Relays every JSON-RPC message byte-for-byte while logging all traffic
    and extracted tool schemas to SQLite. MUST NOT modify any message content.

    Args:
        upstream_command: Command and arguments to spawn the upstream MCP server.
        db_path: Path to the SQLite database for logging.
    """

    def __init__(
        self,
        upstream_command: list[str],
        db_path: str | Path = "experiment.db",
    ) -> None:
        self._upstream_command = upstream_command
        self._db_path = Path(db_path)
        self._list_call_seq: int = 0
        self._pending_list_ids: set[int | str] = set()
        self._logger: ProxyLogger | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._shutting_down: bool = False

    async def run(self) -> None:
        """Start the proxy: spawn upstream server and relay traffic.

        Sets up signal handlers, creates the logger and upstream process,
        then runs bidirectional piping until either side closes or a
        signal is received.
        """
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._request_shutdown)

        async with ProxyLogger(self._db_path) as logger:
            self._logger = logger

            self._process = await asyncio.create_subprocess_exec(
                *self._upstream_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                results = await asyncio.gather(
                    self._pipe_client_to_server(),
                    self._pipe_server_to_client(),
                    self._forward_stderr(),
                    return_exceptions=True,
                )
                for result in results:
                    if isinstance(result, Exception) and not isinstance(
                        result,
                        asyncio.CancelledError,
                    ):
                        raise result
            except asyncio.CancelledError:
                pass
            finally:
                await self._cleanup()

    def _request_shutdown(self) -> None:
        """Signal handler: request a clean shutdown."""
        if not self._shutting_down:
            self._shutting_down = True
            for task in asyncio.all_tasks():
                task.cancel()

    async def _cleanup(self) -> None:
        """Terminate the upstream process if still running."""
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except TimeoutError:
                self._process.kill()
                await self._process.wait()

    async def _pipe_client_to_server(self) -> None:
        """Read from local stdin, log, and forward to upstream stdin.

        Tracks tools/list requests to assign sequence numbers to
        corresponding responses.
        """
        assert self._process is not None
        assert self._process.stdin is not None
        assert self._logger is not None

        # 1 MiB buffer limit provides application-level backpressure.
        # OS-level drain() on the write path adds additional flow control.
        reader = asyncio.StreamReader(limit=2**20)
        protocol = asyncio.StreamReaderProtocol(reader)
        loop = asyncio.get_running_loop()
        await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)

        while not self._shutting_down:
            line = await reader.readline()
            if not line:
                # EOF from client — close upstream stdin to signal completion.
                self._process.stdin.close()
                break

            parsed = parse_jsonrpc(line)
            await self._logger.log_message("client_to_server", parsed)

            # Track tools/list requests for sequence numbering.
            if parsed.method == "tools/list" and parsed.msg_id is not None:
                self._list_call_seq += 1
                self._pending_list_ids.add(parsed.msg_id)

            self._process.stdin.write(line)
            await self._process.stdin.drain()

    async def _pipe_server_to_client(self) -> None:
        """Read from upstream stdout, log, extract schemas, forward to client.

        When a tools/list response is detected, tool schemas are extracted
        and logged with the appropriate sequence number.
        """
        assert self._process is not None
        assert self._process.stdout is not None
        assert self._logger is not None

        while not self._shutting_down:
            line = await self._process.stdout.readline()
            if not line:
                break

            parsed = parse_jsonrpc(line)
            await self._logger.log_message("server_to_client", parsed)

            # Detect tools/list responses and extract schemas.
            if (
                parsed.parsed is not None
                and parsed.msg_id is not None
                and parsed.msg_id in self._pending_list_ids
            ):
                self._pending_list_ids.discard(parsed.msg_id)
                schemas = extract_tool_schemas(parsed.parsed)
                for schema in schemas:
                    await self._logger.log_tool_schema(
                        schema,
                        self._list_call_seq,
                    )

            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()

    async def _forward_stderr(self) -> None:
        """Forward upstream stderr to local stderr."""
        assert self._process is not None
        assert self._process.stderr is not None

        while not self._shutting_down:
            line = await self._process.stderr.readline()
            if not line:
                break
            sys.stderr.buffer.write(line)
            sys.stderr.buffer.flush()
