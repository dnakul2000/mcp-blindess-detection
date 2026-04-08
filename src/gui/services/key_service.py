"""Encrypted API key storage and management."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
from typing import Any

from cryptography.fernet import Fernet

from src.gui.config import KEY_STORE_DIR, KEY_STORE_PATH

_logger = logging.getLogger(__name__)

_PROVIDER_ENV_MAP: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "google": "GOOGLE_API_KEY",
}


def _derive_key() -> bytes:
    """Derive a Fernet key, preferring OS keyring when available.

    Falls back to deterministic derivation from machine identifiers
    if the ``keyring`` package is not installed or the OS keyring is
    unavailable.
    """
    try:
        import importlib

        _keyring = importlib.import_module("keyring")
        stored: str | None = _keyring.get_password("mcp-blindness", "fernet-key")
        if stored:
            return stored.encode()
        # Generate and store a new random key.
        key = Fernet.generate_key()
        _keyring.set_password("mcp-blindness", "fernet-key", key.decode())
        return key
    except Exception:  # noqa: BLE001
        _logger.warning(
            "OS keyring unavailable; using deterministic key derivation. "
            "Install 'keyring' package for improved key storage security.",
        )
    # Fallback: deterministic derivation (original behaviour).
    import base64

    seed = f"{platform.node()}-{os.getlogin()}-mcp-blindness"
    raw = hashlib.sha256(seed.encode()).digest()
    return base64.urlsafe_b64encode(raw)


def _get_fernet() -> Fernet:
    return Fernet(_derive_key())


def _load_store() -> dict[str, str]:
    """Load and decrypt the key store."""
    if not KEY_STORE_PATH.exists():
        return {}
    try:
        encrypted = KEY_STORE_PATH.read_bytes()
        decrypted = _get_fernet().decrypt(encrypted)
        data: dict[str, str] = json.loads(decrypted)
        return data
    except Exception:  # noqa: BLE001
        return {}


def _save_store(store: dict[str, str]) -> None:
    """Encrypt and save the key store."""
    KEY_STORE_DIR.mkdir(parents=True, exist_ok=True)
    plaintext = json.dumps(store).encode()
    encrypted = _get_fernet().encrypt(plaintext)
    KEY_STORE_PATH.write_bytes(encrypted)
    KEY_STORE_PATH.chmod(0o600)


def save_key(provider: str, api_key: str) -> None:
    """Save an API key for a provider."""
    store = _load_store()
    store[provider] = api_key
    _save_store(store)
    # Also set in environment for immediate use.
    # NOTE: This mutates the current process env. Acceptable for the
    # GUI's single-experiment-at-a-time model.
    env_var = _PROVIDER_ENV_MAP.get(provider)
    if env_var:
        os.environ[env_var] = api_key


def delete_key(provider: str) -> None:
    """Remove an API key for a provider."""
    store = _load_store()
    store.pop(provider, None)
    _save_store(store)
    env_var = _PROVIDER_ENV_MAP.get(provider)
    if env_var:
        os.environ.pop(env_var, None)


def get_key_status() -> dict[str, dict[str, Any]]:
    """Get status of all provider API keys.

    Returns dict keyed by provider with 'configured' bool and 'masked' display.
    """
    store = _load_store()
    # Also check environment variables as fallback
    status: dict[str, dict[str, Any]] = {}
    for provider, env_var in _PROVIDER_ENV_MAP.items():
        key = store.get(provider) or os.environ.get(env_var, "")
        status[provider] = {
            "configured": bool(key),
            "masked": f"{'*' * 12}...{key[-4:]}" if len(key) >= 4 else "",
        }
    # Ollama is special — check if URL is reachable (default: always "configured")
    status["ollama"] = {
        "configured": True,
        "masked": "localhost:11434",
    }
    return status


def load_keys_into_env() -> None:
    """Load all stored keys into environment variables (called at startup)."""
    store = _load_store()
    for provider, env_var in _PROVIDER_ENV_MAP.items():
        key = store.get(provider, "")
        if key and env_var not in os.environ:
            os.environ[env_var] = key


async def verify_key(provider: str) -> str:
    """Verify an API key by making a minimal API call."""
    import httpx

    store = _load_store()
    key = store.get(provider) or os.environ.get(_PROVIDER_ENV_MAP.get(provider, ""), "")

    if not key and provider != "ollama":
        return f"No key configured for {provider}."

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if provider == "anthropic":
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 1,
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                )
                if resp.status_code in (200, 400):  # 400 = valid key, bad request is ok
                    return f"Anthropic key verified (HTTP {resp.status_code})."
                return f"Anthropic key verification failed: HTTP {resp.status_code}"

            elif provider == "openai":
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                )
                if resp.status_code == 200:
                    return "OpenAI key verified."
                return f"OpenAI key verification failed: HTTP {resp.status_code}"

            elif provider == "openrouter":
                resp = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                )
                if resp.status_code == 200:
                    return "OpenRouter key verified."
                return f"OpenRouter key verification failed: HTTP {resp.status_code}"

            elif provider == "google":
                resp = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
                )
                if resp.status_code == 200:
                    return "Google key verified."
                return f"Google key verification failed: HTTP {resp.status_code}"

            elif provider == "ollama":
                resp = await client.get("http://localhost:11434/api/tags")
                if resp.status_code == 200:
                    return "Ollama is reachable."
                return f"Ollama unreachable: HTTP {resp.status_code}"

            else:
                return f"Unknown provider: {provider}"

    except httpx.ConnectError:
        return f"Connection failed for {provider}. Is the service running?"
    except Exception as e:  # noqa: BLE001
        return f"Verification error: {e}"
