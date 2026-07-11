"""Backend 1 storage implementation: SQLite + Qdrant.

Wraps the existing ``lore.selfhosted.db``, ``lore.selfhosted.indexer``, and
``lore.selfhosted.vector_store`` helpers behind the :class:`StorageBackend`
interface so the unified server can delegate to them without knowing which
backend is active.

Concurrency notes
-----------------
The SQLite connection is opened once in ``__init__`` with
``check_same_thread=False`` (handled by :func:`~lore.selfhosted.db.init_db`)
and shared across requests.  WAL mode is enabled by ``init_db``, making
concurrent reads safe.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

from qdrant_client import QdrantClient

from lore.mcp.embeddings import EmbeddingModel
from lore.mcp.models import Concept, Link, Rating
from lore.selfhosted.db import (
    get_concept,
    get_links_for_concept,
    init_db,
    insert_concept,
    insert_link,
    insert_rating,
    log_session_usage,
)
from lore.selfhosted.indexer import index_concept, search_concepts
from lore.selfhosted.vector_store import find_near_duplicate, init_qdrant_collection, search_vectors
from lore.server.storage.base import StorageBackend

logger = logging.getLogger(__name__)

COLLECTION_NAME = "concepts"

VALID_LINK_RELS = {"uses", "tested_by", "extends", "alternative_to", "requires"}


def _concept_to_dict(concept: Concept) -> dict:
    """Serialize a :class:`~lore.mcp.models.Concept` to a JSON-safe dict.

    The ``embedding`` BLOB field is excluded — not meaningful over HTTP.

    Args:
        concept: The concept to serialize.

    Returns:
        A JSON-serializable dict with all non-binary concept fields.
    """
    return {
        "concept_id": concept.concept_id,
        "name": concept.name,
        "type": concept.type,
        "content": concept.content,
        "language": concept.language,
        "when_to_use": concept.when_to_use,
        "dont_use_when": concept.dont_use_when,
        "tags": concept.tags,
        "source_url": concept.source_url,
        "author": concept.author,
        "avg_rating": concept.avg_rating,
        "usage_count": concept.usage_count,
        "time_saved_avg_hours": concept.time_saved_avg_hours,
        "created_at": concept.created_at,
    }


def _link_to_dict(link: Link, conn: Optional[sqlite3.Connection] = None) -> dict:
    """Serialize a :class:`~lore.mcp.models.Link` to a JSON-safe dict.

    When ``conn`` is provided the linked concept's ``name``, ``type``, and
    ``when_to_use`` are fetched inline — no second round-trip needed by callers.

    Args:
        link: The link to serialize.
        conn: Optional SQLite connection for linked-concept enrichment.

    Returns:
        A JSON-serializable dict with all link fields plus optional fields
        from the linked concept when ``conn`` is provided.
    """
    d = {
        "link_id": link.link_id,
        "from_id": link.from_id,
        "to_id": link.to_id,
        "rel": link.rel,
        "label": link.label,
    }
    if conn is not None:
        linked = get_concept(conn, link.to_id)
        if linked is not None:
            d["name"] = linked.name
            d["type"] = linked.type
            d["when_to_use"] = linked.when_to_use
    return d


class SqliteQdrantBackend(StorageBackend):
    """Backend 1: SQLite for metadata + Qdrant for semantic search vectors.

    Args:
        sqlite_path: Filesystem path to the SQLite database file.
        qdrant_host: Hostname for the Qdrant service.
        qdrant_port: Port number for the Qdrant service.
        model: Pre-loaded :class:`~lore.mcp.embeddings.EmbeddingModel` instance.
    """

    def __init__(
        self,
        sqlite_path: str,
        qdrant_host: str,
        qdrant_port: int,
        model: EmbeddingModel,
    ) -> None:
        Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        logger.info("Opening SQLite database at %s", sqlite_path)
        self._conn: sqlite3.Connection = init_db(sqlite_path)

        logger.info("Connecting to Qdrant at %s:%s", qdrant_host, qdrant_port)
        self._qdrant = QdrantClient(host=qdrant_host, port=qdrant_port)
        self._model = model

        try:
            init_qdrant_collection(self._qdrant, collection_name=COLLECTION_NAME)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Qdrant collection init failed (will retry on first use): %s", exc
            )

    # ------------------------------------------------------------------
    # Public accessors — used by the HTTP layer for backend-specific routes
    # ------------------------------------------------------------------

    @property
    def db(self) -> sqlite3.Connection:
        """Return the raw SQLite connection for use by HTTP-layer admin routes."""
        return self._conn

    @property
    def qdrant(self) -> QdrantClient:
        """Return the raw QdrantClient for use by HTTP-layer admin routes."""
        return self._qdrant

    def close(self) -> None:
        """Close the SQLite connection (called during server shutdown)."""
        logger.info("Shutting down SqliteQdrantBackend — closing SQLite connection.")
        self._conn.close()

    # ------------------------------------------------------------------
    # StorageBackend interface
    # ------------------------------------------------------------------

    def upsert_concept(self, payload: dict) -> dict:
        """Insert a new concept into SQLite and index its vector in Qdrant.

        The ``payload`` dict must contain the keys expected by
        :class:`~lore.mcp.models.Concept`.  Inline links are **not** handled
        here — they are inserted separately by the HTTP layer.

        Semantic dedup is the caller's responsibility (the HTTP handler calls
        :func:`~lore.selfhosted.vector_store.find_near_duplicate` before invoking
        this method).

        Args:
            payload: Dict with concept fields plus optional ``links`` list.

        Returns:
            ``{"concept_id": str, "name": str}`` on success.

        Raises:
            Exception: If Qdrant indexing fails (SQLite insert is NOT rolled
                back — deliberate Phase 1 trade-off; caller receives the
                concept_id so re-indexing is possible).
        """
        concept_id = str(uuid.uuid4())
        concept = Concept(
            concept_id=concept_id,
            name=payload["name"],
            type=payload["type"],
            content=payload["content"],
            language=payload.get("language"),
            when_to_use=payload["when_to_use"],
            dont_use_when=payload.get("dont_use_when"),
            tags=payload.get("tags", []),
            source_url=payload.get("source_url"),
            author=payload.get("author"),
        )

        insert_concept(self._conn, concept)
        index_concept(self._conn, self._qdrant, concept, self._model, COLLECTION_NAME)

        return {"concept_id": concept_id, "name": payload["name"]}

    def search_concepts(
        self,
        query_vector: list[float],
        limit: int,
        type_filter: str | None,
        language_filter: str | None,
        min_rating: float,
    ) -> list[dict]:
        """Embed a query and return matching concept dicts from SQLite/Qdrant.

        Args:
            query_vector: Pre-computed embedding vector from the HTTP layer.
            limit: Maximum number of results.
            type_filter: Optional concept type constraint.
            language_filter: Optional language constraint.
            min_rating: Minimum average rating threshold.

        Returns:
            List of concept dicts each with a ``links`` key (enriched inline).
        """
        # The unified server pre-computes the query vector; we call search_vectors
        # directly to avoid re-embedding inside indexer.search_concepts.
        concept_ids = search_vectors(
            self._qdrant,
            COLLECTION_NAME,
            query_vector,
            limit=limit,
        )

        results = []
        for cid in concept_ids:
            concept = get_concept(self._conn, cid)
            if concept is None:
                continue
            if type_filter and concept.type != type_filter:
                continue
            if language_filter and concept.language != language_filter:
                continue
            if (concept.avg_rating or 0.0) < min_rating:
                continue
            links = get_links_for_concept(self._conn, cid)
            entry = _concept_to_dict(concept)
            entry["links"] = [_link_to_dict(lnk, self._conn) for lnk in links]
            results.append(entry)

        return results

    def get_concept(self, concept_id: str) -> dict | None:
        """Fetch a concept by ID from SQLite, with links attached.

        Args:
            concept_id: UUID string of the concept.

        Returns:
            Full concept dict with ``links`` array, or ``None`` if not found.
        """
        concept = get_concept(self._conn, concept_id)
        if concept is None:
            return None
        links = get_links_for_concept(self._conn, concept_id)
        result = _concept_to_dict(concept)
        result["links"] = [_link_to_dict(lnk, self._conn) for lnk in links]
        return result

    def rate_concept(
        self,
        concept_id: str,
        outcome: int,
        session_id: str | None,
        hours_saved: float | None,
        notes: str | None,
    ) -> dict:
        """Record a rating in SQLite and return updated aggregates.

        Args:
            concept_id: UUID of the concept to rate.
            outcome: Rating value 1–5.
            session_id: Optional session identifier.
            hours_saved: Optional hours-saved estimate.
            notes: Optional free-text notes.

        Returns:
            ``{"avg_rating": float, "time_saved_avg_hours": float | None}``
        """
        rating = Rating(
            rating_id=str(uuid.uuid4()),
            concept_id=concept_id,
            session_id=session_id,
            outcome=outcome,
            hours_saved=hours_saved,
            notes=notes,
        )
        insert_rating(self._conn, rating)

        updated = get_concept(self._conn, concept_id)
        return {
            "avg_rating": updated.avg_rating if updated else 0.0,
            "time_saved_avg_hours": updated.time_saved_avg_hours if updated else None,
        }

    def log_session_usage(self, session_id: str, concept_id: str) -> None:
        """Log a session-concept usage event in SQLite.

        Args:
            session_id: Session identifier string.
            concept_id: Concept that was used in this session.
        """
        try:
            log_session_usage(self._conn, session_id, concept_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to log session usage for %s: %s", concept_id, exc
            )

    def insert_link(self, from_id: str, to_id: str, rel: str, label: str | None) -> str:
        """Insert a directed link between two concepts.

        Args:
            from_id: Source concept UUID.
            to_id: Target concept UUID.
            rel: Relationship type string.
            label: Optional human-readable label.

        Returns:
            The ``link_id`` of the inserted link.
        """
        link = Link(
            link_id=str(uuid.uuid4()),
            from_id=from_id,
            to_id=to_id,
            rel=rel,
            label=label,
        )
        return insert_link(self._conn, link)

    def find_near_duplicate(
        self, query_vector: list[float]
    ) -> tuple[str, float] | None:
        """Check for a near-duplicate concept in Qdrant.

        Args:
            query_vector: Embedding vector of the candidate concept.

        Returns:
            ``(concept_id, score)`` if a near-duplicate is found, else ``None``.
        """
        return find_near_duplicate(self._qdrant, COLLECTION_NAME, query_vector)

    def health_check(self) -> dict:
        """Check SQLite and Qdrant connectivity.

        Returns:
            ``{"status": "ok", "qdrant": bool, "db": bool}``
        """
        qdrant_ok = False
        db_ok = False

        try:
            self._qdrant.get_collections()
            qdrant_ok = True
        except Exception:  # noqa: BLE001
            pass

        try:
            self._conn.execute("SELECT 1")
            db_ok = True
        except Exception:  # noqa: BLE001
            pass

        return {"status": "ok", "qdrant": qdrant_ok, "db": db_ok}
