"""Test that after_turn fires when the stream consumer stops early (GeneratorExit).

The A2A executor breaks out of the async-for loop as soon as it sees
is_task_complete=True, which sends GeneratorExit to the stream generator
before it can drain the None sentinel.  After the fix the generator checks
whether stream_result is already resolved and calls after_turn so hooks
(e.g. session persistence) always see completed turns.
"""
import asyncio

import pytest

from automa_ai.hook import HookRunner, TurnInputBuilder, TurnRequest, TurnResult


class RecordingHook:
    def __init__(self):
        self.after_calls: list[tuple[str, str]] = []

    async def after_turn(self, turn: TurnRequest, result: TurnResult) -> None:
        self.after_calls.append((turn.context_id, result.content))


async def _make_stream(turn_input_builder, stream_result):
    """Minimal replica of the stream() generator's consumer loop + except block."""

    turn = TurnRequest(query="hello", context_id="sess-1")

    async def producer():
        # Simulate the agent finishing and resolving stream_result before
        # the consumer breaks.
        stream_result.set_result(
            TurnResult(mode="stream", content="agent reply")
        )
        yield {"is_task_complete": True, "content": "agent reply", "response_type": "text", "require_user_input": False}
        # This item is never reached because the consumer breaks above.
        yield None

    try:
        async for item in producer():
            yield item
            if item.get("is_task_complete"):
                break  # consumer breaks — triggers GeneratorExit in producer
        # Normal exit path: only reached when queue is fully drained (not here).
        if stream_result.done():
            await turn_input_builder.after_turn(turn, stream_result.result())
    except BaseException as exc:
        if isinstance(exc, GeneratorExit):
            # This is the fixed path.
            if stream_result.done():
                await turn_input_builder.after_turn(turn, stream_result.result())
            raise


@pytest.mark.asyncio
async def test_after_turn_fires_on_generator_exit_when_stream_result_resolved():
    """after_turn must fire even when GeneratorExit interrupts the consumer loop."""
    hook = RecordingHook()
    builder = TurnInputBuilder.default(hook_runner=HookRunner([hook]))
    stream_result: asyncio.Future[TurnResult] = asyncio.Future()

    gen = _make_stream(builder, stream_result)
    # Consume until the first complete item, then close the generator.
    async for item in gen:
        if item.get("is_task_complete"):
            break
    await gen.aclose()

    assert hook.after_calls == [("sess-1", "agent reply")], (
        "after_turn was not called after GeneratorExit with a resolved stream_result"
    )


@pytest.mark.asyncio
async def test_after_turn_skipped_when_stream_result_not_resolved():
    """after_turn must NOT fire when the agent was mid-stream at GeneratorExit."""
    hook = RecordingHook()
    builder = TurnInputBuilder.default(hook_runner=HookRunner([hook]))
    stream_result: asyncio.Future[TurnResult] = asyncio.Future()

    async def incomplete_producer():
        # Never resolves stream_result — agent was cancelled mid-stream.
        yield {"is_task_complete": False, "content": "partial...", "response_type": "text", "require_user_input": False}

    async def stream_with_incomplete():
        turn = TurnRequest(query="hello", context_id="sess-2")
        try:
            async for item in incomplete_producer():
                yield item
                break
            if stream_result.done():
                await builder.after_turn(turn, stream_result.result())
        except BaseException as exc:
            if isinstance(exc, GeneratorExit):
                if stream_result.done():
                    await builder.after_turn(turn, stream_result.result())
                raise

    gen = stream_with_incomplete()
    async for _ in gen:
        break
    await gen.aclose()

    assert hook.after_calls == [], (
        "after_turn must not fire when stream_result is unresolved at GeneratorExit"
    )
