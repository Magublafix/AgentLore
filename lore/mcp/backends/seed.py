"""Read-only demo backend over the bundled seed corpus (LORE-044).

Used when ``LORE_READ_ONLY=1``. Serves ``search_concepts`` / ``get_concept``
from the plain-dict definitions in :mod:`lore.seed.concepts` with simple
keyword scoring — no SQLite, Qdrant, sentence-transformers or FastAPI, so it
works in the base ``uvx mcp-server-lore`` install. Results carry
``source: "seed"`` and a ``label`` of "curated example"; IDs are
``seed:<slug>`` and can never collide with GitHub gist IDs (hex only).
"""

from __future__ import annotations

import os
import re
from typing import Optional

from lore.core.compat import unknown_compatibility, unknown_reproducer
from lore.core.environment import Environment
from lore.core.ranking import rank_by_compatibility
from lore.seed.concepts import _CONCEPT_DEFS, _LINK_DEFS

SEED_SOURCE = "seed"
SEED_LABEL = "curated example"
SEED_ID_PREFIX = "seed:"
READ_ONLY_HINT = (
    "Lore is running in read-only demo mode (no GitHub token). Publishing, linking and "
    "rating are disabled. Set LORE_GITHUB_TOKEN (or run 'mcp-server-lore init' with "
    "'gh auth login' done) and remove LORE_READ_ONLY to enable them."
)


def read_only_enabled(env: Optional[dict] = None) -> bool:
    """True when ``LORE_READ_ONLY=1`` is set in ``env`` (default ``os.environ``)."""
    return (os.environ if env is None else env).get("LORE_READ_ONLY") == "1"


def read_only_error(tool: str) -> dict:
    """Structured typed error returned by write tools in read-only mode."""
    return {"error": "read_only", "tool": tool, "hint": READ_ONLY_HINT}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _seed_id(name: str) -> str:
    return SEED_ID_PREFIX + _slug(name)


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w]


def _summary(defn: dict) -> dict:
    return {"name": defn["name"], "when_to_use": defn["when_to_use"]}


def _links_for(name: str) -> list[dict]:
    by_name = {d["name"]: d for d in _CONCEPT_DEFS}
    links: list[dict] = []
    for link in _LINK_DEFS:
        if link["from"] == name:
            other, direction = link["to"], "outgoing"
        elif link["to"] == name:
            other, direction = link["from"], "incoming"
        else:
            continue
        if other not in by_name:
            continue
        links.append({
            "gist_id": _seed_id(other),
            "concept_id": _seed_id(other),
            "rel": link["rel"],
            "label": link["label"],
            "direction": direction,
            **_summary(by_name[other]),
        })
    return links


def _to_concept(defn: dict) -> dict:
    cid = _seed_id(defn["name"])
    return {
        "concept_id": cid,
        "name": defn["name"],
        "type": defn["type"],
        "language": defn.get("language"),
        "content": defn["content"],
        "when_to_use": defn["when_to_use"],
        "dont_use_when": defn.get("dont_use_when"),
        "tags": list(defn.get("tags", [])),
        "source_url": None,
        "avg_rating": None,
        "time_saved_avg_hours": None,
        "avg_hours_saved": None,
        "links": _links_for(defn["name"]),
        "reproducer": unknown_reproducer(),
        "compatibility": unknown_compatibility(),
        "source": SEED_SOURCE,
        "label": SEED_LABEL,
    }


def _score(defn: dict, words: list[str]) -> int:
    haystack = set(_words(" ".join([
        defn["name"], defn["when_to_use"], " ".join(defn.get("tags", [])), defn["content"],
    ])))
    return sum(1 for w in words if w in haystack)


def search_concepts(
    problem: str,
    type: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 3,
    min_rating: float = 2.0,
    environment: Optional[Environment] = None,
    include_incompatible: bool = True,
) -> dict:
    """Keyword-search the bundled curated concepts.

    Results carry ``compatibility_check`` and are ordered by
    :func:`lore.core.ranking.rank_by_compatibility`.  Seeds declare no
    compatibility metadata, so their status is always ``unknown``.

    Same result shape as the gists/semantic backends: ``{"results": [...]}``.
    Seeds are unrated, so ``min_rating`` never excludes them (as for unrated
    gist concepts). Only concepts matching at least one query word are returned.
    """
    words = _words(problem)
    scored = []
    for defn in _CONCEPT_DEFS:
        if type is not None and defn["type"] != type:
            continue
        if language is not None and defn.get("language") != language:
            continue
        if min_rating > 0:  # seeds are unrated, so they pass unless a rating ever exists
            rating = _to_concept(defn)["avg_rating"]
            if rating is not None and rating < min_rating:
                continue
        score = _score(defn, words)
        if score > 0:
            scored.append((score, defn))
    scored.sort(key=lambda pair: -pair[0])  # stable: ties keep corpus order
    results = [_to_concept(d) for _, d in scored]
    return {
        "results": rank_by_compatibility(
            results, environment, limit=limit, include_incompatible=include_incompatible
        )
    }


def get_concept(concept_id: str) -> Optional[dict]:
    """Return a bundled concept by ``seed:<slug>`` ID, or ``None`` if unknown."""
    for defn in _CONCEPT_DEFS:
        if _seed_id(defn["name"]) == concept_id:
            return _to_concept(defn)
    return None
