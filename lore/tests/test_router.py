"""Tests for lore.mcp.router.BackendRouter (LORE-011 / LORE-012).

Strategy
--------
- Selfhosted backend: the httpx.Client context manager is mocked via
  ``patch("lore.mcp.router.BackendRouter._client")`` so no real HTTP calls occur.
- Gists backend: ``gists_backend`` module functions are patched at the router's
  import location (``lore.mcp.router.gists_backend.*``).
- GistsClient lazy-init is verified by patching ``lore.mcp.router.GistsClient``
  and asserting it is NOT instantiated when the router is constructed.
- Unknown backend: ValueError is raised by every method when backend is unknown.

Test coverage areas
-------------------
selfhosted backend
    - submit_concept posts to /v1/concepts
    - get_concept calls GET /v1/concepts/{id}
    - search_concepts posts to /v1/concepts/search with correct payload
    - link_concepts posts to /v1/links
    - rate_concept posts to /v1/concepts/{id}/rate
    - submit_concept 409 returns body
    - submit_concept 422 raises ValueError
    - submit_concept 500 raises RuntimeError

gists backend
    - submit_concept delegates to gists_backend.submit_concept
    - get_concept delegates to gists_backend.get_concept
    - search_concepts delegates to gists_backend.search_concepts (LORE-012)
    - link_concepts delegates to gists_backend.link_concepts
    - rate_concept delegates to gists_backend.rate_concept (LORE-014)
    - GistsClient is NOT instantiated at BackendRouter construction time

unknown backend
    - ValueError raised on every method
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from lore.mcp.router import BackendRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_httpx_response(status_code: int, body: Any) -> MagicMock:
    """Return a MagicMock behaving like an httpx.Response."""
    mock = MagicMock(spec=httpx.Response)
    mock.status_code = status_code
    mock.is_error = status_code >= 400
    mock.json.return_value = body
    mock.text = str(body)
    return mock


def _mock_httpx_client(response: MagicMock) -> MagicMock:
    """Return a mock that acts as both a context manager and an HTTP client."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post.return_value = response
    client.get.return_value = response
    return client


def _selfhosted_router() -> BackendRouter:
    """Return a BackendRouter configured for the selfhosted backend."""
    return BackendRouter(backend="selfhosted", selfhosted_url="http://localhost:8765")


def _gists_router() -> BackendRouter:
    """Return a BackendRouter configured for the gists backend."""
    return BackendRouter(backend="gists", selfhosted_url="http://localhost:8765")


def _unknown_router() -> BackendRouter:
    """Return a BackendRouter with an unknown backend value."""
    return BackendRouter(backend="unknown", selfhosted_url="http://localhost:8765")


# ---------------------------------------------------------------------------
# Selfhosted backend
# ---------------------------------------------------------------------------


class TestSelfhostedBackend:
    """Tests for BackendRouter routing to the selfhosted FastAPI service."""

    def test_submit_concept_posts_to_v1_concepts(self):
        """submit_concept POSTs to /v1/concepts."""
        response = _make_httpx_response(201, {"concept_id": "abc", "name": "X"})
        mock_client = _mock_httpx_client(response)
        router = _selfhosted_router()

        with patch.object(router, "_client", return_value=mock_client):
            router.submit_concept(
                name="X",
                type="pattern",
                content="c",
                when_to_use="w",
                tags=["t"],
            )

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/v1/concepts"

    def test_get_concept_calls_get_on_correct_url(self):
        """get_concept calls GET /v1/concepts/{concept_id}."""
        cid = str(uuid.uuid4())
        response = _make_httpx_response(200, {"concept_id": cid, "links": []})
        mock_client = _mock_httpx_client(response)
        router = _selfhosted_router()

        with patch.object(router, "_client", return_value=mock_client):
            router.get_concept(concept_id=cid)

        mock_client.get.assert_called_once_with(f"/v1/concepts/{cid}")

    def test_search_concepts_posts_to_v1_concepts_search(self):
        """search_concepts POSTs to /v1/concepts/search."""
        response = _make_httpx_response(200, {"results": []})
        mock_client = _mock_httpx_client(response)
        router = _selfhosted_router()

        with patch.object(router, "_client", return_value=mock_client):
            router.search_concepts(problem="how to do X")

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/v1/concepts/search"

    def test_search_concepts_payload_includes_problem(self):
        """search_concepts payload includes the problem field."""
        response = _make_httpx_response(200, {"results": []})
        mock_client = _mock_httpx_client(response)
        router = _selfhosted_router()

        with patch.object(router, "_client", return_value=mock_client):
            router.search_concepts(problem="my problem")

        payload = mock_client.post.call_args[1]["json"]
        assert payload["problem"] == "my problem"

    def test_search_concepts_session_id_header(self):
        """search_concepts includes X-Session-ID header when session_id provided."""
        response = _make_httpx_response(200, {"results": []})
        mock_client = _mock_httpx_client(response)
        router = _selfhosted_router()

        with patch.object(router, "_client", return_value=mock_client):
            router.search_concepts(problem="test", session_id="sess-abc")

        headers = mock_client.post.call_args[1]["headers"]
        assert headers.get("X-Session-ID") == "sess-abc"

    def test_link_concepts_posts_to_v1_links(self):
        """link_concepts POSTs to /v1/links."""
        response = _make_httpx_response(201, {"link_id": "link-xyz"})
        mock_client = _mock_httpx_client(response)
        router = _selfhosted_router()

        with patch.object(router, "_client", return_value=mock_client):
            router.link_concepts(
                from_id="a", to_id="b", rel="uses", label="depends on"
            )

        mock_client.post.assert_called_once()
        assert mock_client.post.call_args[0][0] == "/v1/links"

    def test_rate_concept_posts_to_rate_endpoint(self):
        """rate_concept POSTs to /v1/concepts/{id}/rate."""
        cid = str(uuid.uuid4())
        response = _make_httpx_response(200, {"avg_rating": 4.0})
        mock_client = _mock_httpx_client(response)
        router = _selfhosted_router()

        with patch.object(router, "_client", return_value=mock_client):
            router.rate_concept(concept_id=cid, outcome=4, session_id="s")

        mock_client.post.assert_called_once()
        assert f"/v1/concepts/{cid}/rate" in mock_client.post.call_args[0][0]

    def test_submit_concept_409_returns_body(self):
        """submit_concept returns the body dict on a 409 (semantic duplicate)."""
        body = {
            "error": "semantic_duplicate",
            "existing_concept_id": "old-id",
            "similarity": 0.95,
        }
        response = _make_httpx_response(409, body)
        mock_client = _mock_httpx_client(response)
        router = _selfhosted_router()

        with patch.object(router, "_client", return_value=mock_client):
            result = router.submit_concept(
                name="X", type="pattern", content="c", when_to_use="w", tags=[]
            )

        assert result["error"] == "semantic_duplicate"
        assert result["existing_concept_id"] == "old-id"

    def test_submit_concept_422_raises_value_error(self):
        """submit_concept raises ValueError on a 422 backend scanner rejection."""
        matches = [{"field": "content", "reason": "blocked"}]
        response = _make_httpx_response(
            422, {"error": "Content blocked by scanner", "matches": matches}
        )
        mock_client = _mock_httpx_client(response)
        router = _selfhosted_router()

        with patch.object(router, "_client", return_value=mock_client):
            with pytest.raises(ValueError, match="backend scanner"):
                router.submit_concept(
                    name="X", type="pattern", content="c", when_to_use="w", tags=[]
                )

    def test_submit_concept_500_raises_runtime_error(self):
        """submit_concept raises RuntimeError on a 5xx backend error."""
        response = _make_httpx_response(500, {"error": "internal server error"})
        mock_client = _mock_httpx_client(response)
        router = _selfhosted_router()

        with patch.object(router, "_client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="500"):
                router.submit_concept(
                    name="X", type="pattern", content="c", when_to_use="w", tags=[]
                )


# ---------------------------------------------------------------------------
# Gists backend
# ---------------------------------------------------------------------------


class TestGistsBackend:
    """Tests for BackendRouter routing to the GitHub Gists backend."""

    def test_submit_concept_delegates_to_gists_backend(self):
        """submit_concept calls gists_backend.submit_concept."""
        router = _gists_router()
        expected = {"concept_id": "gist-abc", "name": "X", "source_url": "https://..."}

        with patch("lore.mcp.router.gists_backend.submit_concept", return_value=expected) as mock_fn, \
             patch("lore.mcp.router.GistsClient"):
            result = router.submit_concept(
                name="X", type="pattern", content="c", when_to_use="w", tags=["t"]
            )

        mock_fn.assert_called_once()
        assert result is expected

    def test_submit_concept_passes_all_args(self):
        """submit_concept forwards all keyword arguments to gists_backend.submit_concept."""
        router = _gists_router()

        with patch("lore.mcp.router.gists_backend.submit_concept", return_value={}) as mock_fn, \
             patch("lore.mcp.router.GistsClient"):
            router.submit_concept(
                name="My Concept",
                type="tool",
                content="# Content",
                when_to_use="Use this.",
                tags=["t1", "t2"],
                language="python",
                dont_use_when="Not for X.",
                source_url="https://example.com",
                links=[{"gist_id": "other", "rel": "uses"}],
            )

        _, kwargs = mock_fn.call_args
        assert kwargs["name"] == "My Concept"
        assert kwargs["type"] == "tool"
        assert kwargs["language"] == "python"
        assert kwargs["dont_use_when"] == "Not for X."
        assert kwargs["tags"] == ["t1", "t2"]

    def test_get_concept_delegates_to_gists_backend(self):
        """get_concept calls gists_backend.get_concept."""
        router = _gists_router()
        expected = {"concept_id": "gist-abc", "name": "X"}

        with patch("lore.mcp.router.gists_backend.get_concept", return_value=expected) as mock_fn, \
             patch("lore.mcp.router.GistsClient"):
            result = router.get_concept(concept_id="gist-abc")

        mock_fn.assert_called_once()
        assert result is expected

    def test_get_concept_passes_concept_id(self):
        """get_concept passes the concept_id to gists_backend.get_concept."""
        router = _gists_router()

        with patch("lore.mcp.router.gists_backend.get_concept", return_value={}) as mock_fn, \
             patch("lore.mcp.router.GistsClient"):
            router.get_concept(concept_id="target-gist-id")

        # gists_backend.get_concept is called with (client, concept_id) positionally.
        args, _ = mock_fn.call_args
        assert args[1] == "target-gist-id"

    def test_search_concepts_delegates_to_gists_backend(self):
        """search_concepts delegates to gists_backend.search_concepts (LORE-012)."""
        router = _gists_router()
        expected = {"results": [{"concept_id": "gist-abc", "name": "WAL Mode"}]}

        with patch("lore.mcp.router.gists_backend.search_concepts", return_value=expected) as mock_fn, \
             patch("lore.mcp.router.GistsClient"):
            result = router.search_concepts(problem="sqlite concurrency")

        mock_fn.assert_called_once()
        assert result is expected

    def test_search_concepts_passes_all_args_to_gists_backend(self):
        """search_concepts forwards problem, type, language, limit, min_rating to the gists backend."""
        router = _gists_router()

        with patch("lore.mcp.router.gists_backend.search_concepts", return_value={"results": []}) as mock_fn, \
             patch("lore.mcp.router.GistsClient"):
            router.search_concepts(
                problem="my problem",
                type="pattern",
                language="python",
                limit=5,
                min_rating=3.0,
            )

        _, kwargs = mock_fn.call_args
        assert kwargs["type"] == "pattern"
        assert kwargs["language"] == "python"
        assert kwargs["limit"] == 5
        assert kwargs["min_rating"] == pytest.approx(3.0)

    def test_link_concepts_delegates_to_gists_backend(self):
        """link_concepts calls gists_backend.link_concepts (no longer raises NotImplementedError)."""
        router = _gists_router()
        expected = {"link_id": "a:b:uses", "status": "created"}

        with patch("lore.mcp.router.gists_backend.link_concepts", return_value=expected) as mock_fn, \
             patch("lore.mcp.router.GistsClient"):
            result = router.link_concepts(from_id="a", to_id="b", rel="uses", label="l")

        mock_fn.assert_called_once()
        assert result is expected

    def test_rate_concept_delegates_to_gists_backend(self):
        """rate_concept delegates to gists_backend.rate_concept (no longer raises NotImplementedError)."""
        router = _gists_router()
        expected = {"status": "created", "concept_id": "gist-xyz"}

        with patch("lore.mcp.router.gists_backend.rate_concept", return_value=expected) as mock_fn, \
             patch("lore.mcp.router.GistsClient"):
            result = router.rate_concept(concept_id="gist-xyz", outcome=4, session_id="s")

        mock_fn.assert_called_once()
        assert result is expected

    def test_rate_concept_passes_all_args_to_gists_backend(self):
        """rate_concept forwards concept_id, outcome, session_id, hours_saved, notes."""
        router = _gists_router()

        with patch("lore.mcp.router.gists_backend.rate_concept", return_value={}) as mock_fn, \
             patch("lore.mcp.router.GistsClient"):
            router.rate_concept(
                concept_id="gist-xyz",
                outcome=5,
                session_id="session-001",
                hours_saved=2.5,
                notes="great concept",
            )

        args, kwargs = mock_fn.call_args
        # args[0] is the client, args[1] is concept_id, args[2] is outcome, args[3] is session_id
        assert args[1] == "gist-xyz"
        assert args[2] == 5
        assert args[3] == "session-001"
        assert kwargs["hours_saved"] == pytest.approx(2.5)
        assert kwargs["notes"] == "great concept"

    def test_gists_client_is_not_instantiated_at_construction(self):
        """GistsClient must NOT be instantiated when BackendRouter is constructed."""
        with patch("lore.mcp.router.GistsClient") as MockGistsClient:
            BackendRouter(backend="gists", selfhosted_url="http://localhost:8765")

        MockGistsClient.assert_not_called()

    def test_gists_client_lazy_init_on_first_use(self):
        """GistsClient is instantiated on first use, not at construction."""
        with patch("lore.mcp.router.GistsClient") as MockGistsClient, \
             patch("lore.mcp.router.gists_backend.get_concept", return_value={}):
            MockGistsClient.return_value = MagicMock()
            router = BackendRouter(backend="gists", selfhosted_url="http://localhost:8765")

            MockGistsClient.assert_not_called()

            router.get_concept(concept_id="some-gist")

            MockGistsClient.assert_called_once()

    def test_gists_client_reused_across_calls(self):
        """GistsClient is only instantiated once across multiple calls."""
        with patch("lore.mcp.router.GistsClient") as MockGistsClient, \
             patch("lore.mcp.router.gists_backend.get_concept", return_value={}):
            MockGistsClient.return_value = MagicMock()
            router = BackendRouter(backend="gists", selfhosted_url="http://localhost:8765")

            router.get_concept(concept_id="gist-1")
            router.get_concept(concept_id="gist-2")

            assert MockGistsClient.call_count == 1


# ---------------------------------------------------------------------------
# Unknown backend
# ---------------------------------------------------------------------------


class TestUnknownBackend:
    """ValueError is raised for every method when backend is not recognised."""

    def test_search_concepts_raises_value_error(self):
        router = _unknown_router()
        with pytest.raises(ValueError, match="unknown"):
            router.search_concepts(problem="test")

    def test_get_concept_raises_value_error(self):
        router = _unknown_router()
        with pytest.raises(ValueError, match="unknown"):
            router.get_concept(concept_id="x")

    def test_submit_concept_raises_value_error(self):
        router = _unknown_router()
        with pytest.raises(ValueError, match="unknown"):
            router.submit_concept(
                name="X", type="pattern", content="c", when_to_use="w", tags=[]
            )

    def test_link_concepts_raises_value_error(self):
        router = _unknown_router()
        with pytest.raises(ValueError, match="unknown"):
            router.link_concepts(from_id="a", to_id="b", rel="uses", label="l")

    def test_rate_concept_raises_value_error(self):
        router = _unknown_router()
        with pytest.raises(ValueError, match="unknown"):
            router.rate_concept(concept_id="x", outcome=3, session_id="s")
