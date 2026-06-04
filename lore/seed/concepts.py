"""Seed loader for the Lore knowledge graph.

Inserts 6 REST CLI blueprint concepts and 5 directed links via direct
SQLite and Qdrant calls — no HTTP/FastAPI server required.

Usage::

    python -m lore.seed.concepts

or from Python::

    from lore.seed.concepts import seed
    seed()

Idempotency: if the anchor concept ("REST CLI around a REST API") already
exists in SQLite the entire seed run is skipped silently.  Calling seed()
twice will not raise or duplicate data.

Qdrant connectivity is optional — if the client cannot reach a running
Qdrant instance, the embedding step is skipped and a warning is printed.
SQLite data is always inserted.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from typing import Optional

from lore.mcp.models import Concept, Link
from lore.selfhosted.db import init_db, insert_concept, insert_link

# ---------------------------------------------------------------------------
# Default paths / collection names — match the rest of the codebase
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = os.environ.get("LORE_DB_PATH", "lore.db")
_DEFAULT_COLLECTION = "concepts"
_QDRANT_HOST = os.environ.get("QDRANT_HOST", "localhost")
_QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))

# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

_CONCEPT_DEFS: list[dict] = [
    {
        "name": "REST CLI around a REST API",
        "type": "project",
        "language": "python",
        "when_to_use": "building a typed CLI client for an existing REST API",
        "dont_use_when": "the API has no OpenAPI spec; the CLI is one-off scripting",
        "tags": ["rest", "cli", "openapi", "project"],
        "content": (
            "Blueprint for building a typed CLI client that wraps a REST API. "
            "Use openapi-generator to produce the API client, structure commands "
            "in a hierarchy with shared auth context, implement pagination with "
            "cursor guards, and store credentials in the OS keychain. "
            "See linked concepts for each layer."
        ),
    },
    {
        "name": "openapi-generator setup",
        "type": "tool",
        "language": "python",
        "when_to_use": "generating a typed API client from an OpenAPI spec",
        "dont_use_when": "the API spec is incomplete or frequently changing",
        "tags": ["openapi", "codegen", "tool", "rest"],
        "content": (
            "Install openapi-generator-cli via npm or Docker. Configure output "
            "package name and base URL in a config YAML. Run generation, add the "
            "generated client directory to .gitignore (regenerate on spec change). "
            "Wire the generated client into CLI commands via dependency injection — "
            "pass the client instance through Click context (ctx.obj) or Typer state."
        ),
    },
    {
        "name": "CLI command hierarchy pattern",
        "type": "architecture",
        "language": "python",
        "when_to_use": "designing a multi-subcommand CLI with shared auth/config state",
        "dont_use_when": "the CLI has fewer than 3 commands and no shared state",
        "tags": ["cli", "architecture", "typer", "click"],
        "content": (
            "Use a root group (Click group or Typer app) to hold shared options: "
            "--env, --token, --output-format. Pass a context object down via ctx.obj. "
            "Each subcommand lives in a separate module under commands/. Keep command "
            "functions thin — argument parsing and output formatting only. Business "
            "logic belongs in a service layer that the command calls. This makes the "
            "service independently testable without invoking the CLI."
        ),
    },
    {
        "name": "REST CLI test strategy",
        "type": "testing",
        "language": "python",
        "when_to_use": "testing a CLI that wraps a REST API client",
        "dont_use_when": "the CLI logic is trivial pass-through with no transformation",
        "tags": ["testing", "cli", "rest", "mock", "vcr"],
        "content": (
            "Three layers: (1) Unit — mock the API client at the boundary using pytest "
            "fixtures; test CLI argument parsing and output formatting independently. "
            "(2) Integration — use the responses or VCR.py library to replay recorded "
            "HTTP fixtures; covers the happy path end-to-end without a live API. "
            "(3) Contract — run the OpenAPI spec against the live API in CI using "
            "schemathesis or dredd; catches API drift before it breaks users."
        ),
    },
    {
        "name": "Pagination cursor handling",
        "type": "pattern",
        "language": "python",
        "when_to_use": (
            "consuming a paginated REST API where responses include a "
            "next_cursor or next_page token"
        ),
        "dont_use_when": "the API uses offset/limit pagination with a known total count",
        "tags": ["pagination", "cursor", "rest", "pattern"],
        "content": (
            "Use a generator that yields pages: call the API, yield items from the "
            "page, check response for next_cursor, loop until None. Always add a "
            "--max-pages guard to prevent runaway loops on large datasets. For CLI "
            "use, store the last cursor in a session state file "
            "(~/.config/tool/state.json) to enable resumable fetches after interruption."
        ),
    },
    {
        "name": "Auth token storage in CLI tools",
        "type": "pattern",
        "language": "python",
        "when_to_use": (
            "storing and refreshing API tokens in a CLI tool used by "
            "developers on their local machine"
        ),
        "dont_use_when": (
            "the CLI is non-interactive or runs in CI — use environment variables instead"
        ),
        "tags": ["auth", "token", "keychain", "cli", "pattern"],
        "content": (
            "Use the keyring library to store tokens in the OS keychain keyed by "
            "service name + account. Fall back to ~/.config/<tool>/credentials with "
            "0600 permissions if keyring is unavailable. Never store tokens in "
            "environment variables for interactive sessions — they leak to subprocesses "
            "and shell history. Expose `<tool> auth login` and `<tool> auth logout` "
            "commands. On token expiry, catch 401 and prompt for re-auth rather than "
            "crashing."
        ),
    },
]

# Links all originate from "REST CLI around a REST API"
_LINK_DEFS: list[dict] = [
    {
        "from": "REST CLI around a REST API",
        "to": "openapi-generator setup",
        "rel": "uses",
        "label": "generates typed API client",
    },
    {
        "from": "REST CLI around a REST API",
        "to": "CLI command hierarchy pattern",
        "rel": "uses",
        "label": "structures command tree",
    },
    {
        "from": "REST CLI around a REST API",
        "to": "REST CLI test strategy",
        "rel": "tested_by",
        "label": "three-layer test approach",
    },
    {
        "from": "REST CLI around a REST API",
        "to": "Pagination cursor handling",
        "rel": "uses",
        "label": "handles paginated endpoints",
    },
    {
        "from": "REST CLI around a REST API",
        "to": "Auth token storage in CLI tools",
        "rel": "uses",
        "label": "credential storage",
    },
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_concept_id_by_name(conn: sqlite3.Connection, name: str) -> Optional[str]:
    """Return the concept_id for a concept with the given name, or None.

    Args:
        conn: An active SQLite connection.
        name: The exact concept name to look up.

    Returns:
        The concept_id string if found, otherwise None.
    """
    row = conn.execute(
        "SELECT concept_id FROM concepts WHERE name = ?", (name,)
    ).fetchone()
    return row["concept_id"] if row else None


def _make_concept_dataclass(defn: dict) -> Concept:
    """Build a :class:`~lore.mcp.models.Concept` from a seed definition dict.

    Args:
        defn: Dictionary with keys name, type, language, when_to_use,
            dont_use_when, tags, content.

    Returns:
        A :class:`Concept` with concept_id left empty so the DB layer
        generates a UUID on insert.
    """
    return Concept(
        concept_id="",
        name=defn["name"],
        type=defn["type"],
        language=defn["language"],
        when_to_use=defn["when_to_use"],
        dont_use_when=defn.get("dont_use_when"),
        tags=defn.get("tags", []),
        content=defn["content"],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class SeedResult:
    """Summary of a completed seed run.

    Attributes:
        concepts_inserted: Number of concept rows written to SQLite.
        links_inserted: Number of link rows written to SQLite.
        concepts_indexed: Number of concepts successfully indexed into Qdrant.
        skipped: True if the seed was skipped because data was already present.
    """

    concepts_inserted: int
    links_inserted: int
    concepts_indexed: int
    skipped: bool


def seed(
    db_path: str = _DEFAULT_DB_PATH,
    collection_name: str = _DEFAULT_COLLECTION,
    qdrant_host: str = _QDRANT_HOST,
    qdrant_port: int = _QDRANT_PORT,
    conn: Optional[sqlite3.Connection] = None,
    qdrant_client=None,
    embedding_model=None,
) -> SeedResult:
    """Insert the REST CLI blueprint concepts and links into SQLite (and optionally Qdrant).

    Idempotent: if the anchor concept "REST CLI around a REST API" already
    exists in SQLite the function returns immediately without any writes.

    Qdrant indexing is best-effort.  If ``qdrant_client`` is not supplied and
    a live Qdrant instance is not reachable, the SQLite inserts still proceed
    and a warning is printed to stdout.

    Args:
        db_path: Path to the SQLite database file.  Ignored when ``conn`` is
            provided.  Defaults to ``"lore.db"``.
        collection_name: Qdrant collection name.  Defaults to
            ``"lore_concepts"``.
        qdrant_host: Qdrant host.  Defaults to ``"localhost"``.
        qdrant_port: Qdrant port.  Defaults to 6333.
        conn: Optional pre-opened SQLite connection (used in tests to inject
            an in-memory DB).  If None, a new connection is opened at
            ``db_path``.
        qdrant_client: Optional pre-constructed
            :class:`~qdrant_client.QdrantClient` (used in tests for mocking).
            If None, the function attempts to connect to the running Qdrant
            instance; on failure, embedding is skipped.
        embedding_model: Optional pre-loaded
            :class:`~lore.mcp.embeddings.EmbeddingModel` (used in tests for
            mocking).  If None and a Qdrant client is available, a real model
            is loaded.

    Returns:
        A :class:`SeedResult` summarising what was done.
    """
    # -----------------------------------------------------------------------
    # 1. Establish DB connection
    # -----------------------------------------------------------------------
    own_conn = conn is None
    if own_conn:
        conn = init_db(db_path)

    try:
        # -------------------------------------------------------------------
        # 2. Idempotency check — skip if anchor concept already present
        # -------------------------------------------------------------------
        anchor_name = "REST CLI around a REST API"
        if _get_concept_id_by_name(conn, anchor_name) is not None:
            return SeedResult(
                concepts_inserted=0,
                links_inserted=0,
                concepts_indexed=0,
                skipped=True,
            )

        # -------------------------------------------------------------------
        # 3. Insert all concepts, collecting name -> id mapping
        # -------------------------------------------------------------------
        name_to_id: dict[str, str] = {}
        for defn in _CONCEPT_DEFS:
            concept = _make_concept_dataclass(defn)
            cid = insert_concept(conn, concept)
            name_to_id[defn["name"]] = cid

        concepts_inserted = len(name_to_id)

        # -------------------------------------------------------------------
        # 4. Insert links using the id map
        # -------------------------------------------------------------------
        links_inserted = 0
        for link_def in _LINK_DEFS:
            from_id = name_to_id.get(link_def["from"])
            to_id = name_to_id.get(link_def["to"])
            if from_id is None or to_id is None:
                # Defensive: skip any link whose endpoints weren't inserted
                continue
            link = Link(
                link_id="",
                from_id=from_id,
                to_id=to_id,
                rel=link_def["rel"],
                label=link_def.get("label"),
            )
            insert_link(conn, link)
            links_inserted += 1

        # -------------------------------------------------------------------
        # 5. Qdrant indexing (best-effort)
        # -------------------------------------------------------------------
        concepts_indexed = 0
        client = qdrant_client
        model = embedding_model

        if client is None:
            try:
                from qdrant_client import QdrantClient
                client = QdrantClient(host=qdrant_host, port=qdrant_port, timeout=5)
                # Probe connectivity with a lightweight call
                client.get_collections()
            except Exception as exc:
                print(
                    f"[lore.seed] Qdrant not reachable ({exc}); "
                    "skipping vector indexing. SQLite data is intact."
                )
                client = None

        if client is not None and model is None:
            try:
                from lore.mcp.embeddings import EmbeddingModel
                model = EmbeddingModel()
            except Exception as exc:
                print(
                    f"[lore.seed] Could not load EmbeddingModel ({exc}); "
                    "skipping vector indexing."
                )
                model = None

        if client is not None and model is not None:
            from lore.selfhosted.vector_store import init_qdrant_collection
            from lore.selfhosted.indexer import index_concept as do_index
            from lore.selfhosted.db import get_concept

            init_qdrant_collection(client, collection_name)

            for name, cid in name_to_id.items():
                concept_obj = get_concept(conn, cid)
                if concept_obj is None:
                    continue
                try:
                    do_index(conn, client, concept_obj, model, collection_name=collection_name)
                    concepts_indexed += 1
                except Exception as exc:
                    print(f"[lore.seed] Failed to index '{name}': {exc}")

        return SeedResult(
            concepts_inserted=concepts_inserted,
            links_inserted=links_inserted,
            concepts_indexed=concepts_indexed,
            skipped=False,
        )

    finally:
        if own_conn:
            conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    result = seed()
    if result.skipped:
        print("[lore.seed] Seed data already present — nothing to do.")
    else:
        print(
            f"[lore.seed] Done. "
            f"concepts={result.concepts_inserted}, "
            f"links={result.links_inserted}, "
            f"indexed={result.concepts_indexed}"
        )
