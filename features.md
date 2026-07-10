# Features

Implemented and shipped stories. Append-only — never edit or remove entries.

---

<!--
Feature format:

## [LORE-NNN] Title

**Sprint:** N   **Shipped:** YYYY-MM-DD   **Phase:** N   **Tokens:** NNN

**As a** [role]
**I want to be able to** [action]
**So that** [benefit]

**What changed:** one or two sentences — what an agent or user can now do that they couldn't before.

**Implementation notes:** key decisions, affected files, known gotchas.
-->

## [LORE-001] SQLite schema and Qdrant collection setup

**Sprint:** 1   **Shipped:** 2026-05-29   **Phase:** 1   **Tokens:** 50785

**As a** Lore selfhosted backend
**I want to be able to** persist concepts, links, ratings, and session usage in SQLite and search concept vectors via Qdrant
**So that** all Phase 1 backend components have a stable, tested storage foundation to build on

**What changed:** The project now has a working data layer — `schema.sql` defines all four tables, `db.py` provides the full CRUD API, and `vector_store.py` handles Qdrant collection init and similarity search. `models.py` defines the shared `Concept`, `Link`, and `Rating` dataclasses used across the MCP and selfhosted layers.

**Implementation notes:** Bidirectional link queries use `WHERE from_id = ? OR to_id = ?` with separate indexes — direction is preserved in columns, neighbourhood is returned in one query. Rating aggregation recomputes from source truth via `AVG()` on every write to prevent drift. Qdrant point IDs are stable: valid UUID concept IDs pass through; non-UUID IDs get a deterministic UUID5 with the original stored in payload.

---

## [LORE-002] Embedding pipeline

**Sprint:** 1   **Shipped:** 2026-05-29   **Phase:** 1   **Tokens:** 54484

**As a** Lore selfhosted backend
**I want to be able to** compute and store sentence-transformer embeddings for concepts, and run similarity search against them
**So that** agents can describe a problem in natural language and get semantically relevant concepts back

**What changed:** `EmbeddingModel` wraps `all-MiniLM-L6-v2` fully offline. `index_concept()` embeds `when_to_use + name`, stores the BLOB in SQLite, and upserts the vector to Qdrant. `search_concepts()` embeds the query, hits Qdrant, fetches full records from SQLite, and applies type/language filters in-memory.

**Implementation notes:** Embedding target is `when_to_use + " " + name` — `content` is deliberately excluded (too long, too specific). In-memory filtering uses `limit * 4` Qdrant candidates to guard against filter attrition. `update_embedding()` added to `db.py`. LORE-003 must create `EmbeddingModel` once at startup (in `lifespan`) and inject it — the indexer accepts it as a parameter for this reason.

---

## [LORE-003] FastAPI selfhosted service

**Sprint:** 1   **Shipped:** 2026-05-29   **Phase:** 1   **Tokens:** 69828

**As a** Lore MCP server
**I want to be able to** submit, retrieve, search, link, and rate concepts via HTTP
**So that** the MCP layer has a clean, backend-agnostic HTTP boundary to call

**What changed:** `lore/selfhosted/api.py` exposes all five concept operations under `/v1/` as a FastAPI service. A single `EmbeddingModel`, SQLite connection, and `QdrantClient` are created in `lifespan` and shared across requests. Content scanner stub wired at submit time — real scanner slots in without API changes in LORE-005. 25 tests.

**Implementation notes:** SQLite insert happens before Qdrant upsert; Qdrant failure returns HTTP 503 with the `concept_id` so the caller can retry. SQLite insert is not rolled back (documented in arc42 Section 5.3 and R-5). `QDRANT_HOST`, `QDRANT_PORT`, and `LORE_DB_PATH` are env-configurable for Docker. Entry point: `uvicorn lore.selfhosted.api:app --host 0.0.0.0 --port 8765`.

---

## [LORE-004] Docker image for selfhosted backend

**Sprint:** 1   **Shipped:** 2026-05-31   **Phase:** 1   **Tokens:** 68874

**As a** Lore operator
**I want to be able to** run the selfhosted backend as a single Docker container with no network access at runtime
**So that** the self-hosted backend can be deployed in air-gapped environments with a single `docker run` command

**What changed:** `lore/selfhosted/Dockerfile` ships a production-ready multi-stage image (~2.9 GB) with the `all-MiniLM-L6-v2` model baked in. `docker-compose.yml` brings up the full stack (lore-selfhosted + Qdrant) with health checks and named volumes. Offline boot verified with `--network none`.

**Implementation notes:** `TRANSFORMERS_OFFLINE=1` + `HF_DATASETS_OFFLINE=1` are required in the runtime stage — newer `huggingface_hub` does a HEAD request to HuggingFace Hub before loading cached weights, which fails in air-gapped containers. Healthcheck uses Python urllib (not curl) — curl is absent from `python:3.11-slim`. Qdrant sidecar healthcheck retains curl (Qdrant's image ships it). Non-root user `lore` uid 1000; `/data` volume for SQLite.

---

## [LORE-005] MCP server with selfhosted routing

**Sprint:** 1   **Shipped:** 2026-06-01   **Phase:** 1   **Tokens:** —

**As a** AI coding agent
**I want to be able to** call `search_concepts`, `get_concept`, `submit_concept`, `link_concepts`, and `rate_concept` via MCP
**So that** I can retrieve and contribute to the Lore knowledge graph without knowing which backend stores the data

**What changed:** `lore/mcp/server.py` implements all five MCP tools via FastMCP, routing HTTP calls to the selfhosted FastAPI backend at `LORE_SELFHOSTED_URL`. `lore/core/scanner.py` runs a mandatory content scan on every `submit_concept` call — rejects credentials, internal URLs, and custom blocklist matches with a structured error before any write reaches the backend. `python -m lore.mcp.server` starts cleanly. 160 tests, 99.04% coverage.

**Implementation notes:** Routing is done directly in `server.py` (no separate router module) — `LORE_BACKEND` is read at startup; non-selfhosted values raise `NotImplementedError` immediately. Scanner runs client-side before the HTTP call — rejection is instant and does not consume a round-trip. `LORE_BLOCK_PATTERNS` env var accepts semicolon-separated regexes compiled once at import. `httpx.ConnectError` propagates raw to the MCP caller (not wrapped). 422 from the backend maps to `ValueError`; all other HTTP errors map to `RuntimeError`.

---

## [LORE-007] search-concepts skill

**Sprint:** 1   **Shipped:** 2026-06-02   **Phase:** 1   **Tokens:** —

**As a** AI coding agent
**I want to be able to** invoke `/search-concepts` to search the Lore knowledge graph and have used concept IDs automatically tracked in my session file
**So that** I can retrieve relevant prior knowledge before implementing a solution and enable automatic end-of-session ratings

**What changed:** `.claude/skills/search-concepts.md` instructs agents to call `search_concepts(problem=..., limit=5)`, read the full linked concept graph in one call, and append all returned concept IDs to `~/.lore/session.json`. The session file is created if missing and reset if corrupted.

**Implementation notes:** Session file format is a plain JSON array of concept ID strings. Agents are instructed not to make a second MCP call for linked concepts — they are included in the first response. MCP errors are silently swallowed so a missing backend never blocks a task.

---

## [LORE-008] capture-concept skill

**Sprint:** 1   **Shipped:** 2026-06-02   **Phase:** 1   **Tokens:** —

**As a** AI coding agent
**I want to be able to** invoke `/capture-concept` to submit a generalized insight to the Lore knowledge graph, with a mandatory reflection gate and mode-based confirmation
**So that** discovered patterns are preserved for future agents without leaking session-specific details

**What changed:** `.claude/skills/capture-concept.md` implements the full capture flow: reflection gate (3 criteria), mandatory generalization step, `LORE_CAPTURE_MODE` gate (`confirm` default / `auto`), and `submit_concept` call with the correct parameter names. Scanner rejections prompt in-skill retry after further generalization.

**Implementation notes:** `confirm` mode is the default — any value other than `auto` (including absent) uses confirm. Scanner retry is capped at one attempt per field. Successful submissions also append to `~/.lore/session.json` so they appear in the end-of-session rating prompt.

---

## [LORE-009] Stop hook: batch rating and session-end reflection

**Sprint:** 1   **Shipped:** 2026-06-02   **Phase:** 1   **Tokens:** —

**As a** AI coding agent
**I want to** automatically be prompted to rate used Lore concepts and reflect on capturable insights when my session ends
**So that** the knowledge graph accumulates quality signals without requiring explicit agent discipline mid-task

**What changed:** `.claude/hooks/lore-stop.sh` fires at session end via `.claude/settings.json` Stop hook. It reads `~/.lore/session.json`, resolves concept names via the selfhosted API (best-effort), emits a structured rating prompt and reflection prompt to stdout for Claude to act on, then clears the session file.

**Implementation notes:** Hook always exits 0 — never blocks session close. If the selfhosted backend is unreachable, concept IDs are shown instead of names. Session file is cleared after the prompt is emitted; if the hook is killed mid-run the session file remains intact for the next invocation (idempotent). `LORE_SELFHOSTED_URL` env var configures the backend URL (default `http://localhost:8765`).

---

## [LORE-006] Seed concept graph

**Sprint:** 1   **Shipped:** 2026-06-03   **Phase:** 1   **Tokens:** —

**As a** Lore operator
**I want to be able to** run `python -m lore.seed.concepts` to pre-populate the knowledge graph with a validated REST CLI concept graph
**So that** the retrieval path can be verified end-to-end on first run without requiring manual concept creation

**What changed:** `lore/seed/concepts.py` inserts 6 REST CLI concepts (project, tool, architecture, testing, 2×pattern) and 5 directed links from the anchor concept, directly via SQLite and Qdrant — no HTTP, no running server required. 17 seed tests, 177 total, 98.32% coverage.

**Implementation notes:** Idempotency is checked against the anchor concept name before any write — second call returns `SeedResult(skipped=True)` immediately with zero writes. Qdrant indexing is best-effort; SQLite inserts always complete even if Qdrant is unavailable. `_CONCEPT_DEFS` and `_LINK_DEFS` are exported for test assertions. `seed()` accepts injected `conn`, `qdrant_client`, and `embedding_model` for testing without infrastructure.

---

## [LORE-015] Define radev CLI scope and test suite

**Sprint:** 2   **Shipped:** 2026-06-11   **Phase:** Benchmark   **Tokens:** —

**As a** Lore developer
**I want to be able to** reference a fixed CLI specification and a runnable test suite before each benchmark run
**So that** both runs target an identical definition of done and results are directly comparable

**What changed:** `samples/radev/tests/test_radev_cli.py` defines 9 tests (list×2, create×2, get×2, update×1, delete×2) that invoke `radev` via subprocess. `samples/radev/tests/conftest.py` spins a local mock server mirroring restful-api.dev so tests run without external deps or rate limits. `samples/radev/benchmarks/run.py` is the repeatable Anthropic SDK agentic runner.

**Implementation notes:** `RADEV_BASE_URL` env var routes the CLI to any server; conftest reuses it if already set (benchmark runner pre-sets it). Mock server uses stdlib only — no external packages. `capture-concept` and `wrapup` SKILL.md updated: agents now enumerate 3–6 concrete implementation areas before applying capture criteria, replacing a broad sweep that consistently under-captured insights.

---

## [LORE-016] Run 1 — Implement radev CLI without Lore

**Sprint:** 2   **Shipped:** 2026-06-11   **Phase:** Benchmark   **Tokens:** 163,279

**As a** Lore developer
**I want to be able to** implement the radev CLI in a fresh Claude Code session without Lore skills active
**So that** we establish a baseline token count and prompt count, and populate the concept graph via `lore:wrapup` at session end

**What changed:** `samples/radev/results/run1.md` records the baseline: 21 turns, 163,279 total tokens, 160.9s elapsed, 9/9 tests passed. Agent captured concepts post-submit in the same loop using the `capture-concept` skill.

**Implementation notes:** Run 1 has no `search_concepts` tool available — pure cold-start build. Concepts are submitted directly to `~/.lore/lore.db` via SQLite INSERT (no running server required at benchmark time). Loop exits on `end_turn` stop reason, not on `submit` return value, so the agent can continue to concept capture after submitting passing tests.

---

## [LORE-017] Run 2 — Implement radev CLI with Lore concepts

**Sprint:** 2   **Shipped:** 2026-06-12   **Phase:** Benchmark   **Tokens:** 150,867

**As a** Lore developer
**I want to be able to** implement the same radev CLI in a fresh Claude Code session with Lore concepts from Run 1 available
**So that** we can measure how much Lore reduces tokens and prompts compared to the baseline

**What changed:** `samples/radev/results/run2.md` and `samples/radev/results/comparison.md` record the Lore-assisted result: 17 turns (-19%), 150,867 total tokens (-7.6%), 143.7s elapsed (-10.7%), 9/9 tests passed. 8 concepts were available from Run 1.

**Implementation notes:** `search_concepts` does a keyword search against `~/.lore/lore.db` and returns matching concepts injected into the system prompt at session start. Savings are conservative — the concept graph was populated in the same benchmark session; a mature graph with accumulated domain knowledge would be expected to show larger reductions.

---

## [LORE-018] Define text2stl CLI scope and test suite

**Sprint:** 3   **Shipped:** 2026-06-13   **Phase:** Benchmark   **Tokens:** —

**As a** Lore developer
**I want to be able to** reference a fixed CLI specification and 13-test suite before each benchmark run
**So that** all 10 progressive runs target an identical definition of done

**What changed:** `samples/stlgen/tests/test_text2stl_cli.py` — 13 tests across invocation, validation, STL validity, dimensions, and character shapes. `samples/stlgen/benchmarks/run.py` — 10-run progressive benchmark runner with 40-turn budget, forced capture + wrapup phases, `--run N` / `--all` interface.

**Implementation notes:** IoU test (`test_character_shapes_match_text`) required tight-bbox normalization on the PIL reference side to prevent scale mismatch vs the STL cross-section (which always fills its bounding box). All runs share one DB that accumulates organically — no seed concepts injected. Wrapup phase loads `skills/wrapup/SKILL.md` via `_load_skill()` — not inline guidance.

---

## [LORE-019] Run 1 — no Lore baseline

**Sprint:** 3   **Shipped:** 2026-06-13   **Phase:** Benchmark   **Tokens:** —

**As a** Lore developer
**I want to be able to** attempt text2stl without Lore in 40 turns, capturing concepts as I discover them
**So that** we establish a baseline and populate Lore for subsequent runs, even if the task fails

**What changed:** `samples/stlgen/results/run1.md` — baseline result. DB reset to empty on Run 1 start; concepts captured during session populate it for Run 2.

**Implementation notes:** No `search_concepts` tool available. Forced 15-turn capture phase runs after main loop regardless of task outcome.

---

## [LORE-020] Run 2 — Lore ON, unrated concepts from Run 1

**Sprint:** 3   **Shipped:** 2026-06-13   **Phase:** Benchmark   **Tokens:** —

**As a** Lore developer
**I want to be able to** attempt text2stl with unrated Lore concepts from Run 1
**So that** we measure whether any organic Lore knowledge shifts the outcome before ratings provide a quality filter

**What changed:** `samples/stlgen/results/run2.md`.

**Implementation notes:** `search_concepts` default `min_rating=2.0` means concepts with `avg_rating=0.0` (unrated) are invisible. Run 2 effectively had 0 searchable concepts — the wrapup after Run 1 must rate concepts above 2.0 before they surface in Run 3+.

---

## [LORE-021] Run 3 — Lore ON, concepts rated after Runs 1+2

**Sprint:** 3   **Shipped:** 2026-06-14   **Phase:** Benchmark   **Tokens:** —

**As a** Lore developer
**I want to be able to** attempt text2stl with rated Lore concepts from prior runs
**So that** we measure whether concept ratings improve search relevance and compound run-over-run

**What changed:** `samples/stlgen/results/run3.md`.

**Implementation notes:** Series 1 wrapup prompt was ambiguous — allowed rating tried-and-failed approaches 2–3 instead of 1, making bad voxel/marching-cubes concepts visible in search. Fixed in `skills/wrapup/SKILL.md` (tried-and-failed → rate 1) for Series 2.

---

## [LORE-022] Runs 4–10 — Lore ON, progressively rated knowledge base

**Sprint:** 3   **Shipped:** 2026-06-27   **Phase:** Benchmark   **Tokens:** —

**As a** Lore developer
**I want to be able to** attempt text2stl across runs 4–10 with an increasingly rated Lore knowledge base
**So that** we measure whether accumulated, rated concepts compound into measurably better outcomes

**What changed:** `samples/stlgen/results/run4.md` through `run10.md`. `samples/stlgen/benchmarks/README.md` — full series results and analysis including bad-concept amplification diagnosis.

**Implementation notes:** Series 1 DB ended with ~49 concepts; voxel/marching-cubes concepts rated ≥2.0 (visible) while correct Shapely extrusion concepts rated <2.0 (invisible) — `min_rating=2.0` filter acted as a voxel amplifier. Root cause: ambiguous wrapup prompt. Series 2 benchmark needed to validate the wrapup skill fix.

---

## [LORE-026] Aggregate and analyze multi-series benchmark results

**Sprint:** 4   **Shipped:** 2026-07-10   **Phase:** Benchmark   **Tokens:** 73,680

**As a** Lore developer
**I want to be able to** see aggregated pass-rate statistics across all 10 series of the stlgen benchmark
**So that** I can identify trends in how Lore's accumulated knowledge affects task success over time

**What changed:** `samples/stlgen/results/aggregate.md` — full aggregate analysis: per-series pass rates, per-run-position learning curve, concept accumulation table, and concept-bucket analysis.

**Implementation notes:** JSON contained 15 series entries; the first 5 are excluded exploratory runs (duplicate series_id:1, non-fresh DBs). Canonical 10 series are positions 5–14 (0-indexed). Data artifacts noted: position 3 run 4 has concepts_captured: -49; position 3 (series_id:2) is missing run 7.

---

## [LORE-027] Write benchmark README with methodology and findings

**Sprint:** 4   **Shipped:** 2026-07-10   **Phase:** Benchmark   **Tokens:** 43,911

**As a** Lore developer
**I want to be able to** point someone at a single document that explains what was measured, how, and what we found
**So that** the benchmark results are understandable without reading the code or raw result files

**What changed:** `samples/stlgen/BENCHMARK.md` — standalone benchmark document covering task description, methodology, series-level results, learning curve, concept-bucket analysis, outlier explanation (S4/S10), conclusions, and known limitations.

**Implementation notes:** Links to `results/aggregate.md` for raw tables. No invented numbers — all statistics sourced from aggregate.md. Includes explicit note on cross-series isolation design rationale and seed-concept exclusion rationale.
