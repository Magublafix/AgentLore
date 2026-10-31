"""Tests for the watcher bootstrap (LORE-056): gist web-search discovery.

No network: the web client and the GitHub API helpers are faked.  The parser
is exercised against stripped captures of real gist.github.com result pages in
``lore/tests/fixtures/``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import lore.server.watcher as watcher_module
from lore.server.watcher import (
    _discover_concept_gists,
    _env_number,
    _fetch_public_gists,
    _parse_search_page,
    _run_bootstrap,
    watch_loop,
)

FIXTURES = Path(__file__).parent / "fixtures"
REAL_IDS = [
    ("Magubot", "a9ad6483f1fc3ae98d391f874d0e0d00"),
    ("Magubot", "0ab55edac00f843596ab4877d9fce08c"),
    ("Magubot", "c2c62ced9b8cd24b2c9d4ce5871845e6"),
]


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _gid(n: int) -> str:
    return f"{n:032x}"


def _page_html(entries: list[tuple[str, str]]) -> str:
    links = "".join(f'<a href="/{o}/{g}">x</a><a href="/{o}">{o}</a>' for o, g in entries)
    return f"<html><body>{links}</body></html>"


class FakeWeb:
    """Fake unauthenticated client serving scripted responses per page."""

    def __init__(self, pages: list):
        self.pages = pages
        self.requested: list[int] = []

    async def get(self, url, params=None, **kw):
        page = params["p"]
        self.requested.append(page)
        item = self.pages[page - 1] if page - 1 < len(self.pages) else ""
        if isinstance(item, Exception):
            raise item
        status, text = item if isinstance(item, tuple) else (200, item)
        return MagicMock(status_code=status, text=text, headers={})


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------


def test_parse_real_result_page():
    assert _parse_search_page(_fixture("gist_search_page.html")) == REAL_IDS


def test_parse_real_empty_page_no_warning(caplog):
    with caplog.at_level(logging.WARNING):
        assert _parse_search_page(_fixture("gist_search_empty.html")) == []
    assert not caplog.records


def test_parse_malformed_markup_warns_and_returns_empty(caplog):
    with caplog.at_level(logging.WARNING):
        assert _parse_search_page("<html><div>totally different</div>") == []
    assert "unexpected gist search markup" in caplog.text


def test_parse_partial_markup_returns_what_was_found():
    html = '<a href="/bob/' + _gid(1) + '">ok</a><a href="/bob/xyz123">bad'
    assert _parse_search_page(html) == [("bob", _gid(1))]


def test_parse_dedupes_ids():
    html = _page_html([("a", _gid(1))]) + _page_html([("a", _gid(1))])
    assert _parse_search_page(html) == [("a", _gid(1))]


def test_parse_non_string_never_raises():
    assert _parse_search_page(None) == []  # type: ignore[arg-type]


def test_env_number(monkeypatch):
    monkeypatch.delenv("X_N", raising=False)
    assert _env_number("X_N", 5.0) == 5.0
    monkeypatch.setenv("X_N", "abc")
    assert _env_number("X_N", 5.0) == 5.0
    monkeypatch.setenv("X_N", "1")
    assert _env_number("X_N", 5.0, minimum=2.0) == 2.0
    monkeypatch.setenv("X_N", "7")
    assert _env_number("X_N", 5.0, minimum=2.0) == 7.0


# --------------------------------------------------------------------------
# Discovery / paging
# --------------------------------------------------------------------------


async def test_paging_stops_at_empty_page_and_honours_delay():
    pages = [
        _page_html([("a", _gid(1)), ("a", _gid(2))]),
        _page_html([("b", _gid(3))]),
        _fixture("gist_search_empty.html"),
        _page_html([("z", _gid(99))]),  # must never be requested
    ]
    web = FakeWeb(pages)
    sleep = AsyncMock()
    out = await _discover_concept_gists(web, delay=2.5, max_pages=50, sleep=sleep)
    assert [g for _, g in out] == [_gid(1), _gid(2), _gid(3)]
    assert web.requested == [1, 2, 3]
    # delay between requests only, never before the first one
    assert [c.args[0] for c in sleep.await_args_list] == [2.5, 2.5]


async def test_max_pages_bound(caplog):
    web = FakeWeb([_page_html([("a", _gid(i))]) for i in range(1, 20)])
    with caplog.at_level(logging.WARNING):
        out = await _discover_concept_gists(web, delay=0, max_pages=3, sleep=AsyncMock())
    assert len(out) == 3 and web.requested == [1, 2, 3]
    assert "page limit" in caplog.text


async def test_repeated_page_stops():
    same = _page_html([("a", _gid(1))])
    web = FakeWeb([same, same, same])
    out = await _discover_concept_gists(web, delay=0, max_pages=10, sleep=AsyncMock())
    assert len(out) == 1 and web.requested == [1, 2]


@pytest.mark.parametrize("status", [429, 403, 500])
async def test_http_error_stops_keeps_partial(status, caplog):
    web = FakeWeb([_page_html([("a", _gid(1))]), (status, "nope"), _page_html([("a", _gid(2))])])
    with caplog.at_level(logging.WARNING):
        out = await _discover_concept_gists(web, delay=0, max_pages=10, sleep=AsyncMock())
    assert out == [("a", _gid(1))]
    assert web.requested == [1, 2]
    assert f"HTTP {status}" in caplog.text


async def test_captcha_page_stops_keeps_partial(caplog):
    web = FakeWeb([
        _page_html([("a", _gid(1))]),
        "<html><body>Please solve this CAPTCHA</body></html>",
    ])
    with caplog.at_level(logging.WARNING):
        out = await _discover_concept_gists(web, delay=0, max_pages=10, sleep=AsyncMock())
    assert out == [("a", _gid(1))]
    assert "CAPTCHA" in caplog.text


async def test_network_error_stops_keeps_partial(caplog):
    web = FakeWeb([_page_html([("a", _gid(1))]), httpx.ConnectError("boom")])
    with caplog.at_level(logging.WARNING):
        out = await _discover_concept_gists(web, delay=0, max_pages=10, sleep=AsyncMock())
    assert out == [("a", _gid(1))]
    assert "request failed" in caplog.text


# --------------------------------------------------------------------------
# _run_bootstrap
# --------------------------------------------------------------------------


def _full(gist_id: str, *, marker: bool = True, valid: bool = True, owner="a") -> dict:
    desc = ("[agentlore-concept] " if marker else "") + f"Name {gist_id[-4:]} [t]"
    content = (
        json.dumps({"name": f"N{gist_id[-4:]}", "when_to_use": "when X", "tags": []})
        if valid else "{not json"
    )
    return {
        "id": gist_id,
        "description": desc,
        "updated_at": "2026-01-01T00:00:00Z",
        "owner": {"login": owner},
        "files": {"lore.json": {"content": content}},
    }


class FakeAsyncClient:
    """Stand-in for httpx.AsyncClient used as an async context manager."""

    def __init__(self, *a, **kw):
        self.headers = kw.get("headers", {})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def run_env(monkeypatch):
    """Patch discovery, API helpers and the HTTP client; return the knobs."""
    state = {"found": [], "gists": {}, "fetched": []}

    async def fake_discover(web, *, delay, max_pages, sleep):
        state["delay"], state["max_pages"] = delay, max_pages
        return list(state["found"])

    async def fake_full(client, gist_id):
        state["fetched"].append(gist_id)
        if gist_id not in state["gists"]:
            raise httpx.HTTPError("404")
        return state["gists"][gist_id]

    monkeypatch.setattr(watcher_module, "_discover_concept_gists", fake_discover)
    monkeypatch.setattr(watcher_module, "_fetch_full_gist", fake_full)
    monkeypatch.setattr(
        watcher_module, "_fetch_rating_aggregates", AsyncMock(return_value=(None, None))
    )
    monkeypatch.setattr(watcher_module.httpx, "AsyncClient", FakeAsyncClient)
    for v in ("LORE_BOOTSTRAP_DELAY", "LORE_BOOTSTRAP_MAX_PAGES", "LORE_BOOTSTRAP_MAX_PER_OWNER"):
        monkeypatch.delenv(v, raising=False)
    return state


class MemStorage:
    """Minimal idempotent storage: second identical upsert is 'skipped'."""

    def __init__(self):
        self.data: dict[str, dict] = {}

    def upsert_concept(self, payload):
        gid = payload["gist_id"]
        if self.data.get(gid, {}).get("gist_updated_at") == payload["gist_updated_at"]:
            return {"concept_id": gid, "status": "skipped"}
        self.data[gid] = payload
        return {"concept_id": gid, "status": "upserted"}


async def test_bootstrap_without_token_skips(run_env, caplog):
    with caplog.at_level(logging.WARNING):
        stats = await _run_bootstrap(MemStorage(), "", 0.0)
    assert stats["discovered"] == 0 and run_env["fetched"] == []
    assert "skipping bootstrap" in caplog.text


async def test_bootstrap_filters_marker_and_validity(run_env):
    run_env["found"] = [("a", _gid(1)), ("a", _gid(2)), ("a", _gid(3)), ("a", _gid(4))]
    run_env["gists"] = {
        _gid(1): _full(_gid(1)),
        _gid(2): _full(_gid(2), marker=False),
        _gid(3): _full(_gid(3), valid=False),
        # _gid(4) fetch fails (404)
    }
    storage = MemStorage()
    stats = await _run_bootstrap(storage, "tok", 0.0)
    assert list(storage.data) == [_gid(1)]
    assert stats["indexed"] == 1 and stats["rejected"] == 2


async def test_bootstrap_per_owner_cap(run_env, monkeypatch):
    monkeypatch.setenv("LORE_BOOTSTRAP_MAX_PER_OWNER", "2")
    run_env["found"] = [("spam", _gid(i)) for i in range(1, 6)] + [("good", _gid(10))]
    run_env["gists"] = {g: _full(g) for _, g in run_env["found"]}
    storage = MemStorage()
    stats = await _run_bootstrap(storage, "tok", 0.0)
    assert set(storage.data) == {_gid(1), _gid(2), _gid(10)}
    assert stats["capped"] == 3
    assert _gid(5) not in run_env["fetched"]


async def test_bootstrap_delay_clamped_and_configurable(run_env, monkeypatch):
    run_env["found"] = []
    monkeypatch.setenv("LORE_BOOTSTRAP_DELAY", "0.1")
    monkeypatch.setenv("LORE_BOOTSTRAP_MAX_PAGES", "7")
    await _run_bootstrap(MemStorage(), "tok", 0.0)
    assert run_env["delay"] == 2.0 and run_env["max_pages"] == 7
    monkeypatch.setenv("LORE_BOOTSTRAP_DELAY", "5")
    await _run_bootstrap(MemStorage(), "tok", 0.0)
    assert run_env["delay"] == 5.0


async def test_bootstrap_is_idempotent(run_env):
    run_env["found"] = [("a", _gid(1)), ("a", _gid(2))]
    run_env["gists"] = {g: _full(g) for _, g in run_env["found"]}
    storage = MemStorage()
    first = await _run_bootstrap(storage, "tok", 0.0)
    second = await _run_bootstrap(storage, "tok", 0.0)
    assert first["indexed"] == 2 and first["unchanged"] == 0
    assert second["indexed"] == 0 and second["unchanged"] == 2


async def test_bootstrap_rating_filter(run_env, monkeypatch):
    run_env["found"] = [("a", _gid(1))]
    run_env["gists"] = {_gid(1): _full(_gid(1))}
    monkeypatch.setattr(
        watcher_module, "_fetch_rating_aggregates", AsyncMock(return_value=(1.0, None))
    )
    storage = MemStorage()
    stats = await _run_bootstrap(storage, "tok", 3.0)
    assert stats["skipped"] == 1 and not storage.data


async def test_bootstrap_upsert_error_continues(run_env, caplog):
    run_env["found"] = [("a", _gid(1)), ("a", _gid(2))]
    run_env["gists"] = {g: _full(g) for _, g in run_env["found"]}
    storage = MagicMock()
    storage.upsert_concept.side_effect = [RuntimeError("db"), {"status": "upserted"}]
    with caplog.at_level(logging.WARNING):
        stats = await _run_bootstrap(storage, "tok", 0.0)
    assert stats["indexed"] == 1 and "upsert_concept failed" in caplog.text


async def test_bootstrap_discovery_exception_is_fail_soft(run_env, monkeypatch, caplog):
    async def boom(*a, **kw):
        raise RuntimeError("scrape broke")

    monkeypatch.setattr(watcher_module, "_discover_concept_gists", boom)
    with caplog.at_level(logging.WARNING):
        stats = await _run_bootstrap(MemStorage(), "tok", 0.0)
    assert stats["discovered"] == 0 and "discovery failed" in caplog.text


async def test_rate_limit_stop_keeps_partial_results_end_to_end(monkeypatch):
    """Real discovery + fake web: a 429 on page 2 still indexes page 1."""
    web = FakeWeb([_page_html([("a", _gid(1))]), (429, "slow down")])
    storage = MemStorage()

    class Client(FakeAsyncClient):
        async def get(self, url, params=None, **kw):
            return await web.get(url, params=params)

    monkeypatch.setattr(watcher_module.httpx, "AsyncClient", Client)
    monkeypatch.setattr(
        watcher_module, "_fetch_full_gist", AsyncMock(return_value=_full(_gid(1)))
    )
    monkeypatch.setattr(
        watcher_module, "_fetch_rating_aggregates", AsyncMock(return_value=(None, None))
    )
    stats = await _run_bootstrap(storage, "tok", 0.0, sleep=AsyncMock())
    assert stats["indexed"] == 1 and web.requested == [1, 2]


async def test_web_client_never_gets_token(monkeypatch):
    seen = []

    class Spy(FakeAsyncClient):
        def __init__(self, *a, **kw):
            seen.append(kw.get("headers", {}))
            super().__init__(*a, **kw)

        async def get(self, url, params=None, **kw):
            return MagicMock(status_code=200, text=_fixture("gist_search_empty.html"))

    monkeypatch.setattr(watcher_module.httpx, "AsyncClient", Spy)
    await _run_bootstrap(MemStorage(), "secret-token", 0.0, sleep=AsyncMock())
    assert "Authorization" not in seen[0]
    assert "AgentLore" in seen[0]["User-Agent"]


# --------------------------------------------------------------------------
# watch_loop resilience / poll cap
# --------------------------------------------------------------------------


async def test_bootstrap_failure_does_not_stop_poll_loop():
    polled = asyncio.Event()

    async def poll(*a, **kw):
        polled.set()
        raise asyncio.CancelledError()

    with patch.object(watcher_module, "_run_bootstrap", side_effect=RuntimeError("x")), \
         patch.object(watcher_module, "_run_poll_cycle", side_effect=poll):
        with pytest.raises(asyncio.CancelledError):
            await watch_loop(MagicMock(), "tok", interval=1)
    assert polled.is_set()


async def test_public_feed_cap_warns(caplog):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = []
    resp.headers = {"Link": '<https://api.github.com/gists/public?page=2>; rel="next"'}
    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    with caplog.at_level(logging.WARNING):
        await _fetch_public_gists(client, "2026-01-01T00:00:00Z")
    assert client.get.await_count == 30
    assert "may have been missed" in caplog.text


# --------------------------------------------------------------------------
# Review fixes: block detection, parser noise, defaults, cap behaviour
# --------------------------------------------------------------------------


def test_parse_page_with_ratelimit_snippet_fixture():
    out = _parse_search_page(_fixture("gist_search_ratelimit_snippet.html"))
    assert out == REAL_IDS


async def test_snippet_mentioning_rate_limit_does_not_stop_paging():
    page1 = _fixture("gist_search_ratelimit_snippet.html")
    assert watcher_module._looks_blocked(page1)  # text alone would match...
    web = FakeWeb([page1, _page_html([("b", _gid(7))]), _fixture("gist_search_empty.html")])
    out = await _discover_concept_gists(web, delay=0, max_pages=10, sleep=AsyncMock())
    assert [g for _, g in out] == [g for _, g in REAL_IDS] + [_gid(7)]  # ...but paging goes on
    assert web.requested == [1, 2, 3]


async def test_blocklike_page_without_results_stops_with_warning(caplog):
    web = FakeWeb([
        _page_html([("a", _gid(1))]),
        "<html><title>Rate limit exceeded</title>Too many requests</html>",
        _page_html([("a", _gid(2))]),
    ])
    with caplog.at_level(logging.WARNING):
        out = await _discover_concept_gists(web, delay=0, max_pages=10, sleep=AsyncMock())
    assert out == [("a", _gid(1))] and web.requested == [1, 2]
    assert "CAPTCHA/rate-limit" in caplog.text


def test_parse_ignores_noise_links_and_uppercase_ids():
    gid = _gid(0xABCDEF5)  # contains letters, so .upper() really differs
    html = (
        f'<a href="/bob/{gid}">x</a><a href="/bob/{gid}/forks">f</a>'
        f'<a href="/bob/{gid}#comments">c</a><a href="/bob/{gid}/stargazers">s</a>'
        '<a href="/search?o=desc&amp;q=%22agentlore-concept%22&amp;p=2">next</a>'
        '<a href="/bob">bob</a>'
        f'<a href="/eve/{gid.upper()}">upper</a>'
    )
    assert _parse_search_page(html) == [("bob", gid)]


def test_parse_supports_single_quoted_href():
    gid = _gid(6)
    assert _parse_search_page(f"<a href='/amy/{gid}'>x</a>") == [("amy", gid)]


async def test_429_logs_retry_after(caplog):
    web = FakeWeb([_page_html([("a", _gid(1))])])

    async def get(url, params=None, **kw):
        if params["p"] == 1:
            return MagicMock(status_code=200, text=_page_html([("a", _gid(1))]), headers={})
        return MagicMock(status_code=429, text="", headers={"Retry-After": "60"})

    web.get = get
    with caplog.at_level(logging.WARNING):
        out = await _discover_concept_gists(web, delay=0, max_pages=5, sleep=AsyncMock())
    assert len(out) == 1
    assert "Retry-After: 60" in caplog.text and "rate-limited" in caplog.text


async def test_per_owner_cap_is_case_insensitive(run_env, monkeypatch):
    monkeypatch.setenv("LORE_BOOTSTRAP_MAX_PER_OWNER", "2")
    run_env["found"] = [("Bob", _gid(1)), ("bob", _gid(2)), ("BOB", _gid(3))]
    run_env["gists"] = {g: _full(g) for _, g in run_env["found"]}
    stats = await _run_bootstrap(MemStorage(), "tok", 0.0)
    assert stats["indexed"] == 2 and stats["capped"] == 1


def test_default_constants():
    assert watcher_module._DEFAULT_BOOTSTRAP_DELAY >= 2.0
    assert watcher_module._MIN_BOOTSTRAP_DELAY >= 2.0
    assert watcher_module._DEFAULT_BOOTSTRAP_MAX_PER_OWNER == 300
    assert watcher_module._DEFAULT_BOOTSTRAP_MAX_PAGES == 100


async def test_defaults_applied_when_env_unset(run_env):
    await _run_bootstrap(MemStorage(), "tok", 0.0)
    assert run_env["delay"] >= 2.0 and run_env["max_pages"] == 100


async def test_225_gists_one_owner_all_indexed_at_default_cap(run_env):
    run_env["found"] = [("Magubot", _gid(i)) for i in range(1, 226)]
    run_env["gists"] = {g: _full(g) for _, g in run_env["found"]}
    storage = MemStorage()
    stats = await _run_bootstrap(storage, "tok", 0.0)
    assert stats["indexed"] == 225 and stats["capped"] == 0 and len(storage.data) == 225


async def test_public_feed_exactly_30_pages_without_next_does_not_warn(caplog):
    calls = {"n": 0}

    async def get(url, **kw):
        calls["n"] += 1
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = []
        more = calls["n"] < 30
        resp.headers = {"Link": '<https://api.github.com/gists/public?page=2>; rel="next"'} if more else {}
        return resp

    client = AsyncMock()
    client.get = get
    with caplog.at_level(logging.WARNING):
        await _fetch_public_gists(client, "2026-01-01T00:00:00Z")
    assert calls["n"] == 30
    assert "may have been missed" not in caplog.text
