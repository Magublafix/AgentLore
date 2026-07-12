"""Unified FastAPI server for the Lore knowledge graph.

Replaces both ``lore.selfhosted.api`` (Backend 1, port 8765) and
``lore.semantic_server.api`` (Backend 3, port 8766) with a single application
that selects its storage backend via the ``LORE_STORAGE_BACKEND`` environment
variable.

Backend selection
-----------------
``LORE_STORAGE_BACKEND=sqlite_qdrant``  (default)
    Backend 1: SQLite + Qdrant.  Activates all ``/v1/`` routes, metrics, and
    admin reset.  The bare ``/concepts`` and ``/search`` routes return 404.

``LORE_STORAGE_BACKEND=gist_qdrant``
    Backend 3: Qdrant-only with denormalized payloads.  Activates all
    ``/v1/`` routes *and* the bare ``/concepts`` / ``/search`` routes used by
    the BackendRouter ``_semantic_search`` method.  ``/v1/metrics`` and
    ``/v1/admin/reset`` return 404.

HTTP API surface (``/v1/``)
---------------------------
Every path below is identical to the original ``selfhosted/api.py`` so the
MCP router (``lore.mcp.router``) requires no changes.

GET  /v1/health
GET  /v1/metrics              (sqlite_qdrant only)
DELETE /v1/admin/reset        (sqlite_qdrant only)
POST /v1/concepts
GET  /v1/concepts/{concept_id}
POST /v1/concepts/search
POST /v1/links
POST /v1/concepts/{concept_id}/rate

Additional routes (gist_qdrant only)
-------------------------------------
POST /concepts                # upsert — called by the gists sync job
GET  /search                  # semantic search — called by BackendRouter

Environment variables
---------------------
LORE_STORAGE_BACKEND    Backend selector.  Default: ``sqlite_qdrant``.
LORE_DB_PATH            SQLite path (sqlite_qdrant only).  Default: ``~/.lore/lore.db``.
QDRANT_HOST             Qdrant hostname.  Default: ``localhost``.
QDRANT_PORT             Qdrant port (integer).  Default: ``6333``.
LORE_ADMIN_TOKEN        Token required for DELETE /v1/admin/reset.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from lore.core.constants import VALID_CONCEPT_TYPES, VALID_LINK_RELS, embedding_text
from lore.core.scanner import scan_content
from lore.mcp.embeddings import EmbeddingModel
from lore.server.storage.base import StorageBackend

logger = logging.getLogger(__name__)

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
    limit: int = 3
    min_rating: float = 2.0


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


class ConceptUpsertRequest(BaseModel):
    """Request body for POST /concepts (gist_qdrant backend only).

    Mirrors the request shape from the original ``lore.semantic_server.api``.
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
# Backend factory
# ---------------------------------------------------------------------------


def _create_backend(model: EmbeddingModel, backend_name: str) -> StorageBackend:
    """Instantiate the appropriate storage backend.

    Args:
        model: Pre-loaded :class:`~lore.mcp.embeddings.EmbeddingModel`.
        backend_name: ``"sqlite_qdrant"`` or ``"gist_qdrant"``.

    Returns:
        A concrete :class:`~lore.server.storage.base.StorageBackend` instance.

    Raises:
        ValueError: If ``backend_name`` is not a known backend identifier.
    """
    qdrant_host = os.environ.get("QDRANT_HOST", "localhost")
    qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))

    if backend_name == "sqlite_qdrant":
        from lore.server.storage.sqlite_qdrant import SqliteQdrantBackend

        db_path_raw = os.environ.get("LORE_DB_PATH", "~/.lore/lore.db")
        db_path = str(Path(db_path_raw).expanduser())
        return SqliteQdrantBackend(
            sqlite_path=db_path,
            qdrant_host=qdrant_host,
            qdrant_port=qdrant_port,
            model=model,
        )

    if backend_name == "gist_qdrant":
        from lore.server.storage.gist_qdrant import GistQdrantBackend

        return GistQdrantBackend(
            qdrant_host=qdrant_host,
            qdrant_port=qdrant_port,
            model=model,
        )

    raise ValueError(
        f"Unknown LORE_STORAGE_BACKEND '{backend_name}'. "
        "Valid values: 'sqlite_qdrant', 'gist_qdrant'."
    )


# ---------------------------------------------------------------------------
# App factory + lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared resources at startup; clean up at shutdown.

    Loads the embedding model once, then instantiates the storage backend
    selected by ``LORE_STORAGE_BACKEND``.  Both are stored on ``app.state``
    and shared across all requests.

    Args:
        app: The :class:`~fastapi.FastAPI` instance being started.
    """
    backend_name = os.environ.get("LORE_STORAGE_BACKEND", "sqlite_qdrant")
    logger.info("Starting Lore unified server with backend: %s", backend_name)

    logger.info("Loading embedding model…")
    model = EmbeddingModel()
    logger.info("Embedding model loaded.")

    storage = _create_backend(model, backend_name)

    app.state.storage = storage
    app.state.model = model
    app.state.backend_name = backend_name

    # Start background Gist watcher when using the gist_qdrant backend.
    watcher_task: asyncio.Task | None = None
    if backend_name == "gist_qdrant":
        from lore.server.watcher import watch_loop

        interval = int(os.environ.get("LORE_WATCH_INTERVAL", "300"))
        token = os.environ.get("LORE_GITHUB_TOKEN", "")
        watcher_task = asyncio.create_task(watch_loop(storage, token, interval))
        logger.info("Gist watcher task started (interval=%ds).", interval)

    yield

    # Shutdown: cancel watcher task first, then close storage.
    if watcher_task is not None:
        watcher_task.cancel()
        with suppress(asyncio.CancelledError):
            await watcher_task
        logger.info("Gist watcher task stopped.")

    # Close SQLite connection if backend supports it.
    if hasattr(storage, "close"):
        storage.close()
    logger.info("Lore unified server shut down.")


def create_app() -> FastAPI:
    """Construct and return the unified FastAPI application.

    Returns:
        A fully configured :class:`~fastapi.FastAPI` instance.
    """
    app = FastAPI(
        title="Lore Unified API",
        version="1.0.0",
        description="Unified backend server for the Lore knowledge graph.",
        lifespan=lifespan,
    )
    _register_v1_routes(app)
    _register_gist_routes(app)
    return app


# ---------------------------------------------------------------------------
# Route registration — /v1/ (common surface)
# ---------------------------------------------------------------------------


def _register_v1_routes(app: FastAPI) -> None:  # noqa: C901 — deliberate, all routes in one fn
    """Register all /v1/ routes on the application.

    The HTTP surface is identical to the original ``lore.selfhosted.api``
    so ``lore.mcp.router`` requires no changes.

    Args:
        app: The :class:`~fastapi.FastAPI` instance to register routes on.
    """

    @app.get("/v1/health")
    async def health(request: Request):
        """Return service health status.

        For the ``sqlite_qdrant`` backend this checks both Qdrant and SQLite
        connectivity and returns ``{"status": "ok", "qdrant": bool, "db": bool}``.

        For the ``gist_qdrant`` backend this returns ``{"status": "ok"}`` only.

        Returns:
            JSON health dict — always HTTP 200; caller inspects the booleans.
        """
        storage: StorageBackend = request.app.state.storage
        return storage.health_check()

    @app.get("/v1/metrics")
    async def metrics(request: Request):
        """Return aggregate knowledge-base statistics (sqlite_qdrant only).

        Returns:
            HTTP 200 with ``concept_count``, ``rating_count``, ``avg_rating``.
            HTTP 404 for the ``gist_qdrant`` backend.
        """
        if request.app.state.backend_name != "sqlite_qdrant":
            return JSONResponse(
                status_code=404,
                content={"error": "metrics not available for this backend"},
            )

        from lore.server.storage.sqlite_qdrant import SqliteQdrantBackend

        storage: SqliteQdrantBackend = request.app.state.storage
        conn = storage.db
        concept_count = conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
        row = conn.execute(
            "SELECT COUNT(*), AVG(CAST(outcome AS REAL)) FROM ratings"
        ).fetchone()
        rating_count = row[0]
        avg_rating = round(row[1], 3) if row[1] is not None else None
        return {
            "concept_count": concept_count,
            "rating_count": rating_count,
            "avg_rating": avg_rating,
        }

    @app.delete("/v1/admin/reset", status_code=200)
    async def admin_reset(request: Request):
        """Wipe all data from SQLite and delete the Qdrant collection (sqlite_qdrant only).

        Requires the ``X-Admin-Token`` header to match the ``LORE_ADMIN_TOKEN``
        environment variable.  If that variable is unset, this endpoint is
        disabled.

        Returns:
            HTTP 200 with ``concepts_deleted`` and ``ratings_deleted`` counts.
            HTTP 403 if the admin token is missing or incorrect.
            HTTP 404 for the ``gist_qdrant`` backend.
        """
        if request.app.state.backend_name != "sqlite_qdrant":
            return JSONResponse(
                status_code=404,
                content={"error": "admin/reset not available for this backend"},
            )

        _admin_token = os.environ.get("LORE_ADMIN_TOKEN", "")
        if not _admin_token or request.headers.get("X-Admin-Token") != _admin_token:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Admin token required")

        from lore.server.storage.sqlite_qdrant import SqliteQdrantBackend, COLLECTION_NAME

        storage: SqliteQdrantBackend = request.app.state.storage
        conn = storage.db
        qdrant_client = storage.qdrant

        ratings_deleted = conn.execute("SELECT COUNT(*) FROM ratings").fetchone()[0]
        concepts_deleted = conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
        conn.execute("DELETE FROM ratings")
        conn.execute("DELETE FROM concepts")
        conn.commit()

        try:
            qdrant_client.delete_collection(COLLECTION_NAME)
        except Exception:  # noqa: BLE001
            pass

        return {
            "concepts_deleted": concepts_deleted,
            "ratings_deleted": ratings_deleted,
        }

    @app.post("/v1/concepts", status_code=201)
    async def submit_concept(body: ConceptSubmitRequest, request: Request):
        """Submit a new concept to the knowledge graph.

        Steps:
        1. Content scan — HTTP 422 if any blocked patterns are found.
        2. Semantic dedup (sqlite_qdrant only) — HTTP 409 if similarity ≥ 0.88.
        3. Insert concept via the active storage backend.
        4. Insert any inline links (sqlite_qdrant only).

        Args:
            body: Validated :class:`ConceptSubmitRequest`.
            request: FastAPI request.

        Returns:
            HTTP 201 ``{"concept_id": "...", "name": "..."}``.
            HTTP 409 ``{"error": "semantic_duplicate", ...}`` on duplicate.
            HTTP 422 on scan block.
            HTTP 503 if Qdrant is unreachable after SQLite insert.
        """
        # --- Step 1: content scan ---
        scan_fields = {
            "name": body.name,
            "content": body.content,
            "when_to_use": body.when_to_use,
            "dont_use_when": body.dont_use_when,
        }
        matches = scan_content(scan_fields)
        if matches:
            return JSONResponse(
                status_code=422,
                content={"error": "Content blocked by scanner", "matches": matches},
            )

        storage: StorageBackend = request.app.state.storage
        model: EmbeddingModel = request.app.state.model

        # --- Step 2: semantic dedup (sqlite_qdrant only) ---
        if request.app.state.backend_name == "sqlite_qdrant":
            from lore.server.storage.sqlite_qdrant import SqliteQdrantBackend

            sq_storage: SqliteQdrantBackend = storage
            candidate_vector: list[float] = model.embed(
                embedding_text(body.when_to_use, body.name)
            )
            dup = sq_storage.find_near_duplicate(candidate_vector)
            if dup is not None:
                dup_id, dup_score = dup
                return JSONResponse(
                    status_code=409,
                    content={
                        "error": "semantic_duplicate",
                        "existing_concept_id": dup_id,
                        "similarity": round(dup_score, 4),
                    },
                )
        else:
            candidate_vector = model.embed(
                embedding_text(body.when_to_use, body.name)
            )

        # --- Step 3: insert concept ---
        payload = {
            "name": body.name,
            "type": body.type,
            "content": body.content,
            "language": body.language,
            "when_to_use": body.when_to_use,
            "dont_use_when": body.dont_use_when,
            "tags": body.tags,
            "source_url": body.source_url,
            "author": body.author,
        }

        try:
            result = storage.upsert_concept(payload)
        except Exception as exc:  # noqa: BLE001
            logger.error("Backend indexing failed: %s", exc)
            return JSONResponse(
                status_code=503,
                content={"error": "Backend unavailable — concept not saved"},
            )

        if result.pop("_qdrant_failed", False):
            return JSONResponse(
                status_code=503,
                content={
                    "error": "Qdrant unavailable — concept saved but not indexed",
                    "concept_id": result["concept_id"],
                },
            )

        concept_id = result["concept_id"]

        # --- Step 4: inline links (sqlite_qdrant only) ---
        if request.app.state.backend_name == "sqlite_qdrant":
            from lore.server.storage.sqlite_qdrant import SqliteQdrantBackend

            sq_storage = storage  # type: ignore[assignment]
            for link_in in body.links:
                if link_in.rel not in VALID_LINK_RELS:
                    logger.warning(
                        "Skipping link with invalid rel '%s' for concept %s",
                        link_in.rel,
                        concept_id,
                    )
                    continue
                try:
                    sq_storage.insert_link(  # type: ignore[attr-defined]
                        from_id=concept_id,
                        to_id=link_in.to_id,
                        rel=link_in.rel,
                        label=link_in.label,
                    )
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
            concept_id: UUID string of the concept.
            request: FastAPI request.

        Returns:
            HTTP 200 with full concept fields plus a ``links`` array.
            HTTP 404 if the concept does not exist.
        """
        storage: StorageBackend = request.app.state.storage
        result = storage.get_concept(concept_id)
        if result is None:
            return JSONResponse(
                status_code=404,
                content={"error": "not found", "concept_id": concept_id},
            )
        return result

    @app.post("/v1/concepts/search")
    async def search_concepts_endpoint(body: SearchRequest, request: Request):
        """Search for concepts semantically similar to a problem description.

        Args:
            body: Validated :class:`SearchRequest`.
            request: FastAPI request.

        Returns:
            HTTP 200 ``{"results": [...]}`` with links attached per result.
        """
        storage: StorageBackend = request.app.state.storage
        model: EmbeddingModel = request.app.state.model

        query_vector = model.embed(body.problem)
        results = storage.search_concepts(
            query_vector=query_vector,
            limit=body.limit,
            type_filter=body.type,
            language_filter=body.language,
            min_rating=body.min_rating,
        )

        # Log session usage for sqlite_qdrant backend when session header present.
        x_session_id = request.headers.get("x-session-id")
        if x_session_id and request.app.state.backend_name == "sqlite_qdrant":
            sq_storage = storage  # type: ignore[assignment]
            for entry in results:
                sq_storage.log_session_usage(  # type: ignore[attr-defined]
                    x_session_id, entry["concept_id"]
                )

        return {"results": results}

    @app.post("/v1/links", status_code=201)
    async def link_concepts_endpoint(body: LinkRequest, request: Request):
        """Create a directed link between two existing concepts.

        Only available for the ``sqlite_qdrant`` backend.

        Args:
            body: Validated :class:`LinkRequest`.
            request: FastAPI request.

        Returns:
            HTTP 201 ``{"link_id": "..."}``.
            HTTP 404 if either concept is missing.
        """
        storage: StorageBackend = request.app.state.storage

        # Verify both concepts exist before inserting the link.
        from_concept = storage.get_concept(body.from_id)
        if from_concept is None:
            return JSONResponse(
                status_code=404,
                content={"error": "not found", "concept_id": body.from_id},
            )

        to_concept = storage.get_concept(body.to_id)
        if to_concept is None:
            return JSONResponse(
                status_code=404,
                content={"error": "not found", "concept_id": body.to_id},
            )

        if request.app.state.backend_name == "sqlite_qdrant":
            from lore.server.storage.sqlite_qdrant import SqliteQdrantBackend

            sq_storage: SqliteQdrantBackend = storage  # type: ignore[assignment]
            link_id = sq_storage.insert_link(
                from_id=body.from_id,
                to_id=body.to_id,
                rel=body.rel,
                label=body.label,
            )
            return JSONResponse(status_code=201, content={"link_id": link_id})

        # gist_qdrant — no link storage, return a synthetic link_id
        return JSONResponse(
            status_code=201,
            content={"link_id": str(uuid.uuid4())},
        )

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
        storage: StorageBackend = request.app.state.storage

        # Verify the concept exists first.
        concept = storage.get_concept(concept_id)
        if concept is None:
            return JSONResponse(
                status_code=404,
                content={"error": "not found", "concept_id": concept_id},
            )

        result = storage.rate_concept(
            concept_id=concept_id,
            outcome=body.outcome,
            session_id=body.session_id,
            hours_saved=body.hours_saved,
            notes=body.notes,
        )
        return result


# ---------------------------------------------------------------------------
# Route registration — bare /concepts and /search (gist_qdrant only)
# ---------------------------------------------------------------------------


def _register_gist_routes(app: FastAPI) -> None:
    """Register Backend 3 bare routes used by BackendRouter._semantic_search.

    When ``LORE_STORAGE_BACKEND=sqlite_qdrant`` these routes return 404.
    When ``LORE_STORAGE_BACKEND=gist_qdrant`` they behave exactly as the
    original ``lore.semantic_server.api`` did.

    Args:
        app: The :class:`~fastapi.FastAPI` instance to register routes on.
    """

    @app.get("/health")
    async def gist_health(request: Request):
        """Return service health for the gist_qdrant backend.

        Returns:
            ``{"status": "ok"}`` when backend is healthy, HTTP 404 otherwise.
        """
        if request.app.state.backend_name != "gist_qdrant":
            return JSONResponse(
                status_code=404,
                content={"error": "route not active for this backend"},
            )
        return {"status": "ok"}

    @app.post("/concepts", status_code=200)
    async def gist_upsert_concept(body: ConceptUpsertRequest, request: Request):
        """Upsert a concept into the gist_qdrant backend (gist_qdrant only).

        Args:
            body: Validated :class:`ConceptUpsertRequest`.
            request: FastAPI request.

        Returns:
            ``{"status": "skipped"|"upserted", "gist_id": str}``
            HTTP 404 for the ``sqlite_qdrant`` backend.
        """
        if request.app.state.backend_name != "gist_qdrant":
            return JSONResponse(
                status_code=404,
                content={"error": "route not active for this backend"},
            )

        storage: StorageBackend = request.app.state.storage
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
        }
        return storage.upsert_concept(payload)

    @app.get("/search")
    async def gist_search(
        request: Request,
        q: str = Query(..., description="Natural-language search query."),
        k: int = Query(3, ge=1, le=50, description="Maximum number of results."),
    ):
        """Search for concepts semantically (gist_qdrant only).

        Args:
            request: FastAPI request.
            q: Natural-language query string.
            k: Maximum number of results (1–50).

        Returns:
            ``{"results": [...]}`` — HTTP 404 for the ``sqlite_qdrant`` backend.
        """
        if request.app.state.backend_name != "gist_qdrant":
            return JSONResponse(
                status_code=404,
                content={"error": "route not active for this backend"},
            )

        storage: StorageBackend = request.app.state.storage
        model: EmbeddingModel = request.app.state.model

        query_vector = model.embed(q)
        results = storage.search_concepts(
            query_vector=query_vector,
            limit=k,
            type_filter=None,
            language_filter=None,
            min_rating=0.0,
        )
        return {"results": results}


# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------

app = create_app()
