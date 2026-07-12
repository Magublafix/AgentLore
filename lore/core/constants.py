"""Shared constants and helpers used across multiple Lore modules."""

from __future__ import annotations

VALID_LINK_RELS: frozenset[str] = frozenset(
    {"uses", "tested_by", "extends", "alternative_to", "requires"}
)
VALID_CONCEPT_TYPES: frozenset[str] = frozenset(
    {"project", "pattern", "tool", "testing", "architecture"}
)


def embedding_text(when_to_use: str, name: str) -> str:
    """Return the canonical embedding input string for a concept.

    All backends must use this function to ensure vectors are in the same
    embedding space.  The canonical form is ``when_to_use + " " + name``.

    Args:
        when_to_use: The concept's when_to_use field.
        name: The concept's name field.

    Returns:
        A single string ready to pass to the embedding model.
    """
    return (when_to_use or "") + " " + (name or "")
