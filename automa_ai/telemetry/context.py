"""Trace context storage."""

from __future__ import annotations

from contextvars import ContextVar


_trace_id: ContextVar[str | None] = ContextVar("automa_trace_id", default=None)
_span_id: ContextVar[str | None] = ContextVar("automa_span_id", default=None)


def current_trace_id() -> str | None:
    """Return the active trace id for the current async task, if one exists."""
    return _trace_id.get()


def current_span_id() -> str | None:
    """Return the active span id for the current async task, if one exists."""
    return _span_id.get()


def set_trace_context(*, trace_id: str, span_id: str | None = None):
    """Install an incoming or newly created trace context.

    The returned tokens must be passed to `reset_trace_context` in a `finally`
    block. `contextvars` tokens are what keep concurrent async agent turns from
    leaking trace ids into each other.
    """
    trace_token = _trace_id.set(trace_id)
    span_token = _span_id.set(span_id)
    return trace_token, span_token


def reset_trace_context(tokens) -> None:
    """Restore the trace/span values that were active before `set_trace_context`."""
    trace_token, span_token = tokens
    _span_id.reset(span_token)
    _trace_id.reset(trace_token)


def set_current_span(span_id: str):
    """Temporarily replace only the active span inside an existing trace."""
    return _span_id.set(span_id)


def reset_current_span(token) -> None:
    """Restore the parent span after a nested span exits."""
    _span_id.reset(token)
