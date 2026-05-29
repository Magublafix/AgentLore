"""Tests for lore.selfhosted.api (LORE-003).

Strategy
--------
- All tests use an in-memory SQLite database (no filesystem artefacts).
- ``QdrantClient`` and ``EmbeddingModel`` are always mocked — no running
  Qdrant instance is required and no model is loaded.
- ``indexer.index_concept`` and ``indexer.search_concepts`` are patched at the
  module level so handlers never reach real Qdrant.
- The FastAPI lifespan is patched to a no-op, then ``app.state`` is injected
  INSIDE the ``TestClient`` context (i.e. after the patched lifespan runs).
  This guarantees the test-supplied connection/mocks are what the handlers see.

All tests are synchronous; ``fastapi.testclient.TestClient`` drives the ASGI
app synchronously using ``httpx`` under the hood.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager, contextmanager
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lore.mcp.models import Concept, Link
from lore.selfhosted.api import app, COLLECTION_NAME
from lore.selfhosted.db import init_db, insert_concept


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_concept(
    concept_id: str | None = None,
    name: str = "WAL Mode",
    type: str = "pattern",
    language: str | None = "python",
    when_to_use: str = "Use for crash-safe concurrent SQLite writes",
) -> Concept:
    """Return a minimal valid Concept for seeding test databases."""
    return Concept(
        concept_id=concept_id or str(uuid.uuid4()),
        name=name,
        type=type,
        content="Enable WAL mode with PRAGMA journal_mode=WAL.",
        language=language,
        when_to_use=when_to_use,
        dont_use_when=None,
    )


def _fake_vector(dim: int = 384) -> list[float]:
    return [0.001 * i for i in range(dim)]


def _noop_lifespan(app: FastAPI):
    """Async context manager lifespan that does nothing — used to bypass real startup."""
    @asynccontextmanager
    async def _inner(app: FastAPI):
        yield
    return _inner(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def conn():
    """Return an initialised in-memory SQLite connection."""
    return init_db(":memory:")


@pytest.fixture()
def mock_qdrant():
    """Return a MagicMock QdrantClient that satisfies health checks."""
    client = MagicMock()
    client.get_collections.return_value = MagicMock(collections=[])
    return client


@pytest.fixture()
def mock_model():
    """Return a MagicMock EmbeddingModel that returns a deterministic vector."""
    model = MagicMock()
    model.embed.return_value = _fake_vector()
    model.dimension = 384
    return model


@pytest.fixture()
def client(conn, mock_qdrant, mock_model) -> Generator[TestClient, None, None]:
    """Return a TestClient with injected in-memory state.

    The lifespan is patched to a no-op so that no real Qdrant connection or
    model load occurs.  App state is set immediately after the lifespan stub
    completes (inside the ``with TestClient`` block), so handlers see the
    test-supplied objects.
    """
    with patch("lore.selfhosted.api.lifespan", _noop_lifespan):
        with TestClient(app, raise_server_exceptions=True) as c:
            # Inject test state after (no-op) lifespan has run.
            app.state.db = conn
            app.state.qdrant = mock_qdrant
            app.state.model = mock_model
            yield c


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health_returns_ok(client):
    """GET /v1/health returns 200 with status=ok and both flags True."""
    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["qdrant"] is True
    assert data["db"] is True


def test_health_qdrant_down_returns_false(client, mock_qdrant):
    """If Qdrant raises, health returns qdrant=False but still HTTP 200."""
    mock_qdrant.get_collections.side_effect = Exception("connection refused")
    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["qdrant"] is False
    assert data["db"] is True


def test_health_db_down_returns_false(client):
    """If the SQLite connection raises, health returns db=False but still HTTP 200."""
    bad_db = MagicMock()
    bad_db.execute.side_effect = Exception("db gone")
    with patch.object(app.state, "db", bad_db):
        response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["db"] is False


# ---------------------------------------------------------------------------
# Submit concept
# ---------------------------------------------------------------------------

VALID_BODY = {
    "name": "SQLite WAL Mode",
    "type": "pattern",
    "content": "## Description\nEnable WAL mode.",
    "language": "python",
    "when_to_use": "Use for concurrent SQLite writes.",
    "dont_use_when": None,
    "tags": ["sqlite", "concurrency"],
    "source_url": None,
    "author": "test-agent",
    "links": [],
}


def test_submit_concept_returns_201(client):
    """POST /v1/concepts with valid body returns 201 and a concept_id."""
    with patch("lore.selfhosted.api.index_concept") as mock_idx:
        mock_idx.return_value = "fake-id"
        response = client.post("/v1/concepts", json=VALID_BODY)

    assert response.status_code == 201
    data = response.json()
    assert "concept_id" in data
    assert data["name"] == "SQLite WAL Mode"
    # Verify it looks like a UUID
    uuid.UUID(data["concept_id"])


def test_submit_concept_invalid_type_returns_422(client):
    """POST /v1/concepts with type='invalid' returns 422."""
    body = {**VALID_BODY, "type": "invalid"}
    response = client.post("/v1/concepts", json=body)
    assert response.status_code == 422


def test_submit_concept_scanner_block_returns_422(client):
    """If scan_content returns matches, submit returns 422 with the matches."""
    matches = [{"field": "content", "reason": "credential detected"}]
    with patch("lore.selfhosted.api.scan_content", return_value=matches):
        response = client.post("/v1/concepts", json=VALID_BODY)
    assert response.status_code == 422
    data = response.json()
    assert "blocked" in data["error"].lower() or "scanner" in data["error"].lower()
    assert data["matches"] == matches


def test_submit_concept_qdrant_failure_returns_503(client):
    """If index_concept raises, endpoint returns 503 with concept_id."""
    with patch("lore.selfhosted.api.index_concept") as mock_idx:
        mock_idx.side_effect = Exception("Qdrant is down")
        response = client.post("/v1/concepts", json=VALID_BODY)

    assert response.status_code == 503
    data = response.json()
    assert "concept_id" in data
    assert "Qdrant unavailable" in data["error"]
    # The concept_id must be a valid UUID even on failure.
    uuid.UUID(data["concept_id"])


def test_submit_concept_with_links_inserts_links(client, conn):
    """Inline links in the submit body are persisted in SQLite."""
    # First create the target concept so the FK constraint is satisfied.
    target = _make_concept()
    insert_concept(conn, target)

    body = {
        **VALID_BODY,
        "links": [{"to_id": target.concept_id, "rel": "uses", "label": "depends on"}],
    }
    with patch("lore.selfhosted.api.index_concept"):
        response = client.post("/v1/concepts", json=body)

    assert response.status_code == 201
    from_id = response.json()["concept_id"]

    from lore.selfhosted.db import get_links_for_concept
    links = get_links_for_concept(conn, from_id)
    assert len(links) == 1
    assert links[0].rel == "uses"


def test_submit_concept_invalid_inline_rel_is_skipped(client):
    """Links with invalid rel values are silently skipped, not a hard failure."""
    body = {
        **VALID_BODY,
        "links": [{"to_id": str(uuid.uuid4()), "rel": "owns", "label": None}],
    }
    with patch("lore.selfhosted.api.index_concept"):
        response = client.post("/v1/concepts", json=body)

    # Submission must succeed; the bad link is skipped.
    assert response.status_code == 201


# ---------------------------------------------------------------------------
# Get concept
# ---------------------------------------------------------------------------

def test_get_concept_returns_concept(client, conn):
    """GET /v1/concepts/{id} returns the concept with links array."""
    concept = _make_concept()
    insert_concept(conn, concept)

    response = client.get(f"/v1/concepts/{concept.concept_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["concept_id"] == concept.concept_id
    assert data["name"] == concept.name
    assert "links" in data
    assert isinstance(data["links"], list)


def test_get_concept_returns_serialised_links(client, conn):
    """GET /v1/concepts/{id} serialises links with all expected fields."""
    from lore.selfhosted.db import insert_link
    from lore.mcp.models import Link
    concept_a = _make_concept()
    concept_b = _make_concept(concept_id=str(uuid.uuid4()), name="Target")
    insert_concept(conn, concept_a)
    insert_concept(conn, concept_b)
    link = Link(link_id="", from_id=concept_a.concept_id, to_id=concept_b.concept_id,
                rel="uses", label="A uses B")
    insert_link(conn, link)

    response = client.get(f"/v1/concepts/{concept_a.concept_id}")
    assert response.status_code == 200
    links = response.json()["links"]
    assert len(links) == 1
    assert links[0]["from_id"] == concept_a.concept_id
    assert links[0]["to_id"] == concept_b.concept_id
    assert links[0]["rel"] == "uses"
    assert links[0]["label"] == "A uses B"
    assert "link_id" in links[0]


def test_get_concept_not_found_returns_404(client):
    """Unknown concept_id returns 404."""
    response = client.get(f"/v1/concepts/{uuid.uuid4()}")
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "not found"
    assert "concept_id" in data


# ---------------------------------------------------------------------------
# Search concepts
# ---------------------------------------------------------------------------

def test_search_concepts_returns_results(client, conn):
    """POST /v1/concepts/search returns results with links attached."""
    concept = _make_concept()
    insert_concept(conn, concept)

    with patch("lore.selfhosted.api.search_concepts") as mock_search:
        mock_search.return_value = [concept]
        response = client.post(
            "/v1/concepts/search",
            json={"problem": "concurrent database writes", "limit": 5},
        )

    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) == 1
    assert data["results"][0]["concept_id"] == concept.concept_id
    assert "links" in data["results"][0]


def test_search_concepts_empty_returns_200(client):
    """Empty results return {"results": []} with HTTP 200."""
    with patch("lore.selfhosted.api.search_concepts") as mock_search:
        mock_search.return_value = []
        response = client.post(
            "/v1/concepts/search",
            json={"problem": "something that matches nothing"},
        )

    assert response.status_code == 200
    assert response.json() == {"results": []}


def test_search_concepts_logs_session_usage(client, conn):
    """X-Session-ID header triggers session_usage row in SQLite."""
    concept = _make_concept()
    insert_concept(conn, concept)

    session_id = "test-session-abc"
    with patch("lore.selfhosted.api.search_concepts") as mock_search:
        mock_search.return_value = [concept]
        response = client.post(
            "/v1/concepts/search",
            json={"problem": "test query"},
            headers={"X-Session-ID": session_id},
        )

    assert response.status_code == 200

    # Verify a session_usage row was written.
    row = conn.execute(
        "SELECT * FROM session_usage WHERE session_id = ? AND concept_id = ?",
        (session_id, concept.concept_id),
    ).fetchone()
    assert row is not None


# ---------------------------------------------------------------------------
# Link concepts
# ---------------------------------------------------------------------------

def test_link_concepts_returns_201(client, conn):
    """POST /v1/links with two existing concepts returns 201 and link_id."""
    c1 = _make_concept()
    c2 = _make_concept()
    insert_concept(conn, c1)
    insert_concept(conn, c2)

    response = client.post(
        "/v1/links",
        json={"from_id": c1.concept_id, "to_id": c2.concept_id, "rel": "uses"},
    )
    assert response.status_code == 201
    data = response.json()
    assert "link_id" in data
    uuid.UUID(data["link_id"])


def test_link_concepts_invalid_rel_returns_422(client, conn):
    """rel='owns' is not in the allowed set — returns 422."""
    c1 = _make_concept()
    c2 = _make_concept()
    insert_concept(conn, c1)
    insert_concept(conn, c2)

    response = client.post(
        "/v1/links",
        json={"from_id": c1.concept_id, "to_id": c2.concept_id, "rel": "owns"},
    )
    assert response.status_code == 422


def test_link_concepts_missing_from_returns_404(client, conn):
    """from_id pointing to a non-existent concept returns 404."""
    c2 = _make_concept()
    insert_concept(conn, c2)

    response = client.post(
        "/v1/links",
        json={
            "from_id": str(uuid.uuid4()),
            "to_id": c2.concept_id,
            "rel": "uses",
        },
    )
    assert response.status_code == 404


def test_link_concepts_missing_to_returns_404(client, conn):
    """to_id pointing to a non-existent concept returns 404."""
    c1 = _make_concept()
    insert_concept(conn, c1)

    response = client.post(
        "/v1/links",
        json={
            "from_id": c1.concept_id,
            "to_id": str(uuid.uuid4()),
            "rel": "uses",
        },
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Rate concept
# ---------------------------------------------------------------------------

def test_rate_concept_returns_avg(client, conn):
    """Rate a concept; response includes avg_rating and time_saved_avg_hours."""
    concept = _make_concept()
    insert_concept(conn, concept)

    response = client.post(
        f"/v1/concepts/{concept.concept_id}/rate",
        json={"outcome": 4, "hours_saved": 2.5, "notes": "Very helpful"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "avg_rating" in data
    assert data["avg_rating"] == pytest.approx(4.0)
    assert data["time_saved_avg_hours"] == pytest.approx(2.5)


def test_rate_concept_invalid_outcome_returns_422(client, conn):
    """outcome=6 is out of range — returns 422."""
    concept = _make_concept()
    insert_concept(conn, concept)

    response = client.post(
        f"/v1/concepts/{concept.concept_id}/rate",
        json={"outcome": 6},
    )
    assert response.status_code == 422


def test_rate_concept_invalid_outcome_zero_returns_422(client, conn):
    """outcome=0 is out of range — returns 422."""
    concept = _make_concept()
    insert_concept(conn, concept)

    response = client.post(
        f"/v1/concepts/{concept.concept_id}/rate",
        json={"outcome": 0},
    )
    assert response.status_code == 422


def test_rate_concept_negative_hours_returns_422(client, conn):
    """hours_saved=-1 is invalid — returns 422."""
    concept = _make_concept()
    insert_concept(conn, concept)

    response = client.post(
        f"/v1/concepts/{concept.concept_id}/rate",
        json={"outcome": 3, "hours_saved": -1.0},
    )
    assert response.status_code == 422


def test_rate_concept_not_found_returns_404(client):
    """Rating a non-existent concept returns 404."""
    response = client.post(
        f"/v1/concepts/{uuid.uuid4()}/rate",
        json={"outcome": 3},
    )
    assert response.status_code == 404


def test_rate_concept_multiple_ratings_avg(client, conn):
    """Multiple ratings produce a correct rolling average."""
    concept = _make_concept()
    insert_concept(conn, concept)

    client.post(f"/v1/concepts/{concept.concept_id}/rate", json={"outcome": 2})
    response = client.post(
        f"/v1/concepts/{concept.concept_id}/rate", json={"outcome": 4}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["avg_rating"] == pytest.approx(3.0)
