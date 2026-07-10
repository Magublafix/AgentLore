# Lore — Architecture Documentation (arc42)

---

## 1. Introduction and Goals

### 1.1 Requirements Overview

Lore is a typed, linked knowledge graph for AI coding agents. Agents search for reusable concepts — projects, patterns, tools, test strategies — each tagged with "use when" metadata and linked to related concepts. When an agent retrieves a concept, it gets the full proven path: architecture decisions, linked tool concepts, test strategies, and known gotchas — accumulated from prior agent sessions.

Full product spec: `PROJECT.md`.

### 1.2 Quality Goals

| Priority | Quality Goal | Motivation |
|----------|-------------|------------|
| 1 | **Backend transparency** | Switching `LORE_BACKEND` must require zero changes on the agent/MCP side |
| 2 | **Offline capability** | Backend 1 embeddings must run with no external API calls |
| 3 | **Single-call graph retrieval** | `search_concepts` returns the full linked graph — agents must never need a second round-trip |
| 4 | **Graceful degradation** | If the semantic server (Backend 3) is unreachable, fall back to Backend 2 tag search silently |
| 5 | **Human-readable storage** | Backend 2 concepts must be readable and linkable directly on github.com |

### 1.3 Stakeholders

| Role | Expectation |
|------|-------------|
| AI coding agents | Fast, single-call concept retrieval with full linked graph |
| Individual developers | Zero-infrastructure setup via Backend 2 (GitHub token only) |
| Development teams | Self-hosted Backend 1 for private concepts; community sharing via Backend 2/3 |
| Community contributors | Concepts published as public gists; rated by the community |

---

## 2. Architecture Constraints

- MCP tool interface (`search_concepts`, `get_concept`, `submit_concept`, `link_concepts`, `rate_concept`) must be identical across all three backends.
- Backend 1 embeddings use `sentence-transformers/all-MiniLM-L6-v2` — fully offline, no API keys.
- Backend 2 requires only a GitHub personal access token — no servers, no Docker.
- Backend 3 semantic server is always optional; Backend 2 tag search is the fallback.
- `hours_saved` is the primary rating signal; `outcome` (1–5) is secondary.
- Multi-backend fan-out (Backend 1 + Backend 2/3 simultaneously) is out of scope until Phase 4.

---

## 3. System Scope and Context

### 3.1 Business Context

```
┌─────────────────────────────────────────────────────┐
│                  External Actors                    │
│                                                     │
│  AI Agent (Claude Code, Cursor, Cline, Windsurf)   │
│       │  search / submit / rate                     │
│       ▼                                             │
│  ┌─────────────┐                                    │
│  │  Lore MCP   │◄──── LORE_BACKEND env var          │
│  │   Server    │                                    │
│  └──────┬──────┘                                    │
│         │                                           │
│    ┌────┴────┐                                      │
│    ▼         ▼                                      │
│  Self-    GitHub                                    │
│  hosted   Gists ──► Semantic Search Server          │
│  (Docker) (public)  (optional, self-hostable)       │
└─────────────────────────────────────────────────────┘
```

### 3.2 Technical Context

| Interface | Protocol | Notes |
|-----------|----------|-------|
| Agent ↔ MCP server | MCP over stdio or HTTP | FastMCP handles transport |
| MCP server ↔ Backend 1 | HTTP (FastAPI) | `selfhosted/api.py` on :8765 |
| MCP server ↔ Backend 2 | HTTPS (GitHub REST API) | `requests` via `gists_client.py` |
| MCP server ↔ Backend 3 | HTTPS (FastAPI) | Optional; falls back to Backend 2 |
| Backend 1 ↔ Qdrant | gRPC / HTTP | qdrant-client SDK |
| Backend 1 ↔ SQLite | File I/O | sqlite3 (synchronous, WAL mode) |
| Stop hook ↔ session file | File I/O | `~/.lore/session.json` |

---

## 4. Solution Strategy

| Decision | Choice | Rationale |
|----------|--------|-----------|
| MCP framework | FastMCP (Python) | Official MCP SDK; tool registration via decorators |
| Backend abstraction | Router pattern (`router.py`) | Single dispatch point; backends are interchangeable |
| Vector storage | Qdrant | First-class Docker image; Python SDK; production-grade |
| Offline embeddings | sentence-transformers | No API dependency; all-MiniLM-L6-v2 is fast and sufficient |
| Community storage | GitHub Gists | No infrastructure; versioning free; human-readable; existing GitHub accounts |
| Session tracking | JSON file | Simple; hook-compatible; no daemon required |
| Rating collection | Stop hook (bash) | Fires automatically at session end; no explicit agent discipline required |

---

## 5. Building Block View

### 5.1 Level 1 — System

```
lore/
├── mcp/            # MCP server + backend router
├── selfhosted/     # Backend 1: FastAPI + SQLite + Qdrant
├── semantic-server/ # Backend 3: FastAPI + Qdrant + gist watcher
├── skills/         # Claude Code skill file + Stop hook
├── seed/           # Seed concept graph (6 concepts, 5 links)
└── tests/          # unit/ and integration/
```

### 5.2 Level 2 — MCP Layer

| Component | Responsibility |
|-----------|---------------|
| `mcp/server.py` | FastMCP entry point; registers all 5 MCP tools; reads `LORE_BACKEND` and delegates all tool calls to `BackendRouter`; runs content scan on `submit_concept` before dispatch |
| `mcp/router.py` | `BackendRouter` — single dispatch point for all tool calls; routes to selfhosted or gists backend based on `LORE_BACKEND`; lazily initialises `GistsClient` on first gists call |
| `mcp/models.py` | `Concept`, `Link`, `Rating` dataclasses |
| `mcp/embeddings.py` | `EmbeddingModel` — sentence-transformers wrapper; `embed()` and `embed_batch()` produce 384-dim vectors offline |
| `mcp/backends/gists_client.py` | Thin `requests`-based wrapper around the GitHub REST API; typed exceptions (`GistAuthError`, `GistNotFoundError`, `GistRateLimitError`, `GistAPIError`); validates token at init via `GET /user`; rate-limit warning + 502/503 retry built in |
| `mcp/backends/gists.py` | Gists backend: `submit_concept`, `get_concept`, `search_concepts`, `link_concepts`, `rate_concept`; depth-1 link resolution and rating aggregation from gist comments; `LORE_FREELOADER=true` disables comment posting |
| `core/scanner.py` | `scan_content()` — checks all concept text fields for credential patterns, long hex/base64, internal URLs, and `LORE_BLOCK_PATTERNS` custom blocklist before any write; returns structured violation list; cannot be bypassed |

### 5.3 Level 2 — Self-hosted Backend

| Component | Responsibility |
|-----------|---------------|
| `selfhosted/api.py` | FastAPI HTTP service exposing all /v1/ endpoints; shared EmbeddingModel, SQLite connection, and QdrantClient live in FastAPI lifespan |
| `selfhosted/db.py` | SQLite schema + CRUD operations (concepts, links, ratings, session_usage) |
| `selfhosted/schema.sql` | Table definitions for concepts, links, ratings, session_usage |
| `selfhosted/vector_store.py` | Qdrant collection init, vector upsert, similarity search, and near-duplicate detection (`find_near_duplicate`, threshold 0.88) |
| `selfhosted/indexer.py` | Wires embedding model to storage: `index_concept()` and `search_concepts()` |
| `core/scanner.py` | `scan_content()` — credential, hex/base64, internal URL, and custom blocklist detection; called by `submit_concept` before any write |
| `selfhosted/Dockerfile` | Single-container image (`docker run -p 8765:8765 lore/selfhosted`) |

#### Link enrichment — `name`, `type`, `when_to_use` in every link object

The `_link_to_dict()` helper fetches the linked concept from SQLite and includes `name`, `type`, and `when_to_use` in every link object. This satisfies the "no second round-trip" constraint: an agent calling `search_concepts` or `get_concept` receives the full linked graph in one call. Links that reference a non-existent concept fall back to ID-only (no error).

#### Known gap — SQLite/Qdrant write ordering in `POST /v1/concepts`

The submit endpoint inserts the concept into SQLite first, then calls
`index_concept()` to push the vector into Qdrant.  If Qdrant is unavailable
after the SQLite insert completes, the concept exists in SQLite but is not
present in the vector index and therefore not discoverable via
`POST /v1/concepts/search`.

This is a deliberate Phase 1 trade-off documented in the `api.py` module
docstring.  The API returns HTTP 503 with the `concept_id` so the caller or
operator can re-index the concept later.  Rolling back the SQLite insert on
Qdrant failure would leave the caller with no concept_id to retry with.

Re-indexing path (future work, tracked as R-5): a
`POST /v1/concepts/{concept_id}/reindex` endpoint or a background task that
reconciles SQLite concept_ids against Qdrant point IDs.

### 5.4 Level 2 — Skill Layer

| Component | Responsibility |
|-----------|---------------|
| `skills/search-concepts/SKILL.md` | Claude Code skill: calls `search_concepts(problem=...)`, appends returned concept IDs to `~/.lore/session.json` |
| `skills/capture-concept/SKILL.md` | Claude Code skill: reflection gate, mandatory generalization step, `LORE_CAPTURE_MODE` gate, calls `submit_concept` with correct parameters; tracks `existing_concept_id` on 409 dedup |
| `skills/wrapup/SKILL.md` | Claude Code skill: manual session close — resolves concepts via API, rates each, captures new insights, clears session file |
| `.claude/hooks/lore-stop.sh` | Stop hook: reads session.json, resolves concept names via selfhosted API, emits batch rating + reflection prompts, clears session file; always exits 0 |
| `hooks/hooks.json` | Registers lore-stop.sh as a Claude Code Stop hook via the plugin system |

### 5.5 Level 2 — Seed Layer

| Component | Responsibility |
|-----------|---------------|
| `seed/concepts.py` | Idempotent seed loader: inserts 6 REST CLI concepts + 5 links directly via SQLite/Qdrant (no HTTP); validates the full retrieval path on first run |

---

## 6. Runtime View

### 6.1 Concept Search (Backend 1)

```
Agent
  │  invoke search_concepts(problem="...")
  ▼
MCP server (server.py)
  │  validate inputs; LORE_BACKEND=selfhosted
  │  POST /v1/concepts/search → selfhosted FastAPI (one HTTP call)
  ▼
selfhosted/api.py
  │  embed problem → all-MiniLM-L6-v2
  │  query Qdrant → top-N concept_ids by cosine similarity
  │  fetch full records + links from SQLite
  ▼
MCP server
  │  return Concept[] with embedded link graph
  ▼
Agent  ← full concept graph in one call (no N+1 fetches)
```

### 6.2 Session Rating (Stop Hook)

```
Session ends
  ▼
stop.sh fires
  │  read ~/.lore/session.json → concept IDs
  │  if empty → exit 0
  ▼
Present batch rating prompt to user
  │  user responds with ratings + hours_saved
  ▼
call rate_concept for each concept
  │  update avg_rating + time_saved_avg_hours
  ▼
clear ~/.lore/session.json
```

---

## 7. Deployment View

### Backend 1 (self-hosted)

```
docker compose up -d
  ├── lore-selfhosted  (FastAPI + SQLite + sentence-transformers)  :8765
  └── qdrant           (vector store)                              :6333
```

#### Docker image — `lore/selfhosted`

| Property | Value |
|----------|-------|
| Build | Multi-stage (builder + runtime) |
| Base image | `python:3.11-slim` |
| Cached model | `all-MiniLM-L6-v2` (~90 MB) — downloaded on first container start via `entrypoint.sh`, cached in `lore-model-cache` Docker volume; subsequent starts are fully offline |
| Total image size | ~8.7 GB (PyTorch ~1.8 GB, CUDA toolkit, and dependencies; model weights live in `lore-model-cache` volume, not the image) |
| Runtime user | `lore` (uid 1000, non-root) |
| Exposed port | `8765` |
| Healthcheck | `python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/v1/health')"` (no curl dependency) |
| Qdrant sidecar | Required — see `docker-compose.yml`; lore-selfhosted waits for Qdrant healthy before starting |
| Data volume | `/data` — mount here for SQLite persistence (`LORE_DB_PATH=/data/lore.db`) |

**Single-command startup:**
```
docker run -p 8765:8765 lore/selfhosted
```

**Full stack with Qdrant:**
```
docker compose up -d
```

The builder stage installs all Python dependencies. The runtime stage copies only the installed site-packages, uvicorn binary, and source. The embedding model (`all-MiniLM-L6-v2`, ~90 MB) is **not** baked into the image — `entrypoint.sh` downloads it on first container start and caches it in the `lore-model-cache` named Docker volume. Subsequent starts skip the download and set `TRANSFORMERS_OFFLINE=1` automatically.

### Backend 2 (GitHub Gists)

No deployment. Requires `LORE_GITHUB_TOKEN` env var only.

### Backend 3 (semantic server)

```
docker run lore/semantic-server   # independently deployable
  └── FastAPI + Qdrant + gist watcher   :8766
```

MCP server configured via:
```
LORE_BACKEND=gists
LORE_GITHUB_TOKEN=ghp_...
LORE_SEMANTIC_URL=https://search.lore.dev   # optional
```

---

## 8. Cross-cutting Concepts

### 8.1 Backend Interface Contract

All backends must implement:
- `search(problem, type?, language?, limit) → List[Concept]`
- `get(concept_id) → Concept`
- `submit(concept_data) → concept_id`
- `link(from_id, to_id, rel, label) → link_id`
- `rate(concept_id, outcome, hours_saved?, notes?, session_id) → updated averages`

The router calls these methods; MCP tool handlers never access backends directly.

### 8.2 Error Handling

| Scenario | Behavior |
|----------|----------|
| Backend 3 unreachable | Silently fall back to Backend 2 tag search |
| Backend 2 GitHub rate limit | Surface error to agent with clear message |
| Backend 1 Qdrant unreachable | Raise at query time with clear message |
| Invalid `LORE_BACKEND` value | Raise at router initialization, not at query time |
| Session file missing | Stop hook exits 0 silently |

### 8.3 Concept ID Stability

`concept_id` is a UUID assigned at creation and must never change after a concept is published to GitHub Gists. Links reference concept IDs — changing an ID breaks the graph.

### 8.4 Logging

Module-level `logger = logging.getLogger(__name__)` throughout. No `print()`. Log level configurable via `LORE_LOG_LEVEL` env var (default: `INFO`).

---

## 9. Architecture Decisions

| ID | Decision | Status | Date |
|----|----------|--------|------|
| ADR-001 | Use FastMCP as MCP framework | accepted | — |
| ADR-002 | Router pattern for backend abstraction | accepted | — |
| ADR-003 | Embed `when_to_use + name` as the search surface | accepted | — |
| ADR-004 | GitHub Gists as Backend 2 storage | accepted | — |
| ADR-005 | `hours_saved` as primary rating signal | accepted | — |
| ADR-006 | SQLite-first write ordering in submit_concept — no rollback on Qdrant failure | accepted | 2026-05-29 |
| ADR-007 | Content scanner in MCP layer, not FastAPI layer — scan before any network call | accepted | 2026-06-01 |
| ADR-008 | Link responses enriched with `name`, `type`, `when_to_use` — no second round-trip for graph traversal | accepted | 2026-06-04 |

*Add new ADRs here as significant decisions are made. Format: one row per decision, link to a detailed ADR file in `docs/adr/` for complex ones.*

---

## 10. Quality Requirements

### 10.1 Quality Scenarios

| ID | Quality Goal | Scenario | Acceptable Response |
|----|-------------|----------|---------------------|
| QS-1 | Backend transparency | Developer changes `LORE_BACKEND=selfhosted` to `gists` | All MCP tools work with no code changes |
| QS-2 | Offline capability | Developer has no internet access | Backend 1 search and submit work fully offline |
| QS-3 | Single-call retrieval | Agent calls `search_concepts` | Returns matched concept + all linked concepts in one response |
| QS-4 | Graceful degradation | Semantic server goes down | Backend 2 tag search activates silently within the same request |
| QS-5 | Session rating | Session ends with 3 concepts used | Stop hook fires, presents prompt, records ratings without agent intervention |

---

## 11. Risks and Technical Debt

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|-----------|--------|------------|
| R-1 | GitHub Gists API rate limits throttle community search | Medium | Medium | Cache recent searches; surface limit errors clearly |
| R-2 | Near-duplicate concepts degrade community corpus quality | Medium | High | Deduplication on publish (Phase 3) |
| R-3 | Embedding model (all-MiniLM-L6-v2) produces poor matches for highly technical queries | Low | Medium | Evaluate at Phase 1; swap model if needed |
| R-4 | Stop hook fails silently and ratings are never collected | Low | High | Hook must exit 0 but log errors to `~/.lore/hook.log` |
| R-5 | Concept inserted to SQLite but Qdrant unavailable — concept saved but not searchable | Low | Medium | API returns 503 + concept_id; operator can re-index; future reindex endpoint planned |

---

## 12. Glossary

| Term | Definition |
|------|-----------|
| Concept | A typed node in the Lore graph (project, pattern, tool, testing, architecture) |
| Link | A directed edge between two concepts with a `rel` type (uses, tested_by, extends, alternative_to, requires) |
| Backend | The storage and search layer behind the MCP server (selfhosted, gists, or gists+semantic) |
| `when_to_use` | Natural language field embedded for semantic search; the primary retrieval surface |
| `hours_saved` | Estimated hours saved vs. building from scratch; the primary rating signal |
| Session file | `~/.lore/session.json` — tracks concept IDs used in the current agent session |
| Stop hook | Bash script fired by Claude Code when a session ends; collects batch ratings |
| Seed graph | Six concepts and five links pre-loaded on first run to validate the full retrieval path |
| Content scanner | `core/scanner.py` — checks concept fields for credential patterns, internal URLs, and LORE_BLOCK_PATTERNS before persisting |
