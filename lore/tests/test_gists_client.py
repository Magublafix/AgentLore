"""Tests for lore.mcp.backends.gists_client.

All tests use unittest.mock — no real HTTP calls are made.  The ``client``
fixture builds a GistsClient instance by bypassing ``__init__`` so that the
token-validation round-trip is not required for every test.  The handful of
``test_init_*`` tests do exercise the real constructor path.
"""

from __future__ import annotations

import io
import os
from unittest.mock import MagicMock, call, patch

import pytest

from lore.mcp.backends.gists_client import (
    Comment,
    GistAPIError,
    GistAuthError,
    GistData,
    GistNotFoundError,
    GistRateLimitError,
    GistSummary,
    GistsClient,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_response(
    status_code: int,
    json_body=None,
    headers: dict | None = None,
) -> MagicMock:
    """Return a MagicMock that behaves like a requests.Response.

    Default headers include ``X-RateLimit-Remaining: "50"`` and a far-future
    reset timestamp so tests do not accidentally trigger rate-limit warnings
    unless they explicitly set these headers.

    Args:
        status_code: The HTTP status code.
        json_body: The object returned by ``.json()``.  Defaults to ``{}``.
        headers: Optional header overrides merged on top of the defaults.

    Returns:
        A configured :class:`unittest.mock.MagicMock`.
    """
    default_headers: dict[str, str] = {
        "X-RateLimit-Remaining": "50",
        "X-RateLimit-Reset": "9999999999",
    }
    if headers:
        default_headers.update(headers)

    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_body if json_body is not None else {}
    mock_resp.headers = default_headers
    return mock_resp


# ---------------------------------------------------------------------------
# Fixture — pre-built client that bypasses __init__
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> GistsClient:
    """Build a GistsClient without calling __init__ to avoid needing a live token.

    Each test can then configure ``client._session.request.return_value`` or
    set a ``side_effect`` list to control what responses the client sees.
    """
    c = object.__new__(GistsClient)
    c._base_url = "https://api.github.com"
    c._session = MagicMock()
    c.authenticated_login = "testuser"
    return c


# ---------------------------------------------------------------------------
# __init__ tests — these exercise the real constructor
# ---------------------------------------------------------------------------


def test_init_missing_token():
    """GistAuthError is raised when LORE_GITHUB_TOKEN is absent."""
    env_without_token = {k: v for k, v in os.environ.items() if k != "LORE_GITHUB_TOKEN"}
    with patch.dict("os.environ", env_without_token, clear=True):
        with pytest.raises(GistAuthError, match="LORE_GITHUB_TOKEN"):
            GistsClient()


def test_init_invalid_token():
    """GistAuthError is raised when /user returns 401."""
    user_401 = make_response(401)
    with patch.dict("os.environ", {"LORE_GITHUB_TOKEN": "bad-token"}):
        with patch("requests.Session") as MockSession:
            session_instance = MockSession.return_value
            session_instance.request.return_value = user_401
            with pytest.raises(GistAuthError):
                GistsClient()


def test_init_success():
    """authenticated_login is populated from the /user response on success."""
    user_200 = make_response(200, json_body={"login": "octocat"})
    with patch.dict("os.environ", {"LORE_GITHUB_TOKEN": "ghp_valid"}):
        with patch("requests.Session") as MockSession:
            session_instance = MockSession.return_value
            session_instance.request.return_value = user_200
            c = GistsClient()
    assert c.authenticated_login == "octocat"


# ---------------------------------------------------------------------------
# create_gist
# ---------------------------------------------------------------------------


def test_create_gist_happy_path(client: GistsClient):
    """create_gist returns the gist id from the API response."""
    client._session.request.return_value = make_response(
        200, json_body={"id": "abc123"}
    )
    result = client.create_gist({"hello.md": "# Hi"}, description="test", public=False)
    assert result == "abc123"


def test_create_gist_error(client: GistsClient):
    """create_gist raises GistAPIError on a 422 response."""
    client._session.request.return_value = make_response(422)
    with pytest.raises(GistAPIError):
        client.create_gist({"f.md": "x"}, description="bad", public=False)


# ---------------------------------------------------------------------------
# get_gist
# ---------------------------------------------------------------------------


def test_get_gist_happy_path(client: GistsClient):
    """get_gist returns a GistData with decoded file contents."""
    client._session.request.return_value = make_response(
        200,
        json_body={
            "id": "g1",
            "description": "d",
            "files": {"foo.md": {"content": "bar"}},
        },
    )
    result = client.get_gist("g1")
    assert result == GistData(files={"foo.md": "bar"}, description="d")


def test_get_gist_not_found(client: GistsClient):
    """get_gist raises GistNotFoundError on a 404."""
    client._session.request.return_value = make_response(404)
    with pytest.raises(GistNotFoundError):
        client.get_gist("missing")


# ---------------------------------------------------------------------------
# update_gist
# ---------------------------------------------------------------------------


def test_update_gist_happy_path(client: GistsClient):
    """update_gist completes without raising on a 200 response."""
    client._session.request.return_value = make_response(200, json_body={"id": "g1"})
    client.update_gist("g1", {"foo.md": "updated"})  # no exception


def test_update_gist_not_found(client: GistsClient):
    """update_gist raises GistNotFoundError on a 404."""
    client._session.request.return_value = make_response(404)
    with pytest.raises(GistNotFoundError):
        client.update_gist("missing", {"foo.md": "x"})


# ---------------------------------------------------------------------------
# search_gists
# ---------------------------------------------------------------------------


def test_search_gists_results(client: GistsClient):
    """search_gists returns a list of GistSummary objects."""
    client._session.request.return_value = make_response(
        200,
        json_body={"items": [{"id": "g1", "description": "Concept: foo"}]},
    )
    result = client.search_gists("foo")
    assert result == [GistSummary(gist_id="g1", description="Concept: foo")]


def test_search_gists_empty(client: GistsClient):
    """search_gists returns an empty list when no items are returned."""
    client._session.request.return_value = make_response(
        200, json_body={"items": []}
    )
    assert client.search_gists("nothing") == []


# ---------------------------------------------------------------------------
# list_comments
# ---------------------------------------------------------------------------


def test_list_comments(client: GistsClient):
    """list_comments returns Comment instances with stringified id."""
    client._session.request.return_value = make_response(
        200,
        json_body=[
            {"id": 42, "body": "note", "user": {"login": "alice"}}
        ],
    )
    result = client.list_comments("g1")
    assert result == [Comment(id="42", body="note", author_login="alice")]


# ---------------------------------------------------------------------------
# create_comment
# ---------------------------------------------------------------------------


def test_create_comment(client: GistsClient):
    """create_comment returns the new comment id as a string."""
    client._session.request.return_value = make_response(
        200, json_body={"id": 99}
    )
    assert client.create_comment("g1", "great concept") == "99"


# ---------------------------------------------------------------------------
# update_comment
# ---------------------------------------------------------------------------


def test_update_comment(client: GistsClient):
    """update_comment completes without raising on a 200 response."""
    client._session.request.return_value = make_response(200, json_body={})
    client.update_comment("g1", "42", "revised")  # no exception


# ---------------------------------------------------------------------------
# Rate-limit behaviour
# ---------------------------------------------------------------------------


def test_rate_limit_warning(client: GistsClient, capsys):
    """A warning is written to stderr when X-RateLimit-Remaining < 10."""
    client._session.request.return_value = make_response(
        200,
        json_body={
            "id": "g1",
            "description": "d",
            "files": {"foo.md": {"content": "bar"}},
        },
        headers={
            "X-RateLimit-Remaining": "5",
            "X-RateLimit-Reset": "1700000000",
        },
    )
    client.get_gist("g1")
    captured = capsys.readouterr()
    assert "[lore] GitHub rate limit low" in captured.err
    assert "5 requests remaining" in captured.err


def test_rate_limit_exhausted_via_header(client: GistsClient):
    """GistRateLimitError is raised when X-RateLimit-Remaining is "0"."""
    client._session.request.return_value = make_response(
        200,
        json_body={},
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"},
    )
    with pytest.raises(GistRateLimitError):
        client.get_gist("g1")


def test_429_raises_rate_limit_error(client: GistsClient):
    """HTTP 429 always raises GistRateLimitError regardless of header value."""
    client._session.request.return_value = make_response(
        429,
        json_body={},
        headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "9999999999"},
    )
    with pytest.raises(GistRateLimitError):
        client.create_gist({"f.md": "x"}, description="d", public=False)


# ---------------------------------------------------------------------------
# Retry behaviour (502 / 503)
# ---------------------------------------------------------------------------


def test_502_retry_success(client: GistsClient):
    """A 502 followed by a 200 succeeds and makes exactly two requests."""
    gist_200 = make_response(
        200,
        json_body={
            "id": "g1",
            "description": "d",
            "files": {"foo.md": {"content": "bar"}},
        },
    )
    client._session.request.side_effect = [
        make_response(502),
        gist_200,
    ]
    result = client.get_gist("g1")
    assert result == GistData(files={"foo.md": "bar"}, description="d")
    assert client._session.request.call_count == 2


def test_502_retry_failure(client: GistsClient):
    """Two consecutive 502 responses raise GistAPIError."""
    client._session.request.side_effect = [
        make_response(502),
        make_response(502),
    ]
    with pytest.raises(GistAPIError):
        client.get_gist("g1")


# ---------------------------------------------------------------------------
# Auth errors on endpoints other than __init__
# ---------------------------------------------------------------------------


def test_auth_error_401(client: GistsClient):
    """GistAuthError is raised when create_gist receives a 401."""
    client._session.request.return_value = make_response(401)
    with pytest.raises(GistAuthError):
        client.create_gist({"f.md": "x"}, description="d", public=False)


def test_auth_error_403(client: GistsClient):
    """GistAuthError is raised when create_gist receives a 403."""
    client._session.request.return_value = make_response(403)
    with pytest.raises(GistAuthError):
        client.create_gist({"f.md": "x"}, description="d", public=False)


# ---------------------------------------------------------------------------
# delete_gist
# ---------------------------------------------------------------------------


def test_delete_gist_happy_path(client: GistsClient):
    """delete_gist issues DELETE to the correct path and returns None."""
    client._session.request.return_value = make_response(204)
    result = client.delete_gist("abc123")
    assert result is None
    client._session.request.assert_called_once_with(
        "DELETE",
        "https://api.github.com/gists/abc123",
    )


def test_delete_gist_not_found(client: GistsClient):
    """delete_gist raises GistNotFoundError when the gist does not exist (404)."""
    client._session.request.return_value = make_response(404)
    with pytest.raises(GistNotFoundError):
        client.delete_gist("missing")
