"""
Qdrant vector store management.
Handles creation of document-level and paragraph-level collections,
and CRUD operations for vector embeddings.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from qdrant_client import QdrantClient, models

from app.core.config import (
    DOC_COLLECTION,
    EMBEDDING_DIMENSION,
    PARA_COLLECTION,
    QDRANT_HOST,
    QDRANT_PORT,
)

logger = logging.getLogger(__name__)


def get_qdrant_client() -> QdrantClient:
    """Return a Qdrant client instance."""
    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)


def init_collections(client: Optional[QdrantClient] = None) -> None:
    """Create document-level and paragraph-level collections if they don't exist."""
    if client is None:
        client = get_qdrant_client()

    for name in (DOC_COLLECTION, PARA_COLLECTION):
        try:
            client.get_collection(name)
            logger.info(f"Collection '{name}' already exists.")
        except Exception:
            client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=EMBEDDING_DIMENSION,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info(f"Created collection '{name}'.")

    # Ensure payload indexes for filtering
    for name in (DOC_COLLECTION, PARA_COLLECTION):
        try:
            client.create_payload_index(
                collection_name=name,
                field_name="doc_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass  # Index may already exist

    try:
        client.create_payload_index(
            collection_name=PARA_COLLECTION,
            field_name="dispute_tags",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
    except Exception:
        pass


def upsert_document_vector(
    doc_id: str,
    vector: list[float],
    payload: dict,
    client: Optional[QdrantClient] = None,
) -> None:
    """Upsert a document-level embedding vector."""
    if client is None:
        client = get_qdrant_client()
    client.upsert(
        collection_name=DOC_COLLECTION,
        points=[
            models.PointStruct(
                id=doc_id,
                vector=vector,
                payload=payload,
            )
        ],
    )


def upsert_paragraph_vectors(
    points: list[dict],
    client: Optional[QdrantClient] = None,
) -> None:
    """Batch upsert paragraph-level embedding vectors.

    Each dict must contain: para_id, vector, payload.
    """
    if client is None:
        client = get_qdrant_client()

    qdrant_points = []
    for p in points:
        qdrant_points.append(
            models.PointStruct(
                id=p["para_id"],
                vector=p["vector"],
                payload=p["payload"],
            )
        )

    # Batch upsert in chunks of 100
    batch_size = 100
    for i in range(0, len(qdrant_points), batch_size):
        client.upsert(
            collection_name=PARA_COLLECTION,
            points=qdrant_points[i : i + batch_size],
        )


def search_documents(
    query_vector: list[float],
    top_k: int = 5,
    client: Optional[QdrantClient] = None,
) -> list:
    """Search document-level collection for similar documents."""
    if top_k < 1:
        return []
    if client is None:
        client = get_qdrant_client()
    results = client.query_points(
        collection_name=DOC_COLLECTION,
        query=query_vector,
        limit=top_k,
    ).points
    return results


def search_paragraphs(
    query_vector: list[float],
    doc_ids: Optional[list[str]] = None,
    top_k: int = 10,
    dispute_tags: Optional[list[str]] = None,
    client: Optional[QdrantClient] = None,
) -> list:
    """Search paragraph-level collection, optionally filtered by doc_ids or dispute tags."""
    if top_k < 1:
        return []
    if doc_ids is not None and len(doc_ids) == 0:
        return []
    if client is None:
        client = get_qdrant_client()

    # Build filter
    filter_conditions = []
    if doc_ids:
        filter_conditions.append(
            models.FieldCondition(
                key="doc_id",
                match=models.MatchAny(any=[str(d) for d in doc_ids]),
            )
        )
    if dispute_tags:
        filter_conditions.append(
            models.FieldCondition(
                key="dispute_tags",
                match=models.MatchAny(any=dispute_tags),
            )
        )

    query_filter = None
    if filter_conditions:
        query_filter = models.Filter(must=filter_conditions)

    results = client.query_points(
        collection_name=PARA_COLLECTION,
        query=query_vector,
        query_filter=query_filter,
        limit=top_k,
    ).points
    return results


def delete_document_vectors(
    doc_id: str,
    client: Optional[QdrantClient] = None,
) -> None:
    """Delete all vectors (document + paragraphs) for a given doc_id."""
    if client is None:
        client = get_qdrant_client()

    client.delete(
        collection_name=DOC_COLLECTION,
        points_selector=models.PointIdsList(points=[doc_id]),
    )

    # Delete all paragraphs belonging to this document
    client.delete(
        collection_name=PARA_COLLECTION,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="doc_id",
                        match=models.MatchValue(value=doc_id),
                    )
                ]
            )
        ),
    )
