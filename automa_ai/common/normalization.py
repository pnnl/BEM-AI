from __future__ import annotations

from typing import Any


PROTECTED_BLACKBOARD_KEYS = {
    "building_type",
    "energy_standard",
    "save_dir",
    "location",
    "city",
    "state",
    "climate_zone",
    "original_model_path",
    "updated_model_path",
}


def sanitize_model_identifier(value: Any, *, max_length: int = 100) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    collapsed = _collapse_repeated_pattern(text)
    if len(collapsed) > max_length:
        collapsed = collapsed[:max_length]
    return collapsed


def sanitize_blackboard_update(
    agent_name: str,
    blackboard_update: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(blackboard_update, dict):
        return {}

    if _agent_should_protect_core_metadata(agent_name):
        return {
            key: value
            for key, value in blackboard_update.items()
            if key not in PROTECTED_BLACKBOARD_KEYS
        }

    return dict(blackboard_update)


def _agent_should_protect_core_metadata(agent_name: str) -> bool:
    normalized = agent_name.lower()
    return "simulation" in normalized or "output" in normalized


def _collapse_repeated_pattern(text: str) -> str:
    text_len = len(text)
    for unit_len in range(1, (text_len // 2) + 1):
        if text_len % unit_len != 0:
            continue
        unit = text[:unit_len]
        if unit * (text_len // unit_len) == text:
            return unit
    return text
