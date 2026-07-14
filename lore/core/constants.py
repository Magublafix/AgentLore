"""Shared constants and helpers used across multiple Lore modules."""

from __future__ import annotations

VALID_LINK_RELS: frozenset[str] = frozenset(
    {"uses", "tested_by", "extends", "alternative_to", "requires"}
)
VALID_CONCEPT_TYPES: frozenset[str] = frozenset(
    {"project", "pattern", "tool", "testing", "architecture"}
)


def _parse_name_from_description(description: str) -> str:
    """Parse a lore-concept gist description: '[lore-concept] Name [tag1,tag2]'.

    Input format: ``"[lore-concept] My Pattern [tag1, tag2]"``
    Output: ``"My Pattern"``

    Strips the leading ``"[lore-concept] "`` prefix, then strips the trailing
    ``" [...]"`` suffix (everything from the last ``" ["`` onwards).  If
    parsing fails for any reason the full description is returned as a fallback.

    Args:
        description: The raw gist description string.

    Returns:
        The extracted concept name, or the full description if parsing fails.
    """
    try:
        prefix = "[lore-concept] "
        if not description.startswith(prefix):
            return description
        remainder = description[len(prefix):]
        # Strip trailing " [...]" tag section if present.
        last_bracket = remainder.rfind(" [")
        if last_bracket != -1:
            remainder = remainder[:last_bracket]
        return remainder
    except Exception:  # noqa: BLE001
        return description


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


#: Cosine-similarity threshold above which two concepts are considered
#: near-duplicates.  Can be overridden at request time via the
#: ``LORE_DEDUP_THRESHOLD`` environment variable.
LORE_DEDUP_THRESHOLD: float = 0.92
