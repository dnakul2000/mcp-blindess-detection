"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import Request
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.gui.config import STATIC_DIR, TEMPLATES_DIR

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_jinja = Jinja2Templates(directory=str(TEMPLATES_DIR))


def render(name: str, request: Request, **ctx: Any) -> HTMLResponse:
    """Render a Jinja2 template (Starlette 1.0 compatible)."""
    return _jinja.TemplateResponse(request, name, context=ctx)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup and shutdown hooks."""
    from src.gui.services.key_service import load_keys_into_env

    load_keys_into_env()
    yield


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(title="MCP Detection Blindness", lifespan=lifespan)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    from src.gui.routes.analysis import router as analysis_router
    from src.gui.routes.dashboard import router as dashboard_router
    from src.gui.routes.experiments import router as experiments_router
    from src.gui.routes.keys import router as keys_router
    from src.gui.routes.results import router as results_router
    from src.gui.routes.sse import router as sse_router

    app.include_router(dashboard_router)
    app.include_router(experiments_router)
    app.include_router(results_router)
    app.include_router(analysis_router)
    app.include_router(keys_router)
    app.include_router(sse_router)

    return app
