# ---------------------------------------------------------------------------
# Lore self-hosted backend image
# ---------------------------------------------------------------------------
# Multi-stage build:
#   builder  — installs Python dependencies.
#   runtime  — copies the installed packages and source; nothing else.
#
# The embedding model (all-MiniLM-L6-v2, ~90 MB) is NOT baked into the image.
# entrypoint.sh downloads it on first container start and caches it in the
# lore-model-cache Docker volume.  Subsequent starts skip the download and
# switch to TRANSFORMERS_OFFLINE=1 automatically.
# ---------------------------------------------------------------------------

FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

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

# ---------------------------------------------------------------------------
# Runtime stage — minimal, non-root
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# HF cache path is fixed so the entrypoint sentinel check is reliable.
# TRANSFORMERS_OFFLINE is NOT set here — entrypoint.sh sets it after the
# model is confirmed present, allowing first-start download to succeed.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/.cache \
    TRANSFORMERS_CACHE=/app/.cache \
    LORE_DB_PATH=/data/lore.db

# Create a non-root user (uid 1000) before copying files so chown is cheap.
RUN groupadd --gid 1000 lore && \
    useradd --uid 1000 --gid 1000 --no-create-home --shell /bin/false lore

WORKDIR /app

# Copy installed packages and source from the builder stage.
COPY --from=builder --chown=lore:lore /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder --chown=lore:lore /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY --from=builder --chown=lore:lore /app/lore /app/lore

# Entrypoint script — downloads model on first start, then execs uvicorn.
COPY --chown=lore:lore lore/selfhosted/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# /data — SQLite database (mounted as a volume).
# /app/.cache — HuggingFace model cache (mounted as a volume).
RUN mkdir -p /data /app/.cache && chown lore:lore /data /app/.cache

USER lore

EXPOSE 8765

# start_period=60s allows time for first-run model download (~90 MB).
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/v1/health')" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
