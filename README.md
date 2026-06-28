# Lore

**A typed, linked knowledge graph for AI coding agents.**

Lore lets Claude Code agents search for reusable patterns, capture new ones, and rate what actually helped — so every agent session builds on the work of the last.

---

## What it does

When you invoke `/search-concepts`, the agent queries a local knowledge graph for concepts matching the current problem. It gets back not just the best match but the full linked graph — architecture decisions, test strategies, related tools — in a single call. No second round-trip.

At session end, a Stop hook prompts the agent to rate what it used and capture anything worth preserving for the next session.

---

## Prerequisites

- Docker + Docker Compose
- Python 3.11+
- [Claude Code](https://claude.ai/code)

---

## 1. Start the backend

```bash
git clone https://github.com/your-org/lore
cd lore
docker compose up -d
```

This starts the selfhosted backend (FastAPI + SQLite + Qdrant) on port 8765. On first start, the entrypoint downloads the embedding model (~90 MB) into a named Docker volume (`lore-model-cache`). Subsequent starts are fully offline.

Verify:
```bash
curl http://localhost:8765/v1/health
# {"status":"ok","qdrant":true,"db":true}
```

---

## 2. Seed the concept graph

```bash
docker exec agentlore-lore-selfhosted-1 python -m lore.seed.concepts
# [lore.seed] Done. concepts=6, links=5, indexed=6
```

This loads the REST CLI blueprint — six concepts (an anchor project plus five linked concepts covering tool setup, command hierarchy, testing strategy, pagination, and auth). It validates the full retrieval path and gives you something to search against immediately.

---

## 3. Register the MCP server in Claude Code

Add the Lore MCP server to your Claude Code configuration:

```bash
claude mcp add lore \
  -e LORE_BACKEND=selfhosted \
  -e LORE_SELFHOSTED_URL=http://localhost:8765 \
  -e PYTHONPATH="$(pwd)" \
  -- "$(pwd)/.venv/bin/python" -m lore.mcp.server
```

Or add it manually to `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "lore": {
      "command": "/path/to/lore/.venv/bin/python",
      "args": ["-m", "lore.mcp.server"],
      "env": {
        "LORE_BACKEND": "selfhosted",
        "LORE_SELFHOSTED_URL": "http://localhost:8765",
        "PYTHONPATH": "/path/to/lore"
      }
    }
  }
}
```

> **Note:** `PYTHONPATH` is required because another package named `lore` exists on PyPI (Instacart's data science framework). Without it, Claude Code spawns the MCP subprocess from a different working directory and imports the wrong package.

---

## 4. Install the Lore plugin

Lore is a Claude Code plugin. Installing it makes `/search-concepts`, `/capture-concept`, and the Stop hook available across **all** your Claude Code projects.

```bash
# Add the Lore repo as a marketplace
claude plugins marketplace add /path/to/cloned/lore

# Install the plugin
claude plugins install lore
```

Restart Claude Code to activate.

---

## 5. Use it

### Search before you build

In any Claude Code session, invoke:

```
/search-concepts
```

Claude will ask what problem you're solving, call the `search_concepts` MCP tool, and return the most relevant concepts with their full linked graph. Concept IDs are appended to `~/.lore/session.json` for end-of-session rating.

### Capture what you discover

When Claude solves something non-obvious — a workaround, a pattern derived from failure, a gotcha — invoke:

```
/capture-concept
```

Claude applies a reflection gate (is this generalizable? would it save another agent time?), strips session-specific details, and submits it to the graph. In `confirm` mode (default) it shows you the concept first and waits for approval.

### Rate at session end

The Stop hook fires automatically when the session closes. It reads `~/.lore/session.json`, lists the concepts you used, and asks Claude to rate each one (`outcome` 1–5, `hours_saved`) and reflect on anything worth capturing.

**Prerequisite for automatic rating:** Claude Code must be allowed to call `mcp__lore__rate_concept` without prompting, otherwise the Stop hook output is injected but the tool call blocks waiting for approval. Add this to your project or global `settings.json`:

```json
{
  "permissions": {
    "allow": ["mcp__lore__rate_concept"]
  }
}
```

If you prefer not to grant this permission, skip the allowlist entry and invoke `/capture-concept` manually at the end of each session instead — similar to how `/wrapup` works in brain-tools.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `LORE_BACKEND` | `selfhosted` | Backend selector. Only `selfhosted` is implemented in Phase 1. |
| `LORE_SELFHOSTED_URL` | `http://localhost:8765` | Selfhosted backend URL |
| `LORE_CAPTURE_MODE` | `confirm` | `confirm` — shows concept and waits for approval before submitting. `auto` — submits directly without user confirmation. |
| `LORE_BLOCK_PATTERNS` | _(empty)_ | Semicolon-separated regex patterns blocked at submit time. Use for team-specific sensitive strings: `LORE_BLOCK_PATTERNS=corp\.internal;secret-project` |

---

## MCP tools

These are available to Claude whenever the Lore MCP server is registered:

| Tool | What it does |
|---|---|
| `search_concepts` | Semantic search by problem description. Returns matched concepts with full linked graph. |
| `get_concept` | Retrieve a specific concept by ID with all links (both directions). |
| `submit_concept` | Add a new concept. Mandatory content scan runs before write — rejects credentials, internal URLs, and `LORE_BLOCK_PATTERNS`. |
| `link_concepts` | Add a directed link between two existing concepts. |
| `rate_concept` | Record outcome (1–5) and hours saved for a concept. Updates rolling averages. |

---

## Project layout

```
lore/
├── mcp/server.py          # FastMCP server — MCP tool definitions
├── core/scanner.py        # Content scanner (called by submit_concept)
├── selfhosted/            # FastAPI service + SQLite + Qdrant
│   ├── api.py             # HTTP endpoints (/v1/*)
│   ├── db.py              # SQLite CRUD
│   ├── indexer.py         # Embedding + vector upsert
│   ├── vector_store.py    # Qdrant operations
│   └── Dockerfile         # Single-container image (~8.7 GB); model cached in lore-model-cache volume
├── seed/concepts.py       # REST CLI blueprint — 6 concepts, 5 links
└── tests/                 # 177 tests, 98% coverage
skills/
├── search-concepts/SKILL.md    # /search-concepts skill
├── capture-concept/SKILL.md    # /capture-concept skill
└── wrapup/SKILL.md             # /wrapup skill
.claude/
├── hooks/lore-stop.sh          # Stop hook
└── settings.json               # (empty — hook registered via hooks/hooks.json)
docker-compose.yml              # lore-selfhosted + qdrant
```

---

## Ports

| Service | Port |
|---|---|
| Lore selfhosted API | 8765 |
| Qdrant HTTP | 6333 |
| Qdrant gRPC | 6334 |

---

## Verify everything works

```bash
# Search
curl -s -X POST http://localhost:8765/v1/concepts/search \
  -H "Content-Type: application/json" \
  -d '{"problem": "building a typed CLI client for a REST API", "limit": 3}' \
  | python3 -m json.tool | grep '"name"'
```

You should see the REST CLI blueprint concepts with their linked graph.

---

## Full spec

See [`PROJECT.md`](PROJECT.md) for the full product specification, development phases, and MCP tool schemas.
