"""OpenAI-compatible LLM provider adapter.

Works with OpenAI, OpenRouter, and any API that implements the
OpenAI chat completions interface.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from src.client.providers.base import LLMResponse, MCPToolSchema, ToolCall


class OpenAICompatAdapter:
    """Adapter for OpenAI-compatible chat completion APIs.

    Translates MCP tool schemas to OpenAI's function-calling format and
    sends requests to the /chat/completions endpoint.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        provider_name_override: str = "openai",
    ) -> None:
        """Initialise the OpenAI-compatible adapter.

        Args:
            base_url: Base URL of the API (e.g. https://api.openai.com/v1).
            api_key: API key for authentication.
            provider_name_override: Name to use for logging and identification.
        """
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._provider_name = provider_name_override

    @property
    def provider_name(self) -> str:
        """Return the canonical provider name."""
        return self._provider_name

    @staticmethod
    def translate_tools(tools: list[MCPToolSchema]) -> list[dict[str, Any]]:
        """Convert MCP tool schemas to OpenAI function-calling format.

        Args:
            tools: MCP tool schemas from tools/list.

        Returns:
            List of tool definitions in OpenAI's expected format.
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

    def _redact_request_json(self, payload: dict[str, Any]) -> str:
        """Serialise request payload with the API key redacted.

        Args:
            payload: The request payload dictionary.

        Returns:
            JSON string with Authorization header value replaced.
        """
        dump = json.dumps(payload, indent=2)
        return re.sub(
            re.escape(self._api_key),
            "REDACTED",
            dump,
        )

    async def query(
        self,
        messages: list[dict[str, Any]],
        tools: list[MCPToolSchema],
        model: str,
    ) -> LLMResponse:
        """Send a chat completion request to an OpenAI-compatible API.

        Args:
            messages: Conversation messages.
            tools: MCP tool schemas to make available.
            model: The model identifier.

        Returns:
            Structured response with parsed tool calls and raw JSON.
        """
        translated = self.translate_tools(tools)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": translated,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        request_json = self._redact_request_json(payload)
        translated_json = json.dumps(translated, indent=2)

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()

        response_data = resp.json()
        response_json = json.dumps(response_data, indent=2)

        message = response_data["choices"][0]["message"]
        content = message.get("content", "") or ""
        raw_tool_calls = message.get("tool_calls", []) or []
        tool_calls = [
            ToolCall(
                tool_name=tc["function"]["name"],
                arguments=json.loads(tc["function"]["arguments"]),
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
