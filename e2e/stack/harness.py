"""Harness for the semantic-server stack E2E (marker ``e2e_stack``).

Chain under test (one real server process, stub GitHub, no Qdrant service):
stub GitHub -> watcher bootstrap/poll -> in-memory Qdrant -> ``GET /search`` -> MCP stdio client.

Environment knobs:
  LORE_STACK_PYTHON      interpreter that has the code + ``selfhosted`` extra installed
                         (default: the interpreter running pytest)
  LORE_STACK_PYTHONPATH  optional PYTHONPATH for the spawned processes. Local fallback only:
                         when unset, the processes import the INSTALLED lore (CI).
  LORE_STACK_REQUIRE_INSTALLED=1  fail if ``lore`` resolves into the source checkout.
  HF_HOME / HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE are passed through for the model cache.

Safety: every process has a hard timeout, one server runs at a time (module scoped
fixtures), RSS is sampled from /proc, and logs are redacted before landing in e2e/out/stack/.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

import pytest

if TYPE_CHECKING:  # httpx is only needed by the stack job; keep collection import-free
    import httpx

E2E_DIR = Path(__file__).resolve().parent.parent
REPO = E2E_DIR.parent
sys.path.insert(0, str(E2E_DIR / "stubs"))
sys.path.insert(0, str(E2E_DIR))

from gist_stub import GistStub  # noqa: E402

OUT = E2E_DIR / "out" / "stack"
STARTUP_TIMEOUT = 180.0   # model load + bootstrap (3 pages x >=2 s delay)
RSS_LIMIT_BYTES = 3 * 1024 ** 3
WATCH_INTERVAL = 3
PASSTHROUGH = ("HF_HOME", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HTTP_PROXY", "HTTPS_PROXY",
               "http_proxy", "https_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR", "LANG", "LC_ALL")


def redact(text: str, secrets_: list[str]) -> str:
    for s in secrets_:
        if s:
            text = text.replace(s, "[REDACTED]")
    return text


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _rss_bytes(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0


def base_env(home: Path, python_path: str | None) -> dict[str, str]:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
           "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
           "OMP_NUM_THREADS": "2", "TOKENIZERS_PARALLELISM": "false"}
    for k in PASSTHROUGH:
        if k in os.environ:
            env[k] = os.environ[k]
    if python_path:
        env["PYTHONPATH"] = python_path
    return env


class StackServer:
    """The real semantic server (``uvicorn lore.server.api:app``, one worker)."""

    def __init__(self, name: str, stub: GistStub, tmp: Path, token: str) -> None:
        self.name, self.stub, self.tmp, self.token = name, stub, tmp, token
        self.python = os.environ.get("LORE_STACK_PYTHON", sys.executable)
        self.python_path = os.environ.get("LORE_STACK_PYTHONPATH") or None
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.home = tmp / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.log_path = tmp / "server.log"
        self.max_rss = 0
        self.started_at = 0.0
        self._stop = threading.Event()
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        log_cfg = self.tmp / "logging.json"
        log_cfg.write_text(json.dumps({
            "version": 1, "disable_existing_loggers": False,
            "formatters": {"f": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
            "handlers": {"h": {"class": "logging.StreamHandler", "formatter": "f"}},
            "root": {"level": "INFO", "handlers": ["h"]},
        }))
        env = base_env(self.home, self.python_path)
        env.update({
            "LORE_STORAGE_BACKEND": "gist_qdrant",
            "LORE_QDRANT_IN_MEMORY": "1",
            "LORE_ALLOW_INSECURE_TEST_URLS": "1",
            "LORE_GITHUB_API_URL": self.stub.url,
            "LORE_GIST_WEB_URL": self.stub.url,
            "LORE_GITHUB_TOKEN": self.token,
            "LORE_WATCH_INTERVAL": str(WATCH_INTERVAL),
            "LORE_BOOTSTRAP_DELAY": "0",       # production clamps this to its 2 s minimum
            "LORE_BOOTSTRAP_MAX_PAGES": "10",
        })
        self.started_at = time.monotonic()
        with self.log_path.open("wb") as log:
            self.proc = subprocess.Popen(
                [self.python, "-m", "uvicorn", "lore.server.api:app", "--host", "127.0.0.1",
                 "--port", str(self.port), "--workers", "1", "--log-config", str(log_cfg)],
                env=env, cwd=str(self.tmp), stdout=log, stderr=subprocess.STDOUT,
            )
        threading.Thread(target=self._sample_rss, daemon=True).start()
        self.wait_for_log("entering poll loop", STARTUP_TIMEOUT)

    def _sample_rss(self) -> None:
        while not self._stop.wait(0.5):
            assert self.proc
            self.max_rss = max(self.max_rss, _rss_bytes(self.proc.pid))
            if self.max_rss > RSS_LIMIT_BYTES and self.proc.poll() is None:
                self.proc.kill()  # runaway guard: never let a bug eat the container
                return

    @property
    def log(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def wait_for_log(self, needle: str, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if needle in self.log:
                return
            if not self.alive():
                raise AssertionError(f"server exited early (rc={self.proc.returncode if self.proc else None}):\n"
                                     f"{redact(self.log[-3000:], [self.token])}")
            time.sleep(0.25)
        raise AssertionError(f"timeout waiting for {needle!r}; log tail:\n{redact(self.log[-3000:], [self.token])}")

    def get(self, path: str, **params: object) -> "httpx.Response":
        import httpx

        return httpx.get(self.url + path, params=params, timeout=30.0)

    def indexed_ids(self) -> set[str]:
        r = self.get("/search", q="software engineering", k=50)
        assert r.status_code == 200, r.text
        return {x["concept_id"] for x in r.json()["results"]}

    def stop(self) -> None:
        self._stop.set()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{self.name}-server.log").write_text(redact(self.log, [self.token]), encoding="utf-8")
        (OUT / f"{self.name}-max-rss-mib.txt").write_text(f"{self.max_rss // 2**20}\n")
        (OUT / f"{self.name}-stub-requests.json").write_text(json.dumps(
            [{**r, "auth": "[REDACTED]" if r["auth"] else ""} for r in self.stub.snapshot()], indent=1))


def make_stack(name: str, tmp_path_factory: pytest.TempPathFactory, configure=None) -> Iterator[StackServer]:
    stub = GistStub().start()
    if configure:
        configure(stub)
    token = "ghp_E2ESTACK" + secrets.token_hex(12)
    tmp = tmp_path_factory.mktemp(f"stack-{name}")
    server = StackServer(name, stub, tmp, token)
    try:
        server.start()
        yield server
    finally:
        server.stop()
        stub.stop()
