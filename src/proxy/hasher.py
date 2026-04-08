"""Content hashing utilities for MCP proxy message tracking."""

from __future__ import annotations

import hashlib
import json


def canonicalize_json(data: str) -> str:
    """Parse JSON string and re-serialize with sorted keys, no extra whitespace.

    Args:
        data: A JSON string to canonicalize.

    Returns:
        Canonical JSON string with sorted keys and no indentation.

    Raises:
        json.JSONDecodeError: If the input is not valid JSON.
    """
    parsed = json.loads(data)
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"))


def hash_content(data: str) -> str:
    """Compute SHA-256 hash of canonical JSON content.

    If the input is valid JSON, it is first canonicalized (sorted keys,
    no whitespace) before hashing. If parsing fails, the raw string is
    hashed directly.

    Args:
        data: A string to hash, ideally JSON content.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    try:
        canonical = canonicalize_json(data)
    except (json.JSONDecodeError, TypeError):
        canonical = data
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
