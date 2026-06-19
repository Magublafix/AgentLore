# Benchmark Comparison — stlgen (web-search era)

## Run Summary

| Run | Lore | Concepts in DB | Total tokens | Elapsed | Main turns | Capture turns | Wrapup turns | Tests | Concepts added |
|-----|------|---------------|-------------|---------|-----------|--------------|-------------|-------|---------------|
| 1 | ❌ no | 1 (seed) | 175,804 | 3097s | 20 | 15 | 6 | ❌ FAIL | +6 |
| 2 | ✅ yes | 7 | 259,702 | 6112s | 20 | 15 | 10 | ❌ FAIL | +5 |
| 3 | ✅ yes | 12 | 253,588 | 4241s | 20 | 15 | 10 | ❌ FAIL | +5 |
| 4 | ✅ yes | 17 | 213,277 | 6945s | 20 | 15 | 15 | ❌ FAIL | +10 |

No run passed. All 4 hit the 20-turn main loop limit.

## Error Progression

| Run | Terminal error |
|-----|---------------|
| 1 | `AttributeError: module 'trimesh.path.polygons' has no attribute 'find_contours'` — hallucinated API |
| 2 | `struct.error: unpack requires a buffer of 16 bytes` — base64-encoded TTF written as literal text, corrupted |
| 3 | `ImportError: cannot import name 'main' from 'text2stl.cli'` — function not defined |
| 4 | `ImportError: cannot import name 'cli_entry' from 'text2stl.__main__'` — wrong function name in entry point |

Errors got simpler over time (hallucinated API → packaging mismatch), suggesting the model is getting closer to a correct implementation — but never bridged the last gap within 20 turns.

## Approach Taken Each Run

All 4 runs arrived at different implementations:
- **Run 1**: `trimesh.path.polygons.find_contours` (hallucinated)
- **Run 2**: FontTools + base64-embedded TTF (corrupted font file)
- **Run 3**: FontTools + Shapely (correct structure, broken entrypoint)
- **Run 4**: FontTools + Shapely via `__main__` (still broken entrypoint)

The seed concept (`PIL + scikit-image + trimesh`) was **searched on turn 1 of every Lore-ON run** but **never implemented**. The model treated the Lore result as one signal among many, then immediately pivoted to FontTools via web search. Final DB state confirms this: seed concept rating = **0.0**, usage_count = **0**.

## Token Trend

```
Run 1 (no Lore):  175,804  ████████████████░░░░░░░░░
Run 2 (Lore ON):  259,702  ████████████████████████░
Run 3 (Lore ON):  253,588  ███████████████████████░░
Run 4 (Lore ON):  213,277  ███████████████████░░░░░░
```

Run 2 spike: first Lore-ON run also gained working capture+wrapup (previously 0 turns in the pre-fix Run 1). Run 4 is the lowest Lore-ON run, suggesting some efficiency gain from accumulated concepts — but it's confounded by different behavior each run.

## Key Findings

### What worked
- **Capture phase fix** (context trimming to last 4 turns): resolved 0-turn capture issue from context overflow.
- **Lore search IS triggered**: every Lore-ON run searched concepts on turn 1.
- **Wrapup works**: concepts rated across Runs 2–4.
- **Error documentation flows forward**: Run 3 captured `Specific ImportError`, Run 4 captured 10 entry-point concepts — these will be available to future runs.

### What didn't work
- **Seed concept ignored**: the model finds the correct PIL+skimage pipeline in Lore but pivots away to FontTools via web search every time. Web search competes with and overrides Lore.
- **No convergence**: all runs fail; the model never builds on the previous run's progress because each run starts from scratch.
- **Wrong approach locked in**: FontTools is dominant in the captured concept DB (high ratings), while the correct skimage approach has rating 0. Future runs will have Lore pointing them *toward* FontTools, which is incorrect.

## Hypothesis Assessment

> "Lore reduces tokens/turns vs web-search-only by steering the model to the correct approach faster."

**Partially supported, partially refuted:**
- ✅ Model does search Lore first and code earlier (Run 3 jumped to code on turn 2 with no web-search spiral)
- ❌ Model doesn't *follow* Lore's recommended approach — web search overrides it
- ❌ Lore DB accumulates the *wrong* knowledge (FontTools patterns rated highly)
- ⚠️ Token comparison is confounded by capture/wrapup now working (adds ~80-100K tokens to Lore-ON runs)

## Suggested Next Steps

1. **Strengthen Lore signal**: add a system-prompt instruction like "If Lore returns a concept with a complete code example, use that approach before web searching."
2. **Disable or rate-limit web search for Lore-ON runs**: isolate the Lore signal — the current design gives the model an easy escape from Lore.
3. **Longer turn budget**: 20 turns isn't enough for this task with a local 32B model. 30 turns might allow it to fix the packaging issues after getting geometry working.
4. **Clear wrong concepts**: the DB now has FontTools-based patterns rated 3–4.25 and the correct skimage pattern rated 0. A future run will be steered toward a known-broken approach.
