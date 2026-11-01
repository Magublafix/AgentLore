"""Compatibility-aware annotation and ordering of search results (LORE-048).

Single shared home for how ``search_concepts`` results are labelled and ordered
by environment compatibility.  Every backend (selfhosted via the unified
server, gist_qdrant, gists, bundled seeds) calls :func:`rank_by_compatibility`;
no backend orders by compatibility on its own.

Contract:
    * Every result gets ``compatibility_check = {"status", "reason"}`` where
      status is ``compatible`` | ``incompatible`` | ``unknown`` (computed by
      :func:`lore.core.environment.check_compatibility`).  Linked concepts in a
      result's ``links`` list get the same field (``unknown`` when the link
      carries no compatibility metadata or is unavailable).
    * Order is by band: compatible, then unknown, then incompatible.  Within a
      band the incoming order is preserved (stable) -- that incoming order is
      the backend's existing relevance/rating order, so rating only orders
      results inside a band and can never lift an incompatible result.
    * ``include_incompatible=False`` drops incompatible results instead of
      placing them last.
    * Missing information is never read as compatibility: an empty/unknown
      environment yields ``unknown`` for every result and leaves order unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, Optional

from lore.core.environment import (
    COMPATIBLE,
    INCOMPATIBLE,
    UNKNOWN,
    Environment,
    check_compatibility,
    default_detectors,
    detect_environment,
    normalize_language,
    normalize_library_name,
    normalize_platform,
)

#: Candidates fetched per requested result when an environment is known, so
#: compatible results ranked below the raw top-``limit`` can still surface.
OVERFETCH_FACTOR = 4

#: Set to ``0``/``false`` to disable implicit cwd detection in the MCP process.
AUTODETECT_ENV_VAR = "LORE_COMPAT_AUTODETECT"

_BAND = {COMPATIBLE: 0, UNKNOWN: 1, INCOMPATIBLE: 2}


def coerce_environment(value: Any) -> Optional[Environment]:
    """Build an :class:`Environment` from ``None``, an Environment, or a plain dict.

    Dict keys: ``language``, ``runtime_version``, ``libraries`` (``{name: version}``),
    ``platform``.  All optional; names are normalized like detected ones.

    Raises:
        ValueError: If ``value`` is not a dict/Environment/None or a field has the wrong type.
    """
    if value is None or isinstance(value, Environment):
        return value
    if not isinstance(value, dict):
        raise ValueError("environment must be an object with language, runtime_version, libraries, platform")
    unknown_keys = set(value) - {"language", "runtime_version", "libraries", "platform"}
    if unknown_keys:
        raise ValueError(f"environment has unknown field(s): {', '.join(sorted(map(str, unknown_keys)))}")
    for key in ("language", "runtime_version", "platform"):
        if value.get(key) is not None and not isinstance(value[key], str):
            raise ValueError(f"environment.{key} must be a string")
    libs = value.get("libraries") or {}
    if not isinstance(libs, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in libs.items()):
        raise ValueError("environment.libraries must be an object mapping library name to version string")
    language = normalize_language(value.get("language"))
    return Environment(
        language=language,
        runtime_version=value.get("runtime_version") or None,
        libraries={normalize_library_name(k, language): v for k, v in libs.items()},
        platform=normalize_platform(value.get("platform")),
        sources=("request",),
    )


def has_environment_info(env: Optional[Environment]) -> bool:
    """True if ``env`` knows anything that could verify a constraint."""
    return bool(env and (env.language or env.runtime_version or env.libraries or env.platform))


def environment_to_dict(env: Environment) -> dict:
    """JSON-safe dict form accepted back by :func:`coerce_environment`."""
    return {
        "language": env.language,
        "runtime_version": env.runtime_version,
        "libraries": dict(env.libraries),
        "platform": env.platform,
    }


def resolve_environment(environment: Any = None, project_dir: str | Path | None = None) -> Environment:
    """Pick the target environment for a search (client side, i.e. the MCP process).

    Precedence:
        1. ``environment`` (explicit dict) -- used as given, no detection.
        2. ``project_dir`` -- :func:`detect_environment` on that directory
           (manifests/lockfiles, falling back to the running interpreter).
        3. Neither: detect from the current working directory using manifests
           and lockfiles only (a few file reads; nothing is executed or
           installed, no network).  The running interpreter is deliberately NOT
           used here because under ``uvx`` it is Lore's own, not the project's.
           Disable with ``LORE_COMPAT_AUTODETECT=0``.

    Detection failures yield an empty environment (all results ``unknown``).
    """
    env = coerce_environment(environment)
    if env is not None:
        return env
    try:
        if project_dir is not None:
            return detect_environment(project_dir)
        if os.environ.get(AUTODETECT_ENV_VAR, "1").strip().lower() in {"0", "false", "no", "off"}:
            return Environment()
        return detect_environment(Path.cwd(), default_detectors(include_interpreter=False))
    except Exception:  # noqa: BLE001 - never let detection break search
        return Environment()


def candidate_limit(limit: int, env: Optional[Environment]) -> int:
    """How many candidates to fetch before ranking and truncating to ``limit``."""
    return limit * OVERFETCH_FACTOR if has_environment_info(env) and limit > 0 else limit


def _check(compat: Any, env: Environment) -> dict:
    result = check_compatibility(compat, env)
    return {"status": result.status, "reason": result.reason}


def annotate_compatibility(concept: dict, env: Optional[Environment]) -> dict:
    """Set ``compatibility_check`` on ``concept`` and on each of its ``links`` (in place)."""
    env = env if env is not None else Environment()
    concept["compatibility_check"] = _check(concept.get("compatibility"), env)
    for link in concept.get("links") or []:
        if isinstance(link, dict):
            link["compatibility_check"] = _check(link.get("compatibility"), env)
    return concept


def rank_by_compatibility(
    results: Iterable[dict],
    env: Optional[Environment],
    limit: Optional[int] = None,
    include_incompatible: bool = True,
) -> list[dict]:
    """Annotate results and order them compatible > unknown > incompatible.

    Pure apart from adding ``compatibility_check`` to the (shallow-mutated)
    result dicts.  The sort is stable, so the incoming order (rating/relevance)
    is kept inside each band and cannot promote across bands.

    Args:
        results: Result dicts in the backend's native order.
        env: Target environment; ``None``/empty makes every result ``unknown``.
        limit: Truncate to this many results *after* ranking (``None`` = all).
        include_incompatible: ``False`` drops incompatible results.
    """
    annotated = [annotate_compatibility(r, env) for r in results]
    if not include_incompatible:
        annotated = [r for r in annotated if r["compatibility_check"]["status"] != INCOMPATIBLE]
    annotated.sort(key=lambda r: _BAND.get(r["compatibility_check"]["status"], 1))
    return annotated if limit is None else annotated[: max(limit, 0)]


def needs_annotation(results: Iterable[dict]) -> bool:
    """True if any result lacks ``compatibility_check`` (e.g. an older server)."""
    return any(isinstance(r, dict) and "compatibility_check" not in r for r in results)
