"""FastMCP server for the Lore knowledge graph (LORE-005).

Routes all MCP tool calls to the configured backend via :class:`BackendRouter`.
The backend is selected by the ``LORE_BACKEND`` environment variable.

Entry point::

    python -m lore.mcp.server

Environment variables
---------------------
LORE_BACKEND
    Backend selector.  Supported values: ``selfhosted``, ``gists``.
    Default: ``selfhosted``.

LORE_READ_ONLY
    ``1`` = read-only demo mode: search/get use the bundled curated concepts
    (or the semantic server), and submit/link/rate return a ``read_only`` error.

LORE_TOKEN_FROM_GH
    ``1`` = resolve the GitHub token at runtime via ``gh auth token`` when
    ``LORE_GITHUB_TOKEN`` is unset.

LORE_SELFHOSTED_URL
    Base URL for the selfhosted FastAPI service.
    Default: ``http://localhost:8765``.

Tool catalogue
--------------
- ``search_concepts``   — semantic search + linked graph in one call
- ``get_concept``       — fetch a single concept by ID
- ``submit_concept``    — add a new concept (content-scanned before write)
- ``link_concepts``     — create a directed edge between two concepts
- ``rate_concept``      — record an outcome rating for a concept
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastmcp import FastMCP

from lore.mcp.router import BackendRouter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_BACKEND = os.environ.get("LORE_BACKEND", "selfhosted")
_SELFHOSTED_URL = os.environ.get("LORE_SELFHOSTED_URL", "http://localhost:8765").rstrip("/")

# ---------------------------------------------------------------------------
# Router instance
# ---------------------------------------------------------------------------

_router = BackendRouter(backend=_BACKEND, selfhosted_url=_SELFHOSTED_URL)

# ---------------------------------------------------------------------------
# FastMCP server instance
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="lore",
    instructions=(
        "Lore is a typed, linked knowledge graph for AI coding agents. "
        "Use search_concepts to find reusable patterns and tools. "
        "Use submit_concept to contribute new knowledge. "
        "Use rate_concept to record whether a concept helped."
    ),
)


# ---------------------------------------------------------------------------
# Tool: search_concepts
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Search the Lore knowledge graph for concepts matching a problem description. "
        "Returns ranked results, each including the full concept record plus its "
        "directly linked concepts — no second call needed."
    )
)
def search_concepts(
    problem: str,
    type: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 3,
    min_rating: float = 2.0,
    session_id: Optional[str] = None,
    environment: Optional[dict] = None,
    project_dir: Optional[str] = None,
    include_incompatible: bool = True,
) -> dict:
    """Search for concepts semantically similar to a problem description.

    Makes a single call to the configured backend which embeds the problem
    text, queries the store, and attaches all linked concepts inline.

    Args:
        problem: Natural language description of what you are building or
            trying to solve.
        type: Optional filter by concept type.  One of: ``project``,
            ``pattern``, ``tool``, ``testing``, ``architecture``.
        language: Optional filter by programming language (e.g. ``"python"``).
        limit: Maximum number of results to return.  Default 3.
        min_rating: Exclude concepts whose ``avg_rating`` is below this
            threshold.  Unrated concepts (``avg_rating`` is ``None``) are also
            excluded when ``min_rating > 0``.  Set to ``0`` to disable
            filtering.  Default 2.0.
        session_id: Optional session identifier.  When provided, usage is
            logged in the backend for analytics.
        environment: Optional target environment to check compatibility
            against: ``{"language": "python", "runtime_version": "3.12.1",
            "libraries": {"fastapi": "0.110.0"}, "platform": "linux"}`` (all
            keys optional; library values are concrete versions).
        project_dir: Optional project directory; its manifests/lockfiles are
            read to detect the environment.  Ignored when ``environment`` is given.
            If neither is given, the MCP process's current directory is
            inspected (manifests/lockfiles only; disable with
            ``LORE_COMPAT_AUTODETECT=0``).  Nothing detected -> ``unknown``.
        include_incompatible: Default ``True``: incompatible results are kept,
            flagged and placed last.  ``False`` drops them.

    Returns:
        A dict with a ``results`` key containing a list of concept records.
        Each record has ``concept_id``, ``name``, ``type``, ``when_to_use``,
        ``content``, ``avg_rating``, ``usage_count``, ``time_saved_avg_hours``,
        ``links`` (linked concept summaries, each with its own
        ``compatibility_check``) and ``compatibility_check``
        (``{"status": "compatible"|"incompatible"|"unknown", "reason": str}``).
        Results are ordered compatible > unknown > incompatible; rating/relevance
        only orders within a status band, so a highly rated incompatible
        concept is never ranked above a compatible or unknown one.
    """
    return _router.search_concepts(
        problem=problem,
        type=type,
        language=language,
        limit=limit,
        min_rating=min_rating,
        session_id=session_id,
        environment=environment,
        project_dir=project_dir,
        include_incompatible=include_incompatible,
    )


# ---------------------------------------------------------------------------
# Tool: get_concept
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Retrieve a single concept from the Lore knowledge graph by its ID. "
        "Returns the full concept record including all linked concepts in both directions."
    )
)
def get_concept(concept_id: str) -> dict:
    """Fetch a concept by its ID and return it with all links.

    Args:
        concept_id: The identifier of the concept to retrieve (UUID for
            selfhosted, gist id for gists backend).

    Returns:
        The full concept record as a dict, including a ``links`` list.

    Raises:
        RuntimeError: If the concept is not found (HTTP 404) or the backend
            returns an error.
    """
    return _router.get_concept(concept_id=concept_id)


# ---------------------------------------------------------------------------
# Tool: submit_concept
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Submit a new concept to the Lore knowledge graph. "
        "Content is scanned for credentials and internal URLs before any write. "
        "Rejected submissions include a structured error identifying the offending field."
    )
)
def submit_concept(
    name: str,
    type: str,
    content: str,
    when_to_use: str,
    tags: list[str],
    language: Optional[str] = None,
    dont_use_when: Optional[str] = None,
    source_url: Optional[str] = None,
    links: Optional[list[dict]] = None,
    reproducer: Optional[str] = None,
    compatibility: Optional[dict] = None,
) -> dict:
    """Submit a new concept to the knowledge graph after mandatory content scanning.

    The content scan runs locally before sending to the backend, providing an
    early rejection path.  The backend also runs the scan independently so
    no bypass is possible.

    Scanned fields: ``name``, ``content``, ``when_to_use``, ``dont_use_when``.

    Args:
        name: Short human-readable name for the concept.
        type: Concept type.  One of: ``project``, ``pattern``, ``tool``,
            ``testing``, ``architecture``.
        content: Markdown body describing the concept.
        when_to_use: Natural-language description of ideal use context.
        tags: List of tag strings (e.g. ``["sqlite", "concurrency"]``).
        language: Programming language context.  Optional.
        dont_use_when: Known anti-cases / counter-indications.  Optional.
        source_url: Origin URL (GitHub, docs page, etc.).  Optional.
        links: Optional list of initial links.  Each entry must be a dict with
            keys ``to_id`` (str), ``rel`` (str), and optionally ``label``
            (str).  Valid ``rel`` values: ``uses``, ``tested_by``, ``extends``,
            ``alternative_to``, ``requires``.
        reproducer: Minimal reproducer text, or the exact string
            ``"none_available"`` if the author states none exists.  Omit if
            unknown (stored as ``unknown``).  Stored and displayed only; never
            executed.  Optional.
        compatibility: Environment constraints, all keys optional:
            ``language`` (str, e.g. ``"python"``), ``runtime_version``
            (PEP 440 specifier, e.g. ``">=3.11,<4"``), ``libraries`` (list of
            ``{"name": str, "specifier": str}`` or a name->specifier mapping),
            ``platforms`` (list of OS names, e.g. ``["linux", "macos"]``),
            ``assumptions`` (list of free-text strings).  Missing/partial
            metadata is stored as ``unknown`` — never as supported.  Optional.

    Returns:
        On success (HTTP 201): a dict with ``concept_id`` and ``name``.
        On semantic duplicate (HTTP 409): a dict with ``error``,
        ``existing_concept_id``, and ``similarity`` — callers should track
        ``existing_concept_id`` for end-of-session rating.

    Raises:
        ValueError: If the content scan detects credentials, internal URLs,
            or custom blocklist patterns, or if ``reproducer`` /
            ``compatibility`` is invalid (e.g. an unparsable version
            specifier such as ``">=abc"``).
        RuntimeError: If the backend returns an unexpected error.
    """
    from lore.core.compat import normalize_concept_metadata
    from lore.core.scanner import scan_content
    from lore.mcp.backends.seed import read_only_enabled, read_only_error

    if read_only_enabled():
        return read_only_error("submit_concept")

    # Local content scan before any backend call — server-layer responsibility.
    scan_fields: dict[str, str | None] = {
        "name": name,
        "content": content,
        "when_to_use": when_to_use,
        "dont_use_when": dont_use_when,
    }
    violations = scan_content({k: v for k, v in scan_fields.items() if v is not None})
    if violations:
        raise ValueError(
            f"Content scan rejected submission — {len(violations)} violation(s) detected. "
            f"Violations: {violations}"
        )

    # Validate metadata locally (same function the backends use) before any call.
    normalize_concept_metadata(reproducer, compatibility)

    return _router.submit_concept(
        name=name,
        type=type,
        content=content,
        when_to_use=when_to_use,
        tags=tags,
        language=language,
        dont_use_when=dont_use_when,
        source_url=source_url,
        links=links,
        reproducer=reproducer,
        compatibility=compatibility,
    )


# ---------------------------------------------------------------------------
# Tool: link_concepts
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Create a directed, typed link between two existing concepts in Lore. "
        "Valid relationship types: uses, tested_by, extends, alternative_to, requires."
    )
)
def link_concepts(
    from_id: str,
    to_id: str,
    rel: str,
    label: str,
) -> dict:
    """Create a directed edge between two concepts.

    Args:
        from_id: Identifier of the source concept.
        to_id: Identifier of the target concept.
        rel: Relationship type.  Must be one of: ``uses``, ``tested_by``,
            ``extends``, ``alternative_to``, ``requires``.
        label: Human-readable description of the relationship.

    Returns:
        A dict with a ``link_id`` key confirming the created link.

    Raises:
        RuntimeError: If either concept does not exist (HTTP 404) or the
            relationship type is invalid (HTTP 422).
    """
    return _router.link_concepts(from_id=from_id, to_id=to_id, rel=rel, label=label)


# ---------------------------------------------------------------------------
# Tool: rate_concept
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Record an outcome rating for a concept after using it. "
        "hours_saved is optional but strongly encouraged — it is the primary signal "
        "in the Lore rating system."
    )
)
def rate_concept(
    concept_id: str,
    outcome: int,
    session_id: str,
    hours_saved: Optional[float] = None,
    notes: Optional[str] = None,
) -> dict:
    """Rate a concept and return updated aggregate statistics.

    Args:
        concept_id: Identifier of the concept to rate.
        outcome: Integer score 1–5.  5 = extremely helpful, 1 = not helpful.
        session_id: The current agent session identifier.
        hours_saved: Estimated hours saved versus solving from scratch.
            This is the strongest signal in the rating system — include it
            whenever possible.
        notes: Free-text notes explaining the outcome.  Optional.

    Returns:
        A dict with ``avg_rating`` (float) and ``time_saved_avg_hours``
        (float or null) reflecting the updated aggregates.

    Raises:
        RuntimeError: If the concept does not exist (HTTP 404) or the
            outcome value is out of range (HTTP 422).
    """
    return _router.rate_concept(
        concept_id=concept_id,
        outcome=outcome,
        session_id=session_id,
        hours_saved=hours_saved,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    """Entry point: ``init`` runs one-command setup; otherwise start the MCP server."""
    import sys

    args = sys.argv[1:] if argv is None else argv
    if args and args[0] == "init":
        from lore.setup.init import run_init

        sys.exit(run_init(args[1:]))
    mcp.run()


if __name__ == "__main__":
    main()
