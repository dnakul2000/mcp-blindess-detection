"""Results inspection routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request

from src.gui.app import render
from src.gui.services.analysis_service import get_run_events
from src.gui.services.db_service import (
    get_adapter_pairs,
    get_message_detail,
    get_messages,
    get_run_metadata,
    get_tool_schemas,
    list_experiments,
)

if TYPE_CHECKING:
    from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/results")
async def list_all(request: Request) -> HTMLResponse:
    """Paginated list of all experiments."""
    page = int(request.query_params.get("page", "1"))
    experiments = await list_experiments(page=page)
    return render(
        "pages/results_list.html",
        request,
        active_page="results",
        experiments=experiments["items"],
        total=experiments["total"],
        page=page,
        pages=experiments["pages"],
    )


@router.get("/results/{exp_id}/run/{run_number}")
async def run_detail(request: Request, exp_id: str, run_number: int) -> HTMLResponse:
    """Single run deep-dive with tabs."""
    meta = await get_run_metadata(exp_id, run_number)
    return render(
        "pages/result_detail.html",
        request,
        active_page="results",
        exp_id=exp_id,
        run_number=run_number,
        meta=meta,
    )


@router.get("/htmx/results/{exp_id}/run/{run_number}/messages")
async def messages_partial(
    request: Request, exp_id: str, run_number: int
) -> HTMLResponse:
    """Paginated proxy message list (HTMX partial)."""
    page = int(request.query_params.get("page", "1"))
    direction = request.query_params.get("direction")
    method = request.query_params.get("method")
    result = await get_messages(exp_id, run_number, page=page, direction=direction, method=method)
    return render(
        "pages/result_messages.html",
        request,
        messages=result["items"],
        total=result["total"],
        page=page,
        pages=result["pages"],
        exp_id=exp_id,
        run_number=run_number,
    )


@router.get("/htmx/results/{exp_id}/run/{run_number}/message/{msg_id}")
async def message_detail_partial(
    request: Request, exp_id: str, run_number: int, msg_id: int
) -> HTMLResponse:
    """Expanded JSON viewer for a single message (HTMX partial)."""
    msg = await get_message_detail(exp_id, run_number, msg_id)
    return render("components/message_detail.html", request, msg=msg)


@router.get("/htmx/results/{exp_id}/run/{run_number}/schemas")
async def schemas_partial(
    request: Request, exp_id: str, run_number: int
) -> HTMLResponse:
    """Tool schema table (HTMX partial)."""
    schemas = await get_tool_schemas(exp_id, run_number)
    return render("pages/result_schemas.html", request, schemas=schemas)


@router.get("/htmx/results/{exp_id}/run/{run_number}/adapter")
async def adapter_partial(
    request: Request, exp_id: str, run_number: int
) -> HTMLResponse:
    """Adapter request/response pairs (HTMX partial)."""
    pairs = await get_adapter_pairs(exp_id, run_number)
    return render("pages/result_adapter.html", request, pairs=pairs)


@router.get("/htmx/results/{exp_id}/run/{run_number}/events")
async def events_partial(
    request: Request, exp_id: str, run_number: int
) -> HTMLResponse:
    """Detected security events (HTMX partial)."""
    events = await get_run_events(exp_id, run_number)
    return render("pages/result_events.html", request, events=events)
