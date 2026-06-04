from __future__ import annotations

import logging
from typing import Any

from automa_ai.hook.context import (
    ContextPipeline,
    ContextProviderErrorHandler,
    MemoryContextProvider,
    RetrieverContextProvider,
)
from automa_ai.hook.hooks import HookRunner
from automa_ai.hook.input_assembler import InputAssembler
from automa_ai.hook.turn import TurnInputs, TurnRequest, TurnResult

logger = logging.getLogger(__name__)


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
        """Build the default pipeline, preserving existing retriever/memory behavior."""
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
        context_error_handler: ContextProviderErrorHandler | None = None,
    ) -> TurnInputs:
        """Run hooks, collect context, and assemble LangGraph inputs."""
        turn = TurnRequest(
            query=query,
            context_id=context_id,
            task_id=task_id,
            user_id=user_id,
            metadata=metadata or {},
        )
        try:
            original_context_id = turn.context_id
            turn = await self.hook_runner.before_turn(turn)
            self._validate_context_id_unchanged(
                original_context_id=original_context_id,
                turn=turn,
            )
            context_collection = await self.context_pipeline.collect(
                turn,
                on_provider_error=context_error_handler,
            )
            inputs = self.input_assembler.build(
                turn=turn,
                context_blocks=context_collection.blocks,
            )
            return TurnInputs(
                turn=turn,
                inputs=inputs,
                degraded=context_collection.degraded,
                missing_providers=context_collection.missing_providers,
            )
        except Exception as exc:
            # Setup failures happen before agent invoke/stream owns an updated
            # turn, so the builder is the only layer that can consistently
            # notify error hooks for before_turn and assembler failures.
            # Individual context-provider failures are degraded inside
            # ContextPipeline.collect so a missing retrieval/memory block does
            # not abort the turn.
            # Cancellation and process-exit BaseExceptions must propagate
            # without awaiting arbitrary user hook code during teardown.
            await self.on_turn_error(turn, exc)
            raise

    @staticmethod
    def _validate_context_id_unchanged(
        *,
        original_context_id: str,
        turn: TurnRequest,
    ) -> None:
        """Reject hooks that rewrite the session identity for a turn."""
        if turn.context_id != original_context_id:
            raise ValueError(
                "before_turn hooks must not mutate context_id. "
                f"Got {turn.context_id!r}; expected {original_context_id!r}."
            )

    async def after_turn(self, turn: TurnRequest, result: TurnResult) -> None:
        """Dispatch a completed turn result to lifecycle hooks.

        After-turn hooks are side effects. They must not convert a successful
        agent response into a failed user turn.
        """
        try:
            await self.hook_runner.after_turn(turn, result)
        except Exception:
            logger.exception(
                "after_turn hook failed for session %s; preserving agent result.",
                turn.context_id,
            )

    async def on_turn_error(self, turn: TurnRequest, error: BaseException) -> None:
        """Dispatch a turn failure to lifecycle hooks.

        Error hooks are best-effort and must not mask the original exception.
        """
        try:
            await self.hook_runner.on_turn_error(turn, error)
        except Exception:
            logger.exception(
                "on_turn_error hook failed for session %s; preserving original error.",
                turn.context_id,
            )
