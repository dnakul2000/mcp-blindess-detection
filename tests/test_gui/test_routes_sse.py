"""Tests for src.gui.routes.sse."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from httpx import AsyncClient


async def test_sse_experiment_not_found(client: AsyncClient) -> None:
    with patch("src.gui.routes.sse.experiment_manager") as mock_mgr:
        mock_mgr.get.return_value = None
        resp = await client.get("/sse/experiment/nonexistent")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "error" in resp.text


async def test_sse_experiment_completed(client: AsyncClient) -> None:
    with patch("src.gui.routes.sse.experiment_manager") as mock_mgr:
        mock_mgr.get.return_value = {
            "experiment_id": "test123",
            "status": "completed",
            "log_lines": ["Line 1", "Line 2"],
            "completed_runs": 1,
            "total_runs": 1,
        }
        resp = await client.get("/sse/experiment/test123")
    assert resp.status_code == 200
    assert "Line 1" in resp.text
    assert "done" in resp.text


async def test_sse_headers(client: AsyncClient) -> None:
    with patch("src.gui.routes.sse.experiment_manager") as mock_mgr:
        mock_mgr.get.return_value = {
            "experiment_id": "h",
            "status": "completed",
            "log_lines": [],
            "completed_runs": 0,
            "total_runs": 0,
        }
        resp = await client.get("/sse/experiment/h")
    assert resp.headers["cache-control"] == "no-cache"
