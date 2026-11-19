# Cross-task knowledge-transfer experiment — design (LORE-053)

**Status:** design only — no experiment has been run. Implementation is tracked in backlog stories LORE-057 to LORE-059.

## Question

Do concepts that AgentLore captured while the agent built one CLI (`text2stl`, the *source* task) help it on a structurally similar but different CLI (the *target* task)? The stlgen results show within-task improvement; they say nothing about whether the knowledge is general or just task-specific recall.

## Transfer task

The existing `radev` CLI (`samples/radev`: a JSON REST client with `list / get / create / update / delete`) is the **source of the evaluation harness**, not the target. The target is a **new image-processing CLI, `imgtool`**, built on the same recipe: a fixed pytest suite, `pip install -e .`, console-script entry point, JSON on stdout, non-zero exit on error.

Why this pairing: `text2stl` (source) and `imgtool` (target) share no domain knowledge (STL meshes vs. raster images) but share engineering structure (input validation, error handling, modular design, packaging). A domain-specific concept such as "STL winding order" cannot help `imgtool`; a general one can. That separates *transfer of engineering practice* from *recall of domain facts*. `radev` is retained as a second, easier source (network client, different domain again) so that transfer can be measured from two origins.

### Scope of `imgtool` (target)

Subcommands, each reading a file path and writing JSON (or an output image):

| Command | Behaviour |
|---------|-----------|
| `imgtool info <file>` | width, height, format, mode |
| `imgtool resize <file> --width W [--height H] -o OUT` | keeps aspect ratio when only one dimension given |
| `imgtool convert <file> --to {png,jpeg,bmp} -o OUT` | format conversion |
| `imgtool grayscale <file> -o OUT` | luminance conversion |
| `imgtool thumbnail <file> --max N -o OUT` | fit inside N×N |

Out of scope: filters, batch mode, network access. Dependency: Pillow only. Same 40-turn budget, same model and same 10-run series structure as the stlgen benchmark.

### Test-suite outline (`samples/imgtool/tests/test_imgtool_cli.py`, ~14 tests)

1. Entry point installed; `--help` exits 0.
2. `info` reports correct size/format for PNG, JPEG, BMP fixtures.
3. `resize` exact size; aspect ratio preserved; refuses zero/negative/non-integer sizes.
4. `convert` to each format; output re-opens in the target format; unknown format rejected.
5. `grayscale` output mode is `L`; pixel luminance within tolerance of a reference.
6. `thumbnail` never exceeds N in either dimension and never upscales.
7. Missing file, directory instead of file, and non-image file each exit non-zero with a message on stderr and **no traceback**.
8. Refuses to overwrite its own input; creates no partial output on failure.
9. Machine-readable output: stdout is valid JSON for every success path.

Tests 7–8 are where the transferable concepts are most directly exercised.

## Conditions

All conditions use the same task, model, 40-turn budget and run structure, and are compared with the analysis from LORE-052 (mixed-effects logistic with series as random effect, within-series permutation test).

| Condition | Knowledge available on `imgtool` | Notes |
|-----------|----------------------------------|-------|
| **transfer** | Frozen snapshot of the concepts captured at the end of a source `text2stl` series (and, in a variant, a `radev` series). Read-only: the agent can search but captured concepts are not added to the snapshot between runs. | Snapshot taken from a completed series; its id/hash is recorded. |
| **none** | No AgentLore tools or concepts (the `control` condition from LORE-050). | Baseline for repeated-attempt effects. |
| **random-context** | Token-matched dump of unrelated concepts (the `random` condition from LORE-051), matched to what `transfer` retrieves for the same run. | Feasible: the mechanism already exists; the pool must contain no image-processing or CLI-engineering concepts. |

A fourth, optional condition, **within-task** (fresh knowledge DB that grows across runs on `imgtool`), reproduces the stlgen design on the new task and shows how much of the benefit is available without any transfer. It is the upper reference, not a required arm.

Freezing the snapshot (rather than letting it grow) keeps `transfer` runs independent apart from series effects; otherwise the arm mixes transfer with within-task accumulation.

## Concepts expected to transfer

Defined **before** the experiment, from the stlgen concept store, by tagging concepts as general or domain-specific (two reviewers; disagreements resolved by a third). Expected general concepts:

- **Input validation** — validate arguments and file inputs up front, reject out-of-range values with a clear message and exit code 1.
- **Error handling** — catch library exceptions at the CLI boundary, message to stderr, no traceback, non-zero exit, no partial output.
- **Modular design** — separate argument parsing, core logic and I/O so each is testable.
- **Packaging** — `pyproject.toml` entry point, declaring every test-imported dependency.

Domain-specific concepts (STL, meshes, fonts) are expected *not* to transfer and act as a built-in negative control: if only those are retrieved, no benefit is predicted.

## Measuring transfer

Primary outcome: pass/fail of the full `imgtool` suite per run (binary, as in stlgen), analysed per LORE-052 with `transfer` vs `none` and `transfer` vs `random-context` contrasts.

Secondary, to show *which* knowledge mattered:

- Per-test pass rate for tests 7–8 (validation / error handling) against the rest.
- Turns to first passing test run, and turns used out of 40.
- Retrieval log: which retrieved concepts are tagged general vs domain-specific, and the share of general ones in the agent's first search.
- Ablation (if the effect is positive): re-run `transfer` with general concepts removed, then with domain-specific removed.

### Pre-registered interpretation

- `transfer` > `none` **and** `transfer` > `random-context`: evidence that captured knowledge, not extra context or practice, helps.
- `transfer` ≈ `random-context` > `none`: benefit is extra context, not content.
- `transfer` ≈ `none`: no transfer detected at this sample size; report the confidence interval, not "no effect".

## Threats to validity

- One source task, one target task: results do not generalise across task pairs.
- Model-specific: stlgen used a quantized local model; transfer may differ on other models.
- The general/domain-specific tagging is subjective; mitigated by reviewing before running and by the ablation.
- Pass/fail is coarse; the secondary measures are exploratory.
- Series count must come from a power estimate using the LORE-052 variance estimates (as in LORE-054), recorded before running.

## Implementation stories (added to the backlog)

- LORE-057 — `imgtool` target task: spec, fixtures and pytest suite.
- LORE-058 — runner support for a frozen read-only knowledge snapshot (`transfer` condition) and concept tagging.
- LORE-059 — run and analyse the transfer experiment.
