#!/usr/bin/env python3
"""
Lore effectiveness benchmark — text2stl CLI (10-run progressive design).

Same hard task, same 40-turn budget, run ten times.  What changes each time
is what Lore contains and whether concepts have been rated.

  Run 1  — no Lore search; captures concepts after the main loop.
  Run 2+ — Lore search active; concepts accumulate and get rated each run.

Progression tests:
  - Does Lore help at all?                  (Run 1 baseline → Run 2)
  - Does accumulated knowledge compound?    (Run 2 → Run 5+)
  - Does concept rating improve relevance?  (unrated early → rated later)

All concept operations go through the selfhosted Lore API (LORE_API_URL,
default http://localhost:8765).  No direct SQLite access.

Usage:
  python benchmarks/run.py --all             # all 10 runs in sequence
  python benchmarks/run.py --run 1           # single run
  python benchmarks/run.py --dry-run --run 1
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote as _quote

import anthropic

from lore.core.constants import VALID_CONCEPT_TYPES as _VALID_CONCEPT_TYPES

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL = "claude-sonnet-4-6"
MAX_TURNS        = 40  # same budget for every run
MAX_TURNS_WRAPUP = 30  # unified end-of-session wrapup (rate + capture)

# Provider — set LORE_LLM_PROVIDER=local to use Ollama / any OpenAI-compatible server.
# See samples/stlgen/README.md §"Running with a local LLM" for setup instructions.
PROVIDER       = os.environ.get("LORE_LLM_PROVIDER", "anthropic")   # "anthropic" | "local"
# For local runs, point the Anthropic SDK at Ollama's /v1/messages endpoint.
LOCAL_BASE_URL = os.environ.get("LORE_LOCAL_BASE_URL", "http://localhost:11434")
LOCAL_MODEL    = os.environ.get("LORE_LOCAL_MODEL", "qwen2.5-coder:32b")
# Selfhosted Lore API — all concept operations go through here.
LORE_API_URL   = os.environ.get("LORE_API_URL", "http://localhost:8765")
LOCAL_MAX_TOKENS = 8192

# Prepended to the system prompt for local models to encourage immediate tool use.
# /no_think disables Qwen3.x thinking mode — prevents multi-minute <think> chains
# on complex inputs (e.g. IoU test failures) that cause apparent hangs.
LOCAL_SYSTEM_PREFIX = """\
/no_think

CRITICAL INSTRUCTIONS FOR THIS SESSION:
- Before acting, write 1-3 short sentences of reasoning: what the last tool
  result actually told you, and what it implies you should do next. Use this
  to catch mistakes — e.g. an error message that points at a different file
  or line than the one you were about to edit.
- Before using any library function you are not 100% certain exists, verify it
  first: bash -c "python -c 'import <lib>; print(dir(<lib>.<module>))'"
  Do NOT assume an API exists — check it.
- If a tool call or test fails, do NOT rewrite the same code again. Read the
  exact error, identify the specific line that caused it, then change your
  approach entirely if needed.
- After your reasoning, call exactly ONE tool by outputting a single JSON
  object: {"name": "<tool>", "arguments": {<args>}}
- Examples:
    {"name": "bash", "arguments": {"command": "mkdir -p src && ls"}}
    {"name": "write_file", "arguments": {"path": "src/foo.py", "content": "..."}}
- Never emit more than one JSON object in a response — pick one action.
- End your response with the JSON object — nothing after it.

"""

SESSION_FILE = Path(os.environ.get("LORE_SESSION_FILE", "~/.lore/session.json")).expanduser()

REPO_ROOT = Path(__file__).parents[3]
SKILLS_DIR = REPO_ROOT / "skills"
SAMPLES_DIR = Path(__file__).parent.parent
RESULTS_DIR = SAMPLES_DIR / "results"
TEST_FILE = SAMPLES_DIR / "tests" / "test_text2stl_cli.py"
CONFTEST_FILE = SAMPLES_DIR / "tests" / "conftest.py"

# Per-run workdirs are kept on disk for inspection until the whole benchmark
# invocation finishes (see _cleanup_all_workdirs), rather than being deleted
# right after each run — useful for manually checking generated code/output.
_ALL_WORKDIRS: list[Path] = []
_CURRENT_SESSION_ID: str | None = None  # set per-run so search calls carry X-Session-ID

# ---------------------------------------------------------------------------
# Backend selection — set by --backend flag in main(), read by handlers.
# ---------------------------------------------------------------------------

# Active backend: "selfhosted" (default) or "gists".
_ACTIVE_BACKEND: str = "selfhosted"

# Accumulates gist IDs created during a series so they can be deleted at end.
_SERIES_GIST_IDS: list[str] = []

# Concept IDs submitted during the current run (reset each run).
_RUN_SUBMITTED_IDS: list[str] = []

# Lazily initialised GistsClient — created on first gists-backend call.
_gists_client_instance = None


def _get_gists_client():
    """Return a lazily-initialised GistsClient.

    Requires LORE_GITHUB_TOKEN to be set in the environment.

    Returns:
        An authenticated GistsClient instance.
    """
    global _gists_client_instance
    if _gists_client_instance is None:
        from lore.mcp.backends.gists_client import GistsClient
        _gists_client_instance = GistsClient()
    return _gists_client_instance

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
# Task prompt (same for all runs — only Lore availability changes)
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

# Simplified version for local models — capture as you go, not just on success.
_CAPTURE_SUFFIX_LOCAL = """
Focus on getting the tests to pass. As you work, capture domain insights with
submit_concept whenever you discover something non-obvious — which libraries work
for 3D text generation, what failed and why, gotchas with STL mesh validity or
packaging. Do NOT wait for tests to pass before capturing.
When all 13 tests pass, call `submit`.
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
Focus on implementation. Capture domain insights with submit_concept as you
discover them — do NOT wait for tests to pass. When all 13 tests pass, call `submit`.
"""

TASK_PROMPT_NO_LORE   = _TASK + (_CAPTURE_SUFFIX_LOCAL if PROVIDER == "local" else _CAPTURE_SUFFIX)
TASK_PROMPT_WITH_LORE = _TASK + (_SEARCH_SUFFIX_LOCAL  if PROVIDER == "local" else _SEARCH_SUFFIX)

# Forced capture prompt — injected into the same conversation after the main loop
WRAPUP_HISTORY_TURNS = 15  # coding session turns to include as wrapup context

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
    "description": "Signal that all tests pass and the coding task is complete. Only call this after all 13 tests pass.",
    "input_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    },
}

TOOL_FINISH_WRAPUP = {
    "name": "finish_wrapup",
    "description": "Signal that you have finished capturing and rating all concepts and have nothing more to add. Call this when your capture and rating work is done.",
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
TOOLS_WRAPUP    = [TOOL_READ_FILE, TOOL_RATE_CONCEPT, TOOL_SUBMIT_CONCEPT, TOOL_FINISH_WRAPUP]

# ---------------------------------------------------------------------------
# System prompt builders
# ---------------------------------------------------------------------------

def build_system_no_lore() -> str:
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


def build_system_wrapup() -> str:
    wrapup_skill   = _load_skill("wrapup")
    capture_skill  = _load_skill("capture-concept")
    return (
        "You are a senior developer closing out a coding session.\n\n"
        "---\n"
        f"# Lore Skill: wrapup\n\n{wrapup_skill}\n\n"
        f"# Lore Skill: capture-concept\n\n{capture_skill}\n"
        "---\n\n"
        "Follow the wrapup skill steps in order.\n"
        "Step 1: rate every concept ID listed below (use rate_concept).\n"
        "Step 2 (reflection gate) is MANDATORY — enumerate 3-6 implementation areas "
        "and evaluate each for Lore-worthy insights, even if the session was short.\n"
        "Step 3: call submit_concept for each insight identified in Step 2 that is not "
        "already in Lore. You MUST call submit_concept at least once if you learned anything new.\n"
        "Step 4: call finish_wrapup only after Steps 1-3 are complete.\n"
        "When the skill says to invoke capture-concept, call submit_concept directly.\n"
        "LORE_CAPTURE_MODE is set to `auto` — skip all confirmation prompts.\n"
        "Do NOT call finish_wrapup until you have completed Steps 2 and 3."
    )


def build_system_capture() -> str:
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
# Lore API helpers
# ---------------------------------------------------------------------------

def _lore_api(method: str, path: str, session_id: str | None = None,
              admin_token: str | None = None, **kwargs) -> dict:
    """Call the selfhosted Lore API and return parsed JSON. Raises on HTTP errors."""
    import urllib.request as _ur
    import urllib.error as _ue
    url = f"{LORE_API_URL}{path}"
    data = json.dumps(kwargs["json"]).encode() if "json" in kwargs else None
    headers = {"Content-Type": "application/json"} if data else {}
    if session_id:
        headers["X-Session-ID"] = session_id
    if admin_token:
        headers["X-Admin-Token"] = admin_token
    req = _ur.Request(url, data=data, method=method, headers=headers)
    try:
        with _ur.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except _ue.HTTPError as exc:
        # Parse the response body — 503 responses include concept_id so callers
        # can still track the concept even when Qdrant indexing fails.
        try:
            body = json.loads(exc.read())
        except Exception:
            body = {}
        body.setdefault("error", str(exc))
        return body
    except Exception as exc:
        return {"error": str(exc)}


def handle_search_concepts(inputs: dict) -> str:
    """Dispatch search_concepts to the active backend."""
    if _ACTIVE_BACKEND == "gists":
        return _handle_search_concepts_gists(inputs)
    return _handle_search_concepts_selfhosted(inputs)


def _handle_search_concepts_selfhosted(inputs: dict) -> str:
    """Search concepts via the selfhosted Lore API."""
    payload: dict = {"problem": inputs["problem"]}
    if inputs.get("limit"):
        payload["limit"] = inputs["limit"]
    if inputs.get("type"):
        payload["type"] = inputs["type"]
    if inputs.get("language"):
        payload["language"] = inputs["language"]
    result = _lore_api("POST", "/v1/concepts/search", session_id=_CURRENT_SESSION_ID, json=payload)
    if "error" not in result:
        _update_session(r["concept_id"] for r in result.get("results", []))
    return json.dumps(result)


def _handle_search_concepts_gists(inputs: dict) -> str:
    """Search concepts via the gists backend (or semantic server if LORE_SEMANTIC_URL is set)."""
    problem = inputs.get("problem", "")
    limit = inputs.get("limit") or 5
    ctype = inputs.get("type")
    language = inputs.get("language")

    semantic_url = os.environ.get("LORE_SEMANTIC_URL")
    if semantic_url:
        # Try the semantic search server first.
        try:
            import urllib.request as _ur
            params = f"q={_quote(problem)}&k={limit}"
            req = _ur.Request(f"{semantic_url.rstrip('/')}/search?{params}")
            with _ur.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
            _update_session(r["concept_id"] for r in result.get("results", []))
            return json.dumps(result)
        except Exception as exc:
            print(f"  [gists-search] semantic server failed ({exc}), falling back to gists.", flush=True)

    # Fall back to GitHub tag search.
    from lore.mcp.backends import gists as gists_backend
    try:
        result = gists_backend.search_concepts(
            _get_gists_client(),
            problem=problem,
            type=ctype,
            language=language,
            limit=limit,
        )
        _update_session(r["concept_id"] for r in result.get("results", []))
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc), "results": []})


def handle_submit_concept(inputs: dict) -> str:
    """Dispatch submit_concept to the active backend."""
    if _ACTIVE_BACKEND == "gists":
        return _handle_submit_concept_gists(inputs)
    return _handle_submit_concept_selfhosted(inputs)


def _handle_submit_concept_selfhosted(inputs: dict) -> str:
    """Submit a concept via the selfhosted Lore API."""
    name    = (inputs.get("name") or inputs.get("title") or "").strip()
    content = (inputs.get("content") or inputs.get("body") or "").strip()
    if not name:
        return json.dumps({"error": "name is required — provide a short descriptive title"})
    if not content or len(content) < 20:
        return json.dumps({"error": "content is required — describe the concept in detail (at least 20 chars)"})
    raw_type = inputs.get("type") or inputs.get("kind") or ""
    ctype = raw_type if raw_type in _VALID_CONCEPT_TYPES else "pattern"
    payload = {
        "name": name,
        "type": ctype,
        "content": content,
        "when_to_use": inputs.get("when_to_use", ""),
        "dont_use_when": inputs.get("dont_use_when"),
        "language": inputs.get("language"),
        "tags": inputs.get("tags", []),
        "author": "benchmark",
    }
    result = _lore_api("POST", "/v1/concepts", json=payload)
    if "concept_id" in result:
        _update_session([result["concept_id"]])
        if result["concept_id"] not in _RUN_SUBMITTED_IDS:
            _RUN_SUBMITTED_IDS.append(result["concept_id"])
    elif result.get("error") == "semantic_duplicate" and "existing_concept_id" in result:
        # Dedup: track the existing concept so wrapup can rate it.
        _update_session([result["existing_concept_id"]])
        # Reframe as success so the model doesn't retry — "error" label causes a loop.
        result = {
            "status": "already_exists",
            "concept_id": result["existing_concept_id"],
            "similarity": result.get("similarity"),
            "message": "Concept already in Lore. Do not retry — proceed to the next concept or call submit to finish.",
        }
    return json.dumps(result)


def _handle_submit_concept_gists(inputs: dict) -> str:
    """Submit a concept via the gists backend and track the created gist ID."""
    name    = (inputs.get("name") or inputs.get("title") or "").strip()
    content = (inputs.get("content") or inputs.get("body") or "").strip()
    if not name:
        return json.dumps({"error": "name is required — provide a short descriptive title"})
    if not content or len(content) < 20:
        return json.dumps({"error": "content is required — describe the concept in detail (at least 20 chars)"})
    raw_type = inputs.get("type") or inputs.get("kind") or ""
    ctype = raw_type if raw_type in _VALID_CONCEPT_TYPES else "pattern"

    from lore.mcp.backends import gists as gists_backend
    try:
        result = gists_backend.submit_concept(
            _get_gists_client(),
            name=name,
            type=ctype,
            content=content,
            when_to_use=inputs.get("when_to_use", ""),
            tags=inputs.get("tags", []),
            language=inputs.get("language"),
            dont_use_when=inputs.get("dont_use_when"),
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)})

    if "concept_id" in result:
        gist_id = result["concept_id"]
        _update_session([gist_id])
        if gist_id not in _RUN_SUBMITTED_IDS:
            _RUN_SUBMITTED_IDS.append(gist_id)
        # Track gist ID for series-end cleanup.
        if gist_id not in _SERIES_GIST_IDS:
            _SERIES_GIST_IDS.append(gist_id)
    return json.dumps(result)


def handle_rate_concept(inputs: dict) -> str:
    """Dispatch rate_concept to the active backend."""
    if _ACTIVE_BACKEND == "gists":
        return _handle_rate_concept_gists(inputs)
    return _handle_rate_concept_selfhosted(inputs)


def _handle_rate_concept_selfhosted(inputs: dict) -> str:
    """Rate a concept via the selfhosted Lore API."""
    concept_id = inputs.get("concept_id") or inputs.get("id")
    if not concept_id:
        return json.dumps({"error": "concept_id required"})
    outcome_raw = inputs.get("outcome") or inputs.get("score") or inputs.get("rating")
    if outcome_raw is None:
        return json.dumps({"error": "outcome required (1-5)"})
    outcome = int(outcome_raw)
    payload: dict = {"outcome": outcome, "session_id": "benchmark-run"}
    if inputs.get("hours_saved") is not None:
        payload["hours_saved"] = inputs["hours_saved"]
    if inputs.get("notes"):
        payload["notes"] = inputs["notes"]
    result = _lore_api("POST", f"/v1/concepts/{concept_id}/rate", json=payload)
    return json.dumps(result)


def _handle_rate_concept_gists(inputs: dict) -> str:
    """Rate a concept stored as a GitHub Gist.

    Gracefully handles the case where the gist has been deleted mid-run
    (e.g. by manual cleanup): logs the error and returns a no-op result.
    """
    concept_id = inputs.get("concept_id") or inputs.get("id")
    if not concept_id:
        return json.dumps({"error": "concept_id required"})
    outcome_raw = inputs.get("outcome") or inputs.get("score") or inputs.get("rating")
    if outcome_raw is None:
        return json.dumps({"error": "outcome required (1-5)"})
    outcome = int(outcome_raw)

    from lore.mcp.backends import gists as gists_backend
    from lore.mcp.backends.gists_client import GistNotFoundError
    try:
        result = gists_backend.rate_concept(
            _get_gists_client(),
            concept_id=concept_id,
            outcome=outcome,
            session_id="benchmark-run",
            hours_saved=inputs.get("hours_saved"),
            notes=inputs.get("notes"),
        )
        return json.dumps(result)
    except GistNotFoundError:
        print(f"  [gists-rate] gist {concept_id!r} not found (deleted mid-run) — skipping.", flush=True)
        return json.dumps({"status": "skipped", "reason": "gist_not_found", "concept_id": concept_id})
    except Exception as exc:
        print(f"  [gists-rate] rate_concept failed for {concept_id!r}: {exc}", flush=True)
        return json.dumps({"error": str(exc), "concept_id": concept_id})


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
        raw = inputs.get("path") or inputs.get("file_path") or inputs.get("filename")
        if not raw:
            return "[error] write_file requires a 'path' argument"
        p = Path(raw)
        if p.is_absolute():
            return f"[error] absolute paths not allowed: {raw}. Use a relative path under the working directory."
        path = workdir / raw
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(inputs["content"], encoding="utf-8")
        except PermissionError as e:
            return f"[error] permission denied writing {raw}: {e}"
        return f"Written {raw} ({len(inputs['content'])} chars)"

    if name == "read_file":
        raw = inputs.get("path") or inputs.get("file_path") or inputs.get("filename")
        if not raw:
            return "[error] read_file requires a 'path' argument"
        p = Path(raw).expanduser()
        if not p.is_absolute():
            if not workdir:
                return "[error] read_file: relative path requires a working directory"
            p = workdir / raw
        return p.read_text(encoding="utf-8") if p.exists() else f"[not found: {raw}]"

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

    if name == "finish_wrapup":
        return "Wrapup complete — concepts captured and rated."

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
    """Return the first balanced {...} whose first key is double-quoted (JSON).

    Skips TOML inline tables ({name = ...}) and Python dicts ({'key': ...}) by
    requiring the first non-whitespace character after { to be a double quote.
    Falls back to the first plain { if no double-quoted variant is found.
    """
    def _extract_from(start: int) -> str | None:
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

    first_plain = -1
    pos = 0
    while pos < len(text):
        brace_pos = text.find("{", pos)
        if brace_pos == -1:
            break
        if first_plain == -1:
            first_plain = brace_pos
        # Skip if first non-whitespace after { is not " (not a JSON object)
        after = brace_pos + 1
        while after < len(text) and text[after] in " \t\n\r":
            after += 1
        if after < len(text) and text[after] == '"':
            result = _extract_from(brace_pos)
            if result is not None:
                return result
        pos = brace_pos + 1

    # Fallback: extract from first {
    return _extract_from(first_plain) if first_plain != -1 else None


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
        client = anthropic.Anthropic(base_url=LOCAL_BASE_URL, api_key="ollama", timeout=900.0)
        model, max_tok = LOCAL_MODEL, LOCAL_MAX_TOKENS
    else:
        client = anthropic.Anthropic()
        model, max_tok = MODEL, 8192

    total_in = total_out = turns = 0
    submitted = False

    # Local thinking models (e.g. Qwen3.5 via Ollama) frequently end a turn right
    # after their <think> block with no tool call when tool_choice is left at the
    # default "auto" — forcing "any" eliminates that failure mode (~36% of turns
    # were lost to it in earlier runs). Cloud Claude doesn't need this.
    extra_kwargs = {"tool_choice": {"type": "any"}} if PROVIDER == "local" else {}

    while turns < max_turns:
        try:
            response = client.messages.create(
                model=model, max_tokens=max_tok,
                system=system, tools=tools, messages=messages,
                **extra_kwargs,
            )
        except Exception as exc:
            print(f"  {label}[API ERROR turn {turns+1}] {exc}", flush=True)
            break

        total_in  += response.usage.input_tokens
        total_out += response.usage.output_tokens
        turns += 1

        tool_names = [b.name for b in (response.content or []) if getattr(b, "type", None) == "tool_use"]
        tools_str = f" | tools={','.join(tool_names)}" if tool_names else ""
        print(
            f"  {label}turn {turns:02d}/{max_turns} | finish={response.stop_reason} "
            f"| in={response.usage.input_tokens} out={response.usage.output_tokens}{tools_str}",
            flush=True,
        )

        # Serialise content to plain dicts so messages stay JSON-serialisable.
        # Also harvest any thinking/CoT content for use in think→act retries.
        content_blocks: list[dict] = []
        _thinking_text: str = ""
        for b in (response.content or []):
            if b.type == "tool_use":
                content_blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
            elif b.type == "text":
                content_blocks.append({"type": "text", "text": b.text})
                # Capture thinking embedded as <think>…</think> when that's all the block contains
                _tm = re.search(r"<think>(.*?)</think>", b.text, re.DOTALL)
                if _tm and not b.text.replace(_tm.group(0), "").strip():
                    _thinking_text = _tm.group(1).strip()
            elif getattr(b, "type", None) == "thinking" and getattr(b, "thinking", None):
                _thinking_text = b.thinking

        if not content_blocks:
            # Ollama's serving layer (llama.cpp grammar-constrained tool calling)
            # frequently stops generating right after </think> with no tool call.
            # Confirmed not fixable from the client: tool_choice="any" does not
            # reliably force a call here, and assistant-message prefill continuation
            # is rejected outright by the server's tool-call grammar ("peg-native
            # format" 500 errors) once more than a trivial tool registry is in play.
            # The only working mitigation is re-prompting in a fresh user turn.
            if _thinking_text:
                # think→act: feed the reasoning conclusion back as the retry prompt
                conclusion = _thinking_text[-1500:].strip()
                retry_content = (
                    f"Your reasoning concluded:\n{conclusion}\n\n"
                    "Now output exactly one tool call to act on that reasoning."
                )
                print(f"  {label}[thinking→act retry on turn {turns}]", flush=True)
            else:
                retry_content = "You must call one of the available tools now. Output only a JSON tool call."
                print(f"  {label}[empty response on turn {turns} — retrying]", flush=True)
            messages.append({"role": "user", "content": retry_content})
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
            try:
                result = handle_tool(name, inputs, workdir)
            except Exception as _tool_err:
                result = f"[tool error] {_tool_err}"
            if name == "submit":
                if workdir is None or "✓ all tests passed" in result:
                    submitted = True
            if name == "finish_wrapup":
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




def run_wrapup_phase(run_num: int, verbose: bool, messages: list[dict]) -> tuple[int, int, int]:
    """Unified end-of-session wrapup: rate used concepts then capture new ones.

    Mirrors the lore:wrapup skill — one agent call with full session context,
    both rate_concept and submit_concept tools, ending with submit.
    Returns (input_tokens, output_tokens, turns_used).
    """
    try:
        session_ids: list[str] = json.loads(SESSION_FILE.read_text()) if SESSION_FILE.exists() else []
    except (json.JSONDecodeError, OSError):
        session_ids = []

    wrapup_system = build_system_wrapup()
    if PROVIDER == "local":
        wrapup_system = LOCAL_SYSTEM_PREFIX + wrapup_system

    # Inject the tail of the coding session so the agent has recollection context.
    tail = messages[-(WRAPUP_HISTORY_TURNS * 2):] if len(messages) > WRAPUP_HISTORY_TURNS * 2 else list(messages)

    submitted_ids: list[str] = list(_RUN_SUBMITTED_IDS)
    # session_ids contains searched IDs; exclude any that were also submitted
    # (they'll appear in the submitted list instead).
    searched_ids = [cid for cid in session_ids if cid not in submitted_ids]

    wrapup_prompt = "The coding session above is now complete. Follow the wrapup skill from step 1."

    id_section = ""
    if searched_ids:
        id_section += (
            "\n\nConcept IDs RETRIEVED from Lore during this session (rate these with rate_concept):\n"
            + "\n".join(f"  - {cid}" for cid in searched_ids)
        )
    if submitted_ids:
        id_section += (
            "\n\nConcept IDs SUBMITTED to Lore during this session (rate these with rate_concept):\n"
            + "\n".join(f"  - {cid}" for cid in submitted_ids)
        )
    if id_section:
        wrapup_prompt += id_section
        wrapup_prompt += (
            "\n\nCRITICAL: Only call rate_concept for the exact IDs listed above. "
            "Do NOT invent, guess, or slug-ify concept IDs. If an ID is not in the lists above, skip it."
        )
    else:
        wrapup_prompt += (
            "\n\nNo concepts were retrieved or submitted during this session. "
            "Skip Step 1 (no rate_concept calls needed). Proceed directly to Step 2 (reflection)."
        )

    wrapup_messages = tail + [{"role": "user", "content": wrapup_prompt}]

    label = "[wrapup] "
    n_concepts = len(searched_ids) + len(submitted_ids)
    print(f"\n  [wrapup] {n_concepts} concept(s) to rate — up to {MAX_TURNS_WRAPUP} turns "
          f"(session context: last {len(tail)} messages)...", flush=True)

    in_tok, out_tok, turns, _, _ = _run_agent_anthropic(
        wrapup_system, TOOLS_WRAPUP, wrapup_messages,
        workdir=None, max_turns=MAX_TURNS_WRAPUP, verbose=verbose,
        label=label, stop_on_submit=True,
    )

    SESSION_FILE.write_text("[]")
    total_concepts = len(_SERIES_GIST_IDS) if _ACTIVE_BACKEND == "gists" else _count_concepts()
    print(f"  [wrapup] done — {total_concepts} total concepts in DB "
          f"({turns} turns, {in_tok + out_tok:,} tokens) — session cleared.", flush=True)
    return in_tok, out_tok, turns

# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_tests(workdir: Path) -> tuple[bool, str]:
    # Auto-install so tests can find the `text2stl` entry point regardless of
    # whether the agent remembered to run `pip install -e .` themselves.
    install_header = ""
    if (workdir / "pyproject.toml").exists() or (workdir / "setup.py").exists():
        install = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", ".", "-q"],
            cwd=workdir, capture_output=True, text=True, timeout=120,
        )
        if install.returncode != 0:
            install_header = f"[pip install -e . failed]\n{install.stdout}{install.stderr}\n"
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_text2stl_cli.py", "-v", "--tb=short", "--timeout=60"],
            cwd=workdir, capture_output=True, text=True, timeout=600,
        )
        return result.returncode == 0, install_header + result.stdout + result.stderr
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return False, f"[test suite timed out after 600s]\n{install_header}{out}"

# ---------------------------------------------------------------------------
# Core step function — all runs share this logic
# ---------------------------------------------------------------------------

def step_run(
    run_num: int,
    verbose: bool,
    dry_run: bool,
    max_turns: int = MAX_TURNS,
    output_dir: Path | None = None,
    series_num: int = 1,
) -> dict | None:
    """Execute a single benchmark run.

    Args:
        run_num: 1-based run number within a series.
        verbose: Whether to print verbose tool call output.
        dry_run: If True, print header and return immediately without running.
        max_turns: Turn budget for the main coding loop.
        output_dir: Directory to write run*.md into. Defaults to RESULTS_DIR.
    """
    lore_active = run_num > 1

    if run_num == 1:
        _clear_db()

    concepts_in_db = len(_SERIES_GIST_IDS) if _ACTIVE_BACKEND == "gists" else _count_concepts()

    lore_label = f"Lore ON ({concepts_in_db} concepts)" if lore_active else "no Lore"
    model_name = LOCAL_MODEL if PROVIDER == "local" else MODEL
    print(f"\n{'='*60}\n  Run {run_num} — {lore_label}  |  {max_turns} turns  |  {model_name}\n{'='*60}")

    if dry_run:
        print("[dry-run] skipping.")
        return None

    global _CURRENT_SESSION_ID, _RUN_SUBMITTED_IDS
    _CURRENT_SESSION_ID = f"benchmark-s{series_num}-r{run_num}"
    _RUN_SUBMITTED_IDS = []

    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text("[]")
    concepts_before = concepts_in_db
    gists_before = len(_SERIES_GIST_IDS) if _ACTIVE_BACKEND == "gists" else 0

    system      = build_system_with_lore() if lore_active else build_system_no_lore()
    if PROVIDER == "local":
        system = LOCAL_SYSTEM_PREFIX + system
    tools       = TOOLS_WITH_LORE if lore_active else TOOLS_NO_LORE
    task_prompt = TASK_PROMPT_WITH_LORE if lore_active else TASK_PROMPT_NO_LORE

    workdir = Path(tempfile.mkdtemp(prefix=f"lore_stlgen_run{run_num}_"))
    _ALL_WORKDIRS.append(workdir)
    print(f"Working dir: {workdir}")
    (workdir / "tests").mkdir(exist_ok=True)
    shutil.copy(TEST_FILE,    workdir / "tests" / "test_text2stl_cli.py")
    shutil.copy(CONFTEST_FILE, workdir / "tests" / "conftest.py")

    start = datetime.now()
    in_tok, out_tok, turns, submitted, messages = run_agent(
        system, tools, task_prompt, workdir, max_turns, verbose,
        stop_on_submit=True,
    )
    elapsed = (datetime.now() - start).total_seconds()

    print(f"\nMain loop {'✓ submitted' if submitted else '✗ hit limit'}. Running tests...")
    passed, test_out = run_tests(workdir)

    # Unified wrapup: rate used concepts and capture new ones in one call with session context.
    w_in, w_out, w_turns = run_wrapup_phase(run_num, verbose, messages)
    in_tok  += w_in
    out_tok += w_out

    if _ACTIVE_BACKEND == "gists":
        concepts_captured = len(_SERIES_GIST_IDS) - gists_before
    else:
        concepts_captured = _count_concepts() - concepts_before

    result = {
        "run": run_num,
        "backend": _ACTIVE_BACKEND,
        "lore_active": lore_active,
        "concepts_available": concepts_in_db,
        "concepts_captured": concepts_captured,
        "turn_budget": max_turns,
        "turns_main": turns,
        "turns_wrapup": w_turns,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "total_tokens": in_tok + out_tok,
        "elapsed": elapsed,
        "task_submitted": submitted,
        "tests_passed": passed,
    }
    _write_run_md(result, test_out, output_dir=output_dir)
    _print_summary(result)
    return result


def _cleanup_all_workdirs() -> None:
    """Remove every per-run temp workdir accumulated so far in this invocation."""
    for workdir in _ALL_WORKDIRS:
        shutil.rmtree(workdir, ignore_errors=True)
    _ALL_WORKDIRS.clear()

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _count_concepts() -> int:
    """Return the number of concepts in the active backend.

    For the selfhosted backend this queries the /v1/metrics endpoint.
    For the gists backend, returning a meaningful count would require a
    GitHub search API call — return 0 instead (the field is informational only).
    """
    if _ACTIVE_BACKEND == "gists":
        return 0
    result = _lore_api("GET", "/v1/metrics")
    return result.get("concept_count", 0)


def _clear_db() -> None:
    """Reset concept storage at the start of a new series.

    For the selfhosted backend: drops all concepts, ratings, and Qdrant vectors
    via the admin API.

    For the gists backend: deletes ALL [agentlore-concept] gists owned by the
    authenticated user (not just those tracked in _SERIES_GIST_IDS), ensuring a
    clean slate even when restarting after a killed run.
    """
    if _ACTIVE_BACKEND == "gists":
        _cleanup_all_agentlore_gists()
        return
    result = _lore_api("DELETE", "/v1/admin/reset",
                       admin_token=os.environ.get("LORE_ADMIN_TOKEN", ""))
    if SESSION_FILE.exists():
        SESSION_FILE.write_text("[]")
    deleted = result.get("concepts_deleted", "?")
    print(f"  [reset] concept DB cleared — {deleted} concepts removed.")
    print("  [reset] Qdrant collection wiped — will recreate on first index.")


def _cleanup_all_agentlore_gists() -> None:
    """Delete ALL [agentlore-concept] gists owned by the authenticated user.

    Used at the start of Run 1 to ensure a clean slate, including gists left
    over from a previously killed benchmark run that were never tracked in
    _SERIES_GIST_IDS.
    """
    from lore.mcp.backends.gists_client import GistNotFoundError
    import requests as _req
    client = _get_gists_client()
    token = os.environ.get("LORE_GITHUB_TOKEN", "")
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    page, deleted, total = 1, 0, 0
    while True:
        resp = _req.get(
            "https://api.github.com/gists",
            params={"per_page": 100, "page": page},
            headers=headers, timeout=15,
        )
        gists = resp.json() if resp.ok else []
        if not gists:
            break
        for g in gists:
            if "[agentlore-concept]" in (g.get("description") or ""):
                total += 1
                try:
                    client.delete_gist(g["id"])
                    deleted += 1
                except GistNotFoundError:
                    pass
                except Exception as exc:
                    print(f"  [reset] failed to delete {g['id']}: {exc}", flush=True)
        page += 1
    _SERIES_GIST_IDS.clear()
    if total:
        print(f"  [reset] deleted {deleted}/{total} [agentlore-concept] gists.", flush=True)
    else:
        print("  [reset] no [agentlore-concept] gists to delete.", flush=True)
    # Flush Qdrant so stale vectors from deleted gists don't pollute search results.
    semantic_url = os.environ.get("LORE_SEMANTIC_URL", "").rstrip("/")
    if semantic_url:
        try:
            import urllib.request as _ur
            req = _ur.Request(f"{semantic_url}/admin/flush", method="POST",
                              headers={"Content-Type": "application/json"})
            with _ur.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
            print(f"  [reset] Qdrant flushed — {body}", flush=True)
        except Exception as exc:
            print(f"  [reset] Qdrant flush failed (non-fatal): {exc}", flush=True)


def _cleanup_series_gists() -> None:
    """Delete all gists tracked in ``_SERIES_GIST_IDS`` and clear the list.

    Failures for individual gists are logged but do not abort the cleanup loop.
    A gist that was already deleted (e.g. by manual cleanup) is handled
    gracefully via GistNotFoundError.
    """
    global _SERIES_GIST_IDS
    if not _SERIES_GIST_IDS:
        print("  [gists-cleanup] no gists to delete.", flush=True)
        return
    from lore.mcp.backends.gists_client import GistNotFoundError
    client = _get_gists_client()
    total = len(_SERIES_GIST_IDS)
    deleted = 0
    for gist_id in list(_SERIES_GIST_IDS):
        try:
            client.delete_gist(gist_id)
            deleted += 1
        except GistNotFoundError:
            print(f"  [gists-cleanup] {gist_id} already gone — skipping.", flush=True)
        except Exception as exc:
            print(f"  [gists-cleanup] failed to delete {gist_id}: {exc}", flush=True)
    _SERIES_GIST_IDS.clear()
    print(f"  [gists-cleanup] deleted {deleted}/{total} gists.", flush=True)


def _seed_concepts() -> None:
    """Inject hand-authored seed concepts from seed_concepts/ into the DB.

    Not called in the current benchmark design — seeding was removed so that
    Lore bootstraps purely from concepts captured organically in earlier runs.
    Kept for ad-hoc debugging (call manually before step_run if needed).
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


def _write_run_md(r: dict, test_out: str, output_dir: Path | None = None) -> None:
    """Write per-run markdown results file.

    Args:
        r: Run result dict.
        test_out: Raw pytest output string.
        output_dir: Directory to write into. Defaults to RESULTS_DIR.
    """
    out_dir = output_dir or RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    run_n = r["run"]
    lore = f"yes ({r['concepts_available']} concepts)" if r["lore_active"] else "no"
    backend = r.get("backend", "selfhosted")
    (out_dir / f"run{run_n}.md").write_text(
        f"# Benchmark — Run {run_n}\n\n"
        f"| Field | Value |\n|-------|-------|\n"
        f"| Date | {datetime.now().strftime('%Y-%m-%d %H:%M')} |\n"
        f"| Backend | {backend} |\n"
        f"| Model | {LOCAL_MODEL if PROVIDER == 'local' else MODEL} |\n"
        f"| Lore search active | {lore} |\n"
        f"| Web search active | yes |\n"
        f"| Turn budget | {r['turn_budget']} |\n"
        f"| Turns (main loop) | {r['turns_main']} |\n"
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
    print(f"  Results → {out_dir / f'run{run_n}.md'}")


def _print_summary(r: dict) -> None:
    sub = "✓" if r["task_submitted"] else "✗"
    tests = "PASS" if r["tests_passed"] else "FAIL"
    print(
        f"\nRun {r['run']}: turns={r['turns_main']}/{r['turn_budget']}  "
        f"tokens={r['total_tokens']:,}  tests={tests}  "
        f"submitted={sub}  concepts+={r['concepts_captured']}  "
        f"elapsed={r['elapsed']:.1f}s"
    )



def _write_comparison(results: list[dict], output_dir: Path | None = None) -> None:
    """Write the cross-run comparison markdown table.

    Args:
        results: List of run result dicts for a single series.
        output_dir: Directory to write comparison.md into. Defaults to RESULTS_DIR.
    """
    out_dir = output_dir or RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    n = max(r["run"] for r in results)
    run_cols = " | ".join(f"Run {i}" for i in range(1, n + 1))
    sep_cols  = " | ".join("-------" for _ in range(1, n + 1))
    header = (
        f"# Benchmark Comparison — {n} Runs, Same Task, Same Budget\n\n"
        f"*All runs: same hard task, {MAX_TURNS}-turn budget.\n"
        "What changes: Lore content (more each run) and concept ratings.*\n\n"
        f"| Metric | {run_cols} |\n"
        f"|--------|{sep_cols}|\n"
    )

    by_run = {r["run"]: r for r in results}
    run_range = range(1, n + 1)
    rows = [
        ("Lore concepts available",
            *[str(by_run[i]["concepts_available"]) if i in by_run else "—" for i in run_range]),
        ("Task submitted",
            *[("✓" if by_run[i]["task_submitted"] else "✗") if i in by_run else "—" for i in run_range]),
        ("Tests passed",
            *[("✅" if by_run[i]["tests_passed"] else "❌") if i in by_run else "—" for i in run_range]),
        ("Turns (main loop)",
            *[str(by_run[i]["turns_main"]) if i in by_run else "—" for i in run_range]),
        ("Total tokens",
            *[f"{by_run[i]['total_tokens']:,}" if i in by_run else "—" for i in run_range]),
        ("Concepts captured",
            *[str(by_run[i]["concepts_captured"]) if i in by_run else "—" for i in run_range]),
        ("Elapsed (s)",
            *[f"{by_run[i]['elapsed']:.0f}" if i in by_run else "—" for i in run_range]),
    ]

    table = header
    for label, *cells in rows:
        table += f"| {label} | {' | '.join(cells)} |\n"
    table += f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"

    (out_dir / "comparison.md").write_text(table, encoding="utf-8")
    print(f"\nComparison → {out_dir / 'comparison.md'}")


# ---------------------------------------------------------------------------
# Multi-series helpers
# ---------------------------------------------------------------------------

def _write_aggregate_json(series_id: int, series_results: list[dict], turn_budget: int) -> None:
    """Append a completed series to results/aggregate.json.

    Loads existing data if the file exists and appends the new series block.
    Top-level metadata (model, turn_budget, generated) is updated on each write.

    Args:
        series_id: 1-based series number.
        series_results: List of run result dicts for this series.
        turn_budget: The --max-turns value used for this run.
    """
    agg_path = RESULTS_DIR / "aggregate.json"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing data or start fresh
    if agg_path.exists():
        try:
            existing = json.loads(agg_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    else:
        existing = {}

    existing_series: list[dict] = existing.get("series", [])

    new_series = {
        "series_id": series_id,
        "runs": [
            {
                "run": r["run"],
                "backend": r.get("backend", "selfhosted"),
                "lore_active": r["lore_active"],
                "concepts_available": r["concepts_available"],
                "concepts_captured": r["concepts_captured"],
                "turn_budget": r["turn_budget"],
                "turns_main": r["turns_main"],
                "turns_wrapup": r["turns_wrapup"],
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
                "total_tokens": r["total_tokens"],
                "elapsed": round(r["elapsed"], 1),
                "task_submitted": r["task_submitted"],
                "tests_passed": r["tests_passed"],
            }
            for r in series_results
        ],
    }
    existing_series.append(new_series)

    model_name = LOCAL_MODEL if PROVIDER == "local" else MODEL
    output = {
        "model": model_name,
        "turn_budget": turn_budget,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "series": existing_series,
    }

    agg_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\nAggregate → {agg_path}")


def _print_series_summary(all_series: list[list[dict]]) -> None:
    """Print a cross-series summary table after all series complete.

    Args:
        all_series: List of series, each being a list of run result dicts.
    """
    n_series = len(all_series)
    # Determine run count from the first series that has data
    n_runs = max(len(s) for s in all_series) if all_series else 0
    if n_runs == 0:
        return

    print(f"\n{'='*65}")
    print(f"  Multi-Series Summary ({n_series} series x {n_runs} runs)")
    print(f"{'='*65}")
    print(f"{'Run':>4} | {'Pass rate':>9} | {'Avg turns (pass)':>16} | {'Avg tokens':>10} | {'Avg elapsed':>11}")
    print(f"{'-'*4}-+-{'-'*9}-+-{'-'*16}-+-{'-'*10}-+-{'-'*11}")

    for run_idx in range(1, n_runs + 1):
        # Collect results for this run number across all series
        run_results = [
            r
            for series in all_series
            for r in series
            if r["run"] == run_idx
        ]
        if not run_results:
            continue

        total = len(run_results)
        passed = [r for r in run_results if r["tests_passed"]]
        pass_rate = len(passed) / total * 100

        avg_turns_pass = (
            sum(r["turns_main"] for r in passed) / len(passed)
            if passed else None
        )
        avg_tokens = sum(r["total_tokens"] for r in run_results) / total
        avg_elapsed_m = sum(r["elapsed"] for r in run_results) / total / 60

        pass_str   = f"{pass_rate:.0f}%"
        turns_str  = f"{avg_turns_pass:.1f}" if avg_turns_pass is not None else "—"
        tokens_str = f"{avg_tokens:,.0f}"
        elapsed_str = f"{avg_elapsed_m:.1f}m"

        print(
            f"{run_idx:>4} | {pass_str:>9} | {turns_str:>16} | {tokens_str:>10} | {elapsed_str:>11}"
        )
    print()

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point for the Lore benchmark runner.

    Modes:
      --run N      Run a single numbered run (single-series, writes to results/).
      --all        Run all 10 runs in sequence (single-series, writes to results/).
      --series N   Run N complete 10-run series in sequence, each starting fresh.
                   Writes to results/series_NNN/ and appends to results/aggregate.json.
    """
    parser = argparse.ArgumentParser(
        description="Lore effectiveness benchmark — text2stl, 10 progressive runs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", type=int, choices=list(range(1, 11)), metavar="{1..10}",
                      help="Run a single numbered run")
    mode.add_argument("--all", action="store_true",
                      help="Run all 10 in sequence")
    mode.add_argument("--series", type=int, metavar="N",
                      help="Run N complete 10-run series in sequence (each series starts fresh)")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-turns", type=int, default=MAX_TURNS, metavar="N",
                        help=f"Turn budget for the main coding loop (default: {MAX_TURNS})")
    parser.add_argument("--start-series", type=int, default=1, metavar="N",
                        help="First series number (default: 1). Use to avoid overwriting existing series.")
    parser.add_argument("--backend", choices=["selfhosted", "gists"], default="selfhosted",
                        help="Backend to use for concept operations (default: selfhosted).")
    args = parser.parse_args()

    global _ACTIVE_BACKEND, _gists_client_instance
    _ACTIVE_BACKEND = args.backend
    _gists_client_instance = None  # reset so lazy init picks up correct env

    if args.series is not None:
        # Multi-series mode: run N complete 10-run series.
        # Each series gets its own results/series_NNN/ subdirectory.
        n_series = args.series
        start_series = args.start_series
        all_series_results: list[list[dict]] = []

        for series_num in range(start_series, start_series + n_series):
            series_dir = RESULTS_DIR / f"series_{series_num:03d}"
            print(f"\n{'#'*60}")
            print(f"  SERIES {series_num}/{start_series + n_series - 1}")
            print(f"  Output dir: {series_dir}")
            print(f"{'#'*60}")

            series_results: list[dict] = []
            for run_num in range(1, 11):
                try:
                    res = step_run(
                        run_num,
                        args.verbose,
                        args.dry_run,
                        max_turns=args.max_turns,
                        output_dir=series_dir,
                        series_num=series_num,
                    )
                except Exception as _run_exc:
                    import traceback as _tb
                    print(f"\n[FATAL] S{series_num}R{run_num} crashed: {_run_exc}", flush=True)
                    print(_tb.format_exc(), flush=True)
                    res = None
                if res:
                    series_results.append(res)

            if len(series_results) >= 2:
                _write_comparison(series_results, output_dir=series_dir)

            if series_results and not args.dry_run:
                _write_aggregate_json(series_num, series_results, args.max_turns)

            passes = sum(1 for r in series_results if r.get("tests_passed"))
            print(f"\n@@SERIES_COMPLETE@@:{series_num}/{n_series}:passes={passes}/{len(series_results)}", flush=True)

            all_series_results.append(series_results)

        if not args.dry_run:
            _print_series_summary(all_series_results)

        _cleanup_all_workdirs()
        if _ACTIVE_BACKEND == "gists":
            _cleanup_series_gists()

    else:
        # Single-series mode (--all or --run): unchanged behaviour.
        runs = list(range(1, 11)) if args.all else [args.run]
        results: list[dict] = []

        for run_num in runs:
            res = step_run(run_num, args.verbose, args.dry_run, max_turns=args.max_turns)
            if res:
                results.append(res)

        if len(results) >= 2:
            _write_comparison(results)

        _cleanup_all_workdirs()
        # Only wipe gists when the full series (--all) completes. A single
        # --run N invocation must leave gists in place so a subsequent
        # --run N+1 (separate process) can still search them.
        if _ACTIVE_BACKEND == "gists" and args.all:
            _cleanup_series_gists()


if __name__ == "__main__":
    main()
