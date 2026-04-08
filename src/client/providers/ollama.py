"""Ollama LLM provider adapter."""

from __future__ import annotations

import json
from typing import Any

import httpx

from src.client.providers.base import LLMResponse, MCPToolSchema, ToolCall


class OllamaAdapter:
    """Adapter for the Ollama local inference API.

    Translates MCP tool schemas to Ollama's function-calling format and
    sends chat completion requests via the /api/chat endpoint.
    """

    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        """Initialise the Ollama adapter.

        Args:
            base_url: Base URL of the Ollama API server.
        """
        self._base_url = base_url.rstrip("/")

    @property
    def provider_name(self) -> str:
        """Return the canonical provider name."""
        return "ollama"

    @staticmethod
    def translate_tools(tools: list[MCPToolSchema]) -> list[dict[str, Any]]:
        """Convert MCP tool schemas to Ollama function-calling format.

        Args:
            tools: MCP tool schemas from tools/list.

        Returns:
            List of tool definitions in Ollama's expected format.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]

    async def query(
        self,
        messages: list[dict[str, Any]],
        tools: list[MCPToolSchema],
        model: str,
    ) -> LLMResponse:
        """Send a chat completion request to Ollama.

        Args:
            messages: Conversation messages.
            tools: MCP tool schemas to make available.
            model: The Ollama model identifier.

        Returns:
            Structured response with parsed tool calls and raw JSON.
        """
        translated = self.translate_tools(tools)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": translated,
            "stream": False,
        }
        request_json = json.dumps(payload, indent=2)
        translated_json = json.dumps(translated, indent=2)

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self._base_url}/api/chat",
                json=payload,
            )
            resp.raise_for_status()

        response_data = resp.json()
        response_json = json.dumps(response_data, indent=2)

        content = response_data.get("message", {}).get("content", "")
        raw_tool_calls = response_data.get("message", {}).get("tool_calls", [])
        tool_calls = [
            ToolCall(
                tool_name=tc["function"]["name"],
                arguments=tc["function"].get("arguments", {}),
            )
            for tc in raw_tool_calls
        ]

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            raw_request_json=request_json,
            raw_response_json=response_json,
            translated_tools_json=translated_json,
        )
