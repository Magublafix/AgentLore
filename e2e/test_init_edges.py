"""Scenarios 4, 6, 7, 8, 10-15: refusals, conflicts, missing prerequisites, failures."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e

TOOLS = {"search_concepts", "get_concept", "submit_concept", "link_concepts", "rate_concept"}


def nothing_written(sb) -> None:
    assert sb.lore_registration() is None
    assert not (sb.home / ".lore").exists()
    assert not (sb.cwd / ".mcp.json").exists()


# ---------------------------------------------------------------- 4
def test_project_scope_refuses_store_token(sb, stub):
    res = sb.init("--yes", "--scope", "project", "--store-token", extra_env=sb.use_stub(stub, sb.token))
    assert res.rc == 1, res.text
    assert "refusing to store a token with project scope" in res.stdout
    assert "fix:" in res.stdout and "--scope user" in res.stdout
    assert "Traceback" not in res.text
    nothing_written(sb)
    assert stub.requests == []  # refused before any network use of the token


def test_project_scope_refuses_credentialed_semantic_url(sb):
    secret = "E2EPASSWORD" + sb.token[-8:]
    sb.secrets.append(secret)
    res = sb.init("--yes", "--scope", "project", "--semantic-url", f"https://user:{secret}@semantic.invalid")
    assert res.rc == 1, res.text
    assert "refusing to register this semantic URL with project scope" in res.stdout
    assert "fix:" in res.stdout
    nothing_written(sb)


def test_project_scope_demo_writes_a_secret_free_mcp_json(sb):
    res = sb.init("--yes", "--scope", "project", "--no-verify")
    assert res.rc == 0, res.text
    mcp = (sb.cwd / ".mcp.json").read_text()
    assert '"lore"' in mcp and "LORE_READ_ONLY" in mcp and str(sb.wheel) in mcp
    assert sb.mcp_get()["scope"].startswith("Project config")


# ---------------------------------------------------------------- 6
def test_mode_switch_demo_to_token(sb, stub):
    assert sb.init("--yes").rc == 0
    before = sb.snapshot()
    env = sb.use_stub(stub, sb.token)
    res = sb.init("--yes", extra_env=env)
    assert res.rc == 1, res.text
    assert "already registered with different settings" in res.stdout
    assert "registered in read-only mode, but a token is now available" in res.stdout
    assert "re-run with --force" in res.stdout
    assert sb.snapshot() == before
    forced = sb.init("--yes", "--force", extra_env=env)
    assert forced.rc == 0, forced.text
    assert "removing existing 'lore'" in forced.stdout
    entry = sb.lore_registration()
    assert "LORE_READ_ONLY" not in entry["env"]
    assert sb.token not in sb.user_config_text()


def test_mode_switch_token_to_demo(sb, stub):
    first = sb.init("--yes", extra_env=sb.use_stub(stub, sb.token))
    assert first.rc == 0, first.text
    assert "LORE_READ_ONLY" not in sb.lore_registration()["env"]
    before = sb.snapshot()
    res = sb.init("--yes")  # no token in the environment any more
    assert res.rc == 1, res.text
    assert "registered with a token, but no token is available now (read-only mode)" in res.stdout
    assert sb.snapshot() == before
    forced = sb.init("--yes", "--force")
    assert forced.rc == 0, forced.text
    assert sb.lore_registration()["env"]["LORE_READ_ONLY"] == "1"
    assert "READ-ONLY DEMO mode" in forced.stdout


# ---------------------------------------------------------------- 7
def test_local_registers_the_interpreter_and_verifies(sb):
    sb.unlink("uvx")  # --local must not need uvx
    res = sb.init("--yes", "--local", via="venv")
    assert res.rc == 0, res.text
    assert "search_concepts returned" in res.stdout
    info = sb.mcp_get()
    assert info["command"] == str(sb.venv_python)
    assert info["args"] == ["-m", "lore.mcp.server"]
    sb.assert_connected()
    with sb.spawn_registered() as srv:
        assert {t["name"] for t in srv.list_tools()} == TOOLS
        top = srv.call_tool("search_concepts", {"problem": "REST CLI around a REST API"})["results"]
        assert top and top[0]["name"] == "REST CLI around a REST API"


# ---------------------------------------------------------------- 8
def test_dry_run_on_clean_home_changes_nothing(sb):
    before = sb.home_hash()
    res = sb.init("--yes", "--dry-run")
    assert res.rc == 0, res.text
    assert "Dry run complete" in res.stdout and "[dry-run]" in res.stdout
    assert sb.home_hash() == before
    nothing_written(sb)


def test_dry_run_with_conflict_changes_nothing(sb, stub):
    assert sb.init("--yes").rc == 0
    before = sb.home_hash()
    env = sb.use_stub(stub, sb.token)
    refused = sb.init("--yes", "--dry-run", extra_env=env)
    assert refused.rc == 1 and "already registered with different settings" in refused.stdout
    forced = sb.init("--yes", "--dry-run", "--force", extra_env=env)
    assert forced.rc == 0, forced.text
    assert "[dry-run] removing existing 'lore'" in forced.stdout
    assert "Dry run complete" in forced.stdout
    assert sb.home_hash() == before
    assert stub.requests == []  # dry-run skips token validation


# ---------------------------------------------------------------- 10
def test_missing_claude_cli_is_a_clean_error(sb):
    sb.unlink("claude")
    res = sb.init("--yes")
    assert res.rc == 1, res.text
    assert "Claude Code CLI ('claude') not found on PATH" in res.stdout
    assert "fix:" in res.stdout and "Setup stopped" in res.stdout
    assert "Traceback" not in res.text
    assert not (sb.home / ".lore").exists()


# ---------------------------------------------------------------- 11
def test_missing_uvx_is_a_clean_error_and_registers_nothing(sb):
    sb.unlink("uvx")
    res = sb.init("--yes", via="venv")
    assert res.rc == 1, res.text
    assert "'uvx' not found on PATH" in res.stdout
    assert "Install uv" in res.stdout and "--local" in res.stdout and "Setup stopped" in res.stdout
    assert "Traceback" not in res.text
    nothing_written(sb)


# ---------------------------------------------------------------- 12
@pytest.mark.parametrize("stdin_open", [False, True], ids=["devnull", "open-pipe"])
def test_no_tty_and_no_yes_never_prompts_or_hangs(sb, stdin_open):
    res = sb.init(timeout=240, stdin_open=stdin_open)
    assert res.rc == 0, res.text
    assert "input hidden" not in res.text and "Press Enter" not in res.text
    assert "READ-ONLY DEMO mode" in res.stdout


# ---------------------------------------------------------------- 13
def test_store_token_without_any_token_is_rejected(sb):
    """Contract: asking to store a token when none exists must not silently succeed."""
    res = sb.init("--yes", "--store-token")
    assert res.rc != 0, res.text
    assert "--store-token needs a token" in res.text
    assert "Traceback" not in res.text
    nothing_written(sb)


# ---------------------------------------------------------------- 14
def test_verification_failure_is_reported_and_no_verify_skips_it(sb, stub):
    sb.fake_tool("uvx", "echo 'boom: simulated server crash' >&2\nexit 1")
    env = sb.use_stub(stub, sb.token)
    res = sb.init("--yes", via="venv", extra_env=env)
    assert res.rc == 1, res.text
    assert "verification failed" in res.stdout
    assert "fix:" in res.stdout and "--no-verify" in res.stdout
    assert "Traceback" not in res.text
    assert sb.token not in res.text
    # Claude's own view agrees with init's: the registered command is broken
    st = sb.claude_status("Failed", timeout=60)
    assert "Failed to connect" in st["get"].get("status", ""), st["get"]["raw"]
    assert st["get"].get("issue"), st["get"]["raw"]
    assert "Failed to connect" in st["list"], st["list"]
    skipped = sb.init("--yes", "--no-verify", via="venv", extra_env=env)
    assert skipped.rc == 0, skipped.text
    assert "Skipped verification (--no-verify)" in skipped.stdout


# ---------------------------------------------------------------- 15
def test_bad_token_and_unreachable_github_have_distinct_messages(sb, stub):
    env = sb.use_stub(stub, sb.token)
    messages = {}
    for mode, needle in (("401", "GitHub rejected the token (401 Bad credentials)"),
                         ("500", "GitHub returned HTTP 500 while validating the token"),
                         ("delay", "could not reach GitHub to validate the token")):
        stub.mode = mode
        res = sb.init("--yes", via="venv", extra_env=env, label=f"init-{mode}")
        assert res.rc == 1, (mode, res.text)
        assert needle in res.stdout, (mode, res.text)
        assert "Traceback" not in res.text
        messages[mode] = needle
        nothing_written(sb)
    assert len(set(messages.values())) == 3
    assert {r["path"] for r in stub.requests} == {"/user"}
    assert stub.auth_headers() == {f"Bearer {sb.token}"}


# ---------------------------------------------------------------- negative control
def test_claude_status_check_can_fail_when_the_command_is_broken_after_init(sb):
    """init verification passes, then the command is broken: Claude's status must flip."""
    res = sb.init("--yes")
    assert res.rc == 0, res.text
    sb.assert_connected()
    sb.fake_tool("uvx", "echo 'broken after init' >&2\nexit 1")
    st = sb.claude_status("Failed", timeout=60)
    assert "Failed to connect" in st["get"].get("status", ""), st["get"]["raw"]
    assert st["get"].get("issue"), st["get"]["raw"]
    assert "Failed to connect" in st["list"] and "Connected" not in st["list"].replace("Failed to connect", "")
