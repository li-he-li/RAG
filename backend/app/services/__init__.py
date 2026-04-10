"""Service package exports with lazy imports to avoid startup side effects."""

from __future__ import annotations

from typing import Any

_EXPORTS = {
    "encode_texts": ("app.services.embedding", "encode_texts"),
    "encode_single": ("app.services.embedding", "encode_single"),
    "ingest_document": ("app.services.indexer", "ingest_document"),
    "delete_document": ("app.services.indexer", "delete_document"),
    "parse_document": ("app.services.parser", "parse_document"),
    "rerank": ("app.services.reranker", "rerank"),
    "execute_search": ("app.services.retrieval", "execute_search"),
    "validate_and_enrich_results": (
        "app.services.traceability",
        "validate_and_enrich_results",
    ),
    "init_collections": ("app.services.vector_store", "init_collections"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = _EXPORTS[name]
    from importlib import import_module

    return getattr(import_module(module_name), attribute_name)
