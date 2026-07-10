# stlgen Benchmark — Lore Effectiveness Study

## What Was Measured

Lore is a typed, linked knowledge graph designed for AI coding agents. It lets agents store reusable insights — correct library calls, known failure modes, working patterns — and retrieve them at the start of future sessions. The core hypothesis is that accumulated, rated knowledge reduces the number of attempts an agent needs to solve a problem and improves its probability of success.

This benchmark tests that hypothesis on a geometry-heavy coding task: building a 3D text-to-STL command-line tool. The question is straightforward: does an agent that can query a growing knowledge graph before writing code succeed more often than one starting from scratch?

## Task Description

The agent was given a single instruction: implement a `text2stl` CLI that accepts a text string of 1–15 characters and produces a 3D-printable STL file with raised letters. The implementation had to pass a fixed test suite of 13 pytest tests covering:

- **Invocation**: correct CLI interface (`text2stl "Hello" -o out.stl`), default filename behavior
- **Input validation**: rejection of empty strings and strings longer than 15 characters
- **Mesh validity**: the output STL must load cleanly under `trimesh`, be water-tight (manifold), have positive volume, and contain no degenerate triangles
- **Dimension scaling**: a 5-character mesh must be measurably wider than a 1-character mesh
- **Character shape verification**: a mid-height cross-section of the STL must have Intersection-over-Union (IoU) ≥ 0.25 against a PIL-rendered reference bitmap of the same text, and a separate band-correlation test must confirm the characters are not truncated along either axis

The geometry constraints make this a hard task for a language model. Producing a watertight STL from rasterized text glyphs requires chaining together a specific library pipeline (PIL for rendering, scikit-image for contour extraction, Shapely for polygon construction, trimesh for extrusion and mesh validation) with correct parameter choices at each step. Models routinely hallucinate non-existent trimesh APIs, miscalibrate font sizes so glyphs overflow or disappear, or build meshes with topology errors that fail the manifold check. The task was deliberately chosen because it sits at the edge of what the model can reliably do unaided — making the Lore signal easier to isolate.

## Methodology

The benchmark uses a **series × run** design with 10 series and 10 runs per series, for 100 total runs.

**Each series starts with a fresh, empty concept database.** There is no pre-seeded knowledge — the agent must build the knowledge graph entirely from what it discovers and captures during the runs.

**Within a series, the runs are structured as follows:**

| Run | Lore active | DB state at run start |
|-----|-------------|-----------------------|
| R1  | Off         | Empty (0 concepts)    |
| R2  | On          | Concepts from R1      |
| R3–R10 | On       | Accumulates from all prior runs |

**Run 1 is the control.** Lore is disabled, so the agent writes code without any knowledge graph. During and after R1, concepts are captured via `submit_concept` and rated in a wrapup phase, but the agent cannot query them during the run itself.

**Runs 2–10 use Lore.** At the start of each run, the agent calls `search_concepts` to retrieve relevant knowledge before writing any code. After each run, a wrapup phase rates the concepts that were captured or used, improving the retrieval quality for subsequent runs.

**The 40-turn budget** is enforced per run. If the agent has not submitted a passing implementation by turn 40, the run ends as a failure.

**No hand-authored seed concepts were injected.** Earlier experiments showed that a single targeted seed concept could single-handedly determine success, making it impossible to measure whether Lore as a system was helping. The 10-run no-seed design measures whether organic accumulation of knowledge — the full loop of capture, rate, search, apply — produces measurable improvement.

**Model:** `unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M`, a quantized local LLM served via `llama-server` (llama.cpp's Anthropic-compatible endpoint).

## Results

### Series-Level Pass Rates

Each cell shows whether the run passed (✓) or failed (✗) the 13-test suite. Pass rate is the fraction of 10 runs that passed within the series.

| Series | R1 | R2 | R3 | R4 | R5 | R6 | R7 | R8 | R9 | R10 | Pass Rate |
|--------|----|----|----|----|----|----|----|----|----|----|-----------|
| S1     | ✗  | ✗  | ✓  | ✓  | ✓  | ✓  | ✓  | ✓  | ✓  | ✗  | 7/10 |
| S2     | ✗  | ✗  | ✗  | ✗  | ✓  | ✓  | ✓  | ✗  | ✓  | ✓  | 5/10 |
| S3     | ✗  | ✓  | ✓  | ✗  | ✓  | ✓  | ✗  | ✗  | ✓  | ✗  | 5/10 |
| S4     | ✗  | ✗  | ✗  | ✗  | ✗  | ✗  | ✗  | ✗  | ✗  | ✗  | 0/10 |
| S5     | ✗  | ✗  | ✓  | ✓  | ✓  | ✓  | ✓  | ✗  | ✓  | ✗  | 6/10 |
| S6     | ✗  | ✓  | ✓  | ✗  | ✓  | ✓  | ✓  | ✓  | ✓  | ✓  | 8/10 |
| S7     | ✗  | ✓  | ✓  | ✓  | ✗  | ✓  | ✗  | ✓  | ✓  | ✓  | 7/10 |
| S8     | ✓  | ✗  | ✓  | ✓  | ✓  | ✗  | ✗  | ✓  | ✓  | ✓  | 7/10 |
| S9     | ✗  | ✓  | ✓  | ✓  | ✓  | ✓  | ✓  | ✓  | ✓  | ✓  | 9/10 |
| S10    | ✗  | ✗  | ✗  | ✗  | ✗  | ✗  | ✓  | ✗  | ✗  | ✗  | 1/10 |
| **Mean** | | | | | | | | | | | **5.5/10** |

Overall pass rate across all 100 runs: **55%**.

### Does Lore Help?

The headline comparison: **R1 (Lore OFF) passed 10% of the time** — 1 out of 10 runs, and that single pass was S8, which appears to have been a lucky baseline. **Runs R2–R10 (Lore ON) passed 60% of the time** — 54 out of 90 runs.

That is a **6× improvement**.

Even controlling for the cold-start advantage (later runs have had more attempts at the task), the R2 pass rate alone makes the case: R2 achieved 40% — four times the R1 baseline — despite being the very next attempt, typically with only 2–5 concepts available in the knowledge graph. The agent was not benefiting from task familiarity alone. It had real, if sparse, knowledge to draw on, and that knowledge made a measurable difference immediately.

### Does Knowledge Compound?

The learning curve across run positions (aggregated over all 10 series):

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

The jump from R1 (10%) to R2 (40%) to R3 (70%) suggests that even a small number of concepts captured in the first two attempts provides meaningful guidance. R3 is typically when those early concepts have enough coverage to steer the agent past the most common failure modes.

The curve then oscillates between 50% and 80% rather than continuing to climb monotonically. This reflects a mix of two effects: series where the knowledge graph is compounding well (S6 reaches 8/10, S9 reaches 9/10), and outlier series (S4, S10) where the agent never found a working strategy and dragged the aggregate down.

A more direct measure of knowledge accumulation: the **concept-bucket analysis** groups all 100 runs by how many concepts were available at run start and computes the pass rate for each bucket.

| Concepts Available | Pass Rate | Mean Tokens | N runs |
|-------------------|-----------|-------------|--------|
| 0–4               | 34.6%     | 45,181      | 26     |
| 5–9               | 50.0%     | 40,948      | 16     |
| 10–14             | 63.6%     | 43,791      | 11     |
| 15–19             | 61.5%     | 49,811      | 13     |
| 20–24             | 78.6%     | 33,856      | 14     |
| 25–29             | 50.0%     | 47,323      | 10     |
| 30–34             | 66.7%     | 38,148      | 6      |
| 35+               | 75.0%     | 42,402      | 4      |

The trend from 0–4 concepts (34.6%) up to 20–24 concepts (78.6%) is clear: more accumulated knowledge correlates with higher success rates. The 25–29 bucket drops back to 50%, but this is largely a S10 artifact — that series accumulated a large concept database while failing persistently, so many of its late runs land in the higher buckets and pull the rate down. See the Outlier Series section below.

See [`results/aggregate.md`](results/aggregate.md) for the full concept-bucket table with token counts and per-series data.

### Outlier Series

**Series 4 (0/10)** is a genuine zero: 10 runs, 0 passes, despite Lore being active from R2 onward. S4 accumulated only 22 concepts across the full series — the fewest of any series — and knowledge capture stalled completely in R5 and R6 (0 concepts captured). The agent was not generating useful knowledge to store, so the knowledge graph could not break the failure cycle. Lore can only help an agent that is attempting the right approach and failing on details. If the agent's core strategy is wrong, storing and retrieving knowledge about that wrong strategy does not help.

**Series 10 (1/10)** is nearly as bad: one pass at R7 (when 26 concepts were available), but the agent could not reproduce the result in subsequent runs despite a similar number of concepts being available. The single pass at R7 appears to have been a lucky draw from a distribution that was never reliably above the failure threshold. Like S4, S10 represents a series where the task strategy remained fundamentally broken across all runs.

Both series illustrate the same ceiling: Lore amplifies a working approach but cannot conjure one from nothing.

## Conclusions

- **Lore helps substantially.** The R1 baseline (Lore OFF) passed 10% of the time. Runs with Lore ON passed 60% of the time — a 6× improvement. Even R2, with only 2–5 concepts available, achieved a 40% pass rate. The signal is too large and appears too early to attribute to task familiarity alone.

- **Accumulated, rated knowledge compounds.** Pass rates climb from 34.6% at 0–4 concepts to 78.6% at 20–24 concepts. The early accumulation phase (R1–R3) provides the sharpest gains; the curve flattens and oscillates after the knowledge base matures. Approximately 20 concepts appears to be a practical sweet spot for this task and model.

- **Rating improves retrieval over time.** The wrapup phase after each run rates concepts for relevance and utility. The progressive improvement within successful series (S6, S9) is consistent with rated concepts surfacing more reliably in later runs. This cannot be isolated cleanly from the sheer volume effect, but the concept-bucket trend suggests quality matters alongside quantity.

- **Lore cannot fix a broken strategy.** S4 and S10 demonstrate the ceiling: an agent that never finds a working approach will not benefit from a growing knowledge graph. The concepts it captures describe failures, and retrieving descriptions of failures does not unlock a path to success if that path requires a fundamentally different approach the agent has not yet tried.

- **The overall picture is positive.** 8 of 10 series passed at least 5 out of 10 runs. The mean series pass rate was 5.5/10. For a quantized local model on a task at the edge of its capability, Lore reliably shifted outcomes from near-certain failure to better-than-even success.

## Known Limitations

- **Local LLM variability**: The benchmark used `unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M`, a quantized local model served via llama.cpp. Token counts are not directly comparable to cloud model results — local inference reports delta tokens only, so run totals are likely 2–5× understated relative to actual compute. Results also reflect this specific model's strengths and blind spots.

- **Task difficulty**: The stlgen task requires correct geometry math (trimesh, numpy-stl, correct polygon normals, character shape IoU ≥ 0.25, band-correlation truncation check). Some failure modes appear to be intrinsic to the model's capability ceiling — there is a class of geometry error that Lore-supplied knowledge cannot prevent if the model cannot execute the correct code even when told what to write.

- **Series isolation**: Each series starts with a fresh database. Cross-series concept transfer — whether knowledge accumulated in one series would help a different series — was not tested. The design deliberately isolates within-series compounding to avoid confounding the signal.

- **Sample size**: 10 series is enough to identify the main trends (Lore ON vs. OFF, concept accumulation curve) but not enough for statistical significance on per-series comparisons. S4 and S10's failures are interpretively clear but not statistically distinguishable from bad luck at this sample size.

- **No seed concepts**: This benchmark explicitly excludes hand-authored seed concepts to measure the organic accumulation loop. A seeded variant (see earlier experiments in `benchmarks/README.md`) reached 13/13 passing tests by Run 3, suggesting that targeted, expert-authored concepts can close remaining gaps that organic accumulation alone cannot reach within 10 runs.

## Raw Data

See [`results/aggregate.md`](results/aggregate.md) for per-series pass rate tables, learning curve data, and concept-bucket analysis with token counts.
