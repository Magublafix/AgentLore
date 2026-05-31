# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Lore self-hosted backend image
# ---------------------------------------------------------------------------
# Multi-stage build keeps the final layer lean:
#   builder  — installs dependencies into a venv, then pre-downloads the
#              sentence-transformers model so the runtime image needs no
#              network access at startup.
#   runtime  — copies the venv + cached model; nothing else.
#
# The model (~90 MB weights, all-MiniLM-L6-v2) is stored at /app/.cache so that:
#   - The cache lives in a path we own (not /root/.cache).
#   - The non-root `lore` user can read it at runtime without chmod hacks.
# TRANSFORMERS_OFFLINE=1 + HF_DATASETS_OFFLINE=1 are set in the runtime ENV so
# that huggingface_hub does not attempt any HEAD requests before loading the
# locally cached model (newer huggingface_hub versions do this by default).
# ---------------------------------------------------------------------------

# Pin the patch version for reproducible builds.
FROM python:3.11-slim AS builder

# Silence pip warnings and bytecode noise during the build step.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Redirect the HuggingFace / Transformers cache to a predictable location
    # inside the image so we control ownership and path.
    HF_HOME=/app/.cache \
    TRANSFORMERS_CACHE=/app/.cache

WORKDIR /app

# Install build tools needed by some C-extension wheels (e.g. tokenizers).
# --no-install-recommends keeps the layer thin.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy only the files pip needs — avoids cache-busting on source changes.
COPY pyproject.toml ./

# Create a placeholder package directory so `pip install .` (which reads
# pyproject.toml) can resolve the project without the full source tree.
# We copy the real source in the next step.
RUN mkdir -p lore

# Install runtime dependencies only (no [dev] extras).
RUN pip install --no-cache-dir .

# Now copy the actual source so the installed package is complete.
# (We installed first so this layer is only invalidated by source changes,
# not by dep changes — keeps the dependency layer cached across code edits.)
COPY lore/ lore/

# Reinstall in-place so the package metadata points at the copied source.
RUN pip install --no-cache-dir --no-deps .

# Pre-download the embedding model into the cache directory.
# This bakes the model (~90 MB) into the image so the container can serve
# embed requests immediately without network access at runtime.
RUN mkdir -p /app/.cache && \
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# ---------------------------------------------------------------------------
# Runtime stage — minimal, non-root
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/.cache \
    TRANSFORMERS_CACHE=/app/.cache \
    # Force HuggingFace / sentence-transformers into fully offline mode.
    # Without these, newer versions of huggingface_hub attempt a HEAD request
    # to check for model updates even when the weights are already cached.
    TRANSFORMERS_OFFLINE=1 \
    HF_DATASETS_OFFLINE=1 \
    # Default DB path; override at container runtime via -e LORE_DB_PATH=...
    LORE_DB_PATH=/data/lore.db

# Create a non-root user (uid 1000) before copying files so chown is cheap.
RUN groupadd --gid 1000 lore && \
    useradd --uid 1000 --gid 1000 --no-create-home --shell /bin/false lore

WORKDIR /app

# Copy the installed packages and cached model from the builder stage.
COPY --from=builder --chown=lore:lore /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder --chown=lore:lore /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY --from=builder --chown=lore:lore /app/.cache /app/.cache
COPY --from=builder --chown=lore:lore /app/lore /app/lore

# /data is where the SQLite database lives at runtime (mounted as a volume).
RUN mkdir -p /data && chown lore:lore /data

USER lore

EXPOSE 8765

# Liveness/readiness probe: the /v1/health endpoint is always available
# even when Qdrant is unreachable.
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/v1/health')" || exit 1

# Use exec form so signals (SIGTERM) reach uvicorn directly — clean shutdown.
ENTRYPOINT ["uvicorn", "lore.selfhosted.api:app", "--host", "0.0.0.0", "--port", "8765"]
