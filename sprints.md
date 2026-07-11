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

## Sprint 3 — 2026-06-13 → 2026-06-27
**Goal:** Second Lore effectiveness benchmark — implement a 3D-printable text CLI (text2stl) with and without Lore, measuring token reduction on a geometry-heavy task.
**Status:** done

### Stories
| ID | Title | Agent | Status | Tokens |
|----|-------|-------|--------|--------|
| LORE-018 | Define text2stl CLI scope and test suite | test-suite-architect | done | — |
| LORE-019 | Run 1 — no Lore, hard task, capture on discovery | general-purpose | done | — |
| LORE-020 | Run 2 — Lore ON, unrated concepts from Run 1 | general-purpose | done | — |
| LORE-021 | Run 3 — Lore ON, concepts rated after Runs 1+2 wrapup | general-purpose | done | — |
| LORE-022 | Runs 4–10 — Lore ON, progressively rated knowledge base | general-purpose | done | — |

### Notes
- LORE-018 must complete before any run — all runs use the same 13-test suite.
- 10-run progressive design: same hard task, same 40-turn budget, 10 times.
- What changes each run: (a) Lore content grows organically (no seed), (b) concepts get rated via wrapup phase after each run.
- Tests: does Lore help at all? (R1→R2)  does accumulated knowledge compound? (R2→R5+)  does rating improve relevance? (unrated early → rated later)
- All runs use forced 15-turn capture phase after main loop — concepts captured even on failure.
- Run 1 attempt on 2026-06-13 hit MAX_TURNS=50 without approach hint. Redesigned to progressive structure; seed concept removed after post-IoU-fix experiments.
- DoD Gates 3 and 4 waived for benchmark stories (same as Sprint 2).

---

## Sprint 4 — 2026-07-09 → 2026-07-16
**Goal:** Document and explain the multi-series stlgen benchmark — aggregate results from 10 series × 10 runs, produce a benchmark README with methodology, findings, and conclusions.
**Status:** done

### Stories
| ID | Title | Agent | Status | Tokens |
|----|-------|-------|--------|--------|
| LORE-026 | Aggregate and analyze multi-series benchmark results | general-purpose | done | 73,680 |
| LORE-027 | Write benchmark README with methodology and findings | general-purpose | done | 43,911 |

### Notes
- LORE-026 first — analysis informs the README narrative.
- DoD Gates 3 and 4 waived for benchmark stories (no Lore infrastructure changed).

---

## Sprint 5 — 2026-07-17 → 2026-07-28
**Goal:** Wire up CI/CD — automated test runs, Docker image builds, and Renovate dependency updates — before beginning Phase 2 feature work.
**Status:** done

### Stories
| ID | Title | Agent | Status | Tokens |
|----|-------|-------|--------|--------|
| LORE-023 | GitHub Actions — CI test pipeline | devops-docker-engineer | done | 35,488 |
| LORE-024 | GitHub Actions — Docker image build and push | devops-docker-engineer | done | 29,142 |
| LORE-025 | Renovate — automated dependency updates | devops-docker-engineer | done | 32,431 |

### Notes
- LORE-023 (tests) should land first; LORE-024 (Docker build) can follow independently.
- LORE-025 (Renovate) is independent — can run at any time during the sprint.
- DoD Gate 4 verification: run `pytest --cov=lore --cov-fail-under=80` locally to confirm CI mirrors the same gate.

---

## Sprint 6 — 2026-07-10 → 2026-07-10
**Goal:** Implement the GitHub Gists backend (Phase 2) — a thin API client plus all five MCP tools — so agents can share and discover concepts with no local infrastructure.
**Status:** done

### Stories
| ID | Title | Agent | Status | Tokens |
|----|-------|-------|--------|--------|
| LORE-010 | GitHub Gists API client | python-mcp-engineer | done | 38,179 |
| LORE-011 | Gists backend: submit_concept and get_concept | python-mcp-engineer | done | 50,322 |
| LORE-012 | Gists backend: search_concepts via GitHub Search API | python-mcp-engineer | done | 25,744 |
| LORE-013 | Gists backend: link_concepts | python-mcp-engineer | done | 58,114 |
| LORE-014 | Gists backend: rate_concept via GitHub comments | python-mcp-engineer | done | 67,312 |

### Notes
- LORE-010 is the foundation — all other stories depend on `gists_client.py` being in place first.
- LORE-011 (submit/get) must land before LORE-012 (search) and LORE-013 (link) — they both build on gist structure and routing.
- LORE-014 (rate) depends on `list_comments` / `create_comment` from LORE-010 and the get_concept comment aggregation from LORE-011.
- LORE-012 and LORE-013 can run in parallel once LORE-011 is done.
- All stories target `lore/mcp/backends/` and route through `router.py` via `LORE_BACKEND=gists`.

---

## [LORE-018] Define text2stl CLI scope and test suite

**Phase:** Benchmark
**Priority:** high
**Effort:** S
**Agent:** test-suite-architect
**Phase item:** N/A — benchmark sprint

**As a** Lore developer
**I want to be able to** reference a fixed CLI specification and runnable test suite before each benchmark run
**So that** both runs target an identical definition of done and results are directly comparable

**Acceptance Criteria:**
- [x] `samples/stlgen/tests/test_text2stl_cli.py` committed — 13 tests across invocation, validation, STL validity, dimensions, character shapes
- [x] Tests invoke CLI as `text2stl <string> -o <path>` via `subprocess.run`
- [x] STL validity tests use `trimesh` (watertight, positive volume, no degenerate triangles)
- [x] Character shape test uses mid-height cross-section IoU ≥ 0.25 vs PIL-rendered reference
- [x] `samples/stlgen/README.md` documents CLI interface and test coverage
- [x] `samples/stlgen/benchmarks/run.py` committed — same structure as radev benchmark runner

**DoD:**
- [x] AC above met — tokens recorded
- [ ] Test suite passes against a reference implementation before Run 1 begins

---

## [LORE-019] Run 1 — no Lore, hard task, capture on discovery

**Phase:** Benchmark
**Priority:** high
**Effort:** L
**Agent:** general-purpose
**Phase item:** N/A — benchmark sprint

**As a** Lore developer
**I want to be able to** attempt text2stl without Lore in 40 turns, capturing concepts as I work
**So that** we establish a baseline and populate Lore for subsequent runs, even if the task fails

**Acceptance Criteria:**
- [ ] `python samples/stlgen/benchmarks/run.py --run 1` completes without error
- [ ] Agent has no `search_concepts` tool; calls `submit_concept` incrementally during session
- [ ] Forced 15-turn capture phase runs after main loop (win or lose)
- [ ] `samples/stlgen/results/run1.md` written with turns, tokens, test result, concepts captured

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] `samples/stlgen/results/run1.md` committed
- [ ] `lore:wrapup` run after this story to rate captured concepts before Run 2

---

## [LORE-020] Run 2 — Lore ON, unrated concepts from Run 1

**Phase:** Benchmark
**Priority:** high
**Effort:** L
**Agent:** general-purpose
**Phase item:** N/A — benchmark sprint

**As a** Lore developer
**I want to be able to** attempt text2stl with unrated Lore concepts from Run 1, same 40-turn budget
**So that** we measure whether Lore knowledge (unrated) converts a failing run into a passing one

**Acceptance Criteria:**
- [ ] `python samples/stlgen/benchmarks/run.py --run 2` completes without error
- [ ] Agent searches Lore before writing any code
- [ ] `samples/stlgen/results/run2.md` written

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] `samples/stlgen/results/run2.md` committed
- [ ] `lore:wrapup` run after this story to rate concepts before Run 3

---

## [LORE-021] Run 3 — Lore ON, concepts rated after Runs 1+2 wrapup

**Phase:** Benchmark
**Priority:** high
**Effort:** L
**Agent:** general-purpose
**Phase item:** N/A — benchmark sprint

**As a** Lore developer
**I want to be able to** attempt text2stl with rated Lore concepts, same 40-turn budget
**So that** we measure whether concept ratings improve search relevance and task outcome

**Acceptance Criteria:**
- [ ] `python samples/stlgen/benchmarks/run.py --run 3` completes without error
- [ ] Agent searches Lore before writing any code
- [ ] `samples/stlgen/results/run3.md` written

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] `samples/stlgen/results/run3.md` committed
- [ ] `lore:wrapup` run after this story before Run 4

---

## [LORE-022] Runs 4–10 — Lore ON, progressively rated knowledge base

**Phase:** Benchmark
**Priority:** high
**Effort:** L
**Agent:** general-purpose
**Phase item:** N/A — benchmark sprint

**As a** Lore developer
**I want to be able to** attempt text2stl across runs 4–10 with an increasingly rated Lore knowledge base
**So that** we measure whether accumulated, rated concepts compound into measurably better outcomes

**Acceptance Criteria:**
- [x] `python samples/stlgen/benchmarks/run.py --run N` completes for N=4..10
- [x] Agent searches Lore before writing any code each run
- [x] `samples/stlgen/results/runN.md` written for each run

**DoD:**
- [x] AC above met — tokens recorded
- [x] Result files committed

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
- [x] `samples/radev/results/run1.md` committed

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
- [x] `samples/radev/results/run2.md` and `samples/radev/results/comparison.md` committed

---

## [LORE-023] GitHub Actions — CI test pipeline

**Phase:** Infrastructure
**Priority:** high
**Effort:** S
**Agent:** devops-docker-engineer
**Phase item:** N/A — infrastructure sprint

**As a** Lore developer
**I want to be able to** have tests run automatically on every push and pull request
**So that** regressions are caught before merging and the main branch stays green

**Acceptance Criteria:**
- [ ] `.github/workflows/test.yml` committed — triggers on `push` and `pull_request` to `main`
- [ ] Workflow runs `pytest lore/tests/ --cov=lore --cov-fail-under=80` in the project's Python 3.11 venv
- [ ] Workflow caches pip dependencies to keep run time under 3 minutes
- [ ] Failing tests block the PR (status check required)
- [ ] Badge added to `README.md` showing CI status

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] Workflow passes on `main` branch
- [ ] `pytest --cov=lore --cov-fail-under=80` passes locally

---

## [LORE-024] GitHub Actions — Docker image build and push

**Phase:** Infrastructure
**Priority:** high
**Effort:** M
**Agent:** devops-docker-engineer
**Phase item:** N/A — infrastructure sprint

**As a** Lore developer
**I want to be able to** have the selfhosted Docker image built and pushed to a registry automatically on every merge to main
**So that** a fresh image is always available without manual `docker build` steps

**Acceptance Criteria:**
- [ ] `.github/workflows/docker.yml` committed — triggers on `push` to `main`
- [ ] Workflow builds `lore/selfhosted/Dockerfile` and pushes to GitHub Container Registry (`ghcr.io`)
- [ ] Image tagged with both `latest` and the short commit SHA
- [ ] Build uses Docker layer caching (BuildKit cache) to avoid re-downloading PyTorch on every run
- [ ] Workflow fails fast if `docker build` exits non-zero

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] Image visible at `ghcr.io/<owner>/lore-selfhosted:latest` after a push to `main`
- [ ] Local `docker pull ghcr.io/<owner>/lore-selfhosted:latest` succeeds

---

## [LORE-025] Renovate — automated dependency updates

**Phase:** Infrastructure
**Priority:** medium
**Effort:** S
**Agent:** devops-docker-engineer
**Phase item:** N/A — infrastructure sprint

**As a** Lore developer
**I want to be able to** receive automated pull requests when Python or Docker dependencies have updates available
**So that** the project stays current without manual dependency audits

**Acceptance Criteria:**
- [ ] `renovate.json` committed at repo root with a sensible base config
- [ ] Python dependencies in `lore/selfhosted/requirements.txt` and `pyproject.toml` covered
- [ ] Docker base image in `lore/selfhosted/Dockerfile` covered
- [ ] GitHub Actions workflow files covered (action version pinning)
- [ ] Renovate configured to group patch updates and open PRs on a weekly schedule (not daily noise)
- [ ] `README.md` mentions Renovate is active

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] Renovate app installed on the repository (or Renovate GitHub Action configured as fallback)
- [ ] At least one dependency PR opened (or dry-run output confirms it would)

---

## [LORE-026] Aggregate and analyze multi-series benchmark results

**Phase:** Benchmark
**Priority:** high
**Effort:** S
**Agent:** general-purpose
**Phase item:** N/A — benchmark sprint

**As a** Lore developer
**I want to be able to** see aggregated pass-rate statistics across all 10 series of the stlgen benchmark
**So that** I can identify trends in how Lore's accumulated knowledge affects task success over time

**Acceptance Criteria:**
- [ ] Read `samples/stlgen/results/aggregate.json` — it already contains per-run `concepts_available` (concepts in DB at run start), `total_tokens`, and `tests_passed` for every series; no benchmark re-run needed
- [ ] Compute per-series pass rate (passes/10), mean pass rate across series, best/worst series
- [ ] Compute per-run-number pass rate across series (e.g. R1 across S1–S10) to show learning curve
- [ ] Compute concept accumulation trend — concepts captured per series
- [ ] Group all runs by `concepts_available` into buckets of size 5 (0–4, 5–9, 10–14, …); for each bucket compute: mean pass rate, mean total tokens, and sample count
- [ ] `aggregate.md` includes: summary table (series × pass rate), per-run-position table, concepts-in-DB bucket table (bucket | mean pass rate | mean tokens | N), key statistics, and a plain-language interpretation of the trends

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] `samples/stlgen/results/aggregate.md` committed

---

## [LORE-027] Write benchmark README with methodology and findings

**Phase:** Benchmark
**Priority:** high
**Effort:** M
**Agent:** general-purpose
**Phase item:** N/A — benchmark sprint

**As a** Lore developer
**I want to be able to** point someone at a single document that explains what was measured, how, and what we found
**So that** the benchmark results are understandable without reading the code or raw result files

**Acceptance Criteria:**
- [ ] `samples/stlgen/BENCHMARK.md` committed covering:
  - Task description (text2stl CLI, 13 tests, geometry constraints)
  - Methodology: progressive design, 10 runs per series, 40-turn budget, fresh DB per series, wrapup after each run
  - Results: series-level pass rates, per-run-position trends, Series 4 outlier explanation
  - Conclusions: does Lore help? does knowledge compound? does rating improve relevance?
  - Known limitations: local LLM variability, token counts not comparable to cloud
- [ ] Document links to `aggregate.md` for raw numbers
- [ ] Document is readable by someone unfamiliar with the Lore codebase

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] `samples/stlgen/BENCHMARK.md` committed

---

## Sprint 7 — 2026-07-11 → 2026-07-25
**Goal:** Deliver the Phase 3 core pipeline — semantic search server running, gist watcher indexing community concepts, and MCP routing with graceful fallback.
**Status:** planned

### Stories
| ID | Title | Agent | Status | Tokens |
|----|-------|-------|--------|--------|
| LORE-030 | Semantic search server — FastAPI + Qdrant core | python-mcp-engineer | planned | — |
| LORE-031 | Gist watcher — poll, embed, and index public lore concepts | python-mcp-engineer | planned | — |
| LORE-032 | LORE_SEMANTIC_URL routing in MCP server | python-mcp-engineer | planned | — |
| LORE-036 | Graceful fallback — semantic server unreachable → Backend 2 | python-mcp-engineer | planned | — |

### Notes
- LORE-030 is foundational — LORE-031, LORE-032, and LORE-036 all depend on the server being up.
- Implement order: LORE-030 → LORE-031 (parallel with LORE-032) → LORE-036 (needs LORE-032).
- Consult ai-data-specialist + software-architect before LORE-030 implementation for schema and deployment decisions.
- LORE-033, LORE-034, LORE-035 (ratings, auth, dedup) deferred to Sprint 8 — they require the core server.

---

## Sprint 8 — 2026-07-25 → 2026-08-08
**Goal:** Harden the semantic server with auth, ratings aggregation, and deduplication — completing Phase 3.
**Status:** planned

### Stories
| ID | Title | Agent | Status | Tokens |
|----|-------|-------|--------|--------|
| LORE-033 | Server-side ratings aggregation | python-mcp-engineer | planned | — |
| LORE-034 | API key auth — one key per GitHub user | python-mcp-engineer | planned | — |
| LORE-035 | Deduplication — flag near-duplicate concepts on publish | python-mcp-engineer | planned | — |

### Notes
- All three stories depend on LORE-030 (core server) from Sprint 7.
- LORE-034 (auth) should be implemented before LORE-033 and LORE-035 so write endpoints are protected from the start.
- After Sprint 8: run LORE-029 (gists benchmark) to validate the full Phase 3 stack end-to-end.
