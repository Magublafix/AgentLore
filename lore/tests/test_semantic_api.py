"""Tests for the unified Lore API with gist_qdrant backend and BackendRouter
semantic routing (LORE-030).

Strategy
--------
- All Qdrant interactions are mocked via ``unittest.mock.MagicMock`` — no real
  Qdrant instance is required.
- ``EmbeddingModel`` is always mocked — no sentence-transformers model is loaded.
- The FastAPI lifespan is patched to a no-op and ``app.state`` is injected
  after startup via the ``TestClient`` context.
- BackendRouter semantic call tests use ``httpx.MockTransport`` so no real
  network calls are made.
- Tests are fully offline and fast.

Test areas
----------
POST /concepts
    - New concept: embeds and upserts.
    - Idempotency: same gist_updated_at → skipped, no re-embed.
    - Update: different gist_updated_at → re-embeds and upserts.

GET /search
    - Returns results in correct ``{"results": [...]}`` shape.
    - Results include ``score``, ``links: []``, and correct field mapping.
    - Empty collection → ``{"results": []}`` without error.

GET /health
    - Returns ``{"status": "ok"}``.

BackendRouter
    - When ``LORE_SEMANTIC_URL`` set and server responds → calls semantic search.
    - When ``LORE_SEMANTIC_URL`` set and server down → falls back to gists backend.
    - When ``LORE_SEMANTIC_URL`` not set → calls gists backend directly.
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lore.server.api import app
from lore.server.storage.gist_qdrant import COLLECTION_NAME


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_vector(dim: int = 384) -> list[float]:
    """Return a deterministic fake embedding vector."""
    return [0.001 * i for i in range(dim)]


def _noop_lifespan(application: FastAPI):
    """Async context manager lifespan that does nothing — bypasses real startup."""
    @asynccontextmanager
    async def _inner(application: FastAPI):
        yield
    return _inner(application)


def _make_mock_qdrant(
    retrieve_returns: list | None = None,
    query_points_returns=None,
) -> MagicMock:
    """Return a MagicMock QdrantClient.

    Args:
        retrieve_returns: Value returned by ``qdrant.retrieve()``.
            Defaults to ``[]`` (no existing points).
        query_points_returns: Value returned by ``qdrant.query_points()``.
            Defaults to a mock with empty ``.points``.
    """
    mock = MagicMock()
    mock.retrieve.return_value = retrieve_returns if retrieve_returns is not None else []
    if query_points_returns is None:
        qp = MagicMock()
        qp.points = []
        mock.query_points.return_value = qp
    else:
        mock.query_points.return_value = query_points_returns
    return mock


def _make_mock_model(vector: list[float] | None = None) -> MagicMock:
    """Return a MagicMock EmbeddingModel."""
    mock = MagicMock()
    mock.embed.return_value = vector or _fake_vector()
    return mock


class _MockGistStorage:
    """Thin mock that delegates to the mock QdrantClient and model.

    Mirrors GistQdrantBackend's interface so the unified server's gist_qdrant
    routes work correctly in tests without importing qdrant_client models.
    """

    def __init__(self, mock_qdrant, mock_model):
        self._qdrant = mock_qdrant
        self._model = mock_model
        # Direct attribute access from the /concepts route
        self.qdrant = mock_qdrant
        self.model = mock_model

    def health_check(self) -> dict:
        return {"status": "ok"}

    def upsert_concept(self, payload: dict) -> dict:
        from lore.server.storage.gist_qdrant import _gist_id_to_point_id
        gist_id = payload["gist_id"]
        point_id = _gist_id_to_point_id(gist_id)

        existing = self._qdrant.retrieve(
            collection_name=COLLECTION_NAME,
            ids=[point_id],
            with_payload=True,
        )
        if existing:
            stored_updated_at = existing[0].payload.get("gist_updated_at")
            if stored_updated_at == payload.get("gist_updated_at"):
                return {"status": "skipped", "gist_id": gist_id}

        embed_text = payload["when_to_use"] + " " + payload["name"]
        vector = self._model.embed(embed_text)

        from qdrant_client.http import models as qmodels
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
            "avg_outcome": 0.0,
            "avg_hours_saved": None,
            "rating_count": 0,
            "usage_count": 0,
        }
        self._qdrant.upsert(
            collection_name=COLLECTION_NAME,
            points=[qmodels.PointStruct(id=point_id, vector=vector, payload=qdrant_payload)],
        )
        return {"status": "upserted", "gist_id": gist_id}

    def search_concepts(self, query_vector, limit, type_filter, language_filter, min_rating):
        from lore.server.storage.gist_qdrant import _payload_to_result
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
            _payload_to_result(hit.payload, hit.score)
            for hit in hits
            if hit.payload
        ]

    def get_concept(self, concept_id: str):
        from lore.server.storage.gist_qdrant import _gist_id_to_point_id, _payload_to_result
        point_id = _gist_id_to_point_id(concept_id)
        results = self._qdrant.retrieve(
            collection_name=COLLECTION_NAME,
            ids=[point_id],
            with_payload=True,
        )
        if not results or not results[0].payload:
            return None
        return _payload_to_result(results[0].payload, 1.0)

    def search_similar(
        self,
        vector: list,
        top_k: int = 3,
        exclude_id: str | None = None,
    ) -> list:
        """Return no duplicates by default — dedup is not under test here."""
        return []

    def rate_concept(self, concept_id, outcome, session_id, hours_saved, notes):
        raise NotImplementedError("rate_concept not implemented for gist_qdrant")


def _make_test_client(mock_qdrant=None, mock_model=None) -> TestClient:
    """Return a TestClient with patched lifespan and injected app.state."""
    if mock_qdrant is None:
        mock_qdrant = _make_mock_qdrant()
    if mock_model is None:
        mock_model = _make_mock_model()

    storage = _MockGistStorage(mock_qdrant, mock_model)
    with patch("lore.server.api.lifespan", _noop_lifespan):
        client = TestClient(app, raise_server_exceptions=True)

    # Inject state — the noop lifespan leaves app.state unpopulated.
    app.state.storage = storage
    app.state.model = mock_model
    app.state.backend_name = "gist_qdrant"
    # Disable auth for these tests (no key_store → _require_api_key is a no-op).
    app.state.key_store = None
    return client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_qdrant():
    """Return a fresh mock QdrantClient."""
    return _make_mock_qdrant()


@pytest.fixture()
def mock_model():
    """Return a fresh mock EmbeddingModel."""
    return _make_mock_model()


@pytest.fixture()
def client(mock_qdrant, mock_model):
    """Return a TestClient with mocked Qdrant and EmbeddingModel."""
    storage = _MockGistStorage(mock_qdrant, mock_model)
    with patch("lore.server.api.lifespan", _noop_lifespan):
        tc = TestClient(app, raise_server_exceptions=True)
    app.state.storage = storage
    app.state.model = mock_model
    app.state.backend_name = "gist_qdrant"
    # Disable auth for these tests (no key_store → _require_api_key is a no-op).
    app.state.key_store = None
    return tc


def _concept_body(**overrides) -> dict:
    """Return a minimal valid POST /concepts request body."""
    base = {
        "gist_id": "abc123",
        "name": "SQLite WAL mode",
        "type": "pattern",
        "language": "python",
        "author": "user1",
        "tags": ["sqlite", "concurrency"],
        "when_to_use": "Use for crash-safe concurrent SQLite writes.",
        "dont_use_when": "Not needed for read-only workloads.",
        "gist_updated_at": "2026-07-11T00:00:00Z",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


class TestHealth:
    """Tests for GET /health."""

    def test_health_returns_ok(self, client):
        """GET /health returns HTTP 200 with {status: ok}."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /concepts — new concept
# ---------------------------------------------------------------------------


class TestUpsertConceptNew:
    """POST /concepts with a gist_id that does not yet exist in Qdrant."""

    def test_new_concept_returns_upserted(self, client, mock_qdrant, mock_model):
        """A brand-new concept returns status=upserted."""
        # retrieve() returns [] (no existing point)
        mock_qdrant.retrieve.return_value = []

        response = client.post("/concepts", json=_concept_body())
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "upserted"
        assert data["gist_id"] == "abc123"

    def test_new_concept_calls_embed(self, client, mock_qdrant, mock_model):
        """A new concept causes EmbeddingModel.embed() to be called (dedup + upsert)."""
        mock_qdrant.retrieve.return_value = []

        client.post("/concepts", json=_concept_body())

        # embed is called at least once: once for the dedup check and once inside
        # upsert_concept for the actual upsert embedding.
        assert mock_model.embed.called
        # All calls target the same content (name + when_to_use).
        for call in mock_model.embed.call_args_list:
            arg = call[0][0]
            assert "SQLite WAL mode" in arg
            assert "crash-safe" in arg

    def test_new_concept_calls_qdrant_upsert(self, client, mock_qdrant, mock_model):
        """A new concept calls qdrant.upsert() once."""
        mock_qdrant.retrieve.return_value = []

        client.post("/concepts", json=_concept_body())

        mock_qdrant.upsert.assert_called_once()

    def test_new_concept_payload_includes_all_fields(self, client, mock_qdrant, mock_model):
        """Qdrant upsert payload contains all required denormalized fields."""
        mock_qdrant.retrieve.return_value = []

        client.post("/concepts", json=_concept_body())

        upsert_call = mock_qdrant.upsert.call_args
        points = upsert_call[1]["points"]
        assert len(points) == 1
        payload = points[0].payload
        assert payload["gist_id"] == "abc123"
        assert payload["name"] == "SQLite WAL mode"
        assert payload["type"] == "pattern"
        assert payload["language"] == "python"
        assert payload["author"] == "user1"
        assert payload["tags"] == ["sqlite", "concurrency"]
        assert "when_to_use" in payload
        assert payload["gist_updated_at"] == "2026-07-11T00:00:00Z"
        assert payload["avg_outcome"] == 0.0
        assert payload["avg_hours_saved"] is None
        assert payload["rating_count"] == 0
        assert payload["usage_count"] == 0

    def test_new_concept_uses_deterministic_point_id(self, client, mock_qdrant, mock_model):
        """Point ID is deterministic: uuid5(NAMESPACE_URL, gist_id)."""
        mock_qdrant.retrieve.return_value = []

        client.post("/concepts", json=_concept_body(gist_id="gist-xyz"))

        upsert_call = mock_qdrant.upsert.call_args
        points = upsert_call[1]["points"]
        expected_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "gist-xyz"))
        assert str(points[0].id) == expected_id


# ---------------------------------------------------------------------------
# POST /concepts — idempotency (same gist_updated_at)
# ---------------------------------------------------------------------------


class TestUpsertConceptIdempotent:
    """POST /concepts with a gist_id that already exists and has the same timestamp."""

    def _make_existing_point(self, gist_updated_at: str = "2026-07-11T00:00:00Z"):
        """Return a mock existing Qdrant point with the given timestamp."""
        point = MagicMock()
        point.payload = {
            "gist_id": "abc123",
            "gist_updated_at": gist_updated_at,
        }
        return point

    def test_same_timestamp_returns_skipped(self, client, mock_qdrant, mock_model):
        """Same gist_updated_at returns status=skipped."""
        mock_qdrant.retrieve.return_value = [self._make_existing_point()]

        response = client.post("/concepts", json=_concept_body())
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "skipped"
        assert data["gist_id"] == "abc123"

    def test_same_timestamp_does_not_embed(self, client, mock_qdrant, mock_model):
        """Same gist_updated_at skips the upsert embed, but dedup check still embeds.

        The dedup check in the endpoint always calls embed() once to build the
        query vector.  The _MockGistStorage.upsert_concept returns early on a
        timestamp match, so embed() is called exactly once total (dedup only).
        """
        mock_qdrant.retrieve.return_value = [self._make_existing_point()]

        client.post("/concepts", json=_concept_body())

        # embed is called once for the dedup check; upsert_concept returns early
        # without embedding again.
        mock_model.embed.assert_called_once()

    def test_same_timestamp_does_not_upsert(self, client, mock_qdrant, mock_model):
        """Same gist_updated_at must NOT call qdrant.upsert()."""
        mock_qdrant.retrieve.return_value = [self._make_existing_point()]

        client.post("/concepts", json=_concept_body())

        mock_qdrant.upsert.assert_not_called()


# ---------------------------------------------------------------------------
# POST /concepts — update (different gist_updated_at)
# ---------------------------------------------------------------------------


class TestUpsertConceptUpdate:
    """POST /concepts when the point exists but gist_updated_at has changed."""

    def _make_existing_point(self, gist_updated_at: str):
        point = MagicMock()
        point.payload = {
            "gist_id": "abc123",
            "gist_updated_at": gist_updated_at,
        }
        return point

    def test_different_timestamp_returns_upserted(self, client, mock_qdrant, mock_model):
        """Different gist_updated_at triggers re-embed and returns status=upserted."""
        # Stored timestamp differs from the request
        mock_qdrant.retrieve.return_value = [self._make_existing_point("2026-01-01T00:00:00Z")]

        response = client.post("/concepts", json=_concept_body(gist_updated_at="2026-07-11T00:00:00Z"))
        assert response.status_code == 200
        assert response.json()["status"] == "upserted"

    def test_different_timestamp_calls_embed(self, client, mock_qdrant, mock_model):
        """Different gist_updated_at calls EmbeddingModel.embed() (dedup + upsert)."""
        mock_qdrant.retrieve.return_value = [self._make_existing_point("2026-01-01T00:00:00Z")]

        client.post("/concepts", json=_concept_body(gist_updated_at="2026-07-11T00:00:00Z"))

        # embed is called at least once: once for dedup check and once for upsert.
        assert mock_model.embed.called

    def test_different_timestamp_calls_upsert(self, client, mock_qdrant, mock_model):
        """Different gist_updated_at calls qdrant.upsert() once."""
        mock_qdrant.retrieve.return_value = [self._make_existing_point("2026-01-01T00:00:00Z")]

        client.post("/concepts", json=_concept_body(gist_updated_at="2026-07-11T00:00:00Z"))

        mock_qdrant.upsert.assert_called_once()


# ---------------------------------------------------------------------------
# GET /search
# ---------------------------------------------------------------------------


class TestSearch:
    """Tests for GET /search."""

    def _make_hit(self, gist_id: str = "abc123", score: float = 0.92) -> MagicMock:
        """Return a mock Qdrant search hit."""
        hit = MagicMock()
        hit.score = score
        hit.payload = {
            "gist_id": gist_id,
            "name": "SQLite WAL mode",
            "type": "pattern",
            "language": "python",
            "author": "user1",
            "tags": ["sqlite"],
            "when_to_use": "Use for concurrent writes.",
            "dont_use_when": None,
            "avg_outcome": 0.0,
            "avg_hours_saved": None,
            "usage_count": 0,
        }
        return hit

    def _make_query_points_result(self, hits: list) -> MagicMock:
        """Return a mock query_points response."""
        result = MagicMock()
        result.points = hits
        return result

    def test_search_returns_results_key(self, client, mock_qdrant, mock_model):
        """GET /search returns a dict with a 'results' key."""
        hit = self._make_hit()
        mock_qdrant.query_points.return_value = self._make_query_points_result([hit])

        response = client.get("/search", params={"q": "sqlite concurrency"})
        assert response.status_code == 200
        data = response.json()
        assert "results" in data

    def test_search_result_has_correct_shape(self, client, mock_qdrant, mock_model):
        """Each result has the canonical concept dict shape."""
        hit = self._make_hit(gist_id="gist-abc", score=0.95)
        mock_qdrant.query_points.return_value = self._make_query_points_result([hit])

        response = client.get("/search", params={"q": "sqlite"})
        data = response.json()

        assert len(data["results"]) == 1
        result = data["results"][0]

        # concept_id must be gist_id
        assert result["concept_id"] == "gist-abc"
        assert result["name"] == "SQLite WAL mode"
        assert result["type"] == "pattern"
        assert result["language"] == "python"
        assert result["author"] == "user1"
        assert result["tags"] == ["sqlite"]
        assert "when_to_use" in result
        assert result["avg_rating"] == 0.0
        assert result["usage_count"] == 0
        assert result["time_saved_avg_hours"] is None
        # links is always empty for Backend 3
        assert result["links"] == []
        # score is the cosine similarity
        assert abs(result["score"] - 0.95) < 1e-4

    def test_search_uses_k_parameter(self, client, mock_qdrant, mock_model):
        """GET /search passes k to qdrant.query_points as limit."""
        mock_qdrant.query_points.return_value = self._make_query_points_result([])

        client.get("/search", params={"q": "test", "k": 7})

        call_kwargs = mock_qdrant.query_points.call_args[1]
        assert call_kwargs["limit"] == 7

    def test_search_embeds_query(self, client, mock_qdrant, mock_model):
        """GET /search calls EmbeddingModel.embed() with the query string."""
        mock_qdrant.query_points.return_value = self._make_query_points_result([])

        client.get("/search", params={"q": "find me patterns"})

        mock_model.embed.assert_called_once_with("find me patterns")

    def test_search_empty_collection_returns_empty_results(self, client, mock_qdrant, mock_model):
        """GET /search returns empty results list without error."""
        mock_qdrant.query_points.return_value = self._make_query_points_result([])

        response = client.get("/search", params={"q": "anything"})
        assert response.status_code == 200
        assert response.json() == {"results": []}

    def test_search_collection_not_found_returns_empty_results(self, client, mock_qdrant, mock_model):
        """GET /search returns empty results when collection does not exist."""
        mock_qdrant.query_points.side_effect = Exception("Collection doesn't exist")

        response = client.get("/search", params={"q": "anything"})
        assert response.status_code == 200
        assert response.json() == {"results": []}

    def test_search_requires_q_parameter(self, client, mock_qdrant, mock_model):
        """GET /search returns 422 when q parameter is missing."""
        response = client.get("/search")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# BackendRouter — semantic routing
# ---------------------------------------------------------------------------


class TestBackendRouterSemanticRouting:
    """BackendRouter delegates to semantic server when LORE_SEMANTIC_URL is set."""

    def _make_router(self, semantic_url: str | None = None):
        """Return a BackendRouter with the given semantic URL."""
        from lore.mcp.router import BackendRouter
        with patch.dict("os.environ", {"LORE_SEMANTIC_URL": semantic_url or ""}, clear=False):
            if semantic_url:
                import os
                os.environ["LORE_SEMANTIC_URL"] = semantic_url
            else:
                import os
                os.environ.pop("LORE_SEMANTIC_URL", None)
            router = BackendRouter(backend="gists", selfhosted_url="http://localhost:8765")
            router._semantic_url = semantic_url  # set directly for test isolation
        return router

    def test_semantic_url_set_calls_semantic_search(self):
        """When LORE_SEMANTIC_URL is set and server responds, result is from semantic server."""
        from lore.mcp.router import BackendRouter

        expected = {"results": [{"concept_id": "gist-abc", "name": "WAL"}]}

        # Build a mock httpx transport that returns the expected payload.
        def _mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=expected)

        router = BackendRouter(backend="gists", selfhosted_url="http://localhost:8765")
        router._semantic_url = "http://localhost:8766"

        with patch.object(
            router,
            "_semantic_search",
            return_value=expected,
        ) as mock_sem:
            result = router.search_concepts(problem="test problem")

        mock_sem.assert_called_once()
        assert result is expected

    def test_semantic_url_not_set_calls_gists_backend(self):
        """When LORE_SEMANTIC_URL is not set, search_concepts delegates to gists backend."""
        from lore.mcp.router import BackendRouter

        expected = {"results": []}
        router = BackendRouter(backend="gists", selfhosted_url="http://localhost:8765")
        router._semantic_url = None  # explicitly no semantic URL

        with patch("lore.mcp.router.gists_backend.search_concepts", return_value=expected) as mock_gists, \
             patch("lore.mcp.router.GistsClient"):
            result = router.search_concepts(problem="test")

        mock_gists.assert_called_once()
        assert result is expected

    def test_semantic_server_down_falls_back_to_gists(self):
        """When semantic server is unreachable, falls back to gists backend."""
        from lore.mcp.router import BackendRouter

        gists_result = {"results": [{"concept_id": "gist-fallback"}]}
        router = BackendRouter(backend="gists", selfhosted_url="http://localhost:8765")
        router._semantic_url = "http://localhost:8766"

        def _semantic_fails(*args, **kwargs):
            raise httpx.ConnectError("Connection refused")

        with patch.object(router, "_semantic_search", side_effect=_semantic_fails), \
             patch("lore.mcp.router.gists_backend.search_concepts", return_value=gists_result) as mock_gists, \
             patch("lore.mcp.router.GistsClient"):
            result = router.search_concepts(problem="test")

        mock_gists.assert_called_once()
        assert result is gists_result

    def test_semantic_timeout_falls_back_to_gists(self):
        """When semantic server times out, falls back to gists backend."""
        from lore.mcp.router import BackendRouter

        gists_result = {"results": []}
        router = BackendRouter(backend="gists", selfhosted_url="http://localhost:8765")
        router._semantic_url = "http://localhost:8766"
        router._semantic_timeout = 0.001  # force instant timeout

        def _semantic_fails(*args, **kwargs):
            raise httpx.TimeoutException("timeout")

        with patch.object(router, "_semantic_search", side_effect=_semantic_fails), \
             patch("lore.mcp.router.gists_backend.search_concepts", return_value=gists_result) as mock_gists, \
             patch("lore.mcp.router.GistsClient"):
            result = router.search_concepts(problem="test")

        mock_gists.assert_called_once()

    def test_semantic_search_method_calls_correct_endpoint(self):
        """_semantic_search calls GET /search with q and k params."""
        from lore.mcp.router import BackendRouter

        captured_requests: list[httpx.Request] = []

        def _mock_handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            return httpx.Response(200, json={"results": []})

        router = BackendRouter(backend="gists", selfhosted_url="http://localhost:8765")
        router._semantic_url = "http://localhost:8766"

        with patch("lore.mcp.router.httpx.Client") as MockClient:
            mock_client_instance = MagicMock()
            mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
            mock_client_instance.__exit__ = MagicMock(return_value=False)
            mock_response = MagicMock()
            mock_response.json.return_value = {"results": []}
            mock_client_instance.get.return_value = mock_response
            MockClient.return_value = mock_client_instance

            router._semantic_search("my query", None, None, 5, 2.0)

        mock_client_instance.get.assert_called_once()
        call_args = mock_client_instance.get.call_args
        assert call_args[0][0] == "/search"
        params = call_args[1]["params"]
        assert params["q"] == "my query"
        assert params["k"] == 5


# ---------------------------------------------------------------------------
# POST /concepts — validation
# ---------------------------------------------------------------------------


class TestUpsertConceptValidation:
    """POST /concepts input validation tests."""

    def test_upsert_missing_required_field_returns_422(self, client):
        """POST /concepts with missing required fields returns HTTP 422."""
        response = client.post("/concepts", json={"gist_id": "abc"})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /search — error propagation
# ---------------------------------------------------------------------------


class TestSearchErrorPropagation:
    """GET /search unexpected error propagation tests."""

    @pytest.fixture()
    def client_no_raise(self, mock_qdrant, mock_model):
        """TestClient that returns 500 instead of raising on server exceptions."""
        storage = _MockGistStorage(mock_qdrant, mock_model)
        with patch("lore.server.api.lifespan", _noop_lifespan):
            tc = TestClient(app, raise_server_exceptions=False)
        app.state.storage = storage
        app.state.model = mock_model
        app.state.backend_name = "gist_qdrant"
        # Disable auth for these tests (no key_store → _require_api_key is a no-op).
        app.state.key_store = None
        return tc

    def test_search_unexpected_qdrant_error_returns_500(
        self, client_no_raise, mock_qdrant, mock_model
    ):
        """GET /search re-raises unexpected Qdrant errors as HTTP 500."""
        mock_qdrant.query_points.side_effect = Exception("internal qdrant failure")
        response = client_no_raise.get("/search", params={"q": "test"})
        assert response.status_code == 500
