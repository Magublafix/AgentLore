"""Compatibility-aware search ranking (LORE-048).

Covers the shared pure ranking function, environment resolution, every
backend (gists, seed, selfhosted sqlite_qdrant, gist_qdrant), the router
(selfhosted forwarding, semantic forwarding, old-server backfill) and an
integration-style test of the unified server's filtering/ordering.

Everything is in-process: real storage backends use in-memory Qdrant/SQLite
and the embedding model is faked.  No Docker is required, so none of these
are skipped.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from lore.core.environment import Environment
from lore.core.ranking import (
    annotate_compatibility,
    candidate_limit,
    coerce_environment,
    environment_to_dict,
    rank_by_compatibility,
    resolve_environment,
)
from lore.mcp.backends import gists as gists_backend
from lore.mcp.backends import seed as seed_backend
from lore.mcp.backends.gists_client import GistData, GistSummary
from lore.mcp.router import BackendRouter

PY312 = Environment(language="python", runtime_version="3.12.1", libraries={"fastapi": "0.110.0"}, platform="linux")
OK = {"status": "declared", "language": "python", "runtime_version": ">=3.11", "libraries": [], "platforms": ["linux"], "assumptions": []}
BAD = {"status": "declared", "language": "python", "runtime_version": "<3.10", "libraries": [], "platforms": ["linux"], "assumptions": []}


def _r(name, compat=None, rating=None, links=None):
    return {"concept_id": name, "name": name, "avg_rating": rating, "compatibility": compat, "links": links or []}


def _names(results):
    return [r["name"] for r in results]


def _status(r):
    return r["compatibility_check"]["status"]


# ---------------------------------------------------------------------------
# Pure ranking function
# ---------------------------------------------------------------------------


class TestRankByCompatibility:
    def test_bands_compatible_unknown_incompatible(self):
        res = rank_by_compatibility([_r("bad", BAD), _r("unk"), _r("ok", OK)], PY312)
        assert _names(res) == ["ok", "unk", "bad"]
        assert [_status(r) for r in res] == ["compatible", "unknown", "incompatible"]
        assert all(r["compatibility_check"]["reason"] for r in res)

    def test_rating_cannot_promote_incompatible(self):
        res = rank_by_compatibility(
            [_r("bad5", BAD, rating=5.0), _r("unk", rating=2.0), _r("ok", OK, rating=2.0)], PY312
        )
        assert _names(res) == ["ok", "unk", "bad5"]

    def test_stable_within_band(self):
        # incoming order is the backend's rating/relevance order; it must be preserved per band
        inp = [_r("b1", BAD), _r("o1", OK), _r("u1"), _r("o2", OK), _r("b2", BAD), _r("u2"), _r("o3", OK)]
        assert _names(rank_by_compatibility(inp, PY312)) == ["o1", "o2", "o3", "u1", "u2", "b1", "b2"]

    def test_exclude_incompatible(self):
        res = rank_by_compatibility([_r("bad", BAD), _r("ok", OK)], PY312, include_incompatible=False)
        assert _names(res) == ["ok"]

    def test_limit_applies_after_ranking(self):
        res = rank_by_compatibility([_r("bad", BAD), _r("u"), _r("ok", OK)], PY312, limit=1)
        assert _names(res) == ["ok"]

    def test_no_environment_is_all_unknown_and_order_unchanged(self):
        for env in (None, Environment()):
            res = rank_by_compatibility([_r("bad", BAD), _r("ok", OK), _r("u")], env)
            assert _names(res) == ["bad", "ok", "u"]
            assert {_status(r) for r in res} == {"unknown"}

    def test_legacy_and_malformed_metadata_never_compatible(self):
        res = rank_by_compatibility([_r("a", None), _r("b", "garbage"), _r("c", {"status": "unknown"})], PY312)
        assert {_status(r) for r in res} == {"unknown"}

    def test_links_carry_status(self):
        links = [{"gist_id": "x", "compatibility": OK}, {"gist_id": "y", "compatibility": BAD},
                 {"gist_id": "z", "status": "unavailable"}]
        (res,) = rank_by_compatibility([_r("a", OK, links=links)], PY312)
        assert [_status(l) for l in res["links"]] == ["compatible", "incompatible", "unknown"]

    def test_annotate_in_place_and_empty(self):
        c = _r("a", OK)
        assert annotate_compatibility(c, PY312) is c and _status(c) == "compatible"
        assert rank_by_compatibility([], PY312) == []

    def test_candidate_limit(self):
        assert candidate_limit(3, PY312) == 12
        assert candidate_limit(3, Environment()) == 3
        assert candidate_limit(3, None) == 3


class TestEnvironmentResolution:
    def test_coerce_dict_normalizes(self):
        env = coerce_environment({"language": "Python3", "libraries": {"FastAPI": "0.1"}, "platform": "Darwin"})
        assert env.language == "python" and env.platform == "macos" and "fastapi" in env.libraries
        assert coerce_environment(None) is None
        assert coerce_environment(environment_to_dict(PY312)).libraries == PY312.libraries

    @pytest.mark.parametrize("bad", ["x", [1], {"nope": 1}, {"language": 3}, {"libraries": ["a"]}, {"libraries": {"a": 1}}])
    def test_coerce_rejects_malformed(self, bad):
        with pytest.raises(ValueError):
            coerce_environment(bad)

    def test_precedence_explicit_over_project_dir(self, tmp_path):
        (tmp_path / "package.json").write_text('{"dependencies": {"left-pad": "1.3.0"}}')
        env = resolve_environment({"language": "python"}, tmp_path)
        assert env.language == "python" and not env.libraries

    def test_project_dir_detected(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("requests==2.31.0\n")
        assert resolve_environment(None, tmp_path).libraries["requests"] == "2.31.0"

    def test_cwd_detection_is_files_only_and_can_be_disabled(self, tmp_path, monkeypatch):
        (tmp_path / "requirements.txt").write_text("requests==2.31.0\n")
        monkeypatch.chdir(tmp_path)
        env = resolve_environment()
        assert env.libraries == {"requests": "2.31.0"} and env.runtime_version is None  # no interpreter leak
        monkeypatch.setenv("LORE_COMPAT_AUTODETECT", "0")
        assert resolve_environment() == Environment()

    def test_detection_failure_yields_empty_env(self, monkeypatch):
        monkeypatch.setattr("lore.core.ranking.detect_environment", MagicMock(side_effect=RuntimeError))
        assert resolve_environment(None, "/nonexistent") == Environment()


# ---------------------------------------------------------------------------
# Gists backend
# ---------------------------------------------------------------------------


def _gist(name, compat=None, links=None):
    lore = {"schema_version": "1", "type": "pattern", "language": "python", "when_to_use": "w",
            "tags": [], "links": links or [], "compatibility": compat}
    return GistData(files={"concept.md": "# c", "lore.json": json.dumps(lore)},
                    description=f"[agentlore-concept] {name} []")


class TestGistsBackend:
    def _client(self, gists: dict):
        client = MagicMock()
        client.search_gists.return_value = [GistSummary(gist_id=g, description=f"[agentlore-concept] {g} []") for g in gists]
        client.get_gist.side_effect = lambda gid: gists[gid]
        client.list_comments.return_value = []
        return client

    def test_ranked_and_labelled(self):
        client = self._client({"bad": _gist("bad", BAD), "unk": _gist("unk"), "ok": _gist("ok", OK)})
        res = gists_backend.search_concepts(client, "x", environment=PY312)["results"]
        assert _names(res) == ["ok", "unk", "bad"]
        assert [_status(r) for r in res] == ["compatible", "unknown", "incompatible"]

    def test_overfetch_surfaces_compatible_beyond_limit(self):
        gists = {f"b{i}": _gist(f"b{i}", BAD) for i in range(3)}
        gists["ok"] = _gist("ok", OK)
        res = gists_backend.search_concepts(self._client(gists), "x", limit=1, environment=PY312)["results"]
        assert _names(res) == ["ok"]

    def test_default_environment_none_keeps_order_all_unknown(self):
        client = self._client({"bad": _gist("bad", BAD), "ok": _gist("ok", OK)})
        res = gists_backend.search_concepts(client, "x")["results"]
        assert {_status(r) for r in res} == {"unknown"}

    def test_exclude_incompatible_and_linked_status(self):
        links = [{"gist_id": "l1", "rel": "uses", "label": None}]
        gists = {"bad": _gist("bad", BAD), "ok": _gist("ok", OK, links=links), "l1": _gist("l1", BAD)}
        client = self._client({k: v for k, v in gists.items() if k != "l1"})
        client.get_gist.side_effect = lambda gid: gists[gid]
        res = gists_backend.search_concepts(client, "x", environment=PY312, include_incompatible=False)["results"]
        assert _names(res) == ["ok"]
        assert _status(res[0]["links"][0]) == "incompatible"


class TestSeedBackend:
    def test_seeds_are_unknown_with_status_on_links(self):
        res = seed_backend.search_concepts("REST CLI around a REST API", environment=PY312)["results"]
        assert res and {_status(r) for r in res} == {"unknown"}
        assert all("compatibility_check" in l for r in res for l in r["links"])


# ---------------------------------------------------------------------------
# Storage backends (real, in-memory) + unified server integration
# ---------------------------------------------------------------------------

DIM = 384


def _vec(angle_rank: int) -> list[float]:
    """Unit-ish vectors: smaller rank = closer to the query vector e0."""
    v = [0.0] * DIM
    v[0] = 1.0
    v[1 + angle_rank] = 0.2 * angle_rank
    return v


QUERY = _vec(0)


@pytest.fixture
def sqlite_backend():
    from lore.selfhosted.db import init_db
    from lore.selfhosted.vector_store import init_qdrant_collection
    from lore.server.storage.sqlite_qdrant import COLLECTION_NAME, SqliteQdrantBackend

    b = SqliteQdrantBackend.__new__(SqliteQdrantBackend)
    b._conn = init_db(":memory:")
    b._qdrant = QdrantClient(":memory:")
    b._model = MagicMock()
    init_qdrant_collection(b._qdrant, collection_name=COLLECTION_NAME)
    ranks = {}
    b._model.embed.side_effect = lambda text: _vec(next(r for n, r in ranks.items() if n in text))
    b.ranks = ranks
    return b


@pytest.fixture
def gist_backend():
    from lore.server.storage.gist_qdrant import GistQdrantBackend, _init_collection

    b = GistQdrantBackend.__new__(GistQdrantBackend)
    b._qdrant = QdrantClient(":memory:")
    b._model = MagicMock()
    _init_collection(b._qdrant)
    ranks = {}
    b._model.embed.side_effect = lambda text: _vec(next(r for n, r in ranks.items() if n in text))
    b.ranks = ranks
    return b


# name -> (similarity rank, compat); "bestmatch" is the closest hit but incompatible.
CORPUS = {"bestmatch": (1, BAD), "second": (2, None), "third": (3, OK), "fourth": (4, OK)}


def _fill_sqlite(b):
    for name, (rank, compat) in CORPUS.items():
        b.ranks[name] = rank
        b.upsert_concept({"name": name, "type": "pattern", "content": "c", "language": "python",
                          "when_to_use": f"w {name}", "tags": [], "compatibility": compat})


def _fill_gist(b):
    for name, (rank, compat) in CORPUS.items():
        b.ranks[name] = rank
        b.upsert_concept({"gist_id": name, "name": name, "type": "pattern", "language": "python",
                          "when_to_use": f"w {name}", "tags": [], "gist_updated_at": "t", "compatibility": compat})


class TestStorageBackendsThroughServer:
    """Integration-style: real FastAPI app + real storage backend + in-memory Qdrant."""

    def _client(self, backend, name):
        from lore.server.api import app

        @asynccontextmanager
        async def _noop(application):
            yield

        with patch("lore.server.api.lifespan", _noop):
            tc = TestClient(app, raise_server_exceptions=True)
        model = MagicMock()
        model.embed.return_value = QUERY
        app.state.storage, app.state.model = backend, model
        app.state.backend_name, app.state.key_store = name, None
        return tc

    def test_semantic_server_get_search_orders_and_filters(self, gist_backend):
        _fill_gist(gist_backend)
        tc = self._client(gist_backend, "gist_qdrant")

        plain = tc.get("/search", params={"q": "x", "k": 4}).json()["results"]
        assert _names(plain)[0] == "bestmatch" and {_status(r) for r in plain} == {"unknown"}  # backward compatible

        env = json.dumps(environment_to_dict(PY312))
        res = tc.get("/search", params={"q": "x", "k": 4, "environment": env}).json()["results"]
        assert _names(res) == ["third", "fourth", "second", "bestmatch"]  # best raw hit pushed last
        assert [_status(r) for r in res] == ["compatible", "compatible", "unknown", "incompatible"]
        assert all(r["compatibility_check"]["reason"] for r in res)

        # k=1 over-fetches so the top *compatible* result is returned, not the top raw hit
        one = tc.get("/search", params={"q": "x", "k": 1, "environment": env}).json()["results"]
        assert _names(one) == ["third"]

        no_inc = tc.get("/search", params={"q": "x", "k": 4, "environment": env, "include_incompatible": "false"}).json()["results"]
        assert "bestmatch" not in _names(no_inc) and len(no_inc) == 3

    def test_semantic_server_rejects_bad_environment(self, gist_backend):
        tc = self._client(gist_backend, "gist_qdrant")
        assert tc.get("/search", params={"q": "x", "environment": "{not json"}).status_code == 422
        assert tc.get("/search", params={"q": "x", "environment": '{"nope": 1}'}).status_code == 422

    def test_post_search_sqlite_backend(self, sqlite_backend):
        _fill_sqlite(sqlite_backend)
        tc = self._client(sqlite_backend, "sqlite_qdrant")
        body = {"problem": "x", "limit": 4, "min_rating": 0, "environment": environment_to_dict(PY312)}
        res = tc.post("/v1/concepts/search", json=body).json()["results"]
        assert _names(res) == ["third", "fourth", "second", "bestmatch"]
        res1 = tc.post("/v1/concepts/search", json={**body, "limit": 1}).json()["results"]
        assert _names(res1) == ["third"]
        res2 = tc.post("/v1/concepts/search", json={**body, "include_incompatible": False}).json()["results"]
        assert "bestmatch" not in _names(res2)
        legacy = tc.post("/v1/concepts/search", json={"problem": "x", "limit": 4, "min_rating": 0}).json()["results"]
        assert _names(legacy)[0] == "bestmatch" and {_status(r) for r in legacy} == {"unknown"}
        assert tc.post("/v1/concepts/search", json={"problem": "x", "environment": {"bogus": 1}}).status_code == 422

    def test_sqlite_links_carry_status(self, sqlite_backend):
        _fill_sqlite(sqlite_backend)
        ids = {c["name"]: c["concept_id"] for c in sqlite_backend.search_concepts(QUERY, 10, None, None, 0)}
        from lore.selfhosted.db import insert_link
        from lore.mcp.models import Link
        insert_link(sqlite_backend._conn, Link(link_id="l1", from_id=ids["third"], to_id=ids["bestmatch"], rel="uses", label=None))
        tc = self._client(sqlite_backend, "sqlite_qdrant")
        body = {"problem": "x", "limit": 4, "min_rating": 0, "environment": environment_to_dict(PY312)}
        third = next(r for r in tc.post("/v1/concepts/search", json=body).json()["results"] if r["name"] == "third")
        assert _status(third["links"][0]) == "incompatible"


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def _resp(body):
    m = MagicMock(spec=httpx.Response)
    m.status_code = 200
    m.is_error = False
    m.json.return_value = body
    return m


class TestRouter:
    def _selfhosted(self, body):
        client = MagicMock()
        client.__enter__.return_value = client
        client.post.return_value = _resp(body)
        return client

    def test_selfhosted_forwards_environment_and_flag(self, monkeypatch):
        monkeypatch.delenv("LORE_READ_ONLY", raising=False)
        r = BackendRouter(backend="selfhosted", selfhosted_url="http://x")
        client = self._selfhosted({"results": [{"name": "a", "compatibility_check": {"status": "unknown", "reason": "r"}}]})
        with patch.object(r, "_client", return_value=client):
            r.search_concepts("p", environment={"language": "python", "libraries": {"fastapi": "0.110.0"}}, include_incompatible=False)
        payload = client.post.call_args.kwargs["json"]
        assert payload["environment"]["language"] == "python" and payload["include_incompatible"] is False

    def test_old_server_response_is_annotated_locally(self, monkeypatch):
        monkeypatch.delenv("LORE_READ_ONLY", raising=False)
        r = BackendRouter(backend="selfhosted", selfhosted_url="http://x")
        client = self._selfhosted({"results": [_r("bad", BAD), _r("ok", OK), _r("u")]})
        with patch.object(r, "_client", return_value=client):
            res = r.search_concepts("p", environment=environment_to_dict(PY312))["results"]
        assert _names(res) == ["ok", "u", "bad"]

    def test_no_env_given_sends_no_environment(self, monkeypatch, tmp_path):
        monkeypatch.delenv("LORE_READ_ONLY", raising=False)
        monkeypatch.setenv("LORE_COMPAT_AUTODETECT", "0")
        r = BackendRouter(backend="selfhosted", selfhosted_url="http://x")
        client = self._selfhosted({"results": []})
        with patch.object(r, "_client", return_value=client):
            r.search_concepts("p")
        assert "environment" not in client.post.call_args.kwargs["json"]

    def test_invalid_environment_raises_value_error(self, monkeypatch):
        monkeypatch.delenv("LORE_READ_ONLY", raising=False)
        r = BackendRouter(backend="selfhosted", selfhosted_url="http://x")
        with pytest.raises(ValueError):
            r.search_concepts("p", environment={"bogus": 1})

    def test_semantic_call_params_and_gists_fallback_ranked(self, monkeypatch):
        monkeypatch.delenv("LORE_READ_ONLY", raising=False)
        monkeypatch.setenv("LORE_SEMANTIC_URL", "http://sem.invalid")
        seen = {}

        class FakeClient:
            def __init__(self, **kw): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def get(self, path, params=None):
                seen.update(params)
                m = MagicMock(); m.raise_for_status.return_value = None
                m.json.return_value = {"results": [{"name": "a", "compatibility_check": {"status": "unknown", "reason": "r"}}]}
                return m

        with patch("lore.mcp.router.httpx.Client", FakeClient):
            r = BackendRouter(backend="gists", selfhosted_url="http://unused")
            r.search_concepts("p", environment={"language": "python"}, include_incompatible=False)
        assert json.loads(seen["environment"])["language"] == "python" and seen["include_incompatible"] == "false"

        # semantic down -> gists backend, which ranks with the same environment
        gclient = TestGistsBackend()._client({"bad": _gist("bad", BAD), "ok": _gist("ok", OK)})
        r = BackendRouter(backend="gists", selfhosted_url="http://unused")
        r._BackendRouter__gists_client = gclient
        with patch("lore.mcp.router.httpx.Client", side_effect=httpx.ConnectError("down")):
            res = r.search_concepts("p", environment=environment_to_dict(PY312))
        assert res["fallback"] is True and _names(res["results"]) == ["ok", "bad"]
