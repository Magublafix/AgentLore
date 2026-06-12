# Sprints

Stories currently planned or in progress. One sprint block per sprint.

---

<!--
Sprint format:

## Sprint N — YYYY-MM-DD → YYYY-MM-DD
**Goal:** one sentence describing the sprint's focus
**Status:** planned | in-progress | done

### Stories
| ID | Title | Agent | Status | Tokens |
|----|-------|-------|--------|--------|
| LORE-001 | ... | python-mcp-engineer | in-progress | — |

### Notes
Anything relevant to this sprint: blockers, scope changes, deferred items.
-->

## Sprint 1 — 2026-05-29 → 2026-06-12
**Goal:** Deliver a working selfhosted backend (SQLite + Qdrant + FastAPI + Docker) wired to the MCP server, with agent-facing skills and a Stop hook — full Phase 1.
**Status:** done

### Stories
| ID | Title | Agent | Status | Tokens |
|----|-------|-------|--------|--------|
| LORE-001 | SQLite schema and Qdrant collection setup | python-mcp-engineer | done | 50785 |
| LORE-002 | Embedding pipeline | python-mcp-engineer | done | 54484 |
| LORE-003 | FastAPI selfhosted service | python-mcp-engineer | done | 69828 |
| LORE-004 | Docker image for selfhosted backend | devops-docker-engineer | done | 68874 |
| LORE-005 | MCP server with selfhosted routing | python-mcp-engineer | done | — |
| LORE-006 | Seed concept graph | python-mcp-engineer | done | — |
| LORE-007 | search-concepts skill | skill-engineer | done | — |
| LORE-008 | capture-concept skill | skill-engineer | done | — |
| LORE-009 | Stop hook: batch rating and session-end reflection | skill-engineer | done | — |

### Notes
- LORE-001 → LORE-002 → LORE-003 → LORE-004 → LORE-005 → LORE-006 is the backend dependency chain; must implement in order.
- LORE-007, LORE-008, LORE-009 (skills + hook) are parallel tracks — skill-engineer can start once LORE-005 MCP tool schemas are defined.
- LORE-003 has a compile-time dependency on `lore/core/scanner.py` (LORE-005); the AC notes this and LORE-003 tests should mock the scanner until LORE-005 delivers it.
- DoD Gate 4 for LORE-004: run `docker run --network none` to prove no runtime downloads.

---

## Sprint 2 — 2026-06-11 → 2026-06-25
**Goal:** Establish a Lore effectiveness baseline — build a restful-api.dev CLI twice (with and without Lore) and measure token + prompt reduction.
**Status:** done

### Stories
| ID | Title | Agent | Status | Tokens |
|----|-------|-------|--------|--------|
| LORE-015 | Define radev CLI scope and test suite | test-suite-architect | done | — |
| LORE-016 | Run 1 — Implement radev CLI without Lore | general-purpose | done | 163,279 |
| LORE-017 | Run 2 — Implement radev CLI with Lore concepts | general-purpose | done | 150,867 |

### Notes
- LORE-015 must complete before either run — both runs target the same fixed test suite.
- LORE-016 must complete and `lore:wrapup` must fire before LORE-017 starts; Run 2 depends on captured concepts.
- Token count = total session tokens (input + output) reported at session end via `/cost`.
- Prompt count = number of user turns until all 9 tests in `samples/radev/tests/test_radev_cli.py` pass.
- DoD Gates 3 and 4 waived for benchmark stories — no Lore infrastructure changed; `pytest --cov=lore` not applicable.

---

## [LORE-015] Define radev CLI scope and test suite

**Phase:** Benchmark
**Priority:** high
**Effort:** S
**Agent:** test-suite-architect
**Phase item:** N/A — benchmark sprint

**As a** Lore developer
**I want to be able to** reference a fixed CLI specification and a runnable test suite before each benchmark run
**So that** both runs target an identical definition of done and results are directly comparable

**Acceptance Criteria:**
- [x] `samples/radev/tests/test_radev_cli.py` committed — 9 tests across `list`, `create`, `get`, `update`, `delete`
- [x] Tests invoke CLI as `radev <command>` via `subprocess.run`; JSON on stdout; non-zero exit on error
- [x] `samples/radev/README.md` documents CLI interface (commands, flags, output format, install steps)
- [x] `samples/radev/benchmarks/run.py` committed — repeatable agentic benchmark runner (Anthropic SDK loop)
- [x] Test suite passes against a reference implementation before Run 1 begins

**DoD:**
- [x] AC above met — tokens recorded
- [x] `pytest samples/radev/tests/` passes against a reference implementation

---

## [LORE-016] Run 1 — Implement radev CLI without Lore

**Phase:** Benchmark
**Priority:** high
**Effort:** M
**Agent:** general-purpose
**Phase item:** N/A — benchmark sprint

**As a** Lore developer
**I want to be able to** implement the radev CLI in a fresh Claude Code session without Lore skills active
**So that** we establish a baseline token count and prompt count, and populate the concept graph via `lore:wrapup` at session end

**Acceptance Criteria:**
- [x] `python samples/radev/benchmarks/run.py --run 1` completes without error
- [x] Agent implements CLI without Lore search (no `search_concepts` tool available)
- [x] All 9 tests in `samples/radev/tests/test_radev_cli.py` pass at end of run
- [x] After `submit`, agent applies `capture-concept` SKILL.md and calls `submit_concept` in the same loop
- [x] `samples/radev/results/run1.md` written with turns, input/output tokens, elapsed, test result

**DoD:**
- [x] AC above met — tokens recorded (163,279)
- [ ] `samples/radev/results/run1.md` committed

---

## [LORE-017] Run 2 — Implement radev CLI with Lore concepts

**Phase:** Benchmark
**Priority:** high
**Effort:** M
**Agent:** general-purpose
**Phase item:** N/A — benchmark sprint

**As a** Lore developer
**I want to be able to** implement the same radev CLI in a fresh Claude Code session with Lore concepts from Run 1 available
**So that** we can measure how much Lore reduces tokens and prompts compared to the baseline

**Acceptance Criteria:**
- [x] `python samples/radev/benchmarks/run.py --run 2` completes without error
- [x] Script queries `~/.lore/lore.db` and injects matching concepts into agent system prompt
- [x] Agent implements CLI from scratch in a clean temp directory with Lore concepts in context
- [x] All 9 tests in `samples/radev/tests/test_radev_cli.py` pass at end of run
- [x] `samples/radev/results/run2.md` written with turns, input/output tokens, elapsed, test result
- [x] `samples/radev/results/comparison.md` written with delta table (Run 1 vs Run 2)

**DoD:**
- [x] AC above met — tokens recorded (150,867)
- [ ] `samples/radev/results/run2.md` and `samples/radev/results/comparison.md` committed
