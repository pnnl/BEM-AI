import pytest

from automa_ai.hook import (
    ContextBlock,
    ContextPipeline,
    HookRunner,
    TurnInputBuilder,
    TurnRequest,
    build_turn_input_builder_from_config,
)


class PrefixHook:
    async def before_turn(self, turn: TurnRequest) -> TurnRequest:
        return turn.with_updates(query=f"prefix: {turn.query}")


class RecordingHook:
    def __init__(self) -> None:
        self.after_result = None
        self.error = None

    async def after_turn(self, turn: TurnRequest, result):
        self.after_result = (turn.query, result)

    async def on_turn_error(self, turn: TurnRequest, error: BaseException):
        self.error = (turn.query, type(error).__name__)


class StaticContextProvider:
    async def collect(self, turn: TurnRequest):
        return ContextBlock(
            name="static",
            content=f"context for {turn.query}",
            priority=50,
        )


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

    await builder.after_turn(turn, {"ok": True})
    await builder.on_turn_error(turn, RuntimeError("bad"))

    assert hook.after_result == ("hello", {"ok": True})
    assert hook.error == ("hello", "RuntimeError")


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
