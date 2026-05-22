"""Payload sanitization helpers for telemetry."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|token|secret|password|passwd|authorization|credential)",
    re.IGNORECASE,
)
PAYLOAD_KEY_PATTERN = re.compile(
    r"(content|arguments?|result|payload|input|output|prompt|response|artifact)",
    re.IGNORECASE,
)
SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(sk-[a-z0-9_-]{12,}|bearer\s+[a-z0-9._~+/=-]{12,})"
)


def content_hash(value: Any) -> str:
    """Return a stable digest so payloads can be correlated without storing them."""
    text = value if isinstance(value, str) else repr(value)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def sanitize_text(
    value: Any,
    *,
    mode: str = "metadata",
    max_chars: int = 4000,
) -> dict[str, Any]:
    """Sanitize a single text payload according to the configured privacy mode."""
    text = "" if value is None else str(value)
    sanitized: dict[str, Any] = {
        "length": len(text),
        "sha256": content_hash(text),
    }
    if mode in {"off", "metadata"}:
        return sanitized
    content = text
    if mode == "redacted":
        content = SECRET_VALUE_PATTERN.sub("[REDACTED]", content)
    if max_chars >= 0 and len(content) > max_chars:
        content = content[:max_chars]
        sanitized["truncated"] = True
    sanitized["content"] = content
    return sanitized


def sanitize_value(
    value: Any,
    *,
    mode: str = "metadata",
    max_chars: int = 4000,
) -> Any:
    """Recursively sanitize payload-like values while preserving scalar metadata."""
    if isinstance(value, Mapping):
        return sanitize_mapping(value, mode=mode, max_chars=max_chars)
    if isinstance(value, str):
        return sanitize_text(value, mode=mode, max_chars=max_chars)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [sanitize_value(item, mode=mode, max_chars=max_chars) for item in value]
    return value


def sanitize_mapping(
    payload: Mapping[str, Any] | None,
    *,
    mode: str = "metadata",
    max_chars: int = 4000,
) -> dict[str, Any]:
    """Sanitize one telemetry attributes mapping.

    Attribute keys drive behavior:
    - obvious secret keys are always removed;
    - payload-like keys get length/hash metadata by default;
    - ordinary string metadata such as `agent.name` stays readable.
    """
    if not payload:
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        key_text = str(key)
        if SECRET_KEY_PATTERN.search(key_text):
            sanitized[key_text] = "[REDACTED]"
            continue
        if PAYLOAD_KEY_PATTERN.search(key_text):
            sanitized[key_text] = sanitize_value(
                value, mode=mode, max_chars=max_chars
            )
        elif isinstance(value, str) and mode == "redacted":
            sanitized[key_text] = SECRET_VALUE_PATTERN.sub("[REDACTED]", value)
        else:
            sanitized[key_text] = value
    return sanitized
