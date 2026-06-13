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

## Running the benchmark

```bash
python benchmarks/run.py --run 1   # baseline (clears DB, no Lore)
python benchmarks/run.py --run 2   # Lore ON, unrated concepts from Run 1
python benchmarks/run.py --run 3   # Lore ON, concepts rated after Run 2
python benchmarks/run.py --run 4   # Lore ON, all prior concepts rated
```

By default the runner uses the Anthropic API. To use a self-hosted LLM instead, see the next section.

## Running with a local LLM (Ollama)

### On the remote machine

1. Install Ollama:
   ```bash
   curl -fsSL https://ollama.ai/install.sh | sh
   ```

2. Configure Ollama to accept connections from other machines:
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

3. Pull the model (runs automatically on first use, but pulling first avoids mid-benchmark delays):
   ```bash
   ollama pull qwen2.5-coder:7b
   ```

4. Verify it is reachable:
   ```bash
   curl http://localhost:11434/api/tags
   ```

### On the machine running the benchmark

1. Install the `openai` Python package (used as the HTTP client for Ollama's OpenAI-compatible API):
   ```bash
   pip install openai
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

## Benchmark results

See `results/run*.md` for token and turn counts from each benchmark run, and `results/comparison.md` for the cross-run summary.
