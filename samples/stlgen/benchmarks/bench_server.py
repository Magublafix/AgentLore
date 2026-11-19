"""Benchmark-only launcher for the private Lore server (SQLite + local on-disk Qdrant).

The selfhosted ``sqlite_qdrant`` backend normally needs a separate Qdrant service.  This launcher
swaps its client for qdrant-client's embedded local mode (``QdrantClient(path=...)``) so the
benchmark can run without Docker.  Production code is untouched; the gists backend is not involved.

Environment: ``LORE_BENCH_QDRANT_PATH`` (required), ``LORE_DB_PATH``, ``LORE_ADMIN_TOKEN``,
``BENCH_SERVER_PORT`` (default 8765).  Single process only (local Qdrant locks its directory).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repo root, for ``import lore``


def patch_qdrant(path: str) -> None:
    """Make SqliteQdrantBackend use an embedded on-disk Qdrant at ``path``.

    The admin reset deletes the collection and relies on a Qdrant *service* tolerating queries
    against the missing collection until the next index.  The embedded client raises
    ``ValueError`` instead (HTTP 500 on the next submit), so the collection is re-created
    straight after every delete.
    """
    from qdrant_client import QdrantClient

    import lore.server.storage.sqlite_qdrant as sq
    from lore.selfhosted.vector_store import init_qdrant_collection

    os.makedirs(path, exist_ok=True)

    class _EmbeddedClient(QdrantClient):
        def delete_collection(self, collection_name, *args, **kwargs):
            result = super().delete_collection(collection_name, *args, **kwargs)
            init_qdrant_collection(self, collection_name=collection_name)
            return result

    sq.QdrantClient = lambda *a, **k: _EmbeddedClient(path=path)  # type: ignore[assignment]


def main() -> None:
    path = os.environ.get("LORE_BENCH_QDRANT_PATH")
    if not path:
        sys.exit("LORE_BENCH_QDRANT_PATH is required")
    patch_qdrant(path)
    import uvicorn

    from lore.server.api import app

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("BENCH_SERVER_PORT", "8765")),
                log_level="info")


if __name__ == "__main__":
    main()
