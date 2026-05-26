# Lore — Claude Code Instructions

These rules are **mandatory** and override default behavior for every task in this project.

---

## Project Overview

Lore is a typed, linked knowledge graph for AI coding agents. Full spec: `PROJECT.md`.

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

Project structure: `lore/mcp/`, `lore/selfhosted/`, `lore/semantic-server/`, `lore/skills/`, `lore/seed/`, `lore/tests/`

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
| `PROJECT.md` | Architecture decisions, schema changes, new tools |
| `README.md` | New setup steps, changed ports, new dependencies |
| Docstrings | Any public function/class added or changed |

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

## Key Constraints

- The MCP tool interface (`search_concepts`, `submit_concept`, etc.) must be identical across all backends — switching backend is a config change only.
- Backend 1 embeddings run fully offline — no external API calls.
- `search_concepts` always returns linked concepts in a single call — agents must never need a second round-trip to discover the graph.
- `hours_saved` is optional in ratings but encouraged — it is the strongest signal in the rating system.
