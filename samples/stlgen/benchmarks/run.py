#!/usr/bin/env python3
"""
Lore effectiveness benchmark — text2stl CLI (4-run progressive design).

Same hard task, same 20-turn budget, run four times.  What changes each time
is what Lore contains and whether concepts have been rated.

  Run 1 — no Lore search available; captures concepts as it works.
           Forced 15-turn capture phase after main loop (win or lose).
  Run 2 — Lore search active; uses unrated concepts from Run 1.
           Captures new patterns it finds.
  Run 3 — Lore search active; concepts from Runs 1+2, rated by wrapup
           phase that ran automatically after Run 2.
  Run 4 — Lore search active; all prior concepts, more rated.

Progression tests:
  - Does Lore help at all?            (Run 1 baseline → Run 2)
  - Does more accumulated knowledge help? (Run 2 → Run 3)
  - Does concept rating improve relevance? (Run 3 → Run 4)

The task is deliberately hard (no approach hint) so early runs may fail
while later runs may succeed — that qualitative jump is the clearest signal.

Usage:
  python benchmarks/run.py --run 1        # baseline
  python benchmarks/run.py --run 2        # after Run 1 + wrapup
  python benchmarks/run.py --run 3        # after Run 2 + wrapup
  python benchmarks/run.py --run 4        # after Run 3 + wrapup
  python benchmarks/run.py --dry-run --run 1
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import anthropic

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL = "claude-sonnet-4-6"
MAX_TURNS = 20          # same budget for every run
MAX_TURNS_CAPTURE = 15  # forced post-loop capture phase
MAX_TURNS_WRAPUP  = 15  # wrapup/rating phase that runs after capture

# Provider — set LORE_LLM_PROVIDER=local to use Ollama / any OpenAI-compatible server.
# See samples/stlgen/README.md §"Running with a local LLM" for setup instructions.
PROVIDER       = os.environ.get("LORE_LLM_PROVIDER", "anthropic")   # "anthropic" | "local"
# For local runs, point the Anthropic SDK at Ollama's /v1/messages endpoint.
LOCAL_BASE_URL = os.environ.get("LORE_LOCAL_BASE_URL", "http://localhost:11434")
LOCAL_MODEL    = os.environ.get("LORE_LOCAL_MODEL", "qwen2.5-coder:32b")
LOCAL_MAX_TOKENS = 8192

# Prepended to the system prompt for local models to encourage immediate tool use.
LOCAL_SYSTEM_PREFIX = """\
CRITICAL INSTRUCTIONS FOR THIS SESSION:
- Do NOT write plans, explanations, or prose of any kind.
- Call a tool on EVERY response by outputting a single JSON object and NOTHING else.
- Format: {"name": "<tool>", "arguments": {<args>}}
- Examples:
    {"name": "bash", "arguments": {"command": "mkdir -p src && ls"}}
    {"name": "write_file", "arguments": {"path": "src/foo.py", "content": "..."}}
- Start immediately with your first tool call. No preamble.

"""

LORE_DB_PATH = Path(os.environ.get("LORE_DB_PATH", "~/.lore/lore.db")).expanduser()
SESSION_FILE = Path(os.environ.get("LORE_SESSION_FILE", "~/.lore/session.json")).expanduser()

REPO_ROOT = Path(__file__).parents[3]
SKILLS_DIR = REPO_ROOT / "skills"
SAMPLES_DIR = Path(__file__).parent.parent
RESULTS_DIR = SAMPLES_DIR / "results"
TEST_FILE = SAMPLES_DIR / "tests" / "test_text2stl_cli.py"
CONFTEST_FILE = SAMPLES_DIR / "tests" / "conftest.py"

# ---------------------------------------------------------------------------
# Skill loader
# ---------------------------------------------------------------------------

def _load_skill(name: str) -> str:
    path = SKILLS_DIR / name / "SKILL.md"
    if not path.exists():
        return f"[skill {name} not found at {path}]"
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.index("---", 3)
        text = text[end + 3:].lstrip()
    return text

# ---------------------------------------------------------------------------
# Task prompt (same for all 4 runs — only Lore availability changes)
# ---------------------------------------------------------------------------

_TASK = """\
Build a Linux CLI tool called `text2stl` that converts a text string into a
3D-printable STL file with readable, correctly formed characters.

Usage:
  text2stl "Hello" -o output.stl   — write STL to output.stl
  text2stl "Hello"                  — write to "Hello.stl" in cwd

Requirements:
- Accept exactly one positional argument: a string of 1–15 printable ASCII characters.
- Exit code 1 (with error to stderr) if the string is empty or exceeds 15 characters.
- Generate a valid, 3D-printable STL:
    • Raised letter geometry — characters must be recognizable when printed.
    • Mesh must be water-tight (manifold) — no open edges, no self-intersections.
    • All face normals must point outward (positive volume).
- Installable via `pip install -e .`
- Entry point registered as `text2stl` in pyproject.toml.

A test file is at tests/test_text2stl_cli.py.
Note: the tests import `trimesh`, `numpy`, and `PIL`. Include them as
dependencies in pyproject.toml so `pip install -e .` installs them.

IMPORTANT: Do NOT modify or delete any file inside the tests/ directory.
The tests are fixed — only modify your implementation files.

Run with: pip install -e . && pytest tests/ -v
"""

_CAPTURE_SUFFIX = """
IMPORTANT — capture DOMAIN concepts as you work:
Whenever you discover something useful about 3D text generation, font libraries,
STL mesh construction, geometry pipelines, or Python packaging — call
`submit_concept` immediately. Examples of things worth capturing:
  - Which library (or combination) works for generating 3D text geometry
  - How to convert font glyph outlines to extrudable 2D polygons
  - How to build a watertight manifold STL mesh from character shapes
  - Approaches that failed and why (use `dont_use_when`)
  - Non-obvious pip/packaging steps for CLI entry points

Do NOT capture concepts about the Lore system itself (session files,
capture-concept mechanics, rate_concept, etc.).

When all 13 tests pass, call `submit`.
"""

# Simplified version for local models — no skill docs, defers capture to after tests pass.
_CAPTURE_SUFFIX_LOCAL = """
Focus on getting the tests to pass first.
Once all 13 tests pass, capture what you learned with submit_concept — which
libraries worked, what failed and why, non-obvious packaging steps.
Then call `submit`.
"""

_SEARCH_SUFFIX = """
Before writing any code, use the `search_concepts` skill to search Lore for
patterns relevant to 3D text generation, STL mesh construction, font libraries,
and Python CLI packaging.

IMPORTANT — capture new DOMAIN concepts as you work:
Call `submit_concept` for any domain insight not already in Lore — about
geometry, fonts, STL format, mesh validity, or packaging.
Do NOT capture concepts about the Lore system itself.

When all 13 tests pass, call `submit`.
"""

# Simplified version for local models.
_SEARCH_SUFFIX_LOCAL = """
Before writing any code, call search_concepts once to find relevant patterns.
Focus on implementation. Once all 13 tests pass, capture new insights with
submit_concept, then call `submit`.
"""

TASK_PROMPT_NO_LORE   = _TASK + (_CAPTURE_SUFFIX_LOCAL if PROVIDER == "local" else _CAPTURE_SUFFIX)
TASK_PROMPT_WITH_LORE = _TASK + (_SEARCH_SUFFIX_LOCAL  if PROVIDER == "local" else _SEARCH_SUFFIX)

# Forced capture prompt — injected into the same conversation after the main loop
FORCED_CAPTURE_PROMPT = """\
The main coding phase is now complete (turn limit reached or task submitted).
You have full context of what you just attempted above.

Now extract domain knowledge from this session.
Call `submit_concept` for every insight that would help a future agent with this task:
  - Which Python libraries work (or don't) for 3D text geometry
  - How to extract font glyph outlines and turn them into extrudable 2D polygons
  - How to build a watertight (manifold) STL from character shapes
  - Approaches that failed and why — capture these with `dont_use_when`
  - Specific errors and what caused them
  - Non-obvious pip / pyproject.toml steps for CLI entry points

Focus only on domain knowledge (3D geometry, STL format, fonts, Python packaging).
Do NOT submit concepts about the Lore system itself.

Call `submit` when you have nothing more to add.
"""

# ---------------------------------------------------------------------------
# Tool definitions (identical signatures to lore/mcp/server.py)
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
    "description": "Signal that the task (or capture phase) is complete.",
    "input_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    },
}

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
            "problem": {"type": "string"},
            "type": {"type": "string"},
            "language": {"type": "string"},
            "limit": {"type": "integer", "default": 5},
        },
        "required": ["problem"],
    },
}

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

TOOL_RATE_CONCEPT = {
    "name": "rate_concept",
    "description": "Rate a concept based on how useful it was in this session.",
    "input_schema": {
        "type": "object",
        "properties": {
            "concept_id": {"type": "string"},
            "outcome": {"type": "integer", "description": "1-5: 5=extremely helpful, 1=not helpful"},
            "hours_saved": {"type": "number", "description": "Estimated hours saved (omit if zero or uncertain)"},
            "notes": {"type": "string", "description": "Optional free-text notes"},
        },
        "required": ["concept_id", "outcome"],
    },
}

TOOL_WEB_SEARCH = {
    "name": "web_search",
    "description": (
        "Search the web for documentation, API examples, and solutions. "
        "Returns up to 5 results with title, URL, and a short snippet. "
        "Use this when you need to look up library APIs or find working code examples."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
        },
        "required": ["query"],
    },
}

TOOLS_NO_LORE   = [TOOL_BASH, TOOL_WRITE_FILE, TOOL_READ_FILE, TOOL_SUBMIT, TOOL_SUBMIT_CONCEPT, TOOL_WEB_SEARCH]
TOOLS_WITH_LORE = [TOOL_BASH, TOOL_WRITE_FILE, TOOL_READ_FILE, TOOL_SUBMIT, TOOL_SEARCH_CONCEPTS, TOOL_SUBMIT_CONCEPT, TOOL_WEB_SEARCH]
TOOLS_CAPTURE   = [TOOL_SUBMIT, TOOL_SUBMIT_CONCEPT]
TOOLS_WRAPUP    = [TOOL_RATE_CONCEPT, TOOL_SUBMIT]

# ---------------------------------------------------------------------------
# System prompt builders
# ---------------------------------------------------------------------------

def build_system_no_lore() -> str:
    if PROVIDER == "local":
        return (
            "You are an expert Python developer. Implement the CLI exactly as specified. "
            "Use tools to write files and run shell commands. "
            "Use web_search to look up library APIs and examples when you are unsure. "
            "Use submit_concept(name, type, content, when_to_use, tags) to save domain patterns you discover."
        )
    capture_skill = _load_skill("capture-concept")
    return (
        "You are an expert Python developer. Implement the CLI exactly as specified. "
        "Use the provided tools to write files and run shell commands. "
        "Capture useful concepts with submit_concept as soon as you discover them.\n\n"
        "---\n"
        f"# Lore Skill: capture-concept\n\n{capture_skill}\n"
        "---\n\n"
        "LORE_CAPTURE_MODE is set to `auto` — skip all confirmation prompts."
    )


def build_system_with_lore() -> str:
    if PROVIDER == "local":
        return (
            "You are an expert Python developer. Implement the CLI exactly as specified. "
            "Use tools to write files and run shell commands. "
            "Search Lore before writing any code. "
            "Use web_search to look up library APIs and examples when Lore doesn't have what you need. "
            "Use submit_concept(name, type, content, when_to_use, tags) to save new domain patterns."
        )
    search_skill  = _load_skill("search-concepts")
    capture_skill = _load_skill("capture-concept")
    return (
        "You are an expert Python developer. Implement the CLI exactly as specified. "
        "Use the provided tools to write files and run shell commands. "
        "Search Lore before writing any code. Capture new patterns as you find them.\n\n"
        "---\n"
        f"# Lore Skill: search-concepts\n\n{search_skill}\n\n"
        f"# Lore Skill: capture-concept\n\n{capture_skill}\n"
        "---\n\n"
        "LORE_CAPTURE_MODE is set to `auto` — skip all confirmation prompts."
    )


def build_system_capture() -> str:
    if PROVIDER == "local":
        return (
            "You are a senior developer reflecting on a just-completed coding attempt. "
            "Extract and record what you learned. "
            "Use submit_concept(name, type, content, when_to_use, tags) to save insights. "
            "Call submit when done."
        )
    capture_skill = _load_skill("capture-concept")
    return (
        "You are a senior developer reflecting on a just-completed coding attempt. "
        "Extract and record everything you learned from the session.\n\n"
        "---\n"
        f"# Lore Skill: capture-concept\n\n{capture_skill}\n"
        "---\n\n"
        "LORE_CAPTURE_MODE is set to `auto` — skip all confirmation prompts."
    )

# ---------------------------------------------------------------------------
# Lore DB helpers
# ---------------------------------------------------------------------------

def _ensure_db() -> None:
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


_VALID_CONCEPT_TYPES = {"project", "pattern", "tool", "testing", "architecture"}
_SEMANTIC_DEDUP_THRESHOLD = 0.88  # cosine similarity above this → reject as duplicate
_embed_model = None  # lazy-loaded sentence-transformers model


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embed_model


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def handle_submit_concept(inputs: dict) -> str:
    _ensure_db()
    name    = (inputs.get("name") or inputs.get("title") or "").strip()
    content = (inputs.get("content") or inputs.get("body") or "").strip()
    if not name:
        return json.dumps({"error": "name is required — provide a short descriptive title"})
    if not content or len(content) < 20:
        return json.dumps({"error": "content is required — describe the concept in detail (at least 20 chars)"})

    raw_type = inputs.get("type") or inputs.get("kind") or ""
    ctype = raw_type if raw_type in _VALID_CONCEPT_TYPES else "pattern"

    # Embed name + content for semantic dedup
    model = _get_embed_model()
    vec: list[float] = model.encode(f"{name}. {content}").tolist()
    import struct as _struct
    embedding_blob = _struct.pack(f"{len(vec)}f", *vec)

    concept_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn = sqlite3.connect(str(LORE_DB_PATH))

        # Backfill embeddings for any concepts saved before semantic dedup was added
        unembedded = conn.execute(
            "SELECT concept_id, name, content FROM concepts WHERE embedding IS NULL"
        ).fetchall()
        if unembedded:
            for eid, ename, econtent in unembedded:
                evec = model.encode(f"{ename}. {econtent}").tolist()
                eblob = _struct.pack(f"{len(evec)}f", *evec)
                conn.execute("UPDATE concepts SET embedding = ? WHERE concept_id = ?", (eblob, eid))
            conn.commit()

        # Semantic dedup: compare against all stored embeddings (now always populated)
        existing = conn.execute(
            "SELECT concept_id, name, embedding FROM concepts WHERE embedding IS NOT NULL"
        ).fetchall()
        for eid, ename, eblob in existing:
            evec = list(_struct.unpack(f"{len(eblob)//4}f", eblob))
            sim = _cosine_similarity(vec, evec)
            if sim >= _SEMANTIC_DEDUP_THRESHOLD:
                conn.close()
                return json.dumps({
                    "error": "semantic_duplicate",
                    "existing_id": eid,
                    "existing_name": ename,
                    "similarity": round(sim, 3),
                    "message": (
                        f"too similar to existing concept '{ename}' "
                        f"(similarity={sim:.2f}) — skip or capture a meaningfully different angle"
                    ),
                })

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
                concept_id, name, ctype, content,
                inputs.get("language"), inputs.get("when_to_use", ""),
                inputs.get("dont_use_when", ""),
                json.dumps(inputs.get("tags", [])),
                inputs.get("source_url"), "benchmark",
                0.0, 0, None, now, embedding_blob,
            ),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as exc:
        return json.dumps({"error": str(exc)})
    _update_session([concept_id])
    return json.dumps({"concept_id": concept_id, "name": name})


def handle_rate_concept(inputs: dict) -> str:
    """Insert a rating and recompute avg_rating on the concept — mirrors db.insert_rating."""
    _ensure_db()
    concept_id = inputs.get("concept_id") or inputs.get("id")
    if not concept_id:
        return json.dumps({"error": "concept_id required"})
    outcome_raw = inputs.get("outcome") or inputs.get("score") or inputs.get("rating")
    if outcome_raw is None:
        return json.dumps({"error": "outcome required (1-5)"})
    outcome = int(outcome_raw)
    if not 1 <= outcome <= 5:
        return json.dumps({"error": "outcome must be 1-5"})
    hours_saved = inputs.get("hours_saved")
    notes = inputs.get("notes")
    now = datetime.now(timezone.utc).isoformat()
    rating_id = str(uuid.uuid4())
    session_id = f"benchmark-run"

    try:
        conn = sqlite3.connect(str(LORE_DB_PATH))
        conn.row_factory = sqlite3.Row
        # Verify concept exists
        if not conn.execute("SELECT 1 FROM concepts WHERE concept_id=?", (concept_id,)).fetchone():
            conn.close()
            return json.dumps({"error": f"concept {concept_id} not found"})
        conn.execute(
            "INSERT INTO ratings (rating_id,concept_id,session_id,outcome,hours_saved,notes,rated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (rating_id, concept_id, session_id, outcome, hours_saved, notes, now),
        )
        # Recompute aggregates
        agg = conn.execute(
            "SELECT AVG(CAST(outcome AS REAL)) AS avg_o, AVG(hours_saved) AS avg_h "
            "FROM ratings WHERE concept_id=?",
            (concept_id,),
        ).fetchone()
        usage_row = conn.execute(
            "SELECT usage_count FROM concepts WHERE concept_id=?", (concept_id,)
        ).fetchone()
        usage_count = usage_row["usage_count"] if usage_row else 0
        conn.execute(
            "UPDATE concepts SET avg_rating=?, usage_count=?, time_saved_avg_hours=? WHERE concept_id=?",
            (agg["avg_o"] or 0.0, usage_count, agg["avg_h"], concept_id),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as exc:
        return json.dumps({"error": str(exc)})
    return json.dumps({"rated": concept_id, "outcome": outcome, "avg_rating": agg["avg_o"] or 0.0})


def handle_web_search(inputs: dict) -> str:
    query = inputs.get("query", "").strip()
    if not query:
        return json.dumps({"error": "query is required"})
    try:
        from ddgs import DDGS
        results = list(DDGS().text(query, max_results=5))
    except Exception as exc:
        return json.dumps({"error": f"search failed: {exc}"})
    if not results:
        return json.dumps({"results": [], "message": "No results found"})
    out = []
    for r in results:
        out.append({
            "title": r.get("title", ""),
            "url": r.get("href", ""),
            "snippet": (r.get("body") or "")[:400],
        })
    return json.dumps({"results": out})


def _update_session(concept_ids) -> None:
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

_BLOCKED_EDITORS = re.compile(r"^\s*(vim?|nano|emacs|pico|gedit|code)\b")

def handle_tool(name: str, inputs: dict, workdir: Path | None) -> str:
    if name == "bash" and workdir:
        cmd = inputs.get("command", "")
        if _BLOCKED_EDITORS.match(cmd):
            return "[error: interactive editors are not available — use write_file to create or modify files]"
        try:
            result = subprocess.run(
                cmd, shell=True, cwd=workdir,
                capture_output=True, text=True, timeout=120,
            )
        except subprocess.TimeoutExpired:
            return "[error: timed out after 120s]"
        out = result.stdout
        if result.stderr:
            out += f"\n[stderr]\n{result.stderr}"
        if result.returncode != 0:
            out += f"\n[exit {result.returncode}]"
        out = out.strip() or "(no output)"
        if len(out) > 4000:
            out = out[:2000] + f"\n... [truncated {len(out)-4000} chars] ...\n" + out[-2000:]
        return out

    if name == "write_file" and workdir:
        path = workdir / inputs["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(inputs["content"], encoding="utf-8")
        return f"Written {inputs['path']} ({len(inputs['content'])} chars)"

    if name == "read_file" and workdir:
        path = workdir / inputs["path"]
        return path.read_text(encoding="utf-8") if path.exists() else f"[not found: {inputs['path']}]"

    if name == "submit":
        if workdir:
            ok, test_out = run_tests(workdir)
            if ok:
                return "✓ all tests passed — session complete."
            return (
                "Tests are NOT passing yet — keep working on the implementation.\n\n"
                + test_out[:3000]
            )
        return "Phase complete."

    if name == "search_concepts":
        return handle_search_concepts(inputs)

    if name == "submit_concept":
        return handle_submit_concept(inputs)

    if name == "rate_concept":
        return handle_rate_concept(inputs)

    if name == "web_search":
        return handle_web_search(inputs)

    return f"[error: unknown tool {name!r}]"

# ---------------------------------------------------------------------------
# Agent loops
# ---------------------------------------------------------------------------

_TOOLS_REGISTRY_NAMES: set[str] = set()


def _extract_first_json_object(text: str) -> str | None:
    """Return the first balanced {...} substring.

    When the model emits multiple tool calls as separate JSON objects in one
    text block, the greedy r"\{.*\}" regex grabs all of them and produces
    invalid JSON. This walks characters to find the end of the first balanced
    object instead.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(text[start:], start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _try_parse_obj(candidate: str) -> dict | None:
    """JSON parse with fallbacks for malformed model output."""
    import ast as _ast
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    # Fallback 1: re-escape literal control chars (model emits raw \n in strings)
    try:
        escaped = candidate.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        obj = json.loads(escaped)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    # Fallback 2: ast.literal_eval handles single-quoted strings that contain double quotes
    try:
        obj = _ast.literal_eval(candidate)
        return obj if isinstance(obj, dict) else None
    except (ValueError, SyntaxError):
        return None


def _parse_tool_from_text_blocks(blocks: list[dict]) -> dict | None:
    """For local models: extract a tool call from text content blocks.

    Ollama's Anthropic-compatible API accepts tool definitions but the model
    often returns JSON in a text block instead of a structured tool_use block.
    Returns an Anthropic-format tool_use dict, or None.
    """
    for block in blocks:
        if block.get("type") != "text":
            continue
        raw = (block.get("text") or "").strip()
        # deepseek-r1 wraps reasoning in <think>...</think> — strip paired blocks
        # then also any stray orphan closing tag the model sometimes emits first
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
        raw = re.sub(r"</think>", "", raw).strip()
        text = re.sub(
            r"^```(?:json)?\s*|\s*```$",
            "",
            raw,
            flags=re.DOTALL,
        ).strip()

        obj = _try_parse_obj(text)
        if obj is None:
            first = _extract_first_json_object(text)
            if first:
                obj = _try_parse_obj(first)
        if obj is None:
            continue

        name = obj.get("name") or obj.get("function")
        args = obj.get("arguments") or obj.get("parameters") or obj.get("args") or {}
        if not name or name not in _TOOLS_REGISTRY_NAMES:
            continue
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        return {
            "type": "tool_use",
            "id": f"toolu_{uuid.uuid4().hex[:16]}",
            "name": name,
            "input": args,
        }
    return None


def _run_agent_anthropic(
    system: str,
    tools: list[dict],
    messages: list[dict],
    workdir: Path | None,
    max_turns: int,
    verbose: bool,
    label: str = "",
    stop_on_submit: bool = False,
) -> tuple[int, int, int, bool, list[dict]]:
    """Unified Anthropic-SDK agent loop for both cloud (Claude) and local (Ollama).

    For local runs, uses Ollama's Anthropic-compatible /v1/messages endpoint and
    applies text promotion when the model returns JSON in a text block instead of
    a structured tool_use block.
    """
    global _TOOLS_REGISTRY_NAMES
    _TOOLS_REGISTRY_NAMES = {t["name"] for t in tools}

    if PROVIDER == "local":
        client = anthropic.Anthropic(base_url=LOCAL_BASE_URL, api_key="ollama", timeout=1200.0)
        model, max_tok = LOCAL_MODEL, LOCAL_MAX_TOKENS
    else:
        client = anthropic.Anthropic()
        model, max_tok = MODEL, 8192

    total_in = total_out = turns = 0
    submitted = False

    while turns < max_turns:
        try:
            response = client.messages.create(
                model=model, max_tokens=max_tok,
                system=system, tools=tools, messages=messages,
            )
        except Exception as exc:
            print(f"  {label}[API ERROR turn {turns+1}] {exc}", flush=True)
            break

        total_in  += response.usage.input_tokens
        total_out += response.usage.output_tokens
        turns += 1

        print(
            f"  {label}turn {turns:02d}/{max_turns} | finish={response.stop_reason} "
            f"| in={response.usage.input_tokens} out={response.usage.output_tokens}",
            flush=True,
        )

        # Serialise content to plain dicts so messages stay JSON-serialisable
        content_blocks: list[dict] = []
        for b in (response.content or []):
            if b.type == "tool_use":
                content_blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
            elif b.type == "text":
                content_blocks.append({"type": "text", "text": b.text})

        if not content_blocks:
            print(f"  {label}[empty response on turn {turns} — retrying]", flush=True)
            messages.append({"role": "user", "content": "You must call one of the available tools now. Output only a JSON tool call."})
            continue

        messages.append({"role": "assistant", "content": content_blocks})

        # Text promotion: local model wrote JSON in a text block instead of tool_use
        if PROVIDER == "local" and not any(b.get("type") == "tool_use" for b in content_blocks):
            promoted = _parse_tool_from_text_blocks(content_blocks)
            if promoted:
                args_preview = json.dumps(promoted["input"])[:120].replace("\n", " ")
                print(f"  {label}[promoted text tool call: {promoted['name']}  args={args_preview}]", flush=True)
                messages[-1] = {"role": "assistant", "content": [promoted]}
                content_blocks = [promoted]
            else:
                if turns >= max_turns:
                    print(f"  {label}[no tool calls, turn limit reached — stopping]", flush=True)
                    break
                # Log what the model said + attempt parse error for diagnosis
                raw_text = " ".join(b.get("text","") for b in content_blocks if b.get("type")=="text")
                preview = raw_text[:1500].replace(chr(10), " ")
                print(f"  {label}[no tool calls on turn {turns} — model said: {preview}]", flush=True)
                # Show why parsing failed
                _diag = re.sub(r"<think>.*?</think>|</think>", "", raw_text, flags=re.DOTALL).strip()
                _diag = re.sub(r"^```(?:json)?\s*|\s*```$", "", _diag, flags=re.DOTALL).strip()
                first_obj = _extract_first_json_object(_diag)
                if first_obj:
                    try:
                        json.loads(first_obj)
                    except json.JSONDecodeError as _e:
                        print(f"  {label}[parse error: {_e} | first 200 chars of obj: {first_obj[:200].replace(chr(10),' ')}]", flush=True)
                else:
                    print(f"  {label}[parse error: no balanced {{...}} found in text]", flush=True)
                messages.append({
                    "role": "user",
                    "content": "You must call one of the available tools now. Output only a JSON tool call.",
                })
                continue

        if response.stop_reason == "end_turn" and PROVIDER != "local":
            break

        # Execute tool calls
        tool_results = []
        for block in content_blocks:
            if block.get("type") != "tool_use":
                continue
            name   = block["name"]
            inputs = block.get("input", {})
            bid    = block["id"]
            if verbose:
                print(f"    → {name}({json.dumps(inputs)[:100]})", flush=True)
            result = handle_tool(name, inputs, workdir)
            if name == "submit":
                if workdir is None or "✓ all tests passed" in result:
                    submitted = True
            if verbose:
                print(f"    ← {str(result)[:120].replace(chr(10), ' ')}", flush=True)
            tool_results.append({"type": "tool_result", "tool_use_id": bid, "content": result})

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

        if stop_on_submit and submitted:
            break

    return total_in, total_out, turns, submitted, messages


def run_agent(
    system: str,
    tools: list[dict],
    first_message: str,
    workdir: Path | None,
    max_turns: int,
    verbose: bool,
    stop_on_submit: bool = False,
) -> tuple[int, int, int, bool, list[dict]]:
    """Returns (input_tokens, output_tokens, turns_used, submitted, messages)."""
    messages: list[dict] = [{"role": "user", "content": first_message}]
    return _run_agent_anthropic(system, tools, messages, workdir, max_turns, verbose,
                                stop_on_submit=stop_on_submit)


def run_capture_phase(messages: list[dict], system: str, verbose: bool) -> tuple[int, int, int]:
    """Continue the same conversation for concept extraction.

    Keeps only the last CAPTURE_HISTORY_TURNS message pairs to avoid exceeding
    the local model's context window (qwen2.5-coder:32b defaults to 32K tokens).
    Returns (in_tokens, out_tokens, turns).
    """
    CAPTURE_HISTORY_TURNS = 4  # keep last N user/assistant pairs (~8 messages)
    tail = messages[-(CAPTURE_HISTORY_TURNS * 2):] if len(messages) > CAPTURE_HISTORY_TURNS * 2 else list(messages)
    print(f"\n  [capture] concept extraction — up to {MAX_TURNS_CAPTURE} turns "
          f"(using last {len(tail)} messages of {len(messages)} to stay within context window)...")
    capture_messages = tail + [{"role": "user", "content": FORCED_CAPTURE_PROMPT}]
    in_tok, out_tok, turns, _, _ = _run_agent_anthropic(
        system, TOOLS_CAPTURE, capture_messages,
        workdir=None, max_turns=MAX_TURNS_CAPTURE, verbose=verbose, label="[capture] ",
    )
    print(f"  [capture] done — {_count_concepts()} total concepts in DB "
          f"({turns} turns, {in_tok + out_tok:,} tokens)")
    return in_tok, out_tok, turns


def run_wrapup_phase(run_num: int, verbose: bool) -> tuple[int, int, int]:
    """
    Rate the concepts used during this run — mirrors the lore:wrapup skill.

    Reads session.json, resolves concept names, presents them to an agent that
    calls rate_concept for each one, then clears the session file.
    Returns (input_tokens, output_tokens, turns_used).
    """
    try:
        session_ids: list[str] = json.loads(SESSION_FILE.read_text()) if SESSION_FILE.exists() else []
    except (json.JSONDecodeError, OSError):
        session_ids = []

    if not session_ids:
        print(f"  [wrapup] no concepts in session file — skipping.")
        return 0, 0, 0

    # Resolve concept names from DB for a readable prompt
    concept_lines: list[str] = []
    try:
        conn = sqlite3.connect(str(LORE_DB_PATH))
        conn.row_factory = sqlite3.Row
        for cid in session_ids:
            row = conn.execute(
                "SELECT name, type, avg_rating FROM concepts WHERE concept_id=?", (cid,)
            ).fetchone()
            if row:
                concept_lines.append(
                    f"  - [{row['type']}] {row['name']}  (current avg_rating: {row['avg_rating']:.1f})  id={cid}"
                )
            else:
                concept_lines.append(f"  - (unresolved)  id={cid}")
        conn.close()
    except sqlite3.Error:
        concept_lines = [f"  - id={cid}" for cid in session_ids]

    concept_list = "\n".join(concept_lines)

    wrapup_system = build_system_capture()
    if PROVIDER == "local":
        wrapup_system = LOCAL_SYSTEM_PREFIX + wrapup_system

    if PROVIDER == "local":
        # One focused API call per concept — avoids stalling in a shared session.
        client = anthropic.Anthropic(base_url=LOCAL_BASE_URL, api_key="ollama", timeout=1200.0)
        global _TOOLS_REGISTRY_NAMES
        _TOOLS_REGISTRY_NAMES = {t["name"] for t in TOOLS_WRAPUP}

        print(f"\n  [wrapup] rating {len(session_ids)} concept(s) — one call per concept...", flush=True)
        total_in = total_out = total_turns = 0

        for i, cid in enumerate(session_ids):
            line = concept_lines[i].strip() if i < len(concept_lines) else f"id={cid}"
            single_prompt = (
                f"Rate this concept using rate_concept.\n\n"
                f"Concept: {line}\n\n"
                f"Outcome guide: 5=solved key problem, 4=very helpful, 3=somewhat useful, "
                f"2=barely used, 1=irrelevant"
            )
            wrapup_msgs: list[dict] = [{"role": "user", "content": single_prompt}]
            rated = False

            for attempt in range(5):
                try:
                    response = client.messages.create(
                        model=LOCAL_MODEL,
                        max_tokens=LOCAL_MAX_TOKENS,
                        system=wrapup_system,
                        tools=TOOLS_WRAPUP,
                        messages=wrapup_msgs,
                    )
                except Exception as exc:
                    print(f"  [wrapup] concept {i+1} API error: {exc}", flush=True)
                    break

                total_in  += response.usage.input_tokens
                total_out += response.usage.output_tokens
                total_turns += 1

                content_blocks: list[dict] = []
                for b in response.content:
                    if b.type == "tool_use":
                        content_blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
                    elif b.type == "text":
                        content_blocks.append({"type": "text", "text": b.text})

                # Text promotion for local models
                if not any(b.get("type") == "tool_use" for b in content_blocks):
                    promoted = _parse_tool_from_text_blocks(content_blocks)
                    if promoted:
                        print(f"  [wrapup] [promoted text tool call: {promoted['name']}]", flush=True)
                        content_blocks = [promoted]

                tool_blocks = [b for b in content_blocks if b.get("type") == "tool_use"]
                if not tool_blocks:
                    print(f"  [wrapup] concept {i+1} no tool call (attempt {attempt+1}) — retrying", flush=True)
                    wrapup_msgs.append({"role": "assistant", "content": content_blocks})
                    wrapup_msgs.append({"role": "user", "content": f"Call rate_concept for concept id={cid}."})
                    continue

                for block in tool_blocks:
                    if verbose:
                        print(f"    → {block['name']}({json.dumps(block.get('input',{}))[:100]})", flush=True)
                    result = handle_tool(block["name"], block.get("input", {}), workdir=None)
                    if verbose:
                        print(f"    ← {str(result)[:120].replace(chr(10), ' ')}", flush=True)
                    if block["name"] == "rate_concept":
                        rated = True
                break

            if not rated:
                print(f"  [wrapup] concept {i+1} ({cid}) — skipped after 5 attempts", flush=True)

        SESSION_FILE.write_text("[]")
        print(f"  [wrapup] done ({total_turns} turns, {total_in + total_out:,} tokens) — session cleared.", flush=True)
        return total_in, total_out, total_turns

    # Cloud / unified path: single session rates all concepts, ends with submit
    wrapup_prompt = (
        f"You have just completed Run {run_num} of the text2stl benchmark. "
        f"The following concepts were used or captured during this run:\n\n"
        f"{concept_list}\n\n"
        "For each concept, reflect on whether it was useful in this session "
        "and call `rate_concept` with:\n"
        "  - outcome 5: directly solved a key problem\n"
        "  - outcome 4: meaningfully helpful\n"
        "  - outcome 3: somewhat relevant but not decisive\n"
        "  - outcome 2: appeared in results but wasn't applied\n"
        "  - outcome 1: irrelevant or misleading\n\n"
        "Add hours_saved if you can honestly estimate it. "
        "Call `submit` when all concepts have been rated."
    )

    print(f"\n  [wrapup] rating {len(session_ids)} concept(s) — up to {MAX_TURNS_WRAPUP} turns...", flush=True)
    in_tok, out_tok, turns, _, _messages = run_agent(
        system=wrapup_system,
        tools=TOOLS_WRAPUP,
        first_message=wrapup_prompt,
        workdir=None,
        max_turns=MAX_TURNS_WRAPUP,
        verbose=verbose,
        stop_on_submit=True,
    )

    # Clear session file — same final step as the real wrapup skill
    SESSION_FILE.write_text("[]")
    print(f"  [wrapup] done ({turns} turns, {in_tok + out_tok:,} tokens) — session cleared.", flush=True)
    return in_tok, out_tok, turns

# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_tests(workdir: Path) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_text2stl_cli.py", "-v", "--tb=short"],
        cwd=workdir, capture_output=True, text=True, timeout=300,
    )
    return result.returncode == 0, result.stdout + result.stderr

# ---------------------------------------------------------------------------
# Core step function — all 4 runs share this logic
# ---------------------------------------------------------------------------

def step_run(run_num: int, verbose: bool, dry_run: bool, max_turns: int = MAX_TURNS) -> dict | None:
    lore_active = run_num > 1

    if run_num == 1:
        _clear_db()
        _seed_concepts()

    concepts_in_db = _count_concepts()

    lore_label = f"Lore ON ({concepts_in_db} concepts)" if lore_active else "no Lore"
    print(f"\n{'='*60}\n  Run {run_num} — {lore_label}  |  {max_turns} turns  |  {MODEL}\n{'='*60}")

    if dry_run:
        print("[dry-run] skipping.")
        return None

    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text("[]")
    concepts_before = concepts_in_db

    system      = build_system_with_lore() if lore_active else build_system_no_lore()
    if PROVIDER == "local":
        system = LOCAL_SYSTEM_PREFIX + system
    tools       = TOOLS_WITH_LORE if lore_active else TOOLS_NO_LORE
    task_prompt = TASK_PROMPT_WITH_LORE if lore_active else TASK_PROMPT_NO_LORE

    workdir = Path(tempfile.mkdtemp(prefix=f"lore_stlgen_run{run_num}_"))
    print(f"Working dir: {workdir}")
    try:
        (workdir / "tests").mkdir(exist_ok=True)
        shutil.copy(TEST_FILE,    workdir / "tests" / "test_text2stl_cli.py")
        shutil.copy(CONFTEST_FILE, workdir / "tests" / "conftest.py")

        start = datetime.now()
        in_tok, out_tok, turns, submitted, messages = run_agent(
            system, tools, task_prompt, workdir, max_turns, verbose,
            stop_on_submit=True,
        )
        elapsed = (datetime.now() - start).total_seconds()

        # Continue same session for concept extraction — agent has full history
        c_in, c_out, c_turns = run_capture_phase(messages, system, verbose)
        in_tok  += c_in
        out_tok += c_out

        print(f"\nMain loop {'✓ submitted' if submitted else '✗ hit limit'}. Running tests...")
        passed, test_out = run_tests(workdir)

        concepts_captured = _count_concepts() - concepts_before

        # Wrapup: rate all concepts used this run, then clear session file
        w_in, w_out, w_turns = run_wrapup_phase(run_num, verbose)
        in_tok  += w_in
        out_tok += w_out

        result = {
            "run": run_num,
            "lore_active": lore_active,
            "concepts_available": concepts_in_db,
            "concepts_captured": concepts_captured,
            "turn_budget": max_turns,
            "turns_main": turns,
            "turns_capture": c_turns,
            "turns_wrapup": w_turns,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": in_tok + out_tok,
            "elapsed": elapsed,
            "task_submitted": submitted,
            "tests_passed": passed,
        }
        _write_run_md(result, test_out)
        _print_summary(result)
        return result
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

# ---------------------------------------------------------------------------
# Output helpers
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


def _clear_db() -> None:
    """Drop all concepts and ratings — called before Run 1 to start clean."""
    _ensure_db()
    conn = sqlite3.connect(str(LORE_DB_PATH))
    conn.execute("DELETE FROM ratings")
    conn.execute("DELETE FROM concepts")
    conn.commit()
    conn.close()
    if SESSION_FILE.exists():
        SESSION_FILE.write_text("[]")
    print("  [reset] concept DB cleared — starting from 0 concepts.")


def _seed_concepts() -> None:
    """Inject hand-authored seed concepts from seed_concepts/ into the DB.

    Seed concepts are markdown files with YAML frontmatter providing name, type,
    when_to_use, and tags.  The file body below the frontmatter becomes content.
    They survive the DB reset and are available from Run 1 onward so that the
    Lore-ON runs (2 and 4) can find correct library knowledge even when no prior
    run has captured it organically.

    See README.md §Seeding rationale for why this is done.
    """
    seed_dir = Path(__file__).parent / "seed_concepts"
    if not seed_dir.exists():
        return
    seeded = 0
    for md_file in sorted(seed_dir.glob("*.md")):
        raw = md_file.read_text(encoding="utf-8")
        # Parse YAML frontmatter between --- markers
        fm: dict = {}
        body = raw
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                import re as _re
                for line in parts[1].splitlines():
                    m = _re.match(r"^(\w[\w_-]*):\s*(.+)$", line.strip())
                    if m:
                        fm[m.group(1)] = m.group(2).strip()
                body = parts[2].strip()
        inputs = {
            "name":        fm.get("name", md_file.stem),
            "type":        fm.get("type", "library"),
            "content":     body,
            "when_to_use": fm.get("when_to_use", ""),
            "tags":        fm.get("tags", "").split(","),
        }
        result = handle_submit_concept(inputs)
        parsed = json.loads(result) if result.startswith("{") else {}
        if "error" in parsed:
            print(f"  [seed] {md_file.name}: skipped — {parsed['error']}", flush=True)
        else:
            print(f"  [seed] {md_file.name}: concept #{parsed.get('id','?')} inserted", flush=True)
            seeded += 1
    if seeded:
        print(f"  [seed] {seeded} concept(s) seeded into DB.", flush=True)


def _write_run_md(r: dict, test_out: str) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    run_n = r["run"]
    lore = f"yes ({r['concepts_available']} concepts)" if r["lore_active"] else "no"
    (RESULTS_DIR / f"run{run_n}.md").write_text(
        f"# Benchmark — Run {run_n}\n\n"
        f"| Field | Value |\n|-------|-------|\n"
        f"| Date | {datetime.now().strftime('%Y-%m-%d %H:%M')} |\n"
        f"| Model | {LOCAL_MODEL if PROVIDER == 'local' else MODEL} |\n"
        f"| Lore search active | {lore} |\n"
        f"| Web search active | yes |\n"
        f"| Turn budget | {r['turn_budget']} |\n"
        f"| Turns (main loop) | {r['turns_main']} |\n"
        f"| Turns (capture) | {r['turns_capture']} |\n"
        f"| Turns (wrapup) | {r['turns_wrapup']} |\n"
        f"| Task submitted | {'yes' if r['task_submitted'] else 'no (hit limit)'} |\n"
        f"| Input tokens | {r['input_tokens']:,} |\n"
        f"| Output tokens | {r['output_tokens']:,} |\n"
        f"| Total tokens | {r['total_tokens']:,} |\n"
        f"| Concepts captured this run | {r['concepts_captured']} |\n"
        f"| Elapsed | {r['elapsed']:.1f}s |\n"
        f"| Tests passed | {'✅ yes (13/13)' if r['tests_passed'] else '❌ no'} |\n\n"
        f"## Test output\n\n```\n{test_out[-3000:]}\n```\n",
        encoding="utf-8",
    )
    print(f"  Results → {RESULTS_DIR / f'run{run_n}.md'}")


def _print_summary(r: dict) -> None:
    sub = "✓" if r["task_submitted"] else "✗"
    tests = "PASS" if r["tests_passed"] else "FAIL"
    print(
        f"\nRun {r['run']}: turns={r['turns_main']}/{r['turn_budget']}  "
        f"tokens={r['total_tokens']:,}  tests={tests}  "
        f"submitted={sub}  concepts+={r['concepts_captured']}  "
        f"elapsed={r['elapsed']:.1f}s"
    )



def _write_comparison(results: list[dict]) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    header = (
        "# Benchmark Comparison — 4 Runs, Same Task, Same Budget\n\n"
        "*All runs: same hard task, 20-turn budget.\n"
        "What changes: Lore content (more each run) and concept ratings.*\n\n"
        "| Metric | Run 1 | Run 2 | Run 3 | Run 4 |\n"
        "|--------|-------|-------|-------|-------|\n"
    )

    def cell(r: dict | None, key: str, fmt=str) -> str:
        return fmt(r[key]) if r else "—"

    def tok(r):
        return f"{r['total_tokens']:,}" if r else "—"

    by_run = {r["run"]: r for r in results}
    rows = [
        ("Lore concepts available",
            *[str(by_run[i]["concepts_available"]) if i in by_run else "—" for i in range(1, 5)]),
        ("Task submitted",
            *[("✓" if by_run[i]["task_submitted"] else "✗") if i in by_run else "—" for i in range(1, 5)]),
        ("Tests passed",
            *[("✅" if by_run[i]["tests_passed"] else "❌") if i in by_run else "—" for i in range(1, 5)]),
        ("Turns (main loop)",
            *[str(by_run[i]["turns_main"]) if i in by_run else "—" for i in range(1, 5)]),
        ("Total tokens",
            *[f"{by_run[i]['total_tokens']:,}" if i in by_run else "—" for i in range(1, 5)]),
        ("Concepts captured",
            *[str(by_run[i]["concepts_captured"]) if i in by_run else "—" for i in range(1, 5)]),
        ("Elapsed (s)",
            *[f"{by_run[i]['elapsed']:.0f}" if i in by_run else "—" for i in range(1, 5)]),
    ]

    table = header
    for label, *cells in rows:
        table += f"| {label} | {' | '.join(cells)} |\n"
    table += f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"

    (RESULTS_DIR / "comparison.md").write_text(table, encoding="utf-8")
    print(f"\nComparison → {RESULTS_DIR / 'comparison.md'}")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lore effectiveness benchmark — text2stl, 4 progressive runs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", type=int, choices=[1, 2, 3, 4, 5], metavar="{1,2,3,4,5}",
                      help="Run a single numbered run")
    mode.add_argument("--all", action="store_true",
                      help="Run all 4 in sequence (pauses for wrapup reminders)")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-turns", type=int, default=MAX_TURNS, metavar="N",
                        help=f"Turn budget for the main coding loop (default: {MAX_TURNS})")
    args = parser.parse_args()

    runs = [1, 2, 3, 4] if args.all else [args.run]
    results: list[dict] = []

    for run_num in runs:
        res = step_run(run_num, args.verbose, args.dry_run, max_turns=args.max_turns)
        if res:
            results.append(res)

    if len(results) >= 2:
        _write_comparison(results)


if __name__ == "__main__":
    main()
