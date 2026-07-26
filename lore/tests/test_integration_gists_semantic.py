"""Integration tests — gists backend + semantic search server (Setup 1).

Verifies the full wiring:
- GitHub Gists API mocked via ``responses`` (mocks the ``requests`` Session).
- Semantic server is a **real** uvicorn-served FastAPI app backed by the real
  Qdrant Docker service (localhost:6333).  No ``respx`` HTTP mocking.

Tests that only need GitHub mocking (submit, env wiring) have no Qdrant
dependency.  Tests that exercise the semantic routing use the real server and
are skipped automatically when Qdrant is not running.
"""

from __future__ import annotations

import importlib
import json
import os
import threading
import time
from unittest.mock import patch

import httpx
import pytest
import responses as responses_lib

from lore.mcp.router import BackendRouter


# ---------------------------------------------------------------------------
# Qdrant availability guard (mirrors test_integration_selfhosted.py)
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

# Port used for the real semantic server fixture.
_SEMANTIC_PORT = 18766


# ---------------------------------------------------------------------------
# Session-scoped fixture: real semantic server backed by real Qdrant
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def semantic_server_url():
    """Start a real uvicorn-served semantic server (gist_qdrant backend).

    Uses a fresh app instance via importlib.reload so this uvicorn server does
    not share state with the TestClient-based selfhosted integration tests (which
    patch the module-level ``app`` singleton's lifespan and inject app.state
    directly).

    Yields the base URL (e.g. ``"http://127.0.0.1:18766"``).

    The server runs as a daemon thread and is stopped after the session.
    """
    import uvicorn

    # Save originals so we can restore them after the session — prevents env
    # pollution from bleeding into subsequent test files.
    _saved_env: dict[str, str | None] = {
        k: os.environ.get(k)
        for k in ("LORE_STORAGE_BACKEND", "QDRANT_HOST", "QDRANT_PORT",
                  "LORE_WATCH_INTERVAL")
    }

    # Set env before importing / reloading the app so the lifespan picks them up.
    os.environ["LORE_STORAGE_BACKEND"] = "gist_qdrant"
    os.environ.setdefault("QDRANT_HOST", "localhost")
    os.environ.setdefault("QDRANT_PORT", "6333")
    # Intentionally do NOT set LORE_GITHUB_TOKEN here — the watcher logs a
    # warning and skips bootstrap gracefully when the token is absent, so the
    # server still starts and passes /health.  Setting the token globally would
    # bleed into other test files (e.g. test_ratings.py) and cause assertion
    # failures there.
    # Use an extremely long watcher interval so polling doesn't fire during tests.
    os.environ["LORE_WATCH_INTERVAL"] = "999999"

    # Reload to get a fresh FastAPI app instance that has not had its lifespan
    # patched or its app.state monkey-patched by the selfhosted integration tests.
    import lore.server.api as _api_mod
    importlib.reload(_api_mod)
    fresh_app = _api_mod.create_app()

    config = uvicorn.Config(
        fresh_app,
        host="127.0.0.1",
        port=_SEMANTIC_PORT,
        log_level="error",
    )
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()

    base_url = f"http://127.0.0.1:{_SEMANTIC_PORT}"

    # Wait up to 30 s for the server to respond on /health (gist_qdrant route).
    for _ in range(60):
        try:
            r = httpx.get(f"{base_url}/health", timeout=1.0)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        server.should_exit = True
        t.join(timeout=5)
        raise RuntimeError(
            f"Semantic server did not start on port {_SEMANTIC_PORT} in time"
        )

    yield base_url

    server.should_exit = True
    t.join(timeout=5)

    # Restore original environment to avoid bleeding into other test files.
    for key, original_value in _saved_env.items():
        if original_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original_value


# ---------------------------------------------------------------------------
# Helper: register with the running semantic server and return an API key
# ---------------------------------------------------------------------------


def _register_and_get_api_key(base_url: str) -> str:
    """POST /auth/register with a mocked GitHub user and return the API key.

    ``verify_github_token`` in ``lore.server.auth`` uses ``httpx.get`` to call
    the GitHub REST API.  We patch that function at the module level so the
    uvicorn server thread's call is intercepted and returns a fake successful
    user response, issuing a real API key without a live GitHub token.

    Args:
        base_url: Base URL of the running semantic server.

    Returns:
        The API key string issued by the server.
    """
    import lore.server.auth as _auth_mod
    from unittest.mock import MagicMock

    # Build a mock that quacks like httpx.Response — raise_for_status is a no-op
    # and .json() returns the fake user dict.
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock(return_value=None)
    mock_resp.json.return_value = _GITHUB_USER

    with patch.object(_auth_mod.httpx, "get", return_value=mock_resp):
        r = httpx.post(
            f"{base_url}/auth/register",
            json={"github_token": "fake-token-for-ci"},
            timeout=10.0,
        )
    r.raise_for_status()
    return r.json()["api_key"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


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


@_skip_if_no_qdrant
def test_search_uses_semantic_url(monkeypatch, semantic_server_url):
    """search_concepts routes to semantic server when LORE_SEMANTIC_URL is set.

    Pre-populates Qdrant via a real HTTP POST to the running semantic server,
    then calls router.search_concepts and verifies the result comes back from
    the semantic server (not the GitHub fallback).

    Verifies:
    - Result has ``results`` key.
    - GitHub /gists endpoint was NOT called (no fallback).
    """
    monkeypatch.setenv("LORE_BACKEND", "gists")
    monkeypatch.setenv("LORE_GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("LORE_SEMANTIC_URL", semantic_server_url)
    # Use a very short timeout so we don't wait long on any accidental failure.
    monkeypatch.setenv("LORE_SEMANTIC_TIMEOUT", "10.0")

    # --- Pre-populate: register to get an API key, then upsert a concept. ---
    api_key = _register_and_get_api_key(semantic_server_url)

    concept_payload = {
        "gist_id": "test-gist-sqlite-wal",
        "name": "SQLite WAL Mode",
        "type": "pattern",
        "when_to_use": "Use WAL mode for concurrent SQLite reads and writes.",
        "gist_updated_at": "2024-01-01T00:00:00Z",
        "tags": ["sqlite", "concurrency"],
        "force": True,
    }
    upsert_resp = httpx.post(
        f"{semantic_server_url}/concepts",
        json=concept_payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10.0,
    )
    assert upsert_resp.status_code == 200, (
        f"Pre-populate failed {upsert_resp.status_code}: {upsert_resp.text}"
    )

    # --- Search: BackendRouter must route to semantic server. ---
    # Use assert_all_requests_are_fired=False so unmatched fallback mocks don't
    # cause assertion failures — we want to assert they were NOT called.
    with responses_lib.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        # Register GitHub fallback mocks — these must NOT be called.
        rsps.add(
            responses_lib.GET,
            "https://api.github.com/user",
            json=_GITHUB_USER,
            status=200,
        )
        rsps.add(
            responses_lib.GET,
            "https://api.github.com/gists",
            json=[],
            status=200,
        )
        # Note: ``responses`` only intercepts ``requests`` library calls.
        # BackendRouter._semantic_search uses ``httpx``, so the real HTTP
        # call to the uvicorn semantic server goes through unimpeded.

        router = BackendRouter(backend="gists", selfhosted_url="")
        result = router.search_concepts("sqlite concurrency")

        # GitHub /gists must NOT have been called (semantic server handled it).
        github_gist_calls = [
            c for c in rsps.calls
            if "api.github.com/gists" in c.request.url
            and "user" not in c.request.url
        ]
        assert len(github_gist_calls) == 0, (
            f"GitHub /gists was called {len(github_gist_calls)} times — "
            "fallback should not have triggered"
        )

    assert "results" in result, f"Missing 'results' key in response: {result}"

    # Verify no fallback flag was set (fallback=True only set on semantic failure).
    assert result.get("fallback") is not True, (
        "fallback=True set — semantic server was not reached successfully"
    )


@_skip_if_no_qdrant
@responses_lib.activate
def test_search_falls_back_to_gists_when_semantic_unreachable(monkeypatch):
    """search_concepts falls back to gists when semantic server is unreachable.

    Points LORE_SEMANTIC_URL at port 19999 (nothing listening) so the real
    httpx call gets a real connection-refused error, exhausts retries, and
    falls back to the GitHub Gists list endpoint.

    Verifies:
    - No exception is raised by the router.
    - GitHub /gists endpoint was called (fallback path taken).
    - Result has ``results`` key.
    """
    monkeypatch.setenv("LORE_BACKEND", "gists")
    monkeypatch.setenv("LORE_GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("LORE_SEMANTIC_URL", "http://127.0.0.1:19999")
    # Short timeout so the connection-refused is detected quickly.
    monkeypatch.setenv("LORE_SEMANTIC_TIMEOUT", "1.0")

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

    router = BackendRouter(backend="gists", selfhosted_url="")
    result = router.search_concepts("sqlite")

    # No exception — fallback succeeded.
    assert "results" in result, f"Missing 'results' key in fallback response: {result}"

    # GitHub /gists must have been called (fallback path taken).
    gists_calls = [
        c for c in responses_lib.calls
        if "api.github.com/gists" in c.request.url
        and "user" not in c.request.url
    ]
    assert len(gists_calls) >= 1, (
        "GitHub /gists was not called — fallback path was not taken"
    )


@_skip_if_no_qdrant
def test_rate_concept_via_semantic_raises_when_unreachable(monkeypatch):
    """rate_concept raises RuntimeError when semantic server POST /ratings fails.

    Points LORE_SEMANTIC_URL at port 19999 (nothing listening) so the real
    httpx POST to /ratings gets a connection error, which the router wraps as
    RuntimeError.

    Verifies:
    - ``RuntimeError`` is raised (no silent swallow).
    """
    monkeypatch.setenv("LORE_BACKEND", "gists")
    monkeypatch.setenv("LORE_GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("LORE_SEMANTIC_URL", "http://127.0.0.1:19999")
    monkeypatch.setenv("LORE_SEMANTIC_TIMEOUT", "1.0")

    router = BackendRouter(backend="gists", selfhosted_url="")

    # Bypass API key registration so it does not fail first (no server to register with).
    with patch.object(router, "_ensure_semantic_api_key", return_value=None):
        with pytest.raises(RuntimeError):
            router.rate_concept(
                concept_id="gist-abc",
                outcome=4,
                session_id="s1",
            )
