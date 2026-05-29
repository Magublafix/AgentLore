"""Content scanner stub for LORE-003.

The full scanner (credential patterns, internal URLs, LORE_BLOCK_PATTERNS) is
delivered by LORE-005.  This stub always returns an empty match list so that
the FastAPI submit endpoint can call it unconditionally without blocking Phase 1
submissions.

Once LORE-005 replaces this file with the real implementation, no changes are
needed in ``api.py`` — the call site is identical.
"""

from __future__ import annotations


def scan_content(fields: dict[str, str]) -> list[dict]:
    """Scan concept fields for blocked patterns.

    Args:
        fields: Mapping of field name to field value (e.g. ``{"content": "...",
            "when_to_use": "..."}``) to scan.

    Returns:
        A list of match dicts.  Each entry has at minimum ``{"field": str,
        "pattern": str, "match": str}``.  An empty list means the content is
        clean.  This stub always returns ``[]``.
    """
    return []
