# text2stl — 3D Printable Text CLI

A Linux CLI that converts a text string (1–15 characters) into a 3D-printable STL file.

## Install

```bash
cd samples/stlgen
pip install -e .
```

After install, `text2stl` is available on your PATH.

## CLI Interface

```bash
text2stl "Hello World" -o output.stl   # write to output.stl
text2stl "Hello World"                  # write to "Hello World.stl" in cwd
```

- Accepts 1–15 printable ASCII characters; exits non-zero otherwise.
- Output STL is water-tight (manifold) and 3D printable.
- Characters are extruded — readable when physically printed.

## Running the tests

```bash
pytest samples/stlgen/tests/test_text2stl_cli.py -v
```

13 tests total:
- Basic invocation (single char, 5 chars, 15 chars, default filename)
- Input validation (empty string, >15 chars rejected)
- STL validity via `trimesh` (loads, water-tight, positive volume, no degenerate triangles)
- Dimension scaling (5-char mesh wider than 1-char mesh)
- Character shape verification (mid-height cross-section IoU ≥ 0.25 vs PIL reference)

---

## Benchmark

Measures whether Lore helps a local LLM complete a coding task it cannot reliably solve on its own.

### Task

Build a `text2stl` CLI that converts a text string (≤15 chars) into a 3D-printable STL file with raised letters. The implementation must pass 13 pytest tests covering invocation, geometry, and mesh validity.

### Run structure

| Run | Lore active | DB state at start | Purpose |
|-----|-------------|-------------------|---------|
| 1   | ❌ no        | empty (reset on start) | Control — baseline without Lore |
| 2   | ✅ yes       | Run 1 concepts | Lore ON with concepts captured in Run 1 |
| 3–10 | ✅ yes      | accumulates each prior run | Does accumulated organic knowledge improve results? |

Run 1 is the single control and always resets the DB to empty. Runs 2–10 have Lore ON with progressively richer context from prior runs. No hand-authored seed concepts — Lore must bootstrap entirely from concepts the model captures organically.

### Running the benchmark

```bash
python benchmarks/run.py --run 1    # baseline (clears DB, no Lore)
python benchmarks/run.py --run 2    # Lore ON, concepts accumulate from Run 1
python benchmarks/run.py --run 3    # Lore ON, concepts accumulate from Runs 1-2
# ... repeat through run 10
python benchmarks/run.py --all      # run all 10 sequentially
```

By default the runner uses the Anthropic API. To use a self-hosted LLM instead:

```bash
# Local model via a llama.cpp or Ollama server
LORE_LLM_PROVIDER=local \
LORE_LOCAL_BASE_URL=http://your-llm-server:8080 \
LORE_LOCAL_MODEL="unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M" \
python benchmarks/run.py --run 1
```

### Starting a local llama.cpp server

The benchmark talks to `llama-server`'s built-in Anthropic-compatible `/v1/messages` endpoint. Start it like this:

```bash
llama-server \
  -hf unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M \
  --host 0.0.0.0 --port 8080 \
  --ctx-size 32768 \
  --jinja --reasoning off \
  --temp 0.7 --top-p 0.8 --top-k 20 --min-p 0.0 --presence-penalty 1.5
```

`--reasoning off` is the current (non-deprecated) flag for disabling thinking mode. It also sidesteps the Windows PowerShell quoting problem — it takes a plain word instead of a JSON string argument.

#### The "thinking→act" empty-turn retry

On roughly 1 in 3 turns with Qwen3.5, the model emits a `<think>...</think>` block and then ends its turn with no tool call. The runner recovers by re-prompting in a fresh user turn. Two fixes were tested and ruled out:

- **`tool_choice: {"type": "any"}`** — accepted but not enforced; model still ends turns with `stop_reason=end_turn`.
- **`--jinja`** — retry rate statistically unchanged (38.5% vs ~36% baseline).

`--reasoning off` removes the failure mode at the root: the chat template inserts a pre-closed `<think>\n\n</think>` block so the model starts generating tool calls immediately. Use the non-thinking sampling profile above — this is Unsloth's documented recommendation for `enable_thinking:false`.

### Running with Ollama

1. Configure Ollama to accept connections from other machines:
   ```bash
   sudo systemctl edit ollama --force
   ```
   Paste the following, save, and close:
   ```
   [Service]
   Environment="OLLAMA_HOST=0.0.0.0:11434"
   ```
   Then restart:
   ```bash
   sudo systemctl daemon-reload && sudo systemctl restart ollama
   ```

2. Set environment variables (replace `<remote-ip>` with the Ollama machine's IP or hostname):
   ```bash
   export LORE_LLM_PROVIDER=local
   export LORE_LOCAL_BASE_URL=http://<remote-ip>:11434/v1
   export LORE_LOCAL_MODEL=qwen2.5-coder:7b
   ```

3. Run the benchmark as normal:
   ```bash
   python benchmarks/run.py --run 1
   ```

> **Model quality note:** `qwen2.5-coder:7b` is capable but significantly weaker than Claude Sonnet on complex geometry tasks. The baseline (Run 1) is likely to fail. This makes the Lore progression signal easier to observe — the delta from Run 1 to Run 4 is more dramatic when the baseline is poor.

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LORE_LLM_PROVIDER` | `anthropic` | `anthropic` or `local` |
| `LORE_LOCAL_BASE_URL` | `http://localhost:11434` | llama.cpp / Ollama-compatible server base URL (no `/v1`) |
| `LORE_LOCAL_MODEL` | `qwen2.5-coder:32b` | Model name for local runs |
| `LORE_API_URL` | `http://localhost:8765` | Lore selfhosted API base URL |

---

## Seeding rationale

Hand-authored seed concepts are available in `benchmarks/seed_concepts/` but are **not injected** in the current design. Lore must bootstrap purely from concepts the model captures organically during each run.

**Why no seeding:** Earlier experiments showed that a single well-targeted seed concept could single-handedly determine success or failure, making it impossible to isolate whether *Lore as a system* is improving — as opposed to the seed concept doing all the work. The 10-run no-seed design measures whether the accumulation of organically-captured knowledge actually helps.

**What this tests:** Whether the full Lore loop (capture → accumulate → search → apply) produces measurable improvement run-over-run when the knowledge base grows entirely from model output. The hypothesis: by run 5–10 the DB should contain enough correct concepts that the model outperforms its run-1 baseline.

**`seed_concepts/` files are preserved** for ad-hoc debugging — you can call `_seed_concepts()` manually in a Python session if you want to test the seeded scenario.

### Seed concepts

| File | Concept | Purpose |
|------|---------|---------|
| `benchmarks/seed_concepts/trimesh_pil_text_to_stl.md` | PIL + scikit-image + trimesh text-to-STL pipeline | Provides the correct library API path the model needs |

---

## Benchmark results

Results are written to `benchmarks/results/run{N}.md` after each run. Cross-run summaries are in `benchmarks/results/comparison.md`.

### Sprint 3 run — qwen2.5-coder:32b (seeded benchmark)

| Run | Lore | Tests | Error type | Tokens | Time |
|-----|------|-------|------------|--------|------|
| 1 | ❌ | 0/13 pass | `text2stl` CLI not installed | 246K | 33 min |
| 2 | ✅ | 2/13 pass | "No contours found for text" | 153K | 101 min |
| 3 | ✅ | 2/13 pass | `main()` missing CLI arg wiring (Click bug) | 136K | 93 min |
| 4 | ✅ | 2/13 pass | `numpy.ndarray has no attribute 'is_empty'` | 385K | 52 min |

**Observations:**

- **Run 1 (no Lore)**: Model hallucinated entirely wrong APIs, never produced a working CLI entry point — 0 tests pass.
- **Runs 2–4 (Lore ON)**: Model immediately searched Lore and adopted the correct library pipeline (PIL + skimage + trimesh.creation.extrude_polygon). Validation tests now pass (2/13). Error type shifted from "wrong API family" to "small mistakes in pipeline details."
- **Run 2**: Correct pipeline, but rendering parameters too small → no pixel contours detected.
- **Run 3**: Correct pipeline, but used Click without `@click.argument()` decorators.
- **Run 4**: Correct pipeline, but called `.is_empty` on a numpy contour array instead of on the Shapely Polygon — the exact hallucination the seed concept warned against.

**Conclusion:** Lore measurably shifted the model's behavior from hallucinated APIs and 0 passing tests to correct library choices and 2 passing tests. The remaining failures are downstream implementation details, not the core API knowledge gap.

### Reasoning-prefix-harness run — qwen2.5-coder:32b, 30-turn budget

| Run | Lore | Tests | Result | Tokens |
|-----|------|-------|--------|--------|
| 1 | ❌ | 2/13 pass | `AttributeError: 'Trimesh' object has no attribute 'extrude'` — hallucinated API | 280K |
| 2 | ✅ (1 concept) | 2/13 pass | Correct pipeline, but overshot `font_size` → "No renderable glyphs found" | 270K |
| 3 | ✅ (8 concepts) | **12/13 pass** | Correct, nearly-complete implementation — only failure was the IoU test (test-harness artifact, see below) | 537K |
| 4 | ✅ (15 concepts) | **12/13 pass** | Same outcome as Run 3, reached in 18 turns / 275K tokens — richer context made the model more efficient | 275K |

### IoU test scale-normalization fix

Runs 3 and 4 both stalled on `test_character_shapes_match_text` (IoU = 0.093 against a 0.25 threshold). Investigation showed the implementation was correct: `_stl_cross_section_bitmap` rasterizes a mesh's cross-section against its own tight bounding box, but the reference bitmap rendered text centered with natural padding at a different effective scale. Two correctly-shaped letters at different scales overlap almost nowhere.

**Fix:** crop the reference bitmap to its own tight glyph bounding box before scaling (`_text_reference_bitmap` in `tests/test_text2stl_cli.py`). Using the same implementation that scored IoU = 0.093 against the old function, the corrected function alone raised it to **0.514**. Run 3 and 4's "1 failed" results were a test-harness artifact — the underlying implementation was already correct.

### Truncation-detection fix

The IoU fix traded one failure mode for a quieter one: an implementation rendering text with an oversized font and bottom-anchored placement (silently clipping the lower portion of each glyph) still passed IoU = 0.514 because both sides of the comparison crop tightly and rescale independently — a truncated fragment that fills the frame can resemble the full glyph well enough to clear the bar.

**Fix:** added `test_character_shapes_not_truncated` alongside (not replacing) the IoU test. It divides tight-cropped bitmaps into 20 bands per axis and computes Pearson correlation between STL and reference ink-density profiles (`_band_profile`, `_min_band_correlation`), asserting the worse axis correlation ≥ 0.3. Truncation removes a contiguous chunk before crop/rescale, reshuffling feature placement in that axis's band layout — a signal whole-image IoU cannot see.

**Validation:** the truncated implementation (24.83% bottom clip) scored band-correlation = -0.019 under the new check, while passing IoU = 0.514 under the old one. A correctly-rendered reference implementation scored 0.646. The two tests now cover orthogonal failure modes: IoU catches wrong/malformed/reordered letters; band-correlation catches truncation that IoU's scale-normalization erases.

### Post-IoU-fix run — seeded sequence

| Run | Lore | Tests | Result | Tokens |
|-----|------|-------|--------|--------|
| 1 | ❌ | 2/13 pass | `module 'trimesh' has no attribute 'contour'` — hallucinated API | 287K |
| 2 | ✅ (1 concept) | 0/13 pass | Invalid `pyproject.toml` — `pip install -e .` failed outright | 379K |
| 3 | ✅ (6 concepts) | **13/13 pass** | First-ever full pass. Model called `submit` on turn 10, got "all tests passed" — 10 turns, 132K tokens | 132K |
| 4 | ✅ (15 concepts) | 2/13 pass | `np.product` removed in NumPy 2.0 — environment drift, not a model/Lore regression | 249K |

Run 4's failure was traced to environment drift: `numpy==2.0.2` alongside a stale cached `trimesh==3.9.10`. All benchmark runs share one global unpinned pip install; a later run can silently bump a shared package and break a stale one. **Open item:** isolate each run's install (per-run venv) or pin dependency floors in the test fixtures.

### No-seed control experiment

Seed concept deleted from DB after Run 1's reset. Runs 2–4 started from organically-captured concepts only.

| Run | Lore | Tests | Result |
|-----|------|-------|--------|
| 1 | ❌ | 3/13 pass | Own glyph pipeline, "No vertices generated for character" |
| 2 | ✅ (0 concepts) | 2/13 pass | `search_concepts` found nothing — broken font file path |
| 3 | ✅ (5 concepts) | 2/13 pass | 15 of 30 turns web-searching for a trimesh text API that doesn't exist; the run's own capture phase recorded "Avoid_FontProperties_get_path" — but too late to apply within the same session |
| 4 | ✅ (9 concepts) | 2/13 pass | New voxel-grid method, re-introduced deprecated `draw.textsize()`, hit "matrix not a valid transformation matrix" |

**Conclusion:** across all 4 runs, accumulating 9 organically-captured concepts never moved the result past 2/13. The seeded sequence reached 13/13 by Run 3. A single well-targeted seed concept was worth more than a larger pile of self-discovered, less-targeted knowledge — the organic concepts were real and accurate but arrived too late, ranked low enough not to consistently surface, or described problems without the complete fix.
