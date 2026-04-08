"""Protocol and base types for LLM provider adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolCall:
    """A single tool invocation extracted from an LLM response.

    Attributes:
        tool_name: The name of the tool to call.
        arguments: The arguments to pass to the tool.
    """

    tool_name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Structured response from an LLM provider.

    Attributes:
        content: Text content from the LLM response.
        tool_calls: Tool invocations requested by the LLM.
        raw_request_json: The raw JSON request sent to the provider.
        raw_response_json: The raw JSON response from the provider.
        translated_tools_json: The tool schemas as translated for this provider.
    """

    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_request_json: str = ""
    raw_response_json: str = ""
    translated_tools_json: str = ""


@dataclass
class MCPToolSchema:
    """An MCP tool schema as returned by tools/list.

    Attributes:
        name: The tool name.
        description: Human-readable description of the tool.
        input_schema: JSON Schema describing the tool's input parameters.
    """

    name: str
    description: str
    input_schema: dict[str, Any]


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM provider adapters.

    Each adapter translates MCP tool schemas into the provider's native
    format, sends queries, and returns structured responses with raw
    request/response JSON for logging.
    """

    @property
    def provider_name(self) -> str:
        """Return the canonical name of this provider."""
        ...

    async def query(
        self,
        messages: list[dict[str, Any]],
        tools: list[MCPToolSchema],
        model: str,
    ) -> LLMResponse:
        """Send a query to the LLM provider.

        Args:
            messages: Conversation messages in provider-agnostic format.
            tools: MCP tool schemas to make available to the model.
            model: The model identifier to use.

        Returns:
            Structured response including tool calls and raw JSON logs.
        """
        ...
