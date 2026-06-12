# Benchmark — Comparison

| Metric | Run 1 (no Lore) | Run 2 (with Lore) | Delta |
|--------|-----------------|-------------------|-------|
| Date | 2026-06-11 16:21 | 2026-06-11 16:26 | — |
| Model | claude-sonnet-4-6 | claude-sonnet-4-6 | — |
| Lore skills active | no | yes (8 concepts) | — |
| Turns | 21 | 17 | **-19.0%** |
| Input tokens | 158,121 | 146,442 | **-7.4%** |
| Output tokens | 5,158 | 4,425 | **-14.2%** |
| Total tokens | 163,279 | 150,867 | **-7.6%** |
| Elapsed | 160.9s | 143.7s | **-10.7%** |
| Tests passed | ✅ 9/9 | ✅ 9/9 | — |

## Notes

- Both runs built the same `radev` CLI from scratch against a local mock server mirroring restful-api.dev.
- Run 1 captured concepts via the `capture-concept` skill post-submission; Run 2 searched those concepts before building.
- Token savings are conservative — the 8 concepts available in Run 2 were captured during Run 1 of this same benchmark session. A mature Lore graph with domain-relevant concepts would be expected to show larger reductions.
- The turn reduction (-19%) is the strongest signal: the agent reached the solution faster with fewer back-and-forth iterations.
