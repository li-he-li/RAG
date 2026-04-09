"""
Shared streaming / NDJSON utilities.
"""

from __future__ import annotations

import json


def encode_stream_event(payload: dict) -> str:
    """Encode a streaming event as a single NDJSON line."""
    return json.dumps(payload, ensure_ascii=False) + "\n"


def iter_text_chunks(text: str, chunk_size: int = 24) -> list[str]:
    """Split text into small chunks for frontend streaming."""
    if not text:
        return []
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
