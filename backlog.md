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

## [LORE-010] GitHub Gists API client

**Phase:** 2
**Priority:** high
**Effort:** S
**Agent:** python-mcp-engineer
**Phase item:** `PROJECT.md` §Development Phases > Phase 2 > GitHub API client (gist create, update, search by description marker)

**As a** Lore gists backend
**I want to be able to** create, read, update, and search GitHub Gists via a thin API client
**So that** all GitHub interactions are isolated behind a testable boundary with consistent error handling

**Acceptance Criteria:**
- [ ] `lore/mcp/backends/gists_client.py` wraps the GitHub REST API using `LORE_GITHUB_TOKEN` from env; missing token raises a clear `GistAuthError` at client init — not at first call
- [ ] On init, fetches `GET /user` and stores the authenticated login (`self.authenticated_login`) — used by LORE-014's edit-if-exists; raises `GistAuthError` if the token is invalid
- [ ] Exposes the following interface:
  - `create_gist(files: dict[str, str], description: str, public: bool) -> str` (gist_id)
  - `get_gist(gist_id: str) -> GistData(files, description)`
  - `update_gist(gist_id: str, files: dict[str, str])` — PATCH semantics: only specified files are updated; unspecified files are left unchanged
  - `search_gists(query: str) -> list[GistSummary(gist_id, description)]` — returns description alongside ID so callers can pre-filter without an extra fetch
  - `list_comments(gist_id: str) -> list[Comment(id, body, author_login)]`
  - `create_comment(gist_id: str, body: str) -> str` (comment_id)
  - `update_comment(gist_id: str, comment_id: str, body: str)`
- [ ] GitHub API errors surface as typed exceptions defined in this file: `GistNotFoundError`, `GistAuthError`, `GistRateLimitError`, `GistAPIError` (catch-all)
- [ ] Transient errors (HTTP 502/503) retried once with 1 s backoff before raising `GistAPIError`
- [ ] Rate limit headers inspected on every response; when `X-RateLimit-Remaining < 10`, a warning is logged to stderr with the reset timestamp

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] Tests written + test-suite-architect approved
- [ ] docs/architecture.md, PROJECT.md, docstrings updated
- [ ] pytest --cov=lore --cov-fail-under=80 passes

---

## [LORE-011] Gists backend: submit_concept and get_concept

**Phase:** 2
**Priority:** high
**Effort:** M
**Agent:** python-mcp-engineer
**Phase item:** `PROJECT.md` §Development Phases > Phase 2 > `LORE_BACKEND=gists` routing in MCP server; `submit_concept` creates a public gist

**As a** Claude Code agent
**I want to be able to** submit concepts as public GitHub Gists and retrieve them by ID
**So that** concepts are shareable with the community without any infrastructure

**Acceptance Criteria:**
- [ ] `lore/mcp/backends/gists.py` implements the backend; `router.py` routes to it when `LORE_BACKEND=gists`
- [ ] `submit_concept` creates a public gist with two files: `concept.md` (the content field) and `lore.json` (all structured metadata)
- [ ] `lore.json` schema: `{"schema_version": "1", "type": "...", "language": "...", "when_to_use": "...", "dont_use_when": "...", "tags": [...], "links": [{"gist_id": "...", "rel": "...", "label": "..."}]}`
- [ ] Gist description format is owned by `gists_client.py`: `[lore-concept] <name> [tag1, tag2, ...]` — tags embedded in description enable GitHub Search API tag filtering without requiring a `lore.json` fetch per result
- [ ] `submit_concept` returns `ConceptResponse` matching `lore/mcp/models.py` including the assigned `concept_id` (gist_id) and a `source_url` (gist HTML URL)
- [ ] `get_concept` fetches the gist by ID, parses `concept.md` and `lore.json`, and returns `ConceptResponse` — identical schema to selfhosted backend
- [ ] `get_concept` resolves linked concepts inline (depth 1 only — links of links are not followed): max 10 links resolved per call; if a linked gist is deleted or private, that link is included in the response as `{"gist_id": "...", "status": "unavailable"}` rather than failing the whole call
- [ ] Gist not found or deleted: returns structured error `{"error": "...", "code": "not_found"}`

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] Tests written + test-suite-architect approved
- [ ] docs/architecture.md, PROJECT.md, docstrings updated
- [ ] pytest --cov=lore --cov-fail-under=80 passes

---

## [LORE-012] Gists backend: search_concepts via GitHub Search API

**Phase:** 2
**Priority:** high
**Effort:** M
**Agent:** python-mcp-engineer
**Phase item:** `PROJECT.md` §Development Phases > Phase 2 > `search_concepts` queries GitHub Search API by tags

**As a** Claude Code agent
**I want to be able to** search the public Lore concept corpus by tags without running any local infrastructure
**So that** I can discover community-contributed concepts with only a GitHub token

**Acceptance Criteria:**
- [ ] `search_concepts` queries GitHub Search API using the format `[lore-concept] <tag1> <tag2>` in the description field — tags embedded in the description (LORE-011) make this efficient without fetching `lore.json` per result for tag filtering
- [ ] Fetches up to 3 pages (max 90 results) from GitHub Search API; stops early once `limit` satisfied candidates remain after client-side filtering; results deduplicated by gist_id across pages
- [ ] `type` and `language` filters applied client-side after fetching `lore.json` for each candidate (these fields are not in the description)
- [ ] `limit` parameter governs final result count after all client-side filters; if 3 pages are exhausted before `limit` is reached, returns however many matched — no error
- [ ] For each result, linked concepts resolved inline per the same rules as `get_concept` (depth 1, max 10 links, unavailable links annotated)
- [ ] Response schema matches `lore/mcp/models.py` `ConceptResponse` exactly
- [ ] Empty result set returns an empty list, no error
- [ ] `GistRateLimitError` returns structured MCP error with human-readable message and does not crash

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] Tests written + test-suite-architect approved
- [ ] docs/architecture.md, PROJECT.md, docstrings updated
- [ ] pytest --cov=lore --cov-fail-under=80 passes

---

## [LORE-013] Gists backend: link_concepts

**Phase:** 2
**Priority:** high
**Effort:** S
**Agent:** python-mcp-engineer
**Phase item:** `PROJECT.md` §Development Phases > Phase 2 > `link_concepts` updates `lore.json` on the source gist

**As a** Claude Code agent
**I want to be able to** link two community concepts by updating the source gist's metadata
**So that** the concept graph grows organically without any central database

**Acceptance Criteria:**
- [ ] `link_concepts` reads the current `lore.json` from the `from_id` gist, appends the new link entry, and writes back via `gists_client.update_gist()`
- [ ] Re-linking the same `(from_id, to_id, rel)` triple is idempotent — no duplicate entries written to `lore.json`
- [ ] `rel` validated against `uses|tested_by|extends|alternative_to|requires` before any GitHub API call
- [ ] `to_id` gist must be a valid lore concept (description contains `[lore-concept]`) — linking to a non-lore gist is rejected before writing
- [ ] Max 20 links per concept enforced — attempting to add a 21st link returns a structured error; existing links are not modified
- [ ] Concurrent write safety is a known limitation: last writer wins; documented in `docs/architecture.md` as an accepted gap for Phase 2
- [ ] No direct HTTP calls in `gists.py` — all GitHub access goes through `gists_client.py`

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] Tests written + test-suite-architect approved
- [ ] docs/architecture.md, PROJECT.md, docstrings updated
- [ ] pytest --cov=lore --cov-fail-under=80 passes

---

## [LORE-014] Gists backend: rate_concept via GitHub comments

**Phase:** 2
**Priority:** high
**Effort:** M
**Agent:** python-mcp-engineer
**Phase item:** `PROJECT.md` §Development Phases > Phase 2 > `rate_concept` stores locally; stars surfaced as community signal; manual test: submit a concept, search for it, rate it

**As a** Claude Code agent
**I want to be able to** rate a community concept by posting a structured GitHub comment
**So that** quality feedback is community-visible and aggregatable without any central server

**Acceptance Criteria:**
- [ ] `rate_concept` posts a structured comment: `[lore-rating] {"outcome": N, "hours_saved": F, "notes": "..."}` — `hours_saved` and `notes` optional; `outcome` must be an integer 1–5; negative `hours_saved` explicitly rejected
- [ ] Edit-if-exists: identifies the current user's existing `[lore-rating]` comment by matching `author_login == gists_client.authenticated_login` (set at init in LORE-010); updates that comment rather than posting a new one
- [ ] `LORE_FREELOADER=true` disables comment posting entirely — `rate_concept` returns a no-op acknowledgement; reading community ratings via `get_concept` still works
- [ ] `LORE_FREELOADER` absent or any value other than `true`: community participation enabled
- [ ] `get_concept` fetches gist comments via `gists_client.list_comments()`, parses all `[lore-rating]` entries, computes `avg_rating` and `avg_hours_saved` from valid entries; malformed JSON in a `[lore-rating]` comment is logged to stderr and skipped — does not fail the whole fetch
- [ ] `search_concepts` does NOT fetch comments — ratings resolved on `get_concept` only
- [ ] Integration test: `submit_concept` creates a gist, `search_concepts` returns it by tag, `rate_concept` posts a comment, `get_concept` returns computed `avg_rating`

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] Tests written + test-suite-architect approved
- [ ] docs/architecture.md, PROJECT.md, docstrings updated
- [ ] pytest --cov=lore --cov-fail-under=80 passes
