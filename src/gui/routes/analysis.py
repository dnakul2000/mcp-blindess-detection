"""Analysis routes — heatmaps, detection rates, observability delta."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request

from src.gui.app import render
from src.gui.services.analysis_service import (
    get_compliance_heatmap,
    get_detection_rate_chart,
    get_delta_chart,
)

if TYPE_CHECKING:
    from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/analysis")
async def index(request: Request) -> HTMLResponse:
    """Render the analysis page with charts and heatmaps."""
    heatmap = await get_compliance_heatmap()
    detection_chart = await get_detection_rate_chart()
    delta_chart = await get_delta_chart()

    return render(
        "pages/analysis.html",
        request,
        active_page="analysis",
        heatmap=heatmap,
        detection_chart_config=json.dumps(detection_chart),
        delta_chart_config=json.dumps(delta_chart),
    )
