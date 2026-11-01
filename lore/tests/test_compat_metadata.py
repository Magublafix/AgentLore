"""Tests for reproducer/compatibility metadata (LORE-046).

Covers the shared model/validation (``lore.core.compat``), the SQLite
migration, and submit -> get round trips on every backend: gists, selfhosted
SQLite (storage + HTTP API), and the gist_qdrant semantic index.  Legacy
concepts (no metadata) must load as ``unknown``, never as supported.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from lore.core.compat import (
    NONE_AVAILABLE,
    MetadataValidationError,
    load_compatibility,
    load_reproducer,
    normalize_compatibility,
    normalize_concept_metadata,
    normalize_reproducer,
    unknown_compatibility,
    unknown_reproducer,
    validate_specifier,
)
from lore.mcp.backends import gists as gists_backend
from lore.mcp.backends.gists_client import GistData
from lore.mcp.models import Concept
from lore.selfhosted.db import get_concept as db_get_concept
from lore.selfhosted.db import init_db, insert_concept
from lore.server.api import app
from lore.server.storage.gist_qdrant import GistQdrantBackend, _init_collection
from lore.server.storage.sqlite_qdrant import COLLECTION_NAME, SqliteQdrantBackend

COMPAT = {
    "language": "Python",
    "runtime_version": "<4, >=3.11",
    "libraries": [{"name": "fastapi", "specifier": ">=0.110,<1"}, {"name": "httpx"}],
    "platforms": ["Linux", "macOS"],
    "assumptions": ["Qdrant sidecar reachable"],
}


# ---------------------------------------------------------------------------
# Shared model / validation
# ---------------------------------------------------------------------------


class TestReproducer:
    def test_none_is_unknown(self):
        assert normalize_reproducer(None) == unknown_reproducer()
        assert normalize_reproducer("   ") == unknown_reproducer()

    def test_text_provided(self):
        assert normalize_reproducer(" print(1) ") == {"status": "provided", "text": "print(1)"}

    def test_none_available_marker(self):
        assert normalize_reproducer(NONE_AVAILABLE) == {"status": "none_available", "text": None}

    def test_idempotent(self):
        for v in (None, "x", NONE_AVAILABLE):
            once = normalize_reproducer(v)
            assert normalize_reproducer(once) == once

    def test_too_long_rejected(self):
        with pytest.raises(MetadataValidationError, match="reproducer"):
            normalize_reproducer("x" * 20_001)

    def test_wrong_type_rejected(self):
        with pytest.raises(MetadataValidationError):
            normalize_reproducer(5)

    def test_bad_dict_status_rejected(self):
        with pytest.raises(MetadataValidationError, match="status"):
            normalize_reproducer({"status": "supported", "text": "x"})

    def test_load_is_lenient(self):
        assert load_reproducer(None) == unknown_reproducer()
        assert load_reproducer("not json") == unknown_reproducer()
        assert load_reproducer({"status": "bogus"}) == unknown_reproducer()
        assert load_reproducer(json.dumps({"status": "provided", "text": "a"}))["text"] == "a"


class TestCompatibility:
    def test_none_and_empty_are_unknown(self):
        assert normalize_compatibility(None) == unknown_compatibility()
        assert normalize_compatibility({})["status"] == "unknown"

    def test_full_declared_and_normalized(self):
        c = normalize_compatibility(COMPAT)
        assert c["status"] == "declared"
        assert c["language"] == "python"
        assert c["runtime_version"] == "<4,>=3.11"
        assert c["platforms"] == ["linux", "macos"]
        assert {"name": "fastapi", "specifier": "<1,>=0.110"} in c["libraries"]
        assert {"name": "httpx", "specifier": ""} in c["libraries"]

    def test_partial_is_not_declared(self):
        c = normalize_compatibility({"language": "python"})
        assert c["status"] == "partial"
        assert c["runtime_version"] is None and c["platforms"] == []

    def test_idempotent(self):
        once = normalize_compatibility(COMPAT)
        assert normalize_compatibility(once) == once

    def test_mapping_form_for_libraries(self):
        c = normalize_compatibility({"libraries": {"numpy": ">=1.26"}})
        assert c["libraries"] == [{"name": "numpy", "specifier": ">=1.26"}]
        assert c["status"] == "partial"

    def test_string_assumption_and_platform(self):
        c = normalize_compatibility({"platforms": "Linux", "assumptions": "needs docker"})
        assert c["platforms"] == ["linux"] and c["assumptions"] == ["needs docker"]

    @pytest.mark.parametrize(
        "bad",
        [
            {"runtime_version": ">=abc"},
            {"libraries": [{"name": "x", "specifier": "latest"}]},
            {"libraries": {"x": "1.0 || 2.0"}},
        ],
    )
    def test_invalid_specifier_rejected_with_clear_error(self, bad):
        with pytest.raises(MetadataValidationError, match="invalid version specifier"):
            normalize_compatibility(bad)

    @pytest.mark.parametrize(
        "bad",
        [
            "python",
            {"surprise": 1},
            {"libraries": "fastapi"},
            {"libraries": [{"specifier": ">=1"}]},
            {"libraries": [{"name": "a"}, {"name": "A"}]},
            {"libraries": [{"name": "a", "extra": 1}]},
            {"libraries": [5]},
            {"language": 3},
            {"platforms": [1]},
            {"platforms": 1},
            {"runtime_version": 3},
            {"assumptions": ["x" * 501]},
            {"libraries": [{"name": f"l{i}"} for i in range(51)]},
        ],
    )
    def test_malformed_rejected(self, bad):
        with pytest.raises(MetadataValidationError):
            normalize_compatibility(bad)

    def test_error_is_value_error(self):
        assert issubclass(MetadataValidationError, ValueError)

    def test_load_invalid_falls_back_to_unknown(self):
        assert load_compatibility({"runtime_version": ">=abc"}) == unknown_compatibility()
        assert load_compatibility("garbage") == unknown_compatibility()
        assert load_compatibility(None) == unknown_compatibility()

    def test_validate_specifier(self):
        assert validate_specifier("") == ""
        assert validate_specifier(">=1,<2") == "<2,>=1"
        with pytest.raises(MetadataValidationError):
            validate_specifier(1)

    def test_normalize_concept_metadata(self):
        r, c = normalize_concept_metadata("repro", COMPAT)
        assert r["status"] == "provided" and c["status"] == "declared"


# ---------------------------------------------------------------------------
# SQLite layer + migration
# ---------------------------------------------------------------------------


def _concept(**kw) -> Concept:
    base = dict(
        concept_id="c1", name="N", type="pattern", content="body",
        language="python", when_to_use="when", dont_use_when=None,
    )
    base.update(kw)
    return Concept(**base)


class TestSqliteLayer:
    def test_defaults_are_unknown(self):
        c = _concept()
        assert c.reproducer == unknown_reproducer()
        assert c.compatibility == unknown_compatibility()

    def test_roundtrip(self):
        conn = init_db(":memory:")
        r, c = normalize_concept_metadata("repro", COMPAT)
        insert_concept(conn, _concept(reproducer=r, compatibility=c))
        got = db_get_concept(conn, "c1")
        assert got.reproducer == r and got.compatibility == c

    def test_migration_preserves_legacy_rows_and_is_idempotent(self, tmp_path):
        path = str(tmp_path / "legacy.db")
        legacy = sqlite3.connect(path)
        legacy.executescript(
            """
            CREATE TABLE concepts (
                concept_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('project','pattern','tool','testing','architecture')),
                content TEXT NOT NULL, language TEXT, when_to_use TEXT NOT NULL,
                dont_use_when TEXT, tags TEXT, source_url TEXT, author TEXT,
                avg_rating REAL DEFAULT 0, usage_count INTEGER DEFAULT 0,
                time_saved_avg_hours REAL, created_at TEXT, embedding BLOB);
            INSERT INTO concepts (concept_id,name,type,content,when_to_use,tags,avg_rating)
              VALUES ('old','Old','tool','legacy body','legacy when','["a"]',4.5);
            """
        )
        legacy.commit()
        legacy.close()

        for _ in range(2):  # second pass proves idempotency
            conn = init_db(path)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(concepts)")}
            assert {"reproducer", "compatibility"} <= cols
            got = db_get_concept(conn, "old")
            assert got.content == "legacy body" and got.avg_rating == 4.5
            assert got.tags == ["a"]
            assert got.reproducer == unknown_reproducer()
            assert got.compatibility == unknown_compatibility()
            conn.close()

    def test_corrupt_stored_json_loads_unknown(self):
        conn = init_db(":memory:")
        insert_concept(conn, _concept())
        conn.execute("UPDATE concepts SET reproducer='{bad', compatibility='[1]'")
        got = db_get_concept(conn, "c1")
        assert got.reproducer == unknown_reproducer()
        assert got.compatibility == unknown_compatibility()


# ---------------------------------------------------------------------------
# Selfhosted storage backend + HTTP API
# ---------------------------------------------------------------------------


def _vec(seed: float = 0.1) -> list[float]:
    return [seed] * 384


@pytest.fixture
def sqlite_backend():
    backend = SqliteQdrantBackend.__new__(SqliteQdrantBackend)
    backend._conn = init_db(":memory:")
    backend._qdrant = QdrantClient(":memory:")
    model = MagicMock()
    model.embed.return_value = _vec()
    backend._model = model
    from lore.selfhosted.vector_store import init_qdrant_collection

    init_qdrant_collection(backend._qdrant, collection_name=COLLECTION_NAME)
    return backend


@pytest.fixture
def gist_backend():
    backend = GistQdrantBackend.__new__(GistQdrantBackend)
    backend._qdrant = QdrantClient(":memory:")
    model = MagicMock()
    model.embed.return_value = _vec()
    backend._model = model
    _init_collection(backend._qdrant)
    return backend


def _sq_payload(**kw):
    base = {
        "name": "WAL", "type": "pattern", "content": "body", "language": "python",
        "when_to_use": "concurrent sqlite writes", "tags": ["sqlite"],
    }
    base.update(kw)
    return base


class TestSqliteQdrantBackend:
    def test_submit_then_get_identical_metadata(self, sqlite_backend):
        res = sqlite_backend.upsert_concept(
            _sq_payload(reproducer="run x", compatibility=COMPAT)
        )
        got = sqlite_backend.get_concept(res["concept_id"])
        assert got["reproducer"] == normalize_reproducer("run x")
        assert got["compatibility"] == normalize_compatibility(COMPAT)

    def test_search_results_carry_metadata(self, sqlite_backend):
        sqlite_backend.upsert_concept(_sq_payload(reproducer=NONE_AVAILABLE, compatibility=COMPAT))
        results = sqlite_backend.search_concepts(_vec(), 3, None, None, 0.0)
        assert results[0]["reproducer"]["status"] == "none_available"
        assert results[0]["compatibility"]["status"] == "declared"

    def test_missing_metadata_is_unknown(self, sqlite_backend):
        res = sqlite_backend.upsert_concept(_sq_payload())
        got = sqlite_backend.get_concept(res["concept_id"])
        assert got["reproducer"] == unknown_reproducer()
        assert got["compatibility"] == unknown_compatibility()

    def test_partial_metadata_never_declared(self, sqlite_backend):
        res = sqlite_backend.upsert_concept(_sq_payload(compatibility={"language": "python"}))
        got = sqlite_backend.get_concept(res["concept_id"])
        assert got["compatibility"]["status"] == "partial"

    def test_legacy_row_loads_unknown(self, sqlite_backend):
        sqlite_backend._conn.execute(
            "INSERT INTO concepts (concept_id,name,type,content,when_to_use) "
            "VALUES ('legacy','L','tool','c','w')"
        )
        got = sqlite_backend.get_concept("legacy")
        assert got["reproducer"] == unknown_reproducer()
        assert got["compatibility"] == unknown_compatibility()


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI):
    yield


@pytest.fixture
def api_client(sqlite_backend):
    sqlite_backend._qdrant = MagicMock()
    no_dup = MagicMock()
    no_dup.points = []
    sqlite_backend._qdrant.query_points.return_value = no_dup
    with patch("lore.server.api.lifespan", _noop_lifespan):
        with TestClient(app) as c:
            app.state.storage = sqlite_backend
            app.state.model = sqlite_backend._model
            app.state.backend_name = "sqlite_qdrant"
            yield c


class TestHttpApi:
    BODY = {
        "name": "WAL", "type": "pattern", "content": "body",
        "when_to_use": "concurrent sqlite writes", "tags": [],
    }

    def test_submit_get_roundtrip(self, api_client):
        r = api_client.post(
            "/v1/concepts",
            json={**self.BODY, "reproducer": "do it", "compatibility": COMPAT},
        )
        assert r.status_code == 201, r.text
        got = api_client.get(f"/v1/concepts/{r.json()['concept_id']}").json()
        assert got["reproducer"] == normalize_reproducer("do it")
        assert got["compatibility"] == normalize_compatibility(COMPAT)

    def test_fields_optional_default_unknown(self, api_client):
        r = api_client.post("/v1/concepts", json=self.BODY)
        assert r.status_code == 201
        got = api_client.get(f"/v1/concepts/{r.json()['concept_id']}").json()
        assert got["reproducer"] == unknown_reproducer()
        assert got["compatibility"] == unknown_compatibility()

    def test_invalid_specifier_returns_422_with_message(self, api_client):
        r = api_client.post(
            "/v1/concepts",
            json={**self.BODY, "compatibility": {"runtime_version": ">=abc"}},
        )
        assert r.status_code == 422
        assert "invalid version specifier" in r.text

    def test_non_dict_compatibility_422(self, api_client):
        r = api_client.post("/v1/concepts", json={**self.BODY, "compatibility": "py"})
        assert r.status_code == 422

    def test_oversize_reproducer_422(self, api_client):
        r = api_client.post("/v1/concepts", json={**self.BODY, "reproducer": "x" * 20_001})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# gist_qdrant semantic index payload
# ---------------------------------------------------------------------------


class TestGistQdrantIndex:
    def _payload(self, **kw):
        base = {
            "gist_id": "g1", "name": "WAL", "type": "pattern", "language": "python",
            "tags": [], "when_to_use": "concurrent writes", "gist_updated_at": "t1",
        }
        base.update(kw)
        return base

    def test_roundtrip(self, gist_backend):
        r, c = normalize_concept_metadata("repro", COMPAT)
        gist_backend.upsert_concept(self._payload(reproducer=r, compatibility=c))
        got = gist_backend.get_concept("g1")
        assert got["reproducer"] == r and got["compatibility"] == c
        hit = gist_backend.search_concepts(_vec(), 3, None, None, 0.0)[0]
        assert hit["compatibility"] == c

    def test_missing_is_unknown(self, gist_backend):
        gist_backend.upsert_concept(self._payload())
        got = gist_backend.get_concept("g1")
        assert got["reproducer"] == unknown_reproducer()
        assert got["compatibility"] == unknown_compatibility()

    def test_legacy_point_without_fields_is_unknown(self, gist_backend):
        from qdrant_client.http import models as qm

        from lore.server.storage.gist_qdrant import COLLECTION_NAME as GC
        from lore.server.storage.gist_qdrant import _gist_id_to_point_id

        gist_backend._qdrant.upsert(
            GC,
            [qm.PointStruct(
                id=_gist_id_to_point_id("old"), vector=_vec(),
                payload={"gist_id": "old", "name": "O", "type": "tool", "when_to_use": "w"},
            )],
        )
        got = gist_backend.get_concept("old")
        assert got["compatibility"] == unknown_compatibility()

    def test_http_upsert_validates(self, gist_backend):
        with patch("lore.server.api.lifespan", _noop_lifespan):
            with TestClient(app) as c:
                app.state.storage = gist_backend
                app.state.model = gist_backend._model
                app.state.backend_name = "gist_qdrant"
                body = {
                    "gist_id": "g9", "name": "N", "type": "pattern", "when_to_use": "w",
                    "gist_updated_at": "t", "force": True,
                }
                bad = c.post("/concepts", json={**body, "compatibility": {"runtime_version": "x"}},
                             headers={"Authorization": "Bearer k"})
                assert bad.status_code in (401, 403, 422)
                # Validation happens in the request model, independent of auth:
                from lore.server.api import ConceptUpsertRequest

                with pytest.raises(ValueError):
                    ConceptUpsertRequest(**body, compatibility={"runtime_version": "x"})
                ok = ConceptUpsertRequest(**body, compatibility=COMPAT, reproducer="r")
                assert ok.compatibility == normalize_compatibility(COMPAT)


# ---------------------------------------------------------------------------
# Gists backend (lore.json body)
# ---------------------------------------------------------------------------


class FakeGistsClient:
    """In-memory GistsClient substitute that stores what create_gist receives."""

    def __init__(self):
        self.gists: dict[str, tuple[dict, str]] = {}

    def create_gist(self, files, description, public=True):
        gid = f"gist{len(self.gists) + 1}"
        self.gists[gid] = (dict(files), description)
        return gid

    def get_gist(self, gist_id):
        files, desc = self.gists[gist_id]
        return GistData(files=dict(files), description=desc)

    def list_comments(self, gist_id):
        return []


class TestGistsBackend:
    def _submit(self, client, **kw):
        return gists_backend.submit_concept(
            client, name="WAL", type="pattern", content="body",
            when_to_use="concurrent writes", tags=["sqlite"], **kw,
        )

    def test_roundtrip_identical_metadata(self):
        client = FakeGistsClient()
        res = self._submit(client, reproducer="run it", compatibility=COMPAT)
        got = gists_backend.get_concept(client, res["concept_id"])
        assert got["reproducer"] == normalize_reproducer("run it")
        assert got["compatibility"] == normalize_compatibility(COMPAT)

    def test_lore_json_carries_fields(self):
        client = FakeGistsClient()
        res = self._submit(client, reproducer=NONE_AVAILABLE, compatibility=COMPAT)
        lore = json.loads(client.gists[res["concept_id"]][0]["lore.json"])
        assert lore["reproducer"] == {"status": "none_available", "text": None}
        assert lore["compatibility"]["status"] == "declared"

    def test_omitted_stored_as_unknown(self):
        client = FakeGistsClient()
        res = self._submit(client)
        lore = json.loads(client.gists[res["concept_id"]][0]["lore.json"])
        assert lore["reproducer"] == unknown_reproducer()
        assert lore["compatibility"] == unknown_compatibility()

    def test_invalid_specifier_rejected_before_network(self):
        client = MagicMock()
        with pytest.raises(ValueError, match="invalid version specifier"):
            self._submit(client, compatibility={"libraries": {"x": ">>1"}})
        client.create_gist.assert_not_called()

    def test_legacy_gist_loads_unknown(self):
        client = FakeGistsClient()
        client.gists["old"] = (
            {
                "concept.md": "c",
                "lore.json": json.dumps(
                    {"schema_version": "1", "type": "tool", "when_to_use": "w", "tags": [], "links": []}
                ),
            },
            "[agentlore-concept] Old [a]",
        )
        got = gists_backend.get_concept(client, "old")
        assert got["reproducer"] == unknown_reproducer()
        assert got["compatibility"] == unknown_compatibility()


# ---------------------------------------------------------------------------
# Router / MCP server / watcher
# ---------------------------------------------------------------------------


def _resp(status, body):
    r = MagicMock()
    r.status_code = status
    r.is_error = status >= 400
    r.json.return_value = body
    return r


class TestRouterAndServer:
    def _router(self):
        from lore.mcp.router import BackendRouter

        return BackendRouter(backend="selfhosted", selfhosted_url="http://x")

    def test_selfhosted_payload_includes_fields_only_when_given(self):
        router = self._router()
        with patch.object(router, "_client") as cm:
            http = cm.return_value.__enter__.return_value
            http.post.return_value = _resp(201, {"concept_id": "1", "name": "n"})
            router.submit_concept("n", "pattern", "c", "w", [])
            assert "reproducer" not in http.post.call_args.kwargs["json"]
            router.submit_concept("n", "pattern", "c", "w", [], reproducer="r", compatibility=COMPAT)
            sent = http.post.call_args.kwargs["json"]
            assert sent["reproducer"] == "r" and sent["compatibility"] == COMPAT

    def test_router_rejects_invalid_before_http(self):
        router = self._router()
        with patch.object(router, "_client") as cm:
            with pytest.raises(ValueError, match="invalid version specifier"):
                router.submit_concept(
                    "n", "pattern", "c", "w", [], compatibility={"runtime_version": "??"}
                )
            cm.assert_not_called()

    def test_router_maps_fastapi_422_detail(self):
        router = self._router()
        with patch.object(router, "_client") as cm:
            http = cm.return_value.__enter__.return_value
            http.post.return_value = _resp(422, {"detail": [{"msg": "bad"}]})
            with pytest.raises(ValueError, match="invalid field"):
                router.submit_concept("n", "pattern", "c", "w", [])

    def test_router_gists_passes_fields(self):
        from lore.mcp.router import BackendRouter

        router = BackendRouter(backend="gists", selfhosted_url="http://x")
        with patch("lore.mcp.router.GistsClient"), patch(
            "lore.mcp.router.gists_backend.submit_concept"
        ) as sc:
            sc.return_value = {"concept_id": "g"}
            router.submit_concept("n", "pattern", "c", "w", [], reproducer="r", compatibility=COMPAT)
            assert sc.call_args.kwargs["reproducer"] == "r"
            assert sc.call_args.kwargs["compatibility"] == COMPAT

    def test_mcp_tool_validates_locally_and_forwards(self, monkeypatch):
        monkeypatch.delenv("LORE_READ_ONLY", raising=False)
        import lore.mcp.server as srv

        fn = getattr(srv.submit_concept, "fn", srv.submit_concept)
        with pytest.raises(ValueError, match="invalid version specifier"):
            fn("n", "pattern", "c", "w", [], compatibility={"runtime_version": "nope"})
        with patch.object(srv._router, "submit_concept", return_value={"concept_id": "1"}) as sc:
            fn("n", "pattern", "c", "w", [], reproducer="r", compatibility=COMPAT)
            assert sc.call_args.kwargs["reproducer"] == "r"
            assert sc.call_args.kwargs["compatibility"] == COMPAT

    def test_mcp_tool_schema_params_optional(self):
        import asyncio

        from fastmcp import Client

        import lore.mcp.server as srv

        async def _schema():
            async with Client(srv.mcp) as c:
                tools = {t.name: t for t in await c.list_tools()}
                return tools["submit_concept"].inputSchema

        schema = asyncio.run(_schema())
        assert "reproducer" in schema["properties"] and "compatibility" in schema["properties"]
        assert "reproducer" not in schema["required"]
        assert "compatibility" not in schema["required"]

    def test_watcher_payload_metadata(self):
        from lore.server.watcher import _extract_payload

        def gist(meta):
            return {
                "id": "g", "description": "[agentlore-concept] N [a]", "updated_at": "t",
                "files": {"lore.json": {"content": json.dumps({"when_to_use": "w", **meta})}},
            }

        r, c = normalize_concept_metadata("rep", COMPAT)
        p = _extract_payload(gist({"reproducer": r, "compatibility": c}))
        assert p["reproducer"] == r and p["compatibility"] == c
        legacy = _extract_payload(gist({}))
        assert legacy["reproducer"] == unknown_reproducer()
        assert legacy["compatibility"] == unknown_compatibility()
        bad = _extract_payload(gist({"compatibility": {"runtime_version": "zz"}}))
        assert bad["compatibility"] == unknown_compatibility()

    def test_seed_concepts_are_unknown(self):
        from lore.mcp.backends import seed

        res = seed.search_concepts("sqlite", None, None, 3, 0.0)
        for item in res["results"]:
            assert item["compatibility"] == unknown_compatibility()
            assert item["reproducer"] == unknown_reproducer()
