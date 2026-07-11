# Backlog

Open stories not yet assigned to a sprint. Prioritized top-to-bottom.

---

<!--
Story format:

## [LORE-NNN] Title

**Phase:** N
**Priority:** high | medium | low
**Effort:** S | M | L
**Agent:** python-mcp-engineer | skill-engineer | ai-data-specialist | test-suite-architect | devops-docker-engineer
**Phase item:** `PROJECT.md` §Development Phases > Phase N > checklist item text

**As a** [role]
**I want to be able to** [action]
**So that** [benefit]

**Acceptance Criteria:**
- [ ] ...

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] Tests written + test-suite-architect approved
- [ ] docs/architecture.md, PROJECT.md, docstrings updated
- [ ] pytest --cov=lore --cov-fail-under=80 passes
-->

## [LORE-030] Semantic search server — FastAPI + Qdrant core

**Phase:** 3
**Priority:** high
**Effort:** L
**Agent:** python-mcp-engineer
**Phase item:** `PROJECT.md` §Development Phases > Phase 3 > FastAPI + Qdrant semantic server (independently deployable)

**As a** Lore operator
**I want to be able to** deploy an independently runnable FastAPI + Qdrant service that stores concept embeddings and serves vector search
**So that** community-published concepts are discoverable with semantic similarity beyond tag matching

**Acceptance Criteria:**
- [ ] `lore/semantic-server/api.py` — FastAPI app with `POST /concepts` (upsert), `GET /search?q=&k=` (vector search, returns top-k with scores), `GET /health`
- [ ] Qdrant collection `lore_concepts` created on startup if absent; schema matches Backend 1 (id, text, tags, metadata)
- [ ] Embeddings generated with `all-MiniLM-L6-v2` (same model as Backend 1); fully offline
- [ ] `docker-compose.semantic.yml` adds `semantic-server` service alongside existing Qdrant; `QDRANT_URL` configurable via env
- [ ] Server starts cleanly with `uvicorn lore.semantic_server.api:app` and responds to `/health`
- [ ] `lore/semantic-server/` has its own `Dockerfile` (multi-stage, slim)

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] Tests written + test-suite-architect approved
- [ ] docs/architecture.md, PROJECT.md, docstrings updated
- [ ] pytest --cov=lore --cov-fail-under=80 passes

---

## [LORE-031] Gist watcher — poll, embed, and index public lore concepts

**Phase:** 3
**Priority:** high
**Effort:** M
**Agent:** python-mcp-engineer
**Phase item:** `PROJECT.md` §Development Phases > Phase 3 > Gist watcher: polls for new/updated `[lore-concept]` gists, embeds and indexes them

**As a** Lore operator
**I want to be able to** run a background watcher that polls GitHub Gists for new or updated `[lore-concept]` entries and indexes them into the semantic server
**So that** community contributions are automatically available for vector search without manual intervention

**Acceptance Criteria:**
- [ ] `lore/semantic-server/watcher.py` — polls GitHub Gist search API for `[lore-concept]` tag at configurable interval (default 5 min, `LORE_WATCH_INTERVAL` env)
- [ ] On each poll: fetches gists updated since last run, parses concept JSON, upserts into semantic server via `POST /concepts`
- [ ] Stores last-polled timestamp in a local file (`~/.lore/watcher_cursor.json`) so restarts don't reprocess everything
- [ ] Deduplicates within a single poll cycle — same gist ID seen twice is upserted once
- [ ] `docker-compose.semantic.yml` adds `watcher` service that starts after `semantic-server`
- [ ] Logs each upsert at INFO level; errors at WARNING (does not crash on one bad gist)

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] Tests written + test-suite-architect approved
- [ ] docs/architecture.md, PROJECT.md, docstrings updated
- [ ] pytest --cov=lore --cov-fail-under=80 passes

---

## [LORE-032] LORE_SEMANTIC_URL routing in MCP server

**Phase:** 3
**Priority:** high
**Effort:** S
**Agent:** python-mcp-engineer
**Phase item:** `PROJECT.md` §Development Phases > Phase 3 > `LORE_SEMANTIC_URL` routing in MCP server — when set, overrides GitHub tag search with vector search against the server

**As a** Lore agent user
**I want to be able to** point the MCP server at a semantic search URL and have `search_concepts` automatically use vector search instead of GitHub tag search
**So that** switching to full semantic search is a single env-var change with no code changes

**Acceptance Criteria:**
- [ ] `BackendRouter` (or equivalent) reads `LORE_SEMANTIC_URL` at startup; when set, `search_concepts` calls `GET <LORE_SEMANTIC_URL>/search?q=&k=` instead of GitHub Search API
- [ ] Response is normalized to the same `ConceptResult` schema as Backend 2 tag search — callers see no difference
- [ ] `LORE_SEMANTIC_URL` is documented in `README.md` alongside `LORE_BACKEND`
- [ ] Existing Backend 2 tests still pass — no regression

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] Tests written + test-suite-architect approved
- [ ] docs/architecture.md, PROJECT.md, docstrings updated
- [ ] pytest --cov=lore --cov-fail-under=80 passes

---

## [LORE-036] Graceful fallback — semantic server unreachable → Backend 2

**Phase:** 3
**Priority:** high
**Effort:** S
**Agent:** python-mcp-engineer
**Phase item:** `PROJECT.md` §Development Phases > Phase 3 > Graceful fallback: if server unreachable, fall back to Backend 2

**As a** Lore agent user
**I want to be able to** have `search_concepts` fall back to GitHub tag search automatically when the semantic server is unreachable
**So that** a downed semantic server never breaks an agent's workflow

**Acceptance Criteria:**
- [ ] When `LORE_SEMANTIC_URL` is set and the semantic server returns a connection error or timeout, `search_concepts` retries once then falls back to Backend 2 (GitHub tag search)
- [ ] Fallback is logged at WARNING level with the error reason; the MCP response includes a `fallback: true` field
- [ ] Timeout for semantic server calls is configurable via `LORE_SEMANTIC_TIMEOUT` (default 5s)
- [ ] Unit tests cover: server up (uses semantic), server down (falls back), timeout (falls back)

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] Tests written + test-suite-architect approved
- [ ] docs/architecture.md, PROJECT.md, docstrings updated
- [ ] pytest --cov=lore --cov-fail-under=80 passes

---

## [LORE-033] Server-side ratings aggregation

**Phase:** 3
**Priority:** medium
**Effort:** M
**Agent:** python-mcp-engineer
**Phase item:** `PROJECT.md` §Development Phases > Phase 3 > Server-side ratings aggregation (outcome + hours_saved) across users

**As a** Lore concept author
**I want to be able to** see aggregated ratings (outcome, hours_saved) from all users who used my concept
**So that** high-quality community concepts surface to the top of search results over time

**Acceptance Criteria:**
- [ ] `POST /ratings` endpoint on semantic server: accepts `{concept_id, outcome, hours_saved?}`, stores in Qdrant metadata (append to list)
- [ ] `GET /search` response includes `avg_outcome` and `avg_hours_saved` fields (null if no ratings yet)
- [ ] `rate_concept` MCP tool (Backend 3 path): posts to `POST /ratings` when `LORE_SEMANTIC_URL` is set
- [ ] Aggregation is computed at query time from stored rating lists (no separate materialized view needed at this scale)

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] Tests written + test-suite-architect approved
- [ ] docs/architecture.md, PROJECT.md, docstrings updated
- [ ] pytest --cov=lore --cov-fail-under=80 passes

---

## [LORE-034] API key auth — one key per GitHub user

**Phase:** 3
**Priority:** medium
**Effort:** M
**Agent:** python-mcp-engineer
**Phase item:** `PROJECT.md` §Development Phases > Phase 3 > API key auth (one per GitHub user, issued on first gist publish)

**As a** Lore operator
**I want to be able to** require API key authentication for writes to the semantic server
**So that** only verified GitHub users can publish or rate concepts, preventing spam

**Acceptance Criteria:**
- [ ] `POST /auth/register` — accepts `{github_token}`, verifies with GitHub `/user`, issues a server-generated API key; idempotent (same GitHub user always gets same key)
- [ ] All write endpoints (`POST /concepts`, `POST /ratings`) require `Authorization: Bearer <api-key>` header; unauthenticated requests return 401
- [ ] Read endpoints (`GET /search`, `GET /health`) remain unauthenticated
- [ ] Keys stored in a SQLite DB (`~/.lore/semantic-keys.db`) within the server container; not Qdrant
- [ ] `submit_concept` MCP tool (Backend 3 path) auto-registers and caches the key when `LORE_SEMANTIC_URL` is set and `LORE_GITHUB_TOKEN` is available

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] Tests written + test-suite-architect approved
- [ ] docs/architecture.md, PROJECT.md, docstrings updated
- [ ] pytest --cov=lore --cov-fail-under=80 passes

---

## [LORE-035] Deduplication — flag near-duplicate concepts on publish

**Phase:** 3
**Priority:** medium
**Effort:** M
**Agent:** python-mcp-engineer
**Phase item:** `PROJECT.md` §Development Phases > Phase 3 > Deduplication: flag near-duplicate concepts on publish

**As a** Lore agent user
**I want to be able to** be warned when a concept I'm submitting is very similar to one that already exists
**So that** the knowledge graph stays non-redundant and I can link to the existing concept instead of creating a duplicate

**Acceptance Criteria:**
- [ ] On `POST /concepts`, before upsert: run vector similarity against existing collection; if any concept scores above threshold (default 0.92, configurable via `LORE_DEDUP_THRESHOLD`), return `{"duplicate": true, "similar": [{id, title, score}]}` with HTTP 409
- [ ] `submit_concept` MCP tool (Backend 3 path) surfaces the 409 to the agent as a `DuplicateConceptError` with the similar concept list
- [ ] Threshold is tunable without code change — env var `LORE_DEDUP_THRESHOLD` on the server
- [ ] A force-override flag `force: true` in the request body bypasses dedup check and always upserts

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] Tests written + test-suite-architect approved
- [ ] docs/architecture.md, PROJECT.md, docstrings updated
- [ ] pytest --cov=lore --cov-fail-under=80 passes

---

## [LORE-029] Benchmark runner: gists backend support with series cleanup

**Phase:** Benchmark
**Priority:** medium
**Effort:** M
**Agent:** python-mcp-engineer
**Phase item:** N/A — benchmark sprint
**Depends on:** Phase 3 (LORE-semantic-server) complete

**As a** Lore developer
**I want to be able to** run the stlgen benchmark against the gists backend with automatic cleanup
**So that** the gists + semantic server stack is validated with the same benchmark methodology as the selfhosted backend

**Context:**
The stlgen benchmark currently runs against the selfhosted backend (SQLite + Qdrant). Once Phase 3 (semantic search server) is complete, the gists backend is equivalent in search quality. This story adds gists support to the benchmark runner, including series-level cleanup so test concepts don't persist on the contributor's GitHub account.

**Acceptance Criteria:**
- [ ] `samples/stlgen/benchmarks/run.py` accepts `--backend gists` flag; defaults to `selfhosted` (no regression)
- [ ] With `--backend gists`, the runner sets `LORE_BACKEND=gists` and `LORE_SEMANTIC_URL` (from env); requires `LORE_GITHUB_TOKEN`
- [ ] Benchmark runner tracks all gist IDs created during a series (from `submit_concept` responses)
- [ ] At series end (after wrapup), all created gists are deleted via `GistsClient.delete_gist`; failures are logged but do not abort the run
- [ ] Result files (`runN.md`, `aggregate.json`) include `backend` field so selfhosted and gists runs are distinguishable
- [ ] A deleted-gist during a run (e.g. manual cleanup mid-run) is handled gracefully — logged, not crashed

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] Tests written + test-suite-architect approved
- [ ] pytest --cov=lore --cov-fail-under=80 passes

---

## [LORE-028] Extended stlgen benchmark — 30 series for statistical confidence

**Phase:** Benchmark
**Priority:** low
**Effort:** L
**Agent:** general-purpose
**Phase item:** N/A — benchmark sprint

**As a** Lore developer
**I want to be able to** run 30 series of the stlgen benchmark instead of 10
**So that** the per-run-position learning curve, concept-bucket analysis, and outlier rate are statistically meaningful

**Context:**
The 10-series run established clear directional signals (R1 10% vs Lore-ON 60%, sweet spot at 20–24 concepts) but is underpowered for nuanced conclusions. With N=10 per run position, confidence intervals are ±30%. Two catastrophic series (S4 0/10, S10 1/10) may be bad luck or a ~20% structural failure rate — indistinguishable at this sample size.

**Why 30 series:**
- Brings each run position to N=30 (±18% CI) — enough to distinguish real curve shape from noise
- Gets N≥20 in the high-concept buckets (30+) — currently only N=4–6 there
- With ~30 series, the catastrophic-failure rate can be estimated (is it 2/30 ≈ 7% or 6/30 ≈ 20%?)
- Marginal return beyond 30 is modest unless publishable precision is needed
- Estimated wall time: ~45–60 hours; best run as a background job over several nights

**Acceptance Criteria:**
- [ ] 30 series × 10 runs completed; results appended to `aggregate.json`
- [ ] `aggregate.md` and `BENCHMARK.md` updated with new statistics
- [ ] Interpretation section updated — confirm or revise the 20–24 concept sweet spot claim
- [ ] Note whether catastrophic-failure rate is consistent with 10-series estimate (~20%)

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] `aggregate.md` and `BENCHMARK.md` committed

---

