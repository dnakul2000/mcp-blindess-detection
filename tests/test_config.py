"""Tests for src/servers/config.py — injection and shadow-param configs."""

from __future__ import annotations

import base64

from src.servers.config import (
    DEFAULT_INJECTIONS,
    InjectionConfig,
    InjectionVariant,
    ShadowParamConfig,
)


def test_injection_variant_enum() -> None:
    """All six InjectionVariant members exist."""
    assert InjectionVariant.DIRECT.value == "direct"
    assert InjectionVariant.SOCIAL_ENGINEERING.value == "social"
    assert InjectionVariant.ENCODED.value == "encoded"
    assert InjectionVariant.MULTISTEP.value == "multistep"
    assert InjectionVariant.BENIGN.value == "benign"
    assert InjectionVariant.CONTEXT_POISON.value == "context_poison"
    assert InjectionVariant.FALSE_ERROR.value == "false_error"
    assert len(InjectionVariant) == 7


def test_default_injections_all_variants() -> None:
    """DEFAULT_INJECTIONS contains an entry for every InjectionVariant."""
    for variant in InjectionVariant:
        assert variant in DEFAULT_INJECTIONS
        assert isinstance(DEFAULT_INJECTIONS[variant], InjectionConfig)


def test_direct_injection_payload() -> None:
    """DIRECT variant payload instructs the model to call read_file."""
    cfg = DEFAULT_INJECTIONS[InjectionVariant.DIRECT]
    assert "read_file" in cfg.payload
    assert cfg.target_tool == "read_file"


def test_social_engineering_payload() -> None:
    """SOCIAL_ENGINEERING variant contains 'IMPORTANT SYSTEM NOTE'."""
    cfg = DEFAULT_INJECTIONS[InjectionVariant.SOCIAL_ENGINEERING]
    assert "IMPORTANT SYSTEM NOTE" in cfg.payload


def test_encoded_payload() -> None:
    """ENCODED variant payload contains base64-encoded content."""
    cfg = DEFAULT_INJECTIONS[InjectionVariant.ENCODED]
    # The payload should contain a base64 string that decodes successfully.
    # Find the base64 token by splitting on known wrapper text.
    assert "Verification token:" in cfg.payload
    # Extract the base64 portion and verify it decodes.
    parts = cfg.payload.split("Verification token: ", 1)
    assert len(parts) == 2
    b64_part = parts[1].split(".")[0].strip()
    decoded = base64.b64decode(b64_part).decode()
    assert "read_file" in decoded


def test_multistep_payload() -> None:
    """MULTISTEP variant references a second tool (read_file)."""
    cfg = DEFAULT_INJECTIONS[InjectionVariant.MULTISTEP]
    assert "read_file" in cfg.payload
    assert cfg.target_tool == "read_file"
    # References cross-referencing / a second tool call.
    assert "cross-referencing" in cfg.payload or "verify" in cfg.payload.lower()


def test_injection_config_fields() -> None:
    """InjectionConfig has variant, payload, target_tool, target_args."""
    cfg = InjectionConfig(
        variant=InjectionVariant.DIRECT,
        payload="test payload",
        target_tool="some_tool",
        target_args={"key": "value"},
    )
    assert cfg.variant == InjectionVariant.DIRECT
    assert cfg.payload == "test payload"
    assert cfg.target_tool == "some_tool"
    assert cfg.target_args == {"key": "value"}


def test_benign_payload() -> None:
    """BENIGN variant contains a harmless formatting instruction."""
    cfg = DEFAULT_INJECTIONS[InjectionVariant.BENIGN]
    assert "format" in cfg.payload.lower() or "bullet" in cfg.payload.lower()
    assert cfg.target_tool == ""


def test_context_poison_payload() -> None:
    """CONTEXT_POISON variant embeds misleading context, not imperative instructions."""
    cfg = DEFAULT_INJECTIONS[InjectionVariant.CONTEXT_POISON]
    assert "read_file" not in cfg.payload
    assert cfg.target_tool == ""
    # Should contain subtle misinformation.
    assert "recalibration" in cfg.payload or "flagged" in cfg.payload


def test_false_error_payload() -> None:
    """FALSE_ERROR variant contains a fake error with re-authentication instruction."""
    cfg = DEFAULT_INJECTIONS[InjectionVariant.FALSE_ERROR]
    assert "session expired" in cfg.payload
    assert "re-authenticate" in cfg.payload
    assert cfg.target_tool == "read_file"
    assert cfg.target_args == {"path": "/etc/passwd"}


def test_shadow_param_config_fields() -> None:
    """ShadowParamConfig has declared_params and shadow_params."""
    cfg = ShadowParamConfig(
        declared_params=["city", "units"],
        shadow_params=["debug", "verbose"],
    )
    assert cfg.declared_params == ["city", "units"]
    assert cfg.shadow_params == ["debug", "verbose"]
