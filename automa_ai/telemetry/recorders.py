"""Telemetry recorder implementations."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Protocol


class TelemetryRecorder(Protocol):
    def record(self, item: dict[str, Any]) -> None:
        """Record one telemetry item."""


class NoopRecorder:
    def record(self, item: dict[str, Any]) -> None:
        return None


class JsonlRecorder:
    """Append telemetry records to a local JSONL file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def record(self, item: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(item, default=str, ensure_ascii=False, sort_keys=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as file:
                file.write(f"{line}\n")
