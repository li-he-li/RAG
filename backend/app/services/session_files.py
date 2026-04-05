"""
Session-scoped temporary file storage kept fully outside the database/vector index.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Iterable
from uuid import uuid4

from app.models.schemas import SessionTempFileItem, SessionTempFileKind


UTC = timezone.utc


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


class SessionTempFileStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._sessions: dict[str, SessionTempBucket] = {}

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

        with self._lock:
            bucket = self._sessions.setdefault(session_id, SessionTempBucket(session_id=session_id, updated_at=now))
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
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


session_temp_file_store = SessionTempFileStore()
