"""Telemetry factory helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from automa_ai.config.telemetry import TelemetryConfig
from automa_ai.telemetry.facade import Telemetry
from automa_ai.telemetry.recorders import NoopRecorder
from automa_ai.telemetry.registry import (
    get_telemetry_recorder_factory,
    load_telemetry_recorder_plugins,
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
    if resolved.load_plugins:
        load_telemetry_recorder_plugins()
    try:
        recorder_factory = get_telemetry_recorder_factory(resolved.recorder)
    except (KeyError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    recorder = recorder_factory(
        resolved,
        base_attributes or {},
        base_dir,
    )
    return Telemetry(
        config=resolved,
        recorder=recorder,
        base_attributes=base_attributes or {},
    )
