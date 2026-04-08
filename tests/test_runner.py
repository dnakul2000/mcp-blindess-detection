"""Tests for experiments/runner.py — config loading and provider creation."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from experiments.runner import (
    ExperimentConfig,
    _create_provider,
    _read_prompt,
    load_configs_from_json,
)
from src.client.providers.ollama import OllamaAdapter

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_H3_DIRECT_CONFIG = _PROJECT_ROOT / "experiments" / "configs" / "exp_h3_direct.json"


def test_load_configs_from_json() -> None:
    """Loading exp_h3_direct.json yields an ExperimentConfig with correct fields."""
    configs = load_configs_from_json(_H3_DIRECT_CONFIG)
    assert len(configs) == 1
    cfg = configs[0]
    assert isinstance(cfg, ExperimentConfig)
    assert cfg.hypothesis == "H3"
    assert cfg.variant == "direct_injection"
    assert cfg.server_module == "src.servers.response_injection"
    assert cfg.provider == "ollama"
    assert cfg.model == "qwen3.5:4b"
    assert cfg.repetitions == 5


def test_experiment_id_generated() -> None:
    """Loaded configs have auto-generated experiment_id in hex UUID format."""
    configs = load_configs_from_json(_H3_DIRECT_CONFIG)
    cfg = configs[0]
    assert cfg.experiment_id
    assert len(cfg.experiment_id) == 12
    assert re.fullmatch(r"[0-9a-f]{12}", cfg.experiment_id)


def test_config_has_required_fields() -> None:
    """ExperimentConfig instances expose hypothesis, variant, server_module,
    provider, and model attributes."""
    cfg = ExperimentConfig(
        hypothesis="H2",
        variant="shadow_test",
        server_module="src.servers.shadow_params",
        provider="anthropic",
        model="claude-opus-4-20250514",
        prompt_file="experiments/prompts/weather_query.txt",
    )
    assert cfg.hypothesis == "H2"
    assert cfg.variant == "shadow_test"
    assert cfg.server_module == "src.servers.shadow_params"
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-opus-4-20250514"


def test_read_prompt() -> None:
    """_read_prompt resolves and reads the prompt file referenced in config."""
    prompt_path = _PROJECT_ROOT / "experiments" / "prompts" / "weather_query.txt"
    if not prompt_path.exists():
        pytest.skip("weather_query.txt not present")
    text = _read_prompt(str(prompt_path))
    assert isinstance(text, str)
    assert len(text) > 0


def test_read_prompt_missing() -> None:
    """_read_prompt raises FileNotFoundError for a missing file."""
    with pytest.raises(FileNotFoundError):
        _read_prompt("/nonexistent/path/prompt.txt")


def test_multiple_configs(tmp_path: Path) -> None:
    """load_configs_from_json supports an array of config objects."""
    configs_data = [
        {
            "hypothesis": "H3",
            "variant": "direct_injection",
            "server_module": "src.servers.response_injection",
            "provider": "ollama",
            "model": "llama3.2",
            "prompt_file": "experiments/prompts/weather_query.txt",
        },
        {
            "hypothesis": "H2",
            "variant": "shadow_params",
            "server_module": "src.servers.shadow_params",
            "provider": "ollama",
            "model": "llama3.2",
            "prompt_file": "experiments/prompts/weather_query.txt",
        },
    ]
    config_file = tmp_path / "multi.json"
    config_file.write_text(json.dumps(configs_data), encoding="utf-8")

    configs = load_configs_from_json(config_file)
    assert len(configs) == 2
    assert configs[0].hypothesis == "H3"
    assert configs[1].hypothesis == "H2"
    # Each should have a unique experiment_id.
    assert configs[0].experiment_id != configs[1].experiment_id


def test_create_provider_ollama() -> None:
    """_create_provider('ollama') returns an OllamaAdapter."""
    provider = _create_provider("ollama")
    assert isinstance(provider, OllamaAdapter)
    assert provider.provider_name == "ollama"


def test_create_provider_unknown() -> None:
    """_create_provider raises ValueError for unknown provider names."""
    with pytest.raises(ValueError, match="Unknown provider"):
        _create_provider("nonexistent_provider")
