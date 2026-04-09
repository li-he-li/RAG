"""
Upload body reads with an upper size bound (mitigates memory exhaustion / abuse).
"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile

from app.core.config import MAX_UPLOAD_BYTES

_CHUNK = 1024 * 1024  # 1 MiB


async def read_upload_bytes(file: UploadFile, *, max_bytes: int | None = None) -> bytes:
    """Read the full upload into memory, failing with 413 if larger than max_bytes."""
    limit = max_bytes if max_bytes is not None else MAX_UPLOAD_BYTES
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            mb = max(1, limit // (1024 * 1024))
            raise HTTPException(
                status_code=413,
                detail=f"文件超过大小上限（最大约 {mb} MiB，可由 MAX_UPLOAD_BYTES 调整）",
            )
        chunks.append(chunk)
    return b"".join(chunks)
