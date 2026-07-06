"""SQLite persistence layer for the Lore self-hosted backend.

All connections returned from :func:`init_db` have WAL mode and foreign key
enforcement enabled.  Callers should keep connections open for the lifetime of
a request (or test) and close them when done.

IDs are generated with :func:`uuid.uuid4` and formatted as lowercase
hyphenated strings.  Timestamps are ISO-8601 UTC strings produced by
:func:`datetime.datetime.now` with :attr:`datetime.timezone.utc`.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lore.mcp.models import Concept, Link, Rating


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _schema_path() -> Path:
    """Return the absolute path to schema.sql."""
    return Path(__file__).parent / "schema.sql"


def _utcnow() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    """Generate a new UUID4 string."""
    return str(uuid.uuid4())


def _concept_from_row(row: sqlite3.Row) -> Concept:
    """Convert a sqlite3.Row (from the concepts table) into a :class:`Concept`."""
    tags_raw = row["tags"]
    tags: list[str] = json.loads(tags_raw) if tags_raw else []
    return Concept(
        concept_id=row["concept_id"],
        name=row["name"],
        type=row["type"],
        content=row["content"],
        language=row["language"],
        when_to_use=row["when_to_use"],
        dont_use_when=row["dont_use_when"],
        tags=tags,
        source_url=row["source_url"],
        author=row["author"],
        avg_rating=row["avg_rating"] or 0.0,
        usage_count=row["usage_count"] or 0,
        time_saved_avg_hours=row["time_saved_avg_hours"],
        created_at=row["created_at"] or "",
        embedding=row["embedding"],
    )


def _link_from_row(row: sqlite3.Row) -> Link:
    """Convert a sqlite3.Row (from the links table) into a :class:`Link`."""
    return Link(
        link_id=row["link_id"],
        from_id=row["from_id"],
        to_id=row["to_id"],
        rel=row["rel"],
        label=row["label"],
    )


def _rating_from_row(row: sqlite3.Row) -> Rating:
    """Convert a sqlite3.Row (from the ratings table) into a :class:`Rating`."""
    return Rating(
        rating_id=row["rating_id"],
        concept_id=row["concept_id"],
        session_id=row["session_id"],
        outcome=row["outcome"],
        hours_saved=row["hours_saved"],
        notes=row["notes"],
        rated_at=row["rated_at"] or "",
    )


# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------

def init_db(db_path: str) -> sqlite3.Connection:
    """Open (or create) a SQLite database and apply the Lore schema.

    This function is idempotent — calling it on an existing database is safe;
    all ``CREATE TABLE IF NOT EXISTS`` guards prevent duplicate table creation.

    WAL journal mode and foreign key enforcement are enabled on every
    connection regardless of whether the schema was already present.

    Args:
        db_path: Filesystem path to the SQLite file, or ``":memory:"`` for an
            in-memory database (useful in tests).

    Returns:
        An open :class:`sqlite3.Connection` with ``row_factory`` set to
        :data:`sqlite3.Row` for column-name access.
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Enable WAL mode for concurrent read performance and crash safety.
    conn.execute("PRAGMA journal_mode = WAL")
    # Enforce FK constraints — SQLite disables them by default.
    conn.execute("PRAGMA foreign_keys = ON")

    schema_sql = _schema_path().read_text()
    conn.executescript(schema_sql)
    conn.commit()

    return conn


# ---------------------------------------------------------------------------
# Concept CRUD
# ---------------------------------------------------------------------------

def insert_concept(conn: sqlite3.Connection, concept: Concept) -> str:
    """Insert a new concept row and return its ``concept_id``.

    The ``concept.concept_id`` is used as-is if it is already set; otherwise a
    new UUID is generated.  ``created_at`` is set to the current UTC time if
    empty.

    Args:
        conn: An active SQLite connection (from :func:`init_db`).
        concept: The :class:`Concept` to persist.  ``tags`` is serialized to a
            JSON text string.

    Returns:
        The ``concept_id`` string that was written to the database.
    """
    concept_id = concept.concept_id or _new_id()
    created_at = concept.created_at or _utcnow()
    tags_json = json.dumps(concept.tags) if concept.tags is not None else "[]"

    conn.execute(
        """
        INSERT INTO concepts (
            concept_id, name, type, content, language, when_to_use,
            dont_use_when, tags, source_url, author, avg_rating,
            usage_count, time_saved_avg_hours, created_at, embedding
        ) VALUES (
            :concept_id, :name, :type, :content, :language, :when_to_use,
            :dont_use_when, :tags, :source_url, :author, :avg_rating,
            :usage_count, :time_saved_avg_hours, :created_at, :embedding
        )
        """,
        {
            "concept_id": concept_id,
            "name": concept.name,
            "type": concept.type,
            "content": concept.content,
            "language": concept.language,
            "when_to_use": concept.when_to_use,
            "dont_use_when": concept.dont_use_when,
            "tags": tags_json,
            "source_url": concept.source_url,
            "author": concept.author,
            "avg_rating": concept.avg_rating,
            "usage_count": concept.usage_count,
            "time_saved_avg_hours": concept.time_saved_avg_hours,
            "created_at": created_at,
            "embedding": concept.embedding,
        },
    )
    conn.commit()
    return concept_id


def get_concept(conn: sqlite3.Connection, concept_id: str) -> Optional[Concept]:
    """Fetch a single concept by its primary key.

    Args:
        conn: An active SQLite connection.
        concept_id: The UUID string to look up.

    Returns:
        A :class:`Concept` dataclass if found, otherwise ``None``.
    """
    row = conn.execute(
        "SELECT * FROM concepts WHERE concept_id = ?", (concept_id,)
    ).fetchone()
    if row is None:
        return None
    return _concept_from_row(row)


def search_concepts_by_ids(
    conn: sqlite3.Connection, ids: list[str]
) -> list[Concept]:
    """Fetch multiple concepts by their IDs in a single query.

    Typically called after Qdrant returns a ranked list of ``concept_id``
    values.  The returned list preserves the order of ``ids``.

    Args:
        conn: An active SQLite connection.
        ids: List of ``concept_id`` strings to fetch.

    Returns:
        List of :class:`Concept` objects for IDs that exist in the database.
        Missing IDs are silently omitted.
    """
    if not ids:
        return []

    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT * FROM concepts WHERE concept_id IN ({placeholders})", ids
    ).fetchall()

    # Preserve the caller-supplied ordering (Qdrant relevance order).
    row_by_id = {r["concept_id"]: r for r in rows}
    return [_concept_from_row(row_by_id[cid]) for cid in ids if cid in row_by_id]


def update_concept_stats(
    conn: sqlite3.Connection,
    concept_id: str,
    avg_rating: float,
    usage_count: int,
    time_saved_avg_hours: Optional[float],
) -> None:
    """Overwrite the rolling aggregate fields on a concept.

    Called by :func:`insert_rating` after recomputing averages from the
    ratings table.  Also callable directly by usage-tracking code.

    Args:
        conn: An active SQLite connection.
        concept_id: The concept to update.
        avg_rating: New rolling average of ``outcome`` values.
        usage_count: New total usage count.
        time_saved_avg_hours: New rolling average of ``hours_saved`` values,
            or ``None`` if no rater has ever provided a value.
    """
    conn.execute(
        """
        UPDATE concepts
        SET avg_rating = ?, usage_count = ?, time_saved_avg_hours = ?
        WHERE concept_id = ?
        """,
        (avg_rating, usage_count, time_saved_avg_hours, concept_id),
    )
    conn.commit()


def update_embedding(conn: sqlite3.Connection, concept_id: str, embedding: bytes) -> None:
    """Update the embedding BLOB for an existing concept.

    Called by the indexer after computing a vector so that the raw float32
    bytes are persisted alongside the Qdrant entry.  The concept must already
    exist in the database (i.e. :func:`insert_concept` was already called).

    Args:
        conn: An active SQLite connection (from :func:`init_db`).
        concept_id: Primary key of the concept to update.
        embedding: Raw float32 bytes produced by the embedding pipeline.
    """
    conn.execute(
        "UPDATE concepts SET embedding = ? WHERE concept_id = ?",
        (embedding, concept_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Link CRUD
# ---------------------------------------------------------------------------

def insert_link(conn: sqlite3.Connection, link: Link) -> str:
    """Insert a directed link between two concepts and return its ``link_id``.

    Args:
        conn: An active SQLite connection.
        link: The :class:`Link` to persist.  ``link.link_id`` is used if set;
            otherwise a new UUID is generated.

    Returns:
        The ``link_id`` string written to the database.
    """
    link_id = link.link_id or _new_id()

    conn.execute(
        """
        INSERT INTO links (link_id, from_id, to_id, rel, label)
        VALUES (:link_id, :from_id, :to_id, :rel, :label)
        """,
        {
            "link_id": link_id,
            "from_id": link.from_id,
            "to_id": link.to_id,
            "rel": link.rel,
            "label": link.label,
        },
    )
    conn.commit()
    return link_id


def get_links_for_concept(
    conn: sqlite3.Connection, concept_id: str
) -> list[Link]:
    """Return all links where the concept appears as either source or target.

    Bidirectional fetch is intentional: the graph is undirected from a
    retrieval perspective — if concept A ``uses`` concept B, you want that
    edge visible when retrieving either A or B.

    Args:
        conn: An active SQLite connection.
        concept_id: The concept whose links to retrieve.

    Returns:
        List of :class:`Link` objects for all edges touching ``concept_id``.
    """
    rows = conn.execute(
        "SELECT * FROM links WHERE from_id = ? OR to_id = ?",
        (concept_id, concept_id),
    ).fetchall()
    return [_link_from_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Rating CRUD
# ---------------------------------------------------------------------------

def insert_rating(conn: sqlite3.Connection, rating: Rating) -> str:
    """Insert a rating and recompute the parent concept's aggregate stats.

    The aggregation query recalculates ``avg_rating`` (mean of all ``outcome``
    values) and ``time_saved_avg_hours`` (mean of non-NULL ``hours_saved``
    values) across *all* ratings for the concept.  The new values are written
    back via :func:`update_concept_stats` in the same transaction.

    Args:
        conn: An active SQLite connection.
        rating: The :class:`Rating` to persist.

    Returns:
        The ``rating_id`` string written to the database.

    Raises:
        sqlite3.IntegrityError: If ``rating.concept_id`` does not reference an
            existing concept (FK violation).
    """
    rating_id = rating.rating_id or _new_id()
    rated_at = rating.rated_at or _utcnow()

    conn.execute(
        """
        INSERT INTO ratings (rating_id, concept_id, session_id, outcome,
                             hours_saved, notes, rated_at)
        VALUES (:rating_id, :concept_id, :session_id, :outcome,
                :hours_saved, :notes, :rated_at)
        """,
        {
            "rating_id": rating_id,
            "concept_id": rating.concept_id,
            "session_id": rating.session_id,
            "outcome": rating.outcome,
            "hours_saved": rating.hours_saved,
            "notes": rating.notes,
            "rated_at": rated_at,
        },
    )

    # Recompute aggregates from all ratings for this concept.
    agg_row = conn.execute(
        """
        SELECT
            AVG(CAST(outcome AS REAL))       AS avg_outcome,
            AVG(hours_saved)                 AS avg_hours,
            COUNT(*)                         AS total_ratings
        FROM ratings
        WHERE concept_id = ?
        """,
        (rating.concept_id,),
    ).fetchone()

    avg_rating = agg_row["avg_outcome"] or 0.0
    time_saved_avg = agg_row["avg_hours"]  # None if no rater provided hours_saved

    # Fetch current usage_count so we don't zero it out.
    usage_row = conn.execute(
        "SELECT usage_count FROM concepts WHERE concept_id = ?",
        (rating.concept_id,),
    ).fetchone()
    usage_count = usage_row["usage_count"] if usage_row else 0

    update_concept_stats(conn, rating.concept_id, avg_rating, usage_count, time_saved_avg)
    # update_concept_stats already commits; no double-commit needed.
    return rating_id


# ---------------------------------------------------------------------------
# Session usage logging
# ---------------------------------------------------------------------------

def log_session_usage(
    conn: sqlite3.Connection, session_id: str, concept_id: str
) -> None:
    """Record that a session accessed a concept.

    Inserts a row into ``session_usage``.  Does not enforce uniqueness — the
    same (session_id, concept_id) pair may appear multiple times if the
    concept was retrieved in multiple calls within the same session.

    Args:
        conn: An active SQLite connection.
        session_id: The calling agent's session identifier.
        concept_id: The concept that was accessed.
    """
    conn.execute(
        "INSERT INTO session_usage (session_id, concept_id, used_at) VALUES (?, ?, ?)",
        (session_id, concept_id, _utcnow()),
    )
    conn.execute(
        "UPDATE concepts SET usage_count = usage_count + 1 WHERE concept_id = ?",
        (concept_id,),
    )
    conn.commit()
