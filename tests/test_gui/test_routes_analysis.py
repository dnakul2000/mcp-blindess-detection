"""Tests for src.gui.routes.analysis."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:
    from httpx import AsyncClient


async def test_analysis_page(client: AsyncClient) -> None:
    empty_chart = {"type": "bar", "data": {"labels": [], "datasets": []}, "options": {}}
    with (
        patch(
            "src.gui.routes.analysis.get_compliance_heatmap",
            new_callable=AsyncMock,
            return_value={"models": [], "variants": [], "cells": {}},
        ),
        patch(
            "src.gui.routes.analysis.get_detection_rate_chart",
            new_callable=AsyncMock,
            return_value=empty_chart,
        ),
        patch(
            "src.gui.routes.analysis.get_delta_chart",
            new_callable=AsyncMock,
            return_value=empty_chart,
        ),
    ):
        resp = await client.get("/analysis")
    assert resp.status_code == 200
