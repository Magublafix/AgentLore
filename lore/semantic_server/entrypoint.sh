#!/bin/bash
# ---------------------------------------------------------------------------
# Semantic server entrypoint — downloads model on first start, then starts
# uvicorn.  Mirrors the pattern from lore/selfhosted/entrypoint.sh.
# ---------------------------------------------------------------------------

set -euo pipefail

MODEL_CACHE_SENTINEL="${HF_HOME:-/app/.cache}/models--sentence-transformers--all-MiniLM-L6-v2"

if [ -d "$MODEL_CACHE_SENTINEL" ]; then
    echo "[lore-semantic] Model cache found — starting in offline mode."
    export TRANSFORMERS_OFFLINE=1
else
    echo "[lore-semantic] Downloading all-MiniLM-L6-v2 model (first start)…"
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
    echo "[lore-semantic] Model download complete."
    export TRANSFORMERS_OFFLINE=1
fi

exec uvicorn lore.server.api:app \
    --host 0.0.0.0 \
    --port 8766 \
    --workers 1
