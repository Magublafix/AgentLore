# E2E: `mcp-server-lore init` against the built wheel

Black-box tests: the **built wheel** is run through `uvx --from <wheel> mcp-server-lore init ...`
with the **real `claude` CLI**, in a throwaway HOME / XDG / `CLAUDE_CONFIG_DIR` / TMPDIR / cwd per
scenario. GitHub is replaced by a local stdlib stub (`stubs/github_api.py`). Nothing is published.

## Run locally

```bash
python -m venv .venv-e2e && . .venv-e2e/bin/activate
pip install build pytest uv          # claude must also be on PATH (npm i -g @anthropic-ai/claude-code)
python -m build                      # -> dist/*.whl   (or export LORE_E2E_WHEEL=/abs/path.whl)
python -m pytest e2e/test_init_core.py e2e/test_init_edges.py -m e2e   # (stack tier: pytest e2e/stack -m e2e_stack)
                                     # ~5 min cold, mostly uv resolving the wheel's dependencies
```

Redacted per-command logs land in `e2e/out/` (git-ignored). Tool-schema snapshot:
`LORE_E2E_UPDATE_SNAPSHOTS=1` (with the init tests) rewrites `snapshots/tools_schema.json`; a missing snapshot fails the contract test.
`LORE_E2E_TMP` moves the sandbox root (must be outside your real home).

## Safety rails
Explicit `env=` for every subprocess (never `os.environ`), `stdin=DEVNULL`, hard timeouts, PATH is a
shim dir of symlinks (claude, uvx, uv, python, realpath, dirname[, node]). A session guard fails if the
sandbox is under the real home or if the real `~/.lore` / `~/.claude.json` lore entry changes. A leak
scanner greps all captured output, logs and the sandbox tree for the unique fake tokens of each test.
Test-only hooks (ADR-016): `LORE_INIT_UVX_FROM`, `LORE_ALLOW_INSECURE_TEST_URLS` + loopback URLs.
`init` forwards those override vars to its verification child, so scenarios that need the stub just set them in init's env; tests that spawn the registered command themselves pass them as the "agent environment".

## What each tier covers
- `test_init_core.py`: demo mode, env token (validated, not stored), `--store-token`, idempotent re-run,
  remove + re-init, session.json untouched, registered command answers (tool list, schema snapshot,
  `search_concepts` shape, typed `read_only` errors).
- `test_init_edges.py`: project-scope refusals, demo/token mode switch with and without `--force`,
  `--local`, `--dry-run`, missing `claude` / `uvx`, no TTY, `--no-verify`, verification failure,
  401 vs 5xx vs timeout.

## What this proves WITHOUT a login
No API key or `claude` login is needed. `claude mcp add/get/list/remove` are pure config handling,
and `claude mcp get` / `claude mcp list` really spawn the registered stdio server, perform the MCP
handshake and print `Status: ✔ Connected` or `✘ Failed to connect` + `Issue: <reason>`. The suite
therefore proves, with Claude Code's own code path (not just our client): the registration is written
to the right scope with the right command/args/env, Claude Code can start that exact command from the
isolated environment and complete the handshake (retried until a generous deadline, since a cold uv
cache downloads dependencies), and a broken command is reported as `Failed to connect` with a reason
(scenario 14 and the negative control, which breaks the command after a passing init).

## What it cannot prove
An authenticated session in which a model chooses to call `search_concepts`, tool-permission
prompts, and the interactive `/mcp` UI. These stay on the manual release checklist; an optional future
scheduled canary using an API key could cover the first.

## NOT covered (manual release checklist)
- Real interactive TTY (hidden token prompt, Enter for demo mode)
- Windows and macOS desktop behaviour (macOS runs in CI as non-blocking only)
- An authenticated Claude session actually calling the tool
- The real published PyPI artifact (`uvx mcp-server-lore` without `--from`)
- Corporate proxies / custom CAs / offline mirrors
- The real GitHub token flow (scopes, gist creation, rate limits) and `gh auth token`

## Stack tier (`e2e/stack`, marker `e2e_stack`)

Black-box test of the semantic server as ONE real process: fixture-driven fake GitHub
(`e2e/stubs/gist_stub.py`: gist web search HTML shaped like the captured fixtures, gist/comment/feed
JSON, spam / unmarked / 3 MB gists, block / 429 / 5xx modes, request log) -> watcher bootstrap and poll
loop -> Qdrant -> `GET /search` -> the real `lore.mcp.server` over stdio (`LORE_READ_ONLY=1`,
`LORE_SEMANTIC_URL`). Qdrant is `QdrantClient(":memory:")` via the test-only
`LORE_QDRANT_IN_MEMORY=1` (honoured only with `LORE_ALLOW_INSECURE_TEST_URLS=1`, ADR-016), so no
Docker or Qdrant service is needed and the server must run with one worker.

Run locally (one heavy process at a time; torch + the cached `all-MiniLM-L6-v2` are required):

    pip install "dist/mcp_server_lore-*.whl[selfhosted]" pytest
    pytest e2e/stack -m e2e_stack

Without an installed wheel point `LORE_STACK_PYTHON` at an interpreter with the `selfhosted` extra and
set `LORE_STACK_PYTHONPATH=<checkout>` (fallback; CI sets `LORE_STACK_REQUIRE_INSTALLED=1`, which
fails if `lore` resolves into the checkout). Redacted logs, stub request logs and peak RSS land in
`e2e/out/stack/`.

What it proves: bootstrap discovery with the real parser, validity filtering (spam/unmarked/huge
skipped), embedding + search ranking on keyword-free paraphrases, rating comments surfacing, poll-loop
discovery of a new gist, the full MCP chain without `fallback`, degraded web search (block page, 429,
5xx) keeps partial results and the poll loop, the token reaches only the stub (never the web search,
logs or output), and bounded behaviour (request counts, log volume, RSS < 3 GiB) as a guard against
runaway loops. Production clamps the bootstrap page delay to >= 2 s; the stack tests keep it (about
10 s per server start).

What it does NOT prove: real Qdrant (persistence, restart, payload indexes, which local mode ignores),
real GitHub HTML/API behaviour and rate limits, the Docker image, `docker compose` wiring and
healthchecks, GPU, multi-worker deployment. The compose/Docker path stays covered only by the
existing Docker build workflow (`.github/workflows/docker.yml`).
