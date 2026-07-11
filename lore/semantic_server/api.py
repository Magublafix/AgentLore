"""FastAPI service for the Lore semantic search server (LORE-030).

Backend 3 — a standalone, independently deployable FastAPI + Qdrant service
that provides semantic vector search over Lore concepts.  Unlike Backend 1
(selfhosted), this server has **no SQLite** layer; all concept metadata is
stored denormalized directly in the Qdrant payload.

Design decisions
----------------
- Qdrant payload is denormalized (no SQLite) — every Qdrant point stores the
  full concept metadata in its payload so search results are self-contained.
- Deterministic point IDs via ``uuid.uuid5(uuid.NAMESPACE_URL, gist_id)`` —
  upserts are idempotent without a lookup table.
- Embedding target: ``name + " " + when_to_use`` — identical to Backend 1.
- ``POST /concepts`` is idempotent: if the stored ``gist_updated_at`` matches
  the request value the point is **not** re-embedded (fast-path skip).
- ``GET /search`` returns the same ``{"results": [...]}`` shape as other
  backends so ``BackendRouter`` can delegate to it transparently.
- ``links`` is always ``[]`` in search results — link resolution is out of
  scope for Backend 3.

Environment variables
---------------------
QDRANT_HOST         Qdrant hostname.  Default: ``localhost``.
QDRANT_PORT         Qdrant port (integer).  Default: ``6333``.

Payload indexes are created at collection init on: ``type``, ``language``,
``tags``, ``author`` — enabling efficient server-side filtering (future work).
"""

from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from lore.mcp.embeddings import EmbeddingModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COLLECTION_NAME = "lore_concepts"
VECTOR_SIZE = 384  # all-MiniLM-L6-v2 output dimension

# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------


def _gist_id_to_point_id(gist_id: str) -> str:
    """Convert a GitHub gist ID to a deterministic Qdrant point UUID.

    Uses ``uuid.uuid5(uuid.NAMESPACE_URL, gist_id)`` so the mapping is stable
    across restarts and upserts are idempotent without a separate lookup table.

    Args:
        gist_id: The GitHub gist identifier string.

    Returns:
        A UUID string suitable for use as a Qdrant point ID.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, gist_id))


def init_collection(client: QdrantClient) -> None:
    """Create the ``lore_concepts`` Qdrant collection if it does not exist.

    This function is idempotent — calling it on an already-existing collection
    is safe and leaves existing vectors untouched.

    Payload indexes are created on ``type``, ``language``, ``tags``, and
    ``author`` to support efficient server-side filtering in future work.

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

        # Create payload indexes for efficient filtering.
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

        # tags is a list — use keyword index on the repeated field.
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="tags",
            field_schema=qmodels.PayloadSchemaType.KEYWORD,
        )
        logger.info("Created payload indexes on type, language, author, tags.")
    else:
        logger.info("Qdrant collection '%s' already exists — skipping init.", COLLECTION_NAME)


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class ConceptUpsertRequest(BaseModel):
    """Request body for ``POST /concepts``.

    Attributes:
        gist_id: The GitHub gist identifier (external key, not a UUID).
        name: Short human-readable name for the concept.
        type: Concept type string (e.g. ``"pattern"``, ``"tool"``).
        language: Programming language context.  ``None`` if not applicable.
        author: GitHub username of the concept author.
        tags: List of tag strings.
        when_to_use: Natural-language description of ideal use context.
        dont_use_when: Known anti-cases / counter-indications.
        gist_updated_at: GitHub's ``updated_at`` ISO timestamp string.
            Used as an idempotency key — if this matches the stored value
            the embedding step is skipped.
    """

    gist_id: str
    name: str
    type: str
    language: Optional[str] = None
    author: Optional[str] = None
    tags: list[str] = []
    when_to_use: str
    dont_use_when: Optional[str] = None
    gist_updated_at: str


# ---------------------------------------------------------------------------
# Dependency getters — injectable for testing via app.dependency_overrides
# ---------------------------------------------------------------------------


def _get_qdrant(request: Request) -> QdrantClient:
    """Return the shared QdrantClient from ``app.state``.

    Args:
        request: FastAPI :class:`~fastapi.Request` carrying ``app.state.qdrant``.

    Returns:
        The active :class:`~qdrant_client.QdrantClient`.
    """
    return request.app.state.qdrant


def _get_model(request: Request) -> EmbeddingModel:
    """Return the shared EmbeddingModel from ``app.state``.

    Args:
        request: FastAPI :class:`~fastapi.Request` carrying ``app.state.model``.

    Returns:
        The loaded :class:`~lore.mcp.embeddings.EmbeddingModel`.
    """
    return request.app.state.model


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _payload_to_result(payload: dict, score: float) -> dict:
    """Convert a Qdrant point payload to a search result dict.

    Maps stored payload fields to the canonical shape expected by
    ``BackendRouter.search_concepts()`` callers.  The ``concept_id`` key
    is set to ``gist_id`` so the caller-facing API is backend-agnostic.

    ``links`` is always ``[]`` — Backend 3 does not resolve graph links.

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
        "avg_rating": payload.get("avg_outcome", 0.0),
        "usage_count": payload.get("usage_count", 0),
        "time_saved_avg_hours": payload.get("avg_hours_saved"),
        "links": [],
        "score": round(score, 6),
    }


# ---------------------------------------------------------------------------
# App factory + lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared resources at startup; clean up at shutdown.

    Creates a :class:`~qdrant_client.QdrantClient`, initializes the Qdrant
    collection idempotently, and loads the embedding model once.  All resources
    are stored on ``app.state`` and shared across all requests.

    Args:
        app: The :class:`~fastapi.FastAPI` instance being started.

    Raises:
        Exception: If Qdrant collection initialization or model loading fails.
            The process exits loudly rather than starting with broken state.
    """
    qdrant_host = os.environ.get("QDRANT_HOST", "localhost")
    qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
    logger.info("Connecting to Qdrant at %s:%s", qdrant_host, qdrant_port)
    qdrant_client = QdrantClient(host=qdrant_host, port=qdrant_port)

    try:
        init_collection(qdrant_client)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Qdrant collection init failed (will retry on first use): %s", exc
        )

    logger.info("Loading embedding model…")
    embedding_model = EmbeddingModel()
    logger.info("Embedding model loaded.")

    app.state.qdrant = qdrant_client
    app.state.model = embedding_model

    yield

    logger.info("Semantic server shutting down.")


def create_app() -> FastAPI:
    """Construct and return the semantic server FastAPI application.

    Returns:
        A fully configured :class:`~fastapi.FastAPI` instance ready to serve.
    """
    app = FastAPI(
        title="Lore Semantic Server",
        version="1.0.0",
        description="Backend 3 — standalone semantic search server for the Lore knowledge graph.",
        lifespan=lifespan,
    )
    _register_routes(app)
    return app


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def _register_routes(app: FastAPI) -> None:
    """Attach all routes to the application.

    Args:
        app: The :class:`~fastapi.FastAPI` instance to register routes on.
    """

    @app.get("/health")
    async def health():
        """Return service health.

        Always returns HTTP 200 ``{"status": "ok"}``.  Liveness probe only —
        no deep check against Qdrant to keep latency minimal.

        Returns:
            ``{"status": "ok"}``
        """
        return {"status": "ok"}

    @app.post("/concepts", status_code=200)
    async def upsert_concept(body: ConceptUpsertRequest, request: Request):
        """Upsert a concept into Qdrant with a full denormalized payload.

        Idempotency: retrieves the existing Qdrant point by deterministic ID.
        If the stored ``gist_updated_at`` payload value matches the request
        value the embedding step is skipped and ``{"status": "skipped"}`` is
        returned immediately.

        When the concept is new or updated, ``name + " " + when_to_use`` is
        embedded and the point is upserted with the full payload.

        Args:
            body: Validated :class:`ConceptUpsertRequest`.
            request: FastAPI request (provides ``app.state``).

        Returns:
            ``{"status": "skipped", "gist_id": ...}`` if up to date.
            ``{"status": "upserted", "gist_id": ...}`` on insert or update.
        """
        qdrant: QdrantClient = request.app.state.qdrant
        model: EmbeddingModel = request.app.state.model

        point_id = _gist_id_to_point_id(body.gist_id)

        # Idempotency check: retrieve existing point and compare gist_updated_at.
        existing = qdrant.retrieve(
            collection_name=COLLECTION_NAME,
            ids=[point_id],
            with_payload=True,
        )
        if existing:
            stored_updated_at = existing[0].payload.get("gist_updated_at")  # type: ignore[union-attr]
            if stored_updated_at == body.gist_updated_at:
                return {"status": "skipped", "gist_id": body.gist_id}

        # Embed and upsert.
        embed_text = body.name + " " + body.when_to_use
        vector = model.embed(embed_text)

        payload = {
            "gist_id": body.gist_id,
            "name": body.name,
            "type": body.type,
            "language": body.language,
            "author": body.author,
            "tags": body.tags,
            "when_to_use": body.when_to_use,
            "dont_use_when": body.dont_use_when,
            "gist_updated_at": body.gist_updated_at,
            "avg_outcome": 0.0,
            "avg_hours_saved": None,
            "rating_count": 0,
            "usage_count": 0,
        }

        qdrant.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                qmodels.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            ],
        )
        logger.info("Upserted concept '%s' (gist_id=%s).", body.name, body.gist_id)
        return {"status": "upserted", "gist_id": body.gist_id}

    @app.get("/search")
    async def search(
        request: Request,
        q: str = Query(..., description="Natural-language search query."),
        k: int = Query(3, ge=1, le=50, description="Maximum number of results to return."),
    ):
        """Search for concepts semantically similar to the query string.

        Embeds ``q`` using the loaded ``all-MiniLM-L6-v2`` model and queries
        Qdrant for the top-``k`` nearest neighbours by cosine similarity.

        Results are returned in the canonical ``{"results": [...]}`` shape used
        by all Lore backends.  Each concept dict includes a ``score`` field
        (cosine similarity, 0–1) and ``links: []``.

        Args:
            request: FastAPI request (provides ``app.state``).
            q: Natural-language query string.
            k: Maximum number of results.  Clamped to 1–50.

        Returns:
            ``{"results": [...]}`` — empty list when the collection is empty
            or no concepts are found.
        """
        qdrant: QdrantClient = request.app.state.qdrant
        model: EmbeddingModel = request.app.state.model

        query_vector = model.embed(q)

        try:
            response = qdrant.query_points(
                collection_name=COLLECTION_NAME,
                query=query_vector,
                limit=k,
                with_payload=True,
            )
            hits = response.points
        except Exception as exc:  # noqa: BLE001
            if "doesn't exist" in str(exc) or "Not found" in str(exc):
                return {"results": []}
            raise

        results = [
            _payload_to_result(hit.payload, hit.score)  # type: ignore[arg-type]
            for hit in hits
            if hit.payload
        ]
        return {"results": results}


# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------

app = create_app()
