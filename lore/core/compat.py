"""Reproducer and compatibility metadata for Lore concepts (LORE-046).

This is the single shared home for the metadata model, validation, and
(de)serialization used by every backend (gists, selfhosted SQLite, the unified
server, and the semantic index payload).  LORE-047 (environment checker) should
import from here rather than re-parsing raw dicts.

Canonical shapes (always plain JSON-safe dicts):

Reproducer::

    {"status": "provided", "text": "<minimal reproducer>"}
    {"status": "none_available", "text": None}   # author says none exists
    {"status": "unknown", "text": None}          # nothing was supplied

Compatibility::

    {
        "status": "unknown" | "partial" | "declared",
        "language": "python" | None,           # lower-cased runtime/language name
        "runtime_version": ">=3.11,<4" | None, # canonical PEP 440 specifier
        "libraries": [{"name": "fastapi", "specifier": ">=0.110"}],  # specifier "" = any
        "platforms": ["linux", "macos"],       # lower-cased OS/platform names
        "assumptions": ["free text", ...],
    }

Semantics:
    * ``unknown`` means *nothing* was declared.  ``partial`` means some, but
      not all, of language / runtime_version / platforms were declared.
      ``declared`` means all three were.  No status ever means "supported":
      absence of metadata is never read as compatibility.
    * Legacy concepts (stored before this schema) and malformed stored data
      load as the unknown values via :func:`load_reproducer` /
      :func:`load_compatibility`, which never raise.
    * Submitted data goes through :func:`normalize_reproducer` /
      :func:`normalize_compatibility`, which raise :class:`MetadataValidationError`
      (a ``ValueError``) with a message naming the offending field.
    * Normalization is idempotent, so submit -> store -> get round-trips
      return identical metadata.
"""

from __future__ import annotations

import json
from typing import Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet

#: Marker accepted for ``reproducer`` meaning "the author states none exists".
NONE_AVAILABLE = "none_available"

REPRODUCER_PROVIDED = "provided"
REPRODUCER_UNKNOWN = "unknown"

COMPAT_UNKNOWN = "unknown"
COMPAT_PARTIAL = "partial"
COMPAT_DECLARED = "declared"

MAX_REPRODUCER_CHARS = 20_000
MAX_LIBRARIES = 50
MAX_PLATFORMS = 20
MAX_ASSUMPTIONS = 20
MAX_ASSUMPTION_CHARS = 500
MAX_NAME_CHARS = 100

_COMPAT_KEYS = frozenset(
    {"language", "runtime_version", "libraries", "platforms", "assumptions", "status"}
)


class MetadataValidationError(ValueError):
    """Raised when submitted reproducer/compatibility metadata is invalid."""


# ---------------------------------------------------------------------------
# Unknown values
# ---------------------------------------------------------------------------


def unknown_reproducer() -> dict:
    """Return the canonical ``unknown`` reproducer value (a fresh dict)."""
    return {"status": REPRODUCER_UNKNOWN, "text": None}


def unknown_compatibility() -> dict:
    """Return the canonical ``unknown`` compatibility value (a fresh dict)."""
    return {
        "status": COMPAT_UNKNOWN,
        "language": None,
        "runtime_version": None,
        "libraries": [],
        "platforms": [],
        "assumptions": [],
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_specifier(value: Any, field_name: str = "specifier") -> str:
    """Validate a PEP 440 version specifier and return its canonical string.

    Args:
        value: Specifier text such as ``">=1.2,<2"``.  Empty/blank means "any
            version" and returns ``""``.
        field_name: Name used in the error message.

    Returns:
        ``str(SpecifierSet(value))`` (clauses sorted and stripped), so the
        result is stable under repeated normalization.

    Raises:
        MetadataValidationError: If ``value`` is not a string or not a valid
            specifier set.
    """
    if not isinstance(value, str):
        raise MetadataValidationError(
            f"{field_name}: version specifier must be a string, got {type(value).__name__}"
        )
    text = value.strip()
    if not text:
        return ""
    try:
        return str(SpecifierSet(text))
    except InvalidSpecifier as exc:
        raise MetadataValidationError(
            f"{field_name}: invalid version specifier {value!r} "
            f"(expected PEP 440 syntax such as '>=1.2,<2'): {exc}"
        ) from exc


def _clean_str(value: Any, field_name: str, max_chars: int) -> str:
    if not isinstance(value, str):
        raise MetadataValidationError(
            f"{field_name}: must be a string, got {type(value).__name__}"
        )
    text = value.strip()
    if len(text) > max_chars:
        raise MetadataValidationError(f"{field_name}: exceeds {max_chars} characters")
    return text


def _str_list(value: Any, field_name: str, max_items: int, max_chars: int, lower: bool) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise MetadataValidationError(f"{field_name}: must be a string or list of strings")
    if len(value) > max_items:
        raise MetadataValidationError(f"{field_name}: at most {max_items} entries allowed")
    out: list[str] = []
    for i, item in enumerate(value):
        text = _clean_str(item, f"{field_name}[{i}]", max_chars)
        if not text:
            continue
        if lower:
            text = text.lower()
        if text not in out:
            out.append(text)
    return out


def normalize_reproducer(value: Any) -> dict:
    """Validate submitted reproducer input and return the canonical dict.

    Args:
        value: ``None``/blank (-> unknown), the string ``"none_available"``
            (-> explicit marker), any other string (reproducer text), or an
            already-canonical dict (idempotence for round-trips).

    Raises:
        MetadataValidationError: If the type is wrong or the text is too long.
    """
    if isinstance(value, dict):
        status = value.get("status")
        if status == "none_available":
            return {"status": NONE_AVAILABLE, "text": None}
        if status == REPRODUCER_PROVIDED:
            value = value.get("text")
        elif status in (None, REPRODUCER_UNKNOWN) and not value.get("text"):
            return unknown_reproducer()
        else:
            raise MetadataValidationError(
                f"reproducer: invalid status {status!r}; expected "
                "'provided', 'none_available' or 'unknown'"
            )
    if value is None:
        return unknown_reproducer()
    text = _clean_str(value, "reproducer", MAX_REPRODUCER_CHARS)
    if not text:
        return unknown_reproducer()
    if text == NONE_AVAILABLE:
        return {"status": NONE_AVAILABLE, "text": None}
    return {"status": REPRODUCER_PROVIDED, "text": text}


def _normalize_libraries(value: Any) -> list[dict]:
    if value is None:
        return []
    entries: list[tuple[Any, Any]]
    if isinstance(value, dict):
        entries = list(value.items())
    elif isinstance(value, (list, tuple)):
        entries = []
        for i, item in enumerate(value):
            if isinstance(item, str):
                entries.append((item, ""))
            elif isinstance(item, dict):
                unknown = set(item) - {"name", "specifier"}
                if unknown:
                    raise MetadataValidationError(
                        f"compatibility.libraries[{i}]: unknown keys {sorted(unknown)}"
                    )
                entries.append((item.get("name"), item.get("specifier") or ""))
            else:
                raise MetadataValidationError(
                    f"compatibility.libraries[{i}]: must be a {{name, specifier}} object"
                )
    else:
        raise MetadataValidationError(
            "compatibility.libraries: must be a list of {name, specifier} objects "
            "or a name->specifier mapping"
        )
    if len(entries) > MAX_LIBRARIES:
        raise MetadataValidationError(
            f"compatibility.libraries: at most {MAX_LIBRARIES} entries allowed"
        )
    out: list[dict] = []
    seen: dict[str, int] = {}
    for name, spec in entries:
        label = f"compatibility.libraries[{name!r}]"
        clean = _clean_str(name, label, MAX_NAME_CHARS) if name is not None else ""
        if not clean:
            raise MetadataValidationError("compatibility.libraries: library name is required")
        specifier = validate_specifier(spec if spec is not None else "", f"{label}.specifier")
        key = clean.lower()
        if key in seen:
            raise MetadataValidationError(
                f"compatibility.libraries: duplicate library {clean!r}"
            )
        seen[key] = len(out)
        out.append({"name": clean, "specifier": specifier})
    return out


def normalize_compatibility(value: Any) -> dict:
    """Validate submitted compatibility input and return the canonical dict.

    Accepted input keys: ``language`` (str), ``runtime_version`` (specifier
    str), ``libraries`` (list of ``{"name", "specifier"}`` or a
    ``{name: specifier}`` mapping), ``platforms`` (str or list of str),
    ``assumptions`` (str or list of str).  All keys are optional; ``status`` is
    always recomputed.  ``None`` or an empty dict yields unknown.

    Raises:
        MetadataValidationError: On wrong types, unknown keys, or an invalid
            version specifier (naming the offending field and value).
    """
    if value is None:
        return unknown_compatibility()
    if not isinstance(value, dict):
        raise MetadataValidationError("compatibility: must be an object")
    unexpected = set(value) - _COMPAT_KEYS
    if unexpected:
        raise MetadataValidationError(
            f"compatibility: unknown keys {sorted(unexpected)}; allowed: "
            f"{sorted(_COMPAT_KEYS - {'status'})}"
        )
    language_raw = value.get("language")
    language = (
        _clean_str(language_raw, "compatibility.language", MAX_NAME_CHARS).lower()
        if language_raw is not None
        else ""
    )
    runtime_raw = value.get("runtime_version")
    runtime = (
        validate_specifier(runtime_raw, "compatibility.runtime_version")
        if runtime_raw is not None
        else ""
    )
    result = {
        "status": COMPAT_UNKNOWN,
        "language": language or None,
        "runtime_version": runtime or None,
        "libraries": _normalize_libraries(value.get("libraries")),
        "platforms": _str_list(
            value.get("platforms"), "compatibility.platforms", MAX_PLATFORMS, MAX_NAME_CHARS, True
        ),
        "assumptions": _str_list(
            value.get("assumptions"),
            "compatibility.assumptions",
            MAX_ASSUMPTIONS,
            MAX_ASSUMPTION_CHARS,
            False,
        ),
    }
    result["status"] = _compat_status(result)
    return result


def _compat_status(c: dict) -> str:
    core = [c["language"], c["runtime_version"], c["platforms"]]
    any_set = any(core) or bool(c["libraries"]) or bool(c["assumptions"])
    if not any_set:
        return COMPAT_UNKNOWN
    return COMPAT_DECLARED if all(core) else COMPAT_PARTIAL


def normalize_concept_metadata(reproducer: Any, compatibility: Any) -> tuple[dict, dict]:
    """Validate both fields at once; returns ``(reproducer, compatibility)`` canonical dicts."""
    return normalize_reproducer(reproducer), normalize_compatibility(compatibility)


# ---------------------------------------------------------------------------
# Lenient loading of stored data
# ---------------------------------------------------------------------------


def _maybe_json(raw: Any) -> Any:
    if isinstance(raw, (str, bytes)):
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None
    return raw


def load_reproducer(raw: Any) -> dict:
    """Load a stored reproducer (dict, JSON string, or ``None``); never raises.

    Missing or malformed data returns the unknown value.
    """
    data = _maybe_json(raw)
    if not isinstance(data, dict):
        return unknown_reproducer()
    try:
        return normalize_reproducer(data)
    except MetadataValidationError:
        return unknown_reproducer()


def load_compatibility(raw: Any) -> dict:
    """Load stored compatibility (dict, JSON string, or ``None``); never raises.

    Missing or malformed data (including invalid specifiers) returns the
    unknown value rather than a partially trusted one.
    """
    data = _maybe_json(raw)
    if not isinstance(data, dict):
        return unknown_compatibility()
    try:
        return normalize_compatibility(data)
    except MetadataValidationError:
        return unknown_compatibility()


def dump_metadata(value: dict) -> str:
    """Serialize a canonical metadata dict to a stable JSON string (for SQLite)."""
    return json.dumps(value, sort_keys=True)
