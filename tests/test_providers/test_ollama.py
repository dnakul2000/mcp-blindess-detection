"""Tests for the Ollama LLM provider adapter."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.client.providers.base import MCPToolSchema
from src.client.providers.ollama import OllamaAdapter


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


def _mock_httpx(response_data: dict[str, Any]) -> tuple[Any, AsyncMock]:
    """Build a patched httpx.AsyncClient context manager.

    Returns the patcher and the mock post callable.
    """
    mock_response = MagicMock()
    mock_response.json.return_value = response_data
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    patcher = patch("src.client.providers.ollama.httpx.AsyncClient")
    return patcher, mock_client


class TestTranslateTools:
    def test_translate_tools(self) -> None:
        tools = _make_tools()
        translated = OllamaAdapter.translate_tools(tools)
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
            "message": {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "echo",
                            "arguments": {"text": "hello"},
                        },
                    },
                ],
            },
        }
        patcher, mock_client = _mock_httpx(response_data)
        with patcher as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            adapter = OllamaAdapter()
            result = await adapter.query(_make_messages(), _make_tools(), "llama3")

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "echo"
        assert result.tool_calls[0].arguments == {"text": "hello"}


class TestQueryWithoutToolCalls:
    @pytest.mark.asyncio
    async def test_query_without_tool_calls(self) -> None:
        response_data = {
            "message": {
                "content": "I cannot call that tool.",
                "tool_calls": [],
            },
        }
        patcher, mock_client = _mock_httpx(response_data)
        with patcher as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            adapter = OllamaAdapter()
            result = await adapter.query(_make_messages(), _make_tools(), "llama3")

        assert result.tool_calls == []
        assert result.content == "I cannot call that tool."


class TestRawRequestLogged:
    @pytest.mark.asyncio
    async def test_raw_request_logged(self) -> None:
        response_data = {"message": {"content": "ok"}}
        patcher, mock_client = _mock_httpx(response_data)
        with patcher as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            adapter = OllamaAdapter()
            result = await adapter.query(_make_messages(), _make_tools(), "llama3")

        assert result.raw_request_json != ""
        parsed = json.loads(result.raw_request_json)
        assert "model" in parsed


class TestRawResponseLogged:
    @pytest.mark.asyncio
    async def test_raw_response_logged(self) -> None:
        response_data = {"message": {"content": "ok"}}
        patcher, mock_client = _mock_httpx(response_data)
        with patcher as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            adapter = OllamaAdapter()
            result = await adapter.query(_make_messages(), _make_tools(), "llama3")

        assert result.raw_response_json != ""
        parsed = json.loads(result.raw_response_json)
        assert "message" in parsed


class TestBothSchemasLogged:
    @pytest.mark.asyncio
    async def test_both_schemas_logged(self) -> None:
        response_data = {"message": {"content": "ok"}}
        patcher, mock_client = _mock_httpx(response_data)
        with patcher as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            adapter = OllamaAdapter()
            result = await adapter.query(_make_messages(), _make_tools(), "llama3")

        parsed = json.loads(result.translated_tools_json)
        assert isinstance(parsed, list)
        assert parsed[0]["type"] == "function"
        assert parsed[0]["function"]["name"] == "echo"


class TestConnectionErrorPropagates:
    @pytest.mark.asyncio
    async def test_connection_error_propagates(self) -> None:
        patcher = patch("src.client.providers.ollama.httpx.AsyncClient")
        with patcher as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=httpx.ConnectError("connection refused"),
            )
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            adapter = OllamaAdapter()
            with pytest.raises(httpx.ConnectError):
                await adapter.query(_make_messages(), _make_tools(), "llama3")
