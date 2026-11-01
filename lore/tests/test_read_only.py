"""Read-only demo mode and bundled seed corpus (LORE-044). No network, no GitHub."""

from __future__ import annotations

import asyncio
import subprocess
import sys

import httpx
import pytest

from lore.mcp.backends import seed as seed_backend
from lore.mcp.router import BackendRouter


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for key in ("LORE_GITHUB_TOKEN", "LORE_TOKEN_FROM_GH", "LORE_SEMANTIC_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LORE_READ_ONLY", "1")


def _router(monkeypatch, tmp_path):
    r = BackendRouter(backend="gists", selfhosted_url="http://unused")
    # Any GistsClient construction in read-only mode is a bug.
    monkeypatch.setattr(
        "lore.mcp.router.GistsClient", lambda *a, **k: pytest.fail("GistsClient used in read-only mode")
    )
    return r


class TestSeedBackend:
    def test_search_finds_anchor_with_labels_and_links(self):
        res = seed_backend.search_concepts("REST CLI around a REST API")["results"]
        top = res[0]
        assert top["name"] == "REST CLI around a REST API"
        assert top["source"] == "seed" and top["label"] == "curated example"
        assert top["concept_id"].startswith("seed:")
        assert len(top["links"]) == 5 and all(l["name"] for l in top["links"])
        # contract keys of the gists backend
        for key in ("concept_id", "name", "type", "language", "content", "when_to_use",
                    "dont_use_when", "tags", "source_url", "avg_rating", "avg_hours_saved", "links"):
            assert key in top

    def test_ids_cannot_collide_with_gist_ids(self):
        ids = [c["concept_id"] for c in seed_backend.search_concepts("rest cli api pagination", limit=20)["results"]]
        assert ids and all(":" in i for i in ids)  # gist ids are bare hex

    def test_filters_limit_and_no_match(self):
        assert seed_backend.search_concepts("rest", type="nope")["results"] == []
        assert seed_backend.search_concepts("rest", language="rust")["results"] == []
        assert len(seed_backend.search_concepts("rest cli api", limit=2)["results"]) == 2
        assert seed_backend.search_concepts("zzzqqq")["results"] == []

    def test_get_concept_round_trip_and_incoming_links(self):
        anchor = seed_backend.search_concepts("REST CLI around a REST API")["results"][0]
        got = seed_backend.get_concept(anchor["concept_id"])
        assert got["name"] == anchor["name"]
        child = seed_backend.get_concept(anchor["links"][0]["concept_id"])
        assert child["links"][0]["direction"] == "incoming"
        assert seed_backend.get_concept("seed:nope") is None
        assert seed_backend.get_concept("1234abcd") is None

    def test_does_not_import_heavy_dependencies(self):
        code = (
            "import sys, lore.mcp.backends.seed as s; s.search_concepts('rest');"
            "bad=[m for m in sys.modules if m.split('.')[0] in "
            "('fastapi','qdrant_client','sentence_transformers','torch')];"
            "print(bad)"
        )
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
        assert out.stdout.strip() == "[]"


class TestRouterReadOnly:
    def test_search_uses_seeds_without_github(self, monkeypatch, tmp_path):
        r = _router(monkeypatch, tmp_path)
        res = r.search_concepts("REST CLI around a REST API")
        assert res["results"] and "fallback" not in res

    def test_get_concept_seed_and_unknown(self, monkeypatch, tmp_path):
        r = _router(monkeypatch, tmp_path)
        cid = r.search_concepts("REST CLI")["results"][0]["concept_id"]
        assert r.get_concept(cid)["source"] == "seed"
        with pytest.raises(RuntimeError, match="Read-only"):
            r.get_concept("abc123")

    def test_write_tools_return_typed_error(self, monkeypatch, tmp_path):
        r = _router(monkeypatch, tmp_path)
        for res, tool in (
            (r.submit_concept("n", "pattern", "c", "w", []), "submit_concept"),
            (r.link_concepts("a", "b", "uses", "l"), "link_concepts"),
            (r.rate_concept("a", 5, "s"), "rate_concept"),
        ):
            assert res["error"] == "read_only" and res["tool"] == tool and res["hint"]

    def test_semantic_first_then_seed_fallback(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LORE_SEMANTIC_URL", "http://sem.invalid")
        r = _router(monkeypatch, tmp_path)
        calls = []
        monkeypatch.setattr(r, "_semantic_search", lambda *a: calls.append(a) or {"results": [{"name": "x"}]})
        out = r.search_concepts("rest")  # older server without compatibility_check: annotated locally
        assert [x["name"] for x in out["results"]] == ["x"]
        assert out["results"][0]["compatibility_check"]["status"] == "unknown"

        def down(*a):
            raise httpx.ConnectError("down")

        monkeypatch.setattr(r, "_semantic_search", down)
        res = r.search_concepts("REST CLI around a REST API")
        assert res["fallback"] is True and res["results"][0]["source"] == "seed"

    def test_read_only_off_does_not_use_seeds(self, monkeypatch):
        monkeypatch.delenv("LORE_READ_ONLY")
        r = BackendRouter(backend="gists", selfhosted_url="http://unused")
        from lore.mcp.backends.gists_client import GistAuthError

        with pytest.raises(GistAuthError):
            r.search_concepts("rest")


    def test_get_concept_non_seed_id_with_semantic_url_is_typed_error(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LORE_SEMANTIC_URL", "http://sem.invalid")
        r = _router(monkeypatch, tmp_path)
        res = r.get_concept("deadbeef")
        assert res["error"] == "read_only_lookup_unavailable" and res["hint"]
        cid = seed_backend.search_concepts("REST CLI")["results"][0]["concept_id"]
        assert r.get_concept(cid)["source"] == "seed"

    def test_seed_search_honours_min_rating(self, monkeypatch):
        monkeypatch.setattr(seed_backend, "_to_concept",
                            lambda d, _orig=seed_backend._to_concept: {**_orig(d), "avg_rating": 1.0})
        assert seed_backend.search_concepts("rest", min_rating=2.0)["results"] == []
        assert seed_backend.search_concepts("rest", min_rating=0.5)["results"]


SECRET_CONTENT = "token ghp_" + "a" * 36


class TestServerTools:
    @pytest.mark.parametrize("backend", ["gists", "selfhosted"])
    def test_write_wrappers_return_read_only_before_anything_else(self, monkeypatch, backend):
        import lore.mcp.server as srv
        from lore.core.scanner import scan_content

        assert scan_content({"content": SECRET_CONTENT})  # would be rejected if the scan ran first
        router = BackendRouter(backend, "http://127.0.0.1:9")
        monkeypatch.setattr(srv, "_router", router)
        monkeypatch.setattr("lore.mcp.router.GistsClient", lambda *a: pytest.fail("github"))
        monkeypatch.setattr(router, "_client", lambda: pytest.fail("selfhosted HTTP"))
        sub = srv.submit_concept(name="n", type="pattern", content=SECRET_CONTENT, when_to_use="w", tags=[])
        lnk = srv.link_concepts(from_id="a", to_id="b", rel="uses", label="l")
        rat = srv.rate_concept(concept_id="a", outcome=5, session_id="s")
        for res in (sub, lnk, rat):
            assert res["error"] == "read_only" and res["hint"]

    @pytest.mark.parametrize("backend", ["gists", "selfhosted"])
    def test_search_and_get_use_seeds_for_either_backend(self, monkeypatch, backend):
        import lore.mcp.server as srv

        router = BackendRouter(backend, "http://127.0.0.1:9")
        monkeypatch.setattr(srv, "_router", router)
        monkeypatch.setattr(router, "_client", lambda: pytest.fail("selfhosted HTTP"))
        res = srv.search_concepts(problem="REST CLI around a REST API")
        assert res["results"][0]["source"] == "seed"
        assert srv.get_concept(concept_id=res["results"][0]["concept_id"])["source"] == "seed"

    def test_tool_list_and_full_schemas_identical_to_non_read_only_server(self, tmp_path):
        from fastmcp import Client
        from fastmcp.client.transports import StdioTransport

        async def schemas(extra):
            env = {"LORE_BACKEND": "gists", "HOME": str(tmp_path), **extra}
            client = Client(StdioTransport(sys.executable, ["-m", "lore.mcp.server"], env=env,
                                           keep_alive=False))
            async with client:
                return {t.name: (t.description, t.inputSchema) for t in await client.list_tools()}

        ro = asyncio.run(schemas({"LORE_READ_ONLY": "1"}))
        rw = asyncio.run(schemas({}))
        assert set(ro) == {"search_concepts", "get_concept", "submit_concept",
                           "link_concepts", "rate_concept"}
        assert ro == rw
