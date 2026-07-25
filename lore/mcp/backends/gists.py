"""GitHub Gists backend for Lore MCP tools (LORE-011).

Provides ``submit_concept`` and ``get_concept`` functions that store and
retrieve Lore concepts as GitHub Gists.

Each concept gist contains two files:
- ``concept.md``: the concept's content field verbatim.
- ``lore.json``: JSON metadata (type, tags, when_to_use, links, etc.).

The gist description encodes the concept name and tags in the format:
    ``[lore-concept] <name> [<tag1>, <tag2>, ...]``

Rating data is stored as gist comments whose body starts with the prefix
``[lore-rating]`` followed by a JSON payload.  Each call to
``rate_concept`` always creates a new comment so ratings accumulate across
runs and users.

Depth-1 link resolution is performed inline during ``get_concept`` — a
maximum of 10 linked concepts are resolved in a single call.  Unavailable
or errored linked gists are represented with a status field rather than
raising.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

from lore.core.constants import VALID_LINK_RELS, _parse_name_from_description
from lore.mcp.backends.gists_client import (
    GistNotFoundError,
    GistRateLimitError,
    GistsClient,
)

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_LORE_RATING_PREFIX = "[lore-rating]"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def submit_concept(
    client: GistsClient,
    name: str,
    type: str,
    content: str,
    when_to_use: str,
    tags: list[str],
    language: Optional[str] = None,
    dont_use_when: Optional[str] = None,
    source_url: Optional[str] = None,
    links: Optional[list[dict]] = None,
) -> dict:
    """Submit a concept as a GitHub Gist.

    Creates a public gist with two files: ``concept.md`` (the concept content)
    and ``lore.json`` (structured metadata).  The gist description encodes
    the concept name and tags so that name and tags can be recovered without
    parsing the JSON file.

    Args:
        client: An authenticated :class:`GistsClient` instance.
        name: Short human-readable name for the concept.
        type: Concept type (e.g. ``"pattern"``, ``"tool"``).
        content: Markdown body describing the concept.
        when_to_use: Natural-language description of ideal use context.
        tags: List of tag strings.
        language: Programming language context.  ``None`` if not applicable.
        dont_use_when: Known anti-cases / counter-indications.  ``None`` if
            not applicable.
        source_url: Origin URL.  ``None`` if not applicable.
        links: Optional list of link dicts.  Each dict should contain
            ``"gist_id"`` and ``"rel"`` keys.  Defaults to ``[]``.

    Returns:
        A dict with ``concept_id`` (the gist id), ``name``, and
        ``source_url`` (the public gist URL).

    Raises:
        GistAuthError: If the GitHub token is invalid or missing.
        GistRateLimitError: If the GitHub API rate limit is exhausted.
        GistAPIError: On unexpected GitHub API errors.
    """
    description = f"[agentlore-concept] {name} [{', '.join(tags)}]"

    lore_metadata: dict = {
        "schema_version": "1",
        "type": type,
        "language": language,
        "when_to_use": when_to_use,
        "dont_use_when": dont_use_when,
        "tags": tags,
        "links": links if links is not None else [],
    }

    files: dict[str, str] = {
        "concept.md": content,
        "lore.json": json.dumps(lore_metadata, indent=2),
    }

    gist_id = client.create_gist(files=files, description=description, public=True)

    return {
        "concept_id": gist_id,
        "name": name,
        "source_url": f"https://gist.github.com/{gist_id}",
    }


def link_concepts(
    client: GistsClient,
    from_id: str,
    to_id: str,
    rel: str,
    label: str | None = None,
) -> dict:
    """Add a typed directional link from one concept gist to another.

    Appends a link entry to the ``links`` list in the source concept's
    ``lore.json`` file, then updates the gist via the GitHub API.

    Args:
        client: An authenticated :class:`GistsClient` instance.
        from_id: GitHub gist id of the source concept.
        to_id: GitHub gist id of the target concept.
        rel: Relationship type.  Must be one of: ``"uses"``,
            ``"tested_by"``, ``"extends"``, ``"alternative_to"``,
            ``"requires"``.
        label: Optional human-readable description of the link edge.
            Stored as-is; ``None`` is accepted.

    Returns:
        On success:
            ``{"link_id": "<from_id>:<to_id>:<rel>", "status": "created"}``
        When the link already exists (idempotent):
            ``{"link_id": None, "status": "already_exists"}``
        When the source concept has too many links:
            ``{"error": "Maximum 20 links per concept exceeded",
               "code": "max_links_exceeded"}``

    Raises:
        ValueError: If ``rel`` is not one of the allowed relationship types,
            or if ``to_id`` does not refer to a valid lore concept gist.
        GistNotFoundError: If either ``from_id`` or ``to_id`` gist does not
            exist (propagated from :class:`GistsClient`).
        GistRateLimitError: If the GitHub API rate limit is exhausted.
        GistAPIError: On unexpected GitHub API errors.
    """
    # Step 1 — validate rel before any network call.
    if rel not in VALID_LINK_RELS:
        raise ValueError(
            f"Invalid rel: {rel!r}. Must be one of: uses, tested_by, extends, alternative_to, requires"
        )

    # Step 2 — validate to_id is a lore concept (GistNotFoundError propagates).
    to_gist = client.get_gist(to_id)
    if "[agentlore-concept]" not in to_gist.description:
        raise ValueError(f"to_id {to_id!r} is not a valid lore concept gist")

    # Step 3 — fetch source gist (GistNotFoundError propagates).
    from_gist = client.get_gist(from_id)

    # Step 4 — parse lore.json from the source gist.
    lore_json: dict = json.loads(from_gist.files["lore.json"])

    # Step 5 — idempotency check.
    for entry in lore_json.get("links", []):
        if entry.get("gist_id") == to_id and entry.get("rel") == rel:
            return {"link_id": None, "status": "already_exists"}

    # Step 6 — max links check.
    if len(lore_json.get("links", [])) >= 20:
        return {"error": "Maximum 20 links per concept exceeded", "code": "max_links_exceeded"}

    # Step 7 — append the new link.
    lore_json.setdefault("links", []).append({"gist_id": to_id, "rel": rel, "label": label})

    # Step 8 — write back to GitHub.
    updated_json_str = json.dumps(lore_json, indent=2)
    client.update_gist(from_id, {"lore.json": updated_json_str})

    # Step 9 — return success.
    return {"link_id": f"{from_id}:{to_id}:{rel}", "status": "created"}


def get_concept(client: GistsClient, concept_id: str) -> dict | None:
    """Fetch and return a concept from a GitHub Gist.

    Retrieves the gist by ``concept_id``, parses ``lore.json``, resolves
    linked concepts at depth 1 (up to 10), and aggregates rating comments.

    Args:
        client: An authenticated :class:`GistsClient` instance.
        concept_id: The GitHub gist id for the concept.

    Returns:
        A dict with keys: ``concept_id``, ``name``, ``type``, ``language``,
        ``content``, ``when_to_use``, ``dont_use_when``, ``tags``,
        ``source_url``, ``avg_rating``, ``avg_hours_saved``, and ``links``.
        Returns ``None`` if the gist is not found.
    """
    # Fetch the primary gist.
    try:
        gist_data = client.get_gist(concept_id)
    except GistNotFoundError:
        return None

    lore_json: dict = json.loads(gist_data.files["lore.json"])

    # ---------------------------------------------------------------------------
    # Inline link resolution (depth 1, max 10 links).
    # ---------------------------------------------------------------------------
    raw_links: list[dict] = lore_json.get("links", [])
    resolved_links: list[dict] = []

    for link_entry in raw_links[:10]:
        linked_gist_id = link_entry.get("gist_id", "")
        try:
            linked_gist = client.get_gist(linked_gist_id)
            linked_lore_json: dict = json.loads(linked_gist.files["lore.json"])
            resolved_links.append({
                **link_entry,
                "name": _parse_name_from_description(linked_gist.description),
                "when_to_use": linked_lore_json.get("when_to_use"),
            })
        except Exception as exc:
            logger.warning("Failed to resolve link %s: %s", linked_gist_id, exc)
            resolved_links.append({"gist_id": linked_gist_id, "status": "unavailable"})

    # ---------------------------------------------------------------------------
    # Rating aggregation from gist comments.
    # ---------------------------------------------------------------------------
    avg_rating: Optional[float] = None
    avg_hours_saved: Optional[float] = None

    try:
        comments = client.list_comments(concept_id)
    except Exception as exc:
        logger.warning("Failed to fetch comments for gist %s: %s", concept_id, exc)
        comments = []

    outcomes: list[float] = []
    hours_list: list[float] = []

    for comment in comments:
        if not comment.body.startswith(_LORE_RATING_PREFIX):
            continue
        raw_json = comment.body[len(_LORE_RATING_PREFIX):]
        try:
            rating_data = json.loads(raw_json)
            outcomes.append(float(rating_data["outcome"]))
            if "hours_saved" in rating_data and rating_data["hours_saved"] is not None:
                hours_list.append(float(rating_data["hours_saved"]))
        except Exception as exc:
            logger.warning("Skipping malformed rating comment on gist %s: %s", concept_id, exc)

    if outcomes:
        avg_rating = sum(outcomes) / len(outcomes)
    if hours_list:
        avg_hours_saved = sum(hours_list) / len(hours_list)

    return {
        "concept_id": concept_id,
        "name": _parse_name_from_description(gist_data.description),
        "type": lore_json["type"],
        "language": lore_json.get("language"),
        "content": gist_data.files["concept.md"],
        "when_to_use": lore_json["when_to_use"],
        "dont_use_when": lore_json.get("dont_use_when"),
        "tags": lore_json.get("tags", []),
        "source_url": f"https://gist.github.com/{concept_id}",
        "avg_rating": avg_rating,
        "time_saved_avg_hours": avg_hours_saved,
        "avg_hours_saved": avg_hours_saved,
        "links": resolved_links,
    }


def rate_concept(
    client: GistsClient,
    concept_id: str,
    outcome: int,
    session_id: str,
    hours_saved: float | None = None,
    notes: str | None = None,
) -> dict:
    """Rate a concept by posting a new ``[lore-rating]`` comment on its gist.

    Each call always creates a new comment so ratings accumulate across runs
    and users.  Aggregates are read back from the full comment history via
    :func:`get_concept`.

    Respects the ``LORE_FREELOADER`` environment variable: when set to
    ``"true"`` (case-insensitive) no comment is written and a no-op result is
    returned immediately.

    Args:
        client: An authenticated :class:`GistsClient` instance.
        concept_id: The GitHub gist id for the concept to rate.
        outcome: Integer quality score 1–5 (1 = not helpful, 5 = very helpful).
        session_id: The current agent session identifier; stored in the comment.
        hours_saved: Estimated engineering hours saved by using the concept.
            Must be non-negative if provided.  ``None`` omits the field.
        notes: Free-text notes to attach to the rating.  ``None`` omits the field.

    Returns:
        One of:
        - ``{"status": "no-op", "reason": "LORE_FREELOADER=true"}`` when freeloader mode is active.
        - ``{"status": "created", "concept_id": ..., "avg_rating": float|None, "time_saved_avg_hours": float|None}``

    Raises:
        ValueError: If ``outcome`` is outside the range 1–5, or if ``hours_saved``
            is negative.
        GistNotFoundError: If the concept gist does not exist.
        GistAuthError: If the GitHub token is invalid or missing.
        GistRateLimitError: If the GitHub API rate limit is exhausted.
        GistAPIError: On unexpected GitHub API errors.
    """
    if not (1 <= outcome <= 5):
        raise ValueError(f"outcome must be 1–5, got {outcome}")
    if hours_saved is not None and hours_saved < 0:
        raise ValueError(f"hours_saved must be non-negative, got {hours_saved}")

    if os.environ.get("LORE_FREELOADER", "").lower() == "true":
        return {
            "status": "no-op",
            "reason": "LORE_FREELOADER=true",
            "avg_rating": None,
            "time_saved_avg_hours": None,
        }

    payload: dict = {"outcome": outcome}
    if session_id:
        payload["session_id"] = session_id
    if hours_saved is not None:
        payload["hours_saved"] = hours_saved
    if notes:
        payload["notes"] = notes
    comment_body = f"{_LORE_RATING_PREFIX} {json.dumps(payload)}"

    client.create_comment(concept_id, comment_body)

    updated = get_concept(client, concept_id)
    avg_rating = updated["avg_rating"] if updated else None
    time_saved_avg_hours = updated.get("time_saved_avg_hours") if updated else None

    return {
        "status": "created",
        "concept_id": concept_id,
        "avg_rating": avg_rating,
        "time_saved_avg_hours": time_saved_avg_hours,
    }


def search_concepts(
    client: GistsClient,
    problem: str,
    type: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 3,
    min_rating: float = 2.0,
) -> dict:
    """Search for Lore concepts stored as GitHub Gists.

    Lists all gists owned by the authenticated user via a single
    :meth:`GistsClient.search_gists` call (which follows ``Link`` header
    pagination internally), filters to those whose description contains the
    ``"[agentlore-concept]"`` marker, ranks candidates by keyword relevance
    to ``problem``, and then fetches full concept details for each candidate
    until ``limit`` filter-passing results have been collected.

    Relevance scoring: the number of lowercased words from ``problem`` that
    appear in the gist description (lowercased).  Candidates are sorted by
    descending score before detail-fetching begins.

    Filters applied after concept detail is fetched:
    - ``type``: concept ``type`` field must match (when ``type`` is not None).
    - ``language``: concept ``language`` field must match (when not None).
    - ``min_rating``: concepts with ``avg_rating`` strictly below threshold
      are excluded.  Unrated concepts (``avg_rating`` is None) always pass.

    Args:
        client: An authenticated :class:`GistsClient` instance.
        problem: Natural-language description of the problem to search for.
            Used for relevance scoring against gist descriptions.
        type: Optional concept type filter.
        language: Optional programming language filter.
        limit: Maximum number of matching concepts to return.  Defaults to 3.
        min_rating: Minimum average rating threshold (inclusive).  Defaults
            to 2.0.

    Returns:
        A dict with a single key ``"results"`` whose value is a list of
        concept dicts, each matching the shape returned by :func:`get_concept`.
        Returns ``{"results": []}`` when no concepts match.

    Raises:
        RuntimeError: If a :class:`GistRateLimitError` is raised during any
            GitHub API call.
    """
    try:
        all_summaries = client.search_gists("")
    except GistRateLimitError as exc:
        raise RuntimeError(f"GitHub rate limit reached: {exc}") from exc

    # Filter to lore concept gists only.
    concept_summaries = [
        s for s in all_summaries if "[agentlore-concept]" in s.description
    ]

    # Rank by keyword relevance: count how many problem words appear in description.
    problem_words = problem.lower().split()

    def _relevance(summary) -> int:
        desc_lower = summary.description.lower()
        return sum(1 for w in problem_words if w in desc_lower)

    ranked = sorted(concept_summaries, key=_relevance, reverse=True)

    seen_ids: set[str] = set()
    results: list[dict] = []

    for summary in ranked:
        if len(results) >= limit:
            break

        gist_id = summary.gist_id
        if gist_id in seen_ids:
            continue
        seen_ids.add(gist_id)

        # Fetch full concept (includes lore.json, link resolution, ratings).
        try:
            concept = get_concept(client, gist_id)
        except GistRateLimitError as exc:
            raise RuntimeError(f"GitHub rate limit reached: {exc}") from exc

        if concept is None:
            # Gist not found or unavailable — skip silently.
            continue

        # Client-side type filter.
        if type is not None and concept.get("type") != type:
            continue

        # Client-side language filter.
        if language is not None and concept.get("language") != language:
            continue

        # Rating filter: unrated concepts (avg_rating is None) always pass.
        avg_rating = concept.get("avg_rating")
        if avg_rating is not None and avg_rating < min_rating:
            continue

        results.append(concept)

    return {"results": results}
