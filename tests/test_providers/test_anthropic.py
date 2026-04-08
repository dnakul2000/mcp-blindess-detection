"""Tests for the Anthropic LLM provider adapter."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.client.providers.anthropic import AnthropicAdapter
from src.client.providers.base import MCPToolSchema

API_KEY = "sk-ant-test-secret-key-12345"


def _make_tools() -> list[MCPToolSchema]:
    return [
        MCPToolSchema(
            name="echo",
            description="Echoes input",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
            },
        ),
    ]


def _make_messages() -> list[dict[str, Any]]:
    return [{"role": "user", "content": "Call echo with hello"}]


def _mock_httpx(
    response_data: dict[str, Any],
) -> tuple[Any, AsyncMock]:
    mock_response = MagicMock()
    mock_response.json.return_value = response_data
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    patcher = patch(
        "src.client.providers.anthropic.httpx.AsyncClient",
    )
    return patcher, mock_client


class TestTranslateTools:
    def test_translate_tools(self) -> None:
        tools = _make_tools()
        translated = AnthropicAdapter.translate_tools(tools)
        assert len(translated) == 1
        t = translated[0]
        assert t["name"] == "echo"
        assert t["description"] == "Echoes input"
        assert t["input_schema"]["type"] == "object"
        assert "text" in t["input_schema"]["properties"]


class TestQueryWithToolUse:
    @pytest.mark.asyncio
    async def test_query_with_tool_use(self) -> None:
        response_data = {
            "content": [
                {"type": "text", "text": "I will call echo."},
                {
                    "type": "tool_use",
                    "name": "echo",
                    "input": {"text": "hello"},
                },
            ],
        }
        patcher, mock_client = _mock_httpx(response_data)
        with patcher as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            adapter = AnthropicAdapter(api_key=API_KEY)
            result = await adapter.query(
                _make_messages(),
                _make_tools(),
                "claude-opus-4-20250514",
            )

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "echo"
        assert result.tool_calls[0].arguments == {"text": "hello"}
        assert "I will call echo." in result.content


class TestQueryTextOnly:
    @pytest.mark.asyncio
    async def test_query_text_only(self) -> None:
        response_data = {
            "content": [
                {"type": "text", "text": "First part."},
                {"type": "text", "text": "Second part."},
            ],
        }
        patcher, mock_client = _mock_httpx(response_data)
        with patcher as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            adapter = AnthropicAdapter(api_key=API_KEY)
            result = await adapter.query(
                _make_messages(),
                _make_tools(),
                "claude-opus-4-20250514",
            )

        assert result.tool_calls == []
        assert "First part." in result.content
        assert "Second part." in result.content


class TestApiKeyRedacted:
    @pytest.mark.asyncio
    async def test_api_key_redacted(self) -> None:
        response_data = {
            "content": [{"type": "text", "text": "ok"}],
        }
        patcher, mock_client = _mock_httpx(response_data)
        with patcher as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            adapter = AnthropicAdapter(api_key=API_KEY)
            result = await adapter.query(
                _make_messages(),
                _make_tools(),
                "claude-opus-4-20250514",
            )

        assert API_KEY not in result.raw_request_json
        assert API_KEY not in result.raw_response_json
