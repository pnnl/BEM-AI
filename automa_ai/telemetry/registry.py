"""Extensible registry for telemetry recorder implementations."""

from __future__ import annotations

import importlib.metadata
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from automa_ai.config.telemetry import TelemetryConfig
from automa_ai.telemetry.otel import build_otel_recorder
from automa_ai.telemetry.recorders import JsonlRecorder, NoopRecorder, TelemetryRecorder

TelemetryRecorderFactory = Callable[
    [TelemetryConfig, dict[str, Any], str | Path | None],
    TelemetryRecorder,
]

logger = logging.getLogger(__name__)
_BUILTIN_RECORDER_NAMES = frozenset({"noop", "jsonl", "otel"})
_PLUGIN_LOAD_LOCK = threading.Lock()


class TelemetryRecorderRegistry:
    """Maps recorder names to recorder factory functions.

    The facade emits one stable AUTOMA telemetry record shape. Projects can
    register adapters that convert that shape into OpenTelemetry, AgentCore,
    CloudWatch, or another backend without adding those dependencies to core.
    """

    def __init__(self) -> None:
        self._factories: dict[str, TelemetryRecorderFactory] = {}
        self._lock = threading.Lock()

    def register(
        self,
        name: str,
        factory: TelemetryRecorderFactory,
        *,
        override: bool = False,
    ) -> None:
        """Register a recorder factory under a short config name."""
        normalized = _normalize_name(name)
        with self._lock:
            if self._factories.get(normalized) is factory:
                return
            if normalized in _BUILTIN_RECORDER_NAMES and normalized in self._factories:
                raise ValueError(
                    f"Telemetry recorder '{normalized}' is built in and cannot be replaced."
                )
            if not override and normalized in self._factories:
                raise ValueError(
                    f"Telemetry recorder '{normalized}' is already registered."
                )
            self._factories[normalized] = factory

    def get(self, name: str) -> TelemetryRecorderFactory:
        """Return the factory for a registered recorder name."""
        normalized = _normalize_name(name)
        with self._lock:
            try:
                return self._factories[normalized]
            except KeyError as exc:
                known = ", ".join(sorted(self._factories)) or "<none>"
                raise KeyError(
                    f"Telemetry recorder '{normalized}' is not registered. "
                    f"Known recorders: {known}"
                ) from exc

    def list(self) -> list[str]:
        """List registered recorder names for diagnostics and docs."""
        with self._lock:
            return sorted(self._factories)


def _normalize_name(name: str) -> str:
    """Normalize recorder names before registry lookup."""
    text = str(name).strip()
    if not text:
        raise ValueError("Telemetry recorder name cannot be empty.")
    return text


def _build_noop_recorder(
    _config: TelemetryConfig,
    _base_attributes: dict[str, Any],
    _base_dir: str | Path | None,
) -> TelemetryRecorder:
    return NoopRecorder()


def _build_jsonl_recorder(
    config: TelemetryConfig,
    _base_attributes: dict[str, Any],
    base_dir: str | Path | None,
) -> TelemetryRecorder:
    path = config.resolved_path(base_dir=base_dir) or Path("./logs/telemetry.jsonl")
    return JsonlRecorder(path)


TELEMETRY_RECORDER_REGISTRY = TelemetryRecorderRegistry()
TELEMETRY_RECORDER_REGISTRY.register("noop", _build_noop_recorder)
TELEMETRY_RECORDER_REGISTRY.register("jsonl", _build_jsonl_recorder)
TELEMETRY_RECORDER_REGISTRY.register("otel", build_otel_recorder)

_PLUGINS_LOADED = False


def register_telemetry_recorder(
    name: str,
    factory: TelemetryRecorderFactory,
    *,
    override: bool = False,
) -> None:
    """Register a project-provided telemetry recorder factory."""
    TELEMETRY_RECORDER_REGISTRY.register(name, factory, override=override)


def get_telemetry_recorder_factory(name: str) -> TelemetryRecorderFactory:
    """Return a registered telemetry recorder factory."""
    return TELEMETRY_RECORDER_REGISTRY.get(name)


def list_telemetry_recorders() -> list[str]:
    """Return registered telemetry recorder names."""
    return TELEMETRY_RECORDER_REGISTRY.list()


def load_telemetry_recorder_plugins() -> None:
    """Load recorder factories exposed through package entry points.

    Plugin packages can expose factories under the `automa_ai.telemetry_recorders`
    entry point group. Loading is idempotent for this process so repeated agent
    construction does not re-register the same recorder.
    """
    global _PLUGINS_LOADED
    with _PLUGIN_LOAD_LOCK:
        if _PLUGINS_LOADED:
            return
        try:
            entry_points = importlib.metadata.entry_points().select(
                group="automa_ai.telemetry_recorders"
            )
        except Exception:
            logger.warning(
                "Unable to discover telemetry recorder plugins.", exc_info=True
            )
            return
        try:
            for ep in entry_points:
                try:
                    register_telemetry_recorder(ep.name, ep.load())
                    logger.info(
                        "Loaded telemetry recorder plugin '%s' from %s.",
                        ep.name,
                        ep.value,
                    )
                except Exception:
                    logger.warning(
                        "Skipping telemetry recorder plugin '%s' from %s.",
                        ep.name,
                        ep.value,
                        exc_info=True,
                    )
        finally:
            _PLUGINS_LOADED = True
