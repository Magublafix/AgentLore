# stlgen benchmark

Measures whether Lore helps a local LLM complete a coding task it cannot reliably solve on its own.

## Task

Build a `text2stl` CLI that converts a text string (≤15 chars) into a 3D-printable STL file with raised letters. The implementation must pass 13 pytest tests covering invocation, geometry, and mesh validity.

## Run structure

| Run | Lore active | DB state at start | Purpose |
|-----|-------------|-------------------|---------|
| 1   | ❌ no        | seed concept only | Control — proves the model cannot solve the task without Lore |
| 2   | ✅ yes       | seed concept only | Core test — does the seed concept rescue the model? |
| 3   | ✅ yes       | seed + Run 1–2 concepts | Does accumulated knowledge (including failed-run noise) help further? |
| 4   | ✅ yes       | seed + Run 1–3 concepts | Does more Lore context improve or regress? |

Run 1 is the single control. Runs 2–4 are treatment with progressively richer Lore context.

## How to run

```bash
# Cloud Claude (anthropic provider)
python benchmarks/run.py --run 1

# Local model via Ollama Anthropic-compatible API
LORE_LLM_PROVIDER=local \
LORE_LOCAL_BASE_URL=http://192.168.1.38:11434 \
LORE_LOCAL_MODEL=qwen2.5-coder:32b \
python benchmarks/run.py --run 1
```

Run all four sequentially:

```bash
for i in 1 2 3 4; do python benchmarks/run.py --run $i; done
```

## Seeding rationale

The benchmark includes hand-authored seed concepts in `seed_concepts/`. These are injected into the Lore DB immediately after the Run 1 reset, before any model runs.

**Why we seed:**

All local models tested (qwen2.5-coder:7b, qwen2.5-coder:32b, deepseek-r1:32b) consistently failed to complete the task due to a specific knowledge gap: they hallucinate non-existent trimesh geometry APIs (`trimesh.contour`, `trimesh.triangulation`, `trimesh.creation.text()` etc.). The real pipeline uses `skimage.measure.find_contours()` + `trimesh.creation.extrude_polygon()`, which is sparsely represented in training data.

This is a training-data gap, not a reasoning failure. The models understand *what* to do (render text → extract contours → extrude → export STL) but confabulate the *how*.

Without seeding, all 4 runs produce FAIL because:
- Run 1 fails (model doesn't know the right API)
- Run 2 searches Lore but finds nothing useful (DB only has wrong concepts from Run 1)
- Runs 3 and 4 repeat the same failure

This defeats the purpose of the benchmark: we cannot measure whether Lore *helps* if Lore never has the right answer.

**What seeding tests:**

With a correct seed concept in the DB, the Lore-ON runs (2 and 4) retrieve it on turn 1 via `search_concepts`. If the model uses the retrieved API correctly, tests pass — demonstrating that Lore-sourced knowledge can rescue a model from a pure knowledge gap. The Lore-OFF runs (1 and 3) still lack the information and are expected to fail, giving a clean FAIL vs PASS comparison.

This is the core Lore hypothesis in its purest form: *one agent captures working knowledge; a future agent uses it to succeed where it would otherwise fail.*

**What seeding does NOT test:**

- Whether the model would organically capture the right approach (it wouldn't — it never succeeds)
- Whether the Lore graph is self-populating from model runs alone
- General Lore utility beyond this specific knowledge gap

## Seed concepts

| File | Concept | Purpose |
|------|---------|---------|
| `seed_concepts/trimesh_pil_text_to_stl.md` | PIL + scikit-image + trimesh text-to-STL pipeline | Provides the correct library API path the model needs |

## Results

Results are written to `results/run{N}.md` after each run.

### Sprint 3 run — qwen2.5-coder:32b (seeded benchmark)

| Run | Lore | Tests | Error type | Tokens | Time |
|-----|------|-------|------------|--------|------|
| 1 | ❌ | 0/13 pass | `text2stl` CLI not installed | 246K | 33 min |
| 2 | ✅ | 2/13 pass | "No contours found for text" | 153K | 101 min |
| 3 | ✅ | 2/13 pass | `main()` missing CLI arg wiring (Click bug) | 136K | 93 min |
| 4 | ✅ | 2/13 pass | `numpy.ndarray has no attribute 'is_empty'` | 385K | 52 min |

**Observations:**

- **Run 1 (no Lore)**: Model hallucinated entirely wrong APIs, never produced a working CLI entry point at all — 0 tests pass.
- **Runs 2–4 (Lore ON)**: Model immediately searched Lore and adopted the correct library pipeline (PIL + skimage + trimesh.creation.extrude_polygon). Validation tests now pass (2/13). Error type shifted from "wrong API family" to "small mistakes in pipeline details."
- **Run 2**: Correct pipeline, but rendering parameters too small → no pixel contours detected. Model didn't follow the seed concept's `font_size=72` recommendation closely enough.
- **Run 3**: Correct pipeline, but used Click without `@click.argument()` decorators — function signature bug rather than geometry bug.
- **Run 4**: Correct pipeline, but called `.is_empty` on a numpy contour array instead of on the Shapely Polygon — the exact hallucination the seed concept warned against. Model read the warning but did not follow the complete minimal implementation closely enough.

**Conclusion:** Lore measurably shifted the model's behavior — from hallucinated APIs and 0 passing tests (Run 1) to correct library choices and 2 passing tests (Runs 2–4). The remaining failures are downstream implementation details, not the core API knowledge gap. A more complete seed concept (explicit rendering parameters, complete argparse/click wiring, stronger `.is_empty` guard) would likely close the gap further.

### Reasoning-prefix-harness run — qwen2.5-coder:32b, 30-turn budget

Two harness changes preceded this sequence: `search-concepts/SKILL.md` now
states the `type` filter is optional (a wrong guess previously zeroed out
results silently), and `LOCAL_SYSTEM_PREFIX` now permits 1–3 sentences of
reasoning before each tool call instead of forbidding all prose.

| Run | Lore | Tests | Result | Tokens |
|-----|------|-------|--------|--------|
| 1 | ❌ | 2/13 pass | `AttributeError: 'Trimesh' object has no attribute 'extrude'` — hallucinated API | 280K |
| 2 | ✅ (1 concept) | 2/13 pass | Correct pipeline, but overshot `font_size` (72→192) chasing an unrelated bug → "No renderable glyphs found" | 270K |
| 3 | ✅ (8 concepts) | **12/13 pass** | Correct, nearly-complete implementation — only failure was the IoU test (see below) | 537K |
| 4 | ✅ (15 concepts) | **12/13 pass** | Same outcome as Run 3, reached in 18 turns / 275K tokens instead of 30 turns / 537K — richer rated context made the model more efficient at reaching the same result, but didn't close the remaining gap | 275K |

A new failure mode appeared in this run series: on roughly 1 in 6 turns, the
model wrote an unfinished code block in a markdown fence instead of ending
its response with a tool call, costing a wasted turn each time (the existing
retry path recovers it on the next turn). All four main loops also ended on
an Ollama API timeout rather than the 30-turn ceiling — a local-inference
characteristic, not a benchmark design issue.

### IoU test scale-normalization fix

Runs 3 and 4 both stalled on `test_character_shapes_match_text`, which
asserts the STL's mid-height cross-section has IoU ≥ 0.25 against a
PIL-rendered reference of the same text. Both runs measured IoU = 0.093.

Regenerating the implementation and rendering the actual cross-section
showed the text was correctly formed, legible, and in the right order — the
test was failing for a reason that had nothing to do with the model's
geometry. `_stl_cross_section_bitmap` rasterizes a mesh's cross-section
using a pitch derived from the section's own bounding box, so the STL side
of the comparison always fills its 400×100 frame edge-to-edge (blank canvas
in the model's 2D rendering produces no geometry, so it can never appear as
margin in the 3D bounding box — there is no way for the model to fix this
from its own implementation). The reference bitmap, however, rendered text
centered with its natural padding inside the same frame, at a different
effective scale. Two correctly-shaped letters at different scales overlap
almost nowhere, which is why IoU bottomed out near zero regardless of
geometry quality.

**Fix:** crop the reference bitmap to its own tight glyph bounding box
before scaling to the frame (`tests/test_text2stl_cli.py`,
`_text_reference_bitmap`), matching the tight-bbox convention the STL side
already uses by construction.

**Validation:** using the exact same implementation that scored
IoU = 0.093 against the old reference function, the corrected reference
function alone raised it to **0.514** — well above the 0.25 threshold.
Reinstalling that implementation and running the full suite against the
fixed test file passed all 13/13 tests, with zero changes to the
implementation. This means **Run 3 and Run 4's "1 failed" results were a
test-harness artifact**, not a shortcoming of the model or of Lore — the
underlying implementation was already correct.

Two alternative fixes were considered and rejected:
- *Lower the IoU threshold* — papers over the scale mismatch without fixing
  the actual comparison; would leave the test permanently miscalibrated.
- *Add a margin requirement to the task prompt* — tested and confirmed
  ineffective: blank canvas around rendered glyphs produces no mesh
  geometry, so it cannot survive into the STL's bounding box no matter what
  margin convention the model follows.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LORE_LLM_PROVIDER` | `anthropic` | `anthropic` or `local` |
| `LORE_LOCAL_BASE_URL` | `http://localhost:11434` | Ollama base URL (no `/v1`) |
| `LORE_LOCAL_MODEL` | `qwen2.5-coder:32b` | Model name for local runs |
| `LORE_DB_PATH` | `~/.lore/lore.db` | Path to Lore SQLite DB |
