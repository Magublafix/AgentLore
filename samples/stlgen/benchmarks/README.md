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

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LORE_LLM_PROVIDER` | `anthropic` | `anthropic` or `local` |
| `LORE_LOCAL_BASE_URL` | `http://localhost:11434` | Ollama base URL (no `/v1`) |
| `LORE_LOCAL_MODEL` | `qwen2.5-coder:32b` | Model name for local runs |
| `LORE_DB_PATH` | `~/.lore/lore.db` | Path to Lore SQLite DB |
