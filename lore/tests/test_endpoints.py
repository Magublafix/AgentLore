"""Tests for the test-only endpoint overrides (ADR-016): helper, call sites, redirects.

No real network: stub servers bind 127.0.0.1:0.
"""

from __future__ import annotations

import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
import requests

from lore.core import endpoints as ep

ALLOW = "LORE_ALLOW_INSECURE_TEST_URLS"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in (ALLOW, ep.API_ENV, ep.WEB_ENV):
        monkeypatch.delenv(k, raising=False)
    ep._honoured_logged.clear()


@pytest.fixture
def stub():
    """Factory for loopback stub servers: ``make(routes) -> (base_url, seen)``."""
    servers = []

    def make(routes):
        seen: list[tuple[str, dict]] = []

        class H(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
                status, headers, body = routes.get(self.path.split("?")[0], (404, {}, b"{}"))
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}", seen

    yield make
    for s in servers:
        s.shutdown()
        s.server_close()


def _enable(monkeypatch, api=None, web=None):
    monkeypatch.setenv(ALLOW, "1")
    if api:
        monkeypatch.setenv(ep.API_ENV, api)
    if web:
        monkeypatch.setenv(ep.WEB_ENV, web)


# ---------------------------------------------------------------- helper


def test_defaults_when_unset():
    assert ep.github_api_url() == "https://api.github.com"
    assert ep.gist_web_url() == "https://gist.github.com"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://127.0.0.1:8080", "http://127.0.0.1:8080"),
        ("http://localhost:9/", "http://localhost:9"),
        ("https://127.0.0.1:8443", "https://127.0.0.1:8443"),
        ("http://[::1]:8080", "http://[::1]:8080"),
        ("http://LOCALHOST", "http://LOCALHOST"),
    ],
)
def test_loopback_accepted(monkeypatch, url, expected):
    _enable(monkeypatch, api=url)
    assert ep.github_api_url() == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://api.github.com",
        "http://127.0.0.1.evil.com",
        "http://0.0.0.0:80",
        "http://user:pw@127.0.0.1:80",
        "http://user@localhost",
        "http://127.0.0.1:80?x=1",
        "http://127.0.0.1:80/?",
        "http://127.0.0.1:80#frag",
        "ftp://127.0.0.1",
        "127.0.0.1:8080",
        "http://",
        "http://127.0.0.1:notaport",
        "http://[::1",
    ],
)
def test_unsafe_rejected_with_warning(monkeypatch, caplog, url):
    _enable(monkeypatch, api=url)
    with caplog.at_level(logging.WARNING, logger="lore.core.endpoints"):
        assert ep.github_api_url() == "https://api.github.com"
    assert any("Ignoring LORE_GITHUB_API_URL" in r.message for r in caplog.records)


def test_missing_opt_in_ignored(monkeypatch, caplog):
    monkeypatch.setenv(ep.WEB_ENV, "http://127.0.0.1:1")
    with caplog.at_level(logging.WARNING, logger="lore.core.endpoints"):
        assert ep.gist_web_url() == "https://gist.github.com"
    assert any(ALLOW in r.message for r in caplog.records)


def test_opt_in_must_be_exactly_one(monkeypatch):
    monkeypatch.setenv(ALLOW, "true")
    monkeypatch.setenv(ep.API_ENV, "http://127.0.0.1:1")
    assert ep.github_api_url() == "https://api.github.com"


def test_honoured_override_warns_once(monkeypatch, caplog):
    _enable(monkeypatch, api="http://127.0.0.1:5")
    with caplog.at_level(logging.WARNING, logger="lore.core.endpoints"):
        ep.github_api_url()
        ep.github_api_url()
    msgs = [r for r in caplog.records if "TEST-ONLY" in r.message]
    assert len(msgs) == 1 and msgs[0].levelno == logging.WARNING


def test_resolved_at_call_time(monkeypatch):
    assert ep.github_api_url() == "https://api.github.com"
    _enable(monkeypatch, api="http://127.0.0.1:7")
    assert ep.github_api_url() == "http://127.0.0.1:7"


# ---------------------------------------------------------------- call sites


def test_setup_auth_validate_token_uses_override(monkeypatch, stub):
    from lore.setup import auth as auth_mod

    base, seen = stub({"/user": (200, {}, b'{"login": "octo"}')})
    _enable(monkeypatch, api=base)
    assert auth_mod.validate_token("tok") == "octo"
    assert seen[0][0] == "/user" and seen[0][1]["authorization"] == "Bearer tok"


def test_setup_auth_default_url(monkeypatch):
    from lore.setup import auth as auth_mod

    urls = []

    def http(url, headers=None, timeout=None):
        urls.append(url)
        raise requests.ConnectionError("x")

    with pytest.raises(auth_mod.AuthError):
        auth_mod.validate_token("tok", http)
    assert urls == ["https://api.github.com/user"]


def test_gists_client_uses_override(monkeypatch, stub):
    from lore.mcp.backends.gists_client import GistsClient

    base, seen = stub(
        {"/user": (200, {}, b'{"login": "octo"}'), "/gists/abc/comments": (200, {}, b"[]")}
    )
    _enable(monkeypatch, api=base)
    monkeypatch.setenv("LORE_GITHUB_TOKEN", "ghp_tok")
    c = GistsClient()
    assert c.authenticated_login == "octo"
    c.list_comments("abc")  # exercises _request on the override
    assert seen[0][0] == "/user" and seen[1][0].startswith("/gists/abc/comments")
    assert all(h["authorization"] == "Bearer ghp_tok" for _, h in seen)


def test_gists_client_default_base(monkeypatch):
    from unittest.mock import MagicMock, patch

    from lore.mcp.backends.gists_client import GistsClient

    resp = MagicMock(status_code=200, headers={})
    resp.json.return_value = {"login": "o"}
    monkeypatch.setenv("LORE_GITHUB_TOKEN", "t")
    with patch("requests.Session") as S:
        S.return_value.request.return_value = resp
        c = GistsClient()
    assert c._base_url == "https://api.github.com"


def test_gists_backend_submit_source_url_uses_web_override(monkeypatch):
    from unittest.mock import MagicMock

    from lore.mcp.backends import gists as gists_mod

    client = MagicMock()
    client.create_gist.return_value = "g1"
    args = dict(name="n", type="tool", content="c", when_to_use="w", tags=["t"])
    assert gists_mod.submit_concept(client, **args)["source_url"] == "https://gist.github.com/g1"
    _enable(monkeypatch, web="http://127.0.0.1:9")
    assert gists_mod.submit_concept(client, **args)["source_url"] == "http://127.0.0.1:9/g1"


def test_server_auth_verify_github_token_uses_override(monkeypatch, stub):
    from lore.server.auth import verify_github_token

    base, seen = stub({"/user": (200, {}, b'{"id": 7, "login": "octo"}')})
    _enable(monkeypatch, api=base)
    assert verify_github_token("tok") == {"id": 7, "login": "octo"}
    assert seen[0][1]["authorization"] == "token tok"


async def test_watcher_api_calls_use_override(monkeypatch, stub):
    from lore.server import watcher

    base, seen = stub(
        {
            "/gists/abc": (200, {}, b'{"id": "abc"}'),
            "/gists/abc/comments": (200, {}, b"[]"),
            "/gists/public": (200, {}, b"[]"),
        }
    )
    _enable(monkeypatch, api=base)
    async with httpx.AsyncClient() as client:
        assert (await watcher._fetch_full_gist(client, "abc")) == {"id": "abc"}
        await watcher._fetch_rating_aggregates(client, "abc")
        await watcher._fetch_public_gists(client, "2024-01-01T00:00:00Z")
    paths = [p.split("?")[0] for p, _ in seen]
    assert paths == ["/gists/abc", "/gists/abc/comments", "/gists/public"]


async def test_watcher_gist_search_uses_web_override(monkeypatch, stub):
    from lore.server import watcher

    base, seen = stub({"/search": (200, {}, b"<html></html>")})
    _enable(monkeypatch, web=base)
    async with httpx.AsyncClient() as client:
        out = await watcher._discover_concept_gists(client, delay=0, max_pages=1)
    assert out == [] and seen and seen[0][0].startswith("/search?")


def test_no_hardcoded_endpoints_left():
    """Every GitHub endpoint literal lives in the helper (display text in comments excepted)."""
    import pathlib
    import re

    root = pathlib.Path(ep.__file__).resolve().parents[1]
    offenders = []
    for p in root.rglob("*.py"):
        if "tests" in p.parts or p.name == "endpoints.py":
            continue
        for n, line in enumerate(p.read_text().splitlines(), 1):
            code = line.split("#")[0]
            if re.search(r'["\']https://(api|gist)\.github\.com', code):
                offenders.append(f"{p.name}:{n}")
    assert offenders == []


# ---------------------------------------------------------------- redirects


def _redirect_pair(stub):
    target, tseen = stub({"/user": (200, {}, b'{"login": "x", "id": 1}')})
    origin, _ = stub({"/user": (302, {"Location": f"{target}/user"}, b"")})
    return origin, tseen


def test_requests_strips_authorization_on_cross_origin_redirect(monkeypatch, stub):
    from lore.mcp.backends.gists_client import GistsClient

    origin, tseen = _redirect_pair(stub)
    _enable(monkeypatch, api=origin)
    monkeypatch.setenv("LORE_GITHUB_TOKEN", "ghp_secret")
    GistsClient()  # GET /user follows the redirect
    assert tseen and "authorization" not in tseen[0][1]


def test_setup_auth_requests_strips_authorization(monkeypatch, stub):
    from lore.setup import auth as auth_mod

    origin, tseen = _redirect_pair(stub)
    _enable(monkeypatch, api=origin)
    auth_mod.validate_token("ghp_secret")
    assert tseen and "authorization" not in tseen[0][1]


def test_httpx_strips_authorization_on_cross_origin_redirect(monkeypatch, stub):
    origin, tseen = _redirect_pair(stub)
    r = httpx.get(
        f"{origin}/user", headers={"Authorization": "token ghp_secret"}, follow_redirects=True
    )
    assert r.status_code == 200 and tseen and "authorization" not in tseen[0][1]


def test_server_auth_does_not_follow_redirects(monkeypatch, stub):
    """verify_github_token uses httpx defaults (no redirect following): the 302 is an error."""
    from lore.server.auth import verify_github_token

    origin, tseen = _redirect_pair(stub)
    _enable(monkeypatch, api=origin)
    with pytest.raises(httpx.HTTPStatusError):
        verify_github_token("ghp_secret")
    assert tseen == []


# ---------------------------------------------------------------- pagination origin


def test_same_origin_helper():
    assert ep.same_origin("https://api.github.com/x?p=2", "https://api.github.com")
    assert ep.same_origin("https://api.github.com:443/x", "https://api.github.com")
    assert not ep.same_origin("http://api.github.com/x", "https://api.github.com")
    assert not ep.same_origin("https://evil.com/x", "https://api.github.com")
    assert not ep.same_origin("http://127.0.0.1:1/x", "http://127.0.0.1:2")
    assert not ep.same_origin("garbage", "https://api.github.com")


def _paged(stub, same, path):
    other, oseen = stub({path: (200, {}, b'[{"id": "evil", "description": ""}]')})
    routes: dict = {}
    origin, seen = stub(routes)
    nxt = (origin if same else other) + path + "?page=2"
    routes[path] = (200, {"Link": f'<{nxt}>; rel="next"'}, b'[{"id": "one", "description": ""}]')
    return origin, seen, oseen


async def test_watcher_cross_origin_link_not_followed(monkeypatch, stub, caplog):
    from lore.server import watcher

    origin, seen, oseen = _paged(stub, False, "/gists/public")
    _enable(monkeypatch, api=origin)
    with caplog.at_level(logging.WARNING):
        async with httpx.AsyncClient(headers={"Authorization": "token t"}) as c:
            res = await watcher._fetch_public_gists(c, "2024-01-01T00:00:00Z")
    assert [g["id"] for g in res] == ["one"] and oseen == []
    assert any("cross-origin" in r.message for r in caplog.records)


async def test_watcher_same_origin_pagination_still_works(monkeypatch, stub):
    from lore.server import watcher

    origin, seen, _ = _paged(stub, True, "/gists/public")
    _enable(monkeypatch, api=origin)
    async with httpx.AsyncClient() as c:
        res = await watcher._fetch_public_gists(c, "2024-01-01T00:00:00Z")
    # the stub serves the same Link on page 2 too; bounded by the 30-page cap
    assert len(seen) == watcher._PUBLIC_FEED_MAX_PAGES and res[0]["id"] == "one"


def _client_with_token(monkeypatch, origin):
    from lore.mcp.backends.gists_client import GistsClient

    _enable(monkeypatch, api=origin)
    monkeypatch.setenv("LORE_GITHUB_TOKEN", "ghp_t")
    return GistsClient


def test_gists_client_cross_origin_link_not_followed(monkeypatch, stub, caplog):
    other, oseen = stub({"/gists": (200, {}, b'[{"id": "evil"}]')})
    routes: dict = {"/user": (200, {}, b'{"login": "o"}')}
    origin, seen = stub(routes)
    routes["/gists"] = (200, {"Link": f'<{other}/gists?page=2>; rel="next"'}, b'[{"id": "one"}]')
    c = _client_with_token(monkeypatch, origin)()
    with caplog.at_level(logging.WARNING):
        res = c.search_gists("q")
    assert [g.gist_id for g in res] == ["one"] and oseen == []
    assert any("cross-origin" in r.message for r in caplog.records)


def test_gists_client_same_origin_pagination_works(monkeypatch, stub):
    routes: dict = {"/user": (200, {}, b'{"login": "o"}')}
    origin, seen = stub(routes)

    routes["/gists"] = (200, {"Link": f'<{origin}/gists2>; rel="next"'}, b'[{"id": "one"}]')
    routes["/gists2"] = (200, {}, b'[{"id": "two"}]')
    c = _client_with_token(monkeypatch, origin)()
    assert [g.gist_id for g in c.search_gists("q")] == ["one", "two"]
