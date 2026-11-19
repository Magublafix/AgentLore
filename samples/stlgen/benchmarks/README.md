# stlgen benchmark

See [`../README.md`](../README.md) for the full benchmark documentation: task description, run structure, how to run (Anthropic + llama.cpp + Ollama), seeding rationale, and all result series.

## Conditions and analysis (Sprint 12)

```bash
python benchmarks/run.py --series 5 --condition control
python benchmarks/run.py --series 5 --condition random --match-series 1   # or --random-target-tokens N
python benchmarks/bench_stats.py --results results --out results/analysis.md
```

See the "Controlled Conditions" section of [`../BENCHMARK.md`](../BENCHMARK.md). The cross-task transfer design is in [`../../TRANSFER_EXPERIMENT.md`](../../TRANSFER_EXPERIMENT.md).
