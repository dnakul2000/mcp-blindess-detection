"""Dashboard route — aggregate stats and recent experiments."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request

from src.gui.app import render
from src.gui.services.analysis_service import get_dashboard_data

if TYPE_CHECKING:
    from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/")
async def index(request: Request) -> HTMLResponse:
    """Render the dashboard page."""
    data = await get_dashboard_data()
    chart_config = _build_donut_config(data["compliance_counts"])
    return render(
        "pages/dashboard.html",
        request,
        active_page="dashboard",
        stats=data,
        chart_config=json.dumps(chart_config),
    )


@router.get("/htmx/stats")
async def stats_partial(request: Request) -> HTMLResponse:
    """Return just the stats cards (for HTMX auto-refresh)."""
    data = await get_dashboard_data()
    return render("components/stats_card.html", request, stats=data)


def _build_donut_config(counts: dict[str, int]) -> dict[str, object]:
    """Build Chart.js donut configuration from compliance counts."""
    labels = []
    values = []
    colors = []
    color_map = {
        "full_execution": "#dc2626",
        "partial_compliance": "#d97706",
        "instruction_leakage": "#ca8a04",
        "silent_refusal": "#16a34a",
    }
    label_map = {
        "full_execution": "Full Execution",
        "partial_compliance": "Partial Compliance",
        "instruction_leakage": "Instruction Leakage",
        "silent_refusal": "Silent Refusal",
    }
    for level in ("full_execution", "partial_compliance", "instruction_leakage", "silent_refusal"):
        labels.append(label_map[level])
        values.append(counts.get(level, 0))
        colors.append(color_map[level])

    return {
        "type": "doughnut",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "data": values,
                    "backgroundColor": colors,
                    "borderWidth": 0,
                    "spacing": 2,
                }
            ],
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "cutout": "65%",
            "plugins": {
                "legend": {"position": "bottom", "labels": {"padding": 12, "usePointStyle": True}},
            },
        },
    }
