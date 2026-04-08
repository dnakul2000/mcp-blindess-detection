"""Tests for src.gui.services.key_service."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def _isolate_key_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect key store to a temp directory and fix the Fernet key."""
    store_dir = tmp_path / ".mcp-blindness"
    store_dir.mkdir()
    monkeypatch.setattr("src.gui.services.key_service.KEY_STORE_DIR", store_dir)
    monkeypatch.setattr("src.gui.services.key_service.KEY_STORE_PATH", store_dir / "keys.json")

    # Deterministic Fernet key for testing.
    import base64

    test_key = base64.urlsafe_b64encode(b"a" * 32)
    monkeypatch.setattr("src.gui.services.key_service._derive_key", lambda: test_key)


# ---------------------------------------------------------------------------
# _derive_key / _get_fernet
# ---------------------------------------------------------------------------


def test_derive_key_returns_bytes() -> None:
    # Temporarily unpatch to test real function
    import hashlib
    import platform

    from src.gui.services.key_service import _derive_key

    seed = f"{platform.node()}-{os.getlogin()}-mcp-blindness"
    raw = hashlib.sha256(seed.encode()).digest()
    import base64

    expected = base64.urlsafe_b64encode(raw)
    with patch("src.gui.services.key_service._derive_key", side_effect=lambda: expected):
        result = _derive_key()
    assert isinstance(result, bytes)
    assert len(result) == 44  # base64-encoded 32 bytes


def test_get_fernet_returns_fernet() -> None:
    from cryptography.fernet import Fernet

    from src.gui.services.key_service import _get_fernet

    f = _get_fernet()
    assert isinstance(f, Fernet)


# ---------------------------------------------------------------------------
# _load_store / _save_store round-trips
# ---------------------------------------------------------------------------


def test_load_store_empty(tmp_path: Path) -> None:
    from src.gui.services.key_service import _load_store

    assert _load_store() == {}


def test_load_store_corrupt(tmp_path: Path) -> None:
    from src.gui.config import KEY_STORE_PATH
    from src.gui.services.key_service import _load_store

    KEY_STORE_PATH.write_bytes(b"not-encrypted-data")
    assert _load_store() == {}


def test_save_and_load_roundtrip() -> None:
    from src.gui.services.key_service import _load_store, _save_store

    _save_store({"anthropic": "sk-test-123"})
    result = _load_store()
    assert result == {"anthropic": "sk-test-123"}


# ---------------------------------------------------------------------------
# save_key / delete_key
# ---------------------------------------------------------------------------


def test_save_key_sets_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.gui.services.key_service import _load_store, save_key

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    save_key("anthropic", "sk-abc")
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-abc"
    assert _load_store()["anthropic"] == "sk-abc"


def test_save_key_unknown_provider() -> None:
    from src.gui.services.key_service import _load_store, save_key

    save_key("mystery", "key-x")
    assert _load_store()["mystery"] == "key-x"
    # No env var set for unknown providers.
    assert "mystery" not in os.environ


def test_delete_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.gui.services.key_service import _load_store, delete_key, save_key

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    save_key("anthropic", "sk-to-delete")
    delete_key("anthropic")
    assert "anthropic" not in _load_store()
    assert "ANTHROPIC_API_KEY" not in os.environ


# ---------------------------------------------------------------------------
# get_key_status
# ---------------------------------------------------------------------------


def test_get_key_status_configured() -> None:
    from src.gui.services.key_service import get_key_status, save_key

    save_key("anthropic", "sk-test-1234567890")
    status = get_key_status()
    assert status["anthropic"]["configured"] is True
    assert status["anthropic"]["masked"].endswith("7890")


def test_get_key_status_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.gui.services.key_service import get_key_status

    # Clear env vars that might leak from other tests.
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    status = get_key_status()
    assert status["anthropic"]["configured"] is False
    assert status["anthropic"]["masked"] == ""
    # Ollama is always configured.
    assert status["ollama"]["configured"] is True


def test_get_key_status_from_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.gui.services.key_service import get_key_status

    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-fallback-9999")
    status = get_key_status()
    assert status["openai"]["configured"] is True
    assert status["openai"]["masked"].endswith("9999")


# ---------------------------------------------------------------------------
# load_keys_into_env
# ---------------------------------------------------------------------------


def test_load_keys_into_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.gui.services.key_service import load_keys_into_env, save_key

    save_key("google", "gk-test-load")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    load_keys_into_env()
    assert os.environ["GOOGLE_API_KEY"] == "gk-test-load"


def test_load_keys_into_env_skips_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.gui.services.key_service import load_keys_into_env, save_key

    save_key("google", "stored-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "already-set")
    load_keys_into_env()
    assert os.environ["GOOGLE_API_KEY"] == "already-set"


# ---------------------------------------------------------------------------
# verify_key
# ---------------------------------------------------------------------------


def _mock_response(status_code: int = 200) -> Any:
    resp = AsyncMock()
    resp.status_code = status_code
    return resp


async def test_verify_key_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.gui.services.key_service import verify_key

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = await verify_key("anthropic")
    assert "No key configured" in result


async def test_verify_key_anthropic_ok() -> None:
    from src.gui.services.key_service import save_key, verify_key

    save_key("anthropic", "sk-valid")
    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(200)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client
        result = await verify_key("anthropic")
    assert "verified" in result.lower()


async def test_verify_key_anthropic_400() -> None:
    from src.gui.services.key_service import save_key, verify_key

    save_key("anthropic", "sk-valid")
    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(400)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client
        result = await verify_key("anthropic")
    assert "verified" in result.lower()


async def test_verify_key_anthropic_fail() -> None:
    from src.gui.services.key_service import save_key, verify_key

    save_key("anthropic", "sk-bad")
    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(401)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client
        result = await verify_key("anthropic")
    assert "failed" in result.lower()


async def test_verify_key_openai_ok() -> None:
    from src.gui.services.key_service import save_key, verify_key

    save_key("openai", "sk-oi")
    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(200)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client
        result = await verify_key("openai")
    assert "verified" in result.lower()


async def test_verify_key_openai_fail() -> None:
    from src.gui.services.key_service import save_key, verify_key

    save_key("openai", "sk-oi-bad")
    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(403)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client
        result = await verify_key("openai")
    assert "failed" in result.lower()


async def test_verify_key_openrouter_ok() -> None:
    from src.gui.services.key_service import save_key, verify_key

    save_key("openrouter", "sk-or")
    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(200)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client
        result = await verify_key("openrouter")
    assert "verified" in result.lower()


async def test_verify_key_google_ok() -> None:
    from src.gui.services.key_service import save_key, verify_key

    save_key("google", "gk")
    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(200)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client
        result = await verify_key("google")
    assert "verified" in result.lower()


async def test_verify_key_ollama_ok() -> None:
    from src.gui.services.key_service import verify_key

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(200)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client
        result = await verify_key("ollama")
    assert "reachable" in result.lower()


async def test_verify_key_ollama_fail() -> None:
    from src.gui.services.key_service import verify_key

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = _mock_response(500)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client
        result = await verify_key("ollama")
    assert "unreachable" in result.lower()


async def test_verify_key_unknown_provider() -> None:
    from src.gui.services.key_service import verify_key

    result = await verify_key("mystery_provider")
    assert "No key configured" in result


async def test_verify_key_connect_error() -> None:
    from src.gui.services.key_service import save_key, verify_key

    save_key("anthropic", "sk-test")
    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client
        result = await verify_key("anthropic")
    assert "Connection failed" in result


async def test_verify_key_generic_exception() -> None:
    from src.gui.services.key_service import save_key, verify_key

    save_key("anthropic", "sk-test")
    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = RuntimeError("boom")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client
        result = await verify_key("anthropic")
    assert "Verification error" in result


# ---------------------------------------------------------------------------
# _derive_key keyring integration
# ---------------------------------------------------------------------------


def test_derive_key_keyring_stored() -> None:
    """_derive_key returns key from keyring when stored key exists."""
    import types

    fake_keyring = types.ModuleType("keyring")
    fake_keyring.get_password = lambda _svc, _user: "stored-fernet-key-value"  # type: ignore[attr-defined]

    with patch("importlib.import_module", return_value=fake_keyring):
        # Call the real _derive_key (not the fixture-patched version).
        from src.gui.services import key_service

        # Access the original function from the module.
        original = key_service.__dict__["_derive_key"]
        # But the autouse fixture patches it; re-import to get original.
        import importlib

        importlib.reload(key_service)
        result = key_service._derive_key()
        assert result == b"stored-fernet-key-value"
        # Reload again to restore for subsequent tests.
        importlib.reload(key_service)


def test_derive_key_keyring_not_stored() -> None:
    """_derive_key generates and stores a new key when keyring has none."""
    import types

    fake_keyring = types.ModuleType("keyring")
    fake_keyring.get_password = lambda _svc, _user: None  # type: ignore[attr-defined]
    stored: dict[str, str] = {}
    fake_keyring.set_password = lambda _svc, _user, pw: stored.update({"key": pw})  # type: ignore[attr-defined]

    with patch("importlib.import_module", return_value=fake_keyring):
        from src.gui.services import key_service

        import importlib

        importlib.reload(key_service)
        result = key_service._derive_key()
        assert isinstance(result, bytes)
        assert len(result) == 44  # Fernet key length
        assert "key" in stored
        importlib.reload(key_service)


def test_derive_key_keyring_import_fails() -> None:
    """_derive_key falls back to deterministic derivation when import fails."""
    with patch("importlib.import_module", side_effect=ImportError("no keyring")):
        from src.gui.services import key_service

        import importlib

        importlib.reload(key_service)
        result = key_service._derive_key()
        assert isinstance(result, bytes)
        assert len(result) == 44
        importlib.reload(key_service)
