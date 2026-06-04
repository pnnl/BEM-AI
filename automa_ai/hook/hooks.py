from __future__ import annotations

import inspect
from collections.abc import Iterable
from typing import Any, Protocol

from automa_ai.hook.turn import TurnRequest


class AgentTurnHook(Protocol):
    """Lifecycle hook for agent turns."""

    async def before_turn(self, turn: TurnRequest) -> TurnRequest | None:
        ...

    async def after_turn(self, turn: TurnRequest, result: Any) -> None:
        ...

    async def on_turn_error(self, turn: TurnRequest, error: BaseException) -> None:
        ...


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class HookRunner:
    """Runs agent turn hooks in registration order."""

    def __init__(self, hooks: Iterable[AgentTurnHook] | None = None) -> None:
        self._hooks = list(hooks or [])

    @classmethod
    def empty(cls) -> "HookRunner":
        return cls()

    async def before_turn(self, turn: TurnRequest) -> TurnRequest:
        current = turn
        for hook in self._hooks:
            before = getattr(hook, "before_turn", None)
            if not callable(before):
                continue
            updated = await _maybe_await(before(current))
            if updated is not None:
                current = updated
        return current

    async def after_turn(self, turn: TurnRequest, result: Any) -> None:
        for hook in self._hooks:
            after = getattr(hook, "after_turn", None)
            if callable(after):
                await _maybe_await(after(turn, result))

    async def on_turn_error(self, turn: TurnRequest, error: BaseException) -> None:
        for hook in self._hooks:
            on_error = getattr(hook, "on_turn_error", None)
            if callable(on_error):
                await _maybe_await(on_error(turn, error))
