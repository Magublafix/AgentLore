"""Fixture-driven fake GitHub for the semantic-server stack E2E (stdlib only).

Serves, on 127.0.0.1:<ephemeral port> from a daemon thread:

* ``GET /search?q=..&p=N``  gist web search (HTML shaped like
  ``lore/tests/fixtures/gist_search_page.html`` so the REAL parser is exercised;
  the last page is shaped like ``gist_search_empty.html``)
* ``GET /gists/<id>``, ``/gists/<id>/comments``, ``/gists/public``, ``/user``  (JSON API)

Corpus: five valid concepts from two owners with semantically distinct
``when_to_use`` text, plus a spam gist (marker, invalid lore.json), a gist
without the marker and a gist with a huge (3 MB) non-JSON ``lore.json``.

Failure modes (set at any time): ``search_mode`` in ``ok | block | 429 | 5xx`` with
``fail_from_page`` (first page number that fails) and ``api_mode`` in ``ok | 5xx``;
``feed_late`` publishes one extra concept (not on any search page) via ``/gists/public``.
Every request is logged (method, path, query, Authorization, User-Agent).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

MARKER = "[agentlore-concept]"
HUGE_BYTES = 3_000_000


@dataclass(frozen=True)
class Concept:
    gist_id: str
    owner: str
    name: str
    when_to_use: str
    language: str
    tags: tuple[str, ...]


# Semantically distinct on purpose: tests query with paraphrases that share no keywords.
CONCEPTS = [
    Concept("a1" * 16, "alice-dev", "Retry with exponential backoff",
            "Use when a network call or HTTP request fails intermittently and you must "
            "wait progressively longer between repeated attempts, adding random jitter.",
            "python", ("retry", "http", "resilience")),
    Concept("b2" * 16, "alice-dev", "Database connection pooling",
            "Use when an application opens too many database connections and you need to "
            "reuse a bounded set of long-lived sessions to the SQL server.",
            "python", ("database", "pool", "postgres")),
    Concept("c3" * 16, "bob-codes", "Multi-stage container image build",
            "Use when a Docker image is too large and you want to compile in one stage and "
            "ship only the runtime artifacts in a small final layer.",
            "dockerfile", ("docker", "image-size")),
    Concept("d4" * 16, "bob-codes", "Parameterized SQL queries",
            "Use when user input is concatenated into a query string and you need to prevent "
            "injection attacks by binding values as placeholders.",
            "python", ("security", "sql")),
    Concept("e5" * 16, "alice-dev", "Freeze the clock in tests",
            "Use when a unit test depends on the current time or dates and flakes around "
            "midnight; patch the time source so results are deterministic.",
            "python", ("testing", "time")),
]
# Not on any search page; only the /gists/public feed can reveal it (poll-loop discovery).
LATE = Concept("29" * 16, "carol-ops", "Graceful shutdown on SIGTERM",
               "Use when a long-running service gets terminated by the orchestrator and must "
               "finish in-flight work and release resources before the process exits.",
               "python", ("shutdown", "signals"))
SPAM_ID, UNMARKED_ID, HUGE_ID = "f6" * 16, "07" * 16, "18" * 16
SPAM_OWNER, UNMARKED_OWNER, HUGE_OWNER = "spammer", "bob-codes", "bloat-bot"

# Result pages (links are what the parser reads); page 3+ is the empty page.
PAGES = [
    [CONCEPTS[0].gist_id, CONCEPTS[1].gist_id, CONCEPTS[2].gist_id, SPAM_ID],
    [CONCEPTS[3].gist_id, CONCEPTS[4].gist_id, UNMARKED_ID, HUGE_ID],
]
VALID_IDS = [c.gist_id for c in CONCEPTS]
UPDATED_AT = "2026-10-31T10:00:00Z"

_OWNERS = {c.gist_id: c.owner for c in CONCEPTS}
_OWNERS[LATE.gist_id] = LATE.owner
_OWNERS.update({SPAM_ID: SPAM_OWNER, UNMARKED_ID: UNMARKED_OWNER, HUGE_ID: HUGE_OWNER})

_SNIPPET = """<div class="gist-snippet">
      <div class="gist-snippet-meta d-flex flex-lg-row flex-column width-full">
        <ul class="col-lg-5 col-12 flex-order-2 f6 tmp-mt-lg-0 tmp-mt-3 tmp-mb-lg-0 mb-2 d-flex flex-lg-justify-end">
          <li class="d-inline-block tmp-mr-lg-3 mr-2">
            <a class="Link--muted" href="/{owner}/{gid}">
              2 files
            </a>
          </li>
          <li class="d-inline-block tmp-mr-lg-3 mr-2">
            <a class="Link--muted" href="/{owner}/{gid}/forks">
              0 forks
            </a>
          </li>
        </ul>
        <div class="flex-order-1 col-lg-7 col-12 d-flex">
          <div class="d-inline-block px-lg-2 px-0">
            <span>
                <a href="/{owner}">{owner}</a>
                / <a href="/{owner}/{gid}"><strong class="css-truncate-target">concept.md</strong></a>
            </span>
            <span class="f6 color-fg-muted">
                {desc}
            </span>
          </div>
        </div>
      </div>
      <div class="file my-2"><article>[content stripped]</article></div>
    </div>
"""
_PAGE = ('<!DOCTYPE html>\n<html><head><title>Search</title></head><body>\n'
         '<div class="container-lg">\n{body}</div>\n</body></html>\n')
_EMPTY = ('<!DOCTYPE html>\n<html><head><title>Search</title></head><body>\n'
          '<div class="blankslate-container"><div class="blankslate">'
          '<h2 class="blankslate-heading">We couldn’t find any gists matching '
          '&#39;&quot;agentlore-concept&quot;&#39;</h2></div></div>\n</body></html>\n')
_BLOCK = ('<!DOCTYPE html><html><head><title>Verify</title></head><body>'
          '<h1>Are you a robot?</h1><p>Unusual traffic detected. Complete the CAPTCHA.</p>'
          '</body></html>')


def description(gid: str) -> str:
    if gid == UNMARKED_ID:
        return "Just some notes about retries (no marker)"
    if gid == SPAM_ID:
        return f"{MARKER} BUY CHEAP WATCHES http://spam.invalid"
    if gid == HUGE_ID:
        return f"{MARKER} Enormous payload [bloat]"
    c = next(c for c in [*CONCEPTS, LATE] if c.gist_id == gid)
    # One description deliberately mentions CAPTCHA/rate limit: result text must not count as a block.
    extra = " handles rate limit and CAPTCHA responses" if c is CONCEPTS[0] else ""
    return f"{MARKER} {c.name}{extra} [{', '.join(c.tags)}]"


def gist_json(gid: str) -> dict:
    files: dict[str, dict]
    if gid == SPAM_ID:
        files = {"lore.json": {"filename": "lore.json", "content": "{not valid json"}}
    elif gid == HUGE_ID:
        files = {"lore.json": {"filename": "lore.json", "content": "A" * HUGE_BYTES}}
    elif gid == UNMARKED_ID:
        files = {"notes.md": {"filename": "notes.md", "content": "retries are nice"}}
    else:
        c = next(c for c in [*CONCEPTS, LATE] if c.gist_id == gid)
        meta = {"name": c.name, "type": "pattern", "language": c.language,
                "when_to_use": c.when_to_use, "tags": list(c.tags)}
        files = {"lore.json": {"filename": "lore.json", "content": json.dumps(meta)},
                 "concept.md": {"filename": "concept.md", "content": f"# {c.name}\n\nBody.\n"}}
    return {"id": gid, "description": description(gid), "owner": {"login": _OWNERS[gid]},
            "updated_at": UPDATED_AT, "files": files}


class GistStub:
    def __init__(self) -> None:
        self.search_mode = "ok"      # ok | block | 429 | 5xx   (gist web search)
        self.fail_from_page = 1      # first page number affected by search_mode
        self.feed_late = False       # include LATE in /gists/public (default: empty feed)
        self.api_mode = "ok"         # ok | 5xx                 (JSON API)
        self.requests: list[dict] = []
        self._lock = threading.Lock()
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                pass

            def _send(self, code: int, body: bytes, ctype: str, headers: dict | None = None) -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

            def _json(self, code: int, obj: object) -> None:
                self._send(code, json.dumps(obj).encode(), "application/json")

            def do_GET(self) -> None:  # noqa: N802
                parts = urlsplit(self.path)
                query = parse_qs(parts.query)
                with stub._lock:
                    stub.requests.append({
                        "method": "GET", "path": parts.path, "query": parts.query,
                        "auth": self.headers.get("Authorization", ""),
                        "ua": self.headers.get("User-Agent", ""),
                    })
                path = parts.path
                if path == "/search":
                    return self._search(query)
                if stub.api_mode == "5xx":
                    return self._json(503, {"message": "Service Unavailable"})
                if path == "/user":
                    return self._json(200, {"login": "e2e-user"})
                if path == "/gists/public":
                    summaries = [{k: v for k, v in gist_json(g).items() if k != "files"}
                                 for g in ([LATE.gist_id] if stub.feed_late else [])]
                    return self._json(200, summaries)
                segs = path.strip("/").split("/")
                if len(segs) == 3 and segs[0] == "gists" and segs[2] == "comments":
                    body = []
                    if segs[1] == CONCEPTS[0].gist_id:
                        body = [{"body": '[lore-rating]{"outcome": 5, "hours_saved": 2}'}]
                    return self._json(200, body)
                if len(segs) == 2 and segs[0] == "gists" and segs[1] in _OWNERS:
                    return self._json(200, gist_json(segs[1]))
                self._json(404, {"message": "Not Found"})

            def _search(self, query: dict) -> None:
                page = int((query.get("p") or ["1"])[0])
                if stub.search_mode != "ok" and page >= stub.fail_from_page:
                    if stub.search_mode == "block":
                        return self._send(200, _BLOCK.encode(), "text/html; charset=utf-8")
                    if stub.search_mode == "429":
                        return self._send(429, b"Too Many Requests", "text/plain",
                                          {"Retry-After": "60"})
                    return self._send(502, b"Bad Gateway", "text/plain")
                if page > len(PAGES):
                    return self._send(200, _EMPTY.encode(), "text/html; charset=utf-8")
                body = "".join(_SNIPPET.format(owner=_OWNERS[g], gid=g, desc=description(g))
                               for g in PAGES[page - 1])
                self._send(200, _PAGE.format(body=body).encode(), "text/html; charset=utf-8")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> "GistStub":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.requests)

    def count(self, path: str) -> int:
        return sum(1 for r in self.snapshot() if r["path"] == path)
