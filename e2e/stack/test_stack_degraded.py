"""Degraded gist web search: server stays healthy, partial results kept, poll loop alive."""

from __future__ import annotations

import time

import pytest

from harness import RSS_LIMIT_BYTES, StackServer, make_stack
from gist_stub import CONCEPTS

PAGE1_VALID = {c.gist_id for c in CONCEPTS[:3]}
EXPECT_WARNING = {"block": "looks like a CAPTCHA/rate-limit page", "429": "HTTP 429", "5xx": "HTTP 502"}


@pytest.fixture(scope="module", params=["block", "429", "5xx"])
def degraded(request, tmp_path_factory) -> StackServer:
    def configure(stub) -> None:
        stub.search_mode, stub.fail_from_page = request.param, 2

    yield from make_stack(f"degraded-{request.param}", tmp_path_factory, configure)


def test_partial_results_kept_and_server_healthy(degraded: StackServer, request) -> None:
    mode = request.node.callspec.params["degraded"]
    assert degraded.get("/health").json() == {"status": "ok"}
    assert degraded.indexed_ids() == PAGE1_VALID
    log = degraded.log
    warning_lines = [ln for ln in log.splitlines() if " WARNING " in ln and "Bootstrap" in ln]
    assert any(EXPECT_WARNING[mode] in ln and "keeping 4 result(s)" in ln for ln in warning_lines), warning_lines
    assert "Traceback" not in log
    assert degraded.stub.count("/search") == 2, "discovery must stop at the failing page, no retry loop"


def test_poll_loop_survives_and_stays_bounded(degraded: StackServer) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and degraded.stub.count("/gists/public") < 2:
        time.sleep(0.5)
    assert degraded.stub.count("/gists/public") >= 2
    assert degraded.stub.count("/search") == 2
    assert degraded.alive() and 0 < degraded.max_rss < RSS_LIMIT_BYTES
    assert degraded.token not in degraded.log
    assert all(r["auth"] == "" for r in degraded.stub.snapshot() if r["path"] == "/search")
