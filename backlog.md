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

## [LORE-029] Benchmark runner: gists backend support with series cleanup

**Phase:** Benchmark
**Priority:** medium
**Effort:** M
**Agent:** python-mcp-engineer
**Phase item:** N/A — benchmark sprint
**Depends on:** Phase 3 (LORE-semantic-server) complete

**As a** Lore developer
**I want to be able to** run the stlgen benchmark against the gists backend with automatic cleanup
**So that** the gists + semantic server stack is validated with the same benchmark methodology as the selfhosted backend

**Context:**
The stlgen benchmark currently runs against the selfhosted backend (SQLite + Qdrant). Once Phase 3 (semantic search server) is complete, the gists backend is equivalent in search quality. This story adds gists support to the benchmark runner, including series-level cleanup so test concepts don't persist on the contributor's GitHub account.

**Acceptance Criteria:**
- [ ] `samples/stlgen/benchmarks/run.py` accepts `--backend gists` flag; defaults to `selfhosted` (no regression)
- [ ] With `--backend gists`, the runner sets `LORE_BACKEND=gists` and `LORE_SEMANTIC_URL` (from env); requires `LORE_GITHUB_TOKEN`
- [ ] Benchmark runner tracks all gist IDs created during a series (from `submit_concept` responses)
- [ ] At series end (after wrapup), all created gists are deleted via `GistsClient.delete_gist`; failures are logged but do not abort the run
- [ ] Result files (`runN.md`, `aggregate.json`) include `backend` field so selfhosted and gists runs are distinguishable
- [ ] A deleted-gist during a run (e.g. manual cleanup mid-run) is handled gracefully — logged, not crashed

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] Tests written + test-suite-architect approved
- [ ] pytest --cov=lore --cov-fail-under=80 passes

---

## [LORE-028] Extended stlgen benchmark — 30 series for statistical confidence

**Phase:** Benchmark
**Priority:** low
**Effort:** L
**Agent:** general-purpose
**Phase item:** N/A — benchmark sprint

**As a** Lore developer
**I want to be able to** run 30 series of the stlgen benchmark instead of 10
**So that** the per-run-position learning curve, concept-bucket analysis, and outlier rate are statistically meaningful

**Context:**
The 10-series run established clear directional signals (R1 10% vs Lore-ON 60%, sweet spot at 20–24 concepts) but is underpowered for nuanced conclusions. With N=10 per run position, confidence intervals are ±30%. Two catastrophic series (S4 0/10, S10 1/10) may be bad luck or a ~20% structural failure rate — indistinguishable at this sample size.

**Why 30 series:**
- Brings each run position to N=30 (±18% CI) — enough to distinguish real curve shape from noise
- Gets N≥20 in the high-concept buckets (30+) — currently only N=4–6 there
- With ~30 series, the catastrophic-failure rate can be estimated (is it 2/30 ≈ 7% or 6/30 ≈ 20%?)
- Marginal return beyond 30 is modest unless publishable precision is needed
- Estimated wall time: ~45–60 hours; best run as a background job over several nights

**Acceptance Criteria:**
- [ ] 30 series × 10 runs completed; results appended to `aggregate.json`
- [ ] `aggregate.md` and `BENCHMARK.md` updated with new statistics
- [ ] Interpretation section updated — confirm or revise the 20–24 concept sweet spot claim
- [ ] Note whether catastrophic-failure rate is consistent with 10-series estimate (~20%)

**DoD:**
- [ ] AC above met — tokens recorded
- [ ] `aggregate.md` and `BENCHMARK.md` committed

---

