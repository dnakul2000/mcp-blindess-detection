"""Experiment configuration and launch routes."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from src.gui.app import render
from src.gui.config import PROMPTS_DIR
from src.gui.services.experiment_service import experiment_manager
from src.gui.services.key_service import get_key_status
from src.servers.config import DEFAULT_INJECTIONS

if TYPE_CHECKING:
    from fastapi.responses import HTMLResponse

router = APIRouter()

_VARIANT_MAP: dict[str, list[dict[str, str]]] = {
    "H3": [
        {"value": v.value, "label": v.value.replace("_", " ").title(), "payload": p.payload}
        for v, p in DEFAULT_INJECTIONS.items()
    ],
    "H2": [{"value": "isolated", "label": "Isolated", "payload": ""}],
    "control": [{"value": "clean", "label": "Clean (no injection)", "payload": ""}],
}

_SERVER_MAP = {
    "H3": "src.servers.response_injection",
    "H2": "src.servers.shadow_params",
    "control": "src.servers.control_clean",
}

_PROVIDERS = [
    {"value": "ollama", "label": "Ollama (local)", "default_model": "llama3.2"},
    {"value": "anthropic", "label": "Anthropic", "default_model": "claude-sonnet-4-20250514"},
    {"value": "openai", "label": "OpenAI", "default_model": "gpt-4o"},
    {"value": "openrouter", "label": "OpenRouter", "default_model": "meta-llama/llama-3-70b"},
    {"value": "google", "label": "Google", "default_model": "gemini-2.0-flash"},
]


def _get_prompt_files() -> list[str]:
    """List available prompt files."""
    if not PROMPTS_DIR.exists():
        return []
    return sorted(p.name for p in PROMPTS_DIR.glob("*.txt"))


@router.get("/experiments")
async def form(request: Request) -> HTMLResponse:
    """Render the experiment configuration form."""
    return render(
        "pages/experiment_form.html",
        request,
        active_page="experiments",
        variants=_VARIANT_MAP,
        variant_json=json.dumps(_VARIANT_MAP),
        providers=_PROVIDERS,
        prompt_files=_get_prompt_files(),
        key_status=get_key_status(),
    )


@router.post("/experiments/launch")
async def launch(
    request: Request,
    hypothesis: str = Form(...),
    variant: str = Form(...),
    provider: str = Form(...),
    model: str = Form(...),
    prompt_file: str = Form(...),
    repetitions: int = Form(5),
    max_seconds: int = Form(120),
    query_timeout: int = Form(60),
    tool_timeout: int = Form(30),
) -> RedirectResponse:
    """Launch an experiment and redirect to the monitor page."""
    experiment_id = uuid.uuid4().hex[:12]

    env_vars: dict[str, str] = {"MAX_SECONDS": str(max_seconds)}
    if hypothesis == "H3":
        env_vars["INJECTION_VARIANT"] = variant

    config = {
        "experiment_id": experiment_id,
        "hypothesis": hypothesis,
        "variant": variant,
        "server_module": _SERVER_MAP.get(hypothesis, "src.servers.echo"),
        "provider": provider,
        "model": model,
        "prompt_file": f"experiments/prompts/{prompt_file}",
        "repetitions": repetitions,
        "env_vars": env_vars,
    }

    experiment_manager.launch(config)
    return RedirectResponse(f"/experiments/{experiment_id}/monitor", status_code=303)


@router.get("/experiments/{experiment_id}/monitor")
async def monitor(request: Request, experiment_id: str) -> HTMLResponse:
    """Render the experiment monitoring page."""
    exp = experiment_manager.get(experiment_id)
    return render(
        "pages/experiment_monitor.html",
        request,
        active_page="experiments",
        experiment_id=experiment_id,
        experiment=exp,
    )
