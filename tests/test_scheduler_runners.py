from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from automa_ai.scheduler import (
    LoopScheduler,
    build_a2a_loop_runner,
    build_local_agent_loop_runner,
)


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


class FakeAgent:
    def __init__(self) -> None:
        self.calls = []

    async def stream(
        self,
        query,
        context_id,
        task_id,
        user_id=None,
        metadata=None,
    ):
        self.calls.append(
            {
                "query": query,
                "context_id": context_id,
                "task_id": task_id,
                "user_id": user_id,
                "metadata": metadata,
            }
        )
        yield {"content": "working"}
        yield {"content": "done"}


class FakeClient:
    def __init__(self) -> None:
        self.calls = []

    async def send_streaming_message(self, message, context_id=None):
        self.calls.append({"message": message, "context_id": context_id})
        yield {"result": {"kind": "status-update"}}
        yield {"result": {"kind": "artifact-update"}}


@pytest.mark.asyncio
async def test_local_agent_loop_runner_reuses_context_and_emits_chunks() -> None:
    clock = MutableClock(datetime(2026, 5, 15, 12, 0, tzinfo=UTC))
    agent = FakeAgent()
    chunks = []
    scheduler = LoopScheduler(
        build_local_agent_loop_runner(
            agent,
            user_id="user-1",
            metadata_factory=lambda task: {"loop_task_id": task.id},
            on_chunk=lambda task, chunk: chunks.append((task.id, chunk["content"])),
        ),
        now_provider=clock,
    )
    scheduler.create_loop(
        prompt="check deployment",
        interval=timedelta(minutes=1),
        context_id="session-1",
        task_id="task-1",
    )

    clock.current = datetime(2026, 5, 15, 12, 1, tzinfo=UTC)
    await scheduler.run_due_tasks()

    assert agent.calls == [
        {
            "query": "check deployment",
            "context_id": "session-1",
            "task_id": "loop-task-1-1",
            "user_id": "user-1",
            "metadata": {"loop_task_id": "task-1"},
        }
    ]
    assert chunks == [("task-1", "working"), ("task-1", "done")]


@pytest.mark.asyncio
async def test_a2a_loop_runner_reuses_context_and_emits_chunks() -> None:
    clock = MutableClock(datetime(2026, 5, 15, 12, 0, tzinfo=UTC))
    client = FakeClient()
    chunks = []
    scheduler = LoopScheduler(
        build_a2a_loop_runner(
            client,
            on_chunk=lambda task, chunk: chunks.append(
                (task.id, chunk["result"]["kind"])
            ),
        ),
        now_provider=clock,
    )
    scheduler.create_loop(
        prompt="check queue",
        interval=timedelta(minutes=1),
        context_id="session-2",
        task_id="task-2",
    )

    clock.current = datetime(2026, 5, 15, 12, 1, tzinfo=UTC)
    await scheduler.run_due_tasks()

    assert client.calls == [{"message": "check queue", "context_id": "session-2"}]
    assert chunks == [
        ("task-2", "status-update"),
        ("task-2", "artifact-update"),
    ]
