# Multi-Series Benchmark — Aggregate Analysis

**Model:** unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M  
**Task:** text2stl CLI (13 tests, 40-turn budget)  
**Design:** 10 series × 10 runs; fresh concept DB per series; wrapup rating after each run

---

## Data Notes

The JSON file contains **15 series entries** rather than the intended 10. The first 5 entries
(positions 0–4, 0-indexed) are earlier exploratory runs and are excluded from canonical analysis:
they carry duplicate `series_id: 1` values, and two of them show anomalous DB state (position 2
has `concepts_available: 22` at R1, meaning the DB was not fresh; position 4 has
`concepts_available: 11` at R1). The **last 10 entries** (positions 5–14, series_id 1–10) are the
canonical 10-series benchmark used for all analysis below — each starts with `concepts_available: 0`
at R1 and contains all 10 runs.

Additional data quality items in the excluded portion:
- **Position 3 (series_id: 2), run 4**: `concepts_captured: -49` — a counter underflow artifact;
  noted but excluded with the rest of this entry.
- **Position 3 (series_id: 2)**: run 7 is missing entirely (only 9 runs present).

---

## Series-Level Results

| Series | R1 | R2 | R3 | R4 | R5 | R6 | R7 | R8 | R9 | R10 | Pass Rate |
|--------|----|----|----|----|----|----|----|----|----|----|-----------|
| S1     | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | 7/10 |
| S2     | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ | 5/10 |
| S3     | ✗ | ✓ | ✓ | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ | ✗ | 5/10 |
| S4     | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | 0/10 |
| S5     | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✗ | 6/10 |
| S6     | ✗ | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 8/10 |
| S7     | ✗ | ✓ | ✓ | ✓ | ✗ | ✓ | ✗ | ✓ | ✓ | ✓ | 7/10 |
| S8     | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ | ✓ | ✓ | ✓ | 7/10 |
| S9     | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 9/10 |
| S10    | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | 1/10 |
| **Mean** | | | | | | | | | | | **5.5/10** |

---

## Learning Curve (per run position across series)

| Run | Passes (of 10) | Pass Rate |
|-----|----------------|-----------|
| R1 (Lore OFF) | 1 | 10% |
| R2 | 4 | 40% |
| R3 | 7 | 70% |
| R4 | 5 | 50% |
| R5 | 7 | 70% |
| R6 | 7 | 70% |
| R7 | 6 | 60% |
| R8 | 5 | 50% |
| R9 | 8 | 80% |
| R10 | 5 | 50% |

---

## Concept Accumulation

| Series | Concepts at R1 | Total Captured | Final Concepts |
|--------|---------------|----------------|----------------|
| S1 | 0 | 66 | 66 |
| S2 | 0 | 37 | 37 |
| S3 | 0 | 26 | 26 |
| S4 | 0 | 22 | 22 |
| S5 | 0 | 31 | 31 |
| S6 | 0 | 39 | 39 |
| S7 | 0 | 24 | 24 |
| S8 | 0 | 39 | 39 |
| S9 | 0 | 32 | 32 |
| S10 | 0 | 35 | 35 |

"Final concepts" = concepts_available at R10 + concepts_captured at R10 (i.e., cumulative DB size
at end of series). S1 accumulated the most (66), aided by heavy capture bursts at R5 (13) and R8
(19). S4 accumulated the fewest (22) and never passed a single run.

---

## Concepts-Available Bucket Analysis

All 100 runs from the 10 canonical series, grouped by `concepts_available` at run start.

| Concepts Available | Pass Rate | Mean Pass Rate | Mean Tokens | N |
|-------------------|-----------|----------------|-------------|---|
| 0–4  | 9/26  | 34.6% | 45,181 | 26 |
| 5–9  | 8/16  | 50.0% | 40,948 | 16 |
| 10–14 | 7/11  | 63.6% | 43,791 | 11 |
| 15–19 | 8/13  | 61.5% | 49,811 | 13 |
| 20–24 | 11/14 | 78.6% | 33,856 | 14 |
| 25–29 | 5/10  | 50.0% | 47,323 | 10 |
| 30–34 | 4/6   | 66.7% | 38,148 | 6 |
| 35+  | 3/4   | 75.0% | 42,402 | 4 |

---

## Key Statistics

- **Overall pass rate (all 100 runs):** 55%
- **R1 baseline pass rate (Lore OFF):** 10% (1/10 — a single lucky run in S8)
- **R2–R10 Lore-ON pass rate:** 60% (54/90)
- **Best series:** S9 (9/10)
- **Worst series:** S4 (0/10)
- **Second-worst series:** S10 (1/10 — only R7 passed)
- **Series 4 (all failures):** Despite accumulating 22 concepts by end of series, S4 never passed.
  The DB never exceeded 17 concepts_available at any run start, and knowledge capture stalled early
  (0 captured in R5 and R6). This series appears to represent a run of consistently poor task
  strategies that Lore could not compensate for within 10 attempts.

---

## Interpretation

**Does Lore help?** The headline comparison is stark: the R1 baseline (Lore OFF) passed only 10%
of the time (1 out of 10 runs), while Lore-ON runs R2–R10 passed 60% of the time (54/90). Even
granting that Lore is not the sole variable — early runs naturally face harder cold-start problems
than later runs where the agent has tried the task before — the magnitude of the gap is too large
to attribute to task familiarity alone. The R2 pass rate alone (40%) is four times the R1 baseline
despite being the very next attempt, typically with only 2–5 concepts available.

**Does knowledge compound within a series?** The bucket analysis shows a clear trend from 0–4
concepts (34.6% pass rate) up to 20–24 concepts (78.6% pass rate), suggesting that the early
accumulation phase provides real benefit. However, the curve is not monotone: the 25–29 bucket
drops to 50%, driven largely by S10's persistent failures in R6–R9 where the DB had grown to 25–28
concepts but the agent continued to fail. This implies that having concepts is not sufficient on
its own — the agent must still execute the strategy those concepts suggest, and S10 never found a
working approach regardless of how much knowledge was available.

**What the learning curve shape reveals:** Pass rates jump from 10% (R1) to 40% (R2) and reach
70% by R3, then oscillate between 50% and 80% for the rest of the series. The R3 and R9 peaks
(both 70%/80%) hint at inflection points — R3 is typically when early concepts captured in R1-R2
first have enough mass to guide the agent meaningfully, and R9 is often when the DB has matured
enough (15–25 concepts) to provide a near-complete picture of pitfalls. The R10 dip back to 50%
is notable: it may reflect that at very late runs, some series' agents hit saturation or the wrapup
quality degrades, while others (S10) drag down the average with an unrecovered series.

**Series 4 and Series 10 outliers:** S4 is a genuine zero — 10 runs, 0 passes, despite Lore
being active from R2 onward. The root cause appears structural: S4 accumulated only 22 concepts
across the full series (vs. S1's 66 or S6's 39), and the concepts captured were sparse in early
runs (0 in R5 and R6). The agent was not generating useful knowledge to store, which means the
knowledge graph could not break the failure cycle. S10 is nearly as bad (1/10), with the one pass
occurring at R7 when the DB had 26 concepts — but the agent could not reproduce that result in
subsequent runs. Both series represent failure modes where the task strategy itself is broken, and
Lore can only help an agent that is trying the right things and failing on details, not an agent
that is fundamentally misdirected from the start.
