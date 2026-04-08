"""Unit tests for TransparentProxy covering the source code directly.

The integration tests in test_proxy.py and test_proxy_transparency.py run
the proxy in a subprocess, so coverage is not tracked. These tests import
and exercise the proxy class directly with mocked subprocesses.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.proxy.proxy import TransparentProxy


def test_proxy_init(tmp_path: Path) -> None:
    proxy = TransparentProxy(upstream_command=["echo"], db_path=tmp_path / "test.db")
    assert proxy._upstream_command == ["echo"]
    assert proxy._db_path == tmp_path / "test.db"
    assert proxy._list_call_seq == 0
    assert proxy._shutting_down is False


def test_proxy_init_string_db() -> None:
    proxy = TransparentProxy(upstream_command=["echo"], db_path="test.db")
    assert proxy._db_path == Path("test.db")


def test_request_shutdown() -> None:
    proxy = TransparentProxy(upstream_command=["echo"])
    proxy._shutting_down = False

    with patch("src.proxy.proxy.asyncio") as mock_asyncio:
        mock_task1 = MagicMock()
        mock_task2 = MagicMock()
        mock_asyncio.all_tasks.return_value = [mock_task1, mock_task2]
        proxy._request_shutdown()

    assert proxy._shutting_down is True
    mock_task1.cancel.assert_called_once()
    mock_task2.cancel.assert_called_once()


def test_request_shutdown_idempotent() -> None:
    proxy = TransparentProxy(upstream_command=["echo"])
    proxy._shutting_down = True

    with patch("src.proxy.proxy.asyncio") as mock_asyncio:
        proxy._request_shutdown()
        mock_asyncio.all_tasks.assert_not_called()


async def test_cleanup_running_process() -> None:
    proxy = TransparentProxy(upstream_command=["echo"])
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.terminate = MagicMock()
    mock_proc.wait = AsyncMock()
    proxy._process = mock_proc

    await proxy._cleanup()
    mock_proc.terminate.assert_called_once()


async def test_cleanup_already_exited() -> None:
    proxy = TransparentProxy(upstream_command=["echo"])
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    proxy._process = mock_proc

    await proxy._cleanup()
    mock_proc.terminate.assert_not_called()


async def test_cleanup_kill_on_timeout() -> None:
    proxy = TransparentProxy(upstream_command=["echo"])
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()

    async def slow_wait() -> None:
        await asyncio.sleep(100)

    mock_proc.wait = slow_wait
    proxy._process = mock_proc

    await proxy._cleanup()
    mock_proc.kill.assert_called_once()


async def test_cleanup_no_process() -> None:
    proxy = TransparentProxy(upstream_command=["echo"])
    proxy._process = None
    await proxy._cleanup()  # Should not raise.


async def test_pipe_client_to_server(tmp_path: Path) -> None:
    """Test client-to-server piping with a mock reader."""
    proxy = TransparentProxy(upstream_command=["echo"], db_path=tmp_path / "test.db")

    # Create mock stdin writer.
    mock_stdin = MagicMock()
    mock_stdin.write = MagicMock()
    mock_stdin.drain = AsyncMock()
    mock_stdin.close = MagicMock()

    mock_proc = MagicMock()
    mock_proc.stdin = mock_stdin
    proxy._process = mock_proc

    mock_logger = AsyncMock()
    proxy._logger = mock_logger

    # Create a reader that returns one message then EOF.
    msg = json.dumps({"jsonrpc": "2.0", "method": "tools/list", "id": 1}).encode() + b"\n"

    # Mock the entire stdin reading pipeline.
    with (
        patch("src.proxy.proxy.asyncio.StreamReader") as MockReader,
        patch("src.proxy.proxy.asyncio.StreamReaderProtocol"),
        patch("src.proxy.proxy.asyncio.get_running_loop") as mock_loop,
    ):
        reader = AsyncMock()
        reader.readline = AsyncMock(side_effect=[msg, b""])
        MockReader.return_value = reader
        mock_loop.return_value.connect_read_pipe = AsyncMock()

        await proxy._pipe_client_to_server()

    mock_logger.log_message.assert_called()
    mock_stdin.write.assert_called_once_with(msg)
    assert proxy._list_call_seq == 1


async def test_pipe_server_to_client(tmp_path: Path) -> None:
    """Test server-to-client piping."""
    proxy = TransparentProxy(upstream_command=["echo"], db_path=tmp_path / "test.db")

    # Tools/list response with tools.
    response = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo",
                            "inputSchema": {"type": "object", "properties": {}},
                        }
                    ]
                },
            }
        ).encode()
        + b"\n"
    )

    mock_stdout = AsyncMock()
    mock_stdout.readline = AsyncMock(side_effect=[response, b""])

    mock_proc = MagicMock()
    mock_proc.stdout = mock_stdout
    proxy._process = mock_proc

    mock_logger = AsyncMock()
    proxy._logger = mock_logger

    # Set up pending list IDs so the schema extraction fires.
    proxy._list_call_seq = 1
    proxy._pending_list_ids = {1}

    with patch("src.proxy.proxy.sys") as mock_sys:
        mock_buffer = MagicMock()
        mock_sys.stdout.buffer = mock_buffer

        await proxy._pipe_server_to_client()

    mock_logger.log_message.assert_called()
    mock_logger.log_tool_schema.assert_called()
    mock_buffer.write.assert_called_once()


async def test_forward_stderr() -> None:
    proxy = TransparentProxy(upstream_command=["echo"])

    mock_stderr = AsyncMock()
    mock_stderr.readline = AsyncMock(side_effect=[b"error message\n", b""])

    mock_proc = MagicMock()
    mock_proc.stderr = mock_stderr
    proxy._process = mock_proc

    with patch("src.proxy.proxy.sys") as mock_sys:
        mock_buffer = MagicMock()
        mock_sys.stderr.buffer = mock_buffer
        await proxy._forward_stderr()

    mock_buffer.write.assert_called_once_with(b"error message\n")


async def test_run_lifecycle(tmp_path: Path) -> None:
    """Test the full run() method with mocked subprocess."""
    proxy = TransparentProxy(upstream_command=["echo"], db_path=tmp_path / "test.db")

    mock_stdin = MagicMock()
    mock_stdin.write = MagicMock()
    mock_stdin.drain = AsyncMock()
    mock_stdin.close = MagicMock()

    mock_stdout = AsyncMock()
    mock_stdout.readline = AsyncMock(return_value=b"")

    mock_stderr = AsyncMock()
    mock_stderr.readline = AsyncMock(return_value=b"")

    mock_proc = MagicMock()
    mock_proc.stdin = mock_stdin
    mock_proc.stdout = mock_stdout
    mock_proc.stderr = mock_stderr
    mock_proc.returncode = 0
    mock_proc.wait = AsyncMock()

    with (
        patch("src.proxy.proxy.asyncio.get_running_loop") as mock_loop,
        patch(
            "src.proxy.proxy.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ),
        patch("src.proxy.proxy.asyncio.StreamReader") as MockReader,
        patch("src.proxy.proxy.asyncio.StreamReaderProtocol"),
    ):
        reader = AsyncMock()
        reader.readline = AsyncMock(return_value=b"")
        MockReader.return_value = reader

        mock_loop_instance = MagicMock()
        mock_loop_instance.add_signal_handler = MagicMock()
        mock_loop_instance.connect_read_pipe = AsyncMock()
        mock_loop.return_value = mock_loop_instance

        await proxy.run()

    # Verify signal handlers were set up.
    assert mock_loop_instance.add_signal_handler.call_count == 2


async def test_run_reraises_non_cancelled_error(tmp_path: Path) -> None:
    """Lines 71-73: exceptions from gather results are re-raised."""
    proxy = TransparentProxy(upstream_command=["echo"], db_path=tmp_path / "test.db")

    mock_stdin = MagicMock()
    mock_stdin.close = MagicMock()
    mock_stdout = AsyncMock()
    mock_stderr = AsyncMock()

    mock_proc = MagicMock()
    mock_proc.stdin = mock_stdin
    mock_proc.stdout = mock_stdout
    mock_proc.stderr = mock_stderr
    mock_proc.returncode = 0
    mock_proc.wait = AsyncMock()

    async def failing_pipe() -> None:
        msg = "pipe failed"
        raise RuntimeError(msg)

    with (
        patch("src.proxy.proxy.asyncio.get_running_loop") as mock_loop,
        patch(
            "src.proxy.proxy.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ),
        patch(
            "src.proxy.proxy.asyncio.gather",
            new_callable=AsyncMock,
            return_value=[RuntimeError("pipe failed"), None, None],
        ),
    ):
        mock_loop_instance = MagicMock()
        mock_loop_instance.add_signal_handler = MagicMock()
        mock_loop.return_value = mock_loop_instance

        with pytest.raises(RuntimeError, match="pipe failed"):
            await proxy.run()


async def test_run_handles_cancelled_error(tmp_path: Path) -> None:
    """Line 72-73: CancelledError is caught and ignored."""
    proxy = TransparentProxy(upstream_command=["echo"], db_path=tmp_path / "test.db")

    mock_proc = MagicMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdout = AsyncMock()
    mock_proc.stderr = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.wait = AsyncMock()

    with (
        patch("src.proxy.proxy.asyncio.get_running_loop") as mock_loop,
        patch(
            "src.proxy.proxy.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ),
        patch(
            "src.proxy.proxy.asyncio.gather",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError,
        ),
    ):
        mock_loop_instance = MagicMock()
        mock_loop_instance.add_signal_handler = MagicMock()
        mock_loop.return_value = mock_loop_instance

        # Should not raise.
        await proxy.run()
