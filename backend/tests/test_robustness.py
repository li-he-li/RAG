from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

import pytest

from app.agents.robustness import (
    BackgroundTaskTracker,
    DirtyStateCleaner,
    IdempotentRequestCache,
    RequestCancelled,
    RequestCancellationManager,
    RobustnessManager,
)
from app.services.analytics.telemetry import TelemetryService


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _workspace_path(name: str) -> Path:
    workspace = Path("test-workspace") / "robustness"
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / name
    if path.exists() and path.is_file():
        path.unlink()
    return path


async def _value_after_signal(signal: asyncio.Event, value: str) -> str:
    await signal.wait()
    return value


def test_idempotent_retry_returns_cached_result_and_expires_after_ttl() -> None:
    TelemetryService.instance().reset()
    cache = IdempotentRequestCache(ttl_seconds=0.05)
    calls = 0

    async def factory() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"answer": f"value-{calls}"}

    first = _run(cache.run("session-1", "hash-1", factory))
    second = _run(cache.run("session-1", "hash-1", factory))
    different = _run(cache.run("session-1", "hash-2", factory))
    time.sleep(0.07)
    third = _run(cache.run("session-1", "hash-1", factory))

    assert first == {"answer": "value-1"}
    assert second == first
    assert different == {"answer": "value-2"}
    assert third == {"answer": "value-3"}
    assert calls == 3
    assert any(event["event_type"] == "idempotent_cache_hit" for event in TelemetryService.instance().events)


def test_duplicate_request_waits_for_in_progress_execution_without_second_run() -> None:
    cache = IdempotentRequestCache(ttl_seconds=10)
    signal = asyncio.Event()
    calls = 0

    async def factory() -> str:
        nonlocal calls
        calls += 1
        return await _value_after_signal(signal, "done")

    async def scenario() -> tuple[str, str, int]:
        first = asyncio.create_task(cache.run("session-1", "hash-1", factory))
        await asyncio.sleep(0)
        second = asyncio.create_task(cache.run("session-1", "hash-1", factory))
        await asyncio.sleep(0)
        signal.set()
        return await first, await second, calls

    assert _run(scenario()) == ("done", "done", 1)


def test_graceful_cancellation_cancels_in_progress_work_and_runs_cleanup() -> None:
    TelemetryService.instance().reset()
    manager = RequestCancellationManager(check_interval_seconds=0.01)
    disconnected = asyncio.Event()
    cleaned = False

    async def long_work() -> str:
        try:
            await asyncio.sleep(10)
            return "finished"
        finally:
            await asyncio.sleep(0)

    async def cleanup() -> None:
        nonlocal cleaned
        cleaned = True

    async def scenario() -> None:
        task = asyncio.create_task(
            manager.run(
                long_work(),
                request_id="req-1",
                should_cancel=disconnected.is_set,
                cleanup=cleanup,
            )
        )
        await asyncio.sleep(0.02)
        disconnected.set()
        with pytest.raises(RequestCancelled):
            await task

    _run(scenario())

    assert cleaned is True
    assert any(event["event_type"] == "request_cancelled" for event in TelemetryService.instance().events)


def test_background_task_tracker_tracks_warns_and_cancels_orphans_on_shutdown() -> None:
    TelemetryService.instance().reset()
    tracker = BackgroundTaskTracker(default_max_duration_seconds=0.01)

    async def slow_task() -> None:
        await asyncio.sleep(10)

    async def scenario() -> tuple[int, int]:
        task = tracker.create_task(slow_task(), task_type="trajectory_write", context={"session": "s1"})
        await asyncio.sleep(0.03)
        warnings = tracker.detect_long_running(cancel_overdue=False)
        assert not task.done()
        cancelled = await tracker.shutdown(grace_period_seconds=0.01)
        return len(warnings), cancelled

    warning_count, cancelled_count = _run(scenario())

    assert warning_count == 1
    assert cancelled_count == 1
    assert any(event["event_type"] == "background_task_long_running" for event in TelemetryService.instance().events)
    assert any(event["event_type"] == "background_tasks_cancelled" for event in TelemetryService.instance().events)


def test_dirty_state_cleanup_removes_old_orphaned_temp_files_and_clears_cache() -> None:
    root = _workspace_path("dirty-root")
    root.mkdir(parents=True, exist_ok=True)
    orphan = root / "orphan.tmp"
    fresh = root / "fresh.tmp"
    active_dir = root / "active-session"
    active_dir.mkdir(exist_ok=True)
    active_file = active_dir / "keep.tmp"
    for path in (orphan, fresh, active_file):
        path.write_text("x", encoding="utf-8")

    old = time.time() - 3600
    os.utime(orphan, (old, old))
    os.utime(active_file, (old, old))

    cache = IdempotentRequestCache(ttl_seconds=60)
    _run(cache.run("session-1", "hash-1", lambda: asyncio.sleep(0, result="cached")))

    cleaner = DirtyStateCleaner(temp_roots=(root,), ttl_seconds=60)
    removed = cleaner.cleanup(active_session_ids={"active-session"}, idempotent_cache=cache)

    assert removed == [orphan]
    assert not orphan.exists()
    assert fresh.exists()
    assert active_file.exists()
    assert cache.entry_count == 0


def test_startup_cleanup_runs_as_background_task_without_blocking() -> None:
    root = _workspace_path("startup-root")
    root.mkdir(parents=True, exist_ok=True)
    old_file = root / "old.tmp"
    old_file.write_text("x", encoding="utf-8")
    old = time.time() - 3600
    os.utime(old_file, (old, old))
    tracker = BackgroundTaskTracker()
    manager = RobustnessManager(
        idempotent_cache=IdempotentRequestCache(),
        task_tracker=tracker,
        dirty_state_cleaner=DirtyStateCleaner(temp_roots=(root,), ttl_seconds=60),
    )

    async def scenario() -> None:
        task = manager.schedule_startup_cleanup(active_session_ids=set())
        assert task is not None
        await asyncio.wait_for(task, timeout=1)

    _run(scenario())

    assert not old_file.exists()
    assert tracker.active_count == 0
