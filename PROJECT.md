# Lore — Project Description

## Vision

A typed, linked knowledge graph for AI coding agents. Agents search
for reusable concepts — projects, patterns, tools, test strategies —
each tagged with "use when" metadata and linked to related concepts.
When an agent retrieves a project blueprint, it gets the full proven
path: architecture decisions, linked tool concepts, test strategies,
and known gotchas. All accumulated from prior agent sessions.

The problem it solves: agents repeatedly spend hours solving
architectural problems that other agents have already solved. Web
search finds libraries. Lore finds proven blueprints — and the full
graph of related decisions that surround them.

**Example:** An agent searching "build a CLI for a REST API" retrieves
not just "use openapi-generator" but a full project concept linked to
command structure patterns, auth handling, pagination, and a REST CLI
test strategy — the product of hours of prior agent work, reusable
in minutes.

---

## Concept Types

Concepts are typed nodes in a linked graph. Each type has a different
content structure optimized for how agents consume it.

| Type | Contains | Example |
|---|---|---|
| `project` | Full architectural blueprint: structure, key decisions, known gotchas | REST CLI around a REST API |
| `pattern` | A reusable design decision with context and consequences | Pagination cursor pattern |
| `tool` | When/how to use a specific tool or library | openapi-generator setup |
| `testing` | Test strategy for a specific context | Testing CLI commands against a live API |
| `architecture` | Structural approach for a recurring shape of problem | Layered CLI command hierarchy |

---

## Data Model

### concepts table

```sql
concept_id           TEXT PRIMARY KEY,   -- UUID
name                 TEXT NOT NULL,
type                 TEXT NOT NULL,      -- project|pattern|tool|testing|architecture
content              TEXT NOT NULL,      -- the blueprint, pattern, or strategy (markdown)
language             TEXT,              -- java, python, typescript, generic, etc.
when_to_use          TEXT NOT NULL,     -- natural language (embedded for search)
dont_use_when        TEXT,             -- known anti-cases
tags                 TEXT,             -- JSON array
source_url           TEXT,             -- GitHub, docs, prior agent session, etc.
author               TEXT,
avg_rating           REAL DEFAULT 0,
usage_count          INTEGER DEFAULT 0,
time_saved_avg_hours REAL,             -- reported by raters: hours saved vs. from scratch
created_at           TEXT,
embedding            BLOB              -- sqlite-vec float32 vector on when_to_use + name
```

### links table

```sql
link_id   TEXT PRIMARY KEY,
from_id   TEXT REFERENCES concepts,
to_id     TEXT REFERENCES concepts,
rel       TEXT NOT NULL,    -- uses|tested_by|extends|alternative_to|requires
label     TEXT              -- human-readable edge description
```

### ratings table

```sql
rating_id    TEXT PRIMARY KEY,
concept_id   TEXT REFERENCES concepts,
session_id   TEXT,
outcome      INTEGER,   -- 1-5
hours_saved  REAL,      -- estimated hours saved vs. building from scratch
notes        TEXT,
rated_at     TEXT
```

### session_usage table

```sql
session_id   TEXT,
concept_id   TEXT,
used_at      TEXT
```

---

## Architecture

**Three layers:**

1. **MCP server** — exposes all tools as MCP endpoints. Works in
   Cursor, Windsurf, Cline, Claude Code, and any MCP-compatible
   runtime. Delegates to whichever backend is configured.

2. **Backend (configurable)** — pluggable via env vars. Three options
   described below. The MCP tool interface is identical regardless of
   which backend is active.

3. **Claude Code skill** — a thin wrapper over the MCP server that
   adds session tracking and a Stop hook. When a session ends, the
   hook collects all concepts consumed and presents a batch rating
   prompt — no explicit agent discipline required.

---

## Backend Options

Three backends, each suited to a different use case. Configured via
`LORE_BACKEND` env var. The MCP tool interface does not change.

### Backend 1 — Self-hosted (team use)

```
LORE_BACKEND=selfhosted
LORE_HOST=http://localhost:8765   # or team server
```

A single Docker container running a FastAPI service backed by Qdrant
(vector search) and SQLite (concept content + links). Can run on
localhost for a single developer or on a shared team server. Full
semantic search. Concepts are private to the team.

```
docker run -p 8765:8765 lore/selfhosted
```

**Tradeoffs:** requires Docker. No community sharing — concepts stay
within the team. Best for internal patterns, company conventions, and
proprietary solutions that shouldn't be public.

---

### Backend 2 — GitHub Gists (community, tag search)

```
LORE_BACKEND=gists
LORE_GITHUB_TOKEN=ghp_...
```

No infrastructure. Each concept is a public gist with two files:

- `concept.md` — the content (blueprint, pattern, or strategy)
- `lore.json` — structured metadata:

```json
{
  "type": "project",
  "language": "generic",
  "when_to_use": "...",
  "dont_use_when": "...",
  "tags": ["cli", "rest-api"],
  "links": [
    { "gist_id": "abc123", "rel": "uses", "label": "openapi-generator setup" }
  ]
}
```

Gist descriptions include `[lore-concept]` for discovery via GitHub
search API. `search_concepts` queries GitHub by tag match — no local
cache, no embeddings. GitHub stars are the community rating signal.
Fine-grained ratings (outcome, hours_saved) remain local only.

`submit_concept` creates a gist. `link_concepts` updates `lore.json`
on the source gist. Everything is human-readable on github.com.

**Tradeoffs:** no infrastructure, community already has GitHub
accounts, versioning is free. Search is tag-based only — no semantic
"describe your problem" matching. Works at any scale since GitHub
handles the storage and the search is on-demand.

---

### Backend 3 — GitHub Gists + semantic search server (community, full search)

```
LORE_BACKEND=gists
LORE_GITHUB_TOKEN=ghp_...
LORE_SEMANTIC_URL=https://search.lore.dev   # or self-hosted
```

Extends Backend 2. GitHub Gists remain the source of truth for
content and publishing. An optional semantic search server indexes
the public gist corpus and serves vector search queries. When
`LORE_SEMANTIC_URL` is set, `search_concepts` sends the natural
language problem to the server instead of the GitHub tag API.

```
agent → MCP client → semantic search server → ranked results
                             ↑
                   GitHub Gists (source of truth)
                   indexed + embedded server-side (Qdrant)
```

The semantic server is independently deployable — teams can
self-host it for their own gist corpus, or use a shared public
instance. It watches for new/updated `[lore-concept]` gists,
embeds them, and stores fine-grained community ratings.

**Tradeoffs:** requires a running semantic server (self-hosted or
shared). Adds server-side ratings aggregation across all users.
Backend 2 (tag search) remains the fallback if the server is
unreachable.

---

## MCP Tools

### search_concepts

```
Input:
  problem   str        — natural language description of what you're building
  type      str?       — filter by concept type (project|pattern|tool|testing|architecture)
  language  str?       — filter by language
  limit     int = 5

Output: ranked list of concepts, each with:
  concept_id, name, type, when_to_use, content (markdown),
  avg_rating, usage_count, time_saved_avg_hours,
  links: [{ rel, label, concept_id, name, type, when_to_use }]
```

Returns the matched concept **plus its full linked graph** — one call
gives the agent the blueprint and all related concepts. Logs usage
to session_usage.

### get_concept

```
Input:  concept_id str
Output: full concept record + all links (both directions)
```

Retrieve a specific concept by ID, including incoming links
(what links to this) and outgoing links (what this links to).

### submit_concept

```
Input:
  name          str
  type          str         — concept type
  content       str         — markdown blueprint, pattern, or strategy
  language      str?
  when_to_use   str
  dont_use_when str?
  tags          str[]
  source_url    str?
  links         [{to_id, rel, label}]?   — link to existing concepts

Output: concept_id, confirmation
```

Before writing, `submit_concept` runs a content scan across all text fields:

- **Credential patterns** — API keys, tokens, Bearer strings, long hex/base64 strings
- **Internal URL patterns** — `localhost` (non-example), `.internal`, `.corp`, `.local` domains
- **Configurable blocklist** — regex patterns from `LORE_BLOCK_PATTERNS` env var for team-specific sensitive strings

On a match the tool rejects with a structured error identifying which field triggered
and why, so the agent can generalize and resubmit. The scan cannot be bypassed
— it runs regardless of `LORE_CAPTURE_MODE`. In `confirm` mode the user sees
the concept before submission; in `auto` mode the scan is the only gate, so it
must pass cleanly.

### link_concepts

```
Input:
  from_id   str
  to_id     str
  rel       str    — uses|tested_by|extends|alternative_to|requires
  label     str

Output: link_id, confirmation
```

Add a link between two existing concepts. Agents can call this
after discovering a relationship during a task.

### rate_concept

```
Input:
  concept_id   str
  outcome      int     — 1-5
  hours_saved  float?  — estimated hours saved vs. building from scratch
  notes        str?
  session_id   str

Output: updated avg_rating, updated time_saved_avg_hours
```

### sync_to_community

```
Input:  community_url str, api_key str
Output: pushed_count, pulled_count
```

Pushes local concepts, links, and ratings to the community backend.
Pulls community concepts not yet in local store. Run manually or
on a schedule.

---

## Claude Code Skill Layer

### search-concepts skill

Located at `.claude/skills/search-concepts.md`. When invoked:

1. Calls `search_concepts` MCP tool with the agent's problem
2. Appends returned concept IDs to `~/.lore/session.json`
3. Returns the full concept graph to the agent

### capture-concept skill

Located at `.claude/skills/capture-concept.md`. Called by the agent at any
point during a task when it believes it has encountered something worth
preserving. The skill embeds structured reflection criteria to help the agent
evaluate quality before submitting.

**Reflection criteria** (embedded in the skill prompt):
- Is this generalizable beyond this specific codebase or task?
- Is there a gotcha, surprise, or non-obvious constraint another agent would rediscover?
- Would this save a future agent meaningful time?

**Mandatory generalization step** — before constructing the submission the skill
instructs the agent:

> Replace all codebase-specific names, internal URLs, credentials, schema
> details, and domain-specific terminology with generic placeholders. You are
> capturing the *pattern*, not the *implementation*. If you cannot describe
> this concept without referencing specifics, it is not ready to submit.

If the concept passes, behaviour depends on `LORE_CAPTURE_MODE`:

| Mode | Behaviour |
|---|---|
| `confirm` (default) | Agent surfaces the concept to the user: "I want to capture this — approve?" User approves or rejects before `submit_concept` is called. |
| `auto` | Agent calls `submit_concept` directly without user confirmation. |

Agents call this skill by judgment — there is no automatic trigger mid-task.
The Stop hook (below) provides the session-end prompt that surfaces concepts
the agent may have noted but not yet captured.

### Stop hook

Registered in `.claude/settings.json`. Fires when a session ends:

1. Reads `~/.lore/session.json` for concept IDs used this session
2. If any concepts were used, presents a batch rating prompt:

```
This session you used these Lore concepts:
• REST CLI Project Blueprint (project)
• openapi-generator setup (tool)
• REST CLI test strategy (testing)

For each, how many hours did it save vs. building from scratch?
Rate usefulness 1-5.
```

3. Calls `rate_concept` for each response
4. Injects a session-end reflection prompt:

```
Reflect on this session — did you encounter any non-trivial patterns,
gotchas, or solutions that would save another agent meaningful time?
If yes, call capture-concept for each one before closing.
```

5. Agent responds: calls `capture-concept` for any qualifying concepts, or skips
6. Clears the session file

---

## Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| MCP server | Python + FastMCP | Official MCP SDK, fast iteration |
| Backend 1 storage | SQLite (content + links) + Qdrant (vectors) | Clean separation; Qdrant has a first-class Docker image |
| Backend 1 container | Docker (single image) | Simplest self-host story — one command |
| Backend 2 storage | GitHub Gists | No infrastructure, versioning free, human-readable |
| Backend 2 search | GitHub Search API (tag match) | On-demand, no local cache needed |
| Backend 3 search | FastAPI + Qdrant (self-hostable) | Vector search at scale; gists stay source of truth |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | Fully offline in Backend 1; server-side in Backend 3 |
| Claude Code skill | Bash + markdown skill file | Leverages Stop hook |
| Session tracking | JSON file (~/.lore/session.json) | Simple, hook-compatible |
| Capture mode | `LORE_CAPTURE_MODE=confirm\|auto` env var | Confirm is safe default; auto unlocks autonomous growth |
| Leak prevention | `LORE_BLOCK_PATTERNS` env var (regex list) | Team-specific sensitive strings blocked at submit time |

---

## Seed Concept Graph

Validates the full retrieval path on first run. Five linked concepts
covering the REST CLI blueprint end-to-end.

```
[project] REST CLI around a REST API
  when_to_use:    building a typed CLI client for an existing REST API
  dont_use_when:  the API has no OpenAPI spec; the CLI is one-off scripting
  links:
    → [tool]         openapi-generator setup          (uses)
    → [architecture] CLI command hierarchy pattern    (uses)
    → [testing]      REST CLI test strategy           (tested_by)
    → [pattern]      Pagination cursor handling       (uses)
    → [pattern]      Auth token storage in CLI tools  (uses)
```

Each linked concept is a full entry in the graph, independently
searchable and reusable in other project blueprints.

---

## Development Phases

Phases describe **build order**, not deployment stages. All three
backends are built incrementally and remain independently useful.

### Phase 1 — Backend 1: Self-hosted team store

Build the MCP server and the self-hosted backend. This is the fastest
path to a working system with full semantic search.

- [x] Qdrant + SQLite schema (concepts, links, ratings, session_usage)
- [x] Embedding pipeline (sentence-transformers, all-MiniLM-L6-v2)
- [x] FastAPI service wrapping Qdrant + SQLite
- [x] Docker image: single container, `docker run -p 8765:8765 lore/selfhosted`
- [x] MCP server with `LORE_BACKEND=selfhosted` routing:
      search_concepts, get_concept, submit_concept, link_concepts, rate_concept
- [ ] Seed the REST CLI concept graph (5 linked concepts)
- [ ] Claude Code search-concepts skill file
- [ ] capture-concept skill file (confirm/auto mode, structured reflection criteria)
- [ ] Stop hook: batch rating prompt (hours_saved) + session-end reflection prompt
- [ ] Manual test: agent searches, follows links, rates at session end

### Phase 2 — Backend 2: GitHub Gists (community, tag search)

Add the Gists backend. No infrastructure required. Validate the
community sharing loop with tag-based search.

- [ ] GitHub API client (gist create, update, search by description marker)
- [ ] `LORE_BACKEND=gists` routing in MCP server
- [ ] `submit_concept` creates a public gist
- [ ] `link_concepts` updates `lore.json` on the source gist
- [ ] `search_concepts` queries GitHub Search API by tags
- [ ] `rate_concept` stores locally; stars surfaced as community signal
- [ ] Manual test: submit a concept, search for it, star it, rate it

### Phase 3 — Backend 3: Semantic search server (community, full search)

Add the optional semantic server. GitHub Gists remain the source of
truth. The server indexes the public corpus and serves vector search.

- [ ] FastAPI + Qdrant semantic server (independently deployable)
- [ ] Gist watcher: polls for new/updated `[lore-concept]` gists,
      embeds and indexes them
- [ ] `LORE_SEMANTIC_URL` routing in MCP server — when set, overrides
      GitHub tag search with vector search against the server
- [ ] Server-side ratings aggregation (outcome + hours_saved) across users
- [ ] API key auth (one per GitHub user, issued on first gist publish)
- [ ] Deduplication: flag near-duplicate concepts on publish
- [ ] Graceful fallback: if server unreachable, fall back to Backend 2

### Phase 4 — Publishing

- [ ] Publish MCP server to PyPI as `lore-mcp`
- [ ] Publish self-hosted Docker image to Docker Hub as `lore/selfhosted`
- [ ] Hosted public semantic search instance
- [ ] Concept graph browser (read-only web UI)
- [ ] Flip `LORE_CAPTURE_MODE` default to `auto` — agent-autonomous publishing
      without user confirmation (Phase 1 capture-concept skill supports both modes;
      this phase makes `auto` the recommended default)

---

## Project Structure

```
lore/
├── mcp/
│   ├── server.py               # FastMCP entry point
│   ├── router.py               # backend routing (reads LORE_BACKEND)
│   ├── backends/
│   │   ├── selfhosted.py       # Backend 1: Qdrant + SQLite client
│   │   ├── gists.py            # Backend 2: GitHub Gists client
│   │   └── semantic.py         # Backend 3: semantic server client
│   ├── embeddings.py           # sentence-transformers wrapper (Backend 1)
│   └── models.py               # Concept, Link, Rating dataclasses
├── selfhosted/
│   ├── api.py                  # FastAPI service (Backend 1)
│   ├── db.py                   # SQLite schema + operations
│   ├── schema.sql
│   └── Dockerfile
├── semantic-server/
│   ├── api.py                  # FastAPI semantic search service (Backend 3)
│   ├── watcher.py              # Gist watcher + indexer
│   └── Dockerfile
├── skills/
│   ├── search-concepts.md      # Claude Code skill — search + session tracking
│   ├── capture-concept.md      # Claude Code skill — agent-initiated concept submission
│   └── hooks/
│       └── stop.sh             # Stop hook — batch rating + session-end reflection prompt
├── seed/
│   └── concepts.json           # Seed concept graph (REST CLI + 4 linked)
├── tests/
├── docker-compose.yml          # selfhosted stack (Backend 1)
├── pyproject.toml
└── CLAUDE.md                   # this file
```

---

## Key Constraints

- The MCP tool interface (`search_concepts`, `submit_concept`, etc.)
  is identical across all three backends. Switching backend is a
  config change only — no agent-side changes required.
- Backend 1 embeddings run fully offline — no API calls.
- Backend 2 requires only a GitHub token — no servers, no Docker.
- Backend 3 semantic server is always optional and always falls back
  to Backend 2 tag search if unreachable.
- `search_concepts` always returns linked concepts in the same call —
  agents should never need a second round-trip to discover the graph.
- `hours_saved` is optional but encouraged — it's the strongest
  signal in the rating system.
- `submit_concept` content scan is mandatory and cannot be bypassed — it runs
  regardless of `LORE_CAPTURE_MODE`. In `auto` mode this is the only leak gate.
- `confirm` mode is strongly recommended for teams on sensitive codebases —
  human review is the final guard the scan cannot replace.
- `LORE_BLOCK_PATTERNS` accepts a comma-separated list of regex strings for
  team-specific sensitive terms (internal service names, proprietary identifiers).
- Backends are not mutually exclusive in future: a team could run
  Backend 1 for private concepts and Backend 2/3 for public ones —
  but multi-backend fan-out is out of scope until Phase 4.
