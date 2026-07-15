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

## [LORE-037] Benchmark series: noise resilience — polluted graph with medium-rated wrong concepts

**Phase:** Benchmark
**Priority:** medium
**Effort:** M
**Agent:** python-mcp-engineer
**Phase item:** N/A — benchmark sprint
**Depends on:** LORE-029 (gists benchmark support)

**As a** Lore developer
**I want to be able to** run the stlgen benchmark against a graph pre-seeded with intentionally wrong concepts at medium ratings
**So that** I can verify the system still achieves passing results despite concept-level noise pollution

**Context:**
The benchmark currently tests learning from correct concepts. This story tests resilience: if a contributor submits wrong or misleading concepts (e.g. incorrect STL generation guidance) and rates them a medium 3/5, does the agent still succeed? Medium ratings are the dangerous case — high ratings for bad concepts would dominate search; low ratings would be filtered. Medium-rated wrong concepts blend into the graph and are the hardest noise to recover from.

**Acceptance Criteria:**
- [ ] Benchmark runner supports `--inject-noise N` flag: injects N wrong concepts (pre-authored, stored in `samples/stlgen/benchmarks/noise_concepts.json`) before series start
- [ ] Injected concepts are submitted via `submit_concept` and immediately rated 3/5 with no `hours_saved`
- [ ] Wrong concepts are plausibly related to STL generation but contain factually incorrect guidance (e.g. wrong vertex winding order, incorrect unit assumptions, bad normals advice)
- [ ] Series runs normally after injection; results include `noise_injected: N` field in `runN.md` and `aggregate.json`
- [ ] At series end, injected concepts are deleted/cleaned up (same as LORE-029 gist cleanup)
- [ ] Benchmark achieves the same pass threshold as clean runs (≥ baseline from LORE-028/029 aggregate) — a meaningful degradation is flagged in the results but does not fail the runner itself
- [ ] A comparison summary (clean vs noisy pass rates) is appended to `aggregate.md`

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

