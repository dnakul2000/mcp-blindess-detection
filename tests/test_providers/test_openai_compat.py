"""Tests for the OpenAI-compatible LLM provider adapter."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.client.providers.base import MCPToolSchema
from src.client.providers.openai_compat import OpenAICompatAdapter

API_KEY = "sk-test-secret-key-12345"
BASE_URL = "https://api.openai.com/v1"


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
        "src.client.providers.openai_compat.httpx.AsyncClient",
    )
    return patcher, mock_client


class TestTranslateTools:
    def test_translate_tools(self) -> None:
        tools = _make_tools()
        translated = OpenAICompatAdapter.translate_tools(tools)
        assert len(translated) == 1
        t = translated[0]
        assert t["type"] == "function"
        assert t["function"]["name"] == "echo"
        assert t["function"]["description"] == "Echoes input"
        assert t["function"]["parameters"]["type"] == "object"


class TestQueryWithToolCalls:
    @pytest.mark.asyncio
    async def test_query_with_tool_calls(self) -> None:
        response_data = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "echo",
                                    "arguments": json.dumps(
                                        {"text": "hello"},
                                    ),
                                },
                            },
                        ],
                    },
                },
            ],
        }
        patcher, mock_client = _mock_httpx(response_data)
        with patcher as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            adapter = OpenAICompatAdapter(
                base_url=BASE_URL,
                api_key=API_KEY,
            )
            result = await adapter.query(
                _make_messages(),
                _make_tools(),
                "gpt-4",
            )

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "echo"
        assert result.tool_calls[0].arguments == {"text": "hello"}


class TestQueryWithoutToolCalls:
    @pytest.mark.asyncio
    async def test_query_without_tool_calls(self) -> None:
        response_data = {
            "choices": [
                {
                    "message": {
                        "content": "I cannot do that.",
                        "tool_calls": None,
                    },
                },
            ],
        }
        patcher, mock_client = _mock_httpx(response_data)
        with patcher as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            adapter = OpenAICompatAdapter(
                base_url=BASE_URL,
                api_key=API_KEY,
            )
            result = await adapter.query(
                _make_messages(),
                _make_tools(),
                "gpt-4",
            )

        assert result.tool_calls == []
        assert result.content == "I cannot do that."


class TestApiKeyRedacted:
    @pytest.mark.asyncio
    async def test_api_key_redacted(self) -> None:
        response_data = {
            "choices": [
                {"message": {"content": "ok", "tool_calls": None}},
            ],
        }
        patcher, mock_client = _mock_httpx(response_data)
        with patcher as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            adapter = OpenAICompatAdapter(
                base_url=BASE_URL,
                api_key=API_KEY,
            )
            result = await adapter.query(
                _make_messages(),
                _make_tools(),
                "gpt-4",
            )

        assert API_KEY not in result.raw_request_json
        assert "REDACTED" in result.raw_request_json or API_KEY not in result.raw_request_json


class TestConfigurableBaseUrl:
    @pytest.mark.asyncio
    async def test_configurable_base_url(self) -> None:
        custom_url = "https://openrouter.ai/api/v1"
        response_data = {
            "choices": [
                {"message": {"content": "ok", "tool_calls": None}},
            ],
        }
        patcher, mock_client = _mock_httpx(response_data)
        with patcher as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            adapter = OpenAICompatAdapter(
                base_url=custom_url,
                api_key=API_KEY,
                provider_name_override="openrouter",
            )
            await adapter.query(
                _make_messages(),
                _make_tools(),
                "gpt-4",
            )

        call_args = mock_client.post.call_args
        url_called = call_args[0][0]
        assert url_called.startswith(custom_url.rstrip("/"))
        assert "/chat/completions" in url_called
