"""Tests for the Google Gemini LLM provider adapter."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.client.providers.base import MCPToolSchema
from src.client.providers.google import GoogleAdapter

API_KEY = "AIzaSy-test-secret-key-12345"


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

    patcher = patch("src.client.providers.google.httpx.AsyncClient")
    return patcher, mock_client


class TestTranslateTools:
    def test_translate_tools(self) -> None:
        tools = _make_tools()
        translated = GoogleAdapter.translate_tools(tools)
        assert len(translated) == 1
        decls = translated[0]["function_declarations"]
        assert len(decls) == 1
        assert decls[0]["name"] == "echo"
        assert decls[0]["description"] == "Echoes input"
        assert decls[0]["parameters"]["type"] == "object"


class TestQueryWithFunctionCall:
    @pytest.mark.asyncio
    async def test_query_with_function_call(self) -> None:
        response_data = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "echo",
                                    "args": {"text": "hello"},
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

            adapter = GoogleAdapter(api_key=API_KEY)
            result = await adapter.query(
                _make_messages(),
                _make_tools(),
                "gemini-pro",
            )

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "echo"
        assert result.tool_calls[0].arguments == {"text": "hello"}


class TestQueryTextOnly:
    @pytest.mark.asyncio
    async def test_query_text_only(self) -> None:
        response_data = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Here is the result."},
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

            adapter = GoogleAdapter(api_key=API_KEY)
            result = await adapter.query(
                _make_messages(),
                _make_tools(),
                "gemini-pro",
            )

        assert result.tool_calls == []
        assert "Here is the result." in result.content


class TestApiKeyRedacted:
    @pytest.mark.asyncio
    async def test_api_key_redacted(self) -> None:
        response_data = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "ok"}],
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

            adapter = GoogleAdapter(api_key=API_KEY)
            result = await adapter.query(
                _make_messages(),
                _make_tools(),
                "gemini-pro",
            )

        # The API key appears in the URL, so redact_json handles it
        assert API_KEY not in result.raw_request_json
        assert API_KEY not in result.raw_response_json

        # Also verify the URL passed to post contained the key
        # (adapter builds URL with key=... param)
        call_args = mock_client.post.call_args
        url_called = call_args[0][0]
        assert f"key={API_KEY}" in url_called
