from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from automa_ai.scheduler import LoopScheduler, LoopTaskStatus


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


async def _wait_until_scheduler_running(scheduler: LoopScheduler) -> None:
    for _ in range(20):
        if scheduler._stop_event is not None:
            return
        await asyncio.sleep(0)
    raise AssertionError("scheduler did not enter run_forever")


@pytest.mark.asyncio
async def test_scheduler_runs_due_tasks_and_advances_cadence() -> None:
    clock = MutableClock(datetime(2026, 5, 15, 12, 0, tzinfo=UTC))
    calls = []

    async def run_task(task) -> None:
        calls.append((task.id, task.prompt, task.context_id))

    scheduler = LoopScheduler(run_task, now_provider=clock)
    task = scheduler.create_loop(
        prompt="check deployment",
        interval=timedelta(minutes=5),
        context_id="session-1",
        task_id="task-1",
    )

    assert await scheduler.run_due_tasks() == []

    clock.current = datetime(2026, 5, 15, 12, 5, tzinfo=UTC)
    assert await scheduler.run_due_tasks() == [task]
    assert calls == [("task-1", "check deployment", "session-1")]
    assert task.run_count == 1
    assert task.last_run_at == datetime(2026, 5, 15, 12, 5, tzinfo=UTC)
    assert task.next_run_at == datetime(2026, 5, 15, 12, 10, tzinfo=UTC)

    clock.current = datetime(2026, 5, 15, 12, 22, tzinfo=UTC)
    assert await scheduler.run_due_tasks() == [task]
    assert task.run_count == 2
    assert task.next_run_at == datetime(2026, 5, 15, 12, 25, tzinfo=UTC)


@pytest.mark.asyncio
async def test_scheduler_serializes_concurrent_due_task_runs() -> None:
    clock = MutableClock(datetime(2026, 5, 15, 12, 0, tzinfo=UTC))
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def run_task(task) -> None:
        calls.append(task.id)
        started.set()
        await release.wait()

    scheduler = LoopScheduler(run_task, now_provider=clock)
    task = scheduler.create_loop(
        prompt="check deployment",
        interval=timedelta(minutes=1),
        context_id="session-1",
        task_id="task-1",
    )

    clock.current = datetime(2026, 5, 15, 12, 1, tzinfo=UTC)
    first_run = asyncio.create_task(scheduler.run_due_tasks())
    await started.wait()

    second_run = asyncio.create_task(scheduler.run_due_tasks())
    await asyncio.sleep(0)
    assert calls == ["task-1"]

    release.set()
    assert await first_run == [task]
    assert await second_run == []
    assert task.run_count == 1


@pytest.mark.asyncio
async def test_scheduler_records_errors_without_dropping_task() -> None:
    clock = MutableClock(datetime(2026, 5, 15, 12, 0, tzinfo=UTC))

    async def run_task(_task) -> None:
        raise RuntimeError("boom")

    scheduler = LoopScheduler(run_task, now_provider=clock)
    task = scheduler.create_loop(
        prompt="check",
        interval=timedelta(minutes=1),
        context_id="session-1",
        task_id="task-1",
    )

    clock.current = datetime(2026, 5, 15, 12, 1, tzinfo=UTC)
    await scheduler.run_due_tasks()

    assert task.run_count == 1
    assert task.last_error == "RuntimeError: boom"
    assert task.status == LoopTaskStatus.ACTIVE


@pytest.mark.asyncio
async def test_scheduler_cancels_and_expires_tasks() -> None:
    clock = MutableClock(datetime(2026, 5, 15, 12, 0, tzinfo=UTC))
    calls = []

    async def run_task(task) -> None:
        calls.append(task.id)

    scheduler = LoopScheduler(
        run_task,
        now_provider=clock,
        task_ttl=timedelta(minutes=2),
    )
    cancelled = scheduler.create_loop(
        prompt="cancel me",
        interval=timedelta(minutes=1),
        context_id="session-1",
        task_id="cancelled",
    )
    expired = scheduler.create_loop(
        prompt="expire me",
        interval=timedelta(minutes=5),
        context_id="session-1",
        task_id="expired",
    )

    assert scheduler.cancel(cancelled.id) is True
    assert scheduler.cancel(cancelled.id) is False

    clock.current = datetime(2026, 5, 15, 12, 3, tzinfo=UTC)
    assert await scheduler.run_due_tasks() == []

    assert cancelled.status == LoopTaskStatus.CANCELLED
    assert expired.status == LoopTaskStatus.EXPIRED
    assert calls == []


def test_scheduler_list_tasks_refreshes_expiry_before_filtering() -> None:
    clock = MutableClock(datetime(2026, 5, 15, 12, 0, tzinfo=UTC))

    async def run_task(_task) -> None:
        return None

    scheduler = LoopScheduler(
        run_task,
        now_provider=clock,
        task_ttl=timedelta(minutes=2),
    )
    task = scheduler.create_loop(
        prompt="expire me",
        interval=timedelta(minutes=5),
        context_id="session-1",
        task_id="task-1",
    )

    clock.current = datetime(2026, 5, 15, 12, 3, tzinfo=UTC)

    assert scheduler.list_tasks(active_only=True) == []
    assert scheduler.list_tasks() == [task]
    assert task.status == LoopTaskStatus.EXPIRED


def test_scheduler_cancel_refreshes_expiry_before_status_change() -> None:
    clock = MutableClock(datetime(2026, 5, 15, 12, 0, tzinfo=UTC))

    async def run_task(_task) -> None:
        return None

    scheduler = LoopScheduler(
        run_task,
        now_provider=clock,
        task_ttl=timedelta(minutes=2),
    )
    task = scheduler.create_loop(
        prompt="expire me",
        interval=timedelta(minutes=5),
        context_id="session-1",
        task_id="task-1",
    )

    clock.current = datetime(2026, 5, 15, 12, 3, tzinfo=UTC)

    assert scheduler.cancel(task.id) is False
    assert task.status == LoopTaskStatus.EXPIRED


@pytest.mark.asyncio
async def test_scheduler_run_forever_stops_when_requested() -> None:
    clock = MutableClock(datetime(2026, 5, 15, 12, 0, tzinfo=UTC))

    async def run_task(_task) -> None:
        return None

    scheduler = LoopScheduler(run_task, now_provider=clock)
    runner = asyncio.create_task(scheduler.run_forever(poll_interval_s=60))

    await _wait_until_scheduler_running(scheduler)
    scheduler.stop()

    await asyncio.wait_for(runner, timeout=1)
    assert scheduler._stop_event is None


@pytest.mark.asyncio
async def test_scheduler_run_forever_rejects_concurrent_runs() -> None:
    clock = MutableClock(datetime(2026, 5, 15, 12, 0, tzinfo=UTC))

    async def run_task(_task) -> None:
        return None

    scheduler = LoopScheduler(run_task, now_provider=clock)
    runner = asyncio.create_task(scheduler.run_forever(poll_interval_s=60))

    await _wait_until_scheduler_running(scheduler)
    with pytest.raises(RuntimeError, match="scheduler is already running"):
        await scheduler.run_forever(poll_interval_s=1)

    scheduler.stop()
    await asyncio.wait_for(runner, timeout=1)


@pytest.mark.asyncio
async def test_scheduler_run_forever_rejects_invalid_poll_interval() -> None:
    async def run_task(_task) -> None:
        return None

    scheduler = LoopScheduler(run_task)

    with pytest.raises(ValueError, match="poll_interval_s must be greater than zero"):
        await scheduler.run_forever(poll_interval_s=0)


def test_scheduler_requires_aware_timestamps() -> None:
    async def run_task(_task) -> None:
        return None

    scheduler = LoopScheduler(
        run_task,
        now_provider=lambda: datetime(2026, 5, 15, 12, 0),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        scheduler.create_loop(
            prompt="check",
            interval=timedelta(minutes=1),
            context_id="session-1",
        )
