"""Server-Sent Events for live experiment progress."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
from fastapi.responses import StreamingResponse

from src.gui.services.experiment_service import experiment_manager

router = APIRouter()


@router.get("/sse/experiment/{experiment_id}")
async def experiment_stream(experiment_id: str) -> StreamingResponse:
    """Stream experiment progress as SSE events."""

    async def event_generator() -> AsyncGenerator[str, None]:
        exp = experiment_manager.get(experiment_id)
        if exp is None:
            yield "data: {\"type\": \"error\", \"message\": \"Experiment not found\"}\n\n"
            return

        cursor = 0
        while True:
            lines = exp["log_lines"]
            if cursor < len(lines):
                for line in lines[cursor:]:
                    yield f"data: {line}\n\n"
                cursor = len(lines)

            if exp["status"] in ("completed", "failed"):
                status = exp["status"]
                yield f"event: done\ndata: {{\"status\": \"{status}\"}}\n\n"
                return

            await asyncio.sleep(0.5)  # pragma: no cover

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
