"""Unit tests for lore.selfhosted.indexer.

SQLite uses in-memory databases.  QdrantClient is fully mocked — no running
Qdrant instance is required.  The EmbeddingModel is mocked to avoid loading
the real sentence-transformers model (which is covered by test_embeddings.py).
"""

from __future__ import annotations

import struct
from unittest.mock import MagicMock, call

import pytest

from lore.mcp.models import Concept
from lore.selfhosted.db import init_db, insert_concept, get_concept
from lore.selfhosted.indexer import index_concept, search_concepts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_concept(
    concept_id: str = "aabbccdd-0000-0000-0000-000000000001",
    name: str = "SQLite WAL Mode",
    type: str = "pattern",
    language: str | None = "python",
    when_to_use: str = "Use when you need crash-safe concurrent SQLite writes",
) -> Concept:
    """Return a minimal valid :class:`Concept` for testing."""
    return Concept(
        concept_id=concept_id,
        name=name,
        type=type,
        content="Enable WAL mode for better concurrency.",
        language=language,
        when_to_use=when_to_use,
        dont_use_when=None,
    )


def _fake_vector(dim: int = 384) -> list[float]:
    """Return a deterministic fake vector."""
    return [0.001 * i for i in range(dim)]


def _make_model(vector: list[float] | None = None) -> MagicMock:
    """Return a mock EmbeddingModel that returns a deterministic vector."""
    model = MagicMock()
    model.embed.return_value = vector or _fake_vector()
    model.dimension = 384
    return model


def _make_qdrant_client(hit_concept_ids: list[str] | None = None) -> MagicMock:
    """Return a mock QdrantClient.

    Uses query_points (qdrant-client ≥1.8) which returns a response object
    with a .points attribute rather than a bare list.
    """
    client = MagicMock()

    def _make_hit(cid: str) -> MagicMock:
        hit = MagicMock()
        hit.payload = {"concept_id": cid}
        hit.score = 0.9
        return hit

    resp = MagicMock()
    resp.points = [_make_hit(cid) for cid in (hit_concept_ids or [])]
    client.query_points.return_value = resp
    return client


# ---------------------------------------------------------------------------
# index_concept tests
# ---------------------------------------------------------------------------

class TestIndexConcept:
    def test_index_concept_stores_embedding_in_sqlite(self) -> None:
        """After index_concept, get_concept must return a concept with non-None embedding."""
        conn = init_db(":memory:")
        concept = _make_concept()
        insert_concept(conn, concept)

        model = _make_model()
        qdrant = _make_qdrant_client()

        index_concept(conn, qdrant, concept, model)

        stored = get_concept(conn, concept.concept_id)
        assert stored is not None
        assert stored.embedding is not None
        assert len(stored.embedding) > 0

    def test_index_concept_embedding_blob_is_float32_bytes(self) -> None:
        """The embedding BLOB must be exactly 384 * 4 bytes (float32 little-endian)."""
        conn = init_db(":memory:")
        concept = _make_concept()
        insert_concept(conn, concept)

        model = _make_model()
        qdrant = _make_qdrant_client()

        index_concept(conn, qdrant, concept, model)

        stored = get_concept(conn, concept.concept_id)
        assert stored is not None
        assert stored.embedding is not None
        assert len(stored.embedding) == 384 * 4  # 384 float32 values

    def test_index_concept_calls_qdrant_upsert(self) -> None:
        """index_concept must call upsert_concept_vector with a 384-dim vector."""
        conn = init_db(":memory:")
        concept = _make_concept()
        insert_concept(conn, concept)

        vector = _fake_vector()
        model = _make_model(vector)
        qdrant = MagicMock()  # direct mock — capture all calls

        index_concept(conn, qdrant, concept, model)

        qdrant.upsert.assert_called_once()
        call_kwargs = qdrant.upsert.call_args.kwargs
        points = call_kwargs["points"]
        assert len(points) == 1
        assert points[0].vector == vector
        assert points[0].payload["concept_id"] == concept.concept_id

    def test_index_concept_returns_concept_id(self) -> None:
        """index_concept must return the concept_id unchanged."""
        conn = init_db(":memory:")
        concept = _make_concept()
        insert_concept(conn, concept)

        model = _make_model()
        qdrant = _make_qdrant_client()

        result = index_concept(conn, qdrant, concept, model)
        assert result == concept.concept_id

    def test_index_concept_embeds_correct_text(self) -> None:
        """The model must be called with 'when_to_use + \" \" + name'."""
        conn = init_db(":memory:")
        concept = _make_concept(
            name="Retry Pattern",
            when_to_use="Use for transient failures",
        )
        insert_concept(conn, concept)

        model = _make_model()
        qdrant = _make_qdrant_client()

        index_concept(conn, qdrant, concept, model)

        model.embed.assert_called_once_with("Use for transient failures Retry Pattern")


# ---------------------------------------------------------------------------
# search_concepts tests
# ---------------------------------------------------------------------------

class TestSearchConcepts:
    def test_search_concepts_returns_concepts_in_order(self) -> None:
        """Results must follow Qdrant's relevance order."""
        conn = init_db(":memory:")
        cid1 = "aabbccdd-0000-0000-0000-000000000001"
        cid2 = "aabbccdd-0000-0000-0000-000000000002"

        c1 = _make_concept(concept_id=cid1, name="First")
        c2 = _make_concept(concept_id=cid2, name="Second")
        insert_concept(conn, c1)
        insert_concept(conn, c2)

        # Qdrant returns cid1 first (higher score)
        qdrant = _make_qdrant_client(hit_concept_ids=[cid1, cid2])
        model = _make_model()

        results = search_concepts(conn, qdrant, model, "some problem", min_rating=0)
        assert len(results) == 2
        assert results[0].concept_id == cid1
        assert results[1].concept_id == cid2

    def test_search_concepts_applies_type_filter(self) -> None:
        """Only concepts matching type_filter must be returned."""
        conn = init_db(":memory:")
        cid_pattern = "aabbccdd-0000-0000-0000-000000000001"
        cid_tool = "aabbccdd-0000-0000-0000-000000000002"

        c_pattern = _make_concept(concept_id=cid_pattern, name="Retry", type="pattern")
        c_tool = _make_concept(concept_id=cid_tool, name="Redis", type="tool")
        insert_concept(conn, c_pattern)
        insert_concept(conn, c_tool)

        qdrant = _make_qdrant_client(hit_concept_ids=[cid_pattern, cid_tool])
        model = _make_model()

        results = search_concepts(conn, qdrant, model, "some problem", type_filter="pattern", min_rating=0)
        assert len(results) == 1
        assert results[0].type == "pattern"
        assert results[0].concept_id == cid_pattern

    def test_search_concepts_applies_language_filter(self) -> None:
        """Only concepts matching language_filter must be returned."""
        conn = init_db(":memory:")
        cid_py = "aabbccdd-0000-0000-0000-000000000001"
        cid_ts = "aabbccdd-0000-0000-0000-000000000002"

        c_py = _make_concept(concept_id=cid_py, name="PyPattern", language="python")
        c_ts = _make_concept(concept_id=cid_ts, name="TsPattern", language="typescript")
        insert_concept(conn, c_py)
        insert_concept(conn, c_ts)

        qdrant = _make_qdrant_client(hit_concept_ids=[cid_py, cid_ts])
        model = _make_model()

        results = search_concepts(
            conn, qdrant, model, "some problem", language_filter="python", min_rating=0
        )
        assert len(results) == 1
        assert results[0].language == "python"
        assert results[0].concept_id == cid_py

    def test_search_concepts_empty_qdrant_returns_empty(self) -> None:
        """When Qdrant returns no results, the function must return an empty list."""
        conn = init_db(":memory:")
        qdrant = _make_qdrant_client(hit_concept_ids=[])
        model = _make_model()

        results = search_concepts(conn, qdrant, model, "any problem")
        assert results == []

    def test_search_concepts_respects_limit(self) -> None:
        """Results must be truncated to limit after filtering."""
        conn = init_db(":memory:")
        ids = [f"aabbccdd-0000-0000-0000-{str(i).zfill(12)}" for i in range(1, 6)]
        for i, cid in enumerate(ids):
            insert_concept(conn, _make_concept(concept_id=cid, name=f"C{i}"))

        qdrant = _make_qdrant_client(hit_concept_ids=ids)
        model = _make_model()

        results = search_concepts(conn, qdrant, model, "problem", limit=3, min_rating=0)
        assert len(results) == 3

    def test_search_concepts_type_and_language_filter_combined(self) -> None:
        """Both type_filter and language_filter are applied together (AND semantics)."""
        conn = init_db(":memory:")
        cid_match = "aabbccdd-0000-0000-0000-000000000001"
        cid_type_only = "aabbccdd-0000-0000-0000-000000000002"
        cid_lang_only = "aabbccdd-0000-0000-0000-000000000003"

        insert_concept(conn, _make_concept(
            concept_id=cid_match, name="Match", type="pattern", language="python"
        ))
        insert_concept(conn, _make_concept(
            concept_id=cid_type_only, name="TypeOnly", type="pattern", language="typescript"
        ))
        insert_concept(conn, _make_concept(
            concept_id=cid_lang_only, name="LangOnly", type="tool", language="python"
        ))

        qdrant = _make_qdrant_client(
            hit_concept_ids=[cid_match, cid_type_only, cid_lang_only]
        )
        model = _make_model()

        results = search_concepts(
            conn, qdrant, model, "some problem",
            type_filter="pattern", language_filter="python", min_rating=0
        )
        assert len(results) == 1
        assert results[0].concept_id == cid_match

    def test_search_concepts_language_filter_excludes_none_language(self) -> None:
        """Concepts with language=None must be excluded when language_filter is active."""
        conn = init_db(":memory:")
        cid_none_lang = "aabbccdd-0000-0000-0000-000000000001"
        cid_py = "aabbccdd-0000-0000-0000-000000000002"

        insert_concept(conn, _make_concept(
            concept_id=cid_none_lang, name="Generic", language=None
        ))
        insert_concept(conn, _make_concept(
            concept_id=cid_py, name="PyConcept", language="python"
        ))

        qdrant = _make_qdrant_client(hit_concept_ids=[cid_none_lang, cid_py])
        model = _make_model()

        results = search_concepts(
            conn, qdrant, model, "problem", language_filter="python", min_rating=0
        )
        assert len(results) == 1
        assert results[0].concept_id == cid_py

    def test_search_concepts_calls_qdrant_exactly_once(self) -> None:
        """search_concepts must issue exactly one search call to Qdrant — no N+1."""
        conn = init_db(":memory:")
        cid = "aabbccdd-0000-0000-0000-000000000001"
        insert_concept(conn, _make_concept(concept_id=cid))
        qdrant = _make_qdrant_client(hit_concept_ids=[cid])
        model = _make_model()

        search_concepts(conn, qdrant, model, "some problem")

        qdrant.query_points.assert_called_once()
