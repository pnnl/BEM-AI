"""Slash-command parsing for scheduler-facing clients."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from automa_ai.scheduler.intervals import IntervalParseError, parse_interval


@dataclass(frozen=True, slots=True)
class LoopCommand:
    """Parsed ``/loop`` command payload."""

    interval: str | None
    prompt: str | None


@dataclass(frozen=True, slots=True)
class TasksCommand:
    """Parsed ``/tasks`` command."""


@dataclass(frozen=True, slots=True)
class CancelCommand:
    """Parsed ``/cancel`` command payload."""

    task_id: str


def parse_scheduler_command(
    raw: str,
) -> LoopCommand | TasksCommand | CancelCommand | None:
    """Parse supported scheduler slash commands, returning ``None`` otherwise."""
    text = raw.strip()
    if not text.startswith("/"):
        return None

    if text == "/tasks":
        return TasksCommand()

    if text.startswith("/cancel"):
        parts = text.split(maxsplit=1)
        if len(parts) != 2 or not parts[1].strip():
            raise ValueError("/cancel requires a task id")
        return CancelCommand(task_id=parts[1].strip())

    if not text.startswith("/loop"):
        return None

    rest = text[len("/loop") :].strip()
    if not rest:
        return LoopCommand(interval=None, prompt=None)

    candidate, _, remainder = rest.partition(" ")
    try:
        parse_interval(candidate)
    except IntervalParseError:
        return LoopCommand(interval=None, prompt=rest)

    return LoopCommand(
        interval=candidate,
        prompt=remainder.strip() or None,
    )


def load_default_loop_prompt(
    *,
    project_root: str | Path | None = None,
    home_dir: str | Path | None = None,
) -> str | None:
    """Load the first available default loop prompt from project or user scope."""
    candidates: list[Path] = []

    if project_root is not None:
        candidates.append(Path(project_root) / ".automa" / "loop.md")

    if home_dir is None:
        home_dir = Path.home()
    candidates.append(Path(home_dir) / ".automa" / "loop.md")

    for path in candidates:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip() or None
    return None
