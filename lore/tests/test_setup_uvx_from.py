"""Tests for the test-only ``LORE_INIT_UVX_FROM`` hook of ``init`` (ADR-016)."""

from __future__ import annotations

import sys

import pytest

from lore.setup import auth as auth_mod
from lore.setup import init as init_mod
from lore.setup import verify as verify_mod
from lore.setup.agents import Registration, ServerSpec
from lore.setup.checks import Check
from lore.tests.test_setup_init import FakeAdapter

ENV = "LORE_INIT_UVX_FROM"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(auth_mod, "validate_token", lambda token, http=None: "tester")


def _run(argv, adapter, env, verify=None):
    lines: list[str] = []
    code = init_mod.run_init(
        argv,
        adapters={"claude": lambda: adapter},
        checks_fn=lambda semantic, **k: [Check("python", True, "ok")],
        out=lines.append,
        env=env,
        verify_fn=verify or (lambda *a, **k: verify_mod.VerifyResult(True, "ok", ["t"] * 5, 1)),
    )
    return code, "\n".join(lines)


def _wheel(tmp_path, name="lore-0.1-py3-none-any.whl"):
    p = tmp_path / name
    p.write_bytes(b"x")
    return p


class RecordingAdapter(FakeAdapter):
    def register(self, spec: ServerSpec, scope):
        super().register(spec, scope)
        self.spec = spec


@pytest.mark.parametrize("name", ["a.whl", "a-1.0.tar.gz"])
def test_registers_uvx_from_abs_path(tmp_path, name):
    p = _wheel(tmp_path, name)
    a = RecordingAdapter()
    code, out = _run([], a, {ENV: str(p)})
    assert code == 0
    assert a.spec.command == "uvx"
    assert a.spec.args == ("--from", str(p.resolve()), "mcp-server-lore")
    assert "TEST-ONLY" in out and str(p) in out


def test_relative_path_made_absolute(tmp_path, monkeypatch):
    _wheel(tmp_path)
    monkeypatch.chdir(tmp_path)
    a = RecordingAdapter()
    assert _run([], a, {ENV: "lore-0.1-py3-none-any.whl"})[0] == 0
    assert a.spec.args[1] == str(tmp_path / "lore-0.1-py3-none-any.whl")


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com/x.whl",
        "file:///tmp/x.whl",
        "git+https://github.com/x/y.git",
        "/nonexistent/x.whl",
        "{tmp}/dir.whl",  # directory
        "{tmp}/x.zip",  # wrong suffix, exists
    ],
)
def test_rejected(tmp_path, value):
    (tmp_path / "dir.whl").mkdir()
    (tmp_path / "x.zip").write_bytes(b"x")
    a = RecordingAdapter()
    code, out = _run([], a, {ENV: value.format(tmp=tmp_path)})
    assert code == 1 and a.calls == [] and ENV in out


def test_ignored_with_local(tmp_path):
    a = RecordingAdapter()
    code, out = _run(["--local"], a, {ENV: "https://evil.example/x.whl"})
    assert code == 0 and a.spec.command == sys.executable
    assert "--from" not in a.spec.args and "TEST-ONLY" not in out


def test_unset_keeps_default():
    a = RecordingAdapter()
    _run([], a, {})
    assert a.spec.args == ("mcp-server-lore",)


def test_existing_default_registration_conflicts(tmp_path):
    p = _wheel(tmp_path)
    default = Registration("stdio", "uvx", ("mcp-server-lore",), {"LORE_BACKEND": "gists", "LORE_READ_ONLY": "1"}, "user")
    a = RecordingAdapter(default)
    code, out = _run([], a, {ENV: str(p)})
    assert code == 1 and a.calls == [] and "different command or arguments" in out
    code, _ = _run(["--force"], a, {ENV: str(p)})
    assert code == 0 and a.calls == [("remove", "lore", "user"), ("register", "lore", "user")]


def test_same_registration_is_idempotent(tmp_path):
    p = _wheel(tmp_path)
    reg = Registration(
        "stdio", "uvx", ("--from", str(p), "mcp-server-lore"),
        {"LORE_BACKEND": "gists", "LORE_READ_ONLY": "1"}, "user",
    )
    a = RecordingAdapter(reg)
    code, out = _run([], a, {ENV: str(p)})
    assert code == 0 and a.calls == [] and "already configured" in out


def test_verification_runs_registered_command(tmp_path):
    p = _wheel(tmp_path)
    seen = {}

    def verify(command, args, env, **k):
        seen.update(command=command, args=list(args))
        return verify_mod.VerifyResult(True, "ok", ["t"] * 5, 1)

    code, _ = _run([], RecordingAdapter(), {ENV: str(p)}, verify)
    assert code == 0
    assert seen == {"command": "uvx", "args": ["--from", str(p), "mcp-server-lore"]}


# ---- init hardening: --store-token without token, verify env forwarding, uvx hint


def _run2(argv, adapter, env, verify=None):
    lines = []
    code = init_mod.run_init(
        argv, adapters={"claude": lambda: adapter},
        checks_fn=lambda semantic, **k: [Check("python", True, "ok")],
        out=lines.append, env=env,
        token_fn=lambda **k: auth_mod.TokenResult(),
        verify_fn=verify or (lambda *a, **k: verify_mod.VerifyResult(True, "ok", ["t"] * 5, 1)),
    )
    return code, "\n".join(lines)


def test_store_token_without_token_fails_before_registering(tmp_path):
    a = RecordingAdapter()
    code, out = _run2(["--store-token"], a, {})
    assert code == 1 and a.calls == []
    assert "--store-token needs a token" in out and "gh auth login" in out
    assert not (tmp_path / "home" / ".lore").exists()


def test_no_token_without_store_token_still_demo():
    code, out = _run2([], RecordingAdapter(), {})
    assert code == 0 and "READ-ONLY" in out


def test_store_token_with_token_still_works():
    a = RecordingAdapter()
    lines = []
    tok = "ghp_" + "b" * 36
    code = init_mod.run_init(
        ["--store-token"], adapters={"claude": lambda: a},
        checks_fn=lambda semantic, **k: [Check("python", True, "ok")],
        out=lines.append, env={"LORE_GITHUB_TOKEN": tok},
        verify_fn=lambda *a_, **k: verify_mod.VerifyResult(True, "ok", ["t"] * 5, 1),
    )
    assert code == 0 and a.spec.secrets == {"LORE_GITHUB_TOKEN": tok}
    assert tok not in "\n".join(lines)


FWD = {
    "LORE_ALLOW_INSECURE_TEST_URLS": "1",
    "LORE_GITHUB_API_URL": "http://127.0.0.1:5",
    "LORE_GIST_WEB_URL": "http://127.0.0.1:6",
}


def test_test_endpoints_forwarded_to_verify_only():
    seen = {}
    a = RecordingAdapter()
    code, out = _run2([], a, dict(FWD), lambda c, args, env, **k: (
        seen.update(env), verify_mod.VerifyResult(True, "ok", ["t"] * 5, 1))[1])
    assert code == 0
    for k, v in FWD.items():
        assert seen[k] == v
        assert k not in a.spec.env and not any(v in x for x in a.spec.args)
        assert v.startswith("http") is False or v not in out


def test_test_endpoints_absent_when_unset():
    seen = {}
    _run2([], RecordingAdapter(), {}, lambda c, args, env, **k: (
        seen.update(env), verify_mod.VerifyResult(True, "ok", ["t"] * 5, 1))[1])
    assert not any(k in seen for k in FWD)


def test_uvx_fix_mentions_local():
    from lore.setup.checks import check_uvx

    assert "--local" in check_uvx(lambda n: None).fix
