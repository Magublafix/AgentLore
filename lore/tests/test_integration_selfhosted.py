"""Integration tests — selfhosted backend (Setup 2).

Uses the FastAPI app in-process with:
- Real SQLite (tmp_path file — SqliteQdrantBackend.__init__ calls mkdir on the parent).
- Real QdrantClient pointing at localhost:6333.
- Mock EmbeddingModel returning a 384-dim zero vector (keeps tests fast).
- No-op lifespan + direct app.state injection (same pattern as test_api.py).

Tests skip automatically when Qdrant is not reachable (local dev without Docker).
In CI, Qdrant runs as a service container on localhost:6333.
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
from lore.selfhosted.db import get_concept, init_db
from lore.server.api import app
from lore.server.storage.sqlite_qdrant import COLLECTION_NAME, SqliteQdrantBackend


# ---------------------------------------------------------------------------
# Qdrant availability check (runs once at module load)
# ---------------------------------------------------------------------------


def _qdrant_available() -> bool:
    """Return True if Qdrant is reachable at localhost:6333."""
    try:
        resp = httpx.get("http://localhost:6333/healthz", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


_QDRANT_UP = _qdrant_available()
_skip_if_no_qdrant = pytest.mark.skipif(
    not _QDRANT_UP, reason="Qdrant not running at localhost:6333"
)


# ---------------------------------------------------------------------------
# Helpers
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_model():
    """MagicMock EmbeddingModel returning a 384-dim zero vector."""
    model = MagicMock()
    model.embed.return_value = _fake_vector()
    model.dimension = 384
    return model


@pytest.fixture()
def real_storage(tmp_path, mock_model):
    """Real SqliteQdrantBackend with a real QdrantClient and a temp SQLite file.

    Deletes the 'concepts' Qdrant collection after the test to avoid
    cross-test contamination.
    """
    sqlite_path = str(tmp_path / "lore_test.db")
    storage = SqliteQdrantBackend(
        sqlite_path=sqlite_path,
        qdrant_host="localhost",
        qdrant_port=6333,
        model=mock_model,
    )
    yield storage
    # Teardown: delete the collection to avoid cross-test contamination.
    try:
        storage._qdrant.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    storage.close()


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


@_skip_if_no_qdrant
def test_submit_and_get_concept_selfhosted(real_storage, mock_model):
    """POST /v1/concepts then GET /v1/concepts/{id} round-trip via in-process FastAPI.

    Uses a real SqliteQdrantBackend with a real QdrantClient.

    Verifies:
    - POST returns 201 with a concept_id.
    - GET returns 200 with the matching name and a ``links`` list.
    - The SQLite row exists after submission (confirmed via direct DB query).
    """
    with patch("lore.server.api.lifespan", _noop_lifespan):
        with TestClient(app, raise_server_exceptions=True) as client:
            app.state.storage = real_storage
            app.state.model = mock_model
            app.state.backend_name = "sqlite_qdrant"
            app.state.key_store = None

            # Submit.
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

    # SQLite row persisted — query via the backend's DB connection.
    row = get_concept(real_storage.db, concept_id)
    assert row is not None, "SQLite row missing after submit"


@_skip_if_no_qdrant
def test_submit_and_search_selfhosted(real_storage, mock_model):
    """POST /v1/concepts then POST /v1/concepts/search — search returns 200 with results list.

    Uses real Qdrant. The mock model returns a zero vector for all embeds,
    so the submitted concept IS indexed in Qdrant and IS findable by search
    (both embed calls return the same vector, so similarity is 1.0 but dedup
    threshold is 0.88 — second submit would be blocked, but first is fine).

    This test asserts:
    - The pipeline doesn't error (no 500).
    - results is a list.
    - The submitted concept appears in the results (real Qdrant returns it).
    """
    with patch("lore.server.api.lifespan", _noop_lifespan):
        with TestClient(app, raise_server_exceptions=True) as client:
            app.state.storage = real_storage
            app.state.model = mock_model
            app.state.backend_name = "sqlite_qdrant"
            app.state.key_store = None

            # Submit a concept.
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

            # Search — real Qdrant, should return the concept we just submitted.
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
            # Real Qdrant — the submitted concept should appear.
            assert len(data["results"]) >= 1, (
                "Expected at least one search result from real Qdrant"
            )


def test_selfhosted_full_chain_via_router(monkeypatch):
    """BackendRouter submit_concept + get_concept via respx-mocked selfhosted service.

    Uses respx to intercept httpx calls; verifies:
    - POST /v1/concepts called exactly once.
    - submit_concept returns concept_id from the mocked response.
    - get_concept returns the mocked concept with correct name.

    This test does not need Qdrant — it tests the router HTTP layer only.
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
