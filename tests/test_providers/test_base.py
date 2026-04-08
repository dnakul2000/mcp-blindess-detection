"""Tests for LLM provider base types."""

from __future__ import annotations

from typing import Any

from src.client.providers.base import LLMResponse, MCPToolSchema, ToolCall


class TestToolCallDataclass:
    """Verify ToolCall dataclass construction and field access."""

    def test_tool_call_dataclass(self) -> None:
        tc = ToolCall(tool_name="echo", arguments={"text": "hello"})
        assert tc.tool_name == "echo"
        assert tc.arguments == {"text": "hello"}


class TestLLMResponseDataclass:
    """Verify LLMResponse dataclass construction and field access."""

    def test_llm_response_dataclass(self) -> None:
        calls = [
            ToolCall(tool_name="echo", arguments={"text": "a"}),
            ToolCall(tool_name="add", arguments={"x": 1, "y": 2}),
        ]
        resp = LLMResponse(
            content="some text",
            tool_calls=calls,
            raw_request_json='{"model":"m"}',
            raw_response_json='{"ok":true}',
            translated_tools_json='[{"type":"function"}]',
        )
        assert resp.content == "some text"
        assert len(resp.tool_calls) == 2
        assert resp.tool_calls[0].tool_name == "echo"
        assert resp.tool_calls[1].arguments == {"x": 1, "y": 2}
        assert resp.raw_request_json == '{"model":"m"}'
        assert resp.raw_response_json == '{"ok":true}'
        assert resp.translated_tools_json == '[{"type":"function"}]'


class TestMCPToolSchemaDataclass:
    """Verify MCPToolSchema dataclass construction and field access."""

    def test_mcp_tool_schema_dataclass(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
        }
        tool = MCPToolSchema(
            name="echo",
            description="Echoes input",
            input_schema=schema,
        )
        assert tool.name == "echo"
        assert tool.description == "Echoes input"
        assert tool.input_schema["type"] == "object"
        assert "text" in tool.input_schema["properties"]
