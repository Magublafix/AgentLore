# stlgen benchmark

Measures whether Lore helps a local LLM complete a coding task it cannot reliably solve on its own.

## Task

Build a `text2stl` CLI that converts a text string (≤15 chars) into a 3D-printable STL file with raised letters. The implementation must pass 13 pytest tests covering invocation, geometry, and mesh validity.

## Run structure

| Run | Lore active | DB state at start | Purpose |
|-----|-------------|-------------------|---------|
| 1   | ❌ no        | empty (reset on start) | Control — baseline without Lore |
| 2   | ✅ yes       | Run 1 concepts | Lore ON with concepts captured in Run 1 |
| 3–10 | ✅ yes      | accumulates each prior run | Does accumulated organic knowledge improve results? |

Run 1 is the single control and always resets the DB to empty. Runs 2–10 have Lore ON with progressively richer context from prior runs. No hand-authored seed concepts — Lore must bootstrap entirely from concepts the model captures organically.

## How to run

```bash
# Cloud Claude (anthropic provider)
python benchmarks/run.py --run 1

# Local model via an Anthropic-compatible server (llama.cpp or Ollama)
LORE_LLM_PROVIDER=local \
LORE_LOCAL_BASE_URL=http://your-llm-server:8080 \
LORE_LOCAL_MODEL="unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M" \
python benchmarks/run.py --run 1
```

### Starting the local llama.cpp server

The benchmark talks to `llama-server`'s built-in Anthropic-compatible
`/v1/messages` endpoint, not Ollama — `/health` and `/props` on port 8080
confirm a llama.cpp server (`build_info` like `bNNNN-<hash>`), and Ollama's
own port (11434) isn't even open on that host. Start it like this:

```bash
llama-server \
  -hf unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M \
  --host 0.0.0.0 --port 8080 \
  --ctx-size 32768 \
  --jinja --reasoning off \
  --temp 0.7 --top-p 0.8 --top-k 20 --min-p 0.0 --presence-penalty 1.5
```

`--reasoning off` is the current (non-deprecated) flag for disabling
thinking mode — `--chat-template-kwargs '{"enable_thinking":false}'` still
works but `llama-server` now warns it's deprecated in favor of
`--reasoning on`/`--reasoning off`. `--reasoning off` also sidesteps the
Windows PowerShell quoting problem entirely, since it takes a plain word
instead of a JSON string argument — no quote-escaping pitfalls. (For the
record, if you ever do need to pass a literal JSON-string argument to a
native exe from PowerShell: neither `\"`-escaped double quotes nor a plain
single-quoted string reliably survive PowerShell's argument reconstruction
before invoking the native process — the stop-parsing token `--%` followed
by literal `\"`-escaped JSON is the reliable workaround, e.g.
`.\llama-server.exe --% --chat-template-kwargs "{\"enable_thinking\":false}"`.)

### The "thinking→act" empty-turn retry, and what actually fixes it

On roughly 1 in 3 turns with this model, the model emits a `<think>...</think>`
block and then ends its turn with **no tool call** — `run.py` recovers by
re-prompting in a fresh user turn ("now output exactly one tool call"),
which works but costs an extra turn each time. Two hypotheses were tested
and ruled out by live validation before finding the actual lever:

- **`tool_choice: {"type": "any"}`** — accepted by the request but not
  enforced; the model still ends turns with `stop_reason=end_turn` and only
  a `thinking` block.
- **`--jinja`** — accepted, confirmed active (sampler settings from `/props`
  changed after restart), but the retry rate was statistically unchanged
  (38.5% post-restart vs. ~36% baseline). `GET /props` reports
  `"chat_format": "Content-only"` and `"reasoning_format": "none"`
  regardless of `--jinja` for this model/build — this llama.cpp build does
  not appear to grammar-constrain tool-call output for this template family,
  so there's nothing for `--jinja` to lock down. Also ruled out:
  re-downloading the GGUF (the locally cached snapshot already matched the
  latest upstream commit, including Unsloth's official tool-calling
  chat-template fix from March 5).
- Assistant-message prefill (priming the next turn with a partial tool-call
  JSON object) is rejected outright with a `500: "model produced output
  that does not match the expected peg-native format"` — the shim's parser
  expects the Hermes-style `<tool_call>` XML it's configured for, not raw
  JSON, so this isn't a viable workaround either.

**`--chat-template-kwargs "{\"enable_thinking\":false}"`** removes the
failure mode at the root instead of trying to make thinking-mode reliable:
the chat template inserts a pre-closed, empty `<think>\n\n</think>\n\n`
block directly into the prompt when thinking is disabled, so the model
starts generating real content/tool-calls immediately rather than ever
having the option to trail off after an open-ended `<think>` block. Use the
non-thinking/instruct sampling profile above (different from the
thinking-mode profile: temp 0.6–1.0, no presence penalty) — this is
Unsloth's documented recommendation for `enable_thinking:false`, not a
guess. `run.py`'s existing user-turn retry still serves as a safety net
regardless, since no amount of template engineering stops a model from
genuinely declining to act.

Run all 10 sequentially (resets DB on Run 1, accumulates across runs):

```bash
python benchmarks/run.py --all
```

Or step through individually:

```bash
for i in $(seq 1 10); do python benchmarks/run.py --run $i; done
```

## Seeding rationale

Hand-authored seed concepts are available in `seed_concepts/` but are **not injected** in the current design. Lore must bootstrap purely from concepts the model captures organically during each run.

**Why no seeding:**

Earlier experiments (see "Post-IoU-fix run" and "No-seed control experiment" results below) showed that a single well-targeted seed concept could single-handedly determine success or failure, making it impossible to isolate whether *Lore as a system* is improving — as opposed to the seed concept doing all the work. The 10-run no-seed design measures whether the accumulation of organically-captured knowledge actually helps.

**What this tests:**

Whether the full Lore loop (capture → accumulate → search → apply) produces measurable improvement run-over-run when the knowledge base grows entirely from model output. The hypothesis: by run 5–10 the DB should contain enough correct concepts that the model outperforms its run-1 baseline.

**`seed_concepts/` files are preserved** for ad-hoc debugging — you can call `_seed_concepts()` manually in a Python session if you want to test the seeded scenario.

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

### Truncation-detection fix

The IoU fix above traded one failure mode for a quieter one. A separately
inspected implementation rendered text into a bitmap using an oversized
font (`font_size = canvas_height * 0.75`) combined with bottom-anchored
placement (`y = canvas_height - text_height`); the lower portion of every
glyph fell outside the render canvas and was silently dropped by PIL before
the mesh was ever built. Opening the resulting STL showed only the upper
half of each letter — the lower half was simply missing. Despite this,
`test_character_shapes_match_text` passed: IoU = 0.514 against the 0.25
threshold.

**Root cause of the blind spot:** both sides of the IoU comparison crop
tightly to their own non-zero bounding box and *independently rescale* to
the same fixed frame before comparing — exactly the convention the fix
above introduced, and necessarily so (see previous section). The side
effect: a glyph missing a contiguous chunk of its extent still gets
stretched to fill the frame after cropping, and the surviving fragment can
resemble the full glyph well enough to clear the IoU bar purely on
remaining-shape similarity. Sweeping the same implementation's font-size
fraction from 0.40 to 0.75 (canvas size and bottom-anchored placement held
fixed) showed it clips approximately 24-25% of the glyph's true height at
every setting — a near-constant fraction, since the cause is structural
(font metrics relative to canvas height), not incidental — and the old IoU
test passed at four of the eight fractions tested (IoU 0.25-0.51 against
the 0.25 threshold), failing only at the most extreme settings where the
remaining fragment stopped resembling the reference shape at all. A single
global aspect-ratio check on the tight bounding box was tried first and
rejected: it works when truncation happens on only one axis, but this
implementation's font size also overflowed the canvas *width*, clipping
horizontally too, and the two clips partially canceled in the aspect ratio
(STL tight-bbox aspect 4.63 vs. reference 4.10 — only an 11% deviation,
inside any tolerance wide enough to keep allowing legitimate scale
variation).

**Fix:** added `test_character_shapes_not_truncated`, a second, independent
test alongside (not replacing) the IoU test. It divides the same
tight-cropped bitmaps into 20 bands along each axis and computes the
Pearson correlation between the STL and reference ink-density profiles per
axis (`_band_profile`, `_min_band_correlation` in
`tests/test_text2stl_cli.py`), asserting the worse of the two axis
correlations is >= 0.3. Truncation removes a contiguous chunk of the glyph
along one axis *before* the crop/rescale, which reshuffles where the
remaining features (crossbars, counters, serifs) land in that axis's band
layout — a signal whole-image IoU overlap cannot see, because rescaling a
truncated fragment to fill the frame is exactly what erases it. Checking
both axes and taking the minimum catches truncation regardless of which
axis it happens on (or both at once, as in the case above). Because the
check runs on the same already-tight-cropped bitmaps the IoU test uses,
legitimate scale/padding variation — the exact case the IoU fix was
protecting — washes out identically: an untruncated glyph reproduces the
reference's band profile almost exactly (correlation ~1.0) regardless of
how much padding surrounded it before cropping.

**Validation:** against the implementation described above (24.83% bottom
clip, IoU = 0.156, the most severe font-size setting in the sweep), the new
check scored band-correlation = -0.019. Against the mildest setting that
still cleared the old IoU bar (font fraction 0.55, 24.41% bottom clip,
IoU = 0.514 — a clean "pass" under the pre-existing test), the new check
scored -0.003 — still well below the 0.3 threshold. Across the full
0.40-0.75 sweep, every truncated variant scored between -0.094 and 0.207,
never approaching 0.3. A correctly-rendered, non-clipped reference
implementation (different extrusion method — marching-squares contouring
instead of per-column box-stacking, to rule out a method-specific
coincidence) scored 0.646 on the new check and continued to pass the
existing IoU test unchanged. The two tests now cover orthogonal failure
modes: IoU catches wrong/malformed/reordered letters, band-correlation
catches truncation that IoU's scale-normalization can no longer see.

A combined aspect-ratio-only check (single scalar, no per-axis band
profile) was tried and rejected for the reason above: it is fooled
whenever clipping happens on both axes at once, which is not a contrived
edge case — it is what this real implementation actually did, since an
oversized font tends to overflow both canvas dimensions together.

### Post-IoU-fix run — seeded sequence

Same harness as above, re-run from a fresh DB after the IoU fix landed.

| Run | Lore | Tests | Result | Tokens |
|-----|------|-------|--------|--------|
| 1 | ❌ | 2/13 pass | `module 'trimesh' has no attribute 'contour'` — hallucinated API | 287K |
| 2 | ✅ (1 concept) | 0/13 pass | Invalid `pyproject.toml` (`[project.dependencies]` as a bare table instead of a `dependencies = [...]` array) — `pip install -e .` failed outright, worse than the no-Lore floor | 379K |
| 3 | ✅ (6 concepts) | **13/13 pass** | First-ever full pass in the benchmark's history. Model called `submit` on turn 10 and got back "all tests passed" directly — 10 turns, 132K tokens, by far the most efficient successful run | 132K |
| 4 | ✅ (15 concepts) | 2/13 pass | `AttributeError: module 'numpy' has no attribute 'product'` — environment artifact, not a model/Lore regression (see below) | 249K |

**Run 4's failure was traced to environment drift, not the model.** The
crash happens inside trimesh's own `mass_properties` calculation
(`np.product`, removed in NumPy 2.0) and reproduces on *any* mesh,
including `trimesh.creation.box()` with zero custom code:
`numpy==2.0.2` was present alongside an ancient cached `trimesh==3.9.10`.
Run 3 — immediately prior, same session, no explicit version-changing
installs in its log — passed its own volume-dependent test cleanly, so the
combination must have drifted in between. All benchmark runs share one
global, unpinned `pip install -e .` user-site install
(`~/.local/lib/pythonX.Y/site-packages`) across ephemeral run directories;
a later run declaring a slightly different dependency set can let pip's
resolver silently bump a shared package like `numpy` without ever
touching an already-"satisfied" package like the stale `trimesh`,
breaking it. **Open item:** isolate each run's install (per-run venv) or
pin dependency floors/ceilings in the test fixtures to prevent this class
of cross-run contamination.

### No-seed control experiment

To isolate what the hand-authored seed concept actually contributes, the
seed was stripped from the DB immediately after Run 1's automatic
reset+seed (the seed file stays in `seed_concepts/` — only the DB row was
deleted). Runs 2–4 therefore started from concepts the model captured
*organically* from its own web searches and mistakes, with no
hand-authored boost at any point.

| Run | Lore | Tests | Result |
|-----|------|-------|--------|
| 1 | ❌ | 3/13 pass | Own glyph pipeline, "No vertices generated for character" — broadcast shape error in triangulation |
| 2 | ✅ (0 concepts) | 2/13 pass | `search_concepts` found nothing (confirmed "Lore ON (0 concepts)" in the run banner). `FT_Exception: unknown file format` — broken font file path |
| 3 | ✅ (5 concepts) | 2/13 pass | Spent ~15 of 30 turns web-searching for a working trimesh text API that doesn't exist as a single function, before pivoting late to `matplotlib.font_manager`. Final implementation called `FontProperties.get_path()` — which doesn't exist — and crashed. The run's own capture phase recorded a concept titled "Avoid_FontProperties_get_path" warning against exactly this mistake, but too late to apply within the same session |
| 4 | ✅ (9 concepts) | 2/13 pass | Abandoned the font-glyph approach entirely for a new voxel-grid method, re-introducing the deprecated `draw.textsize()` API from an unrelated earlier run, then hit a new failure: "matrix not a valid transformation matrix" |

**Conclusion:** across all 4 runs, accumulating 9 organically-captured
concepts never moved the result past the same 2/13 floor that Run 1 (no
Lore at all) also hit. This is a sharp contrast with the seeded sequence,
which reached 13/13 by Run 3. A single well-targeted seed concept handing
over the *exact* working pipeline was worth more than a larger pile of
self-discovered, less-targeted knowledge — the organic concepts were real
and accurate (e.g. the FontProperties warning) but arrived too
late, were ranked low enough not to consistently surface, or described
problems without the complete fix.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LORE_LLM_PROVIDER` | `anthropic` | `anthropic` or `local` |
| `LORE_LOCAL_BASE_URL` | `http://localhost:11434` | llama.cpp / Ollama-compatible server base URL (no `/v1`) — see [Starting the local llama.cpp server](#starting-the-local-llamacpp-server) |
| `LORE_LOCAL_MODEL` | `qwen2.5-coder:32b` | Model name for local runs |
| `LORE_API_URL` | `http://localhost:8765` | Lore selfhosted API base URL |
