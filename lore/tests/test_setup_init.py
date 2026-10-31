"""Tests for ``mcp-server-lore init`` prerequisites and registration (LORE-043).

The agent CLI is never invoked for real: ``ClaudeCodeAdapter`` takes an injected
runner, and ``run_init`` takes injected adapters and checks.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Optional

import pytest

from lore.setup import init as init_mod
from lore.setup.agents import (
    UNKNOWN_SCOPE,
    AgentAdapter,
    AgentError,
    ClaudeCodeAdapter,
    Registration,
    ServerSpec,
    parse_claude_get,
)
from lore.setup.checks import Check, check_docker, check_python, run_checks

# Output captured from the real `claude mcp get lore` CLI (Claude Code 2.1.316).
GET_OUTPUT = """lore:
  Scope: User config (available in all your projects)
  Status: ✘ Failed to connect
  Issue: ENOENT: Executable not found in $PATH: "uvx"
  Type: stdio
  Command: uvx
  Args: mcp-server-lore
  Environment:
    LORE_BACKEND=gists

To remove this server, run: claude mcp remove lore -s user
"""
GET_MISSING = 'No MCP server named "lore". Run `claude mcp add` to add one.\n'
GET_HTTP = """lore:
  Scope: User config (available in all your projects)
  Status: ✔ Connected
  Type: http
  URL: https://example.com/mcp

To remove this server, run: claude mcp remove lore -s user
"""


def _cp(stdout: str = "", stderr: str = "", rc: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], rc, stdout, stderr)


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------


class TestChecks:
    def test_python_ok_at_minimum(self):
        assert check_python((3, 11, 0)).ok

    def test_python_too_old_has_fix(self):
        c = check_python((3, 10, 14))
        assert not c.ok and "3.10.14" in c.detail and "3.11" in c.fix

    def test_all_present(self):
        checks = run_checks(which=lambda n: f"/bin/{n}", version_info=(3, 12, 0))
        assert [c.name for c in checks] == ["python", "claude", "uvx"]
        assert all(c.ok for c in checks)

    def test_missing_tools_report_fixes(self):
        checks = run_checks(which=lambda n: None, version_info=(3, 12, 0))
        failed = {c.name: c for c in checks if not c.ok}
        assert set(failed) == {"claude", "uvx"}
        assert "claude.ai/code" in failed["claude"].fix
        assert "astral.sh/uv" in failed["uvx"].fix

    def test_docker_only_checked_with_semantic(self):
        no_docker = lambda n: None if n == "docker" else f"/bin/{n}"  # noqa: E731
        assert all(c.ok for c in run_checks(which=no_docker, version_info=(3, 12, 0)))
        sem = run_checks(semantic=True, which=no_docker, version_info=(3, 12, 0))
        assert [c.name for c in sem if not c.ok] == ["docker"]
        assert "omit --semantic" in sem[-1].fix
        assert check_docker(lambda n: "/usr/bin/docker").ok


# --------------------------------------------------------------------------
# parsing and adapter
# --------------------------------------------------------------------------


class TestParse:
    def test_parses_real_output(self):
        reg = parse_claude_get(GET_OUTPUT)
        assert reg == Registration("stdio", "uvx", ("mcp-server-lore",), {"LORE_BACKEND": "gists"}, "user")

    def test_missing_server_is_none(self):
        assert parse_claude_get(GET_MISSING) is None

    @pytest.mark.parametrize("garbage", ["", "something unexpected", "Error: not logged in"])
    def test_unrecognised_output_is_an_error_not_absent(self, garbage):
        with pytest.raises(AgentError, match="could not understand"):
            parse_claude_get(garbage)

    def test_http_server_parses_as_non_stdio_conflict(self):
        reg = parse_claude_get(GET_HTTP)
        assert reg.transport == "http" and reg.command == ""
        assert not reg.matches(ServerSpec())

    def test_connected_status_variant(self):
        out = GET_OUTPUT.replace("✘ Failed to connect", "✔ Connected").replace(
            '  Issue: ENOENT: Executable not found in $PATH: "uvx"\n', "")
        assert parse_claude_get(out).matches(ServerSpec())

    def test_unknown_scope_is_reported_as_unknown(self):
        out = GET_OUTPUT.replace("User config", "Enterprise config")
        assert parse_claude_get(out).scope == UNKNOWN_SCOPE

    def test_empty_environment_block_and_colon_in_value(self):
        out = GET_OUTPUT.replace("    LORE_BACKEND=gists\n", "")
        assert parse_claude_get(out).env == {}
        out = GET_OUTPUT.replace("LORE_BACKEND=gists", "URL=http://h:1/x")
        assert parse_claude_get(out).env == {"URL": "http://h:1/x"}

    def test_args_with_spaces_are_split_so_they_conflict_safely(self):
        out = GET_OUTPUT.replace("Args: mcp-server-lore", "Args: mcp-server-lore --opt a b")
        assert not parse_claude_get(out).matches(ServerSpec())

    def test_scope_variants_and_multiple_env(self):
        out = GET_OUTPUT.replace("User config", "Local config").replace(
            "LORE_BACKEND=gists", "LORE_BACKEND=gists\n    A=b=c"
        )
        reg = parse_claude_get(out)
        assert reg.scope == "local"
        assert reg.env == {"LORE_BACKEND": "gists", "A": "b=c"}

    def test_no_args_or_env(self):
        reg = parse_claude_get("lore:\n  Scope: Project config\n  Type: stdio\n  Command: x\n")
        assert reg.args == () and reg.env == {} and reg.scope == "project"


class TestMatches:
    spec = ServerSpec()

    def test_identical(self):
        assert parse_claude_get(GET_OUTPUT).matches(self.spec)

    def test_extra_env_is_not_a_conflict(self):
        reg = Registration("stdio", "uvx", ("mcp-server-lore",), {"LORE_BACKEND": "gists", "LORE_GITHUB_TOKEN": "x"}, "user")
        assert reg.matches(self.spec)

    @pytest.mark.parametrize(
        "reg",
        [
            Registration("stdio", "python", ("mcp-server-lore",), {"LORE_BACKEND": "gists"}, "user"),
            Registration("stdio", "uvx", ("other",), {"LORE_BACKEND": "gists"}, "user"),
            Registration("stdio", "uvx", ("mcp-server-lore",), {"LORE_BACKEND": "selfhosted"}, "user"),
            Registration("stdio", "uvx", ("mcp-server-lore",), {}, "user"),
            Registration("http", "uvx", ("mcp-server-lore",), {"LORE_BACKEND": "gists"}, "user"),
        ],
    )
    def test_differences_conflict(self, reg):
        assert not reg.matches(self.spec)


class TestClaudeAdapter:
    def test_get_uses_cli_and_parses(self):
        calls = []
        adapter = ClaudeCodeAdapter(lambda cmd: calls.append(cmd) or _cp(GET_OUTPUT))
        assert adapter.get_registration("lore").command == "uvx"
        assert calls == [["claude", "mcp", "get", "lore"]]

    @pytest.mark.parametrize("rc", [0, 1])
    def test_missing_server_is_absent_regardless_of_exit_code_or_stream(self, rc):
        for kw in ({"stdout": GET_MISSING}, {"stderr": GET_MISSING}):
            adapter = ClaudeCodeAdapter(lambda cmd, kw=kw: _cp(rc=rc, **kw))
            assert adapter.get_registration("lore") is None

    def test_get_nonzero_exit_with_other_output_is_an_error_not_absent(self):
        adapter = ClaudeCodeAdapter(lambda cmd: _cp(stderr="Error: not logged in", rc=1))
        with pytest.raises(AgentError, match="'claude mcp get' failed.*not logged in"):
            adapter.get_registration("lore")

    def test_register_builds_command(self):
        calls = []
        ClaudeCodeAdapter(lambda cmd: calls.append(cmd) or _cp()).register(ServerSpec(), "user")
        assert calls == [["claude", "mcp", "add", "lore", "-s", "user", "-e", "LORE_BACKEND=gists", "--", "uvx", "mcp-server-lore"]]

    def test_remove_builds_command(self):
        calls = []
        ClaudeCodeAdapter(lambda cmd: calls.append(cmd) or _cp()).remove("lore", "local")
        assert calls == [["claude", "mcp", "remove", "lore", "-s", "local"]]

    def test_failure_raises_agent_error_with_detail(self):
        adapter = ClaudeCodeAdapter(lambda cmd: _cp(stderr="boom", rc=1))
        with pytest.raises(AgentError, match="register.*boom"):
            adapter.register(ServerSpec(), "user")
        with pytest.raises(AgentError, match="remove"):
            adapter.remove("lore", "user")


# --------------------------------------------------------------------------
# run_init
# --------------------------------------------------------------------------


class FakeAdapter(AgentAdapter):
    name = "Fake"

    def __init__(self, existing: Optional[Registration] = None, fail: bool = False):
        self.existing, self.fail, self.calls = existing, fail, []

    def get_registration(self, server):
        return self.existing

    def register(self, spec, scope):
        if self.fail:
            raise AgentError("'claude mcp register' failed: nope")
        self.calls.append(("register", spec.name, scope))

    def remove(self, server, scope):
        self.calls.append(("remove", server, scope))


GOOD = [Check("python", True, "Python 3.12")]
BAD = [Check("uvx", False, "'uvx' not found", "Install uv")]
SAME = Registration("stdio", "uvx", ("mcp-server-lore",), {"LORE_BACKEND": "gists"}, "user")
OTHER = Registration("stdio", "python", ("-m", "x"), {}, "local")


def _run(argv, adapter, checks=GOOD):
    lines: list[str] = []
    code = init_mod.run_init(
        argv,
        adapters={"claude": lambda: adapter},
        checks_fn=lambda semantic: checks,
        out=lines.append,
    )
    return code, "\n".join(lines)


class TestRunInit:
    def test_fresh_registers(self):
        a = FakeAdapter()
        code, out = _run([], a)
        assert code == 0 and a.calls == [("register", "lore", "user")]
        assert "registering" in out and "Done" in out

    def test_failed_prereq_stops_before_touching_agent(self):
        a = FakeAdapter()
        code, out = _run([], a, BAD)
        assert code == 1 and a.calls == []
        assert "fix: Install uv" in out

    def test_idempotent_when_already_configured(self):
        a = FakeAdapter(SAME)
        code, out = _run([], a)
        assert code == 0 and a.calls == [] and "already configured" in out

    def test_conflict_not_overwritten_without_force(self):
        a = FakeAdapter(OTHER)
        code, out = _run([], a)
        assert code == 1 and a.calls == []
        assert "--force" in out and "claude mcp remove lore -s local" in out

    def test_force_replaces_in_existing_scope(self):
        a = FakeAdapter(OTHER)
        code, _ = _run(["--force", "--scope", "project"], a)
        assert code == 0
        assert a.calls == [("remove", "lore", "local"), ("register", "lore", "project")]

    def test_dry_run_changes_nothing_fresh(self):
        a = FakeAdapter()
        code, out = _run(["--dry-run"], a)
        assert code == 0 and a.calls == []
        assert "[dry-run] registering" in out and "nothing was changed" in out

    def test_dry_run_force_changes_nothing(self):
        a = FakeAdapter(OTHER)
        code, out = _run(["--dry-run", "--force"], a)
        assert code == 0 and a.calls == []
        assert "[dry-run] removing" in out

    def test_agent_error_is_reported(self):
        code, out = _run([], FakeAdapter(fail=True))
        assert code == 1 and "nope" in out

    @pytest.mark.parametrize(
        "exc", [subprocess.TimeoutExpired("claude", 60), FileNotFoundError("claude")]
    )
    def test_cli_failures_are_reported(self, exc):
        class Boom(FakeAdapter):
            def get_registration(self, server):
                raise exc

        code, out = _run([], Boom())
        assert code == 1 and "could not run the agent CLI" in out

    @pytest.mark.parametrize("argv,expected", [([], False), (["--semantic"], True)])
    def test_semantic_flag_passed_to_checks(self, argv, expected):
        seen = []

        def record(semantic):
            seen.append(semantic)
            return GOOD

        init_mod.run_init(argv, adapters={"claude": FakeAdapter}, checks_fn=record, out=lambda _: None)
        assert seen == [expected]

    def test_prereq_failures_listed_with_fixes_and_agent_untouched(self):
        # Real checks with an old Python and no tools: every failure is listed.
        lines: list[str] = []
        a = FakeAdapter()
        code = init_mod.run_init(
            ["--dry-run", "--semantic"],
            adapters={"claude": lambda: a},
            checks_fn=lambda semantic: run_checks(semantic, which=lambda n: None, version_info=(3, 9, 0)),
            out=lines.append,
        )
        out = "\n".join(lines)
        assert code == 1 and a.calls == []
        for name in ("Python 3.9.0", "'claude'", "'uvx'", "Docker"):
            assert name in out
        assert out.count("fix:") == 4 and "Configuring" not in out

    def test_dry_run_with_conflict_and_no_force_fails_without_changes(self):
        a = FakeAdapter(OTHER)
        code, out = _run(["--dry-run"], a)
        assert code == 1 and a.calls == [] and "--force" in out

    def test_force_on_matching_registration_is_a_noop(self):
        a = FakeAdapter(SAME)
        code, out = _run(["--force"], a)
        assert code == 0 and a.calls == [] and "already configured" in out

    def test_matching_registration_in_other_scope_reports_that_scope(self):
        a = FakeAdapter(Registration("stdio", "uvx", ("mcp-server-lore",), {"LORE_BACKEND": "gists"}, "local"))
        code, out = _run(["--scope", "user"], a)
        assert code == 0 and a.calls == [] and "(local scope)" in out

    def test_force_remove_then_register_failure_tells_user(self):
        a = FakeAdapter(OTHER, fail=True)
        code, out = _run(["--force"], a)
        assert code == 1
        assert a.calls == [("remove", "lore", "local")]
        assert "previous 'lore' registration was already removed" in out

    def test_unknown_scope_conflict_is_never_force_removed(self):
        a = FakeAdapter(Registration("stdio", "python", (), {}, UNKNOWN_SCOPE))
        code, out = _run(["--force"], a)
        assert code == 1 and a.calls == [] and "will not guess" in out

    def test_http_registration_is_reported_as_conflict(self):
        a = FakeAdapter(Registration("http", "", (), {}, "user"))
        code, out = _run([], a)
        assert code == 1 and a.calls == [] and "http" in out


class StatefulClaude:
    """Fake `claude` CLI runner that remembers `mcp add` and replays `mcp get`."""

    def __init__(self, get_output: Optional[str] = None, add_rc: int = 0):
        self.commands: list[list[str]] = []
        self.get_output, self.add_rc = get_output, add_rc

    def __call__(self, cmd):
        self.commands.append(cmd)
        sub = cmd[2]
        if sub == "get":
            return _cp(self.get_output) if self.get_output else _cp(GET_MISSING, rc=1)
        if sub == "add":
            if self.add_rc == 0:
                env = "".join(f"    {cmd[i + 1]}\n" for i, x in enumerate(cmd) if x == "-e")
                dash = cmd.index("--")
                scope = cmd[cmd.index("-s") + 1].capitalize()
                self.get_output = (
                    f"lore:\n  Scope: {scope} config (x)\n  Type: stdio\n"
                    f"  Command: {cmd[dash + 1]}\n  Args: {' '.join(cmd[dash + 2:])}\n"
                    f"  Environment:\n{env}"
                )
            return _cp(rc=self.add_rc, stderr="denied" if self.add_rc else "")
        if sub == "remove":
            self.get_output = None
        return _cp()

    def subcommands(self) -> list[str]:
        return [c[2] for c in self.commands]


def _run_real_adapter(argv, runner):
    lines: list[str] = []
    code = init_mod.run_init(
        argv,
        adapters={"claude": lambda: ClaudeCodeAdapter(runner)},
        checks_fn=lambda semantic: GOOD,
        out=lines.append,
    )
    return code, "\n".join(lines)


class TestWithRealAdapter:
    """run_init + ClaudeCodeAdapter against a stateful fake CLI (no mocks of our own code)."""

    def test_what_register_writes_is_what_matches_accepts(self):
        runner = StatefulClaude()
        assert _run_real_adapter([], runner)[0] == 0
        assert runner.subcommands().count("add") == 1
        code, out = _run_real_adapter([], runner)  # second run
        assert code == 0 and "already configured" in out
        assert runner.subcommands().count("add") == 1  # no duplicate registration

    def test_dry_run_issues_no_mutating_commands(self):
        runner = StatefulClaude(get_output=GET_OUTPUT.replace("uvx", "python"))
        _run_real_adapter(["--dry-run", "--force"], runner)
        assert set(runner.subcommands()) == {"get"}

    def test_init_only_ever_reads_registers_or_removes(self):
        runner = StatefulClaude(get_output=GET_OUTPUT.replace("uvx", "python"))
        _run_real_adapter(["--force"], runner)
        assert all(c[:2] == ["claude", "mcp"] for c in runner.commands)
        assert set(runner.subcommands()) <= {"get", "add", "remove"}

    def test_scope_flag_round_trips_through_cli(self):
        runner = StatefulClaude()
        _run_real_adapter(["--scope", "project"], runner)
        code, out = _run_real_adapter(["--scope", "project"], runner)
        assert code == 0 and "(project scope)" in out
        assert runner.subcommands().count("add") == 1

    def test_real_subprocess_wrapper_with_stub_claude(self, tmp_path, monkeypatch):
        stub = tmp_path / "claude"
        stub.write_text("#!/bin/sh\necho 'No MCP server named \"lore\".'\nexit 1\n")
        stub.chmod(0o755)
        monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
        assert ClaudeCodeAdapter().get_registration("lore") is None

    def test_failed_add_is_reported(self):
        code, out = _run_real_adapter([], StatefulClaude(add_rc=1))
        assert code == 1 and "denied" in out

    def test_get_crash_does_not_fall_through_to_register(self):
        runner = lambda cmd: _cp(stderr="Error: not logged in", rc=1)  # noqa: E731
        calls = []
        code, out = _run_real_adapter([], lambda c: calls.append(c) or runner(c))
        assert code == 1 and "not logged in" in out
        assert [c[2] for c in calls] == ["get"]


# --------------------------------------------------------------------------
# main() dispatch
# --------------------------------------------------------------------------


class TestMainDispatch:
    def test_init_subcommand_exits_with_run_init_code(self, monkeypatch):
        from lore.mcp import server

        monkeypatch.setattr(init_mod, "run_init", lambda argv: 7 if argv == ["--dry-run"] else 0)
        monkeypatch.setattr(server.mcp, "run", lambda: pytest.fail("server must not start"))
        with pytest.raises(SystemExit) as exc:
            server.main(["init", "--dry-run"])
        assert exc.value.code == 7

    def test_no_args_starts_server(self, monkeypatch):
        from lore.mcp import server

        started = []
        monkeypatch.setattr(server.mcp, "run", lambda: started.append(1))
        server.main([])
        assert started == [1]


    def test_argv_none_reads_sys_argv(self, monkeypatch):
        from lore.mcp import server

        monkeypatch.setattr(sys, "argv", ["mcp-server-lore", "init", "--dry-run"])
        monkeypatch.setattr(init_mod, "run_init", lambda argv: 3 if argv == ["--dry-run"] else 0)
        with pytest.raises(SystemExit) as exc:
            server.main()
        assert exc.value.code == 3

    def test_init_help_and_bad_args_exit_cleanly(self, capsys):
        from lore.mcp import server

        with pytest.raises(SystemExit) as exc:
            server.main(["init", "--help"])
        assert exc.value.code == 0 and "mcp-server-lore init" in capsys.readouterr().out
        with pytest.raises(SystemExit) as exc:
            server.main(["init", "--bogus"])
        assert exc.value.code == 2

    def test_end_to_end_through_main_with_real_adapter(self, monkeypatch, capsys):
        from lore.mcp import server
        from lore.setup import agents

        runner = StatefulClaude()
        monkeypatch.setattr(agents, "_run", runner)
        monkeypatch.setattr(agents.ClaudeCodeAdapter, "__init__", lambda self, r=runner: setattr(self, "_run", r))
        monkeypatch.setattr(init_mod, "run_checks", lambda semantic: GOOD)
        monkeypatch.setattr(init_mod, "ADAPTERS", {"claude": agents.ClaudeCodeAdapter})
        with pytest.raises(SystemExit) as exc:
            server.main(["init"])
        assert exc.value.code == 0
        assert runner.subcommands() == ["get", "add"]

    def test_console_script_points_at_main(self):
        import tomllib
        from pathlib import Path

        data = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text())
        assert data["project"]["scripts"]["mcp-server-lore"] == "lore.mcp.server:main"
