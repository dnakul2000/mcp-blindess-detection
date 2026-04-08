"""Tests for the AgentLoop and AgentResult."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from src.client.agent import AgentLoop
from src.client.providers.base import LLMResponse, MCPToolSchema, ToolCall

if TYPE_CHECKING:
    from pathlib import Path


class MockProvider:
    """Mock LLM provider that returns pre-configured responses in sequence."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = iter(responses)

    @property
    def provider_name(self) -> str:
        return "mock"

    async def query(
        self,
        messages: list[dict[str, Any]],
        tools: list[MCPToolSchema],
        model: str,
    ) -> LLMResponse:
        return next(self._responses)


@pytest.fixture
def echo_cmd() -> list[str]:
    """Command to start the echo MCP server."""
    return ["uv", "run", "python", "-m", "src.servers.echo"]


async def test_agent_no_tool_calls(
    echo_cmd: list[str],
    tmp_db: Path,
) -> None:
    """LLM returns plain text with no tool calls — loop exits after 1 iteration."""
    provider = MockProvider(
        [
            LLMResponse(content="Hello"),
        ]
    )
    agent = AgentLoop(
        server_command=echo_cmd,
        provider=provider,
        model="test-model",
        max_iterations=5,
        db_path=str(tmp_db),
    )
    result = await agent.run("Say hello")

    assert result.final_response == "Hello"
    assert result.iterations == 1
    assert result.tool_calls_made == []


async def test_agent_executes_tool_call(
    echo_cmd: list[str],
    tmp_db: Path,
) -> None:
    """LLM requests one tool call, then returns final text on second iteration."""
    provider = MockProvider(
        [
            LLMResponse(
                content="Calling echo",
                tool_calls=[ToolCall(tool_name="echo", arguments={"message": "hi"})],
            ),
            LLMResponse(content="Done"),
        ]
    )
    agent = AgentLoop(
        server_command=echo_cmd,
        provider=provider,
        model="test-model",
        max_iterations=5,
        db_path=str(tmp_db),
    )
    result = await agent.run("Echo hi")

    assert result.final_response == "Done"
    assert result.iterations == 2
    assert len(result.tool_calls_made) == 1
    assert result.tool_calls_made[0].tool_name == "echo"
    assert result.tool_calls_made[0].arguments == {"message": "hi"}


async def test_agent_multi_turn(
    echo_cmd: list[str],
    tmp_db: Path,
) -> None:
    """LLM requests tool calls for 3 turns, then final text on the 4th."""
    provider = MockProvider(
        [
            LLMResponse(
                content="Turn 1",
                tool_calls=[ToolCall(tool_name="echo", arguments={"message": "a"})],
            ),
            LLMResponse(
                content="Turn 2",
                tool_calls=[ToolCall(tool_name="echo", arguments={"message": "b"})],
            ),
            LLMResponse(
                content="Turn 3",
                tool_calls=[ToolCall(tool_name="echo", arguments={"message": "c"})],
            ),
            LLMResponse(content="All done"),
        ]
    )
    agent = AgentLoop(
        server_command=echo_cmd,
        provider=provider,
        model="test-model",
        max_iterations=10,
        db_path=str(tmp_db),
    )
    result = await agent.run("Echo three times")

    assert result.final_response == "All done"
    assert result.iterations == 4
    assert len(result.tool_calls_made) == 3


async def test_agent_respects_max_iterations(
    echo_cmd: list[str],
    tmp_db: Path,
) -> None:
    """Loop stops at max_iterations even if the LLM keeps requesting tool calls."""
    # Provide more responses than max_iterations to ensure the cap is hit.
    provider = MockProvider(
        [
            LLMResponse(
                content=f"Turn {i}",
                tool_calls=[ToolCall(tool_name="echo", arguments={"message": str(i)})],
            )
            for i in range(10)
        ]
    )
    agent = AgentLoop(
        server_command=echo_cmd,
        provider=provider,
        model="test-model",
        max_iterations=3,
        db_path=str(tmp_db),
    )
    result = await agent.run("Keep echoing")

    assert result.iterations == 3
    assert "Max iterations" in result.final_response


async def test_agent_operator_log(
    echo_cmd: list[str],
    tmp_db: Path,
) -> None:
    """operator_log should contain entries describing tool calls made."""
    provider = MockProvider(
        [
            LLMResponse(
                content="Calling echo",
                tool_calls=[ToolCall(tool_name="echo", arguments={"message": "logged"})],
            ),
            LLMResponse(content="Done"),
        ]
    )
    agent = AgentLoop(
        server_command=echo_cmd,
        provider=provider,
        model="test-model",
        max_iterations=5,
        db_path=str(tmp_db),
    )
    result = await agent.run("Echo for logging")

    assert len(result.operator_log) == 1
    assert "echo" in result.operator_log[0]
    assert "logged" in result.operator_log[0]
