#!/usr/bin/env python3
"""
Lore effectiveness benchmark — radev CLI.

Runs an agentic coding session (Anthropic SDK loop) to implement the radev CLI
for restful-api.dev, then measures token and prompt counts.

The skills (search-concepts, capture-concept) are loaded from their SKILL.md
files and embedded directly in the system prompt — the same technique used by
the caveman benchmark. The MCP tool signatures (search_concepts, submit_concept)
are backed by direct SQLite writes so no Docker stack is required.

Flow:
  Run 1 — agent codes without Lore search; after submit it applies
           capture-concept and stores patterns in ~/.lore/lore.db.
  Run 2 — agent codes with search-concepts + capture-concept skills active.

Usage:
  python benchmarks/run.py --run 1      # baseline (captures concepts at end)
  python benchmarks/run.py --run 2      # with Lore skills active
  python benchmarks/run.py --all        # run 1 then run 2
  python benchmarks/run.py --dry-run --run 1
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import anthropic

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL = "claude-sonnet-4-6"
MAX_TURNS = 40
LORE_DB_PATH = Path(os.environ.get("LORE_DB_PATH", "~/.lore/lore.db")).expanduser()
SESSION_FILE = Path(os.environ.get("LORE_SESSION_FILE", "~/.lore/session.json")).expanduser()

REPO_ROOT = Path(__file__).parents[3]
SKILLS_DIR = REPO_ROOT / "skills"
SAMPLES_DIR = Path(__file__).parent.parent
RESULTS_DIR = SAMPLES_DIR / "results"
TEST_FILE = SAMPLES_DIR / "tests" / "test_radev_cli.py"
CONFTEST_FILE = SAMPLES_DIR / "tests" / "conftest.py"

# ---------------------------------------------------------------------------
# Local mock server (mirrors restful-api.dev — no rate limits)
# ---------------------------------------------------------------------------

def _start_mock_server() -> str:
    """Start an in-memory mock for restful-api.dev. Returns the base URL."""
    import uuid as _uuid

    _SEED = {
        "1": {"id": "1", "name": "Google Pixel 6 Pro",    "data": {"color": "Cloudy White", "capacity": "128 GB"}},
        "2": {"id": "2", "name": "Apple iPhone 12 Mini",  "data": {"color": "Purple",       "capacity": "64 GB"}},
        "3": {"id": "3", "name": "Samsung Galaxy Z Fold2","data": {"price": 689.99,          "color": "Brown"}},
    }
    _store: dict = dict(_SEED)
    _lock = threading.Lock()

    class _Handler(BaseHTTPRequestHandler):
        def _body(self):
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n)) if n else {}

        def _send(self, payload, status=200):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _obj_id(self):
            return self.path.split("/objects/", 1)[1].split("?")[0]

        def do_GET(self):
            if self.path.rstrip("/") == "/objects":
                with _lock:
                    self._send(list(_store.values()))
            elif "/objects/" in self.path:
                with _lock:
                    obj = _store.get(self._obj_id())
                self._send(obj) if obj else self._send({"error": "Not found"}, 404)
            else:
                self._send({"error": "Not found"}, 404)

        def do_POST(self):
            if self.path.rstrip("/") == "/objects":
                b = self._body()
                obj = {"id": str(_uuid.uuid4()), "name": b.get("name", ""), "data": b.get("data") or {}}
                with _lock:
                    _store[obj["id"]] = obj
                self._send(obj)
            else:
                self._send({"error": "Not found"}, 404)

        def do_PATCH(self):
            if "/objects/" in self.path:
                b = self._body()
                oid = self._obj_id()
                with _lock:
                    obj = _store.get(oid)
                    if obj:
                        obj["data"] = {**obj.get("data", {}), **b.get("data", {})}
                self._send(obj) if obj else self._send({"error": "Not found"}, 404)
            else:
                self._send({"error": "Not found"}, 404)

        do_PUT = do_PATCH

        def do_DELETE(self):
            if "/objects/" in self.path:
                oid = self._obj_id()
                with _lock:
                    ok = _store.pop(oid, None) is not None
                self._send({"message": "Object deleted successfully"}) if ok else self._send({"error": "Not found"}, 404)
            else:
                self._send({"error": "Not found"}, 404)

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    os.environ["RADEV_BASE_URL"] = url
    return url


# ---------------------------------------------------------------------------
# Load skill instructions from the actual SKILL.md files
# ---------------------------------------------------------------------------

def _load_skill(name: str) -> str:
    path = SKILLS_DIR / name / "SKILL.md"
    if not path.exists():
        return f"[skill {name} not found at {path}]"
    text = path.read_text(encoding="utf-8")
    # Strip frontmatter (--- ... ---)
    if text.startswith("---"):
        end = text.index("---", 3)
        text = text[end + 3:].lstrip()
    return text

# ---------------------------------------------------------------------------
# Task prompts
# ---------------------------------------------------------------------------

_CLI_TASK = """\
Build a Linux CLI tool called `radev` for the restful-api.dev public REST API.

Default base URL: https://api.restful-api.dev
The CLI must read the RADEV_BASE_URL environment variable and use it as the base URL
when set. This allows the test suite to point it at a local mock server.

Required commands:
  radev list                                  — list all objects (JSON array to stdout)
  radev get <id>                              — get object by id (JSON object to stdout)
  radev create --name <name> [--data <json>]  — create object (returns created object)
  radev update <id> --data <json>             — PATCH update object's data field
  radev delete <id>                           — delete object

Rules:
- All output is JSON to stdout
- Exit code 0 on success, non-zero on any error (not found, network, bad args)
- Installable via `pip install -e .`
- Entry point registered as `radev` in pyproject.toml or setup.cfg

A test file is at tests/test_radev_cli.py — run with: pip install -e . && pytest tests/ -v
"""

TASK_PROMPT_RUN1 = _CLI_TASK + """
When all 10 tests pass, call `submit`, then immediately apply the capture-concept skill \
to store any non-obvious patterns you discovered.
"""

TASK_PROMPT_RUN2 = _CLI_TASK + """
Before writing any code, use the search-concepts skill to search Lore for relevant patterns.
When all 10 tests pass, call `submit`, then apply the capture-concept skill for any new patterns.
"""

# ---------------------------------------------------------------------------
# MCP-compatible tool definitions (identical signatures to lore/mcp/server.py)
# ---------------------------------------------------------------------------

TOOL_BASH = {
    "name": "bash",
    "description": "Run a shell command in the project working directory.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

TOOL_WRITE_FILE = {
    "name": "write_file",
    "description": "Write text content to a file (relative to project root). Creates parent directories.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
}

TOOL_READ_FILE = {
    "name": "read_file",
    "description": "Read a file's text content.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
}

TOOL_SUBMIT = {
    "name": "submit",
    "description": "Signal that the task is complete.",
    "input_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    },
}

# search_concepts — same name and parameter names as the real MCP tool
TOOL_SEARCH_CONCEPTS = {
    "name": "search_concepts",
    "description": (
        "Search the Lore knowledge graph for concepts matching a problem description. "
        "Returns ranked results, each including the full concept record plus its "
        "directly linked concepts — no second call needed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "problem": {"type": "string", "description": "Natural language description of what you are building or trying to solve"},
            "type": {"type": "string", "description": "Optional: project|pattern|tool|testing|architecture"},
            "language": {"type": "string", "description": "Optional: filter by programming language"},
            "limit": {"type": "integer", "default": 5},
        },
        "required": ["problem"],
    },
}

# submit_concept — same name and parameter names as the real MCP tool
TOOL_SUBMIT_CONCEPT = {
    "name": "submit_concept",
    "description": (
        "Submit a new concept to the Lore knowledge graph. "
        "Content is scanned for credentials and internal URLs before any write."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "type": {"type": "string", "enum": ["project", "pattern", "tool", "testing", "architecture"]},
            "content": {"type": "string"},
            "when_to_use": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "language": {"type": "string"},
            "dont_use_when": {"type": "string"},
        },
        "required": ["name", "type", "content", "when_to_use", "tags"],
    },
}

TOOLS_RUN1 = [TOOL_BASH, TOOL_WRITE_FILE, TOOL_READ_FILE, TOOL_SUBMIT, TOOL_SUBMIT_CONCEPT]
TOOLS_RUN2 = [TOOL_BASH, TOOL_WRITE_FILE, TOOL_READ_FILE, TOOL_SUBMIT, TOOL_SEARCH_CONCEPTS, TOOL_SUBMIT_CONCEPT]

# ---------------------------------------------------------------------------
# System prompt builders
# ---------------------------------------------------------------------------

def build_system_run1() -> str:
    capture_skill = _load_skill("capture-concept")
    return (
        "You are an expert Python developer. Implement the CLI exactly as specified. "
        "Use the provided tools to write files and run shell commands. "
        "Run the test suite to verify, call submit when all tests pass, "
        "then apply the capture-concept skill.\n\n"
        "---\n"
        f"# Lore Skill: capture-concept\n\n{capture_skill}\n"
        "---\n\n"
        "LORE_CAPTURE_MODE is set to `auto` — skip all confirmation prompts."
    )


def build_system_run2() -> str:
    search_skill = _load_skill("search-concepts")
    capture_skill = _load_skill("capture-concept")
    return (
        "You are an expert Python developer. Implement the CLI exactly as specified. "
        "Use the provided tools to write files and run shell commands. "
        "Run the test suite to verify, call submit when all tests pass, "
        "then apply the capture-concept skill.\n\n"
        "---\n"
        f"# Lore Skill: search-concepts\n\n{search_skill}\n\n"
        f"# Lore Skill: capture-concept\n\n{capture_skill}\n"
        "---\n\n"
        "LORE_CAPTURE_MODE is set to `auto` — skip all confirmation prompts."
    )

# ---------------------------------------------------------------------------
# Lore DB helpers
# ---------------------------------------------------------------------------

def _ensure_db() -> None:
    """Init the Lore DB if it doesn't exist yet."""
    if LORE_DB_PATH.exists():
        return
    LORE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema_path = REPO_ROOT / "lore" / "selfhosted" / "schema.sql"
    conn = sqlite3.connect(str(LORE_DB_PATH))
    if schema_path.exists():
        conn.executescript(schema_path.read_text())
    else:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS concepts (
                concept_id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL,
                content TEXT NOT NULL, language TEXT, when_to_use TEXT,
                dont_use_when TEXT, tags TEXT, source_url TEXT, author TEXT,
                avg_rating REAL DEFAULT 0, usage_count INTEGER DEFAULT 0,
                time_saved_avg_hours REAL, created_at TEXT, embedding BLOB
            );
        """)
    conn.commit()
    conn.close()


def handle_search_concepts(inputs: dict) -> str:
    """SQLite keyword search — same return shape as the real MCP tool."""
    _ensure_db()
    problem = inputs["problem"]
    limit = inputs.get("limit", 5)
    type_filter = inputs.get("type")
    language_filter = inputs.get("language")

    terms = problem.split()[:8]
    clauses = " OR ".join(["name LIKE ? OR content LIKE ? OR tags LIKE ?"] * len(terms))
    params: list = []
    for t in terms:
        like = f"%{t}%"
        params.extend([like, like, like])

    extra = ""
    if type_filter:
        extra += " AND type = ?"
        params.append(type_filter)
    if language_filter:
        extra += " AND (language = ? OR language IS NULL)"
        params.append(language_filter)
    params.append(limit)

    try:
        conn = sqlite3.connect(str(LORE_DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT * FROM concepts WHERE ({clauses}){extra} "
            f"ORDER BY avg_rating DESC, usage_count DESC LIMIT ?",
            params,
        ).fetchall()
        conn.close()
    except sqlite3.Error as exc:
        return json.dumps({"error": str(exc), "results": []})

    results = [
        {
            "concept_id": r["concept_id"],
            "name": r["name"],
            "type": r["type"],
            "content": r["content"],
            "when_to_use": r["when_to_use"] or "",
            "dont_use_when": r["dont_use_when"] or "",
            "avg_rating": r["avg_rating"] or 0.0,
            "usage_count": r["usage_count"] or 0,
            "links": [],
        }
        for r in rows
    ]
    _update_session(r["concept_id"] for r in rows)
    return json.dumps({"results": results})


def handle_submit_concept(inputs: dict) -> str:
    """Write a concept directly to the Lore SQLite DB."""
    _ensure_db()
    concept_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn = sqlite3.connect(str(LORE_DB_PATH))
        conn.execute(
            """
            INSERT INTO concepts (
                concept_id, name, type, content, language,
                when_to_use, dont_use_when, tags,
                source_url, author, avg_rating, usage_count,
                time_saved_avg_hours, created_at, embedding
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                concept_id,
                inputs["name"], inputs["type"], inputs["content"],
                inputs.get("language"), inputs.get("when_to_use", ""),
                inputs.get("dont_use_when", ""),
                json.dumps(inputs.get("tags", [])),
                inputs.get("source_url"), "benchmark",
                0.0, 0, None, now, None,
            ),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as exc:
        return json.dumps({"error": str(exc)})
    _update_session([concept_id])
    return json.dumps({"concept_id": concept_id, "name": inputs["name"]})


def _update_session(concept_ids) -> None:
    """Append concept IDs to the session file — mirrors what the real skill does."""
    try:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        existing = json.loads(SESSION_FILE.read_text()) if SESSION_FILE.exists() else []
        if not isinstance(existing, list):
            existing = []
        new_ids = [cid for cid in concept_ids if cid not in existing]
        SESSION_FILE.write_text(json.dumps(existing + new_ids))
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

def handle_tool(name: str, inputs: dict, workdir: Path | None) -> str:
    if name == "bash" and workdir:
        try:
            result = subprocess.run(
                inputs["command"], shell=True, cwd=workdir,
                capture_output=True, text=True, timeout=90,
            )
        except subprocess.TimeoutExpired:
            return "[error: timed out after 90s]"
        out = result.stdout
        if result.stderr:
            out += f"\n[stderr]\n{result.stderr}"
        if result.returncode != 0:
            out += f"\n[exit {result.returncode}]"
        return out.strip() or "(no output)"

    if name == "write_file" and workdir:
        path = workdir / inputs["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(inputs["content"], encoding="utf-8")
        return f"Written {inputs['path']} ({len(inputs['content'])} chars)"

    if name == "read_file" and workdir:
        path = workdir / inputs["path"]
        return path.read_text(encoding="utf-8") if path.exists() else f"[not found: {inputs['path']}]"

    if name == "submit":
        return "Tests passed — task complete. Now apply the capture-concept skill."

    if name == "search_concepts":
        return handle_search_concepts(inputs)

    if name == "submit_concept":
        return handle_submit_concept(inputs)

    return f"[error: unknown tool {name!r}]"

# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def run_agent(
    system: str,
    tools: list[dict],
    first_message: str,
    workdir: Path | None,
    verbose: bool,
) -> tuple[int, int, int, bool]:
    client = anthropic.Anthropic()
    messages: list[dict] = [{"role": "user", "content": first_message}]
    total_in = total_out = turns = 0
    submitted = False  # True once the agent calls submit (tests passed)

    while turns < MAX_TURNS:
        response = client.messages.create(
            model=MODEL, max_tokens=8192,
            system=system, tools=tools, messages=messages,
        )
        total_in += response.usage.input_tokens
        total_out += response.usage.output_tokens
        turns += 1

        if verbose:
            print(f"  turn {turns:02d} | stop={response.stop_reason} "
                  f"| in={response.usage.input_tokens:,} out={response.usage.output_tokens:,}")

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Natural stop — agent has nothing more to do.
        # Only exit here if submit has already been called (or truly no tools used).
        if response.stop_reason == "end_turn":
            break

        tool_results = []
        for block in assistant_content:
            if block.type != "tool_use":
                continue
            if verbose:
                print(f"    → {block.name}({json.dumps(block.input)[:100]})")
            result = handle_tool(block.name, block.input, workdir)
            if block.name == "submit":
                submitted = True
            if verbose:
                print(f"    ← {str(result)[:120].replace(chr(10), ' ')}")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    return total_in, total_out, turns, submitted

# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_tests(workdir: Path) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_radev_cli.py", "-v", "--tb=short"],
        cwd=workdir, capture_output=True, text=True, timeout=120,
    )
    return result.returncode == 0, result.stdout + result.stderr

# ---------------------------------------------------------------------------
# Benchmark steps
# ---------------------------------------------------------------------------

def _seed_workdir(workdir: Path, mock_url: str) -> None:
    """Copy test files into workdir and set RADEV_BASE_URL for the agent's bash calls."""
    (workdir / "tests").mkdir(exist_ok=True)
    shutil.copy(TEST_FILE, workdir / "tests" / "test_radev_cli.py")
    shutil.copy(CONFTEST_FILE, workdir / "tests" / "conftest.py")
    os.environ["RADEV_BASE_URL"] = mock_url  # inherited by all subprocess.run calls


def step_run1(verbose: bool, dry_run: bool) -> dict | None:
    print(f"\n{'='*60}\n  Run 1 — no Lore skills  |  model: {MODEL}\n{'='*60}")
    if dry_run:
        print("[dry-run] skipping.")
        return None

    mock_url = _start_mock_server()
    print(f"Mock API: {mock_url}")

    # Reset session file so Run 1 starts clean
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text("[]")

    workdir = Path(tempfile.mkdtemp(prefix="lore_bench_run1_"))
    print(f"Working dir: {workdir}")
    try:
        _seed_workdir(workdir, mock_url)

        start = datetime.now()
        in_tok, out_tok, turns, done = run_agent(
            build_system_run1(), TOOLS_RUN1, TASK_PROMPT_RUN1, workdir, verbose,
        )
        elapsed = (datetime.now() - start).total_seconds()

        print(f"\nAgent {'done' if done else 'hit limit'}. Running tests...")
        passed, test_out = run_tests(workdir)
        result = _make_result(1, 0, turns, in_tok, out_tok, elapsed, passed)
        _write_run_md(result, test_out)
        _print_summary(result)
        return result
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def step_run2(verbose: bool, dry_run: bool) -> dict | None:
    concepts_in_db = _count_concepts()
    print(f"\n{'='*60}\n  Run 2 — Lore skills active  |  {concepts_in_db} concepts in DB  |  model: {MODEL}\n{'='*60}")
    if dry_run:
        print("[dry-run] skipping.")
        return None
    if concepts_in_db == 0:
        print("[warning] Lore DB is empty — run wrapup first.", file=sys.stderr)

    SESSION_FILE.write_text("[]")

    mock_url = _start_mock_server()
    print(f"Mock API: {mock_url}")

    workdir = Path(tempfile.mkdtemp(prefix="lore_bench_run2_"))
    print(f"Working dir: {workdir}")
    try:
        _seed_workdir(workdir, mock_url)

        start = datetime.now()
        in_tok, out_tok, turns, done = run_agent(
            build_system_run2(), TOOLS_RUN2, TASK_PROMPT_RUN2, workdir, verbose,
        )
        elapsed = (datetime.now() - start).total_seconds()

        print(f"\nAgent {'done' if done else 'hit limit'}. Running tests...")
        passed, test_out = run_tests(workdir)

        result = _make_result(2, concepts_in_db, turns, in_tok, out_tok, elapsed, passed)
        _write_run_md(result, test_out)
        _print_summary(result)
        return result
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------

def _count_concepts() -> int:
    if not LORE_DB_PATH.exists():
        return 0
    try:
        conn = sqlite3.connect(str(LORE_DB_PATH))
        n = conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
        conn.close()
        return n
    except sqlite3.Error:
        return 0


def _make_result(
    run: int, concepts: int, turns: int,
    in_tok: int, out_tok: int, elapsed: float, passed: bool,
) -> dict:
    return {
        "run": run, "concepts_in_db": concepts,
        "turns": turns, "input_tokens": in_tok,
        "output_tokens": out_tok, "total_tokens": in_tok + out_tok,
        "elapsed": elapsed, "tests_passed": passed,
    }


def _write_run_md(r: dict, test_out: str) -> None:
    lore = f"yes ({r['concepts_in_db']} concepts available)" if r["run"] == 2 else "no"
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / f"run{r['run']}.md").write_text(
        f"# Benchmark — Run {r['run']}\n\n"
        f"| Field | Value |\n|-------|-------|\n"
        f"| Date | {datetime.now().strftime('%Y-%m-%d %H:%M')} |\n"
        f"| Model | {MODEL} |\n"
        f"| Lore skills active | {lore} |\n"
        f"| Turns | {r['turns']} |\n"
        f"| Input tokens | {r['input_tokens']:,} |\n"
        f"| Output tokens | {r['output_tokens']:,} |\n"
        f"| Total tokens | {r['total_tokens']:,} |\n"
        f"| Elapsed | {r['elapsed']:.1f}s |\n"
        f"| Tests passed | {'✅ yes (9/9)' if r['tests_passed'] else '❌ no'} |\n\n"
        f"## Test output\n\n```\n{test_out[-3000:]}\n```\n",
        encoding="utf-8",
    )
    run_n = r["run"]
    print(f"  Results → {RESULTS_DIR / f'run{run_n}.md'}")


def _print_summary(r: dict) -> None:
    print(f"\nRun {r['run']}: turns={r['turns']}  tokens={r['total_tokens']:,}  "
          f"tests={'PASS' if r['tests_passed'] else 'FAIL'}  elapsed={r['elapsed']:.1f}s")


def _write_comparison(r1: dict, r2: dict) -> None:
    def d(a, b):
        return f"{(a - b) / b * 100:+.1f}%" if b else "N/A"

    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "comparison.md").write_text(
        "# Benchmark Comparison — Run 1 vs Run 2\n\n"
        "*Negative delta = Run 2 used fewer resources (Lore helped).*\n\n"
        "| Metric | Run 1 (no Lore) | Run 2 (with Lore) | Delta |\n"
        "|--------|-----------------|-------------------|-------|\n"
        f"| Turns | {r1['turns']} | {r2['turns']} | {d(r2['turns'], r1['turns'])} |\n"
        f"| Input tokens | {r1['input_tokens']:,} | {r2['input_tokens']:,} | {d(r2['input_tokens'], r1['input_tokens'])} |\n"
        f"| Output tokens | {r1['output_tokens']:,} | {r2['output_tokens']:,} | {d(r2['output_tokens'], r1['output_tokens'])} |\n"
        f"| Total tokens | {r1['total_tokens']:,} | {r2['total_tokens']:,} | {d(r2['total_tokens'], r1['total_tokens'])} |\n"
        f"| Elapsed | {r1['elapsed']:.1f}s | {r2['elapsed']:.1f}s | {d(r2['elapsed'], r1['elapsed'])} |\n"
        f"| Tests passed | {'✅' if r1['tests_passed'] else '❌'} | {'✅' if r2['tests_passed'] else '❌'} | — |\n\n"
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
        encoding="utf-8",
    )
    print(f"\nComparison → {RESULTS_DIR / 'comparison.md'}")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lore effectiveness benchmark — radev CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", type=int, choices=[1, 2], metavar="{1,2}")
    mode.add_argument("--all", action="store_true",
                      help="Run 1 then Run 2 in sequence (fully automated)")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    r1 = r2 = None

    if args.run == 1 or args.all:
        r1 = step_run1(args.verbose, args.dry_run)

    if args.run == 2 or args.all:
        r2 = step_run2(args.verbose, args.dry_run)

    if r1 and r2:
        _write_comparison(r1, r2)


if __name__ == "__main__":
    main()
