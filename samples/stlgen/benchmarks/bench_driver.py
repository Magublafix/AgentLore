"""Resumable driver for the LORE-054 benchmark series.

Runs ``run.py`` one series at a time for each condition, in order, and skips series that are
already recorded in the condition's ``aggregate.json``.  Safe to kill and restart at any time:
a restart loses at most the series that was in progress.

* Storage is the **private selfhosted backend only** (SQLite + embedded Qdrant, both on disk).  The
  gists backend is never used: ``--backend selfhosted`` is always passed and every GitHub
  credential is removed from the environment of both the server and the runner.
* The Lore server is started (and restarted if it dies) by this driver via ``bench_server.py``:
  the private sqlite_qdrant backend with an embedded on-disk Qdrant (no Docker, no Qdrant service),
  both stored under ``--state-dir`` so they survive a restart.  Every series resets the database
  at run 1 anyway.
* Everything is logged to ``<results>/logs/``.

Usage::

    python bench_driver.py --series-per-condition 30            # all three conditions
    python bench_driver.py --series-per-condition 1 --smoke      # smoke pass, separate results dir
    python bench_driver.py --status                              # show progress and exit
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
STLGEN = HERE.parent
REPO = STLGEN.parent.parent
RESULTS = STLGEN / "results"

CONDITIONS = ("agentlore", "random", "control")   # random needs the agentlore token counts
MODEL_NAME = "unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M"  # must equal the earlier series (parity check)
LLM_BASE_URL = "http://192.168.1.38:8080"
SERVER_PORT = 8765
ADMIN_TOKEN = "bench-admin"
SECRET_ENV = ("LORE_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN", "LORE_SEMANTIC_URL")


def cond_dir(results: Path, cond: str) -> Path:
    """Results directory of a condition (agentlore keeps the legacy top-level location)."""
    return results if cond == "agentlore" else results / cond


def completed_series(results: Path, cond: str) -> set[int]:
    """Series ids already recorded in the condition's aggregate.json (empty if none/corrupt)."""
    path = cond_dir(results, cond) / "aggregate.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {int(s["series_id"]) for s in data.get("series", []) if "series_id" in s}


def pending_series(results: Path, cond: str, n: int) -> list[int]:
    """Series numbers 1..n of ``cond`` that still have to run."""
    done = completed_series(results, cond)
    return [i for i in range(1, n + 1) if i not in done]


def clean_env(base: dict[str, str]) -> dict[str, str]:
    """Copy of ``base`` without any GitHub/gists/semantic-server credentials."""
    return {k: v for k, v in base.items() if k not in SECRET_ENV}


def runner_env(base: dict[str, str], db_dir: Path) -> dict[str, str]:
    """Environment for run.py: local llama.cpp model, private server, no gist credentials."""
    env = clean_env(base)
    env.update({
        "LORE_LLM_PROVIDER": "local",
        "LORE_LOCAL_BASE_URL": LLM_BASE_URL,
        "LORE_LOCAL_MODEL": MODEL_NAME,
        "LORE_API_URL": f"http://127.0.0.1:{SERVER_PORT}",
        "LORE_ADMIN_TOKEN": ADMIN_TOKEN,
        "LORE_SESSION_FILE": str(db_dir / "session.json"),
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": os.pathsep.join(filter(None, [str(REPO), base.get("PYTHONPATH", "")])),
    })
    return env


def server_env(base: dict[str, str], db_dir: Path) -> dict[str, str]:
    """Environment for the private Lore server (SQLite on disk, in-memory Qdrant)."""
    env = clean_env(base)
    env.update({
        "LORE_STORAGE_BACKEND": "sqlite_qdrant",
        "LORE_DB_PATH": str(db_dir / "lore.db"),
        "LORE_BENCH_QDRANT_PATH": str(db_dir / "qdrant"),
        "BENCH_SERVER_PORT": str(SERVER_PORT),
        "LORE_ADMIN_TOKEN": ADMIN_TOKEN,
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
    })
    return env


def series_command(py: str, cond: str, series: int, extra: list[str]) -> list[str]:
    """Command line running exactly one series of ``cond`` (always the private backend)."""
    cmd = [py, str(HERE / "run.py"), "--series", "1", "--start-series", str(series),
           "--condition", cond, "--backend", "selfhosted"]
    if cond == "random":
        cmd += ["--match-series", str(series)]   # random series N matches relevant series N
    return cmd + extra


class Server:
    """The private Lore server subprocess; restarted on demand."""

    def __init__(self, py: str, db_dir: Path, log: Path):
        self.py, self.db_dir, self.log = py, db_dir, log
        self.proc: subprocess.Popen | None = None

    def healthy(self) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{SERVER_PORT}/v1/health", timeout=3) as r:
                return r.status == 200
        except Exception:
            return False

    def ensure(self, timeout: float = 180.0) -> None:
        """Start the server if it is not healthy and wait until it answers."""
        if self.proc and self.proc.poll() is None and self.healthy():
            return
        self.stop()
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.log.parent.mkdir(parents=True, exist_ok=True)
        fh = self.log.open("ab")
        self.proc = subprocess.Popen(
            [self.py, str(HERE / "bench_server.py")],
            cwd=REPO, env=server_env(os.environ, self.db_dir), stdout=fh, stderr=subprocess.STDOUT)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"Lore server exited with {self.proc.returncode}; see {self.log}")
            if self.healthy():
                return
            time.sleep(2)
        raise RuntimeError(f"Lore server not healthy after {timeout}s; see {self.log}")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


def log_line(fh, msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    fh.write(line + "\n")
    fh.flush()


def series_is_degenerate(results: Path, cond: str, series: int) -> bool:
    """True if the recorded series has runs but none made a single model turn (API/key/network failure)."""
    path = cond_dir(results, cond) / "aggregate.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    for s in data.get("series", []):
        if s.get("series_id") == series:
            runs = s.get("runs", [])
            return bool(runs) and all(r.get("turns_main", 0) == 0 for r in runs)
    return False


def drop_series(results: Path, cond: str, series: int) -> None:
    """Remove a series from aggregate.json (used to discard an infrastructure-failed series)."""
    path = cond_dir(results, cond) / "aggregate.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["series"] = [s for s in data.get("series", []) if s.get("series_id") != series]
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_series(py: str, cond: str, series: int, extra: list[str], server: Server | None,
               results: Path, env: dict[str, str], retries: int) -> bool:
    """Run one series (with retries); True once it appears in the condition's aggregate.json."""
    logdir = results / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, retries + 1):
        if server is not None:
            server.ensure()
        log = logdir / f"{cond}_series_{series:03d}.log"
        with log.open("ab") as fh:
            fh.write(f"\n=== attempt {attempt} {time.strftime('%F %T')} ===\n".encode())
            fh.flush()
            subprocess.run(series_command(py, cond, series, extra), cwd=HERE, env=env,
                           stdout=fh, stderr=subprocess.STDOUT)
        if series in completed_series(results, cond):
            if series_is_degenerate(results, cond, series):
                with log.open("ab") as fh:
                    fh.write(b"=== series discarded: no run made a model turn (check LLM endpoint/key) ===\n")
                drop_series(results, cond, series)
                return False                       # retrying would fail the same way
            return True
    return False


def status(results: Path, n: int) -> str:
    rows = [f"{c:<10} {len(completed_series(results, c))}/{n} series done" for c in CONDITIONS]
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--series-per-condition", type=int, default=30)
    ap.add_argument("--conditions", nargs="+", choices=CONDITIONS, default=list(CONDITIONS))
    ap.add_argument("--retries", type=int, default=2, help="attempts per series (default 2)")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--smoke", action="store_true",
                    help="write to results_smoke/ instead of results/ (never mixes with real data)")
    ap.add_argument("--state-dir", type=Path, default=Path("/workspace/AgentLore-scratch/bench-state"),
                    help="persistent dir for the server's SQLite file")
    ap.add_argument("--python", default=sys.executable)
    args = ap.parse_args(argv)

    results = STLGEN / ("results_smoke" if args.smoke else "results")
    if args.status:
        print(status(results, args.series_per_condition))
        return 0

    extra: list[str] = []
    env = runner_env(os.environ, args.state_dir)
    if args.smoke:
        env["LORE_BENCH_RESULTS_DIR"] = str(results)
    (results / "logs").mkdir(parents=True, exist_ok=True)
    server = Server(args.python, args.state_dir, results / "logs" / "server.log")
    failed: list[tuple[str, int]] = []
    with (results / "logs" / "driver.log").open("a", encoding="utf-8") as drv:
        try:
            for cond in args.conditions:
                todo = pending_series(results, cond, args.series_per_condition)
                log_line(drv, f"{cond}: {len(todo)} series to run {todo[:5]}{'...' if len(todo) > 5 else ''}")
                for s in todo:
                    ok = run_series(args.python, cond, s, extra,
                                    server if cond == "agentlore" else None, results, env, args.retries)
                    log_line(drv, f"{cond} series {s}: {'done' if ok else 'FAILED'}")
                    if not ok:
                        failed.append((cond, s))
        finally:
            server.stop()
    if failed:
        print(f"FAILED series (re-run the driver to retry): {failed}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
