# Phase 3 — Summary
**Period:** 2026-07-11 → 2026-07-15   **Status:** ✅ Complete

## Delivered

| Item | Description | Tokens used |
|------|-------------|-------------|
| LORE-030 | Semantic search server — FastAPI + Qdrant core, pluggable storage backends (`sqlite_qdrant`, `gist_qdrant`) | — |
| LORE-031 | Gist watcher — async polling task, embed + index public `[lore-concept]` gists into Qdrant | — |
| LORE-032 | `LORE_SEMANTIC_URL` routing in MCP server — vector search overrides GitHub tag search when set | — |
| LORE-036 | Graceful fallback — semantic server unreachable → falls back to Backend 2 (GitHub tag search) | — |
| Sprint 7 refactor | Unified `lore/server/api.py` with two pluggable backends replacing two separate FastAPI servers | — |
| LORE-034 | API key auth — `KeyStore`, `_require_api_key` dependency, one key per GitHub user | 102,957 |
| LORE-033 | Server-side ratings aggregation — `POST /ratings`, `avg_rating` / `time_saved_avg_hours` in search results | — |
| LORE-035 | Deduplication — `search_similar` wired into `gist_upsert_concept`, `LORE_DEDUP_THRESHOLD` env var, force override | — |
| LORE-029 | Gists backend support in stlgen benchmark runner — `--backend gists`, gist ID tracking, series-end cleanup | — |

## What Works Now

An agent running with `LORE_BACKEND=gists` and `LORE_SEMANTIC_URL` pointing at the semantic server now gets full vector search over the community gist corpus — not just tag matching. When the server is unreachable, search silently falls back to GitHub tag search so the agent always gets a response. API key auth protects all write endpoints; keys are provisioned on first gist publish. Near-duplicate concepts are flagged before submission (configurable threshold), keeping the graph clean. Ratings submitted to the server are aggregated across all users and returned in search results as `avg_rating` and `time_saved_avg_hours`. The benchmark runner can now validate the full Phase 3 stack end-to-end using `--backend gists`.

## Code Coverage

```
Name                                   Stmts   Miss  Cover   Missing
--------------------------------------------------------------------
lore/__init__.py                           0      0   100%
lore/core/__init__.py                      0      0   100%
lore/core/constants.py                    18      2    89%   39-40
lore/core/scanner.py                      52      0   100%
lore/mcp/__init__.py                       0      0   100%
lore/mcp/backends/__init__.py              0      0   100%
lore/mcp/backends/gists.py               137      4    97%   246-248, 464
lore/mcp/backends/gists_client.py         85      0   100%
lore/mcp/embeddings.py                    23      0   100%
lore/mcp/models.py                        35      0   100%
lore/mcp/router.py                       182      6    97%   136-137, 239-240, 371, 450
lore/mcp/server.py                        33      1    97%   326
lore/seed/__init__.py                      2      0   100%
lore/seed/concepts.py                     87     16    82%   296, 331, 363-371, 383, 387-388, 399, 407-411
lore/selfhosted/__init__.py                0      0   100%
lore/selfhosted/db.py                     79      1    99%   79
lore/selfhosted/indexer.py                33      0   100%
lore/selfhosted/vector_store.py           41      4    90%   139-143
lore/semantic_server/__init__.py           0      0   100%
lore/server/__init__.py                    0      0   100%
lore/server/api.py                       344     17    95%   246-255, 419, 454, 478-479, 604-605, 717-718, 759-761, 792, 874
lore/server/auth.py                       36      0   100%
lore/server/storage/__init__.py            2      0   100%
lore/server/storage/base.py               15      0   100%
lore/server/storage/gist_qdrant.py       110      6    95%   131, 160-161, 172, 177, 278
lore/server/storage/sqlite_qdrant.py     114     14    88%   132-133, 144, 149, 244, 248, 322, 350-357, 370, 384-385, 390-391
lore/server/watcher.py                   129      5    96%   214-215, 278-279, 367
----------------------------------------------------------
TOTAL                                   6781    193    97%
Required test coverage of 80% reached. Total coverage: 97.15%
611 passed, 2 skipped in 144.78s
```

## Known Gaps / Deferred

- **Manual Phase 2 test** (`PROJECT.md` §Phase 2 — submit a concept, search for it, star it, rate it) was deferred; the unit and integration tests cover the same paths, but no end-to-end live run against the real GitHub API has been recorded.
- **Hosted public semantic search instance** — Phase 4 item; the server is deployable but no public instance is running.
- **`LORE-028`** (30-series benchmark for statistical confidence) and **`LORE-037`** (noise resilience benchmark) remain in backlog.
- Token counts for LORE-030, 031, 032, 033, 035, 036 were not recorded at the time of the sprint; only LORE-034 was captured (102,957).

## Next Phase — Candidate Items (Phase 4)

- Publish MCP server to PyPI as `lore-mcp`
- Publish self-hosted Docker image to Docker Hub as `lore/selfhosted`
- Host a public semantic search instance
- Concept graph browser (read-only web UI)
- Flip `LORE_CAPTURE_MODE` default to `auto`
