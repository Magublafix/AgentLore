# ---------------------------------------------------------------------------
# Lore semantic server image (LORE-030)
# ---------------------------------------------------------------------------
# Multi-stage build:
#   builder  — installs Python dependencies.
#   runtime  — copies the installed packages and source; nothing else.
#
# The embedding model (all-MiniLM-L6-v2, ~90 MB) is NOT baked into the image.
# It is downloaded on first container start and cached in the
# lore-model-cache Docker volume.  Subsequent starts skip the download.
# ---------------------------------------------------------------------------

FROM python:3.14-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install build tools needed by some C-extension wheels (e.g. tokenizers).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy only the files pip needs to resolve the project.
COPY pyproject.toml ./

# Create placeholder package directory so pip can parse pyproject.toml.
RUN mkdir -p lore

# Install runtime dependencies only (no [dev] extras).
RUN pip install --no-cache-dir .

# Copy the actual source after deps are installed to keep the dep layer cached.
COPY lore/ lore/

# Reinstall in-place so package metadata points at the copied source.
RUN pip install --no-cache-dir --no-deps .

# ---------------------------------------------------------------------------
# Runtime stage — minimal, non-root
# ---------------------------------------------------------------------------
FROM python:3.14-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/.cache \
    TRANSFORMERS_CACHE=/app/.cache \
    LORE_STORAGE_BACKEND=gist_qdrant

# Create a non-root user before copying files so chown is cheap.
RUN groupadd --gid 1000 lore && \
    useradd --uid 1000 --gid 1000 --no-create-home --shell /bin/false lore

WORKDIR /app

# Copy installed packages and source from the builder stage.
COPY --from=builder --chown=lore:lore /usr/local/lib /usr/local/lib
COPY --from=builder --chown=lore:lore /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY --from=builder --chown=lore:lore /app/lore /app/lore

# /app/.cache — HuggingFace model cache (mounted as a volume).
RUN mkdir -p /app/.cache && chown lore:lore /app/.cache

# Entrypoint downloads the model on first start, then launches uvicorn.
COPY --chown=lore:lore lore/semantic_server/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

USER lore

EXPOSE 8766

HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8766/health')" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
