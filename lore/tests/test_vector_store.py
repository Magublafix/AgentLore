"""Unit tests for lore.selfhosted.vector_store.

All Qdrant interactions are mocked — no running Qdrant instance is required.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch, call

import pytest

from lore.selfhosted.vector_store import (
    _concept_id_to_point_id,
    init_qdrant_collection,
    search_vectors,
    upsert_concept_vector,
    VECTOR_DISTANCE,
    VECTOR_SIZE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(collection_names: list[str] | None = None) -> MagicMock:
    """Return a mock QdrantClient with a pre-populated collections list."""
    client = MagicMock()
    names = collection_names or []

    # get_collections().collections is a list of objects with .name attribute.
    # Note: MagicMock's `name` constructor kwarg sets the mock's internal name,
    # not a settable attribute — we must assign .name after construction.
    def _mock_collection(n: str) -> MagicMock:
        m = MagicMock()
        m.name = n
        return m

    client.get_collections.return_value.collections = [
        _mock_collection(n) for n in names
    ]
    return client


def _fake_vector(length: int = 384) -> list[float]:
    return [0.01 * i for i in range(length)]


# ---------------------------------------------------------------------------
# _concept_id_to_point_id
# ---------------------------------------------------------------------------

class TestConceptIdToPointId:
    def test_valid_uuid_returned_unchanged(self) -> None:
        """A well-formed UUID string must pass through unchanged."""
        cid = "550e8400-e29b-41d4-a716-446655440000"
        result = _concept_id_to_point_id(cid)
        assert result == cid

    def test_invalid_string_returns_deterministic_uuid(self) -> None:
        """A non-UUID string must produce a consistent UUID5-derived ID."""
        result1 = _concept_id_to_point_id("not-a-uuid")
        result2 = _concept_id_to_point_id("not-a-uuid")
        assert result1 == result2
        # Must be a valid UUID string
        uuid.UUID(result1)

    def test_different_strings_produce_different_ids(self) -> None:
        """Two distinct non-UUID strings must map to different point IDs."""
        r1 = _concept_id_to_point_id("concept-alpha")
        r2 = _concept_id_to_point_id("concept-beta")
        assert r1 != r2


# ---------------------------------------------------------------------------
# init_qdrant_collection
# ---------------------------------------------------------------------------

class TestInitQdrantCollection:
    def test_creates_collection_when_absent(self) -> None:
        """create_collection must be called when the collection does not exist."""
        client = _make_client(collection_names=[])
        init_qdrant_collection(client, collection_name="concepts")
        client.create_collection.assert_called_once()

        call_kwargs = client.create_collection.call_args
        assert call_kwargs.kwargs["collection_name"] == "concepts"
        vectors_config = call_kwargs.kwargs["vectors_config"]
        assert vectors_config.size == VECTOR_SIZE
        assert vectors_config.distance == VECTOR_DISTANCE

    def test_skips_creation_when_collection_exists(self) -> None:
        """create_collection must NOT be called when the collection already exists."""
        client = _make_client(collection_names=["concepts"])
        init_qdrant_collection(client, collection_name="concepts")
        client.create_collection.assert_not_called()

    def test_default_collection_name_is_concepts(self) -> None:
        """Calling init_qdrant_collection without a name argument uses 'concepts'."""
        client = _make_client(collection_names=[])
        init_qdrant_collection(client)
        call_kwargs = client.create_collection.call_args
        assert call_kwargs.kwargs["collection_name"] == "concepts"

    def test_other_collections_do_not_prevent_creation(self) -> None:
        """An existing collection with a different name must not block creation."""
        client = _make_client(collection_names=["other-collection"])
        init_qdrant_collection(client, collection_name="concepts")
        client.create_collection.assert_called_once()


# ---------------------------------------------------------------------------
# upsert_concept_vector
# ---------------------------------------------------------------------------

class TestUpsertConceptVector:
    def test_calls_upsert_with_correct_payload(self) -> None:
        """upsert must send the concept_id in the point payload."""
        client = MagicMock()
        cid = "550e8400-e29b-41d4-a716-446655440001"
        vector = _fake_vector()

        upsert_concept_vector(client, "concepts", cid, vector)

        client.upsert.assert_called_once()
        call_kwargs = client.upsert.call_args
        assert call_kwargs.kwargs["collection_name"] == "concepts"

        points = call_kwargs.kwargs["points"]
        assert len(points) == 1
        point = points[0]
        assert point.payload["concept_id"] == cid
        assert point.vector == vector

    def test_point_id_is_valid_uuid(self) -> None:
        """The Qdrant point ID derived from concept_id must be a valid UUID."""
        client = MagicMock()
        cid = "550e8400-e29b-41d4-a716-446655440002"
        upsert_concept_vector(client, "concepts", cid, _fake_vector())

        point = client.upsert.call_args.kwargs["points"][0]
        uuid.UUID(point.id)  # raises ValueError if not a valid UUID

    def test_non_uuid_concept_id_produces_stable_point_id(self) -> None:
        """A non-UUID concept_id must produce the same deterministic point ID on repeat calls."""
        client1 = MagicMock()
        client2 = MagicMock()
        cid = "my-custom-concept"
        upsert_concept_vector(client1, "concepts", cid, _fake_vector())
        upsert_concept_vector(client2, "concepts", cid, _fake_vector())

        pid1 = client1.upsert.call_args.kwargs["points"][0].id
        pid2 = client2.upsert.call_args.kwargs["points"][0].id
        assert pid1 == pid2


# ---------------------------------------------------------------------------
# search_vectors
# ---------------------------------------------------------------------------

class TestSearchVectors:
    def _mock_hit(self, concept_id: str, score: float = 0.9) -> MagicMock:
        hit = MagicMock()
        hit.payload = {"concept_id": concept_id}
        hit.score = score
        return hit

    def _mock_response(self, hits: list) -> MagicMock:
        """Wrap hits in a response object with a .points attribute (qdrant-client ≥1.8)."""
        resp = MagicMock()
        resp.points = hits
        return resp

    def test_returns_concept_ids_in_order(self) -> None:
        """search_vectors must return concept_ids in the order Qdrant returns them."""
        client = MagicMock()
        client.query_points.return_value = self._mock_response([
            self._mock_hit("cid-1", 0.95),
            self._mock_hit("cid-2", 0.80),
            self._mock_hit("cid-3", 0.70),
        ])

        result = search_vectors(client, "concepts", _fake_vector(), limit=3)
        assert result == ["cid-1", "cid-2", "cid-3"]

    def test_passes_limit_to_qdrant(self) -> None:
        """search_vectors must forward the limit parameter to client.query_points."""
        client = MagicMock()
        client.query_points.return_value = self._mock_response([])
        search_vectors(client, "concepts", _fake_vector(), limit=10)
        call_kwargs = client.query_points.call_args.kwargs
        assert call_kwargs["limit"] == 10

    def test_empty_results_returns_empty_list(self) -> None:
        """An empty Qdrant result set must return an empty list."""
        client = MagicMock()
        client.query_points.return_value = self._mock_response([])
        result = search_vectors(client, "concepts", _fake_vector())
        assert result == []

    def test_hits_without_payload_are_skipped(self) -> None:
        """Hits with a falsy payload must be skipped gracefully."""
        client = MagicMock()
        hit_ok = self._mock_hit("cid-good")
        hit_bad = MagicMock()
        hit_bad.payload = None
        client.query_points.return_value = self._mock_response([hit_ok, hit_bad])

        result = search_vectors(client, "concepts", _fake_vector())
        assert result == ["cid-good"]

    def test_default_limit_is_5(self) -> None:
        """Calling search_vectors without a limit argument must default to 5."""
        client = MagicMock()
        client.query_points.return_value = self._mock_response([])
        search_vectors(client, "concepts", _fake_vector())
        call_kwargs = client.query_points.call_args.kwargs
        assert call_kwargs["limit"] == 5
