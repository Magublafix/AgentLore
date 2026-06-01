"""Content scanner for the Lore MCP server (LORE-005).

Scans concept fields for credentials, internal URLs, and custom blocklist
patterns before any write to the knowledge graph.  This module is the
authoritative scanner implementation — the stub in LORE-003 is replaced here.

Environment variables
---------------------
LORE_BLOCK_PATTERNS
    Semicolon-separated list of additional regex patterns to block.  Evaluated
    at import time so the list is compiled once per process.  Example::

        LORE_BLOCK_PATTERNS=company\\.internal;secret-project

Pattern catalogue
-----------------
1. **Credential patterns** — API keys, tokens, bearer strings, secrets.
2. **Long hex / base64 strings** — raw secrets without a label.
3. **Internal URL patterns** — ``localhost`` (non-example), ``.internal``,
   ``.corp``, ``.local`` TLD suffixes.
4. **Custom blocklist** — compiled from ``LORE_BLOCK_PATTERNS`` at startup.
"""

from __future__ import annotations

import os
import re
from typing import Any

# ---------------------------------------------------------------------------
# Built-in pattern definitions
# ---------------------------------------------------------------------------

# Credential label + value.
# Handles two forms:
#   - key=value / key: value  (api_key, token, secret, bearer)
#   - "Bearer <token>" as used in Authorization headers (space separator)
_CREDENTIAL_LABEL_RE = re.compile(
    r"(?i)"
    r"(?:"
    r"(api[_\-]?key|token|secret)\s*[:=]\s*\S{8,}"  # key/token/secret + colon/equals
    r"|"
    r"bearer\s*[:=\s]\s*\S{8,}"                       # Bearer: / Bearer= / Bearer <value>
    r")"
)

# Long hex string (32+ chars) — raw secret without a label
_LONG_HEX_RE = re.compile(r"[A-Fa-f0-9]{32,}")

# Long base64-ish string (40+ chars) — could be a token or private key chunk
_LONG_B64_RE = re.compile(r"[A-Za-z0-9+/]{40,}=*")

# Internal URL patterns:
#   - bare "localhost" that is NOT inside an obvious example/placeholder string
#   - hostnames ending in .internal, .corp, or .local
_INTERNAL_HOST_RE = re.compile(
    r"(?i)"
    r"(?<!['\"])\blocalhost\b(?!['\"])"  # localhost not inside quotes
    r"|"
    r"\.(internal|corp|local)\b"
)


def _compile_block_patterns() -> list[re.Pattern[str]]:
    """Compile custom blocklist patterns from ``LORE_BLOCK_PATTERNS`` env var.

    Returns:
        A list of compiled :class:`re.Pattern` objects.  Invalid patterns are
        skipped with a warning printed to stderr so a misconfigured pattern
        does not crash the server at startup.
    """
    raw = os.environ.get("LORE_BLOCK_PATTERNS", "")
    patterns: list[re.Pattern[str]] = []
    for segment in raw.split(";"):
        segment = segment.strip()
        if not segment:
            continue
        try:
            patterns.append(re.compile(segment))
        except re.error as exc:
            import sys
            print(
                f"[lore.scanner] Ignoring invalid LORE_BLOCK_PATTERNS entry "
                f"'{segment}': {exc}",
                file=sys.stderr,
            )
    return patterns


# Compiled once at module load time.
_CUSTOM_BLOCK_PATTERNS: list[re.Pattern[str]] = _compile_block_patterns()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan_content(fields: dict[str, str | Any]) -> list[dict]:
    """Scan concept fields for blocked patterns.

    Checks each non-None field value against credential patterns, internal URL
    patterns, and the custom blocklist.  Stops at the first match per field to
    avoid flooding the caller with redundant violations — but continues
    checking other fields.

    Args:
        fields: Mapping of field name to field value.  Non-string values are
            converted via ``str()``.  ``None`` values are skipped.

    Returns:
        A list of violation dicts.  Each entry has::

            {
                "field":  str,   # e.g. "content"
                "reason": str,   # human-readable description
                "match":  str,   # the matched substring
            }

        An empty list means the content is clean.
    """
    violations: list[dict] = []

    for field_name, raw_value in fields.items():
        if raw_value is None:
            continue
        value = raw_value if isinstance(raw_value, str) else str(raw_value)

        violation = _check_field(field_name, value)
        if violation is not None:
            violations.append(violation)

    return violations


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _check_field(field_name: str, value: str) -> dict | None:
    """Run all pattern checks against a single field value.

    Returns the first violation found, or ``None`` if the field is clean.

    Args:
        field_name: The logical name of the field (e.g. ``"content"``).
        value: The string to scan.

    Returns:
        A violation dict or ``None``.
    """
    # 1. Credential label patterns
    m = _CREDENTIAL_LABEL_RE.search(value)
    if m:
        return {
            "field": field_name,
            "reason": "credential pattern detected (api key / token / secret)",
            "match": m.group(0)[:80],
        }

    # 2. Internal URL patterns
    m = _INTERNAL_HOST_RE.search(value)
    if m:
        return {
            "field": field_name,
            "reason": "internal URL pattern detected",
            "match": m.group(0)[:80],
        }

    # 3. Long hex strings (raw secrets)
    m = _LONG_HEX_RE.search(value)
    if m:
        return {
            "field": field_name,
            "reason": "long hexadecimal string detected (possible raw secret)",
            "match": m.group(0)[:80],
        }

    # 4. Long base64 strings (raw tokens / key material)
    m = _LONG_B64_RE.search(value)
    if m:
        return {
            "field": field_name,
            "reason": "long base64-encoded string detected (possible token or key material)",
            "match": m.group(0)[:80],
        }

    # 5. Custom blocklist patterns
    for pattern in _CUSTOM_BLOCK_PATTERNS:
        m = pattern.search(value)
        if m:
            return {
                "field": field_name,
                "reason": f"blocked by custom pattern '{pattern.pattern}'",
                "match": m.group(0)[:80],
            }

    return None


def reload_custom_patterns() -> None:
    """Re-read ``LORE_BLOCK_PATTERNS`` and recompile the custom blocklist.

    Call this in tests or after changing the environment variable mid-process.
    Under normal server operation the patterns are compiled once at startup.
    """
    global _CUSTOM_BLOCK_PATTERNS
    _CUSTOM_BLOCK_PATTERNS = _compile_block_patterns()
