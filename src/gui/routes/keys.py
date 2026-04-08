"""API key management routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Form, Request

from src.gui.app import render
from src.gui.services.key_service import (
    delete_key,
    get_key_status,
    save_key,
    verify_key,
)

if TYPE_CHECKING:
    from fastapi.responses import HTMLResponse

router = APIRouter()

_PROVIDERS = [
    {"id": "anthropic", "name": "Anthropic", "color": "#d97706", "env_var": "ANTHROPIC_API_KEY"},
    {"id": "openai", "name": "OpenAI", "color": "#10b981", "env_var": "OPENAI_API_KEY"},
    {"id": "openrouter", "name": "OpenRouter", "color": "#6366f1", "env_var": "OPENROUTER_API_KEY"},
    {"id": "google", "name": "Google", "color": "#4285f4", "env_var": "GOOGLE_API_KEY"},
    {"id": "ollama", "name": "Ollama (local)", "color": "#64748b", "env_var": None},
]


@router.get("/keys")
async def index(request: Request) -> HTMLResponse:
    """Render the API key management page."""
    return render(
        "pages/keys.html",
        request,
        active_page="keys",
        providers=_PROVIDERS,
        key_status=get_key_status(),
    )


@router.post("/keys/{provider}")
async def save(request: Request, provider: str, api_key: str = Form(...)) -> HTMLResponse:
    """Save or update an API key."""
    save_key(provider, api_key)
    return render(
        "pages/keys.html",
        request,
        active_page="keys",
        providers=_PROVIDERS,
        key_status=get_key_status(),
        message=f"Key for {provider} saved successfully.",
    )


@router.post("/keys/{provider}/delete")
async def remove(request: Request, provider: str) -> HTMLResponse:
    """Remove an API key."""
    delete_key(provider)
    return render(
        "pages/keys.html",
        request,
        active_page="keys",
        providers=_PROVIDERS,
        key_status=get_key_status(),
        message=f"Key for {provider} removed.",
    )


@router.post("/keys/{provider}/verify")
async def verify(request: Request, provider: str) -> HTMLResponse:
    """Verify an API key works."""
    result = await verify_key(provider)
    return render(
        "pages/keys.html",
        request,
        active_page="keys",
        providers=_PROVIDERS,
        key_status=get_key_status(),
        message=result,
    )
