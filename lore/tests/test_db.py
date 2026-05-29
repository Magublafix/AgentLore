"""Unit tests for lore.selfhosted.db.

All tests use an in-memory SQLite database (:memory:) so they are fast,
isolated, and leave no filesystem artefacts.
"""

from __future__ import annotations

import sqlite3

import pytest

from lore.mcp.models import Concept, Link, Rating
from lore.selfhosted.db import (
    get_concept,
    get_links_for_concept,
    init_db,
    insert_concept,
    insert_link,
    insert_rating,
    log_session_usage,
    search_concepts_by_ids,
    update_concept_stats,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def conn() -> sqlite3.Connection:
    """Return an initialised in-memory SQLite connection."""
    return init_db(":memory:")


def _make_concept(**kwargs) -> Concept:
    """Create a minimal valid Concept with sensible defaults."""
    defaults = dict(
        concept_id="",
        name="Test concept",
        type="pattern",
        content="## Description\nA test concept.",
        language="python",
        when_to_use="When writing tests for SQLite-backed services.",
        dont_use_when=None,
        tags=["testing", "sqlite"],
        source_url=None,
        author="test-agent",
        avg_rating=0.0,
        usage_count=0,
        time_saved_avg_hours=None,
        created_at="",
        embedding=None,
    )
    defaults.update(kwargs)
    return Concept(**defaults)


def _make_link(from_id: str, to_id: str, **kwargs) -> Link:
    defaults = dict(link_id="", from_id=from_id, to_id=to_id, rel="uses", label=None)
    defaults.update(kwargs)
    return Link(**defaults)


def _make_rating(concept_id: str, outcome: int = 4, **kwargs) -> Rating:
    defaults = dict(
        rating_id="",
        concept_id=concept_id,
        session_id="session-abc",
        outcome=outcome,
        hours_saved=None,
        notes=None,
        rated_at="",
    )
    defaults.update(kwargs)
    return Rating(**defaults)


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

class TestInitDb:
    def test_init_db_creates_tables(self, conn: sqlite3.Connection) -> None:
        """All four tables must exist after init_db."""
        expected_tables = {"concepts", "links", "ratings", "session_usage"}
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        actual_tables = {r["name"] for r in rows}
        assert expected_tables.issubset(actual_tables)

    def test_init_db_idempotent(self) -> None:
        """Calling init_db twice on the same path must not raise."""
        conn1 = init_db(":memory:")
        # In-memory DB can't be reopened as ":memory:", so we verify structural
        # idempotency by running executescript again manually.
        from pathlib import Path
        schema_sql = (Path(__file__).parent.parent / "selfhosted" / "schema.sql").read_text()
        # Must not raise — all CREATE TABLE statements use IF NOT EXISTS.
        conn1.executescript(schema_sql)

    def test_wal_mode_enabled(self, tmp_path) -> None:
        """WAL journal mode must be active on a file-backed connection.

        Note: SQLite :memory: databases always report 'memory' as the journal
        mode regardless of the PRAGMA — WAL requires a file-backed DB.
        """
        db_file = str(tmp_path / "wal_test.db")
        file_conn = init_db(db_file)
        try:
            row = file_conn.execute("PRAGMA journal_mode").fetchone()
            assert row[0] == "wal"
        finally:
            file_conn.close()

    def test_foreign_keys_enabled(self, conn: sqlite3.Connection) -> None:
        """Foreign key enforcement must be ON."""
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1


# ---------------------------------------------------------------------------
# Concept round-trips
# ---------------------------------------------------------------------------

class TestConceptCrud:
    def test_insert_and_get_concept(self, conn: sqlite3.Connection) -> None:
        """insert_concept + get_concept must round-trip all fields faithfully."""
        concept = _make_concept(
            name="Pagination cursor",
            type="pattern",
            tags=["pagination", "cursor"],
            language="generic",
            when_to_use="When paginating large result sets.",
            dont_use_when="When datasets fit in a single page.",
            source_url="https://example.com/cursor-pagination",
            author="alice",
        )
        cid = insert_concept(conn, concept)
        assert cid  # must return a non-empty string

        fetched = get_concept(conn, cid)
        assert fetched is not None
        assert fetched.name == "Pagination cursor"
        assert fetched.type == "pattern"
        assert fetched.tags == ["pagination", "cursor"]
        assert fetched.language == "generic"
        assert fetched.when_to_use == "When paginating large result sets."
        assert fetched.dont_use_when == "When datasets fit in a single page."
        assert fetched.source_url == "https://example.com/cursor-pagination"
        assert fetched.author == "alice"
        assert fetched.avg_rating == 0.0
        assert fetched.usage_count == 0
        assert fetched.time_saved_avg_hours is None
        assert fetched.embedding is None

    def test_tags_round_trip_as_list(self, conn: sqlite3.Connection) -> None:
        """Tags stored as JSON text must deserialise back to a Python list."""
        cid = insert_concept(conn, _make_concept(tags=["a", "b", "c"]))
        fetched = get_concept(conn, cid)
        assert fetched is not None
        assert fetched.tags == ["a", "b", "c"]

    def test_empty_tags_round_trip(self, conn: sqlite3.Connection) -> None:
        """An empty tags list must round-trip to an empty list (not None)."""
        cid = insert_concept(conn, _make_concept(tags=[]))
        fetched = get_concept(conn, cid)
        assert fetched is not None
        assert fetched.tags == []

    def test_get_concept_not_found(self, conn: sqlite3.Connection) -> None:
        """get_concept must return None for an unknown concept_id."""
        result = get_concept(conn, "00000000-0000-0000-0000-000000000000")
        assert result is None

    def test_insert_generates_new_id_when_empty(self, conn: sqlite3.Connection) -> None:
        """insert_concept must generate a UUID when concept_id is empty."""
        concept = _make_concept(concept_id="")
        cid = insert_concept(conn, concept)
        assert len(cid) == 36  # standard UUID4 hyphenated string length
        assert cid.count("-") == 4

    def test_insert_preserves_provided_id(self, conn: sqlite3.Connection) -> None:
        """insert_concept must use the caller-supplied concept_id when provided."""
        fixed_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        cid = insert_concept(conn, _make_concept(concept_id=fixed_id))
        assert cid == fixed_id


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

class TestLinks:
    def test_insert_link_and_get_links_from_source(self, conn: sqlite3.Connection) -> None:
        """A link inserted from A -> B must appear when fetching A's links."""
        cid_a = insert_concept(conn, _make_concept(name="A"))
        cid_b = insert_concept(conn, _make_concept(name="B"))
        link = _make_link(cid_a, cid_b, rel="uses", label="A uses B")
        lid = insert_link(conn, link)

        links = get_links_for_concept(conn, cid_a)
        assert len(links) == 1
        assert links[0].link_id == lid
        assert links[0].from_id == cid_a
        assert links[0].to_id == cid_b
        assert links[0].rel == "uses"
        assert links[0].label == "A uses B"

    def test_get_links_returns_both_directions(self, conn: sqlite3.Connection) -> None:
        """get_links_for_concept must return the edge when querying the target."""
        cid_a = insert_concept(conn, _make_concept(name="A"))
        cid_b = insert_concept(conn, _make_concept(name="B"))
        insert_link(conn, _make_link(cid_a, cid_b))

        links_b = get_links_for_concept(conn, cid_b)
        assert len(links_b) == 1
        assert links_b[0].from_id == cid_a
        assert links_b[0].to_id == cid_b

    def test_get_links_multiple_edges(self, conn: sqlite3.Connection) -> None:
        """get_links_for_concept returns all edges touching the concept."""
        cid_a = insert_concept(conn, _make_concept(name="A"))
        cid_b = insert_concept(conn, _make_concept(name="B"))
        cid_c = insert_concept(conn, _make_concept(name="C"))
        insert_link(conn, _make_link(cid_a, cid_b, rel="uses"))
        insert_link(conn, _make_link(cid_c, cid_a, rel="extends"))

        links_a = get_links_for_concept(conn, cid_a)
        assert len(links_a) == 2

    def test_get_links_empty_for_isolated_concept(self, conn: sqlite3.Connection) -> None:
        """A concept with no links must return an empty list."""
        cid = insert_concept(conn, _make_concept())
        assert get_links_for_concept(conn, cid) == []


# ---------------------------------------------------------------------------
# Ratings and aggregate recomputation
# ---------------------------------------------------------------------------

class TestRatings:
    def test_insert_rating_updates_avg(self, conn: sqlite3.Connection) -> None:
        """After two ratings, avg_rating on the concept must be their mean."""
        cid = insert_concept(conn, _make_concept())

        insert_rating(conn, _make_rating(cid, outcome=3))
        insert_rating(conn, _make_rating(cid, outcome=5))

        concept = get_concept(conn, cid)
        assert concept is not None
        assert concept.avg_rating == pytest.approx(4.0)

    def test_insert_rating_updates_time_saved_avg(self, conn: sqlite3.Connection) -> None:
        """time_saved_avg_hours must be the mean of non-NULL hours_saved values."""
        cid = insert_concept(conn, _make_concept())

        insert_rating(conn, _make_rating(cid, outcome=4, hours_saved=2.0))
        insert_rating(conn, _make_rating(cid, outcome=4, hours_saved=4.0))

        concept = get_concept(conn, cid)
        assert concept is not None
        assert concept.time_saved_avg_hours == pytest.approx(3.0)

    def test_time_saved_avg_ignores_null_rows(self, conn: sqlite3.Connection) -> None:
        """A rating with no hours_saved must not skew time_saved_avg_hours."""
        cid = insert_concept(conn, _make_concept())

        insert_rating(conn, _make_rating(cid, outcome=4, hours_saved=6.0))
        insert_rating(conn, _make_rating(cid, outcome=3, hours_saved=None))

        concept = get_concept(conn, cid)
        assert concept is not None
        # AVG ignores NULLs in SQL, so only the 6.0 row counts.
        assert concept.time_saved_avg_hours == pytest.approx(6.0)

    def test_time_saved_avg_none_when_no_hours_provided(self, conn: sqlite3.Connection) -> None:
        """time_saved_avg_hours must stay None if no rater provided hours_saved."""
        cid = insert_concept(conn, _make_concept())
        insert_rating(conn, _make_rating(cid, outcome=4, hours_saved=None))

        concept = get_concept(conn, cid)
        assert concept is not None
        assert concept.time_saved_avg_hours is None

    def test_insert_rating_preserves_usage_count(self, conn: sqlite3.Connection) -> None:
        """update_concept_stats triggered by insert_rating must not reset usage_count."""
        cid = insert_concept(conn, _make_concept())
        conn.execute(
            "UPDATE concepts SET usage_count = 7 WHERE concept_id = ?", (cid,)
        )
        conn.commit()

        insert_rating(conn, _make_rating(cid, outcome=5))

        concept = get_concept(conn, cid)
        assert concept is not None
        assert concept.usage_count == 7

    def test_rating_fk_violation_raises(self, conn: sqlite3.Connection) -> None:
        """Inserting a rating for a non-existent concept must raise IntegrityError."""
        with pytest.raises(sqlite3.IntegrityError):
            insert_rating(
                conn,
                _make_rating("00000000-0000-0000-0000-deadbeef0000", outcome=3),
            )

    def test_rating_fields_round_trip(self, conn: sqlite3.Connection) -> None:
        """Rating fields must persist correctly, including optional hours_saved and notes."""
        cid = insert_concept(conn, _make_concept())
        insert_rating(conn, _make_rating(cid, outcome=2, hours_saved=1.5, notes="worked well"))
        row = conn.execute(
            "SELECT * FROM ratings WHERE concept_id = ?", (cid,)
        ).fetchone()
        assert row["outcome"] == 2
        assert row["hours_saved"] == pytest.approx(1.5)
        assert row["notes"] == "worked well"
        assert row["rated_at"]


# ---------------------------------------------------------------------------
# Session usage
# ---------------------------------------------------------------------------

class TestSessionUsage:
    def test_log_session_usage_inserts_row(self, conn: sqlite3.Connection) -> None:
        """log_session_usage must insert a row into session_usage."""
        cid = insert_concept(conn, _make_concept())
        log_session_usage(conn, "session-xyz", cid)

        rows = conn.execute(
            "SELECT * FROM session_usage WHERE session_id = ? AND concept_id = ?",
            ("session-xyz", cid),
        ).fetchall()
        assert len(rows) == 1

    def test_log_session_usage_multiple_times(self, conn: sqlite3.Connection) -> None:
        """Multiple calls for the same (session, concept) are each recorded."""
        cid = insert_concept(conn, _make_concept())
        log_session_usage(conn, "session-xyz", cid)
        log_session_usage(conn, "session-xyz", cid)

        rows = conn.execute(
            "SELECT * FROM session_usage WHERE session_id = 'session-xyz'"
        ).fetchall()
        assert len(rows) == 2

    def test_log_session_usage_sets_used_at(self, conn: sqlite3.Connection) -> None:
        """Every session_usage row must have a non-empty used_at timestamp."""
        cid = insert_concept(conn, _make_concept())
        log_session_usage(conn, "session-xyz", cid)

        row = conn.execute(
            "SELECT used_at FROM session_usage WHERE session_id = 'session-xyz'"
        ).fetchone()
        assert row is not None
        assert row["used_at"]  # non-empty string


# ---------------------------------------------------------------------------
# search_concepts_by_ids
# ---------------------------------------------------------------------------

class TestSearchConceptsByIds:
    def test_empty_input_returns_empty_list(self, conn: sqlite3.Connection) -> None:
        assert search_concepts_by_ids(conn, []) == []

    def test_returns_concepts_in_input_order(self, conn: sqlite3.Connection) -> None:
        """Results must be ordered by the input list (preserving Qdrant relevance order)."""
        cid_a = insert_concept(conn, _make_concept(name="A"))
        cid_b = insert_concept(conn, _make_concept(name="B"))
        result = search_concepts_by_ids(conn, [cid_b, cid_a])
        assert [c.name for c in result] == ["B", "A"]

    def test_missing_ids_are_silently_omitted(self, conn: sqlite3.Connection) -> None:
        """Unknown IDs must be skipped without raising."""
        cid = insert_concept(conn, _make_concept(name="Real"))
        ghost = "00000000-0000-0000-0000-000000000001"
        result = search_concepts_by_ids(conn, [ghost, cid])
        assert len(result) == 1
        assert result[0].name == "Real"
