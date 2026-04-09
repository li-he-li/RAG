"""
Client-facing error messages: hide exception details unless DEBUG is enabled.
"""

from __future__ import annotations

from app.core.config import DEBUG

GENERIC_INTERNAL_ZH = "服务器内部错误，请稍后重试。"


def internal_error_detail(exc: BaseException | None = None) -> str:
    """Use for generic handler failures (search, chat, ingest)."""
    if DEBUG and exc is not None:
        return str(exc)
    return GENERIC_INTERNAL_ZH


def parser_dependency_detail(label_zh: str, exc: Exception) -> str:
    """Parser / optional dependency import failures (avoid leaking paths in production)."""
    if DEBUG:
        return f"{label_zh} 解析不可用: {exc}"
    return f"{label_zh} 解析依赖未就绪或服务异常。"
