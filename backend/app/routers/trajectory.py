"""
Trajectory query and replay API endpoints.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.services.trajectory.replay import TrajectoryReplayService
from app.services.trajectory.store import InMemoryTrajectoryStore, TrajectoryStore

router = APIRouter(tags=["trajectory"])

# Module-level default store (replaced in production with DB-backed store)
_default_store: TrajectoryStore = InMemoryTrajectoryStore()


def get_trajectory_store() -> TrajectoryStore:
    """FastAPI dependency that provides the trajectory store."""
    return _default_store


def set_trajectory_store(store: TrajectoryStore) -> None:
    """Replace the global trajectory store (for testing or production config)."""
    global _default_store
    _default_store = store


@router.get("/trajectories/{session_id}")
def get_trajectories(
    session_id: str,
    store: TrajectoryStore = Depends(get_trajectory_store),
) -> list[dict[str, Any]]:
    """Retrieve trajectory records for a session, ordered chronologically."""
    return store.query_by_session(session_id)


@router.get("/trajectories/{session_id}/replay")
def get_trajectory_replay(
    session_id: str,
    store: TrajectoryStore = Depends(get_trajectory_store),
) -> dict[str, Any]:
    """Reconstruct a full pipeline replay from stored trajectory data."""
    records = store.query_by_session(session_id)
    return TrajectoryReplayService.replay(records)
