"""Qdrant vector store operations for the Lore self-hosted backend.

All Qdrant interactions are isolated here so that the rest of the codebase
never imports ``qdrant_client`` directly.

Collection initialisation is idempotent — calling :func:`init_qdrant_collection`
on an existing collection is safe and does not modify existing vectors.

Point IDs in Qdrant must be either unsigned integers or UUIDs.  Lore concept
IDs are already UUIDs so they are used directly as Qdrant point IDs after
normalisation to a :class:`str` UUID.  Internally ``qdrant_client`` accepts
UUID strings when the collection ``vector_size`` is fixed.
"""

from __future__ import annotations

import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels


# Vector configuration constants
VECTOR_SIZE = 384           # all-MiniLM-L6-v2 output dimension
VECTOR_DISTANCE = qmodels.Distance.COSINE


def _concept_id_to_point_id(concept_id: str) -> str:
    """Convert a concept_id to a deterministic Qdrant point UUID.

    Qdrant requires point IDs to be valid UUIDs (or unsigned ints).  If the
    caller supplies a well-formed UUID string it is used directly; otherwise
    a deterministic UUID5 is derived from the string so the mapping is stable
    across restarts.

    Args:
        concept_id: The Lore concept UUID string.

    Returns:
        A UUID string suitable for use as a Qdrant point ID.
    """
    try:
        # Validate: if already a valid UUID, use it as-is.
        uuid.UUID(concept_id)
        return concept_id
    except ValueError:
        # Derive a deterministic UUID5 from the raw string.
        return str(uuid.uuid5(uuid.NAMESPACE_OID, concept_id))


def init_qdrant_collection(
    client: QdrantClient,
    collection_name: str = "concepts",
) -> None:
    """Create the Qdrant collection if it does not already exist.

    This function is idempotent.  If the collection is already present (e.g.
    on a warm restart) it returns without error.

    Args:
        client: An active :class:`QdrantClient` instance.
        collection_name: The Qdrant collection name.  Defaults to
            ``"concepts"``.
    """
    existing = {c.name for c in client.get_collections().collections}
    if collection_name in existing:
        return

    client.create_collection(
        collection_name=collection_name,
        vectors_config=qmodels.VectorParams(
            size=VECTOR_SIZE,
            distance=VECTOR_DISTANCE,
        ),
    )


def upsert_concept_vector(
    client: QdrantClient,
    collection_name: str,
    concept_id: str,
    vector: list[float],
) -> None:
    """Upsert a single concept vector into Qdrant.

    The ``concept_id`` is stored in the point payload under the key
    ``"concept_id"`` so that callers can map Qdrant results back to SQLite
    rows without a separate lookup table.

    Args:
        client: An active :class:`QdrantClient` instance.
        collection_name: Target collection name.
        concept_id: The Lore concept UUID string.
        vector: Float list of length 384 (all-MiniLM-L6-v2 output).
    """
    init_qdrant_collection(client, collection_name)
    point_id = _concept_id_to_point_id(concept_id)
    client.upsert(
        collection_name=collection_name,
        points=[
            qmodels.PointStruct(
                id=point_id,
                vector=vector,
                payload={"concept_id": concept_id},
            )
        ],
    )


def search_vectors(
    client: QdrantClient,
    collection_name: str,
    query_vector: list[float],
    limit: int = 5,
) -> list[str]:
    """Search for the nearest concept vectors and return their concept IDs.

    Results are ordered by descending cosine similarity (highest first).

    Args:
        client: An active :class:`QdrantClient` instance.
        collection_name: The collection to search.
        query_vector: Float list of length 384.
        limit: Maximum number of results to return.  Defaults to 5.

    Returns:
        List of ``concept_id`` strings, ordered by relevance.  The list may
        be shorter than ``limit`` if the collection has fewer vectors.
    """
    # qdrant-client ≥1.8 replaced .search() with .query_points()
    try:
        response = client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=limit,
            with_payload=True,
        )
    except Exception as exc:
        # Collection doesn't exist yet — return empty rather than 500.
        if "doesn't exist" in str(exc) or "Not found" in str(exc):
            return []
        raise
    return [hit.payload["concept_id"] for hit in response.points if hit.payload]


def find_near_duplicate(
    client: QdrantClient,
    collection_name: str,
    query_vector: list[float],
    threshold: float = 0.88,
) -> tuple[str, float] | None:
    """Return (concept_id, score) of the nearest existing concept if similarity
    exceeds ``threshold``, or ``None`` if no near-duplicate exists.

    Args:
        client: An active :class:`QdrantClient` instance.
        collection_name: The collection to search.
        query_vector: Float list of length 384.
        threshold: Cosine similarity threshold above which a concept is
            considered a duplicate.  Defaults to 0.88.

    Returns:
        ``(concept_id, score)`` tuple or ``None``.
    """
    try:
        response = client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=1,
            with_payload=True,
            score_threshold=threshold,
        )
    except Exception as exc:
        if "doesn't exist" in str(exc) or "Not found" in str(exc):
            return None
        raise
    if response.points:
        hit = response.points[0]
        return hit.payload["concept_id"], hit.score
    return None
