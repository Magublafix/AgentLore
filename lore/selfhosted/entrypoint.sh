#!/bin/sh
set -e

MODEL_SENTINEL="/app/.cache/hub/models--sentence-transformers--all-MiniLM-L6-v2"

if [ ! -d "$MODEL_SENTINEL" ]; then
    echo "[startup] Embedding model not found in cache — downloading all-MiniLM-L6-v2..."
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
    echo "[startup] Model cached — switching to offline mode."
fi

export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1

exec uvicorn lore.selfhosted.api:app --host 0.0.0.0 --port 8765
