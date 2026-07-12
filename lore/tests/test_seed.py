"""Unit tests for lore.seed.concepts.

All tests use an in-memory SQLite database and a mocked QdrantClient so that
no running Qdrant instance or real embedding model is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lore.selfhosted.db import init_db, get_concept, get_links_for_concept
from lore.seed.concepts import seed, SeedResult, _CONCEPT_DEFS, _LINK_DEFS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def conn():
    """In-memory SQLite connection with the Lore schema applied."""
    return init_db(":memory:")


@pytest.fixture()
def mock_qdrant():
    """Minimal QdrantClient mock that satisfies init_qdrant_collection + upsert calls."""
    client = MagicMock()
    # get_collections() is called by init_qdrant_collection to check existence
    collections_mock = MagicMock()
    collections_mock.collections = []
    client.get_collections.return_value = collections_mock
    return client


@pytest.fixture()
def mock_model():
    """Minimal EmbeddingModel mock that returns a deterministic 384-dim vector."""
    model = MagicMock()
    model.embed.return_value = [0.0] * 384
    model.dimension = 384
    return model


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestSeedHappyPath:
    def test_seed_inserts_all_concepts(self, conn, mock_qdrant, mock_model) -> None:
        """seed() must insert exactly as many concepts as defined in _CONCEPT_DEFS."""
        result = seed(conn=conn, qdrant_client=mock_qdrant, embedding_model=mock_model)

        assert result.skipped is False
        assert result.concepts_inserted == len(_CONCEPT_DEFS)

    def test_seed_inserts_all_links(self, conn, mock_qdrant, mock_model) -> None:
        """seed() must insert exactly as many links as defined in _LINK_DEFS."""
        result = seed(conn=conn, qdrant_client=mock_qdrant, embedding_model=mock_model)

        assert result.links_inserted == len(_LINK_DEFS)

    def test_seed_indexes_all_concepts(self, conn, mock_qdrant, mock_model) -> None:
        """When Qdrant and model are available every concept must be indexed."""
        result = seed(conn=conn, qdrant_client=mock_qdrant, embedding_model=mock_model)

        assert result.concepts_indexed == len(_CONCEPT_DEFS)

    def test_anchor_concept_is_queryable_after_seed(self, conn, mock_qdrant, mock_model) -> None:
        """The anchor concept must be retrievable from SQLite after seed()."""
        seed(conn=conn, qdrant_client=mock_qdrant, embedding_model=mock_model)

        row = conn.execute(
            "SELECT concept_id FROM concepts WHERE name = ?",
            ("REST CLI around a REST API",),
        ).fetchone()
        assert row is not None
        assert row["concept_id"]  # non-empty UUID string

    def test_anchor_concept_when_to_use_is_correct(self, conn, mock_qdrant, mock_model) -> None:
        """The anchor concept must have the correct when_to_use field."""
        seed(conn=conn, qdrant_client=mock_qdrant, embedding_model=mock_model)

        row = conn.execute(
            "SELECT when_to_use FROM concepts WHERE name = ?",
            ("REST CLI around a REST API",),
        ).fetchone()
        assert row is not None
        assert row["when_to_use"] == "building a typed CLI client for an existing REST API"

    def test_pagination_concept_when_to_use_correct(self, conn, mock_qdrant, mock_model) -> None:
        """The pagination concept must have the expected when_to_use value."""
        seed(conn=conn, qdrant_client=mock_qdrant, embedding_model=mock_model)

        row = conn.execute(
            "SELECT when_to_use FROM concepts WHERE name = ?",
            ("Pagination cursor handling",),
        ).fetchone()
        assert row is not None
        assert "next_cursor" in row["when_to_use"]

    def test_links_all_originate_from_anchor(self, conn, mock_qdrant, mock_model) -> None:
        """All inserted links must have from_id equal to the anchor concept's id."""
        seed(conn=conn, qdrant_client=mock_qdrant, embedding_model=mock_model)

        anchor_row = conn.execute(
            "SELECT concept_id FROM concepts WHERE name = ?",
            ("REST CLI around a REST API",),
        ).fetchone()
        assert anchor_row is not None
        anchor_id = anchor_row["concept_id"]

        links = get_links_for_concept(conn, anchor_id)
        outbound = [l for l in links if l.from_id == anchor_id]
        assert len(outbound) == len(_LINK_DEFS)
        for link in outbound:
            assert link.from_id == anchor_id

    def test_qdrant_upsert_called_once_per_concept(self, conn, mock_qdrant, mock_model) -> None:
        """Qdrant upsert must be called exactly once per concept."""
        seed(conn=conn, qdrant_client=mock_qdrant, embedding_model=mock_model)

        assert mock_qdrant.upsert.call_count == len(_CONCEPT_DEFS)

    def test_all_concept_names_present(self, conn, mock_qdrant, mock_model) -> None:
        """Every concept name from _CONCEPT_DEFS must be findable in SQLite."""
        seed(conn=conn, qdrant_client=mock_qdrant, embedding_model=mock_model)

        for defn in _CONCEPT_DEFS:
            row = conn.execute(
                "SELECT name FROM concepts WHERE name = ?", (defn["name"],)
            ).fetchone()
            assert row is not None, f"Concept '{defn['name']}' not found in DB"

    def test_concepts_have_correct_types(self, conn, mock_qdrant, mock_model) -> None:
        """Each seeded concept must have the type declared in its definition."""
        seed(conn=conn, qdrant_client=mock_qdrant, embedding_model=mock_model)

        for defn in _CONCEPT_DEFS:
            row = conn.execute(
                "SELECT type FROM concepts WHERE name = ?", (defn["name"],)
            ).fetchone()
            assert row is not None
            assert row["type"] == defn["type"]


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestSeedIdempotency:
    def test_second_seed_call_returns_skipped_true(self, conn, mock_qdrant, mock_model) -> None:
        """A second call to seed() with the same connection must return skipped=True."""
        seed(conn=conn, qdrant_client=mock_qdrant, embedding_model=mock_model)
        result2 = seed(conn=conn, qdrant_client=mock_qdrant, embedding_model=mock_model)

        assert result2.skipped is True

    def test_second_seed_call_does_not_raise(self, conn, mock_qdrant, mock_model) -> None:
        """Calling seed() twice must not raise any exception."""
        seed(conn=conn, qdrant_client=mock_qdrant, embedding_model=mock_model)
        # Must not raise
        seed(conn=conn, qdrant_client=mock_qdrant, embedding_model=mock_model)

    def test_second_seed_call_does_not_duplicate_concepts(self, conn, mock_qdrant, mock_model) -> None:
        """Row count must not change after a second seed() call."""
        seed(conn=conn, qdrant_client=mock_qdrant, embedding_model=mock_model)
        count_after_first = conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]

        seed(conn=conn, qdrant_client=mock_qdrant, embedding_model=mock_model)
        count_after_second = conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]

        assert count_after_first == count_after_second

    def test_second_seed_call_inserts_zero(self, conn, mock_qdrant, mock_model) -> None:
        """SeedResult on the second call must report 0 insertions."""
        seed(conn=conn, qdrant_client=mock_qdrant, embedding_model=mock_model)
        result2 = seed(conn=conn, qdrant_client=mock_qdrant, embedding_model=mock_model)

        assert result2.concepts_inserted == 0
        assert result2.links_inserted == 0
        assert result2.concepts_indexed == 0


# ---------------------------------------------------------------------------
# Qdrant unavailable — SQLite still works
# ---------------------------------------------------------------------------

class TestSeedQdrantUnavailable:
    @pytest.fixture(autouse=True)
    def block_qdrant(self, monkeypatch):
        """Patch QdrantClient so tests are deterministic regardless of local infra."""
        import qdrant_client as qc
        monkeypatch.setattr(qc, "QdrantClient", MagicMock(side_effect=ConnectionError("blocked")))

    def test_seed_without_qdrant_still_inserts_concepts(self, conn) -> None:
        """When Qdrant is not supplied, SQLite inserts must still succeed."""
        result = seed(conn=conn, qdrant_client=None, embedding_model=None)

        assert result.skipped is False
        assert result.concepts_inserted == len(_CONCEPT_DEFS)
        assert result.links_inserted == len(_LINK_DEFS)

    def test_seed_without_qdrant_reports_zero_indexed(self, conn) -> None:
        """concepts_indexed must be 0 when Qdrant is unavailable."""
        result = seed(conn=conn, qdrant_client=None, embedding_model=None)

        assert result.concepts_indexed == 0


# ---------------------------------------------------------------------------
# Qdrant connectivity probe failure (Gap 5 — lines 354-371)
# ---------------------------------------------------------------------------

class TestSeedQdrantProbeFailure:
    """seed() continues when the Qdrant connectivity probe (get_collections) fails."""

    def test_seed_continues_if_qdrant_probe_fails(self, conn) -> None:
        """When get_collections() raises after QdrantClient is built, seed still inserts."""
        unreachable = MagicMock()
        unreachable.get_collections.side_effect = ConnectionRefusedError("no qdrant")

        with patch("qdrant_client.QdrantClient", return_value=unreachable):
            result = seed(conn=conn, qdrant_client=None, embedding_model=None)

        assert result.skipped is False
        assert result.concepts_inserted == len(_CONCEPT_DEFS)
        assert result.links_inserted == len(_LINK_DEFS)
        assert result.concepts_indexed == 0

    def test_seed_sqlite_rows_intact_when_qdrant_probe_fails(self, conn) -> None:
        """All concepts must be queryable from SQLite even if Qdrant is unreachable."""
        unreachable = MagicMock()
        unreachable.get_collections.side_effect = ConnectionRefusedError("no qdrant")

        with patch("qdrant_client.QdrantClient", return_value=unreachable):
            seed(conn=conn, qdrant_client=None, embedding_model=None)

        count = conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
        assert count == len(_CONCEPT_DEFS)


# ---------------------------------------------------------------------------
# SeedResult dataclass
# ---------------------------------------------------------------------------

class TestSeedResult:
    def test_seed_result_fields(self) -> None:
        """SeedResult must expose all four expected fields."""
        r = SeedResult(
            concepts_inserted=6,
            links_inserted=5,
            concepts_indexed=6,
            skipped=False,
        )
        assert r.concepts_inserted == 6
        assert r.links_inserted == 5
        assert r.concepts_indexed == 6
        assert r.skipped is False
