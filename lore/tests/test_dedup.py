"""Tests for LORE-035: deduplication support.

Test areas
----------
TestSearchSimilar
    - happy path: returns list of {id, title, score} dicts when hits found
    - empty collection: returns [] when query_points raises "doesn't exist"
    - qdrant unreachable (other exception): returns [] (swallowed with warning)
    - exclude_id: excluded concept is not in results
    - top_k: correct limit is passed to qdrant

TestGistUpsertDedupEndpoint
    - search_similar hit at 0.95 → 409 with duplicate payload
    - env var LORE_DEDUP_THRESHOLD=0.80 lowers the bar → 0.85 score → 409
    - default threshold 0.92: score 0.85 → 200 (no dup)
    - force=True bypasses dedup check → 200 even with high-score hit
    - score == threshold (0.92) is treated as duplicate → 409
    - hit with missing payload is skipped

TestGistUpsertEndpoint
    - no auth returns 401 (sanity-check — dedup never reached)
    - sqlite_qdrant backend returns 404 (route not active)
    - gist_qdrant upsert: upsert_concept called with correct payload, 200 returned
    - gist_qdrant: storage raising exception returns 500 (unhandled) or propagates

TestDuplicateConceptError
    - basic: .similar attribute matches the supplied list
    - message: str(error) contains concept title and score
    - single item list: message is well-formed
    - empty list: construction does not raise; similar is []
    - score formatting: score formatted to 3 decimal places

TestBackendRouterDedup
    - 409 response raises DuplicateConceptError with correct .similar
    - force=True sends force in the JSON payload
    - force=False (default) does not send force key
    - 201 response returns parsed JSON body
    - 422 response raises ValueError (scanner rejection)
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lore.mcp.router import BackendRouter, DuplicateConceptError
from lore.server.api import app, _require_api_key
from lore.server.auth import KeyStore
from lore.server.storage.gist_qdrant import GistQdrantBackend, COLLECTION_NAME


# ---------------------------------------------------------------------------
# Shared test helpers (mirrors test_auth.py pattern)
# ---------------------------------------------------------------------------


def _noop_lifespan(application: FastAPI):
    """Async context manager lifespan that does nothing."""

    @asynccontextmanager
    async def _inner(application: FastAPI):
        yield

    return _inner(application)


def _make_mock_storage(backend_name: str = "gist_qdrant") -> MagicMock:
    """Return a minimal mock StorageBackend."""
    storage = MagicMock()
    storage.health_check.return_value = {"status": "ok"}
    storage.upsert_concept.return_value = {"status": "upserted", "gist_id": "abc123"}
    storage.search_similar.return_value = []
    return storage


def _make_test_client(
    key_store: "KeyStore | None" = None,
    backend_name: str = "gist_qdrant",
    mock_storage=None,
) -> TestClient:
    """Return a TestClient with patched lifespan and injected app.state."""
    if mock_storage is None:
        mock_storage = _make_mock_storage(backend_name)

    mock_model = MagicMock()
    mock_model.embed.return_value = [0.0] * 384

    with patch("lore.server.api.lifespan", _noop_lifespan):
        client = TestClient(app, raise_server_exceptions=False)

    app.state.storage = mock_storage
    app.state.model = mock_model
    app.state.backend_name = backend_name
    app.state.key_store = key_store
    return client


def _make_mock_qdrant_client() -> MagicMock:
    """Return a mock QdrantClient that survives _init_collection."""
    qdrant = MagicMock()
    mock_collections = MagicMock()
    mock_collections.collections = []
    qdrant.get_collections.return_value = mock_collections
    return qdrant


def _make_gist_backend(mock_qdrant: MagicMock) -> GistQdrantBackend:
    """Instantiate GistQdrantBackend with a fake QdrantClient."""
    mock_model = MagicMock()
    mock_model.embed.return_value = [0.0] * 384

    with patch("lore.server.storage.gist_qdrant.QdrantClient", return_value=mock_qdrant):
        backend = GistQdrantBackend(
            qdrant_host="localhost",
            qdrant_port=6333,
            model=mock_model,
        )
    return backend


def _make_qdrant_hits(
    items: list[dict],
) -> MagicMock:
    """Build a mock query_points response with the given payload/score items.

    Args:
        items: List of dicts with ``gist_id``, ``name``, and ``score`` keys.

    Returns:
        A MagicMock whose ``.points`` attribute contains the built hit objects.
    """
    hits = []
    for item in items:
        hit = MagicMock()
        hit.payload = {"gist_id": item["gist_id"], "name": item["name"]}
        hit.score = item["score"]
        hits.append(hit)

    response = MagicMock()
    response.points = hits
    return response


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def bypass_auth():
    """Patch _require_api_key to skip authentication for endpoint tests."""
    app.dependency_overrides[_require_api_key] = lambda: ""
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# TestSearchSimilar
# ---------------------------------------------------------------------------


class TestSearchSimilar:
    """Unit tests for GistQdrantBackend.search_similar."""

    def test_happy_path_returns_expected_dicts(self):
        """Happy path: returns [{id, title, score}] list for found hits."""
        mock_qdrant = _make_mock_qdrant_client()
        backend = _make_gist_backend(mock_qdrant)

        mock_qdrant.query_points.return_value = _make_qdrant_hits(
            [
                {"gist_id": "abc123", "name": "My Pattern", "score": 0.95},
                {"gist_id": "def456", "name": "Other Concept", "score": 0.93},
            ]
        )

        result = backend.search_similar([0.0] * 384, top_k=3)

        assert len(result) == 2
        assert result[0] == {"id": "abc123", "title": "My Pattern", "score": 0.95}
        assert result[1] == {"id": "def456", "title": "Other Concept", "score": 0.93}

    def test_empty_collection_returns_empty_list(self):
        """Returns [] when query_points raises a 'doesn't exist' error."""
        mock_qdrant = _make_mock_qdrant_client()
        backend = _make_gist_backend(mock_qdrant)

        mock_qdrant.query_points.side_effect = Exception("Collection doesn't exist")

        result = backend.search_similar([0.0] * 384)
        assert result == []

    def test_not_found_error_returns_empty_list(self):
        """Returns [] when query_points raises a 'Not found' error."""
        mock_qdrant = _make_mock_qdrant_client()
        backend = _make_gist_backend(mock_qdrant)

        mock_qdrant.query_points.side_effect = Exception("Not found: collection lore_concepts")

        result = backend.search_similar([0.0] * 384)
        assert result == []

    def test_qdrant_unreachable_returns_empty_list(self):
        """Returns [] when Qdrant raises an unexpected connection error."""
        mock_qdrant = _make_mock_qdrant_client()
        backend = _make_gist_backend(mock_qdrant)

        mock_qdrant.query_points.side_effect = ConnectionRefusedError("Connection refused")

        result = backend.search_similar([0.0] * 384)
        assert result == []

    def test_exclude_id_omits_matching_concept(self):
        """The concept matching exclude_id is not included in results."""
        mock_qdrant = _make_mock_qdrant_client()
        backend = _make_gist_backend(mock_qdrant)

        mock_qdrant.query_points.return_value = _make_qdrant_hits(
            [
                {"gist_id": "target-id", "name": "Self", "score": 0.99},
                {"gist_id": "other-id", "name": "Other", "score": 0.94},
            ]
        )

        result = backend.search_similar([0.0] * 384, exclude_id="target-id")

        ids = [r["id"] for r in result]
        assert "target-id" not in ids
        assert "other-id" in ids

    def test_top_k_is_passed_to_qdrant(self):
        """top_k is forwarded as the limit argument to query_points."""
        mock_qdrant = _make_mock_qdrant_client()
        backend = _make_gist_backend(mock_qdrant)

        response = MagicMock()
        response.points = []
        mock_qdrant.query_points.return_value = response

        backend.search_similar([0.0] * 384, top_k=7)

        call_kwargs = mock_qdrant.query_points.call_args
        assert call_kwargs.kwargs.get("limit") == 7 or (
            call_kwargs.args and 7 in call_kwargs.args
        )

    def test_hit_with_missing_payload_is_skipped(self):
        """A hit with no payload dict is silently omitted from results."""
        mock_qdrant = _make_mock_qdrant_client()
        backend = _make_gist_backend(mock_qdrant)

        empty_hit = MagicMock()
        empty_hit.payload = None
        valid_hit = MagicMock()
        valid_hit.payload = {"gist_id": "abc", "name": "Valid"}
        valid_hit.score = 0.91

        response = MagicMock()
        response.points = [empty_hit, valid_hit]
        mock_qdrant.query_points.return_value = response

        result = backend.search_similar([0.0] * 384)

        assert len(result) == 1
        assert result[0]["id"] == "abc"

    def test_score_is_rounded_to_six_decimal_places(self):
        """Scores in returned dicts are rounded to 6 decimal places."""
        mock_qdrant = _make_mock_qdrant_client()
        backend = _make_gist_backend(mock_qdrant)

        hit = MagicMock()
        hit.payload = {"gist_id": "z", "name": "Z"}
        hit.score = 0.9512345678

        response = MagicMock()
        response.points = [hit]
        mock_qdrant.query_points.return_value = response

        result = backend.search_similar([0.0] * 384)

        assert result[0]["score"] == round(0.9512345678, 6)

    def test_passes_correct_collection_name(self):
        """query_points is called with the canonical COLLECTION_NAME."""
        mock_qdrant = _make_mock_qdrant_client()
        backend = _make_gist_backend(mock_qdrant)

        response = MagicMock()
        response.points = []
        mock_qdrant.query_points.return_value = response

        backend.search_similar([0.0] * 384)

        call_kwargs = mock_qdrant.query_points.call_args
        assert call_kwargs.kwargs.get("collection_name") == COLLECTION_NAME


# ---------------------------------------------------------------------------
# TestGistUpsertEndpoint
# ---------------------------------------------------------------------------


class TestGistUpsertEndpoint:
    """Integration-style tests for POST /concepts (gist_upsert_concept handler)."""

    def _valid_body(self) -> dict:
        return {
            "gist_id": "abc123",
            "name": "My Pattern",
            "type": "pattern",
            "when_to_use": "Use when testing.",
            "gist_updated_at": "2026-07-14T00:00:00Z",
            "tags": [],
        }

    def test_no_auth_returns_401(self, tmp_path):
        """POST /concepts without auth returns 401 on gist_qdrant backend."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        client = _make_test_client(key_store=ks, backend_name="gist_qdrant")

        resp = client.post("/concepts", json=self._valid_body())
        assert resp.status_code == 401
        ks.close()

    def test_sqlite_qdrant_backend_returns_404(self, bypass_auth):
        """POST /concepts returns 404 when backend is sqlite_qdrant."""
        client = _make_test_client(key_store=None, backend_name="sqlite_qdrant")

        resp = client.post("/concepts", json=self._valid_body())
        assert resp.status_code == 404

    def test_valid_upsert_calls_storage_and_returns_200(self, tmp_path, bypass_auth):
        """POST /concepts with a valid body calls upsert_concept and returns 200."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        api_key = ks.get_or_create("42", "testuser")

        mock_storage = _make_mock_storage("gist_qdrant")
        mock_storage.upsert_concept.return_value = {"status": "upserted", "gist_id": "abc123"}

        client = _make_test_client(
            key_store=ks, backend_name="gist_qdrant", mock_storage=mock_storage
        )

        resp = client.post(
            "/concepts",
            json=self._valid_body(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["gist_id"] == "abc123"
        mock_storage.upsert_concept.assert_called_once()
        ks.close()

    def test_skipped_status_is_returned(self, tmp_path, bypass_auth):
        """POST /concepts forwards skipped status from storage unchanged."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        api_key = ks.get_or_create("42", "testuser")

        mock_storage = _make_mock_storage("gist_qdrant")
        mock_storage.upsert_concept.return_value = {"status": "skipped", "gist_id": "abc123"}

        client = _make_test_client(
            key_store=ks, backend_name="gist_qdrant", mock_storage=mock_storage
        )

        resp = client.post("/concepts", json=self._valid_body())
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"
        ks.close()

    def test_upsert_payload_contains_all_fields(self, tmp_path, bypass_auth):
        """upsert_concept is called with a payload containing all expected fields."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        api_key = ks.get_or_create("42", "testuser")

        mock_storage = _make_mock_storage("gist_qdrant")
        client = _make_test_client(
            key_store=ks, backend_name="gist_qdrant", mock_storage=mock_storage
        )

        body = {
            "gist_id": "xyz789",
            "name": "My Concept",
            "type": "pattern",
            "when_to_use": "When needed.",
            "gist_updated_at": "2026-07-14T12:00:00Z",
            "tags": ["python", "test"],
            "author": "alice",
            "language": "python",
        }

        client.post("/concepts", json=body)

        call_args = mock_storage.upsert_concept.call_args
        passed_payload = call_args[0][0]
        assert passed_payload["gist_id"] == "xyz789"
        assert passed_payload["name"] == "My Concept"
        assert passed_payload["when_to_use"] == "When needed."
        assert passed_payload["gist_updated_at"] == "2026-07-14T12:00:00Z"
        assert passed_payload["author"] == "alice"
        assert passed_payload["language"] == "python"
        ks.close()


# ---------------------------------------------------------------------------
# TestDuplicateConceptError
# ---------------------------------------------------------------------------


class TestDuplicateConceptError:
    """Unit tests for the DuplicateConceptError exception class."""

    def test_similar_attribute_matches_supplied_list(self):
        """DuplicateConceptError.similar holds the list passed at construction."""
        similar = [{"id": "x", "title": "My Pattern", "score": 0.95}]
        exc = DuplicateConceptError(similar)
        assert exc.similar is similar

    def test_message_contains_title(self):
        """str(error) includes the similar concept's title."""
        exc = DuplicateConceptError([{"id": "x", "title": "My Pattern", "score": 0.95}])
        assert "My Pattern" in str(exc)

    def test_message_contains_score(self):
        """str(error) includes the score formatted to 3 decimal places."""
        exc = DuplicateConceptError([{"id": "x", "title": "Concept", "score": 0.954}])
        assert "0.954" in str(exc)

    def test_message_with_multiple_similars(self):
        """str(error) mentions all similar concept titles."""
        similar = [
            {"id": "a", "title": "Alpha", "score": 0.97},
            {"id": "b", "title": "Beta", "score": 0.93},
        ]
        exc = DuplicateConceptError(similar)
        msg = str(exc)
        assert "Alpha" in msg
        assert "Beta" in msg

    def test_empty_list_does_not_raise(self):
        """DuplicateConceptError([]) constructs without error; .similar is []."""
        exc = DuplicateConceptError([])
        assert exc.similar == []

    def test_is_exception(self):
        """DuplicateConceptError is an Exception subclass."""
        exc = DuplicateConceptError([])
        assert isinstance(exc, Exception)

    def test_score_formatting_three_decimal_places(self):
        """Scores appear with exactly 3 decimal places (:.3f) in the message."""
        exc = DuplicateConceptError([{"id": "z", "title": "X", "score": 0.9}])
        # 0.9 formatted as :.3f is "0.900"
        assert "0.900" in str(exc)


# ---------------------------------------------------------------------------
# TestBackendRouterDedup
# ---------------------------------------------------------------------------


class TestBackendRouterDedup:
    """Tests for BackendRouter.submit_concept dedup behaviour (selfhosted backend)."""

    def _make_router(self) -> BackendRouter:
        return BackendRouter(backend="selfhosted", selfhosted_url="http://localhost:8765")

    def _mock_client(self, status_code: int, body: dict):
        """Return a patched httpx.Client context manager with the given response."""
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.json.return_value = body
        mock_response.is_error = status_code >= 400
        mock_response.text = str(body)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        return mock_client

    def _submit(self, router: BackendRouter, mock_client: MagicMock, **kwargs):
        """Call router.submit_concept with a mock httpx.Client."""
        defaults = dict(
            name="Test Concept",
            type="pattern",
            content="Some content here.",
            when_to_use="Use when testing.",
            tags=["test"],
        )
        defaults.update(kwargs)

        with patch("lore.mcp.router.httpx.Client", return_value=mock_client):
            return router.submit_concept(**defaults)

    def test_409_raises_duplicate_concept_error(self):
        """409 response from selfhosted raises DuplicateConceptError."""
        router = self._make_router()
        similar = [{"id": "abc", "title": "Existing Concept", "score": 0.95}]
        mock_client = self._mock_client(
            409, {"duplicate": True, "similar": similar}
        )

        with pytest.raises(DuplicateConceptError) as exc_info:
            self._submit(router, mock_client)

        assert exc_info.value.similar == similar

    def test_409_with_empty_similar_raises_duplicate_concept_error(self):
        """409 response with empty similar list still raises DuplicateConceptError."""
        router = self._make_router()
        mock_client = self._mock_client(409, {"duplicate": True, "similar": []})

        with pytest.raises(DuplicateConceptError) as exc_info:
            self._submit(router, mock_client)

        assert exc_info.value.similar == []

    def test_force_true_sends_force_in_payload(self):
        """When force=True, the JSON payload includes force=True."""
        router = self._make_router()
        mock_client = self._mock_client(
            201, {"concept_id": "new-id", "name": "Test Concept"}
        )

        self._submit(router, mock_client, force=True)

        call_kwargs = mock_client.post.call_args
        sent_json = call_kwargs.kwargs.get("json", call_kwargs.args[1] if len(call_kwargs.args) > 1 else {})
        assert sent_json.get("force") is True

    def test_force_false_does_not_send_force_key(self):
        """When force=False (default), the JSON payload does not include force."""
        router = self._make_router()
        mock_client = self._mock_client(
            201, {"concept_id": "new-id", "name": "Test Concept"}
        )

        self._submit(router, mock_client, force=False)

        call_kwargs = mock_client.post.call_args
        sent_json = call_kwargs.kwargs.get(
            "json", call_kwargs.args[1] if len(call_kwargs.args) > 1 else {}
        )
        assert "force" not in sent_json

    def test_201_returns_parsed_json_body(self):
        """201 response returns the parsed JSON body as a dict."""
        router = self._make_router()
        expected = {"concept_id": "abc-123", "name": "Test Concept"}
        mock_client = self._mock_client(201, expected)

        result = self._submit(router, mock_client)

        assert result == expected

    def test_422_raises_value_error(self):
        """422 response (scanner rejection) raises ValueError."""
        router = self._make_router()
        mock_client = self._mock_client(
            422,
            {"error": "Content blocked by scanner", "matches": ["secret_key"]},
        )

        with pytest.raises(ValueError):
            self._submit(router, mock_client)

    def test_duplicate_concept_error_similar_preserved(self):
        """DuplicateConceptError.similar matches the list from the 409 response body."""
        router = self._make_router()
        similar = [
            {"id": "x", "title": "Concept X", "score": 0.97},
            {"id": "y", "title": "Concept Y", "score": 0.93},
        ]
        mock_client = self._mock_client(409, {"duplicate": True, "similar": similar})

        with pytest.raises(DuplicateConceptError) as exc_info:
            self._submit(router, mock_client)

        assert len(exc_info.value.similar) == 2
        assert exc_info.value.similar[0]["title"] == "Concept X"
        assert exc_info.value.similar[1]["id"] == "y"


# ---------------------------------------------------------------------------
# TestGistUpsertDedupEndpoint
# ---------------------------------------------------------------------------


class TestGistUpsertDedupEndpoint:
    """Integration tests for dedup wiring in POST /concepts (gist_upsert_concept).

    Covers Gap 1 (dedup wired), Gap 2 (env var threshold), Gap 3 (force bypass),
    and Gap 4 (boundary score == threshold treated as duplicate).
    """

    def _valid_body(self, **overrides) -> dict:
        """Return a minimal valid ConceptUpsertRequest body."""
        base = {
            "gist_id": "abc123",
            "name": "My Pattern",
            "type": "pattern",
            "when_to_use": "Use when testing.",
            "gist_updated_at": "2026-07-14T00:00:00Z",
            "tags": [],
        }
        base.update(overrides)
        return base

    def test_search_similar_hit_returns_409(self, bypass_auth):
        """POST /concepts returns 409 when search_similar returns a hit above threshold.

        Gap 1: validates that the dedup check is wired into the endpoint.
        """
        similar_hit = [{"id": "dup-id", "title": "Existing Concept", "score": 0.95}]
        mock_storage = _make_mock_storage("gist_qdrant")
        mock_storage.search_similar.return_value = similar_hit

        client = _make_test_client(backend_name="gist_qdrant", mock_storage=mock_storage)

        resp = client.post("/concepts", json=self._valid_body())

        assert resp.status_code == 409
        body = resp.json()
        assert body["duplicate"] is True
        assert body["similar"] == similar_hit
        # upsert_concept must NOT have been called
        mock_storage.upsert_concept.assert_not_called()

    def test_env_var_threshold_lowers_bar(self, bypass_auth, monkeypatch):
        """LORE_DEDUP_THRESHOLD=0.80 causes score=0.85 to trigger 409.

        Gap 2 (low threshold branch): env var overrides the compile-time default.
        """
        monkeypatch.setenv("LORE_DEDUP_THRESHOLD", "0.80")

        similar_hit = [{"id": "dup-id", "title": "Near Match", "score": 0.85}]
        mock_storage = _make_mock_storage("gist_qdrant")
        mock_storage.search_similar.return_value = similar_hit

        client = _make_test_client(backend_name="gist_qdrant", mock_storage=mock_storage)

        resp = client.post("/concepts", json=self._valid_body())

        assert resp.status_code == 409
        assert resp.json()["duplicate"] is True

    def test_default_threshold_passes_below_threshold(self, bypass_auth, monkeypatch):
        """With default threshold (0.92), a score of 0.85 does NOT trigger 409.

        Gap 2 (high threshold branch): same score that triggered 409 with 0.80
        threshold passes through when threshold is the default 0.92.
        """
        monkeypatch.delenv("LORE_DEDUP_THRESHOLD", raising=False)

        similar_hit = [{"id": "near-id", "title": "Near Match", "score": 0.85}]
        mock_storage = _make_mock_storage("gist_qdrant")
        mock_storage.search_similar.return_value = similar_hit

        client = _make_test_client(backend_name="gist_qdrant", mock_storage=mock_storage)

        resp = client.post("/concepts", json=self._valid_body())

        assert resp.status_code == 200
        mock_storage.upsert_concept.assert_called_once()

    def test_force_true_bypasses_dedup_check(self, bypass_auth):
        """POST /concepts with force=True proceeds to upsert even with a high-score hit.

        Gap 3: validates the force bypass.
        """
        similar_hit = [{"id": "dup-id", "title": "Existing Concept", "score": 0.99}]
        mock_storage = _make_mock_storage("gist_qdrant")
        mock_storage.search_similar.return_value = similar_hit

        client = _make_test_client(backend_name="gist_qdrant", mock_storage=mock_storage)

        resp = client.post("/concepts", json=self._valid_body(force=True))

        assert resp.status_code == 200
        mock_storage.upsert_concept.assert_called_once()
        # search_similar must NOT have been called when force=True
        mock_storage.search_similar.assert_not_called()

    def test_score_equal_to_threshold_is_duplicate(self, bypass_auth, monkeypatch):
        """A score exactly equal to the threshold triggers a 409 (boundary: >=).

        Gap 4: validates that the comparison is >= not >.
        """
        monkeypatch.delenv("LORE_DEDUP_THRESHOLD", raising=False)

        # Default threshold is 0.92; exact match must be treated as duplicate.
        similar_hit = [{"id": "exact-id", "title": "Exact Boundary", "score": 0.92}]
        mock_storage = _make_mock_storage("gist_qdrant")
        mock_storage.search_similar.return_value = similar_hit

        client = _make_test_client(backend_name="gist_qdrant", mock_storage=mock_storage)

        resp = client.post("/concepts", json=self._valid_body())

        assert resp.status_code == 409
        assert resp.json()["duplicate"] is True
        mock_storage.upsert_concept.assert_not_called()
