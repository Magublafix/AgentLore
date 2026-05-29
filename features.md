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
