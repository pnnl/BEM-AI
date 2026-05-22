"""Slash-command parsing for scheduler-facing clients."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex

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
        remainder = text[len("/cancel") :]
        if not remainder:
            raise ValueError("/cancel requires a task id")
        if not remainder[0].isspace():
            return None
        task_id = remainder.strip()
        if not task_id:
            raise ValueError("/cancel requires a task id")
        return CancelCommand(task_id=task_id)

    if not text.startswith("/loop"):
        return None
    if len(text) > len("/loop") and not text[len("/loop")].isspace():
        return None

    rest = text[len("/loop") :].strip()
    if not rest:
        return LoopCommand(interval=None, prompt=None)

    return _parse_loop_command(rest)


def _parse_loop_command(raw_args: str) -> LoopCommand:
    """Parse ``/loop`` arguments without guessing interval boundaries."""
    try:
        # shlex lets callers quote multi-word interval/prompt values while still
        # supporting unquoted forms like: --interval every 10 minutes --prompt check.
        tokens = shlex.split(raw_args)
    except ValueError as exc:
        raise ValueError(f"invalid /loop arguments: {exc}") from exc

    interval: str | None = None
    prompt: str | None = None
    positional_prompt: list[str] = []
    saw_option = False
    index = 0

    while index < len(tokens):
        token = tokens[index]
        if token in {"--interval", "-i"}:
            if interval is not None:
                raise ValueError("/loop interval was provided more than once")
            saw_option = True
            interval_tokens, index = _consume_option_value(tokens, index + 1)
            interval = " ".join(interval_tokens)
            try:
                parse_interval(interval)
            except IntervalParseError as exc:
                raise ValueError(f"invalid /loop interval: {interval}") from exc
            continue

        if token in {"--prompt", "-p"}:
            if prompt is not None:
                raise ValueError("/loop prompt was provided more than once")
            saw_option = True
            prompt_tokens, index = _consume_option_value(tokens, index + 1)
            prompt = " ".join(prompt_tokens)
            continue

        if token.startswith("-"):
            raise ValueError(f"unsupported /loop option: {token}")

        positional_prompt.append(token)
        index += 1

    if positional_prompt and saw_option:
        raise ValueError("unexpected /loop text; pass prompt text with --prompt")

    if positional_prompt:
        prompt = " ".join(positional_prompt)

    return LoopCommand(
        interval=interval,
        prompt=prompt or None,
    )


def _consume_option_value(tokens: list[str], start: int) -> tuple[list[str], int]:
    """Return tokens for one option value, stopping at the next known option."""
    value: list[str] = []
    index = start
    while index < len(tokens):
        # Values may contain spaces, so consume multiple tokens until another
        # supported option starts. This intentionally allows prompt text such as
        # "--status" without requiring extra escaping.
        if tokens[index] in {"--interval", "-i", "--prompt", "-p"}:
            break
        value.append(tokens[index])
        index += 1

    if not value:
        raise ValueError(f"{tokens[start - 1]} requires a value")
    return value, index


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
