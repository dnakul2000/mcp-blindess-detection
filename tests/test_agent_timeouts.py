"""Tests for AgentLoop timeout paths."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.client.agent import AgentLoop
from src.client.providers.base import LLMResponse, MCPToolSchema, ToolCall


class SlowProvider:
    """Provider that sleeps before responding."""

    def __init__(self, sleep_seconds: float) -> None:
        self._sleep = sleep_seconds

    @property
    def provider_name(self) -> str:
        return "slow"

    async def query(
        self,
        messages: list[dict[str, Any]],
        tools: list[MCPToolSchema],
        model: str,
    ) -> LLMResponse:
        await asyncio.sleep(self._sleep)
        return LLMResponse(content="finally")


class TimeoutProvider:
    """Provider whose query always raises TimeoutError."""

    @property
    def provider_name(self) -> str:
        return "timeout"

    async def query(
        self,
        messages: list[dict[str, Any]],
        tools: list[MCPToolSchema],
        model: str,
    ) -> LLMResponse:
        raise TimeoutError


class ToolCallProvider:
    """Provider that returns tool calls targeting a nonexistent tool to test tool timeout."""

    def __init__(self) -> None:
        self._called = False

    @property
    def provider_name(self) -> str:
        return "toolcall"

    async def query(
        self,
        messages: list[dict[str, Any]],
        tools: list[MCPToolSchema],
        model: str,
    ) -> LLMResponse:
        if not self._called:
            self._called = True
            return LLMResponse(
                content="calling tool",
                tool_calls=[ToolCall(tool_name="echo", arguments={"message": "test"})],
            )
        return LLMResponse(content="done")


@pytest.fixture
def echo_cmd() -> list[str]:
    return ["uv", "run", "python", "-m", "src.servers.echo"]


async def test_agent_query_timeout(echo_cmd: list[str], tmp_db: pytest.TempPathFactory) -> None:
    """Lines 203-208: LLM query timeout."""
    provider = SlowProvider(sleep_seconds=10)
    agent = AgentLoop(
        server_command=echo_cmd,
        provider=provider,
        model="test",
        max_iterations=10,
        max_seconds=120,
        query_timeout=0.1,  # Very short query timeout.
        db_path=str(tmp_db),
    )
    result = await agent.run("hello")
    assert result.timed_out is True
    assert "timeout" in result.final_response.lower()


async def test_agent_tool_call_execution(
    echo_cmd: list[str], tmp_db: pytest.TempPathFactory
) -> None:
    """Test tool call execution with a real server."""
    provider = ToolCallProvider()
    agent = AgentLoop(
        server_command=echo_cmd,
        provider=provider,
        model="test",
        max_iterations=5,
        max_seconds=30,
        query_timeout=10,
        tool_timeout=10,
        db_path=str(tmp_db),
    )
    result = await agent.run("test tool call")
    assert result.iterations >= 1
    assert result.final_response == "done"
