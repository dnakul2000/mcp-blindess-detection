"""Google Gemini LLM provider adapter."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from src.client.providers.base import LLMResponse, MCPToolSchema, ToolCall


class GoogleAdapter:
    """Adapter for the Google Gemini generativeai API.

    Translates MCP tool schemas to Gemini's function_declarations format
    and sends requests to the generateContent endpoint.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
    ) -> None:
        """Initialise the Google Gemini adapter.

        Args:
            api_key: Google API key.
            base_url: Base URL of the Gemini API.
        """
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    @property
    def provider_name(self) -> str:
        """Return the canonical provider name."""
        return "google"

    @staticmethod
    def translate_tools(
        tools: list[MCPToolSchema],
    ) -> list[dict[str, Any]]:
        """Convert MCP tool schemas to Gemini function_declarations format.

        Args:
            tools: MCP tool schemas from tools/list.

        Returns:
            List containing a single tools object with function_declarations.
        """
        return [
            {
                "function_declarations": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    }
                    for t in tools
                ],
            },
        ]

    def _redact_json(self, data: str) -> str:
        """Remove the API key from a JSON string.

        Args:
            data: JSON string that may contain the API key.

        Returns:
            JSON string with API key occurrences replaced.
        """
        return re.sub(re.escape(self._api_key), "REDACTED", data)

    @staticmethod
    def _convert_messages(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Convert generic messages to Gemini contents format.

        Gemini expects role ('user' or 'model') and parts with text.

        Args:
            messages: Provider-agnostic messages.

        Returns:
            Messages formatted for the Gemini API.
        """
        converted: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            gemini_role = "model" if role == "assistant" else "user"
            content = msg.get("content", "")
            converted.append(
                {
                    "role": gemini_role,
                    "parts": [{"text": content}],
                },
            )
        return converted

    async def query(
        self,
        messages: list[dict[str, Any]],
        tools: list[MCPToolSchema],
        model: str,
    ) -> LLMResponse:
        """Send a generateContent request to the Gemini API.

        Args:
            messages: Conversation messages.
            tools: MCP tool schemas to make available.
            model: The Gemini model identifier.

        Returns:
            Structured response with parsed tool calls and raw JSON.
        """
        translated = self.translate_tools(tools)
        contents = self._convert_messages(messages)
        payload: dict[str, Any] = {
            "contents": contents,
            "tools": translated,
        }

        url = f"{self._base_url}/models/{model}:generateContent?key={self._api_key}"

        request_json = self._redact_json(json.dumps(payload, indent=2))
        translated_json = json.dumps(translated, indent=2)

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()

        response_data = resp.json()
        response_json = self._redact_json(json.dumps(response_data, indent=2))

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        candidates = response_data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            for part in parts:
                if "text" in part:
                    text_parts.append(part["text"])
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    tool_calls.append(
                        ToolCall(
                            tool_name=fc["name"],
                            arguments=fc.get("args", {}),
                        ),
                    )

        return LLMResponse(
            content="\n".join(text_parts),
            tool_calls=tool_calls,
            raw_request_json=request_json,
            raw_response_json=response_json,
            translated_tools_json=translated_json,
        )
