# Power estimate for LORE-054 (recorded 2026-11-18, before any new runs)

Basis: existing 10 agentlore series (179 runs): pass rate 45.3%, between-series SD sigma = 1.435 (logit),
within-series run slope 0.132/run (`bench_stats.py`). Simulation: 10 runs per series, same run slope in
both conditions, condition effect as a logit shift, Mann-Whitney on per-series pass rates (series = unit),
alpha = 0.05 two-sided, 1500 simulations per cell (seed 0). The mixed model uses the same information, so
power is expected to be similar, not much higher.

| Series per condition | OR 1.5 | OR 2 | OR 3 |
|---|---|---|---|
| 5  | 0.04 | 0.07 | 0.11 |
| 10 | 0.07 | 0.14 | 0.26 |
| 15 | 0.11 | 0.19 | 0.39 |
| 20 | 0.12 | 0.23 | 0.50 |
| 25 | 0.13 | 0.28 | 0.61 |
| 30 | 0.15 | 0.37 | 0.69 |
| 40 | 0.18 | 0.44 | 0.82 |

Reading: between-series variance dominates. Even 30 series per condition detects only a large effect
(OR about 3) with reasonable power. Smaller effects will not be resolvable with this design, so null
results must be reported as inconclusive, not as "no effect".
