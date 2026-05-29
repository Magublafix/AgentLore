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
