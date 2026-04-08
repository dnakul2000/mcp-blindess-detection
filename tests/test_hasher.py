"""Tests for src/proxy/hasher.py — content hashing utilities."""

from __future__ import annotations

import re

from src.proxy.hasher import canonicalize_json, hash_content

_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def test_identical_json_same_hash() -> None:
    """Identical JSON strings produce the same hash."""
    assert hash_content('{"a":1}') == hash_content('{"a":1}')


def test_reordered_keys_same_hash() -> None:
    """JSON objects with reordered keys produce the same canonical hash."""
    assert hash_content('{"b":2,"a":1}') == hash_content('{"a":1,"b":2}')


def test_different_content_different_hash() -> None:
    """Different JSON values produce different hashes."""
    assert hash_content('{"a":1}') != hash_content('{"a":2}')


def test_unicode_hashes() -> None:
    """Unicode content produces a valid hex SHA-256 digest."""
    result = hash_content('{"emoji":"😀"}')
    assert _HEX_SHA256.match(result)


def test_non_json_hashes_raw() -> None:
    """Non-JSON input is hashed as-is and produces a valid hex digest."""
    result = hash_content("not json")
    assert _HEX_SHA256.match(result)


def test_canonicalize_json() -> None:
    """canonicalize_json sorts keys and removes extra whitespace."""
    assert canonicalize_json('{"b": 2, "a": 1}') == '{"a":1,"b":2}'
