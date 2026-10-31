"""Tests for token resolution, validation, redaction and state init (LORE-044).

No network, no real ``gh``, no real home directory.
"""

from __future__ import annotations

import os
import subprocess
from types import SimpleNamespace

import pytest
import requests

from lore.core.auth import REDACTED, gh_auth_token, redact, resolve_github_token
from lore.setup import auth as auth_mod
from lore.setup import init as init_mod
from lore.setup.agents import AgentError, ClaudeCodeAdapter, Registration, ServerSpec
from lore.setup.checks import Check, run_checks
from lore.setup.state import ensure_state

ENV_TOKEN = "ghp_" + "E" * 36
GH_TOKEN = "gho_" + "G" * 36
PROMPT_TOKEN = "ghp_" + "P" * 36
PLAIN_SECRET = "s3cr3t-not-github-shaped"  # matches no token regex: only wiring can redact it


def _gh(stdout=GH_TOKEN + "\n", rc=0):
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, rc, stdout=stdout, stderr="")

    run.calls = calls
    return run


which_gh = lambda n: "/usr/bin/gh"  # noqa: E731
no_gh = lambda n: None  # noqa: E731


class TestCoreAuth:
    def test_env_token_wins_and_gh_not_consulted(self):
        run = _gh()
        env = {"LORE_GITHUB_TOKEN": ENV_TOKEN, "LORE_TOKEN_FROM_GH": "1"}
        assert resolve_github_token(env, which_gh, run) == ENV_TOKEN
        assert run.calls == []

    def test_gh_only_with_opt_in(self):
        run = _gh()
        assert resolve_github_token({}, which_gh, run) is None
        assert run.calls == []
        assert resolve_github_token({"LORE_TOKEN_FROM_GH": "1"}, which_gh, run) == GH_TOKEN
        assert run.calls[0][0] == ["gh", "auth", "token"]
        assert run.calls[0][1]["timeout"] == 5

    @pytest.mark.parametrize("which,run", [
        (no_gh, _gh()),
        (which_gh, _gh(rc=1)),
        (which_gh, _gh(stdout="  \n")),
        (which_gh, lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("gh", 5))),
        (which_gh, lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("gh"))),
    ])
    def test_gh_failures_give_none(self, which, run):
        assert gh_auth_token(which, run) is None

    def test_redact_explicit_and_pattern(self):
        text = f"boom {PROMPT_TOKEN} and custom-secret-value and {GH_TOKEN}"
        out = redact(text, ["custom-secret-value", None, ""])
        assert PROMPT_TOKEN not in out and GH_TOKEN not in out
        assert "custom-secret-value" not in out and REDACTED in out


class TestResolveToken:
    def test_env_beats_gh_beats_prompt(self):
        run = _gh()
        r = auth_mod.resolve_token(env={"LORE_GITHUB_TOKEN": ENV_TOKEN}, which=which_gh, run=run,
                                   interactive=True, prompt=lambda _: pytest.fail("prompted"))
        assert (r.token, r.source) == (ENV_TOKEN, "env") and run.calls == []
        r = auth_mod.resolve_token(env={}, which=which_gh, run=run, interactive=True,
                                   prompt=lambda _: pytest.fail("prompted"))
        assert (r.token, r.source) == (GH_TOKEN, "gh")

    def test_prompt_strips_whitespace_and_points_to_token_page(self):
        lines = []
        r = auth_mod.resolve_token(env={}, which=no_gh, interactive=True,
                                   prompt=lambda _: PROMPT_TOKEN + " \t\n", out=lines.append)
        assert (r.token, r.source) == (PROMPT_TOKEN, "prompt")
        assert "settings/tokens/new?scopes=gist&description=AgentLore" in "\n".join(lines)

    def test_empty_prompt_means_no_token(self):
        r = auth_mod.resolve_token(env={}, which=no_gh, interactive=True, prompt=lambda _: "  ",
                                   out=lambda _: None)
        assert r.token is None

    @pytest.mark.parametrize("allow,interactive", [(False, True), (True, False)])
    def test_never_prompts_without_tty_or_with_yes(self, allow, interactive):
        r = auth_mod.resolve_token(env={}, which=no_gh, allow_prompt=allow, interactive=interactive,
                                   prompt=lambda _: pytest.fail("prompted"))
        assert r.token is None

    def test_repr_hides_token(self):
        assert ENV_TOKEN not in repr(auth_mod.TokenResult(ENV_TOKEN, "env"))


def _http(status=200, scopes="repo, gist", login="octo"):
    def get(url, headers=None, timeout=None):
        assert url == "https://api.github.com/user"
        h = {} if scopes is None else {"X-OAuth-Scopes": scopes}
        return SimpleNamespace(status_code=status, headers=h, json=lambda: {"login": login})

    return get


class TestValidate:
    def test_ok(self):
        assert auth_mod.validate_token(ENV_TOKEN, _http()) == "octo"

    def test_fine_grained_token_without_scope_header_is_accepted(self):
        assert auth_mod.validate_token(ENV_TOKEN, _http(scopes=None)) == "octo"

    def test_401_is_clear(self):
        with pytest.raises(auth_mod.AuthError, match="401"):
            auth_mod.validate_token(ENV_TOKEN, _http(status=401))

    def test_missing_gist_scope(self):
        with pytest.raises(auth_mod.AuthError, match="gist"):
            auth_mod.validate_token(ENV_TOKEN, _http(scopes="repo"))

    def test_unreadable_json_is_an_auth_error(self):
        def get(url, headers=None, timeout=None):
            def bad():
                raise ValueError("not json")

            return SimpleNamespace(status_code=200, headers={}, json=bad)

        with pytest.raises(auth_mod.AuthError):
            auth_mod.validate_token(ENV_TOKEN, get)

    def test_other_status_and_network_error(self):
        with pytest.raises(auth_mod.AuthError, match="500"):
            auth_mod.validate_token(ENV_TOKEN, _http(status=500))

        def boom(*a, **k):
            raise requests.ConnectionError(f"failed with {ENV_TOKEN}")

        with pytest.raises(auth_mod.AuthError) as ei:
            auth_mod.validate_token(ENV_TOKEN, boom)
        assert ENV_TOKEN not in str(ei.value)


class TestEnsureState:
    def test_creates_with_modes(self, tmp_path):
        created = ensure_state(tmp_path)
        assert [p.name for p in created] == [".lore", "session.json"]
        assert (tmp_path / ".lore" / "session.json").read_text() == "[]"
        assert (tmp_path / ".lore").stat().st_mode & 0o777 == 0o700
        assert (tmp_path / ".lore" / "session.json").stat().st_mode & 0o777 == 0o600

    def test_idempotent_and_never_modifies_existing(self, tmp_path):
        d = tmp_path / ".lore"
        d.mkdir(mode=0o755)
        (d / "session.json").write_text('[{"keep": 1}]')
        (d / "other.json").write_text("x")
        before = (d / "session.json").stat().st_mtime_ns
        assert ensure_state(tmp_path) == []
        assert (d / "session.json").read_text() == '[{"keep": 1}]'
        assert (d / "session.json").stat().st_mtime_ns == before
        assert d.stat().st_mode & 0o777 == 0o755
        assert (d / "other.json").read_text() == "x"
        assert ensure_state(tmp_path) == []

    def test_symlinked_session_is_left_alone(self, tmp_path):
        d = tmp_path / ".lore"
        d.mkdir()
        target = tmp_path / "elsewhere.json"
        target.write_text("precious")
        (d / "session.json").symlink_to(target)
        assert ensure_state(tmp_path) == []
        assert target.read_text() == "precious" and (d / "session.json").is_symlink()

    def test_dangling_session_symlink_is_not_followed_or_created(self, tmp_path):
        d = tmp_path / ".lore"
        d.mkdir()
        (d / "session.json").symlink_to(tmp_path / "missing.json")
        assert ensure_state(tmp_path) == []
        assert not (tmp_path / "missing.json").exists()

    def test_symlinked_dir_to_existing_dir_is_used_as_is(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        (tmp_path / ".lore").symlink_to(real)
        ensure_state(tmp_path)
        assert (real / "session.json").read_text() == "[]"
        assert (tmp_path / ".lore").is_symlink()

    def test_dangling_dir_symlink_warns_and_creates_nothing(self, tmp_path):
        (tmp_path / ".lore").symlink_to(tmp_path / "gone")
        warnings = []
        assert ensure_state(tmp_path, warn=warnings.append) == []
        assert len(warnings) == 1 and not (tmp_path / "gone").exists()

    def test_dir_that_is_a_file_warns(self, tmp_path):
        (tmp_path / ".lore").write_text("x")
        warnings = []
        assert ensure_state(tmp_path, warn=warnings.append) == []
        assert warnings and (tmp_path / ".lore").read_text() == "x"

    def test_concurrent_creation_is_left_alone(self, tmp_path, monkeypatch):
        d = tmp_path / ".lore"
        d.mkdir()
        (d / "session.json").write_text("mine")
        real = os.path.lexists
        monkeypatch.setattr(os.path, "lexists",
                            lambda p: False if str(p).endswith("session.json") else real(p))
        assert ensure_state(tmp_path) == []
        assert (d / "session.json").read_text() == "mine"


class TestRegistrationSecrets:
    def test_unrelated_registered_token_does_not_conflict_without_store_token(self):
        reg = Registration("stdio", "uvx", ("mcp-server-lore",),
                           {"LORE_BACKEND": "gists", "LORE_GITHUB_TOKEN": "old"}, "user")
        assert reg.matches(ServerSpec())

    def test_stored_token_is_compared_and_never_shown(self):
        spec = ServerSpec(secrets={"LORE_GITHUB_TOKEN": PLAIN_SECRET})
        base = {"LORE_BACKEND": "gists"}
        same = Registration("stdio", "uvx", ("mcp-server-lore",), {**base, "LORE_GITHUB_TOKEN": PLAIN_SECRET}, "user")
        rotated = Registration("stdio", "uvx", ("mcp-server-lore",), {**base, "LORE_GITHUB_TOKEN": "old-one"}, "user")
        absent = Registration("stdio", "uvx", ("mcp-server-lore",), base, "user")
        assert same.matches(spec)
        for reg in (rotated, absent):
            reason = reg.mismatch_reason(spec)
            assert reason and "differs" in reason
            assert PLAIN_SECRET not in reason and "old-one" not in reason

    def test_repr_hides_env_values_and_spec_secrets(self):
        spec = ServerSpec(secrets={"LORE_GITHUB_TOKEN": ENV_TOKEN})
        reg = Registration("stdio", "uvx", ("a",), {"LORE_GITHUB_TOKEN": ENV_TOKEN}, "user")
        assert ENV_TOKEN not in repr(spec) and ENV_TOKEN not in repr(reg)

    def test_read_only_mismatch_in_both_directions(self):
        ro = ServerSpec(env={"LORE_BACKEND": "gists", "LORE_READ_ONLY": "1"})
        rw = ServerSpec()
        reg_ro = Registration("stdio", "uvx", ("mcp-server-lore",),
                              {"LORE_BACKEND": "gists", "LORE_READ_ONLY": "1"}, "user")
        reg_rw = Registration("stdio", "uvx", ("mcp-server-lore",), {"LORE_BACKEND": "gists"}, "user")
        assert reg_ro.matches(ro) and reg_rw.matches(rw)
        assert not reg_ro.matches(rw) and not reg_rw.matches(ro)

    def test_adapter_error_redacts_stderr(self):
        leaked = f"error: bad flag LORE_GITHUB_TOKEN={PLAIN_SECRET} and {PLAIN_SECRET}"
        runner = lambda cmd: subprocess.CompletedProcess(cmd, 1, stdout="", stderr=leaked)  # noqa: E731
        spec = ServerSpec(secrets={"LORE_GITHUB_TOKEN": PLAIN_SECRET})
        with pytest.raises(AgentError) as ei:
            ClaudeCodeAdapter(runner).register(spec, "user")
        assert PLAIN_SECRET not in str(ei.value) and PLAIN_SECRET not in str(ei.value)

    def test_get_and_remove_failures_redact_adapter_secrets(self):
        leaked = f"boom {PLAIN_SECRET}"
        runner = lambda cmd: subprocess.CompletedProcess(cmd, 1, stdout="", stderr=leaked)  # noqa: E731
        ad = ClaudeCodeAdapter(runner)
        ad.secrets = [PLAIN_SECRET]
        with pytest.raises(AgentError) as e1:
            ad.get_registration("lore")
        with pytest.raises(AgentError) as e2:
            ad.remove("lore", "user")
        assert PLAIN_SECRET not in str(e1.value) and PLAIN_SECRET not in str(e2.value)

    def test_store_token_is_the_only_path_with_token_in_argv(self):
        cmds = []
        runner = lambda cmd: cmds.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")  # noqa: E731
        ClaudeCodeAdapter(runner).register(ServerSpec(), "user")
        assert ENV_TOKEN not in " ".join(cmds[0])
        ClaudeCodeAdapter(runner).register(ServerSpec(secrets={"LORE_GITHUB_TOKEN": ENV_TOKEN}), "user")
        assert f"LORE_GITHUB_TOKEN={ENV_TOKEN}" in cmds[1]


# --------------------------------------------------------------------------
# run_init integration (fake adapter, injected verification)
# --------------------------------------------------------------------------

GOOD = [Check("python", True, "Python 3.12")]


class RecAdapter(ClaudeCodeAdapter):
    name = "Rec"

    def __init__(self, fail_msg=None):
        self.registered = []
        self.fail_msg = fail_msg

    def get_registration(self, server):
        return None

    def register(self, spec, scope):
        if self.fail_msg:
            raise AgentError(self.fail_msg)
        self.registered.append(spec)

    def remove(self, server, scope):  # pragma: no cover
        pass


def _init(argv, tmp_path, env=None, token_fn=None, adapter=None, verify=None, validate=None,
          interactive=False, spec=None):
    from lore.setup.verify import VerifyResult

    lines: list[str] = []
    adapter = adapter or RecAdapter()
    verify_calls = []

    def vf(cmd, args, env_, **kw):
        verify_calls.append((cmd, list(args), dict(env_)))
        return verify or VerifyResult(True, "ok", ["t"] * 5, 1, [], "REST CLI around a REST API")

    (tmp_path / "home").mkdir(exist_ok=True)
    code = init_mod.run_init(
        argv,
        adapters={"claude": lambda: adapter},
        checks_fn=lambda semantic, local=False: GOOD,
        out=lines.append,
        env=env if env is not None else {},
        home=tmp_path / "home",
        token_fn=token_fn,
        validate_fn=validate or (lambda t: "octo"),
        verify_fn=vf,
        interactive=interactive,
        spec=spec,
    )
    return code, "\n".join(lines), adapter, verify_calls


def _tok(token, source):
    return lambda **kw: auth_mod.TokenResult(token, source)


class TestInitAuthModes:
    def test_gh_token_not_stored_and_flag_registered(self, tmp_path):
        code, out, ad, vc = _init([], tmp_path, token_fn=_tok(GH_TOKEN, "gh"))
        spec = ad.registered[0]
        assert code == 0
        assert spec.env == {"LORE_BACKEND": "gists", "LORE_TOKEN_FROM_GH": "1"} and not spec.secrets
        assert GH_TOKEN not in out
        # verification uses the registered env only: the server resolves the gh token itself
        assert "LORE_GITHUB_TOKEN" not in vc[0][2] and vc[0][2]["LORE_TOKEN_FROM_GH"] == "1"

    def test_env_token_not_stored_by_default_and_says_so(self, tmp_path):
        code, out, ad, _ = _init([], tmp_path, token_fn=_tok(ENV_TOKEN, "env"))
        assert code == 0 and not ad.registered[0].secrets
        assert "--store-token" in out and ENV_TOKEN not in out

    def test_store_token_stores_warns_and_never_prints(self, tmp_path):
        code, out, ad, _ = _init(["--store-token"], tmp_path, token_fn=_tok(PLAIN_SECRET, "prompt"))
        assert ad.registered[0].secrets == {"LORE_GITHUB_TOKEN": PLAIN_SECRET}
        assert "PLAIN TEXT" in out and PLAIN_SECRET not in out

    def test_agent_error_text_is_redacted(self, tmp_path):
        ad = RecAdapter(fail_msg=f"claude said {PLAIN_SECRET}")
        code, out, _, _ = _init(["--store-token"], tmp_path, token_fn=_tok(PLAIN_SECRET, "env"), adapter=ad)
        assert code == 1 and PLAIN_SECRET not in out and REDACTED in out

    def test_token_in_adapter_error_is_redacted_even_without_store_token(self, tmp_path):
        ad = RecAdapter(fail_msg=f"claude said {PLAIN_SECRET}")
        code, out, _, _ = _init([], tmp_path, token_fn=_tok(PLAIN_SECRET, "env"), adapter=ad)
        assert code == 1 and PLAIN_SECRET not in out

    def test_no_token_registers_read_only_and_explains(self, tmp_path):
        code, out, ad, vc = _init(["--semantic-url", "http://sem:1"], tmp_path,
                                  token_fn=_tok(None, None))
        assert ad.registered[0].env == {"LORE_BACKEND": "gists", "LORE_READ_ONLY": "1",
                                        "LORE_SEMANTIC_URL": "http://sem:1"}
        for phrase in ("READ-ONLY DEMO", "publishing and rating are disabled",
                       "bundled curated examples", "needs a semantic server"):
            assert phrase in out
        assert "LORE_GITHUB_TOKEN" not in vc[0][2]

    def test_unstored_env_token_is_injected_in_memory_with_warning(self, tmp_path):
        code, out, ad, vc = _init([], tmp_path, token_fn=_tok(PLAIN_SECRET, "env"))
        assert vc[0][2]["LORE_GITHUB_TOKEN"] == PLAIN_SECRET and not ad.registered[0].secrets
        assert "verification used the token from your shell" in out and PLAIN_SECRET not in out

    def test_stored_token_is_in_verify_env_without_warning(self, tmp_path):
        code, out, _, vc = _init(["--store-token"], tmp_path, token_fn=_tok(PLAIN_SECRET, "env"))
        assert vc[0][2]["LORE_GITHUB_TOKEN"] == PLAIN_SECRET and "verification used" not in out

    def test_semantic_url_userinfo_is_not_printed(self, tmp_path):
        _, out, _, _ = _init(["--semantic-url", "http://user:hunter2@sem:1"], tmp_path,
                             token_fn=_tok(None, None))
        assert "hunter2" not in out and "http://***@sem:1" in out

    def test_semantic_url_from_env(self, tmp_path):
        _, _, ad, _ = _init([], tmp_path, env={"LORE_SEMANTIC_URL": "http://e:2"},
                            token_fn=_tok(None, None))
        assert ad.registered[0].env["LORE_SEMANTIC_URL"] == "http://e:2"

    def test_invalid_token_stops_before_registration(self, tmp_path):
        def bad(t):
            raise auth_mod.AuthError("GitHub rejected the token (401 Bad credentials)")

        code, out, ad, _ = _init([], tmp_path, token_fn=_tok(ENV_TOKEN, "env"), validate=bad)
        assert code == 1 and "401" in out and ad.registered == []

    def test_yes_never_prompts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(auth_mod, "gh_auth_token", lambda *a, **k: None)
        monkeypatch.setattr(
            "getpass.getpass", lambda *a: pytest.fail("prompted")
        )
        code, out, ad, _ = _init(["--yes"], tmp_path, token_fn=None, interactive=True)
        assert code == 0 and ad.registered[0].env["LORE_READ_ONLY"] == "1"

    def test_state_created_in_given_home_only(self, tmp_path):
        _init([], tmp_path, token_fn=_tok(None, None))
        assert (tmp_path / "home" / ".lore" / "session.json").read_text() == "[]"

    def test_dry_run_no_state_no_verify_no_validation(self, tmp_path):
        def no(*a):
            pytest.fail("validated")

        code, out, ad, vc = _init(["--dry-run"], tmp_path, token_fn=_tok(ENV_TOKEN, "env"), validate=no)
        assert code == 0 and ad.registered == [] and vc == []
        assert not (tmp_path / "home" / ".lore").exists()

    def test_no_verify_skips_verification(self, tmp_path):
        code, out, _, vc = _init(["--no-verify"], tmp_path, token_fn=_tok(None, None))
        assert code == 0 and vc == [] and "Skipped verification" in out

    def test_verification_failure_exits_1_with_fix(self, tmp_path):
        from lore.setup.verify import VerifyResult

        code, out, _, _ = _init([], tmp_path, token_fn=_tok(None, None),
                                verify=VerifyResult(False, "boom"))
        assert code == 1 and "verification failed: boom" in out and "fix:" in out

    def test_fallback_warning_is_reported_but_succeeds(self, tmp_path):
        from lore.setup.verify import VerifyResult

        code, out, _, _ = _init([], tmp_path, token_fn=_tok(ENV_TOKEN, "env"),
                                verify=VerifyResult(True, "ok", ["t"] * 5, 1, ["used fallback"]))
        assert code == 0 and "warning: used fallback" in out


class ModeAdapter(RecAdapter):
    """Adapter holding one existing registration; records remove/register."""

    def __init__(self, existing):
        super().__init__()
        self.existing, self.removed = existing, []

    def get_registration(self, server):
        return self.existing

    def remove(self, server, scope):
        self.removed.append(scope)


RO_REG = Registration("stdio", "uvx", ("mcp-server-lore",),
                      {"LORE_BACKEND": "gists", "LORE_READ_ONLY": "1"}, "user")
TOKEN_REG = Registration("stdio", "uvx", ("mcp-server-lore",),
                         {"LORE_BACKEND": "gists", "LORE_TOKEN_FROM_GH": "1"}, "user")


class TestModeSwitching:
    def test_read_only_to_token_conflicts_and_creates_nothing(self, tmp_path):
        ad = ModeAdapter(RO_REG)
        code, out, _, vc = _init([], tmp_path, token_fn=_tok(GH_TOKEN, "gh"), adapter=ad)
        assert code == 1 and ad.registered == [] and ad.removed == [] and vc == []
        assert "read-only mode" in out and "--force" in out
        assert not (tmp_path / "home" / ".lore").exists()

    def test_token_to_read_only_conflicts(self, tmp_path):
        ad = ModeAdapter(TOKEN_REG)
        code, out, _, _ = _init([], tmp_path, token_fn=_tok(None, None), adapter=ad)
        assert code == 1 and "no token is available" in out and ad.registered == []

    def test_force_replaces_in_both_directions(self, tmp_path):
        ad = ModeAdapter(RO_REG)
        code, _, _, _ = _init(["--force"], tmp_path, token_fn=_tok(GH_TOKEN, "gh"), adapter=ad)
        assert code == 0 and ad.removed == ["user"]
        assert ad.registered[0].env["LORE_TOKEN_FROM_GH"] == "1"
        ad = ModeAdapter(TOKEN_REG)
        code, _, _, _ = _init(["--force"], tmp_path, token_fn=_tok(None, None), adapter=ad)
        assert code == 0 and ad.registered[0].env["LORE_READ_ONLY"] == "1"

    def test_rotated_stored_token_is_a_conflict_not_already_configured(self, tmp_path):
        reg = Registration("stdio", "uvx", ("mcp-server-lore",),
                           {"LORE_BACKEND": "gists", "LORE_GITHUB_TOKEN": "old-secret-value"}, "user")
        ad = ModeAdapter(reg)
        code, out, _, _ = _init(["--store-token"], tmp_path, token_fn=_tok(PLAIN_SECRET, "env"), adapter=ad)
        assert code == 1 and "differs" in out and "already configured" not in out
        assert "old-secret-value" not in out and PLAIN_SECRET not in out

    def test_dangling_state_symlink_warns_and_continues(self, tmp_path):
        (tmp_path / "home").mkdir()
        (tmp_path / "home" / ".lore").symlink_to(tmp_path / "gone")
        code, out, _, _ = _init([], tmp_path, token_fn=_tok(None, None))
        assert code == 0 and "not a usable directory" in out


class TestProjectScopeNeverStoresToken:
    def test_store_token_with_project_scope_is_refused_before_anything(self, tmp_path):
        ad = RecAdapter()
        called = []
        ad.get_registration = lambda server: called.append(1)
        code, out, _, vc = _init(["--store-token", "--scope", "project"], tmp_path,
                                 token_fn=lambda **kw: pytest.fail("auth ran"), adapter=ad)
        assert code == 1 and ".mcp.json" in out and "--scope user" in out
        assert called == [] and ad.registered == [] and vc == []
        assert not (tmp_path / "home" / ".lore").exists()

    def test_existing_project_registration_is_not_given_a_token(self, tmp_path):
        reg = Registration("stdio", "uvx", ("mcp-server-lore",), {"LORE_BACKEND": "gists"}, "project")
        ad = ModeAdapter(reg)
        code, out, _, _ = _init(["--store-token", "--scope", "user"], tmp_path,
                                token_fn=_tok(PLAIN_SECRET, "env"), adapter=ad)
        assert code == 1 and "project-scope 'lore' registration already exists" in out
        assert "claude mcp remove lore -s project" in out and PLAIN_SECRET not in out
        assert ad.registered == [] and ad.removed == []
        assert not (tmp_path / "home" / ".lore").exists()

    @pytest.mark.parametrize("scope", ["user", "local"])
    def test_other_scopes_can_store(self, tmp_path, scope):
        code, out, ad, _ = _init(["--store-token", "--scope", scope], tmp_path,
                                 token_fn=_tok(PLAIN_SECRET, "env"))
        assert code == 0 and ad.registered[0].secrets and PLAIN_SECRET not in out

    def test_project_scope_without_store_token_works(self, tmp_path):
        code, _, ad, _ = _init(["--scope", "project"], tmp_path, token_fn=_tok(PLAIN_SECRET, "env"))
        assert code == 0 and not ad.registered[0].secrets


    @pytest.mark.parametrize("extra", [[], ["--dry-run"]])
    def test_spec_with_secret_is_refused_at_project_scope(self, tmp_path, extra):
        spec = ServerSpec(secrets={"LORE_GITHUB_TOKEN": PLAIN_SECRET})
        ad = RecAdapter()
        code, out, _, vc = _init(["--scope", "project", *extra], tmp_path,
                                 token_fn=_tok(PLAIN_SECRET, "env"), adapter=ad, spec=spec)
        assert code == 1 and ".mcp.json" in out and PLAIN_SECRET not in out
        assert ad.registered == [] and vc == []
        assert not (tmp_path / "home" / ".lore").exists()


class TestProjectScopeSemanticUrl:
    @pytest.mark.parametrize("url", [
        "http://user:pw@sem:1", "https://sem/x?key=abc", "https://sem/x#frag", "https://u@sem",
        "user:pw@host:1", "user@host", "https:u:p@h", "https://host/path@secret", "host:8766",
    ])
    def test_credentialed_url_refused_for_project_scope(self, tmp_path, url):
        ad = RecAdapter()
        code, out, _, _ = _init(["--scope", "project", "--semantic-url", url], tmp_path,
                                token_fn=_tok(None, None), adapter=ad)
        assert code == 1 and "semantic URL" in out and "pw" not in out and "abc" not in out
        assert "secret" not in out
        assert ad.registered == [] and not (tmp_path / "home" / ".lore").exists()

    def test_env_url_also_checked(self, tmp_path):
        code, out, ad, _ = _init(["--scope", "project"], tmp_path,
                                 env={"LORE_SEMANTIC_URL": "http://u:p@sem:1"}, token_fn=_tok(None, None))
        assert code == 1 and ad.registered == []

    @pytest.mark.parametrize("url", ["https://host", "http://host:8766", "https://host:1/api/v1"])
    def test_plain_urls_accepted_for_project(self, tmp_path, url):
        code, _, ad, _ = _init(["--scope", "project", "--semantic-url", url], tmp_path,
                               token_fn=_tok(None, None))
        assert code == 0 and ad.registered[0].env["LORE_SEMANTIC_URL"] == url

    def test_plain_url_ok_for_project_and_credentialed_ok_for_user(self, tmp_path):
        code, _, ad, _ = _init(["--scope", "project", "--semantic-url", "https://sem.example:8766"],
                               tmp_path, token_fn=_tok(None, None))
        assert code == 0 and ad.registered[0].env["LORE_SEMANTIC_URL"] == "https://sem.example:8766"
        code, _, ad, _ = _init(["--scope", "user", "--semantic-url", "http://u:p@sem:1"],
                               tmp_path, token_fn=_tok(None, None))
        assert code == 0


class TestLocalMode:
    def test_spec_uses_this_interpreter(self, tmp_path):
        import sys

        code, out, ad, vc = _init(["--local"], tmp_path, token_fn=_tok(None, None))
        spec = ad.registered[0]
        assert code == 0 and spec.command == sys.executable and spec.args == ("-m", "lore.mcp.server")
        assert spec.env["LORE_READ_ONLY"] == "1"
        assert vc[0][0] == sys.executable and vc[0][1] == ["-m", "lore.mcp.server"]  # verify runs it
        assert f"registering 'lore': {sys.executable} -m lore.mcp.server" in out

    def test_dry_run_states_the_command(self, tmp_path):
        import sys

        code, out, ad, vc = _init(["--local", "--dry-run"], tmp_path, token_fn=_tok(None, None))
        assert code == 0 and ad.registered == [] and vc == []
        assert f"[dry-run] registering 'lore': {sys.executable} -m lore.mcp.server" in out

    def test_uvx_check_skipped_only_for_local(self):
        no_uvx = lambda n: None if n == "uvx" else f"/bin/{n}"  # noqa: E731
        kw = dict(which=no_uvx, version_info=(3, 12, 0))
        assert [c.name for c in run_checks(local=True, **kw) if not c.ok] == []
        assert [c.name for c in run_checks(**kw) if not c.ok] == ["uvx"]

    def test_checks_receive_local_flag(self, tmp_path):
        seen = []
        from lore.setup.verify import VerifyResult

        (tmp_path / "home").mkdir(exist_ok=True)
        init_mod.run_init(
            ["--local", "--dry-run"], adapters={"claude": RecAdapter},
            checks_fn=lambda semantic, local=False: seen.append(local) or GOOD, out=lambda _: None,
            env={}, home=tmp_path / "home", token_fn=_tok(None, None))
        assert seen == [True]

    def test_uvx_and_local_registrations_conflict_both_ways(self, tmp_path):
        import sys

        local_reg = Registration("stdio", sys.executable, ("-m", "lore.mcp.server"),
                                 {"LORE_BACKEND": "gists", "LORE_READ_ONLY": "1"}, "user")
        code, out, ad, _ = _init([], tmp_path, token_fn=_tok(None, None), adapter=ModeAdapter(local_reg))
        assert code == 1 and "different command" in out
        uvx_reg = Registration("stdio", "uvx", ("mcp-server-lore",),
                               {"LORE_BACKEND": "gists", "LORE_READ_ONLY": "1"}, "user")
        code, out, _, _ = _init(["--local"], tmp_path, token_fn=_tok(None, None), adapter=ModeAdapter(uvx_reg))
        assert code == 1 and "different command" in out
        code, out, _, _ = _init(["--local"], tmp_path, token_fn=_tok(None, None), adapter=ModeAdapter(local_reg))
        assert code == 0 and "already configured" in out
