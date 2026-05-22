"""Async execution engine for recurring prompt loops."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from automa_ai.scheduler.models import LoopTask, LoopTaskStatus

LoopTaskRunner = Callable[[LoopTask], Awaitable[None]]
NowProvider = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class LoopScheduler:
    """Manage session-scoped recurring prompt tasks."""

    def __init__(
        self,
        task_runner: LoopTaskRunner,
        *,
        now_provider: NowProvider = _utc_now,
        task_ttl: timedelta = timedelta(days=7),
    ) -> None:
        if task_ttl <= timedelta(0):
            raise ValueError("task_ttl must be greater than zero")
        self._task_runner = task_runner
        self._now = now_provider
        self._task_ttl = task_ttl
        self._tasks: dict[str, LoopTask] = {}
        self._stop_event: asyncio.Event | None = None
        self._run_lock = asyncio.Lock()

    def create_loop(
        self,
        *,
        prompt: str,
        interval: timedelta,
        context_id: str,
        task_id: str | None = None,
    ) -> LoopTask:
        """Create one recurring loop task."""
        if not prompt.strip():
            raise ValueError("prompt cannot be empty")
        if interval <= timedelta(0):
            raise ValueError("interval must be greater than zero")
        if not context_id.strip():
            raise ValueError("context_id cannot be empty")

        now = self._current_time()
        resolved_task_id = task_id or uuid4().hex
        if resolved_task_id in self._tasks:
            raise ValueError(f"task id already exists: {resolved_task_id}")

        task = LoopTask(
            id=resolved_task_id,
            prompt=prompt.strip(),
            interval=interval,
            context_id=context_id,
            created_at=now,
            next_run_at=now + interval,
            expires_at=now + self._task_ttl,
        )
        self._tasks[task.id] = task
        return task

    def list_tasks(self, *, active_only: bool = False) -> list[LoopTask]:
        """Return known tasks in creation order."""
        self._refresh_expired_tasks()
        tasks = list(self._tasks.values())
        if active_only:
            tasks = [task for task in tasks if task.is_active]
        return tasks

    def get_task(self, task_id: str) -> LoopTask | None:
        """Return one task by id."""
        return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> bool:
        """Cancel an active task, returning whether it existed and changed."""
        task = self._tasks.get(task_id)
        if task is not None:
            # Keep manual cancellation consistent with scheduler polling: an
            # elapsed TTL wins over a late cancel request.
            self._expire_if_needed(task, self._current_time())
        if task is None or not task.is_active:
            return False
        task.status = LoopTaskStatus.CANCELLED
        return True

    async def run_due_tasks(self) -> list[LoopTask]:
        """Execute due tasks once and return the tasks that were attempted."""
        async with self._run_lock:
            now = self._current_time()
            attempted: list[LoopTask] = []

            for task in self._tasks.values():
                self._expire_if_needed(task, now)
                if not task.is_active or task.next_run_at > now:
                    continue

                attempted.append(task)
                try:
                    await self._task_runner(task)
                except Exception as exc:
                    task.last_error = f"{type(exc).__name__}: {exc}"
                else:
                    task.last_error = None
                finally:
                    task.run_count += 1
                    task.last_run_at = now
                    task.next_run_at = self._next_scheduled_time(task, now)
                    self._expire_if_needed(task, now)

            return attempted

    async def run_forever(self, *, poll_interval_s: float = 1.0) -> None:
        """Poll for due tasks until ``stop`` is called."""
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be greater than zero")
        if self._stop_event is not None:
            raise RuntimeError("scheduler is already running")

        self._stop_event = asyncio.Event()
        try:
            while not self._stop_event.is_set():
                await self.run_due_tasks()
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=poll_interval_s,
                    )
                except TimeoutError:
                    continue
        finally:
            self._stop_event = None

    def stop(self) -> None:
        """Request shutdown of ``run_forever``."""
        if self._stop_event is not None:
            self._stop_event.set()

    def _current_time(self) -> datetime:
        """Return the scheduler clock normalized to aware UTC."""
        return self._coerce_aware_utc(self._now())

    def _refresh_expired_tasks(self) -> None:
        """Apply TTL expiry before read-only views expose task status."""
        now = self._current_time()
        for task in self._tasks.values():
            self._expire_if_needed(task, now)

    @staticmethod
    def _coerce_aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("scheduler timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @staticmethod
    def _next_scheduled_time(task: LoopTask, now: datetime) -> datetime:
        next_run_at = task.next_run_at
        if next_run_at > now:
            return next_run_at

        overdue = now - next_run_at
        intervals_to_advance = overdue // task.interval + 1
        return next_run_at + intervals_to_advance * task.interval

    @staticmethod
    def _expire_if_needed(task: LoopTask, now: datetime) -> None:
        if task.is_active and task.expires_at <= now:
            task.status = LoopTaskStatus.EXPIRED
