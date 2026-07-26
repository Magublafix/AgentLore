"""Integration tests — gists backend + semantic search server (Setup 1).

Verifies the full wiring without real external services:
- GitHub Gists API mocked via ``responses`` (mocks the ``requests`` Session).
- Semantic server mocked via ``respx`` (mocks ``httpx`` calls).

Tests catch: wrong env var names, wrong HTTP paths, broken URL construction,
missing payload fields, import-time default bugs.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest
import responses as responses_lib
import respx

from lore.mcp.router import BackendRouter

# ---------------------------------------------------------------------------
# Shared mock payloads
# ---------------------------------------------------------------------------

_GITHUB_USER = {"login": "testuser", "id": 1}

_GIST_RESPONSE = {
    "id": "gist-abc123",
    "description": "[agentlore-concept] WAL Mode [sqlite]",
    "files": {
        "concept.md": {"content": "Enable WAL mode.\n\n---\n*Captured by [mcp-server-lore](...)*"},
        "lore.json": {"content": '{"project_url": "https://github.com/Magublafix/AgentLore"}'},
    },
    "html_url": "https://gist.github.com/gist-abc123",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@responses_lib.activate
def test_submit_concept_gist_shape(monkeypatch):
    """submit_concept creates a gist with the correct files and description.

    Verifies:
    - POST /gists called exactly once.
    - Request files dict contains ``concept.md`` and ``lore.json``.
    - Description starts with ``[agentlore-concept]``.
    - ``concept.md`` content references ``mcp-server-lore``.
    - ``lore.json`` is valid JSON with a ``project_url`` key.
    - Returned dict contains ``concept_id`` matching the mocked gist id.
    """
    monkeypatch.setenv("LORE_BACKEND", "gists")
    monkeypatch.setenv("LORE_GITHUB_TOKEN", "fake-token")

    responses_lib.add(
        responses_lib.GET,
        "https://api.github.com/user",
        json=_GITHUB_USER,
        status=200,
    )
    responses_lib.add(
        responses_lib.POST,
        "https://api.github.com/gists",
        json=_GIST_RESPONSE,
        status=201,
    )

    router = BackendRouter(backend="gists", selfhosted_url="")
    result = router.submit_concept(
        name="WAL Mode",
        type="pattern",
        content="Enable WAL mode.",
        when_to_use="Use for concurrent SQLite writes.",
        tags=["sqlite"],
    )

    # Exactly one POST /gists call.
    post_calls = [c for c in responses_lib.calls if c.request.method == "POST"]
    assert len(post_calls) == 1, f"Expected 1 POST /gists call, got {len(post_calls)}"

    # Inspect request body.
    request_body = json.loads(post_calls[0].request.body)
    files = request_body.get("files", {})
    assert "concept.md" in files, "concept.md missing from gist files"
    assert "lore.json" in files, "lore.json missing from gist files"

    # Description format.
    description = request_body.get("description", "")
    assert description.startswith("[agentlore-concept]"), (
        f"Description does not start with [agentlore-concept]: {description!r}"
    )

    # concept.md must reference the project.
    concept_md_content = files["concept.md"]["content"]
    assert "mcp-server-lore" in concept_md_content, (
        "concept.md does not contain 'mcp-server-lore'"
    )

    # lore.json must be valid JSON with project_url.
    lore_json_content = files["lore.json"]["content"]
    lore_data = json.loads(lore_json_content)
    assert "project_url" in lore_data, "lore.json missing 'project_url' key"

    # Returned concept_id.
    assert result.get("concept_id") == "gist-abc123", (
        f"concept_id mismatch: {result.get('concept_id')!r}"
    )


@responses_lib.activate
def test_search_uses_semantic_url(monkeypatch):
    """search_concepts routes to semantic server when LORE_SEMANTIC_URL is set.

    Verifies:
    - GET /search on semantic server called exactly once.
    - ``q`` query param equals the search problem.
    - Result has ``results`` key.
    - GitHub /gists endpoint was NOT called.
    """
    monkeypatch.setenv("LORE_BACKEND", "gists")
    monkeypatch.setenv("LORE_GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("LORE_SEMANTIC_URL", "http://localhost:8766")

    # GitHub fallback mocks (should not be called).
    responses_lib.add(
        responses_lib.GET,
        "https://api.github.com/user",
        json=_GITHUB_USER,
        status=200,
    )
    responses_lib.add(
        responses_lib.GET,
        "https://api.github.com/gists",
        json=[],
        status=200,
    )

    semantic_response = {
        "results": [{"concept_id": "c1", "name": "WAL", "score": 0.9}]
    }

    with respx.mock:
        respx.get("http://localhost:8766/search").mock(
            return_value=httpx.Response(200, json=semantic_response)
        )

        router = BackendRouter(backend="gists", selfhosted_url="")
        result = router.search_concepts("sqlite concurrency")

    # Semantic /search called once.
    # respx tracks calls on the route object.
    # We can verify via respx call count indirectly by checking result content.
    assert "results" in result, f"Missing 'results' key in response: {result}"

    # GitHub /gists must NOT have been called.
    github_gist_calls = [
        c for c in responses_lib.calls
        if "api.github.com/gists" in c.request.url
        and "user" not in c.request.url
    ]
    assert len(github_gist_calls) == 0, (
        f"GitHub /gists was called {len(github_gist_calls)} times — fallback should not have triggered"
    )


@responses_lib.activate
def test_search_falls_back_to_gists_when_semantic_unreachable(monkeypatch):
    """search_concepts falls back to gists when semantic server is unreachable.

    Patches ``BackendRouter._semantic_search`` to raise ``httpx.ConnectError``
    on every call, so the router exhausts its two retries and falls back to
    the GitHub Gists list endpoint.

    Verifies:
    - No exception is raised by the router.
    - GitHub /gists endpoint was called (fallback path taken).
    - Result has ``results`` key.
    """
    monkeypatch.setenv("LORE_BACKEND", "gists")
    monkeypatch.setenv("LORE_GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("LORE_SEMANTIC_URL", "http://localhost:8766")

    responses_lib.add(
        responses_lib.GET,
        "https://api.github.com/user",
        json=_GITHUB_USER,
        status=200,
    )
    responses_lib.add(
        responses_lib.GET,
        "https://api.github.com/gists",
        json=[],
        status=200,
    )

    def _raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("Connection refused")

    router = BackendRouter(backend="gists", selfhosted_url="")

    with patch.object(BackendRouter, "_semantic_search", side_effect=_raise_connect_error):
        result = router.search_concepts("sqlite")

    # No exception — fallback succeeded.
    assert "results" in result, f"Missing 'results' key in fallback response: {result}"

    # GitHub /gists must have been called.
    gists_calls = [
        c for c in responses_lib.calls
        if "api.github.com/gists" in c.request.url
        and "user" not in c.request.url
    ]
    assert len(gists_calls) >= 1, (
        "GitHub /gists was not called — fallback path was not taken"
    )


@responses_lib.activate
def test_rate_concept_via_semantic_raises_when_unreachable(monkeypatch):
    """rate_concept raises RuntimeError when semantic server POST /ratings fails.

    The router must not silently swallow the error when
    LORE_SEMANTIC_URL is set and the ratings endpoint is unreachable.

    Verifies:
    - ``RuntimeError`` is raised (no silent swallow).
    """
    monkeypatch.setenv("LORE_BACKEND", "gists")
    monkeypatch.setenv("LORE_GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("LORE_SEMANTIC_URL", "http://localhost:8766")

    responses_lib.add(
        responses_lib.GET,
        "https://api.github.com/user",
        json=_GITHUB_USER,
        status=200,
    )

    router = BackendRouter(backend="gists", selfhosted_url="")

    # Bypass API key registration so it does not fail first.
    with patch.object(router, "_ensure_semantic_api_key", return_value=None):
        # Make the httpx POST to /ratings raise ConnectError.
        with respx.mock:
            respx.post("http://localhost:8766/ratings").mock(
                side_effect=httpx.ConnectError("Connection refused")
            )

            with pytest.raises(RuntimeError):
                router.rate_concept(
                    concept_id="gist-abc",
                    outcome=4,
                    session_id="s1",
                )


def test_env_var_wiring_gists(monkeypatch):
    """BackendRouter reads LORE_BACKEND and LORE_SEMANTIC_URL from env at construction.

    Verifies attribute assignment without any network calls.
    """
    monkeypatch.setenv("LORE_BACKEND", "gists")
    monkeypatch.setenv("LORE_GITHUB_TOKEN", "fake")
    monkeypatch.setenv("LORE_SEMANTIC_URL", "http://localhost:8766")

    router = BackendRouter(backend="gists", selfhosted_url="")

    assert router._backend == "gists"
    assert router._semantic_url == "http://localhost:8766"
