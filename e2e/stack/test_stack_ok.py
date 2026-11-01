"""Happy path: stub GitHub -> bootstrap -> in-memory Qdrant -> /search -> MCP client."""

from __future__ import annotations

import re
import sys
import time
from collections import Counter

import pytest

from harness import RSS_LIMIT_BYTES, WATCH_INTERVAL, StackServer, base_env, make_stack, redact
from gist_stub import CONCEPTS, LATE, HUGE_ID, SPAM_ID, UNMARKED_ID, VALID_IDS
from mcp_stdio import McpStdioSession

# Paraphrases sharing no keywords with the stored when_to_use text.
QUERIES = {
    CONCEPTS[0].gist_id: "my web requests flake out occasionally, how long should I pause before trying once more",
    CONCEPTS[1].gist_id: "my app exhausts the server's session limit because every request opens a fresh link to the relational store",
    CONCEPTS[2].gist_id: "the shipped container is gigabytes big, I only want the compiled output in the final layer",
    CONCEPTS[3].gist_id: "attackers type malicious text into a form field that ends up inside my statement to the data layer",
    CONCEPTS[4].gist_id: "my assertions break only when the clock rolls past 12am",
}


@pytest.fixture(scope="module")
def stack(tmp_path_factory) -> StackServer:
    yield from make_stack("ok", tmp_path_factory)


def test_health_and_index_matches_valid_concepts(stack: StackServer) -> None:
    r = stack.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert stack.indexed_ids() == set(VALID_IDS)
    # spam / unmarked / huge never indexed, server did not crash
    assert not {SPAM_ID, UNMARKED_ID, HUGE_ID} & stack.indexed_ids()
    assert "8 discovered, 5 indexed, 0 unchanged, 0 skipped (rating filter), 3 rejected" in stack.log
    assert stack.alive()


@pytest.mark.parametrize("gist_id", VALID_IDS)
def test_semantic_paraphrase_ranks_expected_concept_first(stack: StackServer, gist_id: str) -> None:
    results = stack.get("/search", q=QUERIES[gist_id], k=5).json()["results"]
    assert results[0]["concept_id"] == gist_id, [(x["name"], x["score"]) for x in results]
    assert results[0]["score"] > results[1]["score"]


def test_rating_comment_flows_through(stack: StackServer) -> None:
    top = stack.get("/search", q=QUERIES[CONCEPTS[0].gist_id], k=1).json()["results"][0]
    assert top["avg_rating"] == 5.0 and top["avg_hours_saved"] == 2.0
    assert top["author"] == "alice-dev"


def test_mcp_client_through_full_chain(stack: StackServer, tmp_path) -> None:
    env = base_env(tmp_path, stack.python_path)
    env.update({"LORE_READ_ONLY": "1", "LORE_SEMANTIC_URL": stack.url, "LORE_SEMANTIC_TIMEOUT": "20"})
    with McpStdioSession(stack.python, ["-m", "lore.mcp.server"], env, str(tmp_path), timeout=90) as mcp:
        mcp.initialize()
        assert "search_concepts" in {t["name"] for t in mcp.list_tools()}
        out = mcp.call_tool("search_concepts", {
            "problem": QUERIES[CONCEPTS[2].gist_id], "limit": 3, "min_rating": 0})
        stderr = mcp.stderr
    assert not out.get("fallback"), out
    assert out["results"][0]["concept_id"] == CONCEPTS[2].gist_id
    assert stack.token not in stderr and stack.token not in str(out)


def test_token_only_ever_reaches_the_stub(stack: StackServer) -> None:
    reqs = stack.stub.snapshot()
    assert stack.stub.count("/search") >= 3, "the stub web search was not really hit"
    assert any(r["path"].startswith("/gists/") for r in reqs), "the stub API was not really hit"
    expected = f"Bearer {stack.token}"
    for r in reqs:
        if r["path"] == "/search":
            assert r["auth"] == "", "token must never be sent to the web search"
        else:
            assert r["auth"] == expected, r
    assert stack.token not in stack.log
    assert stack.token not in stack.get("/search", q="token", k=50).text
    assert "TEST-ONLY" in stack.log  # loud warnings for both test hooks
    assert "in-memory Qdrant" in stack.log


def test_poll_loop_alive_and_no_runaway(stack: StackServer) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and stack.stub.count("/gists/public") < 2:
        time.sleep(0.5)
    assert stack.stub.count("/gists/public") >= 2, "poll loop is not running"
    uptime = time.monotonic() - stack.started_at
    # polls are bounded by the interval: no hot loop
    assert stack.stub.count("/gists/public") <= uptime / WATCH_INTERVAL + 3
    assert stack.stub.count("/search") <= 3  # bootstrap pages only, never repeated
    assert len(stack.stub.snapshot()) < 600
    lines = [ln for ln in stack.log.splitlines() if ln.strip()]
    assert len(lines) < 1500, f"log explosion: {len(lines)} lines"
    norm = Counter(re.sub(r"\d+|[0-9a-f]{32}", "#", ln.split(" ", 2)[-1]) for ln in lines)
    msg, n = norm.most_common(1)[0]
    assert n < 150, f"message repeated {n}x: {msg}"
    assert 0 < stack.max_rss < RSS_LIMIT_BYTES, stack.max_rss
    assert stack.alive()
    assert "Traceback" not in stack.log, redact(stack.log, [stack.token])[-2000:]
    _ = sys


def test_poll_loop_discovers_new_gist_from_public_feed(stack: StackServer) -> None:
    stack.stub.feed_late = True
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and LATE.gist_id not in stack.indexed_ids():
        time.sleep(1)
    assert LATE.gist_id in stack.indexed_ids()
    top = stack.get("/search", q="the orchestrator sends a stop signal and we want to finish pending work first", k=1)
    assert top.json()["results"][0]["concept_id"] == LATE.gist_id
