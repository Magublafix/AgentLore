"""Scenarios 1-3, 5, 9, 16, 17: the happy paths of ``init`` against the built wheel."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

SNAPSHOT = Path(__file__).parent / "snapshots" / "tools_schema.json"
SEED_TOP = "REST CLI around a REST API"
TOOLS = {"search_concepts", "get_concept", "submit_concept", "link_concepts", "rate_concept"}
SESSION_JSON = b'[{"pre": "existing session state"}]'


def seed_session(sb) -> Path:
    path = sb.home / ".lore" / "session.json"
    path.parent.mkdir(mode=0o700)
    path.write_bytes(SESSION_JSON)
    return path


def assert_registered_runs_wheel(sb, *, read_only: bool, user_env=None) -> dict:
    """The registration points at the BUILT wheel and the registered command really serves it."""
    info = sb.mcp_get()
    assert info["rc"] == 0
    assert info["command"] == "uvx"
    assert info["args"] == ["--from", str(sb.wheel), "mcp-server-lore"]
    assert info["scope"].startswith("User config")
    assert info["env"].get("LORE_BACKEND") == "gists"
    assert ("LORE_READ_ONLY" in info["env"]) == read_only
    if read_only:
        assert info["env"]["LORE_READ_ONLY"] == "1"
    sb.assert_connected()  # Claude Code's own stdio spawn + MCP handshake
    with sb.spawn_registered(user_env) as srv:
        assert {t["name"] for t in srv.list_tools()} == TOOLS
        found = srv.call_tool("search_concepts", {"problem": "REST CLI around a REST API", "limit": 3})
        assert isinstance(found.get("results"), list) and "error" not in found, found
        if read_only:  # token mode searches the user's (stubbed, empty) gists, not the seed set
            assert found["results"] and found["results"][0]["name"] == SEED_TOP, found
    return info


# ---------------------------------------------------------------- 1 + 9
def test_bare_yes_without_token_is_a_readonly_demo(sb):
    session = seed_session(sb)
    res = sb.init("--yes")
    assert res.rc == 0, res.text
    assert "READ-ONLY DEMO mode" in res.stdout
    assert "no GitHub token found" in res.stdout
    assert "Traceback" not in res.text
    assert "search_concepts returned" in res.stdout
    assert_registered_runs_wheel(sb, read_only=True)
    entry = sb.lore_registration()
    assert entry["env"]["LORE_READ_ONLY"] == "1"
    assert session.read_bytes() == SESSION_JSON  # scenario 9: pre-existing state untouched


# ---------------------------------------------------------------- 2 + 9
def test_env_token_is_validated_but_not_stored(sb, stub):
    session = seed_session(sb)
    stub_env = sb.use_stub(stub, sb.token)
    res = sb.init("--yes", extra_env=stub_env)
    assert res.rc == 0, res.text
    assert "is valid" in res.stdout and "e2e-user" in res.stdout
    assert "is NOT stored in your agent config" in res.stdout
    assert "READ-ONLY" not in res.stdout
    # the stub was really hit, with the token, and nowhere else
    assert "/user" in stub.paths()
    assert "/gists" in stub.paths()  # verification's search_concepts hit the stub too
    assert stub.auth_headers() == {f"Bearer {sb.token}"}
    # token absent from the claude config and from what claude reports
    assert sb.token not in sb.user_config_text()
    info = assert_registered_runs_wheel(sb, read_only=False, user_env=stub_env)
    assert "LORE_GITHUB_TOKEN" not in info["env"]
    assert sb.token not in info["raw"]
    assert session.read_bytes() == SESSION_JSON


# ---------------------------------------------------------------- 3 + 9
def test_store_token_writes_it_only_into_the_user_scope_entry(sb, stub):
    session = seed_session(sb)
    # claude itself shows stored env values in `mcp get`; that output is the one place allowed.
    stub_env = sb.use_stub(stub, sb.token)
    res = sb.init("--yes", "--store-token", extra_env=stub_env)
    assert res.rc == 0, res.text
    assert "PLAIN TEXT" in res.stdout
    assert sb.token not in res.text  # init never echoes it
    entry = sb.lore_registration()
    assert entry["env"]["LORE_GITHUB_TOKEN"] == sb.token
    assert "LORE_READ_ONLY" not in entry["env"]
    # exactly one occurrence in the whole user config, and no project-level (.mcp.json) copy
    assert sb.user_config_text().count(sb.token) == 1
    assert not (sb.cwd / ".mcp.json").exists()
    other = {p: m for p, m in sb.registrations().items() if p != "/mcpServers"}
    assert all("lore" not in m for m in other.values())
    sb.allow_files = [sb.user_config] + list(sb.claude_config.glob("backups/*"))
    assert session.read_bytes() == SESSION_JSON
    # the registered command (with the stored token in its env) still answers
    assert sb.token not in sb.redact_free_outputs(), "init output leaked the token"
    sb.allow_get_output = True  # ONLY `claude mcp get/list` output: claude prints stored env values
    sb.assert_connected()
    with sb.spawn_registered(stub_env) as srv:
        reply = srv.call_tool("search_concepts", {"problem": "REST CLI", "limit": 1})
        assert isinstance(reply.get("results"), list) and "error" not in reply, reply
        assert sb.token not in json.dumps(reply) and sb.token not in srv.stderr
    assert "/gists" in stub.paths()  # the verification child's search reached the stub
    assert stub.auth_headers() == {f"Bearer {sb.token}"}


# ---------------------------------------------------------------- 5
def test_second_run_is_idempotent(sb):
    first = sb.init("--yes")
    assert first.rc == 0, first.text
    before = sb.snapshot()
    cfg_before = sb.user_config.read_bytes()
    second = sb.init("--yes")
    assert second.rc == 0, second.text
    assert "already configured" in second.stdout
    assert "left untouched" in second.stdout
    assert sb.snapshot() == before
    # claude rewrites volatile counters on every run, so byte-identity is checked on the entry itself
    assert json.loads(sb.user_config.read_bytes())["mcpServers"] == json.loads(cfg_before)["mcpServers"]


# ---------------------------------------------------------------- 17
def test_remove_then_init_reregisters_cleanly(sb):
    assert sb.init("--yes").rc == 0
    rm = sb.claude("mcp", "remove", "lore", "-s", "user")
    assert rm.rc == 0, rm.text
    assert sb.lore_registration() is None
    again = sb.init("--yes")
    assert again.rc == 0, again.text
    assert "already configured" not in again.stdout
    assert_registered_runs_wheel(sb, read_only=True)


# ---------------------------------------------------------------- 16
def _normalise(schema: object) -> object:
    """Keep the contract (names, types, required, defaults); drop prose and titles."""
    if isinstance(schema, dict):
        return {k: _normalise(v) for k, v in sorted(schema.items()) if k not in ("title", "description")}
    if isinstance(schema, list):
        return [_normalise(v) for v in schema]
    return schema


def test_registered_server_contract_and_readonly_write_tools(sb):
    assert sb.init("--yes").rc == 0
    with sb.spawn_registered() as srv:
        tools = srv.list_tools()
        assert {t["name"] for t in tools} == TOOLS
        current = {t["name"]: _normalise(t["inputSchema"]) for t in sorted(tools, key=lambda t: t["name"])}
        if os.environ.get("LORE_E2E_UPDATE_SNAPSHOTS") == "1":
            SNAPSHOT.parent.mkdir(exist_ok=True)
            SNAPSHOT.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        assert SNAPSHOT.exists(), f"missing {SNAPSHOT}; generate it with LORE_E2E_UPDATE_SNAPSHOTS=1 and commit it"
        assert current == json.loads(SNAPSHOT.read_text()), (
            "tool input schemas changed; if intended, rerun with LORE_E2E_UPDATE_SNAPSHOTS=1")

        found = srv.call_tool("search_concepts", {"problem": "REST CLI around a REST API", "limit": 3})
        assert isinstance(found["results"], list) and len(found["results"]) >= 1
        assert found["results"][0]["name"] == SEED_TOP
        record = found["results"][0]
        for key in ("concept_id", "name", "type", "when_to_use", "content", "links"):
            assert key in record, (key, sorted(record))
        assert isinstance(record["links"], list)

        calls = {
            "submit_concept": {"name": "x", "type": "pattern", "content": "c", "when_to_use": "w", "tags": ["t"]},
            "link_concepts": {"from_id": "a", "to_id": "b", "rel": "uses", "label": "l"},
            "rate_concept": {"concept_id": "a", "outcome": 3, "session_id": "s"},
        }
        for tool, args in calls.items():
            reply = srv.call_tool(tool, args)
            assert reply.get("error") == "read_only", (tool, reply)
            assert reply.get("tool") == tool
