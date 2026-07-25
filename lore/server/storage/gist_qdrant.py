"""Backend 3 storage implementation: Qdrant-only with denormalized payloads.

All concept metadata is stored directly in the Qdrant point payload — there is
no SQLite layer.  This makes the backend independently deployable and suitable
for a community public corpus where durability guarantees are relaxed.

Deterministic point IDs (via ``uuid.uuid5``) make upserts idempotent without a
separate lookup table.

Design decisions
----------------
- ``concept_id`` in search/get results is set to ``gist_id`` so the caller-
  facing API is backend-agnostic.
- ``links`` is always ``[]`` — graph-link resolution is out of scope for this
  backend (LORE-033 will add rating support; links are a separate follow-on).
- Idempotency on ``upsert_concept``: if the stored ``gist_updated_at`` matches
  the request value the embedding step is skipped and ``{"status": "skipped"}``
  is returned immediately.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from statistics import mean

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from lore.core.constants import embedding_text
from lore.mcp.embeddings import EmbeddingModel
from lore.server.storage.base import StorageBackend

logger = logging.getLogger(__name__)

COLLECTION_NAME = "lore_concepts"
VECTOR_SIZE = 384  # all-MiniLM-L6-v2 output dimension


def _gist_id_to_point_id(gist_id: str) -> str:
    """Convert a GitHub gist ID to a deterministic Qdrant point UUID.

    Uses ``uuid.uuid5(uuid.NAMESPACE_URL, gist_id)`` so the mapping is stable
    across restarts and upserts are idempotent without a lookup table.

    Args:
        gist_id: The GitHub gist identifier string.

    Returns:
        A UUID string suitable for use as a Qdrant point ID.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, gist_id))


def _payload_to_result(payload: dict, score: float) -> dict:
    """Convert a Qdrant point payload to a canonical concept result dict.

    Maps stored payload fields to the shape expected by ``BackendRouter``
    callers.  ``concept_id`` is set to ``gist_id`` so the caller-facing
    API is backend-agnostic.  ``links`` is always ``[]``.

    Args:
        payload: The Qdrant point payload dict.
        score: Cosine similarity score from Qdrant.

    Returns:
        A JSON-serializable concept dict with a ``score`` field appended.
    """
    return {
        "concept_id": payload.get("gist_id", ""),
        "name": payload.get("name", ""),
        "type": payload.get("type", ""),
        "language": payload.get("language"),
        "author": payload.get("author"),
        "tags": payload.get("tags", []),
        "when_to_use": payload.get("when_to_use", ""),
        "dont_use_when": payload.get("dont_use_when"),
        "avg_rating": payload.get("avg_outcome"),
        "usage_count": payload.get("usage_count", 0),
        "time_saved_avg_hours": payload.get("avg_hours_saved"),
        "avg_outcome": payload.get("avg_outcome"),
        "avg_hours_saved": payload.get("avg_hours_saved"),
        "content": None,
        "source_url": None,
        "created_at": None,
        "links": [],
        "score": round(score, 6),
    }


def _init_collection(client: QdrantClient) -> None:
    """Create the ``lore_concepts`` Qdrant collection if it does not exist.

    Idempotent — safe to call on an already-existing collection.  Payload
    indexes are created on ``type``, ``language``, ``tags``, and ``author``
    for efficient server-side filtering.

    Args:
        client: An active :class:`~qdrant_client.QdrantClient` instance.
    """
    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=qmodels.VectorParams(
                size=VECTOR_SIZE,
                distance=qmodels.Distance.COSINE,
            ),
        )
        logger.info("Created Qdrant collection '%s'.", COLLECTION_NAME)

        for field_name, field_type in [
            ("type", qmodels.PayloadSchemaType.KEYWORD),
            ("language", qmodels.PayloadSchemaType.KEYWORD),
            ("author", qmodels.PayloadSchemaType.KEYWORD),
        ]:
            client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name=field_name,
                field_schema=field_type,
            )

        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="tags",
            field_schema=qmodels.PayloadSchemaType.KEYWORD,
        )
        logger.info("Created payload indexes on type, language, author, tags.")
    else:
        logger.info(
            "Qdrant collection '%s' already exists — skipping init.", COLLECTION_NAME
        )


class GistQdrantBackend(StorageBackend):
    """Backend 3: Qdrant-only storage with denormalized concept payloads.

    No SQLite layer — all metadata lives in the Qdrant point payload.
    Designed for the community public corpus (semantic server).

    Args:
        qdrant_host: Hostname for the Qdrant service.
        qdrant_port: Port number for the Qdrant service.
        model: Pre-loaded :class:`~lore.mcp.embeddings.EmbeddingModel` instance.
    """

    def __init__(
        self,
        qdrant_host: str,
        qdrant_port: int,
        model: EmbeddingModel,
    ) -> None:
        logger.info("Connecting to Qdrant at %s:%s", qdrant_host, qdrant_port)
        self._qdrant = QdrantClient(host=qdrant_host, port=qdrant_port)
        self._model = model

        try:
            _init_collection(self._qdrant)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Qdrant collection init failed (will retry on first use): %s", exc
            )

    # ------------------------------------------------------------------
    # Public accessors — used by the HTTP layer for gist-specific routes
    # ------------------------------------------------------------------

    @property
    def qdrant(self) -> QdrantClient:
        """Return the raw QdrantClient for use by HTTP-layer routes."""
        return self._qdrant

    @property
    def model(self) -> EmbeddingModel:
        """Return the EmbeddingModel for use by HTTP-layer routes."""
        return self._model

    # ------------------------------------------------------------------
    # StorageBackend interface
    # ------------------------------------------------------------------

    def upsert_concept(self, payload: dict) -> dict:
        """Upsert a concept into Qdrant with a full denormalized payload.

        Idempotency: retrieves the existing Qdrant point by deterministic ID.
        If the stored ``gist_updated_at`` payload value matches the request
        value the embedding step is skipped and ``{"status": "skipped"}`` is
        returned immediately.

        Args:
            payload: Dict containing ``gist_id``, ``name``, ``type``,
                ``when_to_use``, ``gist_updated_at``, and optional fields.

        Returns:
            ``{"status": "skipped"|"upserted", "gist_id": str}``
        """
        gist_id: str = payload["gist_id"]
        point_id = _gist_id_to_point_id(gist_id)

        avg_rating = payload.get("avg_rating")
        avg_hours_saved = payload.get("avg_hours_saved")

        # Idempotency check: if content unchanged, only update rating fields.
        existing = self._qdrant.retrieve(
            collection_name=COLLECTION_NAME,
            ids=[point_id],
            with_payload=True,
        )
        if existing:
            stored_updated_at = existing[0].payload.get("gist_updated_at")  # type: ignore[union-attr]
            if stored_updated_at == payload.get("gist_updated_at"):
                # Content unchanged — update rating fields if they differ.
                stored_avg = existing[0].payload.get("avg_outcome")  # type: ignore[union-attr]
                if avg_rating != stored_avg:
                    self._qdrant.set_payload(
                        collection_name=COLLECTION_NAME,
                        payload={"avg_outcome": avg_rating, "avg_hours_saved": avg_hours_saved},
                        points=[point_id],
                    )
                return {"status": "skipped", "gist_id": gist_id}

        # Embed and upsert.
        vector = self._model.embed(embedding_text(payload["when_to_use"], payload["name"]))

        qdrant_payload = {
            "gist_id": gist_id,
            "name": payload["name"],
            "type": payload["type"],
            "language": payload.get("language"),
            "author": payload.get("author"),
            "tags": payload.get("tags", []),
            "when_to_use": payload["when_to_use"],
            "dont_use_when": payload.get("dont_use_when"),
            "gist_updated_at": payload.get("gist_updated_at", ""),
            "avg_outcome": avg_rating,
            "avg_hours_saved": avg_hours_saved,
            "rating_count": 0,
            "usage_count": 0,
        }

        self._qdrant.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                qmodels.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=qdrant_payload,
                )
            ],
        )
        logger.info(
            "Upserted concept '%s' (gist_id=%s).", payload["name"], gist_id
        )
        return {"status": "upserted", "gist_id": gist_id}

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
            query_vector: Pre-computed embedding vector from the HTTP layer.
            limit: Maximum number of results.
            type_filter: Not currently applied server-side (future work).
            language_filter: Not currently applied server-side (future work).
            min_rating: Not currently applied server-side (future work).

        Returns:
            List of concept dicts in the canonical shape, each with
            ``links: []`` and a ``score`` field.
        """
        try:
            response = self._qdrant.query_points(
                collection_name=COLLECTION_NAME,
                query=query_vector,
                limit=limit,
                with_payload=True,
            )
            hits = response.points
        except Exception as exc:  # noqa: BLE001
            if "doesn't exist" in str(exc) or "Not found" in str(exc):
                return []
            raise

        return [
            _payload_to_result(hit.payload, hit.score)  # type: ignore[arg-type]
            for hit in hits
            if hit.payload
        ]

    def get_concept(self, concept_id: str) -> dict | None:
        """Retrieve a concept from Qdrant by gist_id.

        The ``concept_id`` parameter is treated as a ``gist_id``.  The
        deterministic point UUID is derived and retrieved from Qdrant.

        Args:
            concept_id: The ``gist_id`` string to look up.

        Returns:
            Full concept dict or ``None`` if not found.
        """
        point_id = _gist_id_to_point_id(concept_id)
        results = self._qdrant.retrieve(
            collection_name=COLLECTION_NAME,
            ids=[point_id],
            with_payload=True,
        )
        if not results or not results[0].payload:
            return None
        return _payload_to_result(results[0].payload, 1.0)

    def add_rating(self, concept_id: str, outcome: int, hours_saved: float | None) -> dict:
        """Append a rating to a concept's Qdrant payload and return updated aggregates.

        Looks up the Qdrant point by gist_id, appends the new rating entry to the
        ``ratings`` list in the payload, recomputes ``avg_outcome`` and
        ``avg_hours_saved``, then writes the updated fields back with
        ``set_payload``.

        Args:
            concept_id: The gist ID string to look up.
            outcome: Rating value (1–5 inclusive).
            hours_saved: Optional hours saved estimate; None if omitted.

        Returns:
            ``{"avg_outcome": float, "avg_hours_saved": float | None}``

        Raises:
            KeyError: If no Qdrant point exists for the given concept_id.
        """
        point_id = _gist_id_to_point_id(concept_id)
        results = self._qdrant.retrieve(
            collection_name=COLLECTION_NAME,
            ids=[point_id],
            with_payload=True,
        )
        if not results or not results[0].payload:
            raise KeyError(concept_id)

        existing_payload = results[0].payload
        ratings: list[dict] = list(existing_payload.get("ratings", []))
        ratings.append(
            {
                "outcome": outcome,
                "hours_saved": hours_saved,
                "ts": datetime.utcnow().isoformat() + "Z",
            }
        )

        avg_outcome = sum(r["outcome"] for r in ratings) / len(ratings)
        hours_values = [r["hours_saved"] for r in ratings if r["hours_saved"] is not None]
        avg_hours_saved: float | None = mean(hours_values) if hours_values else None

        self._qdrant.set_payload(
            collection_name=COLLECTION_NAME,
            payload={
                "ratings": ratings,
                "avg_outcome": avg_outcome,
                "avg_hours_saved": avg_hours_saved,
                "rating_count": len(ratings),
            },
            points=[point_id],
        )
        logger.info(
            "Rated concept gist_id=%s outcome=%d avg_outcome=%.3f",
            concept_id,
            outcome,
            avg_outcome,
        )
        return {"avg_outcome": avg_outcome, "avg_hours_saved": avg_hours_saved}

    def rate_concept(
        self,
        concept_id: str,
        outcome: int,
        session_id: str | None,
        hours_saved: float | None,
        notes: str | None,
    ) -> dict:
        """Rate a concept by delegating to :meth:`add_rating`.

        ``session_id`` and ``notes`` are accepted for interface compatibility
        but are not stored — Backend 3 uses the aggregated payload model.

        Args:
            concept_id: The gist ID string of the concept to rate.
            outcome: Rating value (1–5 inclusive).
            session_id: Accepted but not stored.
            hours_saved: Optional hours saved estimate.
            notes: Accepted but not stored.

        Returns:
            ``{"avg_outcome": float, "avg_hours_saved": float | None}``

        Raises:
            KeyError: If the concept does not exist.
        """
        try:
            return self.add_rating(concept_id, outcome, hours_saved)
        except KeyError:
            raise  # let the HTTP layer handle 404

    def health_check(self) -> dict:
        """Check Qdrant connectivity.

        Returns:
            ``{"status": "ok"}``

        Raises:
            Exception: If Qdrant is unreachable.
        """
        # Lightweight check — just verify the connection responds.
        self._qdrant.get_collections()
        return {"status": "ok"}

    def search_similar(
        self,
        vector: list[float],
        top_k: int = 3,
        exclude_id: str | None = None,
    ) -> list[dict]:
        """Find concepts with high vector similarity to the given embedding.

        Used by the dedup check in the POST /concepts route to detect near-
        duplicates before upserting.

        Args:
            vector: Pre-computed embedding to compare against the collection.
            top_k: Maximum number of similar points to return.
            exclude_id: Optional gist_id (concept_id) to exclude from results —
                used to skip the concept being updated if its id is already known.

        Returns:
            List of dicts with ``id``, ``title``, and ``score`` keys, sorted
            descending by score.  Returns ``[]`` if the collection is empty or
            Qdrant is unreachable.
        """
        try:
            response = self._qdrant.query_points(
                collection_name=COLLECTION_NAME,
                query=vector,
                limit=top_k,
                with_payload=True,
            )
            hits = response.points
        except Exception as exc:  # noqa: BLE001
            if "doesn't exist" in str(exc) or "Not found" in str(exc):
                return []
            logger.warning("search_similar failed: %s", exc)
            return []

        results = []
        for hit in hits:
            if not hit.payload:
                continue
            gist_id = hit.payload.get("gist_id", "")
            if exclude_id and gist_id == exclude_id:
                continue
            results.append({
                "id": gist_id,
                "title": hit.payload.get("name", ""),
                "score": round(hit.score, 6),
            })
        return results
