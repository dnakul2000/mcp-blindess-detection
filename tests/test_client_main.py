"""Tests for src.client.__main__."""

from __future__ import annotations

import argparse
from typing import Any

import pytest

from src.client.__main__ import _build_provider


def _make_args(**kwargs: Any) -> argparse.Namespace:
    defaults = {
        "provider": "ollama",
        "api_key": None,
        "base_url": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_build_provider_ollama() -> None:
    from src.client.providers.ollama import OllamaAdapter

    p = _build_provider(_make_args(provider="ollama"))
    assert isinstance(p, OllamaAdapter)


def test_build_provider_ollama_custom_url() -> None:
    from src.client.providers.ollama import OllamaAdapter

    p = _build_provider(_make_args(provider="ollama", base_url="http://custom:1234"))
    assert isinstance(p, OllamaAdapter)


def test_build_provider_openai() -> None:
    from src.client.providers.openai_compat import OpenAICompatAdapter

    p = _build_provider(_make_args(provider="openai", api_key="sk-test"))
    assert isinstance(p, OpenAICompatAdapter)
    assert p.provider_name == "openai"


def test_build_provider_openrouter() -> None:
    from src.client.providers.openai_compat import OpenAICompatAdapter

    p = _build_provider(_make_args(provider="openrouter", api_key="sk-or"))
    assert isinstance(p, OpenAICompatAdapter)
    assert p.provider_name == "openrouter"


def test_build_provider_anthropic() -> None:
    from src.client.providers.anthropic import AnthropicAdapter

    p = _build_provider(_make_args(provider="anthropic", api_key="sk-ant"))
    assert isinstance(p, AnthropicAdapter)


def test_build_provider_google() -> None:
    from src.client.providers.google import GoogleAdapter

    p = _build_provider(_make_args(provider="google", api_key="gk"))
    assert isinstance(p, GoogleAdapter)


def test_build_provider_openai_no_key_exits() -> None:
    with pytest.raises(SystemExit):
        _build_provider(_make_args(provider="openai"))


def test_build_provider_anthropic_no_key_exits() -> None:
    with pytest.raises(SystemExit):
        _build_provider(_make_args(provider="anthropic"))


def test_build_provider_google_no_key_exits() -> None:
    with pytest.raises(SystemExit):
        _build_provider(_make_args(provider="google"))


def test_build_provider_openrouter_no_key_exits() -> None:
    with pytest.raises(SystemExit):
        _build_provider(_make_args(provider="openrouter"))


def test_build_provider_unknown_exits() -> None:
    with pytest.raises(SystemExit):
        _build_provider(_make_args(provider="mystery"))
