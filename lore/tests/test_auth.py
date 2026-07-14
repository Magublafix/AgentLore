"""Tests for LORE-034: API key authentication for the Lore semantic server.

Test areas
----------
KeyStore
    - get_or_create: new user -> 64-char hex key
    - get_or_create: same user twice -> same key (idempotent)
    - get_or_create: two different users -> different keys
    - validate: valid key -> True
    - validate: unknown key -> False
    - validate: empty string -> False

verify_github_token
    - success -> dict with id and login
    - 401 response -> raises httpx.HTTPStatusError
    - network failure -> raises httpx.HTTPError

POST /auth/register
    - valid github_token -> 201 with api_key and github_login
    - invalid github_token -> 401
    - GitHub API down -> 502
    - same github user twice -> 201, same api_key (idempotent)
    - sqlite_qdrant backend -> 404

POST /v1/concepts (auth)
    - gist_qdrant, no auth header -> 401
    - gist_qdrant, invalid key -> 401
    - gist_qdrant, valid key -> passes through (201 or 503)
    - sqlite_qdrant backend -> no auth required (no 401)

POST /concepts (gist route auth)
    - no auth header -> 401
    - valid key -> passes through

POST /v1/concepts/{id}/rate (auth)
    - no auth header -> 401

BackendRouter._ensure_semantic_api_key
    - no LORE_GITHUB_TOKEN -> returns None
    - successful register -> caches key
    - cache file present -> reads from file (no HTTP call)
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lore.server.api import app
from lore.server.auth import KeyStore, verify_github_token


# ---------------------------------------------------------------------------
# Helpers (shared with test_semantic_api.py pattern)
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
    storage.upsert_concept.return_value = {"status": "upserted", "gist_id": "abc"}
    storage.get_concept.return_value = {
        "concept_id": "test-id",
        "name": "Test",
        "type": "pattern",
        "links": [],
    }
    storage.rate_concept.return_value = {"avg_rating": 3.0, "time_saved_avg_hours": None}
    return storage


def _make_test_client(
    key_store: "KeyStore | None" = None,
    backend_name: str = "gist_qdrant",
    mock_storage=None,
) -> TestClient:
    """Return a TestClient with patched lifespan and injected app.state.

    Args:
        key_store: KeyStore instance to inject into app.state, or None for
            backends that disable auth.
        backend_name: The backend name to inject into app.state.
        mock_storage: Optional mock storage; defaults to a generic mock.

    Returns:
        A configured TestClient.
    """
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


# ---------------------------------------------------------------------------
# KeyStore tests
# ---------------------------------------------------------------------------


class TestKeyStore:
    """Unit tests for KeyStore."""

    def test_get_or_create_new_user_returns_hex_key(self, tmp_path):
        """New user gets a 64-character hex API key."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        try:
            key = ks.get_or_create("12345", "testuser")
            assert len(key) == 64
            assert all(c in "0123456789abcdef" for c in key)
        finally:
            ks.close()

    def test_get_or_create_same_user_returns_same_key(self, tmp_path):
        """Calling get_or_create twice for the same user returns the same key."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        try:
            key1 = ks.get_or_create("12345", "testuser")
            key2 = ks.get_or_create("12345", "testuser")
            assert key1 == key2
        finally:
            ks.close()

    def test_get_or_create_different_users_get_different_keys(self, tmp_path):
        """Two different users receive different API keys."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        try:
            key1 = ks.get_or_create("11111", "alice")
            key2 = ks.get_or_create("22222", "bob")
            assert key1 != key2
        finally:
            ks.close()

    def test_validate_valid_key_returns_true(self, tmp_path):
        """validate() returns True for a key that exists in the store."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        try:
            key = ks.get_or_create("12345", "testuser")
            assert ks.validate(key) is True
        finally:
            ks.close()

    def test_validate_unknown_key_returns_false(self, tmp_path):
        """validate() returns False for a key that was never issued."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        try:
            assert ks.validate("a" * 64) is False
        finally:
            ks.close()

    def test_validate_empty_string_returns_false(self, tmp_path):
        """validate() returns False for an empty string."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        try:
            assert ks.validate("") is False
        finally:
            ks.close()


# ---------------------------------------------------------------------------
# verify_github_token tests
# ---------------------------------------------------------------------------


class TestVerifyGithubToken:
    """Unit tests for verify_github_token()."""

    def test_success_returns_id_and_login(self):
        """A 200 response returns a dict with id and login."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 99, "login": "octocat", "email": "x@y.com"}
        mock_response.raise_for_status.return_value = None

        with patch("httpx.get", return_value=mock_response):
            result = verify_github_token("ghp_test_token")

        assert result == {"id": 99, "login": "octocat"}

    def test_401_response_raises_http_status_error(self):
        """A 401 response from GitHub raises httpx.HTTPStatusError."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=mock_response,
        )

        with patch("httpx.get", return_value=mock_response):
            with pytest.raises(httpx.HTTPStatusError):
                verify_github_token("bad_token")

    def test_network_failure_raises_http_error(self):
        """A connection error raises httpx.HTTPError."""
        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(httpx.HTTPError):
                verify_github_token("ghp_any")


# ---------------------------------------------------------------------------
# POST /auth/register endpoint tests
# ---------------------------------------------------------------------------


class TestRegisterEndpoint:
    """Tests for POST /auth/register."""

    def test_valid_token_returns_201_with_api_key(self, tmp_path):
        """Valid GitHub token returns 201 with api_key and github_login."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        client = _make_test_client(key_store=ks, backend_name="gist_qdrant")

        with patch("lore.server.auth.verify_github_token", return_value={"id": 42, "login": "octocat"}):
            resp = client.post("/auth/register", json={"github_token": "ghp_valid"})

        assert resp.status_code == 201
        data = resp.json()
        assert "api_key" in data
        assert len(data["api_key"]) == 64
        assert data["github_login"] == "octocat"
        ks.close()

    def test_invalid_github_token_returns_401(self, tmp_path):
        """Invalid GitHub token returns 401."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        client = _make_test_client(key_store=ks, backend_name="gist_qdrant")

        mock_response = MagicMock(spec=httpx.Response)
        error = httpx.HTTPStatusError("401", request=MagicMock(), response=mock_response)
        with patch("lore.server.auth.verify_github_token", side_effect=error):
            resp = client.post("/auth/register", json={"github_token": "bad"})

        assert resp.status_code == 401
        ks.close()

    def test_github_api_down_returns_502(self, tmp_path):
        """GitHub API unreachable returns 502."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        client = _make_test_client(key_store=ks, backend_name="gist_qdrant")

        with patch("lore.server.auth.verify_github_token", side_effect=httpx.ConnectError("down")):
            resp = client.post("/auth/register", json={"github_token": "ghp_any"})

        assert resp.status_code == 502
        ks.close()

    def test_same_user_twice_returns_same_api_key(self, tmp_path):
        """Registering the same GitHub user twice returns the same API key."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        client = _make_test_client(key_store=ks, backend_name="gist_qdrant")

        with patch("lore.server.auth.verify_github_token", return_value={"id": 42, "login": "octocat"}):
            resp1 = client.post("/auth/register", json={"github_token": "ghp_valid"})
            resp2 = client.post("/auth/register", json={"github_token": "ghp_valid"})

        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert resp1.json()["api_key"] == resp2.json()["api_key"]
        ks.close()

    def test_sqlite_qdrant_backend_returns_404(self, tmp_path):
        """POST /auth/register returns 404 for sqlite_qdrant backend."""
        client = _make_test_client(key_store=None, backend_name="sqlite_qdrant")

        resp = client.post("/auth/register", json={"github_token": "ghp_any"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /v1/links auth tests
# ---------------------------------------------------------------------------


class TestLinkConceptsAuth:
    """Auth enforcement on POST /v1/links."""

    def _valid_body(self) -> dict:
        """Return a minimal valid link request body."""
        return {
            "from_id": "concept-a",
            "to_id": "concept-b",
            "rel": "related",
            "label": "Test link",
        }

    def test_gist_qdrant_no_auth_returns_401(self, tmp_path):
        """POST /v1/links without auth header returns 401 on gist_qdrant."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        client = _make_test_client(key_store=ks, backend_name="gist_qdrant")

        resp = client.post("/v1/links", json=self._valid_body())
        assert resp.status_code == 401
        ks.close()


# ---------------------------------------------------------------------------
# POST /v1/concepts auth tests
# ---------------------------------------------------------------------------


class TestSubmitConceptAuth:
    """Auth enforcement on POST /v1/concepts."""

    def _valid_concept_body(self) -> dict:
        """Return a minimal valid concept request body."""
        return {
            "name": "Test Concept",
            "type": "pattern",
            "content": "Some content here.",
            "when_to_use": "Use when testing auth.",
            "tags": [],
        }

    def test_gist_qdrant_no_auth_returns_401(self, tmp_path):
        """POST /v1/concepts without auth header returns 401 on gist_qdrant."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        client = _make_test_client(key_store=ks, backend_name="gist_qdrant")

        resp = client.post("/v1/concepts", json=self._valid_concept_body())
        assert resp.status_code == 401
        ks.close()

    def test_gist_qdrant_invalid_key_returns_401(self, tmp_path):
        """POST /v1/concepts with an invalid key returns 401 on gist_qdrant."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        client = _make_test_client(key_store=ks, backend_name="gist_qdrant")

        resp = client.post(
            "/v1/concepts",
            json=self._valid_concept_body(),
            headers={"Authorization": "Bearer invalidkey123"},
        )
        assert resp.status_code == 401
        ks.close()

    def test_gist_qdrant_valid_key_passes_through(self, tmp_path):
        """POST /v1/concepts with a valid key is not rejected with 401."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        api_key = ks.get_or_create("42", "testuser")

        mock_storage = _make_mock_storage("gist_qdrant")
        # Return a clean result without _qdrant_failed to get 201.
        mock_storage.upsert_concept.return_value = {"concept_id": "abc-123", "name": "Test Concept"}

        client = _make_test_client(key_store=ks, backend_name="gist_qdrant", mock_storage=mock_storage)

        resp = client.post(
            "/v1/concepts",
            json=self._valid_concept_body(),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        # Should not be 401 — may be 201, 503, etc.
        assert resp.status_code != 401
        ks.close()

    def test_non_bearer_scheme_returns_401(self, tmp_path):
        """POST /v1/concepts with a non-Bearer auth scheme returns 401.

        The ``_require_api_key`` dependency checks ``credentials.scheme == "Bearer"``
        and must reject Basic/Token/etc. with 401, not just missing headers.
        """
        ks = KeyStore(db_path=tmp_path / "keys.db")
        api_key = ks.get_or_create("42", "testuser")
        client = _make_test_client(key_store=ks, backend_name="gist_qdrant")

        resp = client.post(
            "/v1/concepts",
            json=self._valid_concept_body(),
            headers={"Authorization": f"Basic {api_key}"},
        )
        assert resp.status_code == 401
        ks.close()

    def test_sqlite_qdrant_no_auth_passes_through(self, tmp_path):
        """POST /v1/concepts without auth is allowed on sqlite_qdrant backend."""
        # sqlite_qdrant: key_store is None -> auth disabled
        mock_storage = _make_mock_storage("sqlite_qdrant")
        mock_storage.find_near_duplicate.return_value = None
        mock_storage.upsert_concept.return_value = {"concept_id": "abc-123", "name": "Test Concept"}

        client = _make_test_client(
            key_store=None,
            backend_name="sqlite_qdrant",
            mock_storage=mock_storage,
        )

        resp = client.post("/v1/concepts", json=self._valid_concept_body())
        # Should not be 401
        assert resp.status_code != 401


# ---------------------------------------------------------------------------
# POST /concepts (gist route) auth tests
# ---------------------------------------------------------------------------


class TestGistUpsertAuth:
    """Auth enforcement on POST /concepts (gist route)."""

    def _valid_body(self) -> dict:
        """Return a minimal valid gist upsert request body."""
        return {
            "gist_id": "abc123",
            "name": "Test",
            "type": "pattern",
            "when_to_use": "Use when testing.",
            "gist_updated_at": "2026-07-14T00:00:00Z",
            "tags": [],
        }

    def test_no_auth_returns_401(self, tmp_path):
        """POST /concepts without auth header returns 401 on gist_qdrant."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        client = _make_test_client(key_store=ks, backend_name="gist_qdrant")

        resp = client.post("/concepts", json=self._valid_body())
        assert resp.status_code == 401
        ks.close()

    def test_valid_key_passes_through(self, tmp_path):
        """POST /concepts with a valid key is not rejected with 401."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        api_key = ks.get_or_create("42", "testuser")

        client = _make_test_client(key_store=ks, backend_name="gist_qdrant")

        resp = client.post(
            "/concepts",
            json=self._valid_body(),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code != 401
        ks.close()


# ---------------------------------------------------------------------------
# POST /v1/concepts/{id}/rate auth tests
# ---------------------------------------------------------------------------


class TestRateConceptAuth:
    """Auth enforcement on POST /v1/concepts/{concept_id}/rate."""

    def test_no_auth_returns_401(self, tmp_path):
        """POST /v1/concepts/{id}/rate without auth header returns 401 on gist_qdrant."""
        ks = KeyStore(db_path=tmp_path / "keys.db")
        client = _make_test_client(key_store=ks, backend_name="gist_qdrant")

        resp = client.post(
            "/v1/concepts/test-concept-id/rate",
            json={"outcome": 3},
        )
        assert resp.status_code == 401
        ks.close()


# ---------------------------------------------------------------------------
# BackendRouter._ensure_semantic_api_key tests
# ---------------------------------------------------------------------------


class TestEnsureSemanticApiKey:
    """Tests for BackendRouter._ensure_semantic_api_key."""

    def _make_router(self, semantic_url: "str | None" = "http://localhost:8766"):
        """Return a BackendRouter with the given semantic URL.

        Args:
            semantic_url: Semantic server URL, or None to disable.

        Returns:
            A BackendRouter instance with state set for testing.
        """
        from lore.mcp.router import BackendRouter

        router = BackendRouter(backend="gists", selfhosted_url="http://localhost:8765")
        router._semantic_url = semantic_url
        # Disable disk cache by default in tests (set to None)
        router._semantic_key_cache_path = None
        return router

    def test_no_github_token_returns_none(self):
        """_ensure_semantic_api_key returns None when LORE_GITHUB_TOKEN is not set."""
        router = self._make_router()

        env = {k: v for k, v in os.environ.items() if k != "LORE_GITHUB_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            result = router._ensure_semantic_api_key()

        assert result is None

    def test_no_semantic_url_returns_none(self):
        """_ensure_semantic_api_key returns None when semantic URL is not configured."""
        router = self._make_router(semantic_url=None)

        with patch.dict(os.environ, {"LORE_GITHUB_TOKEN": "ghp_test"}):
            result = router._ensure_semantic_api_key()

        assert result is None

    def test_successful_register_caches_key(self, tmp_path):
        """Successful registration stores the key in-memory and on disk."""
        router = self._make_router()
        cache_path = tmp_path / "semantic-api-key.json"
        router._semantic_key_cache_path = cache_path

        mock_response = MagicMock()
        mock_response.json.return_value = {"api_key": "a" * 64, "github_login": "octocat"}
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response

        with patch.dict(os.environ, {"LORE_GITHUB_TOKEN": "ghp_test"}), \
             patch("lore.mcp.router.httpx.Client", return_value=mock_client):
            result = router._ensure_semantic_api_key()

        assert result == "a" * 64
        assert router._semantic_api_key == "a" * 64
        # Cache file should be written
        assert cache_path.exists()
        cached = json.loads(cache_path.read_text())
        assert cached["api_key"] == "a" * 64

    def test_cache_file_present_no_http_call(self, tmp_path):
        """When cache file exists, no HTTP call is made."""
        router = self._make_router()
        cache_path = tmp_path / "semantic-api-key.json"
        cache_path.write_text(json.dumps({"api_key": "b" * 64}))
        router._semantic_key_cache_path = cache_path

        with patch.dict(os.environ, {"LORE_GITHUB_TOKEN": "ghp_test"}), \
             patch("lore.mcp.router.httpx.Client") as mock_client_cls:
            result = router._ensure_semantic_api_key()

        assert result == "b" * 64
        mock_client_cls.assert_not_called()

    def test_registration_failure_returns_none(self):
        """When the HTTP call to /auth/register raises, _ensure_semantic_api_key returns None.

        Covers the ``except Exception`` handler in the register block that swallows
        transport errors and returns None so callers can continue without a key.
        """
        router = self._make_router()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "503 Service Unavailable",
            request=MagicMock(),
            response=MagicMock(status_code=503),
        )

        with patch.dict(os.environ, {"LORE_GITHUB_TOKEN": "ghp_test"}), \
             patch("lore.mcp.router.httpx.Client", return_value=mock_client):
            result = router._ensure_semantic_api_key()

        assert result is None

    def test_in_memory_cache_hit_calls_http_once(self):
        """Second call to _ensure_semantic_api_key uses in-memory cache — no second HTTP call."""
        router = self._make_router()

        mock_response = MagicMock()
        mock_response.json.return_value = {"api_key": "c" * 64, "github_login": "octocat"}
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response

        with patch.dict(os.environ, {"LORE_GITHUB_TOKEN": "ghp_test"}), \
             patch("lore.mcp.router.httpx.Client", return_value=mock_client) as mock_client_cls:
            result1 = router._ensure_semantic_api_key()
            result2 = router._ensure_semantic_api_key()

        assert result1 == "c" * 64
        assert result2 == "c" * 64
        # httpx.Client should have been instantiated exactly once — second call hits in-memory cache.
        assert mock_client_cls.call_count == 1
