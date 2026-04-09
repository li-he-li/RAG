"""
Session-scoped temporary file storage kept fully outside the database/vector index.

Includes TTL-based eviction and per-session / global size limits to prevent
memory exhaustion attacks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Iterable
from uuid import uuid4

from app.models.schemas import SessionTempFileItem, SessionTempFileKind

logger = logging.getLogger(__name__)

UTC = timezone.utc
MAX_CONTENT_PREVIEW_CHARS = 4000

# ── Limits ──────────────────────────────────────────────────────
_MAX_SESSIONS = 256          # max concurrent sessions stored
_MAX_FILES_PER_SESSION = 50  # max files in a single session
_MAX_TOTAL_BYTES = 200 * 1024 * 1024  # 200 MiB global cap
_DEFAULT_TTL = timedelta(hours=4)      # sessions expire after 4 h


@dataclass(slots=True)
class SessionTempFileRecord:
    file_id: str
    session_id: str
    kind: SessionTempFileKind
    file_name: str
    content: str
    size_bytes: int
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class SessionTempBucket:
    session_id: str
    files: dict[str, SessionTempFileRecord] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class SessionTempFileStore:
    def __init__(
        self,
        *,
        max_sessions: int = _MAX_SESSIONS,
        max_files_per_session: int = _MAX_FILES_PER_SESSION,
        max_total_bytes: int = _MAX_TOTAL_BYTES,
        ttl: timedelta = _DEFAULT_TTL,
    ) -> None:
        self._lock = RLock()
        self._sessions: dict[str, SessionTempBucket] = {}
        self._max_sessions = max_sessions
        self._max_files_per_session = max_files_per_session
        self._max_total_bytes = max_total_bytes
        self._ttl = ttl

    # ── Eviction ───────────────────────────────────────────────

    def _evict_expired(self) -> None:
        """Remove sessions past their TTL. Caller must hold self._lock."""
        cutoff = datetime.now(UTC) - self._ttl
        expired = [
            sid for sid, bucket in self._sessions.items()
            if bucket.updated_at < cutoff
        ]
        for sid in expired:
            self._sessions.pop(sid, None)
        if expired:
            logger.info("Evicted %d expired session(s).", len(expired))

    def _current_total_bytes(self) -> int:
        """Sum of all file content sizes. Caller must hold self._lock."""
        return sum(
            rec.size_bytes
            for bucket in self._sessions.values()
            for rec in bucket.files.values()
        )

    # ── Public API ─────────────────────────────────────────────

    def add_file(
        self,
        *,
        session_id: str,
        kind: SessionTempFileKind,
        file_name: str,
        content: str,
        size_bytes: int,
    ) -> SessionTempFileItem:
        now = datetime.now(UTC)

        with self._lock:
            self._evict_expired()

            bucket = self._sessions.get(session_id)
            if bucket is None:
                if len(self._sessions) >= self._max_sessions:
                    raise ValueError(
                        f"Session limit ({self._max_sessions}) reached. "
                        "Close old sessions before creating new ones."
                    )
                bucket = SessionTempBucket(session_id=session_id, updated_at=now, created_at=now)
                self._sessions[session_id] = bucket

            if len(bucket.files) >= self._max_files_per_session:
                raise ValueError(
                    f"File limit ({self._max_files_per_session}) reached for session {session_id}."
                )

            total = self._current_total_bytes() + size_bytes
            if total > self._max_total_bytes:
                raise ValueError(
                    f"Global storage limit ({self._max_total_bytes // (1024 * 1024)} MiB) exceeded."
                )

            record = SessionTempFileRecord(
                file_id=f"tmp_{uuid4().hex}",
                session_id=session_id,
                kind=kind,
                file_name=file_name,
                content=content,
                size_bytes=size_bytes,
                created_at=now,
                updated_at=now,
            )

            bucket.files[record.file_id] = record
            bucket.updated_at = now
            return self._to_item(record)

    def list_files(
        self,
        *,
        session_id: str,
        kind: SessionTempFileKind | None = None,
    ) -> list[SessionTempFileItem]:
        now = datetime.now(UTC)
        with self._lock:
            bucket = self._sessions.get(session_id)
            if not bucket:
                return []
            bucket.updated_at = now
            records = sorted(bucket.files.values(), key=lambda item: item.created_at)
            if kind is not None:
                records = [record for record in records if record.kind == kind]
            return [self._to_item(record) for record in records]

    def get_files(
        self,
        *,
        session_id: str,
        file_ids: Iterable[str] | None = None,
        kind: SessionTempFileKind | None = None,
    ) -> list[SessionTempFileRecord]:
        now = datetime.now(UTC)
        with self._lock:
            bucket = self._sessions.get(session_id)
            if not bucket:
                return []

            bucket.updated_at = now
            records = list(bucket.files.values())
            if kind is not None:
                records = [record for record in records if record.kind == kind]
            if file_ids is not None:
                wanted = set(file_ids)
                records = [record for record in records if record.file_id in wanted]
            records.sort(key=lambda item: item.created_at)
            return [
                SessionTempFileRecord(
                    file_id=record.file_id,
                    session_id=record.session_id,
                    kind=record.kind,
                    file_name=record.file_name,
                    content=record.content,
                    size_bytes=record.size_bytes,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
                for record in records
            ]

    def delete_file(self, *, file_id: str) -> SessionTempFileItem | None:
        now = datetime.now(UTC)
        with self._lock:
            for session_id, bucket in list(self._sessions.items()):
                record = bucket.files.pop(file_id, None)
                if not record:
                    continue
                bucket.updated_at = now
                if not bucket.files:
                    self._sessions.pop(session_id, None)
                return self._to_item(record)
            return None

    def clear_session(
        self,
        *,
        session_id: str,
        kind: SessionTempFileKind | None = None,
    ) -> int:
        now = datetime.now(UTC)
        with self._lock:
            bucket = self._sessions.get(session_id)
            if not bucket:
                return 0

            if kind is None:
                cleared = len(bucket.files)
                self._sessions.pop(session_id, None)
                return cleared

            target_ids = [record.file_id for record in bucket.files.values() if record.kind == kind]
            for file_id in target_ids:
                bucket.files.pop(file_id, None)
            bucket.updated_at = now
            if not bucket.files:
                self._sessions.pop(session_id, None)
            return len(target_ids)

    def clear_all(self) -> None:
        with self._lock:
            self._sessions.clear()

    @staticmethod
    def _to_item(record: SessionTempFileRecord) -> SessionTempFileItem:
        return SessionTempFileItem(
            file_id=record.file_id,
            session_id=record.session_id,
            kind=record.kind,
            file_name=record.file_name,
            size_bytes=record.size_bytes,
            content_chars=len(record.content),
            content_preview=record.content[:MAX_CONTENT_PREVIEW_CHARS] if record.content else None,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


session_temp_file_store = SessionTempFileStore()
