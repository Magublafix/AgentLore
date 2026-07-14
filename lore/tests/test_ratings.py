"""Tests for LORE-033: server-side ratings aggregation.

Covers:
- GistQdrantBackend.add_rating() unit tests (mock QdrantClient)
- POST /ratings HTTP endpoint tests
- GET /search avg_outcome / avg_hours_saved field presence tests
- BackendRouter.rate_concept() semantic path tests
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, call, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lore.server.api import app
from lore.server.storage.gist_qdrant import (
    COLLECTION_NAME,
    GistQdrantBackend,
    _payload_to_result,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _noop_lifespan(application: FastAPI):
    """Async context manager lifespan that does nothing."""

    @asynccontextmanager
    async def _inner(application: FastAPI):
        yield

    return _inner(application)


def _make_mock_qdrant() -> MagicMock:
    """Return a MagicMock QdrantClient with safe defaults."""
    mock = MagicMock()
    mock.retrieve.return_value = []
    # get_collections() is called by _init_collection inside GistQdrantBackend.__init__
    collections_result = MagicMock()
    collections_result.collections = []
    mock.get_collections.return_value = collections_result
    return mock


def _make_mock_model(vector: list[float] | None = None) -> MagicMock:
    """Return a MagicMock EmbeddingModel."""
    mock = MagicMock()
    mock.embed.return_value = vector or [0.001 * i for i in range(384)]
    return mock


def _make_backend(mock_qdrant: MagicMock | None = None, mock_model: MagicMock | None = None) -> GistQdrantBackend:
    """Instantiate GistQdrantBackend with mocked Qdrant and model.

    Bypasses __init__ to avoid real network calls — injects mocks directly.
    """
    if mock_qdrant is None:
        mock_qdrant = _make_mock_qdrant()
    if mock_model is None:
        mock_model = _make_mock_model()

    backend = object.__new__(GistQdrantBackend)
    backend._qdrant = mock_qdrant
    backend._model = mock_model
    return backend


def _make_existing_point(
    gist_id: str = "abc",
    ratings: list[dict] | None = None,
    avg_outcome: float | None = None,
    avg_hours_saved: float | None = None,
    rating_count: int = 0,
) -> MagicMock:
    """Return a mock Qdrant point with the given payload."""
    point = MagicMock()
    point.payload = {
        "gist_id": gist_id,
        "ratings": ratings if ratings is not None else [],
        "avg_outcome": avg_outcome,
        "avg_hours_saved": avg_hours_saved,
        "rating_count": rating_count,
        "name": "Test Concept",
        "type": "pattern",
        "language": None,
        "author": None,
        "tags": [],
        "when_to_use": "Use it.",
        "dont_use_when": None,
        "usage_count": 0,
    }
    return point


def _make_hit(
    gist_id: str = "abc",
    score: float = 0.92,
    avg_outcome: float | None = None,
    avg_hours_saved: float | None = None,
) -> MagicMock:
    """Return a mock Qdrant search hit."""
    hit = MagicMock()
    hit.score = score
    hit.payload = {
        "gist_id": gist_id,
        "name": "WAL Mode",
        "type": "pattern",
        "language": "python",
        "author": "user1",
        "tags": ["sqlite"],
        "when_to_use": "Use for concurrent writes.",
        "dont_use_when": None,
        "avg_outcome": avg_outcome,
        "avg_hours_saved": avg_hours_saved,
        "usage_count": 0,
    }
    return hit


# ---------------------------------------------------------------------------
# HTTP test client helpers (mirrors test_semantic_api.py pattern)
# ---------------------------------------------------------------------------


class _MockRatingsStorage:
    """Storage mock for /ratings endpoint tests.

    Provides add_rating() controlled via _add_rating_result attribute.
    """

    def __init__(self):
        self._add_rating_result = {"avg_outcome": 4.0, "avg_hours_saved": None}
        self._add_rating_raises = None

    def add_rating(self, concept_id: str, outcome: int, hours_saved):
        if self._add_rating_raises is not None:
            raise self._add_rating_raises
        return self._add_rating_result

    def health_check(self) -> dict:
        return {"status": "ok"}

    def search_concepts(self, query_vector, limit, type_filter, language_filter, min_rating):
        return []


def _make_test_client(
    key_store=None,
    backend_name: str = "gist_qdrant",
    mock_storage=None,
) -> TestClient:
    """Return a TestClient with patched lifespan and injected app.state."""
    if mock_storage is None:
        mock_storage = _MockRatingsStorage()

    mock_model = _make_mock_model()

    with patch("lore.server.api.lifespan", _noop_lifespan):
        client = TestClient(app, raise_server_exceptions=True)

    app.state.storage = mock_storage
    app.state.model = mock_model
    app.state.backend_name = backend_name
    app.state.key_store = key_store
    return client


# ===========================================================================
# GistQdrantBackend.add_rating() — unit tests
# ===========================================================================


class TestAddRatingSingleRating:
    """Tests for GistQdrantBackend.add_rating() with a single rating."""

    def test_add_rating_returns_avg_outcome(self):
        """Single rating with outcome=4 returns avg_outcome=4.0."""
        mock_qdrant = _make_mock_qdrant()
        point = _make_existing_point(gist_id="abc", ratings=[])
        mock_qdrant.retrieve.return_value = [point]

        backend = _make_backend(mock_qdrant)
        result = backend.add_rating("abc", 4, None)

        assert result["avg_outcome"] == pytest.approx(4.0)

    def test_add_rating_single_with_hours_saved(self):
        """Single rating outcome=3, hours_saved=1.5 returns avg_hours_saved=1.5."""
        mock_qdrant = _make_mock_qdrant()
        point = _make_existing_point(gist_id="abc", ratings=[])
        mock_qdrant.retrieve.return_value = [point]

        backend = _make_backend(mock_qdrant)
        result = backend.add_rating("abc", 3, 1.5)

        assert result["avg_hours_saved"] == pytest.approx(1.5)

    def test_add_rating_hours_saved_omitted_returns_none(self):
        """outcome=5, hours_saved=None returns avg_hours_saved=None."""
        mock_qdrant = _make_mock_qdrant()
        point = _make_existing_point(gist_id="abc", ratings=[])
        mock_qdrant.retrieve.return_value = [point]

        backend = _make_backend(mock_qdrant)
        result = backend.add_rating("abc", 5, None)

        assert result["avg_hours_saved"] is None


class TestAddRatingMultipleRatings:
    """Tests for GistQdrantBackend.add_rating() with multiple ratings."""

    def test_add_rating_multiple_ratings_averages(self):
        """Two ratings (outcome=2 and outcome=4) produce avg_outcome=3.0."""
        mock_qdrant = _make_mock_qdrant()
        # Pre-existing rating with outcome=2
        existing_ratings = [{"outcome": 2, "hours_saved": None, "ts": "2026-07-14T00:00:00Z"}]
        point = _make_existing_point(gist_id="abc", ratings=existing_ratings)
        mock_qdrant.retrieve.return_value = [point]

        backend = _make_backend(mock_qdrant)
        result = backend.add_rating("abc", 4, None)

        assert result["avg_outcome"] == pytest.approx(3.0)

    def test_add_rating_mixed_hours_saved_excludes_none(self):
        """Two ratings: hours_saved=2.0 and hours_saved=None → avg_hours_saved=2.0."""
        mock_qdrant = _make_mock_qdrant()
        existing_ratings = [{"outcome": 3, "hours_saved": 2.0, "ts": "2026-07-14T00:00:00Z"}]
        point = _make_existing_point(gist_id="abc", ratings=existing_ratings)
        mock_qdrant.retrieve.return_value = [point]

        backend = _make_backend(mock_qdrant)
        result = backend.add_rating("abc", 4, None)

        # Only the 2.0 value should count — None is excluded
        assert result["avg_hours_saved"] == pytest.approx(2.0)

    def test_add_rating_all_hours_saved_present(self):
        """Two ratings with hours_saved=1.0 and 3.0 → avg_hours_saved=2.0."""
        mock_qdrant = _make_mock_qdrant()
        existing_ratings = [{"outcome": 5, "hours_saved": 1.0, "ts": "2026-07-14T00:00:00Z"}]
        point = _make_existing_point(gist_id="abc", ratings=existing_ratings)
        mock_qdrant.retrieve.return_value = [point]

        backend = _make_backend(mock_qdrant)
        result = backend.add_rating("abc", 3, 3.0)

        assert result["avg_hours_saved"] == pytest.approx(2.0)

    def test_add_rating_appends_to_existing_ratings(self):
        """Existing payload ratings=[{outcome:3}] + new outcome=5 → avg_outcome=4.0."""
        mock_qdrant = _make_mock_qdrant()
        existing_ratings = [{"outcome": 3, "hours_saved": None, "ts": "2026-07-13T00:00:00Z"}]
        point = _make_existing_point(gist_id="abc", ratings=existing_ratings)
        mock_qdrant.retrieve.return_value = [point]

        backend = _make_backend(mock_qdrant)
        result = backend.add_rating("abc", 5, None)

        assert result["avg_outcome"] == pytest.approx(4.0)


class TestAddRatingErrorCases:
    """Error-path tests for GistQdrantBackend.add_rating()."""

    def test_add_rating_concept_not_found_raises_key_error(self):
        """When retrieve returns [], add_rating raises KeyError."""
        mock_qdrant = _make_mock_qdrant()
        mock_qdrant.retrieve.return_value = []

        backend = _make_backend(mock_qdrant)
        with pytest.raises(KeyError):
            backend.add_rating("nonexistent-gist", 3, None)

    def test_add_rating_point_with_empty_payload_raises_key_error(self):
        """When retrieve returns a point with None payload, raises KeyError."""
        mock_qdrant = _make_mock_qdrant()
        point = MagicMock()
        point.payload = None
        mock_qdrant.retrieve.return_value = [point]

        backend = _make_backend(mock_qdrant)
        with pytest.raises(KeyError):
            backend.add_rating("abc", 3, None)


class TestAddRatingPayloadUpdates:
    """Tests that verify the correct payload is written to Qdrant."""

    def test_add_rating_updates_rating_count(self):
        """set_payload is called with rating_count == len(ratings after append)."""
        mock_qdrant = _make_mock_qdrant()
        # Start with 2 existing ratings
        existing_ratings = [
            {"outcome": 3, "hours_saved": None, "ts": "2026-07-14T00:00:00Z"},
            {"outcome": 4, "hours_saved": None, "ts": "2026-07-14T00:00:01Z"},
        ]
        point = _make_existing_point(gist_id="abc", ratings=existing_ratings)
        mock_qdrant.retrieve.return_value = [point]

        backend = _make_backend(mock_qdrant)
        backend.add_rating("abc", 5, None)

        set_payload_call = mock_qdrant.set_payload.call_args
        payload_written = set_payload_call[1]["payload"]
        # After appending one more, count should be 3
        assert payload_written["rating_count"] == 3

    def test_add_rating_calls_set_payload_with_correct_fields(self):
        """set_payload is called with all required keys: ratings, avg_outcome, avg_hours_saved, rating_count."""
        mock_qdrant = _make_mock_qdrant()
        point = _make_existing_point(gist_id="abc", ratings=[])
        mock_qdrant.retrieve.return_value = [point]

        backend = _make_backend(mock_qdrant)
        backend.add_rating("abc", 4, 1.0)

        mock_qdrant.set_payload.assert_called_once()
        set_payload_call = mock_qdrant.set_payload.call_args
        payload_written = set_payload_call[1]["payload"]

        assert "ratings" in payload_written
        assert "avg_outcome" in payload_written
        assert "avg_hours_saved" in payload_written
        assert "rating_count" in payload_written

    def test_add_rating_set_payload_targets_correct_point_id(self):
        """set_payload is called with the deterministic point ID for the given gist_id."""
        import uuid
        mock_qdrant = _make_mock_qdrant()
        point = _make_existing_point(gist_id="mygist", ratings=[])
        mock_qdrant.retrieve.return_value = [point]

        backend = _make_backend(mock_qdrant)
        backend.add_rating("mygist", 3, None)

        expected_point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "mygist"))
        set_payload_call = mock_qdrant.set_payload.call_args
        points_arg = set_payload_call[1]["points"]
        assert expected_point_id in points_arg

    def test_add_rating_appended_entry_has_ts_field(self):
        """The newly appended rating entry contains a 'ts' timestamp field."""
        mock_qdrant = _make_mock_qdrant()
        point = _make_existing_point(gist_id="abc", ratings=[])
        mock_qdrant.retrieve.return_value = [point]

        backend = _make_backend(mock_qdrant)
        backend.add_rating("abc", 4, None)

        set_payload_call = mock_qdrant.set_payload.call_args
        ratings_written = set_payload_call[1]["payload"]["ratings"]
        assert len(ratings_written) == 1
        assert "ts" in ratings_written[0]


# ===========================================================================
# POST /ratings HTTP endpoint tests
# ===========================================================================


class TestPostRatingSuccess:
    """Happy path tests for POST /ratings."""

    def test_post_rating_success_returns_avg_outcome(self):
        """POST /ratings with valid body returns 200 with avg_outcome."""
        storage = _MockRatingsStorage()
        storage._add_rating_result = {"avg_outcome": 4.0, "avg_hours_saved": None}
        client = _make_test_client(mock_storage=storage)

        resp = client.post("/ratings", json={"concept_id": "abc", "outcome": 4})

        assert resp.status_code == 200
        data = resp.json()
        assert data["avg_outcome"] == pytest.approx(4.0)

    def test_post_rating_hours_saved_optional(self):
        """Omitting hours_saved from POST /ratings body returns avg_hours_saved=None."""
        storage = _MockRatingsStorage()
        storage._add_rating_result = {"avg_outcome": 3.0, "avg_hours_saved": None}
        client = _make_test_client(mock_storage=storage)

        resp = client.post("/ratings", json={"concept_id": "abc", "outcome": 3})

        assert resp.status_code == 200
        assert resp.json()["avg_hours_saved"] is None

    def test_post_rating_with_hours_saved_returns_value(self):
        """POST /ratings with hours_saved passes it through and returns avg."""
        storage = _MockRatingsStorage()
        storage._add_rating_result = {"avg_outcome": 5.0, "avg_hours_saved": 2.5}
        client = _make_test_client(mock_storage=storage)

        resp = client.post("/ratings", json={"concept_id": "abc", "outcome": 5, "hours_saved": 2.5})

        assert resp.status_code == 200
        assert resp.json()["avg_hours_saved"] == pytest.approx(2.5)


class TestPostRatingNotFound:
    """404 paths for POST /ratings."""

    def test_post_rating_concept_not_found_returns_404(self):
        """add_rating raising KeyError → 404 response with concept_id."""
        storage = _MockRatingsStorage()
        storage._add_rating_raises = KeyError("missing-concept")
        client = _make_test_client(mock_storage=storage)

        resp = client.post("/ratings", json={"concept_id": "missing-concept", "outcome": 3})

        assert resp.status_code == 404
        data = resp.json()
        assert data["error"] == "not found"
        assert data["concept_id"] == "missing-concept"

    def test_post_rating_sqlite_qdrant_backend_returns_404(self):
        """POST /ratings returns 404 when backend_name != gist_qdrant."""
        client = _make_test_client(backend_name="sqlite_qdrant")

        resp = client.post("/ratings", json={"concept_id": "abc", "outcome": 3})

        assert resp.status_code == 404


class TestPostRatingValidation:
    """Input validation tests for POST /ratings."""

    def test_post_rating_outcome_out_of_range_returns_422(self):
        """outcome=6 is rejected with 422."""
        client = _make_test_client()

        resp = client.post("/ratings", json={"concept_id": "abc", "outcome": 6})

        assert resp.status_code == 422

    def test_post_rating_outcome_zero_returns_422(self):
        """outcome=0 is rejected with 422."""
        client = _make_test_client()

        resp = client.post("/ratings", json={"concept_id": "abc", "outcome": 0})

        assert resp.status_code == 422

    def test_post_rating_negative_hours_saved_returns_422(self):
        """hours_saved=-1 is rejected with 422."""
        client = _make_test_client()

        resp = client.post("/ratings", json={"concept_id": "abc", "outcome": 3, "hours_saved": -1})

        assert resp.status_code == 422

    def test_post_rating_missing_concept_id_returns_422(self):
        """Missing concept_id field returns 422."""
        client = _make_test_client()

        resp = client.post("/ratings", json={"outcome": 3})

        assert resp.status_code == 422

    def test_post_rating_missing_outcome_returns_422(self):
        """Missing outcome field returns 422."""
        client = _make_test_client()

        resp = client.post("/ratings", json={"concept_id": "abc"})

        assert resp.status_code == 422


class TestPostRatingAuth:
    """Auth enforcement tests for POST /ratings."""

    def test_post_rating_requires_auth_when_key_store_set(self):
        """No Authorization header when key_store is set → 401."""
        from lore.server.auth import KeyStore
        import tempfile, os

        with tempfile.TemporaryDirectory() as tmp:
            ks = KeyStore(db_path=f"{tmp}/keys.db")
            try:
                client = _make_test_client(key_store=ks)

                resp = client.post("/ratings", json={"concept_id": "abc", "outcome": 3})

                assert resp.status_code == 401
            finally:
                ks.close()

    def test_post_rating_invalid_auth_returns_401(self):
        """Invalid Bearer token → 401."""
        from lore.server.auth import KeyStore
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            ks = KeyStore(db_path=f"{tmp}/keys.db")
            try:
                client = _make_test_client(key_store=ks)

                resp = client.post(
                    "/ratings",
                    json={"concept_id": "abc", "outcome": 3},
                    headers={"Authorization": "Bearer invalidkey_notregistered"},
                )

                assert resp.status_code == 401
            finally:
                ks.close()

    def test_post_rating_valid_auth_passes_through(self):
        """Valid Bearer token passes auth and reaches add_rating()."""
        from lore.server.auth import KeyStore
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            ks = KeyStore(db_path=f"{tmp}/keys.db")
            api_key = ks.get_or_create("42", "testuser")
            try:
                storage = _MockRatingsStorage()
                storage._add_rating_result = {"avg_outcome": 3.0, "avg_hours_saved": None}
                client = _make_test_client(key_store=ks, mock_storage=storage)

                resp = client.post(
                    "/ratings",
                    json={"concept_id": "abc", "outcome": 3},
                    headers={"Authorization": f"Bearer {api_key}"},
                )

                assert resp.status_code == 200
            finally:
                ks.close()


class TestPostRatingNotImplemented:
    """501 path when storage raises NotImplementedError."""

    def test_post_rating_not_implemented_returns_501(self):
        """Storage raising NotImplementedError → 501."""
        storage = _MockRatingsStorage()
        storage._add_rating_raises = NotImplementedError("not supported")
        client = _make_test_client(mock_storage=storage)

        resp = client.post("/ratings", json={"concept_id": "abc", "outcome": 3})

        assert resp.status_code == 501


# ===========================================================================
# GET /search — avg_outcome and avg_hours_saved field presence
# ===========================================================================


class _MockSearchStorage:
    """Storage mock that returns configurable search results."""

    def __init__(self, hits: list[dict]):
        self._hits = hits

    def health_check(self) -> dict:
        return {"status": "ok"}

    def search_concepts(self, query_vector, limit, type_filter, language_filter, min_rating):
        from lore.server.storage.gist_qdrant import _payload_to_result

        class _FakeHit:
            def __init__(self, payload, score):
                self.payload = payload
                self.score = score

        return [_payload_to_result(h["payload"], h["score"]) for h in self._hits]


def _make_search_client(hits: list[dict]) -> TestClient:
    """Build a TestClient whose /search returns the given hit list."""
    storage = _MockSearchStorage(hits)
    mock_model = _make_mock_model()

    with patch("lore.server.api.lifespan", _noop_lifespan):
        client = TestClient(app, raise_server_exceptions=True)

    app.state.storage = storage
    app.state.model = mock_model
    app.state.backend_name = "gist_qdrant"
    app.state.key_store = None
    return client


class TestSearchResultRatingFields:
    """Tests that GET /search results include avg_outcome and avg_hours_saved fields."""

    def _single_hit(self, avg_outcome=None, avg_hours_saved=None):
        return [
            {
                "payload": {
                    "gist_id": "abc",
                    "name": "WAL Mode",
                    "type": "pattern",
                    "language": "python",
                    "author": "user1",
                    "tags": ["sqlite"],
                    "when_to_use": "Use for concurrent writes.",
                    "dont_use_when": None,
                    "avg_outcome": avg_outcome,
                    "avg_hours_saved": avg_hours_saved,
                    "usage_count": 0,
                },
                "score": 0.9,
            }
        ]

    def test_search_result_includes_avg_outcome_field(self):
        """GET /search result dict has avg_outcome key."""
        client = _make_search_client(self._single_hit())

        resp = client.get("/search", params={"q": "sqlite"})

        assert resp.status_code == 200
        result = resp.json()["results"][0]
        assert "avg_outcome" in result

    def test_search_result_avg_outcome_none_when_unrated(self):
        """avg_outcome is None when payload has avg_outcome=None."""
        client = _make_search_client(self._single_hit(avg_outcome=None))

        resp = client.get("/search", params={"q": "sqlite"})

        result = resp.json()["results"][0]
        assert result["avg_outcome"] is None

    def test_search_result_avg_outcome_populated_after_rating(self):
        """avg_outcome=3.5 in payload is reflected in the search result."""
        client = _make_search_client(self._single_hit(avg_outcome=3.5))

        resp = client.get("/search", params={"q": "sqlite"})

        result = resp.json()["results"][0]
        assert result["avg_outcome"] == pytest.approx(3.5)

    def test_search_result_avg_hours_saved_field_present(self):
        """GET /search result has avg_hours_saved key."""
        client = _make_search_client(self._single_hit(avg_hours_saved=1.5))

        resp = client.get("/search", params={"q": "sqlite"})

        result = resp.json()["results"][0]
        assert "avg_hours_saved" in result
        assert result["avg_hours_saved"] == pytest.approx(1.5)

    def test_search_result_avg_hours_saved_none_when_absent(self):
        """avg_hours_saved is None when payload has no hours saved."""
        client = _make_search_client(self._single_hit(avg_hours_saved=None))

        resp = client.get("/search", params={"q": "sqlite"})

        result = resp.json()["results"][0]
        assert result["avg_hours_saved"] is None

    def test_payload_to_result_maps_avg_outcome(self):
        """_payload_to_result() maps avg_outcome field correctly."""
        payload = {
            "gist_id": "abc",
            "name": "Test",
            "type": "pattern",
            "avg_outcome": 4.2,
            "avg_hours_saved": 1.0,
            "usage_count": 3,
        }
        result = _payload_to_result(payload, 0.95)

        assert result["avg_outcome"] == pytest.approx(4.2)
        # avg_rating is the legacy alias
        assert result["avg_rating"] == pytest.approx(4.2)

    def test_payload_to_result_maps_avg_hours_saved(self):
        """_payload_to_result() maps avg_hours_saved and time_saved_avg_hours alias."""
        payload = {
            "gist_id": "abc",
            "name": "Test",
            "type": "pattern",
            "avg_outcome": None,
            "avg_hours_saved": 2.5,
            "usage_count": 0,
        }
        result = _payload_to_result(payload, 0.8)

        assert result["avg_hours_saved"] == pytest.approx(2.5)
        assert result["time_saved_avg_hours"] == pytest.approx(2.5)


# ===========================================================================
# BackendRouter.rate_concept() — semantic path
# ===========================================================================


def _make_router(semantic_url: str | None = "http://localhost:8766") -> "BackendRouter":
    """Return a BackendRouter pointing at the given semantic URL."""
    from lore.mcp.router import BackendRouter

    router = BackendRouter(backend="gists", selfhosted_url="http://localhost:8765")
    router._semantic_url = semantic_url
    router._semantic_api_key = None
    return router


def _mock_httpx_client(response_json: dict, status_code: int = 200):
    """Return (mock_client_cls, mock_client_instance) for patching httpx.Client.

    The mock_client_instance.post() returns a response with the given body.
    """
    mock_response = MagicMock()
    mock_response.json.return_value = response_json
    mock_response.raise_for_status.return_value = None
    mock_response.status_code = status_code

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_response

    return mock_client


class TestBackendRouterRateConcept:
    """Tests for BackendRouter.rate_concept() with semantic URL configured."""

    def test_rate_concept_semantic_url_set_posts_to_ratings_endpoint(self):
        """When semantic_url is set, rate_concept POSTs to /ratings."""
        router = _make_router(semantic_url="http://localhost:8766")
        mock_client = _mock_httpx_client({"avg_outcome": 4.0, "avg_hours_saved": None})

        with patch("lore.mcp.router.httpx.Client", return_value=mock_client):
            result = router.rate_concept("gist-abc", 4, "session-1")

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/ratings"

    def test_rate_concept_semantic_url_set_sends_auth_header(self):
        """When api_key is available, Authorization header is sent."""
        router = _make_router(semantic_url="http://localhost:8766")
        router._semantic_api_key = "testkey_64chars_" + "x" * 48
        mock_client = _mock_httpx_client({"avg_outcome": 3.0, "avg_hours_saved": None})

        with patch("lore.mcp.router.httpx.Client", return_value=mock_client), \
             patch.object(router, "_ensure_semantic_api_key", return_value=router._semantic_api_key):
            router.rate_concept("gist-abc", 3, "session-1")

        call_kwargs = mock_client.post.call_args[1]
        headers = call_kwargs.get("headers", {})
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")

    def test_rate_concept_semantic_url_not_set_calls_gists_backend(self):
        """When _semantic_url is None, falls back to gists_backend.rate_concept."""
        router = _make_router(semantic_url=None)

        with patch("lore.mcp.router.gists_backend.rate_concept", return_value={"avg_rating": 3.0}) as mock_gists, \
             patch("lore.mcp.router.GistsClient"):
            result = router.rate_concept("gist-abc", 3, "session-1")

        mock_gists.assert_called_once()
        assert result == {"avg_rating": 3.0}

    def test_rate_concept_semantic_server_error_raises_runtime_error(self):
        """When semantic server returns 500, raises RuntimeError."""
        router = _make_router(semantic_url="http://localhost:8766")

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Server Error",
            request=MagicMock(),
            response=mock_response,
        )

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response

        with patch("lore.mcp.router.httpx.Client", return_value=mock_client), \
             patch.object(router, "_ensure_semantic_api_key", return_value=None):
            with pytest.raises(RuntimeError):
                router.rate_concept("gist-abc", 3, "session-1")

    def test_rate_concept_hours_saved_included_in_payload(self):
        """When hours_saved is given, the POST body includes hours_saved."""
        router = _make_router(semantic_url="http://localhost:8766")
        mock_client = _mock_httpx_client({"avg_outcome": 4.0, "avg_hours_saved": 1.5})

        with patch("lore.mcp.router.httpx.Client", return_value=mock_client), \
             patch.object(router, "_ensure_semantic_api_key", return_value=None):
            router.rate_concept("gist-abc", 4, "session-1", hours_saved=1.5)

        call_kwargs = mock_client.post.call_args[1]
        body = call_kwargs.get("json", {})
        assert "hours_saved" in body
        assert body["hours_saved"] == pytest.approx(1.5)

    def test_rate_concept_hours_saved_none_not_included_in_payload(self):
        """When hours_saved=None, the POST body does NOT include hours_saved."""
        router = _make_router(semantic_url="http://localhost:8766")
        mock_client = _mock_httpx_client({"avg_outcome": 3.0, "avg_hours_saved": None})

        with patch("lore.mcp.router.httpx.Client", return_value=mock_client), \
             patch.object(router, "_ensure_semantic_api_key", return_value=None):
            router.rate_concept("gist-abc", 3, "session-1", hours_saved=None)

        call_kwargs = mock_client.post.call_args[1]
        body = call_kwargs.get("json", {})
        assert "hours_saved" not in body

    def test_rate_concept_payload_contains_concept_id_and_outcome(self):
        """POST body always contains concept_id and outcome."""
        router = _make_router(semantic_url="http://localhost:8766")
        mock_client = _mock_httpx_client({"avg_outcome": 4.0, "avg_hours_saved": None})

        with patch("lore.mcp.router.httpx.Client", return_value=mock_client), \
             patch.object(router, "_ensure_semantic_api_key", return_value=None):
            router.rate_concept("gist-xyz", 4, "session-99")

        call_kwargs = mock_client.post.call_args[1]
        body = call_kwargs.get("json", {})
        assert body["concept_id"] == "gist-xyz"
        assert body["outcome"] == 4

    def test_rate_concept_returns_semantic_server_response(self):
        """result dict is the JSON response from the semantic server."""
        router = _make_router(semantic_url="http://localhost:8766")
        expected = {"avg_outcome": 4.5, "avg_hours_saved": 2.0}
        mock_client = _mock_httpx_client(expected)

        with patch("lore.mcp.router.httpx.Client", return_value=mock_client), \
             patch.object(router, "_ensure_semantic_api_key", return_value=None):
            result = router.rate_concept("gist-abc", 5, "session-1", hours_saved=2.0)

        assert result["avg_outcome"] == pytest.approx(4.5)
        assert result["avg_hours_saved"] == pytest.approx(2.0)

    def test_rate_concept_no_api_key_no_auth_header(self):
        """When _ensure_semantic_api_key returns None, no Authorization header is sent."""
        router = _make_router(semantic_url="http://localhost:8766")
        mock_client = _mock_httpx_client({"avg_outcome": 3.0, "avg_hours_saved": None})

        with patch("lore.mcp.router.httpx.Client", return_value=mock_client), \
             patch.object(router, "_ensure_semantic_api_key", return_value=None):
            router.rate_concept("gist-abc", 3, "session-1")

        call_kwargs = mock_client.post.call_args[1]
        headers = call_kwargs.get("headers", {})
        assert "Authorization" not in headers
