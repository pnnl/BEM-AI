"""Telemetry recorder implementations."""

from __future__ import annotations

import json
import queue
import threading
import atexit
from pathlib import Path
from typing import Any, Protocol


class TelemetryRecorder(Protocol):
    def record(self, item: dict[str, Any]) -> None:
        """Record one telemetry item."""

    def flush(self) -> None:
        """Wait until records accepted so far are persisted."""

    def close(self) -> None:
        """Stop the recorder and release resources."""


class NoopRecorder:
    def record(self, item: dict[str, Any]) -> None:
        return None

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


class JsonlRecorder:
    """Append telemetry records to a local JSONL file from a writer thread."""

    _STOP = object()

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._queue: queue.Queue[dict[str, Any] | object] = queue.Queue()
        self._error: BaseException | None = None
        self._closed = False
        self._state_lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._writer_loop,
            name=f"automa-jsonl-telemetry:{self.path}",
            daemon=True,
        )
        self._thread.start()
        atexit.register(self._close_at_exit)

    def record(self, item: dict[str, Any]) -> None:
        with self._state_lock:
            if self._closed:
                raise RuntimeError("Cannot record telemetry after recorder is closed.")
            if self._error is not None:
                raise self._error
            self._queue.put(item)

    def flush(self) -> None:
        self._queue.join()
        if self._error is not None:
            raise self._error

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._queue.put(self._STOP)
        self._queue.join()
        self._thread.join(timeout=5)
        if self._error is not None:
            raise self._error

    def _close_at_exit(self) -> None:
        try:
            self.close()
        except Exception:
            return

    def _writer_loop(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is self._STOP:
                    return
                if self._error is None:
                    self._write_item(item)
            except BaseException as exc:
                self._error = exc
            finally:
                self._queue.task_done()

    def _write_item(self, item: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(item, default=str, ensure_ascii=False, sort_keys=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(f"{line}\n")
