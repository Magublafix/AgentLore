"""Install verification against stub and real stdio MCP servers (LORE-044).

The stub FastMCP server records every tool call to a log file so the tests can
prove ``init`` verification calls ``search_concepts`` exactly once and never
touches submit/link/rate. Nothing talks to GitHub.
"""

from __future__ import annotations

import sys
import textwrap

import pytest

from lore.setup.verify import VerifyResult, verify_install

STUB = textwrap.dedent(
    '''
    import json, os, sys
    from fastmcp import FastMCP

    LOG = os.environ["STUB_LOG"]
    MODE = os.environ.get("STUB_MODE", "ok")
    mcp = FastMCP("stub")

    def rec(name):
        with open(LOG, "a") as fh:
            fh.write(name + "\\n")

    @mcp.tool
    def search_concepts(problem: str, limit: int = 3) -> dict:
        rec("search_concepts")
        if MODE == "crash":
            print("fatal: " + os.environ.get("LORE_GITHUB_TOKEN", ""), file=sys.stderr)
            os._exit(3)
        if MODE == "slow":
            import time; time.sleep(60)
        if MODE == "empty":
            return {"results": []}
        out = {"results": [{"name": "stub concept"}]}
        if MODE == "fallback":
            out["fallback"] = True
        return out

    @mcp.tool
    def get_concept(concept_id: str) -> dict:
        rec("get_concept"); return {}

    if MODE != "missing":
        @mcp.tool
        def submit_concept(name: str) -> dict:
            rec("submit_concept"); return {}

    @mcp.tool
    def link_concepts(a: str) -> dict:
        rec("link_concepts"); return {}

    @mcp.tool
    def rate_concept(a: str) -> dict:
        rec("rate_concept"); return {}

    mcp.run()
    '''
)

TOKEN = "s3cr3t-not-github-shaped"


@pytest.fixture
def stub(tmp_path):
    script = tmp_path / "stub_server.py"
    script.write_text(STUB)
    log = tmp_path / "calls.log"

    def run(mode="ok", timeout=30.0, extra_env=None):
        env = {"STUB_LOG": str(log), "STUB_MODE": mode, **(extra_env or {})}
        res = verify_install(sys.executable, [str(script)], env, secrets=[TOKEN], timeout=timeout)
        calls = log.read_text().split() if log.exists() else []
        return res, calls

    return run


def test_success_lists_tools_and_searches_exactly_once(stub):
    res, calls = stub()
    assert res.ok and res.result_count == 1 and res.first_result == "stub concept"
    assert len(res.tools) == 5 and not res.warnings
    assert calls == ["search_concepts"]  # never submit/link/rate/get


def test_empty_result_list_still_passes(stub):
    res, calls = stub("empty")
    assert res.ok and res.result_count == 0 and calls == ["search_concepts"]


def test_fallback_is_a_warning_not_a_failure(stub):
    res, _ = stub("fallback")
    assert res.ok and any("fallback" in w for w in res.warnings)


def test_missing_tool_fails_without_searching(stub):
    res, calls = stub("missing")
    assert not res.ok and "submit_concept" in res.message and calls == []


def test_crash_reports_stderr_without_leaking_token(stub):
    res, _ = stub("crash", extra_env={"LORE_GITHUB_TOKEN": TOKEN})
    assert not res.ok
    assert "fatal" in res.message  # stderr was captured...
    assert TOKEN not in res.message  # ...and redacted


def test_timeout_is_reported(stub):
    res, _ = stub("slow", timeout=3.0)
    assert not res.ok and "timed out" in res.message


def test_bad_command_is_a_clean_failure():
    res = verify_install("/nonexistent/binary-xyz", [], {}, timeout=10)
    assert not res.ok and res.message


def test_client_factory_is_injectable():
    class Fake:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def list_tools(self):
            return []

    res = verify_install("x", [], {}, client_factory=lambda *a: Fake())
    assert not res.ok and "missing tools" in res.message


def test_real_server_in_read_only_mode_serves_seeds(tmp_path):
    """Spawn the actual `python -m lore.mcp.server` as `init` would (no GitHub, no token)."""
    env = {"LORE_BACKEND": "gists", "LORE_READ_ONLY": "1", "HOME": str(tmp_path)}
    res = verify_install(sys.executable, ["-m", "lore.mcp.server"], env, timeout=60)
    assert res.ok, res.message
    assert res.result_count >= 1 and res.first_result == "REST CLI around a REST API"
    assert len(res.tools) == 5 and not res.warnings


def test_real_server_read_only_with_dead_semantic_url_warns(tmp_path):
    env = {"LORE_BACKEND": "gists", "LORE_READ_ONLY": "1", "HOME": str(tmp_path),
           "LORE_SEMANTIC_URL": "http://127.0.0.1:9", "LORE_SEMANTIC_TIMEOUT": "1"}
    res = verify_install(sys.executable, ["-m", "lore.mcp.server"], env, timeout=60)
    assert res.ok and res.warnings and res.result_count >= 1


GH_STUB = textwrap.dedent(
    '''
    from fastmcp import FastMCP
    from lore.core.auth import resolve_github_token

    mcp = FastMCP("stub")

    @mcp.tool
    def search_concepts(problem: str, limit: int = 3) -> dict:
        tok = resolve_github_token()
        return {"results": [{"name": "resolved:" + str(tok)}]}

    for _n in ("get_concept", "submit_concept", "link_concepts", "rate_concept"):
        mcp.tool(name=_n)(lambda x="": {})
    mcp.run()
    '''
)


def test_gh_token_is_resolved_at_runtime_through_the_verify_child(tmp_path):
    """Registered env (LORE_TOKEN_FROM_GH=1, no injected token) + a fake `gh` on PATH."""
    import os
    import pathlib

    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text("#!/bin/sh\necho fake-gh-token-123\n")
    gh.chmod(0o755)
    script = tmp_path / "gh_stub.py"
    script.write_text(GH_STUB)
    root = str(pathlib.Path(__file__).resolve().parents[2])
    env = {"LORE_TOKEN_FROM_GH": "1", "PATH": f"{bindir}:{os.environ['PATH']}", "PYTHONPATH": root}
    res = verify_install(sys.executable, [str(script)], env, timeout=60)
    assert res.ok, res.message
    assert res.first_result == "resolved:fake-gh-token-123"
    # without the opt-in the same child must NOT call gh
    env.pop("LORE_TOKEN_FROM_GH")
    assert verify_install(sys.executable, [str(script)], env, timeout=60).first_result == "resolved:None"


def test_run_init_verification_never_calls_write_tools(stub, tmp_path):
    """run_init end to end with the real verifier: only search_concepts is ever called."""
    from lore.setup import init as init_mod
    from lore.setup.agents import AgentAdapter, ServerSpec
    from lore.setup.checks import Check

    class Ad(AgentAdapter):
        name = "Fake"

        def get_registration(self, server):
            return None

        def register(self, spec, scope):
            pass

        def remove(self, server, scope):
            pass

    script = tmp_path / "stub_server.py"  # written by the `stub` fixture
    log = tmp_path / "calls.log"
    spec = ServerSpec(command=sys.executable, args=(str(script),),
                      env={"STUB_LOG": str(log), "STUB_MODE": "ok"})
    home = tmp_path / "h"
    home.mkdir()
    lines = []
    code = init_mod.run_init(
        ["--yes"], adapters={"claude": Ad}, checks_fn=lambda semantic: [Check("p", True, "ok")],
        out=lines.append, spec=spec, env={}, home=home,
        token_fn=lambda **kw: __import__("lore.setup.auth", fromlist=["x"]).TokenResult(),
    )
    assert code == 0 and log.read_text().split() == ["search_concepts"]


def test_existing_registration_stored_token_is_redacted_from_verify_output(stub, tmp_path):
    from lore.setup import auth as auth_mod
    from lore.setup import init as init_mod
    from lore.setup.agents import AgentAdapter, Registration, ServerSpec
    from lore.setup.checks import Check

    legacy = "s3cr3t-stored-legacy"
    script = tmp_path / "stub_server.py"
    env = {"STUB_LOG": str(tmp_path / "c.log"), "STUB_MODE": "crash"}
    existing = Registration("stdio", sys.executable, (str(script),), {**env, "LORE_GITHUB_TOKEN": legacy}, "user")

    class Ad(AgentAdapter):
        name = "Fake"

        def get_registration(self, server):
            return existing

        def register(self, spec, scope):  # pragma: no cover
            pass

        def remove(self, server, scope):  # pragma: no cover
            pass

    (tmp_path / "h").mkdir()
    lines = []
    code = init_mod.run_init(
        ["--yes"], adapters={"claude": Ad}, checks_fn=lambda semantic: [Check("p", True, "ok")],
        out=lines.append, spec=ServerSpec(command=sys.executable, args=(str(script),), env=env),
        env={}, home=tmp_path / "h", token_fn=lambda **kw: auth_mod.TokenResult(),
    )
    out = "\n".join(lines)
    assert code == 1 and "fatal" in out and legacy not in out
