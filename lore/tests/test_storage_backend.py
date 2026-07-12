"""Tests for real SqliteQdrantBackend and GistQdrantBackend classes.

Strategy
--------
- SqliteQdrantBackend is instantiated via __new__ + direct attribute injection
  to bypass the real Qdrant/SQLite constructor calls, then wired to in-memory
  SQLite and in-memory Qdrant.
- GistQdrantBackend is similarly bypassed and wired to in-memory Qdrant.
- EmbeddingModel is mocked — no sentence-transformers load occurs.
- All tests are fully offline and fast.

Test areas
----------
SqliteQdrantBackend:
    - upsert_concept returns concept_id + name (no _qdrant_failed)
    - get_concept returns upserted concept with links: []
    - search_concepts returns results for matching vector
    - rate_concept returns avg_rating + time_saved_avg_hours
    - upsert_concept with Qdrant failure sets _qdrant_failed: True, retains SQLite row

GistQdrantBackend:
    - upsert_concept returns status=upserted + gist_id
    - get_concept returns None for unknown gist_id
    - upsert_concept idempotency (same gist_updated_at → status=skipped)
    - rate_concept raises NotImplementedError
    - health_check returns {"status": "ok"}
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from qdrant_client import QdrantClient

from lore.selfhosted.db import init_db
from lore.server.storage.sqlite_qdrant import COLLECTION_NAME, SqliteQdrantBackend
from lore.server.storage.gist_qdrant import GistQdrantBackend


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_backend():
    """Return a SqliteQdrantBackend wired to in-memory SQLite and Qdrant."""
    backend = SqliteQdrantBackend.__new__(SqliteQdrantBackend)
    backend._conn = init_db(":memory:")
    backend._qdrant = QdrantClient(":memory:")

    model = MagicMock()
    model.embed.return_value = [0.0] * 384
    backend._model = model

    # Initialise the Qdrant collection so upsert/search calls succeed.
    from lore.selfhosted.vector_store import init_qdrant_collection
    init_qdrant_collection(backend._qdrant, collection_name=COLLECTION_NAME)

    return backend


@pytest.fixture
def gist_backend():
    """Return a GistQdrantBackend wired to an in-memory Qdrant."""
    backend = GistQdrantBackend.__new__(GistQdrantBackend)
    backend._qdrant = QdrantClient(":memory:")

    model = MagicMock()
    model.embed.return_value = [0.0] * 384
    backend._model = model

    # Initialise the Qdrant collection so upsert/search calls succeed.
    from lore.server.storage.gist_qdrant import _init_collection
    _init_collection(backend._qdrant)

    return backend


def _minimal_concept_payload(**overrides) -> dict:
    """Return a minimal valid concept payload for SqliteQdrantBackend.upsert_concept."""
    base = {
        "name": "WAL Mode",
        "type": "pattern",
        "content": "Enable WAL mode with PRAGMA journal_mode=WAL.",
        "language": "python",
        "when_to_use": "Use for crash-safe concurrent SQLite writes.",
        "dont_use_when": None,
        "tags": ["sqlite"],
        "source_url": None,
        "author": "test-agent",
    }
    base.update(overrides)
    return base


def _minimal_gist_payload(**overrides) -> dict:
    """Return a minimal valid concept payload for GistQdrantBackend.upsert_concept."""
    base = {
        "gist_id": "test-gist-001",
        "name": "WAL Mode",
        "type": "pattern",
        "language": "python",
        "author": "test-agent",
        "tags": ["sqlite"],
        "when_to_use": "Use for crash-safe concurrent SQLite writes.",
        "dont_use_when": None,
        "gist_updated_at": "2026-07-11T00:00:00Z",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# SqliteQdrantBackend tests
# ---------------------------------------------------------------------------


class TestSqliteQdrantBackendUpsert:
    """upsert_concept happy path."""

    def test_upsert_returns_concept_id_and_name(self, sqlite_backend):
        """upsert_concept returns dict with concept_id and name, no _qdrant_failed."""
        result = sqlite_backend.upsert_concept(_minimal_concept_payload())

        assert "concept_id" in result
        assert result["name"] == "WAL Mode"
        assert "_qdrant_failed" not in result
        # concept_id must be a valid UUID.
        uuid.UUID(result["concept_id"])

    def test_upsert_persists_row_in_sqlite(self, sqlite_backend):
        """After upsert_concept the concept is retrievable from SQLite."""
        result = sqlite_backend.upsert_concept(_minimal_concept_payload())
        concept_id = result["concept_id"]

        row = sqlite_backend._conn.execute(
            "SELECT concept_id, name FROM concepts WHERE concept_id = ?",
            (concept_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == concept_id


class TestSqliteQdrantBackendGetConcept:
    """get_concept behaviour."""

    def test_get_concept_returns_upserted_concept(self, sqlite_backend):
        """get_concept returns the concept with links: [] after upsert."""
        result = sqlite_backend.upsert_concept(_minimal_concept_payload())
        concept_id = result["concept_id"]

        fetched = sqlite_backend.get_concept(concept_id)

        assert fetched is not None
        assert fetched["concept_id"] == concept_id
        assert fetched["name"] == "WAL Mode"
        assert "links" in fetched
        assert fetched["links"] == []

    def test_get_concept_returns_none_for_unknown_id(self, sqlite_backend):
        """get_concept returns None for an ID that does not exist."""
        result = sqlite_backend.get_concept(str(uuid.uuid4()))
        assert result is None


class TestSqliteQdrantBackendSearch:
    """search_concepts behaviour."""

    def test_search_returns_results(self, sqlite_backend):
        """search_concepts returns a list (may be empty due to all-zero vectors)."""
        sqlite_backend.upsert_concept(_minimal_concept_payload())

        # All-zero query vector — results depend on Qdrant's cosine scoring
        # for all-zero vectors, but the call must not raise.
        results = sqlite_backend.search_concepts(
            query_vector=[0.0] * 384,
            limit=5,
            type_filter=None,
            language_filter=None,
            min_rating=0.0,
        )

        assert isinstance(results, list)

    def test_search_empty_collection_returns_empty_list(self, sqlite_backend):
        """search_concepts on an empty collection returns []."""
        results = sqlite_backend.search_concepts(
            query_vector=[0.0] * 384,
            limit=5,
            type_filter=None,
            language_filter=None,
            min_rating=0.0,
        )
        assert results == []


class TestSqliteQdrantBackendRate:
    """rate_concept behaviour."""

    def test_rate_concept_returns_avg_rating(self, sqlite_backend):
        """rate_concept returns dict with avg_rating and time_saved_avg_hours."""
        result = sqlite_backend.upsert_concept(_minimal_concept_payload())
        concept_id = result["concept_id"]

        rating_result = sqlite_backend.rate_concept(
            concept_id=concept_id,
            outcome=4,
            session_id="session-001",
            hours_saved=1.5,
            notes="Helpful pattern",
        )

        assert "avg_rating" in rating_result
        assert "time_saved_avg_hours" in rating_result
        assert rating_result["avg_rating"] == pytest.approx(4.0)
        assert rating_result["time_saved_avg_hours"] == pytest.approx(1.5)

    def test_rate_concept_multiple_ratings_average(self, sqlite_backend):
        """Multiple ratings produce a correct rolling average."""
        result = sqlite_backend.upsert_concept(_minimal_concept_payload())
        concept_id = result["concept_id"]

        sqlite_backend.rate_concept(
            concept_id=concept_id, outcome=2, session_id=None,
            hours_saved=None, notes=None,
        )
        result2 = sqlite_backend.rate_concept(
            concept_id=concept_id, outcome=4, session_id=None,
            hours_saved=None, notes=None,
        )

        assert result2["avg_rating"] == pytest.approx(3.0)


class TestSqliteQdrantBackendQdrantFailure:
    """Qdrant failure during upsert_concept."""

    def test_qdrant_failure_sets_qdrant_failed_flag(self, sqlite_backend):
        """When index_concept raises, _qdrant_failed is True in the return dict."""
        with patch(
            "lore.server.storage.sqlite_qdrant.index_concept",
            side_effect=Exception("qdrant down"),
        ):
            result = sqlite_backend.upsert_concept(_minimal_concept_payload())

        assert result.get("_qdrant_failed") is True

    def test_qdrant_failure_returns_real_concept_id(self, sqlite_backend):
        """When Qdrant fails, the returned concept_id is a valid UUID (not fabricated)."""
        with patch(
            "lore.server.storage.sqlite_qdrant.index_concept",
            side_effect=Exception("qdrant down"),
        ):
            result = sqlite_backend.upsert_concept(_minimal_concept_payload())

        assert "concept_id" in result
        uuid.UUID(result["concept_id"])

    def test_qdrant_failure_retains_sqlite_row(self, sqlite_backend):
        """When Qdrant fails, the SQLite row is NOT rolled back."""
        with patch(
            "lore.server.storage.sqlite_qdrant.index_concept",
            side_effect=Exception("qdrant down"),
        ):
            result = sqlite_backend.upsert_concept(_minimal_concept_payload())

        concept_id = result["concept_id"]
        row = sqlite_backend._conn.execute(
            "SELECT concept_id FROM concepts WHERE concept_id = ?",
            (concept_id,),
        ).fetchone()
        assert row is not None, "SQLite row must be retained when Qdrant indexing fails"


# ---------------------------------------------------------------------------
# GistQdrantBackend tests
# ---------------------------------------------------------------------------


class TestGistQdrantBackendUpsert:
    """upsert_concept behaviour."""

    def test_upsert_returns_status_upserted(self, gist_backend):
        """A new gist returns {"status": "upserted", "gist_id": ...}."""
        result = gist_backend.upsert_concept(_minimal_gist_payload())

        assert result["status"] == "upserted"
        assert result["gist_id"] == "test-gist-001"

    def test_upsert_idempotent_same_timestamp_returns_skipped(self, gist_backend):
        """Second upsert with same gist_updated_at returns {"status": "skipped"}."""
        payload = _minimal_gist_payload()
        gist_backend.upsert_concept(payload)

        result = gist_backend.upsert_concept(payload)

        assert result["status"] == "skipped"
        assert result["gist_id"] == "test-gist-001"

    def test_upsert_different_timestamp_re_embeds(self, gist_backend):
        """Upsert with a different gist_updated_at triggers re-embed."""
        payload = _minimal_gist_payload()
        gist_backend.upsert_concept(payload)

        updated_payload = _minimal_gist_payload(gist_updated_at="2026-07-12T00:00:00Z")
        result = gist_backend.upsert_concept(updated_payload)

        assert result["status"] == "upserted"

    def test_upsert_calls_embed_on_new_concept(self, gist_backend):
        """A new upsert calls model.embed() once."""
        gist_backend.upsert_concept(_minimal_gist_payload())

        gist_backend._model.embed.assert_called_once()

    def test_upsert_skipped_does_not_call_embed(self, gist_backend):
        """An idempotent (skipped) upsert must NOT call model.embed()."""
        payload = _minimal_gist_payload()
        gist_backend.upsert_concept(payload)
        gist_backend._model.embed.reset_mock()

        gist_backend.upsert_concept(payload)

        gist_backend._model.embed.assert_not_called()


class TestGistQdrantBackendGetConcept:
    """get_concept behaviour."""

    def test_get_concept_returns_upserted_concept(self, gist_backend):
        """get_concept returns the concept after upsert."""
        payload = _minimal_gist_payload()
        gist_backend.upsert_concept(payload)

        fetched = gist_backend.get_concept("test-gist-001")

        assert fetched is not None
        assert fetched["concept_id"] == "test-gist-001"
        assert fetched["name"] == "WAL Mode"
        assert fetched["links"] == []

    def test_get_concept_returns_none_for_unknown_gist_id(self, gist_backend):
        """get_concept returns None for a gist_id that has not been upserted."""
        result = gist_backend.get_concept("nonexistent-gist-id")
        assert result is None


class TestGistQdrantBackendRate:
    """rate_concept behaviour."""

    def test_rate_concept_raises_not_implemented(self, gist_backend):
        """rate_concept raises NotImplementedError for GistQdrantBackend."""
        with pytest.raises(NotImplementedError):
            gist_backend.rate_concept(
                concept_id="test-gist-001",
                outcome=3,
                session_id=None,
                hours_saved=None,
                notes=None,
            )


class TestGistQdrantBackendHealth:
    """health_check behaviour."""

    def test_health_check_returns_ok(self, gist_backend):
        """health_check returns {"status": "ok"} when Qdrant is reachable."""
        result = gist_backend.health_check()
        assert result == {"status": "ok"}
