"""Anthropic LLM provider adapter."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from src.client.providers.base import LLMResponse, MCPToolSchema, ToolCall


class AnthropicAdapter:
    """Adapter for the Anthropic Messages API.

    Translates MCP tool schemas to Anthropic's native tool format and
    sends requests to the /messages endpoint.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.anthropic.com/v1",
    ) -> None:
        """Initialise the Anthropic adapter.

        Args:
            api_key: Anthropic API key.
            base_url: Base URL of the Anthropic API.
        """
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    @property
    def provider_name(self) -> str:
        """Return the canonical provider name."""
        return "anthropic"

    @staticmethod
    def translate_tools(tools: list[MCPToolSchema]) -> list[dict[str, Any]]:
        """Convert MCP tool schemas to Anthropic tool format.

        Args:
            tools: MCP tool schemas from tools/list.

        Returns:
            List of tool definitions in Anthropic's expected format.
        """
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]

    def _redact_json(self, payload: dict[str, Any]) -> str:
        """Serialise payload with the API key redacted.

        Args:
            payload: The payload dictionary.

        Returns:
            JSON string with API key occurrences replaced.
        """
        dump = json.dumps(payload, indent=2)
        return re.sub(re.escape(self._api_key), "REDACTED", dump)

    @staticmethod
    def _convert_messages(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Convert generic messages to Anthropic message format.

        Anthropic expects role ('user' or 'assistant') and content
        (string or list of content blocks).

        Args:
            messages: Provider-agnostic messages.

        Returns:
            Messages formatted for the Anthropic API.
        """
        converted: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            if role == "system":
                continue
            content = msg.get("content", "")
            converted.append({"role": role, "content": content})
        return converted

    async def query(
        self,
        messages: list[dict[str, Any]],
        tools: list[MCPToolSchema],
        model: str,
    ) -> LLMResponse:
        """Send a message request to the Anthropic API.

        Args:
            messages: Conversation messages.
            tools: MCP tool schemas to make available.
            model: The Anthropic model identifier.

        Returns:
            Structured response with parsed tool calls and raw JSON.
        """
        translated = self.translate_tools(tools)
        anthropic_messages = self._convert_messages(messages)
        payload: dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "tools": translated,
            "max_tokens": 4096,
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        request_json = self._redact_json(payload)
        translated_json = json.dumps(translated, indent=2)

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self._base_url}/messages",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()

        response_data = resp.json()
        response_json = json.dumps(response_data, indent=2)

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response_data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(
                        tool_name=block["name"],
                        arguments=block.get("input", {}),
                    ),
                )

        return LLMResponse(
            content="\n".join(text_parts),
            tool_calls=tool_calls,
            raw_request_json=request_json,
            raw_response_json=response_json,
            translated_tools_json=translated_json,
        )
