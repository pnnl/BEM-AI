from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MeasureSpec:
    measure_id: str
    entrypoint: Path
    description: str
    allowed: bool
    timeout_seconds: int
    args_schema: dict[str, Any]


class MeasureRegistry:
    """Policy-driven registry for OpenStudio Python measures."""

    def __init__(self, policy_path: Path, base_dir: Path):
        self.policy_path = policy_path
        self.base_dir = base_dir
        self._measures: dict[str, MeasureSpec] = {}
        self.reload()

    def reload(self) -> None:
        if not self.policy_path.exists():
            self._measures = {}
            return

        data = json.loads(self.policy_path.read_text(encoding="utf-8"))
        measures_raw = data.get("measures", {})
        if not isinstance(measures_raw, dict):
            raise ValueError("measure_registry.yaml must contain an object field 'measures'.")

        loaded: dict[str, MeasureSpec] = {}
        for measure_id, spec in measures_raw.items():
            if not isinstance(spec, dict):
                continue
            entrypoint_raw = spec.get("entrypoint")
            if not isinstance(entrypoint_raw, str) or not entrypoint_raw.strip():
                raise ValueError(f"Invalid entrypoint for measure '{measure_id}'.")
            entrypoint = (self.base_dir / entrypoint_raw).resolve()
            loaded[measure_id] = MeasureSpec(
                measure_id=measure_id,
                entrypoint=entrypoint,
                description=str(spec.get("description", "")),
                allowed=bool(spec.get("allowed", False)),
                timeout_seconds=int(spec.get("timeout_seconds", 120)),
                args_schema=spec.get("args_schema", {}) if isinstance(spec.get("args_schema", {}), dict) else {},
            )

        self._measures = loaded

    def get(self, measure_id: str) -> MeasureSpec:
        spec = self._measures.get(measure_id)
        if not spec:
            raise KeyError(f"Unknown measure_id: {measure_id}")
        if not spec.allowed:
            raise PermissionError(f"Measure not allowed by policy: {measure_id}")
        if not spec.entrypoint.exists():
            raise FileNotFoundError(f"Measure entrypoint not found: {spec.entrypoint}")
        return spec

    def normalize_args(self, measure_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        spec = self.get(measure_id)
        schema = spec.args_schema
        if not schema:
            return dict(payload)

        properties = schema.get("properties", {}) if isinstance(schema.get("properties", {}), dict) else {}
        required = schema.get("required", []) if isinstance(schema.get("required", []), list) else []

        normalized: dict[str, Any] = {}
        for key, prop in properties.items():
            if key in payload:
                normalized[key] = payload[key]
            elif isinstance(prop, dict) and "default" in prop:
                normalized[key] = prop["default"]

        # Preserve extra args for forward compatibility.
        for key, value in payload.items():
            if key not in normalized:
                normalized[key] = value

        for key in required:
            if key not in normalized:
                raise ValueError(f"Missing required measure arg: {key}")

        for key, value in normalized.items():
            prop = properties.get(key)
            if not isinstance(prop, dict):
                continue
            expected_type = prop.get("type")
            if expected_type == "number" and not isinstance(value, (int, float)):
                raise ValueError(f"Measure arg '{key}' must be number")
            if expected_type == "integer" and not isinstance(value, int):
                raise ValueError(f"Measure arg '{key}' must be integer")
            if expected_type == "boolean" and not isinstance(value, bool):
                raise ValueError(f"Measure arg '{key}' must be boolean")
            if expected_type == "string" and not isinstance(value, str):
                raise ValueError(f"Measure arg '{key}' must be string")

        return normalized

    def list_public_specs(self) -> list[dict[str, Any]]:
        measures: list[dict[str, Any]] = []
        for measure_id, spec in sorted(self._measures.items(), key=lambda item: item[0]):
            if not spec.allowed:
                continue
            measures.append(
                {
                    "measure_id": measure_id,
                    "description": spec.description,
                    "timeout_seconds": spec.timeout_seconds,
                    "args_schema": spec.args_schema,
                }
            )
        return measures
