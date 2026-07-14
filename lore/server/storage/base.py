"""Abstract base class for Lore storage backends.

Every storage backend that the unified FastAPI server can route to must
implement this interface.  The HTTP layer in ``lore.server.api`` calls these
methods and expects the canonical shapes documented below.  The HTTP layer
never touches backend-specific objects on the common CRUD path.  Admin/metrics
routes may access backend-specific accessors directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """Abstract storage backend interface for the Lore unified server.

    Concrete implementations:
    - :class:`~lore.server.storage.sqlite_qdrant.SqliteQdrantBackend` — Backend 1
    - :class:`~lore.server.storage.gist_qdrant.GistQdrantBackend` — Backend 3
    """

    @abstractmethod
    def upsert_concept(self, payload: dict) -> dict:
        """Store or update a concept.

        Args:
            payload: A dict containing all concept fields.  The exact keys
                consumed depend on the concrete implementation but must at
                minimum include ``name``, ``type``, ``content``,
                ``when_to_use``, and for Backend 3, ``gist_id`` and
                ``gist_updated_at``.

        Returns:
            ``{"concept_id": str, "status": "upserted" | "skipped"}`` in the
            normal case.

            When the primary store (SQLite) succeeds but the secondary index
            (Qdrant) fails, a concrete implementation **may** return
            ``{"concept_id": str, "_qdrant_failed": True}`` instead of
            raising.  The HTTP layer interprets this as HTTP 503 and includes
            the ``concept_id`` in the response body so the caller can
            re-trigger indexing.  The primary store row is intentionally NOT
            rolled back — this is a transitional contract until LORE-033
            introduces a typed result class.
        """

    @abstractmethod
    def search_concepts(
        self,
        query_vector: list[float],
        limit: int,
        type_filter: str | None,
        language_filter: str | None,
        min_rating: float,
    ) -> list[dict]:
        """Search for concepts semantically similar to the query vector.

        Args:
            query_vector: Pre-computed embedding of the search query.
            limit: Maximum number of results to return.
            type_filter: Optional concept type to filter by (e.g. ``"pattern"``).
            language_filter: Optional programming language to filter by.
            min_rating: Minimum average rating threshold; concepts below this
                are excluded from results.

        Returns:
            List of concept dicts in the canonical ``ConceptResult`` shape —
            same fields as returned by ``GET /v1/concepts/{id}`` plus
            ``links: []`` and optionally ``score``.
        """

    @abstractmethod
    def get_concept(self, concept_id: str) -> dict | None:
        """Retrieve a single concept by its ID.

        Args:
            concept_id: The unique identifier of the concept to fetch.

        Returns:
            Full concept dict (same shape as search results) or ``None`` if
            the concept does not exist.
        """

    @abstractmethod
    def rate_concept(
        self,
        concept_id: str,
        outcome: int,
        session_id: str | None,
        hours_saved: float | None,
        notes: str | None,
    ) -> dict:
        """Record a concept rating and return updated aggregate statistics.

        Args:
            concept_id: The concept to rate.
            outcome: Rating value (1–5 inclusive).
            session_id: Optional session identifier for traceability.
            hours_saved: Optional hours saved estimate; ``None`` if omitted.
            notes: Optional free-text notes about this rating.

        Returns:
            ``{"avg_rating": float, "time_saved_avg_hours": float | None}``

        Raises:
            NotImplementedError: Subclasses that do not support ratings should
                implement this method by raising ``NotImplementedError``.  The
                HTTP layer translates that to HTTP 501.
        """

    @abstractmethod
    def add_rating(self, concept_id: str, outcome: int, hours_saved: float | None) -> dict:
        """Append a rating to a concept and return updated aggregates.

        Args:
            concept_id: The concept identifier (treated as gist_id on Backend 3).
            outcome: Rating value (1–5 inclusive).
            hours_saved: Optional hours saved estimate; None if omitted.

        Returns:
            ``{"avg_outcome": float, "avg_hours_saved": float | None}``

        Raises:
            NotImplementedError: Subclasses that do not support this method
                should raise NotImplementedError. The HTTP layer maps this to HTTP 501.
            KeyError: If the concept does not exist.
        """

    @abstractmethod
    def health_check(self) -> dict:
        """Check the health of the storage backend.

        Returns:
            ``{"status": "ok"}`` if the backend is healthy.

        Raises:
            Exception: If the backend is in an unhealthy state.
        """
