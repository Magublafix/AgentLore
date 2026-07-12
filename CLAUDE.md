# Lore — Claude Code Instructions

These rules are **mandatory** and override default behavior for every task in this project.

---

## Project Overview

Lore is a typed, linked knowledge graph for AI coding agents. Full spec: `PROJECT.md`.

---

## Story Lifecycle

Stories move through three files as they progress:

| File | Contains | When to update |
|------|----------|----------------|
| `backlog.md` | Open stories, prioritized top-to-bottom | Add new stories here; re-order by priority |
| `sprints.md` | Planned and in-progress stories for the current sprint | Move from backlog when sprint is planned; update status during work |
| `features.md` | Implemented and shipped stories | Move here from sprints.md when all DoD gates pass |

**Rules:**
- Stories only move forward — backlog → sprints → features. Never backwards.
- `features.md` is append-only. Never edit or remove entries.
- When starting a sprint, move chosen stories from `backlog.md` to a new sprint block in `sprints.md`.
- When a story's DoD passes, move it to `features.md` and mark it done in `sprints.md`.

### Story Format

Every story — in backlog, sprints, and features — uses this format:

```markdown
## [LORE-NNN] Title

**Phase:** N
**Priority:** high | medium | low
**Effort:** S | M | L
**Agent:** <primary agent responsible>
**Phase item:** PROJECT.md §Development Phases > Phase N > checklist item text

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
```

**Rules:**
- The user story line **must** follow the form: `As a [role] I want to be able to [action] so that [benefit]`. No other phrasing.
- IDs are sequential and never reused: LORE-001, LORE-002, …
- In `features.md`, replace the DoD checklist with: `**What changed:**` and `**Implementation notes:**`

---

## Stack Reference

| Layer | Choice |
|-------|--------|
| MCP server | Python + FastMCP |
| Backend 1 storage | SQLite + Qdrant (vectors) |
| Backend 2/3 | GitHub Gists + optional semantic server |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| Claude Code skill | Bash + markdown skill file |
| Session tracking | JSON file (~/.lore/session.json) |

Project structure: `lore/mcp/`, `lore/selfhosted/`, `lore/semantic_server/`, `lore/server/`, `lore/seed/`, `lore/tests/`, `skills/`

---

## Definition of Done (DoD)

A story or task is **not done** until all four gates pass. Do not mark anything complete or move to the next story until every gate is checked.

### Gate 1 — Acceptance Criteria
Every acceptance criterion in the task must be met. Check `PROJECT.md` development phases for the relevant checklist items before closing.

After confirming all AC are met, run `/cost` and record the token count — you will need it for the phase summary.

### Gate 2 — Tests
After writing or modifying any Python code:
1. Write unit tests covering the new/changed logic (happy path + edge cases).
2. Invoke `test-suite-architect` agent to review the tests.
3. Address any concerns raised. Only proceed when the agent explicitly approves.

Use `subagent_type: "test-suite-architect"` (it is a named agent type).

### Gate 3 — Documentation
Before the final commit, update every affected doc:

| Doc | Update when |
|-----|-------------|
| `docs/architecture.md` | New component, changed runtime flow, new deployment unit, new ADR, updated risk or quality scenario |
| `PROJECT.md` | Phase checklist item completed, constraint added or changed |
| `README.md` | New setup steps, changed ports, new dependencies |
| Docstrings | Any public function/class added or changed |

**arc42 update rules:**
- New building block → update Section 5
- New runtime flow → update Section 6
- New deployment unit → update Section 7
- Significant architectural decision → add a row to Section 9 (ADR table); create `docs/adr/ADR-NNN.md` for complex decisions
- New risk identified → add a row to Section 11
- New term → add to Section 12 Glossary

Docs and code go in the **same commit**.

### Gate 4 — Verification
After the final commit:
1. Run the test suite: `pytest lore/tests/ --cov=lore --cov-fail-under=80`
2. Verify MCP server starts cleanly: `python -m lore.mcp.server`
3. For Backend 1 changes: verify Docker stack starts: `docker compose up -d`

---

## Phase Completion Gate

When a development phase is declared done (all checklist items closed, all DoD gates passed), produce a phase summary. This is mandatory.

### Steps
1. Run `pytest --cov=lore --cov-report=term-missing` and capture the output.
2. Create `docs/phases/phase-N-summary.md`.
3. Commit with the message `docs: Phase N summary`.

### Summary structure

```markdown
# Phase N — Summary
**Period:** YYYY-MM-DD → YYYY-MM-DD   **Status:** ✅ Complete

## Delivered
| Item | Description | Tokens used |
|------|-------------|-------------|

## What Works Now
<!-- 3-5 sentences: what an agent can now do that it couldn't before -->

## Code Coverage
<!-- paste pytest --cov output -->

## Known Gaps / Deferred
<!-- anything deferred or deliberately descoped -->

## Next Phase — Candidate Items
<!-- top items from next phase checklist -->
```

---

## Agent Delegation

Always delegate — never implement these yourself:

| Work type | Agent |
|-----------|-------|
| Python, FastMCP, SQLite, Qdrant, GitHub API, embeddings | `python-mcp-engineer` |
| Claude Code skill files, hooks, settings.json, session tracking | `skill-engineer` |
| Data modeling, graph design, embedding strategy, backend architecture | `ai-data-specialist` |
| Tests, coverage, edge cases, test data strategy | `test-suite-architect` |
| Docker, docker-compose, CI/CD | `devops-docker-engineer` |
| Architecture review, design decisions | `software-architect` |

### How to invoke agents

Use the agent name directly as `subagent_type`:

| Agent | `subagent_type` |
|-------|-----------------|
| `python-mcp-engineer` | `"python-mcp-engineer"` |
| `skill-engineer` | `"skill-engineer"` |
| `ai-data-specialist` | `"ai-data-specialist"` |
| `test-suite-architect` | `"test-suite-architect"` |
| `devops-docker-engineer` | `"devops-docker-engineer"` |
| `software-architect` | `"software-architect"` |

Fall back to `subagent_type: "general-purpose"` only if a direct agent invocation fails.

### Stakeholder consultation before significant decisions

Before implementing, consult relevant agents in **parallel** (background) and summarize findings to the user:

| Decision type | Consult |
|---------------|---------|
| Backend architecture / storage | `ai-data-specialist` + `software-architect` + `python-mcp-engineer` |
| MCP tool interface design | `ai-data-specialist` + `python-mcp-engineer` |
| Embedding / search strategy | `ai-data-specialist` + `python-mcp-engineer` |
| Docker / deployment | `devops-docker-engineer` + `software-architect` |
| Skill / hook design | `skill-engineer` + `software-architect` |
| Test strategy | `test-suite-architect` + `python-mcp-engineer` |

---

## Benchmark & Test Runner Design

**Skills are the single source of truth for agent behavior guidance.**

Any code that drives a Lore phase (capture, search, wrapup) must load the skill file — never duplicate its guidance inline. Inline copies drift silently and bypass fixes made to the skill.

| Phase | Skill file | How to load |
|-------|-----------|-------------|
| Search | `skills/search-concepts/SKILL.md` | `_load_skill("search-concepts")` |
| Capture | `skills/capture-concept/SKILL.md` | `_load_skill("capture-concept")` |
| Wrapup / rating | `skills/wrapup/SKILL.md` | `_load_skill("wrapup")` |

**Rules:**
- A benchmark runner that builds its own wrapup prompt from scratch is wrong. Load the skill.
- If a runner needs extra context (run number, concept list), append it to the loaded skill — do not replace the skill with a summary of it.
- Any change to agent behavior (rating guidance, reflection criteria, capture standards) goes in the skill file first. The runner inherits it automatically.
- Review note: if you see hardcoded rating scales (`1=irrelevant, 5=excellent`) in a runner script, that is a duplication violation — move it to the skill.

---

## Key Constraints

- The MCP tool interface (`search_concepts`, `submit_concept`, etc.) must be identical across all backends — switching backend is a config change only.
- Backend 1 embeddings run fully offline — no external API calls.
- `search_concepts` always returns linked concepts in a single call — agents must never need a second round-trip to discover the graph.
- `hours_saved` is optional in ratings but encouraged — it is the strongest signal in the rating system.
