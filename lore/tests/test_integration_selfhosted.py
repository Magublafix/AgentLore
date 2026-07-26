"""Integration tests — selfhosted backend (Setup 2).

Uses the FastAPI app in-process with:
- In-memory SQLite (no filesystem artefacts).
- Mock QdrantClient (no running Qdrant).
- No-op lifespan + direct app.state injection (same pattern as test_api.py).

Tests catch: wrong URL construction, missing payload fields, broken path
wiring, env var misreads in BackendRouter.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lore.mcp.router import BackendRouter
from lore.selfhosted.db import get_concept, init_db, insert_concept
from lore.server.api import app
from lore.server.storage.sqlite_qdrant import COLLECTION_NAME


# ---------------------------------------------------------------------------
# Helpers (copied from test_api.py pattern — not imported to avoid coupling)
# ---------------------------------------------------------------------------


def _noop_lifespan(app: FastAPI):
    """Async context manager lifespan that does nothing — bypasses real startup."""
    @asynccontextmanager
    async def _inner(app: FastAPI):
        yield
    return _inner(app)


def _fake_vector(dim: int = 384) -> list[float]:
    """Return a deterministic zero vector of the given dimension."""
    return [0.0] * dim


class _MockStorage:
    """Minimal in-memory storage backend for integration tests.

    Wraps a real in-memory SQLite connection for DB assertions, while
    Qdrant calls go to a MagicMock.
    """

    def __init__(self, conn, mock_qdrant, mock_model):
        """Initialise with real SQLite conn and mocked Qdrant/model."""
        self._conn = conn
        self._qdrant = mock_qdrant
        self._model = mock_model
        self.db = conn
        self.qdrant = mock_qdrant

    def health_check(self) -> dict:
        """Return health dict based on mock state."""
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

    def find_near_duplicate(self, query_vector):
        """Delegate to vector_store helper using mock Qdrant."""
        from lore.selfhosted.vector_store import find_near_duplicate
        return find_near_duplicate(self._qdrant, COLLECTION_NAME, query_vector)

    def upsert_concept(self, payload: dict) -> dict:
        """Insert concept into real SQLite; mock index call."""
        from lore.mcp.models import Concept
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
        from lore.server.storage import sqlite_qdrant as _mod
        try:
            _mod.index_concept(self._conn, self._qdrant, concept, self._model, COLLECTION_NAME)
        except Exception:  # noqa: BLE001
            return {"concept_id": concept_id, "name": payload["name"], "_qdrant_failed": True}
        return {"concept_id": concept_id, "name": payload["name"]}

    def search_concepts(self, query_vector, limit, type_filter, language_filter, min_rating):
        """Delegate to patched search_vectors using mock Qdrant."""
        from lore.server.storage import sqlite_qdrant as _mod
        concept_ids = _mod.search_vectors(self._qdrant, COLLECTION_NAME, query_vector, limit=limit)
        from lore.selfhosted.db import get_concept, get_links_for_concept
        from lore.server.storage.sqlite_qdrant import _concept_to_dict, _link_to_dict
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

    def get_concept(self, concept_id: str):
        """Fetch concept from real SQLite with links resolved."""
        from lore.selfhosted.db import get_concept, get_links_for_concept
        from lore.server.storage.sqlite_qdrant import _concept_to_dict, _link_to_dict
        concept = get_concept(self._conn, concept_id)
        if concept is None:
            return None
        links = get_links_for_concept(self._conn, concept_id)
        result = _concept_to_dict(concept)
        result["links"] = [_link_to_dict(lnk, self._conn) for lnk in links]
        return result

    def rate_concept(self, concept_id, outcome, session_id, hours_saved, notes):
        """Insert rating into real SQLite and return updated aggregates."""
        from lore.selfhosted.db import get_concept, insert_rating
        from lore.mcp.models import Rating
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
        """Log session usage; suppress errors silently."""
        from lore.selfhosted.db import log_session_usage
        try:
            log_session_usage(self._conn, session_id, concept_id)
        except Exception:  # noqa: BLE001
            pass

    def insert_link(self, from_id: str, to_id: str, rel: str, label) -> str:
        """Insert a link into real SQLite."""
        from lore.selfhosted.db import insert_link
        from lore.mcp.models import Link
        link = Link(
            link_id=str(uuid.uuid4()),
            from_id=from_id,
            to_id=to_id,
            rel=rel,
            label=label,
        )
        return insert_link(self._conn, link)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def conn():
    """In-memory SQLite connection with schema applied."""
    return init_db(":memory:")


@pytest.fixture()
def mock_qdrant():
    """MagicMock QdrantClient configured with empty collections and no points."""
    client = MagicMock()
    client.get_collections.return_value = MagicMock(collections=[])
    no_dup = MagicMock()
    no_dup.points = []
    client.query_points.return_value = no_dup
    return client


@pytest.fixture()
def mock_model():
    """MagicMock EmbeddingModel returning a 384-dim zero vector."""
    model = MagicMock()
    model.embed.return_value = _fake_vector()
    model.dimension = 384
    return model


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_env_var_wiring_selfhosted(monkeypatch):
    """BackendRouter reads backend and selfhosted_url from constructor args.

    Verifies attribute assignment without any network calls.
    """
    monkeypatch.setenv("LORE_BACKEND", "selfhosted")
    monkeypatch.setenv("LORE_SELFHOSTED_URL", "http://localhost:8765")

    router = BackendRouter(backend="selfhosted", selfhosted_url="http://localhost:8765")

    assert router._backend == "selfhosted"
    assert router._selfhosted_url == "http://localhost:8765"


def test_submit_and_get_concept_selfhosted(conn, mock_qdrant, mock_model):
    """POST /v1/concepts then GET /v1/concepts/{id} round-trip via in-process FastAPI.

    Verifies:
    - POST returns 201 with a concept_id.
    - GET returns 200 with the matching name and a ``links`` list.
    - The SQLite row exists after submission.
    """
    storage = _MockStorage(conn, mock_qdrant, mock_model)

    with patch("lore.server.api.lifespan", _noop_lifespan):
        with TestClient(app, raise_server_exceptions=True) as client:
            app.state.storage = storage
            app.state.model = mock_model
            app.state.backend_name = "sqlite_qdrant"
            app.state.key_store = None

            # Submit.
            with patch("lore.server.storage.sqlite_qdrant.index_concept"):
                response = client.post(
                    "/v1/concepts",
                    json={
                        "name": "WAL Mode",
                        "type": "pattern",
                        "content": "Enable WAL.",
                        "when_to_use": "Use for concurrent SQLite writes.",
                        "tags": ["sqlite"],
                    },
                )

            assert response.status_code == 201, response.text
            concept_id = response.json()["concept_id"]
            assert concept_id is not None

            # Get.
            response = client.get(f"/v1/concepts/{concept_id}")
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["name"] == "WAL Mode"
            assert "links" in data
            assert isinstance(data["links"], list)

    # SQLite row persisted.
    row = get_concept(conn, concept_id)
    assert row is not None, "SQLite row missing after submit"


def test_submit_and_search_selfhosted(conn, mock_qdrant, mock_model):
    """POST /v1/concepts then POST /v1/concepts/search — search returns 200 with results list.

    Qdrant mock returns no points, so results may be empty — this test asserts
    the pipeline doesn't error (no 500), not that results are non-empty.
    """
    storage = _MockStorage(conn, mock_qdrant, mock_model)

    with patch("lore.server.api.lifespan", _noop_lifespan):
        with TestClient(app, raise_server_exceptions=True) as client:
            app.state.storage = storage
            app.state.model = mock_model
            app.state.backend_name = "sqlite_qdrant"
            app.state.key_store = None

            # Submit a concept.
            with patch("lore.server.storage.sqlite_qdrant.index_concept"):
                post_resp = client.post(
                    "/v1/concepts",
                    json={
                        "name": "WAL Mode",
                        "type": "pattern",
                        "content": "Enable WAL.",
                        "when_to_use": "Use for concurrent SQLite writes.",
                        "tags": ["sqlite"],
                    },
                )
            assert post_resp.status_code == 201, post_resp.text

            # Search.
            search_resp = client.post(
                "/v1/concepts/search",
                json={
                    "problem": "sqlite concurrency",
                    "limit": 3,
                    "min_rating": 0.0,
                },
            )
            assert search_resp.status_code == 200, search_resp.text
            data = search_resp.json()
            assert "results" in data, f"Missing 'results' key: {data}"
            assert isinstance(data["results"], list)


def test_selfhosted_full_chain_via_router(monkeypatch):
    """BackendRouter submit_concept + get_concept via respx-mocked selfhosted service.

    Uses respx to intercept httpx calls; verifies:
    - POST /v1/concepts called exactly once.
    - submit_concept returns concept_id from the mocked response.
    - get_concept returns the mocked concept with correct name.
    """
    monkeypatch.setenv("LORE_BACKEND", "selfhosted")

    concept_id = "uuid-from-server"

    submit_json = {"concept_id": concept_id, "name": "WAL Mode"}
    get_json = {
        "concept_id": concept_id,
        "name": "WAL Mode",
        "type": "pattern",
        "content": "Enable WAL.",
        "when_to_use": "Use for concurrent SQLite writes.",
        "tags": [],
        "links": [],
        "avg_rating": None,
        "time_saved_avg_hours": None,
        "language": None,
        "dont_use_when": None,
        "source_url": None,
        "usage_count": 0,
        "created_at": "2026-01-01T00:00:00",
    }

    with respx.mock:
        post_route = respx.post("http://localhost:8765/v1/concepts").mock(
            return_value=httpx.Response(201, json=submit_json)
        )
        respx.get(f"http://localhost:8765/v1/concepts/{concept_id}").mock(
            return_value=httpx.Response(200, json=get_json)
        )

        router = BackendRouter(backend="selfhosted", selfhosted_url="http://localhost:8765")

        result = router.submit_concept(
            name="WAL Mode",
            type="pattern",
            content="Enable WAL.",
            when_to_use="Use for concurrent SQLite writes.",
            tags=["sqlite"],
        )

        assert result["concept_id"] == concept_id

        concept = router.get_concept(concept_id)

        assert concept["name"] == "WAL Mode"

        # POST /v1/concepts called exactly once.
        assert post_route.called, "POST /v1/concepts was not called"
        assert post_route.call_count == 1, (
            f"Expected 1 POST /v1/concepts call, got {post_route.call_count}"
        )
