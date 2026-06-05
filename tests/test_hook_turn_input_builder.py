import asyncio

import pytest

from automa_ai.hook import (
    ContextBlock,
    ContextPipeline,
    HookRunner,
    TurnInputBuilder,
    TurnRequest,
    TurnResult,
    build_turn_input_builder_from_config,
)


class PrefixHook:
    async def before_turn(self, turn: TurnRequest) -> TurnRequest:
        return turn.with_updates(query=f"prefix: {turn.query}")


class ContextIdChangingHook:
    async def before_turn(self, turn: TurnRequest) -> TurnRequest:
        return turn.with_updates(context_id="other-session")


class FailingBeforeHook:
    async def before_turn(self, turn: TurnRequest) -> TurnRequest:
        raise RuntimeError("before failed")


class CancellingBeforeHook:
    async def before_turn(self, turn: TurnRequest) -> TurnRequest:
        raise asyncio.CancelledError()


class RecordingHook:
    def __init__(self) -> None:
        self.after_result = None
        self.error = None

    async def after_turn(self, turn: TurnRequest, result):
        self.after_result = (turn.query, result)

    async def on_turn_error(self, turn: TurnRequest, error: BaseException):
        self.error = (turn.query, type(error).__name__)


class FailingAfterHook:
    async def after_turn(self, turn: TurnRequest, result: TurnResult):
        raise RuntimeError("after failed")

    async def on_turn_error(self, turn: TurnRequest, error: BaseException):
        raise AssertionError("after_turn failure should not call on_turn_error")


class FailingErrorHook:
    async def on_turn_error(self, turn: TurnRequest, error: BaseException):
        raise RuntimeError("error hook failed")


class CancellingErrorHook:
    async def on_turn_error(self, turn: TurnRequest, error: BaseException):
        raise asyncio.CancelledError()


class StaticContextProvider:
    async def collect(self, turn: TurnRequest):
        return ContextBlock(
            name="static",
            content=f"context for {turn.query}",
            priority=50,
        )


class FailingContextProvider:
    async def collect(self, turn: TurnRequest):
        raise RuntimeError("context failed")


@pytest.mark.asyncio
async def test_turn_input_builder_runs_hooks_context_and_assembler():
    builder = TurnInputBuilder.default(
        hook_runner=HookRunner([PrefixHook()]),
        context_pipeline=ContextPipeline([StaticContextProvider()]),
    )

    turn_inputs = await builder.build_inputs(
        query="hello",
        context_id="session-1",
        metadata={"source": "test"},
    )

    assert turn_inputs.turn.query == "prefix: hello"
    assert turn_inputs.inputs == {
        "messages": [
            {"role": "system", "content": "context for prefix: hello"},
            {"role": "user", "content": "prefix: hello"},
        ]
    }


@pytest.mark.asyncio
async def test_turn_input_builder_exposes_after_and_error_hooks():
    hook = RecordingHook()
    builder = TurnInputBuilder.default(hook_runner=HookRunner([hook]))
    turn = TurnRequest(query="hello", context_id="session-1")
    result = TurnResult(mode="invoke", content="ok", raw_response={"ok": True})

    await builder.after_turn(turn, result)
    await builder.on_turn_error(turn, RuntimeError("bad"))

    assert hook.after_result == ("hello", result)
    assert hook.error == ("hello", "RuntimeError")


@pytest.mark.asyncio
async def test_turn_input_builder_after_turn_failure_is_best_effort():
    builder = TurnInputBuilder.default(hook_runner=HookRunner([FailingAfterHook()]))
    turn = TurnRequest(query="hello", context_id="session-1")
    result = TurnResult(mode="invoke", content="ok")

    await builder.after_turn(turn, result)


@pytest.mark.asyncio
async def test_turn_input_builder_reports_before_turn_failures_to_error_hooks():
    recorder = RecordingHook()
    builder = TurnInputBuilder.default(
        hook_runner=HookRunner([FailingBeforeHook(), recorder]),
    )

    with pytest.raises(RuntimeError, match="before failed"):
        await builder.build_inputs(query="hello", context_id="session-1")

    assert recorder.error == ("hello", "RuntimeError")


@pytest.mark.asyncio
async def test_turn_input_builder_error_hook_failure_preserves_original_error():
    builder = TurnInputBuilder.default(
        hook_runner=HookRunner([FailingBeforeHook(), FailingErrorHook()]),
    )

    with pytest.raises(RuntimeError, match="before failed"):
        await builder.build_inputs(query="hello", context_id="session-1")


@pytest.mark.asyncio
async def test_turn_input_builder_error_hook_cancellation_propagates():
    builder = TurnInputBuilder.default(
        hook_runner=HookRunner([CancellingErrorHook()]),
    )
    turn = TurnRequest(query="hello", context_id="session-1")

    with pytest.raises(asyncio.CancelledError):
        await builder.on_turn_error(turn, RuntimeError("bad"))


@pytest.mark.asyncio
async def test_turn_input_builder_does_not_run_error_hooks_on_cancellation():
    recorder = RecordingHook()
    builder = TurnInputBuilder.default(
        hook_runner=HookRunner([CancellingBeforeHook(), recorder]),
    )

    with pytest.raises(asyncio.CancelledError):
        await builder.build_inputs(query="hello", context_id="session-1")

    assert recorder.error is None


@pytest.mark.asyncio
async def test_turn_input_builder_rejects_context_id_mutation():
    recorder = RecordingHook()

    builder = TurnInputBuilder.default(
        hook_runner=HookRunner([ContextIdChangingHook(), recorder]),
        context_pipeline=ContextPipeline([StaticContextProvider()]),
    )

    with pytest.raises(ValueError, match="must not mutate context_id"):
        await builder.build_inputs(
            query="hello",
            context_id="session-1",
        )

    assert recorder.error == ("hello", "ValueError")


@pytest.mark.asyncio
async def test_turn_input_builder_degrades_context_failures_with_updated_turn():
    recorder = RecordingHook()
    provider_errors: list[tuple[str, str, str]] = []

    async def context_error_handler(provider, error, turn):
        provider_errors.append(
            (provider.__class__.__name__, type(error).__name__, turn.query)
        )

    builder = TurnInputBuilder.default(
        hook_runner=HookRunner([PrefixHook(), recorder]),
        context_pipeline=ContextPipeline([FailingContextProvider()]),
    )

    turn_inputs = await builder.build_inputs(
        query="hello",
        context_id="session-1",
        context_error_handler=context_error_handler,
    )

    assert turn_inputs.inputs == {
        "messages": [{"role": "user", "content": "prefix: hello"}]
    }
    assert turn_inputs.degraded is True
    assert turn_inputs.missing_providers == ["FailingContextProvider"]
    assert recorder.error is None
    assert provider_errors == [
        ("FailingContextProvider", "RuntimeError", "prefix: hello")
    ]


@pytest.mark.asyncio
async def test_turn_input_builder_keeps_degraded_turn_when_error_handler_fails():
    def context_error_handler(provider, error, turn):
        raise RuntimeError("telemetry failed")

    builder = TurnInputBuilder.default(
        context_pipeline=ContextPipeline([FailingContextProvider()]),
    )

    turn_inputs = await builder.build_inputs(
        query="hello",
        context_id="session-1",
        context_error_handler=context_error_handler,
    )

    assert turn_inputs.inputs == {
        "messages": [{"role": "user", "content": "hello"}]
    }
    assert turn_inputs.degraded is True
    assert turn_inputs.missing_providers == ["FailingContextProvider"]


@pytest.mark.asyncio
async def test_turn_input_builder_runs_context_after_before_turn():
    events: list[str] = []

    class RecordingContextProvider:
        async def collect(self, turn: TurnRequest):
            events.append(f"context:{turn.query}")
            return ContextBlock(name="recorded", content="context")

    builder = TurnInputBuilder.default(
        hook_runner=HookRunner([PrefixHook()]),
        context_pipeline=ContextPipeline([RecordingContextProvider()]),
    )

    await builder.build_inputs(
        query="hello",
        context_id="session-1",
    )

    assert events == ["context:prefix: hello"]


@pytest.mark.asyncio
async def test_build_turn_input_builder_from_config_imports_components():
    builder = build_turn_input_builder_from_config(
        {
            "include_default_context": False,
            "turn_hooks": [
                {"impl": "tests.test_hook_turn_input_builder:PrefixHook"}
            ],
            "context_providers": [
                {
                    "impl": (
                        "tests.test_hook_turn_input_builder:"
                        "StaticContextProvider"
                    )
                }
            ],
        }
    )

    turn_inputs = await builder.build_inputs(
        query="hello",
        context_id="session-1",
    )

    assert turn_inputs.inputs["messages"][0]["content"] == (
        "context for prefix: hello"
    )
