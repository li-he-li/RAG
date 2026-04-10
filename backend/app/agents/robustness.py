from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from app.services.analytics.telemetry import TelemetryService

T = TypeVar("T")


class RequestCancelled(asyncio.CancelledError):
    pass


@dataclass(slots=True)
class _IdempotentEntry:
    task: asyncio.Task[Any] | None
    result: Any = None
    expires_at: float = 0.0
    completed: bool = False


class IdempotentRequestCache:
    def __init__(self, *, ttl_seconds: float = 300.0) -> None:
        self.ttl_seconds = float(ttl_seconds)
        self._entries: dict[tuple[str, str], _IdempotentEntry] = {}
        self._lock = asyncio.Lock()

    @property
    def entry_count(self) -> int:
        self._evict_expired_now()
        return len(self._entries)

    async def run(
        self,
        session_id: str,
        request_hash: str,
        factory: Callable[[], Awaitable[T]],
    ) -> T:
        key = (session_id, request_hash)
        now = time.monotonic()
        async with self._lock:
            self._evict_expired_locked(now)
            existing = self._entries.get(key)
            if existing is not None:
                if existing.completed:
                    TelemetryService.instance().record_event(
                        "idempotent_cache_hit",
                        {"session_id": session_id, "request_hash": request_hash},
                    )
                    return existing.result
                task = existing.task
                TelemetryService.instance().record_event(
                    "idempotent_inflight_join",
                    {"session_id": session_id, "request_hash": request_hash},
                )
            else:
                task = asyncio.create_task(factory())
                self._entries[key] = _IdempotentEntry(task=task)

        if task is None:
            raise RuntimeError("idempotent task entry is missing")

        try:
            result = await task
        except Exception:
            async with self._lock:
                self._entries.pop(key, None)
            raise

        async with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.task is task:
                entry.result = result
                entry.task = None
                entry.completed = True
                entry.expires_at = time.monotonic() + self.ttl_seconds
        return result

    def clear(self) -> None:
        for entry in self._entries.values():
            if entry.task is not None and not entry.task.done():
                entry.task.cancel()
        self._entries.clear()

    def _evict_expired_now(self) -> None:
        self._evict_expired_locked(time.monotonic())

    def _evict_expired_locked(self, now: float) -> None:
        expired = [
            key
            for key, entry in self._entries.items()
            if entry.completed and entry.expires_at <= now
        ]
        for key in expired:
            self._entries.pop(key, None)


class RequestCancellationManager:
    def __init__(self, *, check_interval_seconds: float = 0.5) -> None:
        self.check_interval_seconds = float(check_interval_seconds)

    async def run(
        self,
        work: Awaitable[T],
        *,
        request_id: str,
        should_cancel: Callable[[], bool],
        cleanup: Callable[[], Awaitable[None]] | None = None,
    ) -> T:
        task = asyncio.create_task(work)
        try:
            while not task.done():
                if should_cancel():
                    task.cancel()
                    TelemetryService.instance().record_event(
                        "request_cancelled",
                        {"request_id": request_id},
                    )
                    if cleanup is not None:
                        await cleanup()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    raise RequestCancelled(f"request cancelled: {request_id}")
                await asyncio.sleep(self.check_interval_seconds)
            return await task
        except BaseException:
            if cleanup is not None and not task.cancelled() and should_cancel():
                await cleanup()
            raise


@dataclass(frozen=True, slots=True)
class TrackedTaskWarning:
    task_type: str
    duration_seconds: float
    context: dict[str, Any]


@dataclass(slots=True)
class _TrackedTask:
    task: asyncio.Task[Any]
    task_type: str
    created_at: float
    max_duration_seconds: float
    context: dict[str, Any]


class BackgroundTaskTracker:
    def __init__(self, *, default_max_duration_seconds: float = 60.0) -> None:
        self.default_max_duration_seconds = float(default_max_duration_seconds)
        self._tasks: set[asyncio.Task[Any]] = set()
        self._metadata: dict[asyncio.Task[Any], _TrackedTask] = {}

    @property
    def active_count(self) -> int:
        self._drop_finished()
        return len(self._tasks)

    def create_task(
        self,
        coro: Awaitable[Any],
        *,
        task_type: str,
        context: dict[str, Any] | None = None,
        max_duration_seconds: float | None = None,
    ) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        metadata = _TrackedTask(
            task=task,
            task_type=task_type,
            created_at=time.monotonic(),
            max_duration_seconds=(
                self.default_max_duration_seconds
                if max_duration_seconds is None
                else float(max_duration_seconds)
            ),
            context=dict(context or {}),
        )
        self._tasks.add(task)
        self._metadata[task] = metadata
        task.add_done_callback(self._forget)
        return task

    def detect_long_running(self, *, cancel_overdue: bool = False) -> list[TrackedTaskWarning]:
        self._drop_finished()
        now = time.monotonic()
        warnings: list[TrackedTaskWarning] = []
        for task in list(self._tasks):
            metadata = self._metadata[task]
            duration = now - metadata.created_at
            if duration <= metadata.max_duration_seconds:
                continue
            warning = TrackedTaskWarning(
                task_type=metadata.task_type,
                duration_seconds=duration,
                context=dict(metadata.context),
            )
            warnings.append(warning)
            TelemetryService.instance().record_event(
                "background_task_long_running",
                {
                    "task_type": warning.task_type,
                    "duration_seconds": warning.duration_seconds,
                    "context": warning.context,
                },
            )
            if cancel_overdue:
                task.cancel()
        return warnings

    async def shutdown(self, *, grace_period_seconds: float = 5.0) -> int:
        self._drop_finished()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=grace_period_seconds)
        force_cancelled = sum(1 for task in tasks if task.cancelled() or not task.done())
        self._drop_finished()
        TelemetryService.instance().record_event(
            "background_tasks_cancelled",
            {"count": force_cancelled},
        )
        return force_cancelled

    def _forget(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        self._metadata.pop(task, None)

    def _drop_finished(self) -> None:
        for task in list(self._tasks):
            if task.done():
                self._forget(task)


class DirtyStateCleaner:
    def __init__(self, *, temp_roots: Iterable[Path | str], ttl_seconds: float) -> None:
        self.temp_roots = tuple(Path(root) for root in temp_roots)
        self.ttl_seconds = float(ttl_seconds)

    def cleanup(
        self,
        *,
        active_session_ids: set[str],
        idempotent_cache: IdempotentRequestCache | None = None,
    ) -> list[Path]:
        if idempotent_cache is not None:
            idempotent_cache.clear()
        removed: list[Path] = []
        cutoff = time.time() - self.ttl_seconds
        for root in self.temp_roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if path.stat().st_mtime > cutoff:
                    continue
                if self._belongs_to_active_session(path, active_session_ids):
                    continue
                path.unlink()
                removed.append(path)
        return removed

    @staticmethod
    def _belongs_to_active_session(path: Path, active_session_ids: set[str]) -> bool:
        if not active_session_ids:
            return False
        parts = set(path.parts)
        return bool(parts.intersection(active_session_ids))


class RobustnessManager:
    def __init__(
        self,
        *,
        idempotent_cache: IdempotentRequestCache,
        task_tracker: BackgroundTaskTracker,
        dirty_state_cleaner: DirtyStateCleaner,
    ) -> None:
        self.idempotent_cache = idempotent_cache
        self.task_tracker = task_tracker
        self.dirty_state_cleaner = dirty_state_cleaner

    def schedule_startup_cleanup(self, *, active_session_ids: set[str]) -> asyncio.Task[Any]:
        async def _cleanup() -> list[Path]:
            return self.dirty_state_cleaner.cleanup(
                active_session_ids=active_session_ids,
                idempotent_cache=self.idempotent_cache,
            )

        return self.task_tracker.create_task(
            _cleanup(),
            task_type="startup_dirty_state_cleanup",
            context={"active_session_count": len(active_session_ids)},
        )


idempotent_request_cache = IdempotentRequestCache()
background_task_tracker = BackgroundTaskTracker()
