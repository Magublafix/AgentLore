"""Lore seed data package.

Exposes :func:`~lore.seed.concepts.seed` for loading the initial REST CLI
blueprint knowledge graph into SQLite and Qdrant.
"""

from lore.seed.concepts import seed

__all__ = ["seed"]
