from __future__ import annotations

import inspect
from collections.abc import Iterable
from typing import Any, Protocol

from automa_ai.hook.turn import TurnRequest, TurnResult


class AgentTurnHook(Protocol):
    """Lifecycle hook for agent turns."""

    async def before_turn(self, turn: TurnRequest) -> TurnRequest | None:
        ...

    async def after_turn(self, turn: TurnRequest, result: TurnResult) -> None:
        ...

    async def on_turn_error(self, turn: TurnRequest, error: BaseException) -> None:
        ...


async def _maybe_await(value: Any) -> Any:
    """Return plain values directly and await coroutine-like hook results."""
    if inspect.isawaitable(value):
        return await value
    return value


class HookRunner:
    """Runs agent turn hooks in registration order."""

    def __init__(self, hooks: Iterable[AgentTurnHook] | None = None) -> None:
        self._hooks = list(hooks or [])

    @classmethod
    def empty(cls) -> "HookRunner":
        """Return a runner with no registered hooks."""
        return cls()

    async def before_turn(self, turn: TurnRequest) -> TurnRequest:
        """Run before-turn hooks, allowing each hook to replace the turn."""
        current = turn
        for hook in self._hooks:
            before = getattr(hook, "before_turn", None)
            if not callable(before):
                continue
            updated = await _maybe_await(before(current))
            if updated is not None:
                current = updated
        return current

    async def after_turn(self, turn: TurnRequest, result: TurnResult) -> None:
        """Run after-turn hooks with the stable ``TurnResult`` contract."""
        for hook in self._hooks:
            after = getattr(hook, "after_turn", None)
            if callable(after):
                await _maybe_await(after(turn, result))

    async def on_turn_error(self, turn: TurnRequest, error: BaseException) -> None:
        """Run error hooks after a turn has failed."""
        for hook in self._hooks:
            on_error = getattr(hook, "on_turn_error", None)
            if callable(on_error):
                await _maybe_await(on_error(turn, error))
