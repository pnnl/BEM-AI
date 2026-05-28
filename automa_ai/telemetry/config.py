"""Telemetry factory helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from automa_ai.config.telemetry import TelemetryConfig
from automa_ai.telemetry.facade import Telemetry
from automa_ai.telemetry.recorders import (
    JsonlRecorder,
    NoopRecorder,
    OpenTelemetryRecorder,
)


def build_telemetry(
    config: TelemetryConfig | dict[str, Any] | str | None,
    *,
    base_attributes: dict[str, Any] | None = None,
    base_dir: str | Path | None = None,
) -> Telemetry:
    """Build the recorder facade from user config.

    This function is the only place that chooses a recorder implementation.
    Runtime code should depend on the returned `Telemetry` facade, not on JSONL
    or future OpenTelemetry-specific classes.
    """
    resolved = TelemetryConfig.from_value(config)
    if not resolved.enabled:
        return Telemetry(
            config=resolved,
            recorder=NoopRecorder(),
            base_attributes=base_attributes or {},
        )
    if resolved.recorder == "noop":
        recorder = NoopRecorder()
    elif resolved.recorder == "jsonl":
        path = resolved.resolved_path(base_dir=base_dir) or Path(
            "./logs/telemetry.jsonl"
        )
        recorder = JsonlRecorder(path)
    elif resolved.recorder == "otel":
        recorder = OpenTelemetryRecorder(
            service_name=resolved.service_name,
            environment=resolved.environment,
            attributes=resolved.attributes,
        )
    else:
        raise ValueError(f"Unsupported telemetry recorder: {resolved.recorder}")
    return Telemetry(
        config=resolved,
        recorder=recorder,
        base_attributes=base_attributes or {},
    )
