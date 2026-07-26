# ---------------------------------------------------------------------------
# Lore MCP server — thin image
# ---------------------------------------------------------------------------
# This image packages the mcp-server-lore CLI for use in MCP-compatible
# runtimes (Claude Code, Cursor, Windsurf, Cline, etc.).
#
# It is intentionally lightweight: no sentence-transformers, no Qdrant,
# no model cache. The default backend is GitHub Gists — no local
# infrastructure required.
#
# To point at a self-hosted backend instead:
#   docker run -e LORE_BACKEND=selfhosted \
#              -e LORE_SELFHOSTED_URL=http://your-server:8765 \
#              <image>
#
# For the heavy self-hosted backend image (with embeddings + Qdrant),
# see lore/selfhosted/Dockerfile.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Stage 1 — builder
# Installs all Python dependencies into the system site-packages.
# Kept separate so the runtime stage can copy only the installed packages
# and not the build tools (pip, wheel, setuptools internals).
# ---------------------------------------------------------------------------
FROM python:3.14-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copy only the files pip needs to resolve dependencies.
# Avoids cache-busting the install layer on source-only changes.
COPY pyproject.toml ./

# Create the package skeleton so hatchling can read the project metadata
# without the full source tree present during the dep-install step.
RUN mkdir -p lore

# Install runtime dependencies (no [dev] extras — tests don't run in prod).
# --no-cache-dir keeps the layer thin.
RUN pip install --no-cache-dir .

# Copy the actual source now.  Placing this after the install means the
# expensive dep-download layer stays cached across code-only changes.
COPY lore/ lore/

# Reinstall in-place (no-deps: deps are already installed above) so the
# package metadata correctly references the copied source files.
RUN pip install --no-cache-dir --no-deps .

# ---------------------------------------------------------------------------
# Stage 2 — runtime
# Minimal image: just Python, the installed packages, and a non-root user.
# ---------------------------------------------------------------------------
FROM python:3.14-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Default to the GitHub Gists backend — no local infrastructure needed.
    # Requires LORE_GITHUB_TOKEN to be set at runtime.
    LORE_BACKEND=gists

# Create a non-root user before copying files so the chown in COPY is cheap
# (a single metadata update rather than a recursive permission walk).
RUN groupadd --gid 1000 lore && \
    useradd --uid 1000 --gid 1000 --no-create-home --shell /bin/false lore

WORKDIR /app

# Copy the installed packages and the mcp-server-lore entry point script
# from the builder stage.  We copy all of /usr/local/lib to pick up the
# installed package regardless of the exact Python minor-version path.
COPY --from=builder --chown=lore:lore /usr/local/lib /usr/local/lib
COPY --from=builder --chown=lore:lore /usr/local/bin/mcp-server-lore /usr/local/bin/mcp-server-lore
COPY --from=builder --chown=lore:lore /app/lore /app/lore

USER lore

# mcp-server-lore communicates over stdio (MCP transport).
# No ports are exposed — the host runtime connects via stdin/stdout.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import lore.mcp.server" || exit 1

ENTRYPOINT ["mcp-server-lore"]
