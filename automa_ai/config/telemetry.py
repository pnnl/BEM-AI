"""Configuration for AUTOMA-AI telemetry."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class TelemetryConfig(BaseModel):
    """Declarative telemetry configuration.

    The built-in implementation is intentionally local-first. It uses an
    OpenTelemetry-shaped trace/span/event model without requiring an
    OpenTelemetry collector or AWS service during local development.
    """

    enabled: bool = False
    recorder: Literal["noop", "jsonl", "otel"] = "noop"
    path: str | None = None
    content_mode: Literal["off", "metadata", "redacted", "raw"] = "metadata"
    max_content_chars: int = Field(default=4000, ge=0)
    service_name: str = "automa-ai"
    environment: str = "local"
    debug: bool = False
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("path")
    @classmethod
    def _normalize_path(cls, value: str | None) -> str | None:
        """Treat blank path strings as unset so defaults can apply cleanly."""
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @classmethod
    def from_value(
        cls, value: "TelemetryConfig" | dict[str, Any] | str | None
    ) -> "TelemetryConfig":
        """Normalize all public config entry shapes to `TelemetryConfig`."""
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(enabled=True, recorder=value)
        return cls.model_validate(value)

    def resolved_path(self, *, base_dir: str | Path | None = None) -> Path | None:
        """Resolve a JSONL path relative to a YAML spec or caller-provided base."""
        if not self.path:
            return None
        path = Path(self.path)
        if not path.is_absolute() and base_dir is not None:
            path = Path(base_dir) / path
        return path
