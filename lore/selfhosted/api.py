"""FastAPI HTTP service for the Lore self-hosted backend (LORE-003).

This service exposes the SQLite + Qdrant storage layer as a REST API that the
MCP server (LORE-005) calls via HTTP.  All endpoints live under ``/v1/``.

Lifecycle
---------
A single :class:`~lore.mcp.embeddings.EmbeddingModel`, ``sqlite3.Connection``,
and ``QdrantClient`` are created inside the FastAPI ``lifespan`` context manager
and stored on ``app.state``.  They are shared across all requests without
per-request instantiation.

Known gap — SQLite/Qdrant write ordering
-----------------------------------------
``POST /v1/concepts`` inserts the concept into SQLite first, then calls
:func:`~lore.selfhosted.indexer.index_concept` to push the vector into Qdrant.
If Qdrant is unavailable after the SQLite insert completes, the concept exists
in SQLite but is **not** present in the vector index and therefore not
discoverable via ``POST /v1/concepts/search``.

This is a deliberate Phase 1 trade-off: rolling back the SQLite insert on a
Qdrant failure would leave the caller with no concept_id to retry with.
Instead the API returns HTTP 503 with the ``concept_id`` so the caller (or an
operator) can re-index the concept later.  The gap is tolerable for the
low-availability scenarios expected during Phase 1 (single-node Docker,
ephemeral dev environments).

Re-indexing path (future work): a ``POST /v1/concepts/{concept_id}/reindex``
endpoint or a background task that compares SQLite concept_ids against Qdrant
point IDs.

Environment variables
---------------------
LORE_DB_PATH   Filesystem path to the SQLite database.
               Default: ``~/.lore/lore.db``.  ``~`` is expanded at startup.
QDRANT_HOST    Qdrant hostname.  Default: ``localhost``.
QDRANT_PORT    Qdrant port (integer).  Default: ``6333``.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator, model_validator

from qdrant_client import QdrantClient

from lore.core.scanner import scan_content
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
from lore.selfhosted.vector_store import init_qdrant_collection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COLLECTION_NAME = "concepts"

VALID_CONCEPT_TYPES = {"project", "pattern", "tool", "testing", "architecture"}
VALID_LINK_RELS = {"uses", "tested_by", "extends", "alternative_to", "requires"}

# ---------------------------------------------------------------------------
# Dependency getters — injectable for testing via app.dependency_overrides
# ---------------------------------------------------------------------------


def get_db(request: Request) -> sqlite3.Connection:
    """Return the shared SQLite connection from app state.

    Args:
        request: FastAPI request carrying ``app.state.db``.

    Returns:
        The active ``sqlite3.Connection``.
    """
    return request.app.state.db


def get_qdrant(request: Request) -> QdrantClient:
    """Return the shared QdrantClient from app state.

    Args:
        request: FastAPI request carrying ``app.state.qdrant``.

    Returns:
        The active ``QdrantClient``.
    """
    return request.app.state.qdrant


def get_model(request: Request) -> EmbeddingModel:
    """Return the shared EmbeddingModel from app state.

    Args:
        request: FastAPI request carrying ``app.state.model``.

    Returns:
        The loaded ``EmbeddingModel``.
    """
    return request.app.state.model


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class LinkIn(BaseModel):
    """Inline link specification within a concept submission."""

    to_id: str
    rel: str
    label: Optional[str] = None


class ConceptSubmitRequest(BaseModel):
    """Request body for POST /v1/concepts."""

    name: str
    type: str
    content: str
    language: Optional[str] = None
    when_to_use: str
    dont_use_when: Optional[str] = None
    tags: list[str] = []
    source_url: Optional[str] = None
    author: Optional[str] = None
    links: list[LinkIn] = []

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Reject concept types not in the allowed set."""
        if v not in VALID_CONCEPT_TYPES:
            raise ValueError(
                f"Invalid concept type '{v}'. "
                f"Must be one of: {', '.join(sorted(VALID_CONCEPT_TYPES))}"
            )
        return v


class SearchRequest(BaseModel):
    """Request body for POST /v1/concepts/search."""

    problem: str
    type: Optional[str] = None
    language: Optional[str] = None
    limit: int = 5


class LinkRequest(BaseModel):
    """Request body for POST /v1/links."""

    from_id: str
    to_id: str
    rel: str
    label: Optional[str] = None

    @field_validator("rel")
    @classmethod
    def validate_rel(cls, v: str) -> str:
        """Reject link relationship types not in the allowed set."""
        if v not in VALID_LINK_RELS:
            raise ValueError(
                f"Invalid link rel '{v}'. "
                f"Must be one of: {', '.join(sorted(VALID_LINK_RELS))}"
            )
        return v


class RateRequest(BaseModel):
    """Request body for POST /v1/concepts/{concept_id}/rate."""

    session_id: Optional[str] = None
    outcome: int
    hours_saved: Optional[float] = None
    notes: Optional[str] = None

    @field_validator("outcome")
    @classmethod
    def validate_outcome(cls, v: int) -> int:
        """Reject outcome values outside the 1–5 range."""
        if not 1 <= v <= 5:
            raise ValueError("outcome must be between 1 and 5 inclusive")
        return v

    @field_validator("hours_saved")
    @classmethod
    def validate_hours_saved(cls, v: Optional[float]) -> Optional[float]:
        """Reject negative hours_saved values."""
        if v is not None and v < 0:
            raise ValueError("hours_saved must be non-negative")
        return v


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _concept_to_dict(concept: Concept) -> dict:
    """Serialize a :class:`Concept` to a plain dict for JSON responses.

    The ``embedding`` BLOB field is excluded — it is not meaningful over HTTP.

    Args:
        concept: The concept to serialize.

    Returns:
        A JSON-serializable dictionary with all non-binary concept fields.
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
    """Serialize a :class:`Link` to a plain dict for JSON responses.

    When ``conn`` is provided the linked concept's ``name``, ``type``, and
    ``when_to_use`` are fetched and included so callers get the full graph
    in a single API call — no second round-trip needed.

    Args:
        link: The link to serialize.
        conn: Optional SQLite connection for linked-concept enrichment.

    Returns:
        A JSON-serializable dictionary with all link fields plus optional
        ``name``, ``type``, and ``when_to_use`` from the linked concept.
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


# ---------------------------------------------------------------------------
# App factory + lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared resources at startup; clean up at shutdown.

    Resources created here are attached to ``app.state`` and reused for all
    requests.  No per-request instantiation.

    Raises:
        Exception: If any initialization step fails.  The process exits and
            the operator sees the error in logs rather than silently starting
            with broken state.
    """
    # Resolve DB path.
    db_path_raw = os.environ.get("LORE_DB_PATH", "~/.lore/lore.db")
    db_path = str(Path(db_path_raw).expanduser())
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    logger.info("Opening SQLite database at %s", db_path)
    conn: sqlite3.Connection = init_db(db_path)

    # Qdrant connection.
    qdrant_host = os.environ.get("QDRANT_HOST", "localhost")
    qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
    logger.info("Connecting to Qdrant at %s:%s", qdrant_host, qdrant_port)
    qdrant_client = QdrantClient(host=qdrant_host, port=qdrant_port)

    # Initialize Qdrant collection idempotently.
    try:
        init_qdrant_collection(qdrant_client, collection_name=COLLECTION_NAME)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Qdrant collection init failed (will retry on first use): %s", exc)

    # Load embedding model once at startup.
    logger.info("Loading embedding model…")
    embedding_model = EmbeddingModel()
    logger.info("Embedding model loaded.")

    app.state.db = conn
    app.state.qdrant = qdrant_client
    app.state.model = embedding_model

    yield

    logger.info("Shutting down — closing SQLite connection.")
    conn.close()


def create_app() -> FastAPI:
    """Construct and return the FastAPI application.

    Returns:
        A fully configured :class:`fastapi.FastAPI` instance ready to serve.
    """
    app = FastAPI(
        title="Lore Self-hosted API",
        version="1.0.0",
        description="Backend 1 HTTP service for the Lore knowledge graph.",
        lifespan=lifespan,
    )
    _register_routes(app)
    return app


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def _register_routes(app: FastAPI) -> None:
    """Attach all /v1/ routes to the application.

    Args:
        app: The :class:`~fastapi.FastAPI` instance to register routes on.
    """

    @app.get("/v1/health")
    async def health(request: Request):
        """Return service health — always HTTP 200; caller interprets booleans.

        Checks:
        - ``qdrant``: calls ``client.get_collections()``; False on any exception.
        - ``db``: runs ``SELECT 1``; False on any exception.

        Returns:
            JSON with ``status``, ``qdrant``, and ``db`` keys.
        """
        qdrant_ok = False
        db_ok = False

        try:
            request.app.state.qdrant.get_collections()
            qdrant_ok = True
        except Exception:  # noqa: BLE001
            pass

        try:
            request.app.state.db.execute("SELECT 1")
            db_ok = True
        except Exception:  # noqa: BLE001
            pass

        return {"status": "ok", "qdrant": qdrant_ok, "db": db_ok}

    @app.post("/v1/concepts", status_code=201)
    async def submit_concept(body: ConceptSubmitRequest, request: Request):
        """Submit a new concept to the knowledge graph.

        Steps:
        1. Run content scan — HTTP 422 if any blocked patterns are found.
        2. Insert concept into SQLite.
        3. Index concept into Qdrant via the embedding pipeline.
           If Qdrant is unreachable, return HTTP 503 with the concept_id so
           the caller can re-index later (see module docstring for known gap).
        4. Insert any inline links; invalid ``rel`` values are skipped with a
           warning.

        Args:
            body: Validated :class:`ConceptSubmitRequest`.
            request: FastAPI request (provides app.state).

        Returns:
            HTTP 201 ``{"concept_id": "...", "name": "..."}``.
        """
        # Content scan before any DB write.
        scan_fields = {
            "name": body.name,
            "content": body.content,
            "when_to_use": body.when_to_use,
        }
        matches = scan_content(scan_fields)
        if matches:
            return JSONResponse(
                status_code=422,
                content={"error": "Content blocked by scanner", "matches": matches},
            )

        concept_id = str(uuid.uuid4())
        concept = Concept(
            concept_id=concept_id,
            name=body.name,
            type=body.type,
            content=body.content,
            language=body.language,
            when_to_use=body.when_to_use,
            dont_use_when=body.dont_use_when,
            tags=body.tags,
            source_url=body.source_url,
            author=body.author,
        )

        conn: sqlite3.Connection = request.app.state.db
        qdrant_client: QdrantClient = request.app.state.qdrant
        model: EmbeddingModel = request.app.state.model

        insert_concept(conn, concept)

        try:
            index_concept(conn, qdrant_client, concept, model, COLLECTION_NAME)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Qdrant indexing failed for concept %s: %s", concept_id, exc
            )
            return JSONResponse(
                status_code=503,
                content={
                    "error": "Qdrant unavailable — concept saved but not indexed",
                    "concept_id": concept_id,
                },
            )

        # Insert inline links; skip invalid rel values with a warning.
        for link_in in body.links:
            if link_in.rel not in VALID_LINK_RELS:
                logger.warning(
                    "Skipping link with invalid rel '%s' during concept submit for %s",
                    link_in.rel,
                    concept_id,
                )
                continue
            link = Link(
                link_id=str(uuid.uuid4()),
                from_id=concept_id,
                to_id=link_in.to_id,
                rel=link_in.rel,
                label=link_in.label,
            )
            try:
                insert_link(conn, link)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to insert inline link to %s: %s", link_in.to_id, exc
                )

        return JSONResponse(
            status_code=201,
            content={"concept_id": concept_id, "name": body.name},
        )

    @app.get("/v1/concepts/{concept_id}")
    async def get_concept_endpoint(concept_id: str, request: Request):
        """Retrieve a concept and its links by ID.

        Args:
            concept_id: UUID string of the concept to retrieve.
            request: FastAPI request.

        Returns:
            HTTP 200 with full concept fields plus a ``links`` array.
            HTTP 404 if the concept does not exist.
        """
        conn: sqlite3.Connection = request.app.state.db
        concept = get_concept(conn, concept_id)
        if concept is None:
            return JSONResponse(
                status_code=404,
                content={"error": "not found", "concept_id": concept_id},
            )

        links = get_links_for_concept(conn, concept_id)
        result = _concept_to_dict(concept)
        result["links"] = [_link_to_dict(lnk, conn) for lnk in links]
        return result

    @app.post("/v1/concepts/search")
    async def search_concepts_endpoint(
        body: SearchRequest,
        request: Request,
        x_session_id: Optional[str] = Header(default=None),
    ):
        """Search for concepts semantically similar to a problem description.

        Embeds the ``problem`` text, queries Qdrant, fetches full SQLite records,
        and attaches links for each result.  Session usage is logged if the
        ``X-Session-ID`` header is present.

        Args:
            body: Validated :class:`SearchRequest`.
            request: FastAPI request.
            x_session_id: Optional session identifier from the ``X-Session-ID``
                header.

        Returns:
            HTTP 200 ``{"results": [...]}`` where each result is a full concept
            dict with a ``links`` array appended.  Empty results return
            ``{"results": []}`` with HTTP 200.
        """
        conn: sqlite3.Connection = request.app.state.db
        qdrant_client: QdrantClient = request.app.state.qdrant
        model: EmbeddingModel = request.app.state.model

        concepts = search_concepts(
            conn=conn,
            qdrant_client=qdrant_client,
            model=model,
            problem=body.problem,
            type_filter=body.type,
            language_filter=body.language,
            limit=body.limit,
            collection_name=COLLECTION_NAME,
        )

        results = []
        for concept in concepts:
            links = get_links_for_concept(conn, concept.concept_id)
            entry = _concept_to_dict(concept)
            entry["links"] = [_link_to_dict(lnk, conn) for lnk in links]
            results.append(entry)

            if x_session_id:
                try:
                    log_session_usage(conn, x_session_id, concept.concept_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to log session usage for %s: %s",
                        concept.concept_id,
                        exc,
                    )

        return {"results": results}

    @app.post("/v1/links", status_code=201)
    async def link_concepts_endpoint(body: LinkRequest, request: Request):
        """Create a directed link between two existing concepts.

        Both ``from_id`` and ``to_id`` must reference concepts that already
        exist in SQLite.

        Args:
            body: Validated :class:`LinkRequest`.
            request: FastAPI request.

        Returns:
            HTTP 201 ``{"link_id": "..."}``.
            HTTP 404 if either concept is missing.
        """
        conn: sqlite3.Connection = request.app.state.db

        from_concept = get_concept(conn, body.from_id)
        if from_concept is None:
            return JSONResponse(
                status_code=404,
                content={"error": "not found", "concept_id": body.from_id},
            )

        to_concept = get_concept(conn, body.to_id)
        if to_concept is None:
            return JSONResponse(
                status_code=404,
                content={"error": "not found", "concept_id": body.to_id},
            )

        link = Link(
            link_id=str(uuid.uuid4()),
            from_id=body.from_id,
            to_id=body.to_id,
            rel=body.rel,
            label=body.label,
        )
        link_id = insert_link(conn, link)
        return JSONResponse(status_code=201, content={"link_id": link_id})

    @app.post("/v1/concepts/{concept_id}/rate")
    async def rate_concept_endpoint(
        concept_id: str, body: RateRequest, request: Request
    ):
        """Rate a concept and return updated aggregate statistics.

        Args:
            concept_id: UUID string of the concept to rate.
            body: Validated :class:`RateRequest`.
            request: FastAPI request.

        Returns:
            HTTP 200 ``{"avg_rating": float, "time_saved_avg_hours": float|null}``.
            HTTP 404 if the concept does not exist.
        """
        conn: sqlite3.Connection = request.app.state.db

        concept = get_concept(conn, concept_id)
        if concept is None:
            return JSONResponse(
                status_code=404,
                content={"error": "not found", "concept_id": concept_id},
            )

        rating = Rating(
            rating_id=str(uuid.uuid4()),
            concept_id=concept_id,
            session_id=body.session_id,
            outcome=body.outcome,
            hours_saved=body.hours_saved,
            notes=body.notes,
        )
        insert_rating(conn, rating)

        # Refresh concept to get updated aggregates.
        updated = get_concept(conn, concept_id)
        return {
            "avg_rating": updated.avg_rating if updated else 0.0,
            "time_saved_avg_hours": updated.time_saved_avg_hours if updated else None,
        }


# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------

app = create_app()
