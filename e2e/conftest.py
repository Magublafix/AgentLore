"""Harness for the black-box ``mcp-server-lore init`` E2E suite.

Everything runs against the BUILT wheel and the real ``claude`` CLI, inside a per-scenario
sandbox (fresh HOME / XDG_* / CLAUDE_CONFIG_DIR / TMPDIR / cwd). Subprocesses never inherit
``os.environ``: each gets an explicit allowlisted env whose PATH is a shim directory holding
symlinks to the real tools only (so a missing prerequisite is simulated by omitting a link).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from mcp_stdio import McpStdioSession  # noqa: E402

E2E_DIR = Path(__file__).resolve().parent
REPO = E2E_DIR.parent
OUT_DIR = E2E_DIR / "out"
SNAPSHOT_DIR = E2E_DIR / "snapshots"

INIT_TIMEOUT = 300  # cold uv cache may download ~70 packages
CMD_TIMEOUT = 90

# Tools symlinked into every shim dir. realpath/dirname are needed by uv's console-script wrapper;
# node only exists where claude is an npm shim. Scenarios drop entries to simulate absence.
BASE_TOOLS = ("claude", "uvx", "uv", "python", "python3", "realpath", "dirname")
OPTIONAL_TOOLS = ("node",)
PASSTHROUGH_VARS = (
    "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "UV_INDEX_URL",
    "UV_EXTRA_INDEX_URL", "PIP_INDEX_URL", "UV_NATIVE_TLS",
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "e2e: black-box test against the built wheel and real claude CLI")


# --------------------------------------------------------------------------- helpers

def _real_home() -> Optional[Path]:
    try:
        import pwd

        return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
    except Exception:  # noqa: BLE001 - non-POSIX
        return None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree(root: Path, skip: Iterable[str] = ()) -> dict[str, str]:
    out: dict[str, str] = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if any(rel == s or rel.startswith(s + "/") for s in skip):
            continue
        if p.is_symlink():
            out[rel] = "symlink:" + os.readlink(p)
        elif p.is_file():
            out[rel] = _sha(p)
    return out


def _find_server_entries(node: object, path: str = "") -> dict[str, object]:
    """Every ``mcpServers`` mapping inside a parsed ~/.claude.json, keyed by its JSON path."""
    found: dict[str, object] = {}
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "mcpServers" and isinstance(v, dict):
                found[f"{path}/{k}"] = v
            else:
                found.update(_find_server_entries(v, f"{path}/{k}"))
    return found


def parse_mcp_get(output: str) -> dict:
    """Parse ``claude mcp get <name>`` output (independent of lore's own parser)."""
    info: dict = {"env": {}, "raw": output}
    in_env = False
    for raw in output.splitlines():
        line = raw.strip()
        if in_env and "=" in line:
            k, _, v = line.partition("=")
            info["env"][k.strip()] = v.strip()
            continue
        in_env = False
        key, sep, value = line.partition(":")
        if not sep:
            continue
        if key == "Environment":
            in_env = True
        elif key in ("Scope", "Type", "Command", "Args", "Status", "Issue"):
            info[key.lower()] = value.strip()
    info["args"] = info.get("args", "").split()
    return info


class Result:
    def __init__(self, argv: Sequence[str], rc: int, out: str, err: str) -> None:
        self.argv, self.rc, self.stdout, self.stderr = list(argv), rc, out, err

    @property
    def text(self) -> str:
        return self.stdout + self.stderr


# --------------------------------------------------------------------------- session fixtures

@pytest.fixture(scope="session", autouse=True)
def _session_guard():
    """Fail fast when the sandbox could touch the real home; verify it stays untouched."""
    real = _real_home()
    base = Path(os.environ.get("LORE_E2E_TMP") or tempfile.gettempdir()).resolve()
    if real is not None and (base == real or real in base.parents):
        pytest.exit(f"E2E temp base {base} is under the real home {real}; set LORE_E2E_TMP", returncode=2)

    def snap() -> dict:
        if real is None:
            return {}
        cfg = real / ".claude.json"
        servers = {}
        if cfg.is_file():
            try:
                servers = {p: sorted(m) for p, m in _find_server_entries(json.loads(cfg.read_text())).items()}
            except ValueError:
                servers = {"unparseable": []}
        lore_servers = {p: m for p, m in servers.items() if "lore" in m}
        # Names only (no mtimes/sizes): other processes -- including a live Claude session -- legitimately
        # rewrite files in these directories, but a new/removed top-level entry is not ours to cause.
        # ~/.claude is limited to lore-looking names plus its settings files, which `claude mcp` could write.
        def names(d: Path, only: Optional[re.Pattern] = None) -> list[str]:
            try:
                got = sorted(x.name for x in d.iterdir())
            except OSError:
                return []
            return [n for n in got if only is None or only.search(n)]

        lore_like = re.compile(r"lore|mcp-server|\buv\b", re.I)
        claude_settings = {
            n: (st.st_size, st.st_mtime_ns)
            for n in ("settings.json", "settings.local.json")
            if (real / ".claude" / n).exists() for st in [(real / ".claude" / n).stat()]
        }
        return {
            "lore_dir": _tree(real / ".lore"),
            "lore_registrations": lore_servers,
            "home_top": names(real),
            "dot_config": names(real / ".config"),
            "dot_cache": names(real / ".cache"),
            "local_share": names(real / ".local" / "share"),
            "dot_claude_lore": names(real / ".claude", lore_like),
            "claude_settings": claude_settings,
        }

    before = snap()
    shutil.rmtree(OUT_DIR, ignore_errors=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    yield
    after = snap()
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert not changed, f"the suite changed the real home: {changed}"


@pytest.fixture(scope="session")
def tmp_base() -> Path:
    base = Path(os.environ.get("LORE_E2E_TMP") or tempfile.gettempdir())
    root = Path(tempfile.mkdtemp(prefix="lore-e2e-", dir=base)).resolve()
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="session")
def wheel() -> Path:
    given = os.environ.get("LORE_E2E_WHEEL")
    if given:
        path = Path(given).resolve()
    else:
        wheels = sorted((REPO / "dist").glob("*.whl"), key=lambda p: p.stat().st_mtime)
        if not wheels:
            pytest.fail("no wheel: set LORE_E2E_WHEEL or run `python -m build` first")
        path = wheels[-1].resolve()
    assert path.is_file() and path.suffix == ".whl", f"not a wheel: {path}"
    return path


@pytest.fixture(scope="session")
def real_tools() -> dict[str, str]:
    """Resolved real tools (once, from the host PATH)."""
    found: dict[str, str] = {}
    for name in BASE_TOOLS + OPTIONAL_TOOLS:
        if name in ("python", "python3"):
            found[name] = os.path.realpath(sys.executable)
            continue
        p = shutil.which(name) or shutil.which(name, path=str(Path(sys.executable).parent))
        if p:
            found[name] = os.path.realpath(p)
    missing = [n for n in ("claude", "uvx", "uv") if n not in found]
    if missing:
        pytest.fail(f"required tools not on PATH: {missing}")
    return found


@pytest.fixture(scope="session")
def shared_caches(tmp_base: Path) -> dict[str, Path]:
    """Package caches only (never config/state): shared to keep the suite fast."""
    cache = Path(os.environ.get("LORE_E2E_UV_CACHE") or tmp_base / "uv-cache")
    pydir = tmp_base / "uv-python"
    cache.mkdir(parents=True, exist_ok=True)
    pydir.mkdir(exist_ok=True)
    return {"cache": cache, "python": pydir}


@pytest.fixture(scope="session")
def venv_python(tmp_base: Path, wheel: Path, real_tools: dict, shared_caches: dict) -> Path:
    """A venv with ONLY the built wheel installed (for --local and for runs without uvx)."""
    shim = tmp_base / "venv-shim"
    shim.mkdir()
    for n in ("uv", "python", "python3"):
        (shim / n).symlink_to(real_tools[n])
    env = {
        "PATH": str(shim), "HOME": str(tmp_base / "venv-home"), "TMPDIR": str(tmp_base),
        "UV_CACHE_DIR": str(shared_caches["cache"]), "UV_PYTHON_INSTALL_DIR": str(shared_caches["python"]),
        **{k: os.environ[k] for k in PASSTHROUGH_VARS if k in os.environ},
    }
    (tmp_base / "venv-home").mkdir()
    venv = tmp_base / "venv"
    uvx_env = {**env, "PATH": f"{shim}"}
    (shim / "uvx").symlink_to(real_tools["uvx"])
    for n in ("realpath", "dirname"):
        if n in real_tools:
            (shim / n).symlink_to(real_tools[n])
    # One generous warm-up of the exact command the scenarios use, so later health checks are fast.
    warm = subprocess.run([str(shim / "uvx"), "--from", str(wheel), "mcp-server-lore", "init", "--help"],
                          env=uvx_env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=INIT_TIMEOUT)
    assert warm.returncode == 0, f"uvx warm-up failed: {warm.stderr[-800:]}"
    for argv in (
        [real_tools["uv"], "venv", str(venv), "--python", str(shim / "python")],
        [real_tools["uv"], "pip", "install", "--python", str(venv / "bin" / "python"), str(wheel)],
    ):
        r = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=INIT_TIMEOUT)
        assert r.returncode == 0, f"venv setup failed: {r.stderr[-800:]}"
    return venv / "bin" / "python"


# --------------------------------------------------------------------------- stub

def _load_stub_class():
    spec = importlib.util.spec_from_file_location("lore_e2e_github_stub", E2E_DIR / "stubs" / "github_api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.GithubStub


@pytest.fixture
def stub():
    s = _load_stub_class()().start()
    yield s
    s.stop()


# --------------------------------------------------------------------------- sandbox

class Sandbox:
    def __init__(self, root: Path, name: str, wheel: Path, real_tools: dict, caches: dict, venv_py) -> None:
        self.root = root
        self.name = name
        self.wheel = wheel
        self.real_tools = real_tools
        self._venv_py = venv_py
        self.home = root / "home"
        self.xdg_config = root / "xdg-config"
        self.xdg_cache = root / "xdg-cache"
        self.xdg_data = root / "xdg-data"
        self.claude_config = root / "claude-config"
        self.tmpdir = root / "tmp"
        self.cwd = root / "project"
        self.shim = root / "bin"
        for d in (self.home, self.xdg_config, self.xdg_cache, self.xdg_data, self.claude_config,
                  self.tmpdir, self.cwd, self.shim):
            d.mkdir(parents=True)
        # Package caches are shared (see shared_caches); the registered server is spawned by
        # claude with a reduced env, so link the XDG locations instead of relying on UV_* vars.
        (self.xdg_cache / "uv").symlink_to(caches["cache"])
        (self.xdg_data / "uv").symlink_to(caches["python"])
        self.caches = caches
        self.token = "ghp_E2EFAKE" + secrets.token_hex(14)
        self.secrets = [self.token]
        self.allow_files: list[Path] = []
        self.allow_output = False
        self.allow_get_output = False  # only `claude mcp get/list` output (prints stored env by design)
        self.outputs: list[str] = []
        self._n = 0
        self.log_dir = OUT_DIR / re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        real = _real_home()
        assert real is None or real not in self.home.resolve().parents, "sandbox HOME is under the real home"
        for tool in BASE_TOOLS + OPTIONAL_TOOLS:
            self.link(tool)

    # -- PATH shim -----------------------------------------------------------
    def link(self, tool: str) -> None:
        if tool in self.real_tools and not (self.shim / tool).exists():
            (self.shim / tool).symlink_to(self.real_tools[tool])

    def unlink(self, tool: str) -> None:
        p = self.shim / tool
        if p.is_symlink() or p.exists():
            p.unlink()

    def fake_tool(self, tool: str, script: str) -> None:
        self.unlink(tool)
        p = self.shim / tool
        p.write_text("#!/bin/sh\n" + script + "\n")
        p.chmod(p.stat().st_mode | stat.S_IXUSR)

    # -- environment ---------------------------------------------------------
    def env(self, extra: Optional[Mapping[str, str]] = None) -> dict[str, str]:
        env = {
            "PATH": str(self.shim),
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.xdg_config),
            "XDG_CACHE_HOME": str(self.xdg_cache),
            "XDG_DATA_HOME": str(self.xdg_data),
            "CLAUDE_CONFIG_DIR": str(self.claude_config),
            "TMPDIR": str(self.tmpdir),
            "LANG": "C.UTF-8",
            "NO_COLOR": "1",
            "DISABLE_AUTOUPDATER": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "UV_CACHE_DIR": str(self.caches["cache"]),
            "UV_PYTHON_INSTALL_DIR": str(self.caches["python"]),
            "UV_NO_PROGRESS": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "LORE_INIT_UVX_FROM": str(self.wheel),
            **{k: os.environ[k] for k in PASSTHROUGH_VARS if k in os.environ},
        }
        if any(k in env for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")):
            env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost,::1"
        env.update(extra or {})
        return env

    def use_stub(self, stub, token: Optional[str] = None) -> dict[str, str]:
        """Extra env for ``init`` that points GitHub traffic at the local stub.

        init forwards the test-only override vars to its verification child (ADR-016), so no
        wrapper is needed; the registration itself never contains them.
        """
        env = {"LORE_ALLOW_INSECURE_TEST_URLS": "1", "LORE_GITHUB_API_URL": stub.url,
               "LORE_GIST_WEB_URL": stub.url}
        if token:
            env["LORE_GITHUB_TOKEN"] = token
        return env

    # -- running ---------------------------------------------------------------
    def run(self, argv: Sequence[str], *, extra_env: Optional[Mapping[str, str]] = None,
            timeout: int = CMD_TIMEOUT, label: str = "cmd", stdin_open: bool = False) -> Result:
        argv = list(argv)
        if os.sep not in argv[0] and (self.shim / argv[0]).exists():
            argv[0] = str(self.shim / argv[0])
        env = self.env(extra_env)
        stdin = subprocess.PIPE if stdin_open else subprocess.DEVNULL
        proc = subprocess.Popen(argv, env=env, cwd=self.cwd, stdin=stdin, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            self._record(label, argv, -9, out or "", err or "")
            pytest.fail(f"{label}: timed out after {timeout}s (hang?)")
        res = Result(argv, proc.returncode, out, err)
        self._record(label, argv, proc.returncode, out, err)
        return res

    def init(self, *args: str, extra_env: Optional[Mapping[str, str]] = None, via: str = "uvx",
             timeout: int = INIT_TIMEOUT, label: str = "init", stdin_open: bool = False) -> Result:
        if via == "uvx":
            argv = ["uvx", "--from", str(self.wheel), "mcp-server-lore", "init", *args]
        else:  # the wheel installed in a venv, addressed by absolute path
            argv = [str(self._venv_py.parent / "mcp-server-lore"), "init", *args]
        return self.run(argv, extra_env=extra_env, timeout=timeout, label=label, stdin_open=stdin_open)

    def claude(self, *args: str, label: str = "claude") -> Result:
        return self.run(["claude", *args], label=label)

    def mcp_get(self) -> dict:
        res = self.claude("mcp", "get", "lore", label="mcp-get")
        info = parse_mcp_get(res.text)
        info["rc"] = res.rc
        return info

    def _poll(self, argv: Sequence[str], ok, timeout: float, label: str) -> Result:
        """Re-run a claude health-check command until ``ok(result)`` or the deadline.

        Claude spawns the registered server for every ``mcp get/list``; on a cold uv cache that
        can take a while (downloads), hence retry-until-timeout instead of a single call.
        """
        import time

        deadline = time.monotonic() + timeout
        attempt = 0
        while True:
            attempt += 1
            res = self.run(argv, label=f"{label}-{attempt}", timeout=CMD_TIMEOUT)
            if ok(res) or time.monotonic() >= deadline:
                return res

    def claude_status(self, want: str = "Connected", timeout: float = 60) -> dict:
        """Claude Code's OWN view of the server, from ``mcp get`` and ``mcp list``.

        ``want`` is ``"Connected"`` or ``"Failed"``; returns ``{"get": parsed-get, "list": line}``
        after the status settles (or the deadline passes, so the caller's assert shows the truth).
        """
        def got(res: Result) -> bool:
            st = parse_mcp_get(res.text).get("status", "")
            return ("Connected" in st) if want == "Connected" else ("Failed" in st)

        res = self._poll(["claude", "mcp", "get", "lore"], got, timeout, "status-get")
        info = parse_mcp_get(res.text)
        lst = self._poll(
            ["claude", "mcp", "list"],
            lambda r: any(l.startswith("lore:") and (("Connected" in l) == (want == "Connected"))
                          for l in r.stdout.splitlines()),
            timeout, "status-list")
        line = next((l for l in lst.stdout.splitlines() if l.startswith("lore:")), "")
        return {"get": info, "list": line}

    def assert_connected(self) -> None:
        st = self.claude_status("Connected")
        assert "Connected" in st["get"].get("status", ""), st["get"]["raw"]
        assert "Connected" in st["list"], st["list"]

    @property
    def venv_python(self) -> Path:
        return self._venv_py

    # -- logging / redaction -----------------------------------------------------
    def redact(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "<REDACTED>")
        return text

    def _record(self, label: str, argv: Sequence[str], rc: int, out: str, err: str) -> None:
        self._n += 1
        if not (self.allow_get_output and label.startswith(("mcp-get", "status-"))):
            self.outputs.extend([out, err])  # argv is our own input, not output
        body = f"$ {' '.join(argv)}\nexit={rc}\n--- stdout ---\n{out}\n--- stderr ---\n{err}\n"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        (self.log_dir / f"{self._n:02d}-{label}.txt").write_text(self.redact(body))

    def redact_free_outputs(self) -> str:
        """All captured (unredacted) stdout/stderr so far, for in-test leak assertions."""
        return "\n".join(self.outputs)

    # -- state -----------------------------------------------------------------
    @property
    def user_config(self) -> Path:
        return self.claude_config / ".claude.json"

    def user_config_text(self) -> str:
        return self.user_config.read_text() if self.user_config.is_file() else ""

    def registrations(self) -> dict[str, object]:
        """All ``mcpServers`` entries in the isolated claude config, by JSON path."""
        if not self.user_config.is_file():
            return {}
        return _find_server_entries(json.loads(self.user_config.read_text()))

    def lore_registration(self, scope_path: str = "/mcpServers") -> Optional[dict]:
        return (self.registrations().get(scope_path) or {}).get("lore")  # type: ignore[union-attr]

    def snapshot(self) -> dict:
        """What ``init`` is allowed to change: registrations, ~/.lore, ./.mcp.json (not caches/logs)."""
        mcp = self.cwd / ".mcp.json"
        return {
            "registrations": json.dumps(self.registrations(), sort_keys=True),
            "lore_dir": _tree(self.home / ".lore"),
            "project_mcp": mcp.read_text() if mcp.exists() else None,
        }

    def home_hash(self) -> dict:
        """Everything in HOME / claude config except caches, logs and claude's own backups."""
        return {
            "home": _tree(self.home, skip=(".cache", ".local/share")),
            # claude rewrites volatile counters in .claude.json on every call: compare its servers instead
            "claude_cfg": _tree(self.claude_config, skip=("backups", ".claude.json")),
            "registrations": json.dumps(self.registrations(), sort_keys=True),
            "cwd": _tree(self.cwd),
        }

    # -- leak scanning -----------------------------------------------------------
    def leaks(self, allow_files: Sequence[Path] = (), allow_output: bool = False) -> list[str]:
        needles = [s for s in self.secrets if s]
        hits: list[str] = []
        if not allow_output:
            blob = "\n".join(self.outputs)
            hits += [f"captured output contains {n[:12]}…" for n in needles if n in blob]
        allowed = {Path(p).resolve() for p in allow_files}
        for base in (self.root,):
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]
                for fn in filenames:
                    p = Path(dirpath) / fn
                    if p.is_symlink() or p.resolve() in allowed:
                        continue
                    try:
                        data = p.read_bytes()
                    except OSError:
                        continue
                    hits += [f"{p.relative_to(self.root)} contains {n[:12]}…"
                             for n in needles if n.encode() in data]
        for p in self.log_dir.glob("*.txt"):  # our own redacted logs must be clean
            txt = p.read_text(errors="replace")
            hits += [f"log {p.name} contains {n[:12]}…" for n in needles if n in txt]
        return hits

    # -- the registered server -----------------------------------------------------
    def spawn_registered(self, user_env: Optional[Mapping[str, str]] = None) -> McpStdioSession:
        """Spawn EXACTLY the command/args/env that ``claude mcp get lore`` reports.

        ``user_env`` models the environment the agent is started from (e.g. LORE_GITHUB_TOKEN
        when the token was deliberately not stored).
        """
        info = self.mcp_get()
        assert info.get("command"), f"nothing registered: {info['raw']}"
        env = {**self.env(), **(user_env or {}), **info["env"]}
        env.pop("LORE_INIT_UVX_FROM", None)
        command = info["command"]
        if os.sep not in command and (self.shim / command).exists():
            command = str(self.shim / command)
        session = McpStdioSession(command, info["args"], env, str(self.cwd), timeout=120)
        session.initialize()
        return session


@pytest.fixture
def sb(request, tmp_base, wheel, real_tools, shared_caches, venv_python):
    root = tmp_base / re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.name)[:60]
    sandbox = Sandbox(root, request.node.name, wheel, real_tools, shared_caches, venv_python)
    yield sandbox
    # Teardown leak scan: every fake token must be absent everywhere unless the test allowed it.
    problems = sandbox.leaks(sandbox.allow_files, sandbox.allow_output)
    shutil.rmtree(root, ignore_errors=True)
    assert not problems, "secret leak(s): " + "; ".join(problems)


@pytest.fixture
def token(sb) -> str:
    return sb.token
