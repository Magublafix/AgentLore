# Phase 4 — Summary
**Period:** 2026-07-15 → 2026-07-25   **Status:** ✅ Complete

## Delivered

| Item | Description | Tokens used |
|------|-------------|-------------|
| LORE-039 | Modernise `pyproject.toml` — rename to `mcp-server-lore`, hatchling build backend, `uvx` entry point via `main()` in `lore/mcp/server.py` | — |
| LORE-040 | CI/CD publishing — `.github/workflows/ci.yml` (tests on every PR/push), `.github/workflows/publish.yml` (PyPI via OIDC + Docker Hub on `v*` tag), root `Dockerfile` for thin MCP server image | — |
| LORE-042 | Flip `LORE_CAPTURE_MODE` default to `auto` — agents now submit concepts without prompting; `confirm` mode available via env var opt-in | — |
| Benchmark fixes | Watcher bootstrap switched to GitHub code search API; comment-based rating aggregates (`_fetch_rating_aggregates`); `rate_concept` always creates new comment; `gist_qdrant` updates rating fields on idempotency skip; benchmark loop guards (concept cap, consecutive-duplicate rate_concept detection, pip `--no-deps` + `TimeoutExpired`) | — |

## What Works Now

An agent can install the MCP server with `uvx mcp-server-lore` — no pip, no virtualenv, no clone. Pushing a `v*` tag now triggers a fully automated publish pipeline: tests run first, then the package lands on PyPI via OIDC trusted publishing (no stored credentials), and a thin Docker image is pushed to Docker Hub. Capture is autonomous by default: when `lore:capture-concept` fires, concepts are submitted immediately without interrupting the agent for confirmation. The watcher bootstrap now uses GitHub code search to locate Lore concept gists rather than paginating all public gists, and rating aggregates are computed from gist comments rather than embedded in `lore.json`.

## Code Coverage

```
TOTAL    6881    304    96%
605 passed, 2 skipped, 3 warnings in 144.87s
```

Down ~1 pp from Phase 3 (97%) due to new watcher bootstrap code paths (`_search_lore_gists`, `_fetch_rating_aggregates`) that are exercised by integration paths not covered by the unit mock suite. All other modules remain ≥88%. Coverage threshold of 80% is met.

## Known Gaps / Deferred

- **Registry submissions** (Smithery.ai + `registry.modelcontextprotocol.io`) — GitHub issue #11. Requires the PyPI package to be live first.
- **Concept graph browser** (read-only web UI) — GitHub issue #13. Lower priority until v1.0 is published.
- **First publish** requires manual one-time setup: PyPI trusted publisher config + Docker Hub secrets. Steps documented in GitHub issue #12.
- `watcher.py` coverage at 66% — bootstrap and poll-cycle integration paths are hard to unit-test without live GitHub API mocks; acceptable for now.

## Next Phase — Candidate Items

- LORE-037: Noise resilience benchmark — seeded wrong concepts at medium ratings to test graph robustness
- LORE-028: Extended 30-series stlgen benchmark for statistical confidence
