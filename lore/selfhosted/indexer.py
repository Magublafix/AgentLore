"""Embedding indexer — bridges the embedding model to SQLite and Qdrant.

This module is used by the FastAPI service (LORE-003) and the seed loader
(LORE-006).  It assumes that concepts are already persisted in SQLite before
:func:`index_concept` is called; the caller is responsible for the insert.

Dual-write contract:
    1.  Embed the concept text.
    2.  Write the raw bytes to SQLite via :func:`~lore.selfhosted.db.update_embedding`.
    3.  Upsert the vector into Qdrant via
        :func:`~lore.selfhosted.vector_store.upsert_concept_vector`.

If either storage step raises, the exception propagates to the caller without
leaving partial state — SQLite and Qdrant are updated in order, and a failure
in step 3 does not corrupt the SQLite row beyond having a stored embedding BLOB
(which is idempotent to overwrite on retry).
"""

from __future__ import annotations

import struct
import sqlite3
from typing import Optional

from qdrant_client import QdrantClient

from lore.mcp.models import Concept
from lore.mcp.embeddings import EmbeddingModel
from lore.selfhosted.db import update_embedding, search_concepts_by_ids
from lore.selfhosted.vector_store import upsert_concept_vector, search_vectors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vector_to_bytes(vector: list[float]) -> bytes:
    """Serialize a ``list[float]`` to a raw little-endian float32 BLOB.

    Args:
        vector: List of float values.

    Returns:
        Bytes object with ``4 * len(vector)`` bytes.
    """
    return struct.pack(f"{len(vector)}f", *vector)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def index_concept(
    conn: sqlite3.Connection,
    qdrant_client: QdrantClient,
    concept: Concept,
    model: EmbeddingModel,
    collection_name: str = "concepts",
) -> str:
    """Embed a concept and persist the vector to SQLite and Qdrant.

    The embedding target is ``when_to_use + " " + name`` — the primary
    natural-language retrieval surface.  ``content`` is NOT embedded.

    Assumes the concept is already persisted in SQLite
    (:func:`~lore.selfhosted.db.insert_concept` was already called).  This
    function only handles the embedding step.

    Args:
        conn: An active SQLite connection.
        qdrant_client: An active :class:`~qdrant_client.QdrantClient` instance.
        concept: The :class:`~lore.mcp.models.Concept` to embed.  Both
            ``when_to_use`` and ``name`` must be non-empty.
        model: Loaded :class:`~lore.mcp.embeddings.EmbeddingModel` instance.
        collection_name: Qdrant collection name.  Defaults to ``"concepts"``.

    Returns:
        The ``concept_id`` string (unchanged from ``concept.concept_id``).
    """
    embed_text = concept.when_to_use + " " + concept.name
    vector: list[float] = model.embed(embed_text)

    # Write raw bytes to SQLite (idempotent — safe to retry).
    embedding_blob = _vector_to_bytes(vector)
    update_embedding(conn, concept.concept_id, embedding_blob)

    # Upsert the float vector into Qdrant.
    upsert_concept_vector(qdrant_client, collection_name, concept.concept_id, vector)

    return concept.concept_id


def search_concepts(
    conn: sqlite3.Connection,
    qdrant_client: QdrantClient,
    model: EmbeddingModel,
    problem: str,
    type_filter: Optional[str] = None,
    language_filter: Optional[str] = None,
    limit: int = 5,
    collection_name: str = "concepts",
) -> list[Concept]:
    """Find concepts semantically similar to a natural-language problem description.

    Embeds ``problem``, queries Qdrant for the nearest vectors, fetches full
    :class:`~lore.mcp.models.Concept` records from SQLite, then applies
    ``type_filter`` and ``language_filter`` in-memory.

    The in-memory filter is applied *after* fetching from SQLite rather than
    using Qdrant payload filters.  This keeps the Qdrant query simple and
    avoids filter-induced result count shortfalls (e.g. requesting limit=5 but
    only 2 pass the filter in Qdrant).  For small collections this is perfectly
    efficient; a future optimisation could push filters into Qdrant with a
    higher initial limit.

    Args:
        conn: An active SQLite connection.
        qdrant_client: An active :class:`~qdrant_client.QdrantClient` instance.
        model: Loaded :class:`~lore.mcp.embeddings.EmbeddingModel` instance.
        problem: Natural-language description of the agent's current problem.
        type_filter: If provided, only return concepts whose ``type`` matches
            this string exactly (e.g. ``"pattern"``, ``"tool"``).
        language_filter: If provided, only return concepts whose ``language``
            matches this string exactly (e.g. ``"python"``).  Concepts with
            ``language=None`` are excluded when a filter is active.
        limit: Maximum number of results to return after filtering.  Defaults
            to 5.
        collection_name: Qdrant collection name.  Defaults to ``"concepts"``.

    Returns:
        List of :class:`~lore.mcp.models.Concept` objects in descending
        relevance order (Qdrant score order), truncated to ``limit`` entries
        after filtering.
    """
    query_vector: list[float] = model.embed(problem)

    # Fetch more candidates than needed to absorb filter attrition.
    fetch_limit = limit * 4 if (type_filter or language_filter) else limit
    concept_ids: list[str] = search_vectors(
        qdrant_client, collection_name, query_vector, limit=fetch_limit
    )

    if not concept_ids:
        return []

    concepts: list[Concept] = search_concepts_by_ids(conn, concept_ids)

    # Apply in-memory filters while preserving relevance order.
    if type_filter is not None:
        concepts = [c for c in concepts if c.type == type_filter]
    if language_filter is not None:
        concepts = [c for c in concepts if c.language == language_filter]

    return concepts[:limit]
