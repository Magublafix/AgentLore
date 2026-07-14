"""Tests for lore.mcp.server (LORE-005).

Strategy
--------
- The selfhosted HTTP service is mocked via ``unittest.mock.patch`` on
  ``lore.mcp.router.BackendRouter._client`` — no real network calls or
  running service required.
- Each MCP tool is called directly (as a plain Python function) since
  FastMCP tools are synchronous callables decorated with ``@mcp.tool``.
- Scanner violations are tested both at the MCP layer (local scan) and
  at the backend boundary (backend 422 responses).
- Invalid backend configuration is tested via the router's ValueError path.

All tests import from ``lore.mcp.server`` after patching the backend env var.
Since the module-level NotImplementedError guard has been removed, LORE_BACKEND
can be any value at import time without raising.
"""

from __future__ import annotations

import importlib
import os
import sys
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_concept_dict(concept_id: str | None = None, **overrides) -> dict:
    """Return a minimal concept dict matching the selfhosted API response shape."""
    base: dict[str, Any] = {
        "concept_id": concept_id or str(uuid.uuid4()),
        "name": "WAL Mode",
        "type": "pattern",
        "content": "Enable WAL mode.",
        "language": "python",
        "when_to_use": "Use for concurrent SQLite writes.",
        "dont_use_when": None,
        "tags": ["sqlite"],
        "source_url": None,
        "author": None,
        "avg_rating": 4.0,
        "usage_count": 3,
        "time_saved_avg_hours": 1.5,
        "created_at": "2024-01-01T00:00:00Z",
        "links": [],
    }
    base.update(overrides)
    return base


def _make_response(status_code: int, body: Any) -> MagicMock:
    """Return a mock httpx.Response."""
    mock = MagicMock(spec=httpx.Response)
    mock.status_code = status_code
    mock.is_error = status_code >= 400
    mock.json.return_value = body
    mock.text = str(body)
    return mock


# ---------------------------------------------------------------------------
# Import helper — reload server with correct env var
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def ensure_selfhosted_backend(monkeypatch):
    """Ensure LORE_BACKEND=selfhosted for the module-level router instance."""
    monkeypatch.setenv("LORE_BACKEND", "selfhosted")
    # Force the router to use the selfhosted backend for all tool calls in
    # this test file, even if the module was loaded with a different env var.
    import lore.mcp.server as _srv
    import lore.mcp.router as _router_mod
    _srv._router._backend = "selfhosted"


# ---------------------------------------------------------------------------
# Import the server tools after env is set
# ---------------------------------------------------------------------------

import lore.mcp.server as server_mod
from lore.mcp.server import (
    search_concepts,
    get_concept,
    submit_concept,
    link_concepts,
    rate_concept,
)
from lore.mcp.router import DuplicateConceptError


# ---------------------------------------------------------------------------
# Context manager mock for httpx.Client
# ---------------------------------------------------------------------------


def _mock_client(response: MagicMock) -> MagicMock:
    """Return a mock that acts as both a context manager and an HTTP client."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post.return_value = response
    client.get.return_value = response
    return client


# ---------------------------------------------------------------------------
# search_concepts
# ---------------------------------------------------------------------------


class TestSearchConcepts:
    """MCP tool: search_concepts."""

    def test_returns_results(self):
        concept = _make_concept_dict()
        api_response = _make_response(200, {"results": [concept]})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            result = search_concepts(problem="concurrent database writes")

        assert "results" in result
        assert len(result["results"]) == 1
        assert result["results"][0]["concept_id"] == concept["concept_id"]

    def test_no_n_plus_1_fetches(self):
        """search_concepts must make exactly one HTTP call — links are inline, no N+1."""
        linked = _make_concept_dict()
        concept = _make_concept_dict(links=[{"concept_id": linked["concept_id"], "rel": "uses"}])
        api_response = _make_response(200, {"results": [concept]})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            search_concepts(problem="concurrent database writes")

        # Exactly one POST call — no secondary GET calls to fetch linked concepts.
        assert mock_client.post.call_count == 1
        assert mock_client.get.call_count == 0

    def test_passes_type_filter(self):
        api_response = _make_response(200, {"results": []})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            search_concepts(problem="test", type="pattern")

        call_kwargs = mock_client.post.call_args
        payload = call_kwargs[1]["json"]
        assert payload["type"] == "pattern"

    def test_passes_language_filter(self):
        api_response = _make_response(200, {"results": []})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            search_concepts(problem="test", language="python")

        payload = mock_client.post.call_args[1]["json"]
        assert payload["language"] == "python"

    def test_passes_limit(self):
        api_response = _make_response(200, {"results": []})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            search_concepts(problem="test", limit=10)

        payload = mock_client.post.call_args[1]["json"]
        assert payload["limit"] == 10

    def test_passes_session_id_header(self):
        api_response = _make_response(200, {"results": []})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            search_concepts(problem="test", session_id="sess-abc")

        headers = mock_client.post.call_args[1]["headers"]
        assert headers.get("X-Session-ID") == "sess-abc"

    def test_no_session_id_omits_header(self):
        api_response = _make_response(200, {"results": []})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            search_concepts(problem="test")

        headers = mock_client.post.call_args[1]["headers"]
        assert "X-Session-ID" not in headers

    def test_raises_on_backend_error(self):
        api_response = _make_response(500, {"error": "internal"})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="500"):
                search_concepts(problem="test")

    def test_omits_optional_filters_when_none(self):
        api_response = _make_response(200, {"results": []})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            search_concepts(problem="test")

        payload = mock_client.post.call_args[1]["json"]
        assert "type" not in payload
        assert "language" not in payload


# ---------------------------------------------------------------------------
# get_concept
# ---------------------------------------------------------------------------


class TestGetConcept:
    """MCP tool: get_concept."""

    def test_returns_concept(self):
        cid = str(uuid.uuid4())
        concept = _make_concept_dict(concept_id=cid)
        api_response = _make_response(200, concept)
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            result = get_concept(concept_id=cid)

        assert result["concept_id"] == cid
        mock_client.get.assert_called_once_with(f"/v1/concepts/{cid}")

    def test_raises_on_not_found(self):
        cid = str(uuid.uuid4())
        api_response = _make_response(404, {"error": "not found", "concept_id": cid})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="404"):
                get_concept(concept_id=cid)

    def test_raises_on_server_error(self):
        api_response = _make_response(503, {"error": "backend unavailable"})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            with pytest.raises(RuntimeError):
                get_concept(concept_id=str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# submit_concept
# ---------------------------------------------------------------------------


class TestSubmitConcept:
    """MCP tool: submit_concept."""

    _VALID_ARGS = dict(
        name="SQLite WAL Mode",
        type="pattern",
        content="Enable WAL mode for concurrent writes.",
        when_to_use="Use when you need crash-safe concurrent SQLite access.",
        tags=["sqlite", "concurrency"],
        language="python",
    )

    def test_successful_submission(self):
        cid = str(uuid.uuid4())
        api_response = _make_response(201, {"concept_id": cid, "name": "SQLite WAL Mode"})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            result = submit_concept(**self._VALID_ARGS)

        assert result["concept_id"] == cid
        assert result["name"] == "SQLite WAL Mode"

    def test_local_scan_rejects_credential(self):
        """submit_concept raises ValueError when local scan detects a credential."""
        bad_args = {**self._VALID_ARGS, "content": "api_key: supersecretkey12345"}

        with pytest.raises(ValueError, match="scan"):
            submit_concept(**bad_args)

    def test_local_scan_rejects_internal_url(self):
        bad_args = {**self._VALID_ARGS, "when_to_use": "call http://service.internal/v1"}

        with pytest.raises(ValueError, match="scan"):
            submit_concept(**bad_args)

    def test_backend_422_raises_value_error(self):
        """A 422 from the backend is translated to ValueError."""
        matches = [{"field": "content", "reason": "blocked"}]
        api_response = _make_response(
            422,
            {"error": "Content blocked by scanner", "matches": matches}
        )
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            with pytest.raises(ValueError, match="backend scanner"):
                submit_concept(**self._VALID_ARGS)

    def test_passes_optional_fields(self):
        cid = str(uuid.uuid4())
        api_response = _make_response(201, {"concept_id": cid, "name": "X"})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            submit_concept(
                **self._VALID_ARGS,
                dont_use_when="Not for read-heavy workloads",
                source_url="https://sqlite.org/wal.html",
                links=[{"to_id": str(uuid.uuid4()), "rel": "uses", "label": "depends on"}],
            )

        payload = mock_client.post.call_args[1]["json"]
        assert "dont_use_when" in payload
        assert payload["source_url"] == "https://sqlite.org/wal.html"
        assert len(payload["links"]) == 1

    def test_links_default_to_empty_list(self):
        cid = str(uuid.uuid4())
        api_response = _make_response(201, {"concept_id": cid, "name": "X"})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            submit_concept(**self._VALID_ARGS)

        payload = mock_client.post.call_args[1]["json"]
        assert payload["links"] == []

    def test_backend_503_raises_runtime_error(self):
        api_response = _make_response(503, {"error": "Qdrant down", "concept_id": "x"})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="503"):
                submit_concept(**self._VALID_ARGS)

    def test_dont_use_when_none_not_scanned(self):
        """None dont_use_when does not trigger a scan violation."""
        cid = str(uuid.uuid4())
        api_response = _make_response(201, {"concept_id": cid, "name": "X"})
        mock_client = _mock_client(api_response)

        args = {**self._VALID_ARGS}
        args.pop("language", None)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            result = submit_concept(**args, dont_use_when=None)

        assert "concept_id" in result

    def test_network_error_propagates_as_connect_error(self):
        """ConnectError from httpx propagates unchanged — the MCP layer does not swallow it."""
        mock_client = _mock_client(MagicMock())
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            with pytest.raises(httpx.ConnectError):
                submit_concept(**self._VALID_ARGS)

    def test_backend_409_raises_duplicate_concept_error(self):
        """A 409 from the backend (semantic duplicate) raises DuplicateConceptError."""
        body = {"duplicate": True, "similar": [{"id": "abc-123", "title": "Existing", "score": 0.95}]}
        api_response = _make_response(409, body)
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            with pytest.raises(DuplicateConceptError) as exc_info:
                submit_concept(**self._VALID_ARGS)

        assert exc_info.value.similar[0]["id"] == "abc-123"

    def test_local_scan_rejects_credential_in_name(self):
        """Credential pattern in the name field triggers local scan rejection."""
        bad_args = {**self._VALID_ARGS, "name": "api_key: supersecretkey12345"}

        with pytest.raises(ValueError, match="scan"):
            submit_concept(**bad_args)

    def test_local_scan_rejects_internal_url_in_dont_use_when(self):
        """Internal URL in dont_use_when triggers local scan rejection."""
        bad_args = {**self._VALID_ARGS, "dont_use_when": "avoid calling http://service.internal/api"}

        with pytest.raises(ValueError, match="scan"):
            submit_concept(**bad_args)


# ---------------------------------------------------------------------------
# link_concepts
# ---------------------------------------------------------------------------


class TestLinkConcepts:
    """MCP tool: link_concepts."""

    def test_successful_link(self):
        link_id = str(uuid.uuid4())
        api_response = _make_response(201, {"link_id": link_id})
        mock_client = _mock_client(api_response)

        from_id = str(uuid.uuid4())
        to_id = str(uuid.uuid4())

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            result = link_concepts(from_id=from_id, to_id=to_id, rel="uses", label="depends on")

        assert result["link_id"] == link_id

    def test_passes_payload_correctly(self):
        api_response = _make_response(201, {"link_id": "x"})
        mock_client = _mock_client(api_response)

        from_id = str(uuid.uuid4())
        to_id = str(uuid.uuid4())

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            link_concepts(from_id=from_id, to_id=to_id, rel="extends", label="extends it")

        payload = mock_client.post.call_args[1]["json"]
        assert payload["from_id"] == from_id
        assert payload["to_id"] == to_id
        assert payload["rel"] == "extends"
        assert payload["label"] == "extends it"

    def test_raises_on_not_found(self):
        api_response = _make_response(404, {"error": "not found"})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="404"):
                link_concepts(
                    from_id=str(uuid.uuid4()),
                    to_id=str(uuid.uuid4()),
                    rel="uses",
                    label="test",
                )

    def test_raises_on_invalid_rel(self):
        api_response = _make_response(422, {"detail": [{"msg": "Invalid rel"}]})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="422"):
                link_concepts(
                    from_id=str(uuid.uuid4()),
                    to_id=str(uuid.uuid4()),
                    rel="owns",
                    label="bad rel",
                )


# ---------------------------------------------------------------------------
# rate_concept
# ---------------------------------------------------------------------------


class TestRateConcept:
    """MCP tool: rate_concept."""

    def test_successful_rating(self):
        cid = str(uuid.uuid4())
        api_response = _make_response(200, {"avg_rating": 4.0, "time_saved_avg_hours": 2.5})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            result = rate_concept(
                concept_id=cid,
                outcome=4,
                session_id="sess-123",
                hours_saved=2.5,
                notes="Very helpful",
            )

        assert result["avg_rating"] == pytest.approx(4.0)
        assert result["time_saved_avg_hours"] == pytest.approx(2.5)

    def test_correct_endpoint_called(self):
        cid = str(uuid.uuid4())
        api_response = _make_response(200, {"avg_rating": 3.0, "time_saved_avg_hours": None})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            rate_concept(concept_id=cid, outcome=3, session_id="s")

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert f"/v1/concepts/{cid}/rate" in call_args[0][0]

    def test_hours_saved_optional(self):
        cid = str(uuid.uuid4())
        api_response = _make_response(200, {"avg_rating": 2.0, "time_saved_avg_hours": None})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            result = rate_concept(concept_id=cid, outcome=2, session_id="s")

        # Payload should not include hours_saved if not provided
        payload = mock_client.post.call_args[1]["json"]
        assert "hours_saved" not in payload

    def test_notes_optional(self):
        cid = str(uuid.uuid4())
        api_response = _make_response(200, {"avg_rating": 5.0, "time_saved_avg_hours": None})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            rate_concept(concept_id=cid, outcome=5, session_id="s")

        payload = mock_client.post.call_args[1]["json"]
        assert "notes" not in payload

    def test_raises_on_not_found(self):
        cid = str(uuid.uuid4())
        api_response = _make_response(404, {"error": "not found"})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="404"):
                rate_concept(concept_id=cid, outcome=3, session_id="s")

    def test_raises_on_invalid_outcome(self):
        cid = str(uuid.uuid4())
        api_response = _make_response(422, {"detail": [{"msg": "outcome must be between 1 and 5"}]})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="422"):
                rate_concept(concept_id=cid, outcome=99, session_id="s")

    def test_passes_all_fields_when_provided(self):
        cid = str(uuid.uuid4())
        api_response = _make_response(200, {"avg_rating": 5.0, "time_saved_avg_hours": 3.0})
        mock_client = _mock_client(api_response)

        with patch("lore.mcp.router.BackendRouter._client", return_value=mock_client):
            rate_concept(
                concept_id=cid,
                outcome=5,
                session_id="sess-xyz",
                hours_saved=3.0,
                notes="Saved a lot of time",
            )

        payload = mock_client.post.call_args[1]["json"]
        assert payload["outcome"] == 5
        assert payload["session_id"] == "sess-xyz"
        assert payload["hours_saved"] == pytest.approx(3.0)
        assert payload["notes"] == "Saved a lot of time"


# ---------------------------------------------------------------------------
# Invalid backend
# ---------------------------------------------------------------------------


class TestInvalidBackend:
    """Router raises ValueError for unknown backend values."""

    def test_unknown_backend_raises_value_error_on_search(self):
        """Calling search_concepts with an unknown backend raises ValueError."""
        from lore.mcp.router import BackendRouter

        router = BackendRouter(backend="unknown", selfhosted_url="http://localhost:8765")
        with pytest.raises(ValueError, match="unknown"):
            router.search_concepts(problem="test")

    def test_unknown_backend_raises_value_error_on_submit(self):
        """Calling submit_concept with an unknown backend raises ValueError."""
        from lore.mcp.router import BackendRouter

        router = BackendRouter(backend="bogus", selfhosted_url="http://localhost:8765")
        with pytest.raises(ValueError, match="bogus"):
            router.submit_concept(
                name="X",
                type="pattern",
                content="c",
                when_to_use="w",
                tags=[],
            )

    def test_gists_backend_imports_cleanly(self):
        """LORE_BACKEND=gists no longer raises NotImplementedError on import."""
        import lore.mcp.server  # noqa: F401 — should not raise

    def test_selfhosted_backend_does_not_raise(self, monkeypatch):
        """LORE_BACKEND=selfhosted imports cleanly."""
        monkeypatch.setenv("LORE_BACKEND", "selfhosted")
        import lore.mcp.server  # noqa: F401 — should not raise
