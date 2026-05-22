"""Adapters that connect scheduled loop tasks to AUTOMA-AI runtimes."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from automa_ai.client.simple_client import SimpleClient
from automa_ai.common.base_agent import BaseAgent
from automa_ai.scheduler.models import LoopTask
from automa_ai.scheduler.runner import LoopTaskRunner

LoopChunkHandler = Callable[[LoopTask, Any], Awaitable[None] | None]
MetadataFactory = Callable[[LoopTask], dict[str, Any] | None]


def build_local_agent_loop_runner(
    agent: BaseAgent,
    *,
    user_id: str | None = None,
    metadata_factory: MetadataFactory | None = None,
    on_chunk: LoopChunkHandler | None = None,
) -> LoopTaskRunner:
    """Build a scheduler callback that reuses a local agent session."""

    async def run_task(task: LoopTask) -> None:
        task_id = f"loop-{task.id}-{task.run_count + 1}"
        metadata = metadata_factory(task) if metadata_factory else None
        async for chunk in agent.stream(
            task.prompt,
            task.context_id,
            task_id,
            user_id=user_id,
            metadata=metadata,
        ):
            await _emit_chunk(on_chunk, task, chunk)

    return run_task


def build_a2a_loop_runner(
    client: SimpleClient,
    *,
    on_chunk: LoopChunkHandler | None = None,
) -> LoopTaskRunner:
    """Build a scheduler callback that sends prompts through an A2A client."""

    async def run_task(task: LoopTask) -> None:
        async for chunk in client.send_streaming_message(
            task.prompt,
            context_id=task.context_id,
        ):
            await _emit_chunk(on_chunk, task, chunk)

    return run_task


async def _emit_chunk(
    handler: LoopChunkHandler | None,
    task: LoopTask,
    chunk: Any,
) -> None:
    if handler is None:
        return
    result = handler(task, chunk)
    if inspect.isawaitable(result):
        await result
