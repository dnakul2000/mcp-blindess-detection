"""Tests for src.gui.routes.keys."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:
    from httpx import AsyncClient


async def test_keys_page(client: AsyncClient) -> None:
    with patch("src.gui.routes.keys.get_key_status", return_value={}):
        resp = await client.get("/keys")
    assert resp.status_code == 200


async def test_save_key(client: AsyncClient) -> None:
    with (
        patch("src.gui.routes.keys.save_key") as mock_save,
        patch("src.gui.routes.keys.get_key_status", return_value={}),
    ):
        resp = await client.post("/keys/anthropic", data={"api_key": "sk-test"})
    assert resp.status_code == 200
    mock_save.assert_called_once_with("anthropic", "sk-test")


async def test_delete_key(client: AsyncClient) -> None:
    with (
        patch("src.gui.routes.keys.delete_key") as mock_del,
        patch("src.gui.routes.keys.get_key_status", return_value={}),
    ):
        resp = await client.post("/keys/anthropic/delete")
    assert resp.status_code == 200
    mock_del.assert_called_once_with("anthropic")


async def test_verify_key(client: AsyncClient) -> None:
    with (
        patch(
            "src.gui.routes.keys.verify_key", new_callable=AsyncMock, return_value="Key verified!"
        ),
        patch("src.gui.routes.keys.get_key_status", return_value={}),
    ):
        resp = await client.post("/keys/anthropic/verify")
    assert resp.status_code == 200
