from __future__ import annotations

import logging
from typing import Any

from automa_ai.hook.context import (
    ContextPipeline,
    MemoryContextProvider,
    RetrieverContextProvider,
)
from automa_ai.hook.hooks import HookRunner
from automa_ai.hook.input_assembler import InputAssembler
from automa_ai.hook.turn import TurnInputs, TurnRequest


class TurnInputBuilder:
    """Coordinates hooks, context collection, and LangGraph input assembly."""

    def __init__(
        self,
        *,
        hook_runner: HookRunner | None = None,
        context_pipeline: ContextPipeline | None = None,
        input_assembler: InputAssembler | None = None,
    ) -> None:
        self.hook_runner = hook_runner or HookRunner.empty()
        self.context_pipeline = context_pipeline or ContextPipeline.empty()
        self.input_assembler = input_assembler or InputAssembler()

    @classmethod
    def default(
        cls,
        *,
        retriever: Any | None = None,
        memory_manager: Any | None = None,
        hook_runner: HookRunner | None = None,
        context_pipeline: ContextPipeline | None = None,
        input_assembler: InputAssembler | None = None,
        logger: logging.Logger | None = None,
        debug: bool = False,
    ) -> "TurnInputBuilder":
        if context_pipeline is None:
            providers = []
            if retriever is not None:
                providers.append(
                    RetrieverContextProvider(
                        retriever,
                        logger=logger,
                        debug=debug,
                    )
                )
            if memory_manager is not None:
                providers.append(
                    MemoryContextProvider(
                        memory_manager,
                        logger=logger,
                        debug=debug,
                    )
                )
            context_pipeline = ContextPipeline(providers)

        return cls(
            hook_runner=hook_runner,
            context_pipeline=context_pipeline,
            input_assembler=input_assembler,
        )

    async def build_inputs(
        self,
        *,
        query: str,
        context_id: str,
        task_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TurnInputs:
        turn = TurnRequest(
            query=query,
            context_id=context_id,
            task_id=task_id,
            user_id=user_id,
            metadata=metadata or {},
        )
        turn = await self.hook_runner.before_turn(turn)
        context_blocks = await self.context_pipeline.collect(turn)
        inputs = self.input_assembler.build(
            turn=turn,
            context_blocks=context_blocks,
        )
        return TurnInputs(turn=turn, inputs=inputs)

    async def after_turn(self, turn: TurnRequest, result: Any) -> None:
        await self.hook_runner.after_turn(turn, result)

    async def on_turn_error(self, turn: TurnRequest, error: BaseException) -> None:
        await self.hook_runner.on_turn_error(turn, error)
