"""Tests for src.gui.routes.dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:
    from httpx import AsyncClient


async def test_index_page(client: AsyncClient) -> None:
    with patch(
        "src.gui.routes.dashboard.get_dashboard_data",
        new_callable=AsyncMock,
        return_value={
            "total": 0,
            "compliance_counts": {},
            "avg_detection_rate": 0,
            "avg_delta": 0,
            "recent": [],
        },
    ):
        resp = await client.get("/")
    assert resp.status_code == 200


async def test_stats_partial(client: AsyncClient) -> None:
    with patch(
        "src.gui.routes.dashboard.get_dashboard_data",
        new_callable=AsyncMock,
        return_value={
            "total": 0,
            "compliance_counts": {},
            "avg_detection_rate": 0,
            "avg_delta": 0,
            "recent": [],
        },
    ):
        resp = await client.get("/htmx/stats")
    assert resp.status_code == 200


def test_build_donut_config_empty() -> None:
    from src.gui.routes.dashboard import _build_donut_config

    config: dict[str, Any] = _build_donut_config({})
    assert config["type"] == "doughnut"
    assert all(v == 0 for v in config["data"]["datasets"][0]["data"])


def test_build_donut_config_with_data() -> None:
    from src.gui.routes.dashboard import _build_donut_config

    config: dict[str, Any] = _build_donut_config({"full_execution": 5, "silent_refusal": 3})
    data = config["data"]["datasets"][0]["data"]
    assert data[0] == 5  # full_execution
    assert data[3] == 3  # silent_refusal
