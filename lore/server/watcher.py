"""Background Gist watcher for the Lore knowledge graph (LORE-031).

Polls the GitHub public gist API for new/updated ``[lore-concept]`` gists,
parses their structured metadata, and indexes them into the active storage
backend via ``upsert_concept``.

This module is started as an asyncio background task by the unified FastAPI
server's ``lifespan`` context manager when ``LORE_STORAGE_BACKEND=gist_qdrant``.

Environment variables consumed
-------------------------------
``LORE_GITHUB_TOKEN``
    Required.  GitHub personal access token used for authenticated API calls.
    If absent the watcher logs a WARNING and sleeps without polling (rate-limit
    protection for unauthenticated calls).

``LORE_WATCH_INTERVAL``
    Poll interval in seconds.  Defaults to ``300`` (5 minutes).

Cursor persistence
------------------
The watcher maintains a cursor in ``~/.lore/watcher_cursor.json`` with a
single key ``last_polled_at`` (ISO-8601 timestamp).  On first run the cursor
defaults to 24 hours ago so the first poll catches recently-published gists
without scanning all public gists from the beginning of time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from lore.core.constants import _parse_name_from_description
from lore.server.storage.base import StorageBackend

logger = logging.getLogger(__name__)

_CURSOR_PATH = Path("~/.lore/watcher_cursor.json").expanduser()
_GITHUB_API_BASE = "https://api.github.com"
_LORE_CONCEPT_MARKER = "[agentlore-concept]"


# ---------------------------------------------------------------------------
# Cursor helpers
# ---------------------------------------------------------------------------


def _load_cursor() -> str:
    """Load the last-polled-at timestamp from the cursor file.

    If the cursor file does not exist or cannot be parsed, returns a timestamp
    24 hours before the current UTC time so the first poll picks up recently
    published gists.

    Returns:
        ISO-8601 timestamp string ending with ``"Z"``, e.g.
        ``"2024-01-15T12:00:00Z"``.
    """
    try:
        data = json.loads(_CURSOR_PATH.read_text())
        return data["last_polled_at"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        default = datetime.now(tz=timezone.utc) - timedelta(hours=24)
        return default.strftime("%Y-%m-%dT%H:%M:%SZ")


def _save_cursor(timestamp: str) -> None:
    """Persist the last-polled-at timestamp to the cursor file.

    Creates ``~/.lore/`` if it does not already exist.

    Args:
        timestamp: ISO-8601 timestamp string to persist.
    """
    _CURSOR_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CURSOR_PATH.write_text(json.dumps({"last_polled_at": timestamp}))


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------


async def _fetch_authenticated_gists(
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    """Fetch all gists owned by the authenticated user, following pagination.

    Calls ``GET /gists`` (the authenticated user's own gists, not the public
    feed) with ``per_page=100`` and follows ``Link: rel="next"`` headers until
    all pages are exhausted.

    Args:
        client: An authenticated :class:`httpx.AsyncClient` instance.

    Returns:
        List of gist summary dicts from the GitHub API.
    """
    all_gists: list[dict[str, Any]] = []
    url: str | None = f"{_GITHUB_API_BASE}/gists?per_page=100&page=1"

    while url:
        response = await client.get(url)
        response.raise_for_status()
        page = response.json()
        if not page:
            break
        all_gists.extend(page)
        link_header = response.headers.get("Link", "")
        url = _parse_next_link(link_header)

    return all_gists


async def _fetch_public_gists(
    client: httpx.AsyncClient,
    since: str,
) -> list[dict[str, Any]]:
    """Fetch all public gists updated since ``since``, following pagination.

    Follows ``Link: <url>; rel="next"`` headers to paginate through all
    available results.  At most 100 gists are fetched per page.

    Args:
        client: An authenticated :class:`httpx.AsyncClient` instance.
        since: ISO-8601 timestamp; only gists updated at or after this time
            are returned.

    Returns:
        List of gist summary dicts from the GitHub API.
    """
    all_gists: list[dict[str, Any]] = []
    url: str | None = (
        f"{_GITHUB_API_BASE}/gists/public?since={since}&per_page=100"
    )

    while url:
        response = await client.get(url)
        response.raise_for_status()
        all_gists.extend(response.json())

        # Parse Link header for next page URL.
        link_header = response.headers.get("Link", "")
        url = _parse_next_link(link_header)

    return all_gists


def _parse_next_link(link_header: str) -> str | None:
    """Parse the ``Link`` HTTP header and return the ``rel="next"`` URL.

    Args:
        link_header: Raw value of the ``Link`` response header.

    Returns:
        The next-page URL string, or ``None`` if there is no next page.
    """
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        if 'rel="next"' in part:
            # Format: <https://api.github.com/...>; rel="next"
            url_part = part.split(";")[0].strip()
            if url_part.startswith("<") and url_part.endswith(">"):
                return url_part[1:-1]
    return None


async def _fetch_full_gist(
    client: httpx.AsyncClient,
    gist_id: str,
) -> dict[str, Any]:
    """Fetch the full gist object (including file contents) from GitHub.

    Args:
        client: An authenticated :class:`httpx.AsyncClient` instance.
        gist_id: GitHub gist identifier string.

    Returns:
        Full gist dict from the GitHub API including ``files`` with content.

    Raises:
        httpx.HTTPStatusError: On non-2xx HTTP responses.
    """
    response = await client.get(f"{_GITHUB_API_BASE}/gists/{gist_id}")
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Concept extraction
# ---------------------------------------------------------------------------


def _extract_payload(gist: dict[str, Any]) -> dict[str, Any] | None:
    """Extract a upsert payload dict from a full GitHub gist object.

    Reads ``lore.json`` from the gist's files, parses it, and builds the
    payload dict expected by :meth:`~lore.server.storage.base.StorageBackend.upsert_concept`.

    Args:
        gist: Full gist dict from the GitHub API (``GET /gists/{id}``).

    Returns:
        Upsert payload dict, or ``None`` if ``lore.json`` is absent or cannot
        be parsed (a WARNING is logged in that case).
    """
    gist_id: str = gist["id"]
    files: dict[str, Any] = gist.get("files", {})

    lore_json_file = files.get("lore.json")
    if not lore_json_file:
        logger.warning(
            "Gist %s has no lore.json file — skipping.", gist_id
        )
        return None

    raw_content = lore_json_file.get("content", "")
    try:
        metadata = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        logger.warning(
            "Gist %s has malformed lore.json (%s) — skipping.", gist_id, exc
        )
        return None

    # Require at minimum a name and when_to_use for the concept to be useful.
    name: str = metadata.get("name", "")
    when_to_use: str = metadata.get("when_to_use", "")

    # Fall back to parsing name from description if not in lore.json.
    if not name:
        description = gist.get("description", "")
        name = _parse_name_from_description(description)

    if not when_to_use:
        logger.warning("Skipping gist %s — missing 'when_to_use' field", gist_id)
        return None

    return {
        "gist_id": gist_id,
        "name": name,
        "type": metadata.get("type", "pattern"),
        "language": metadata.get("language"),
        "when_to_use": when_to_use,
        "dont_use_when": metadata.get("dont_use_when"),
        "tags": metadata.get("tags", []),
        "author": metadata.get("author") or (gist.get("owner") or {}).get("login"),
        "source_url": metadata.get("source_url"),
        "links": metadata.get("links", []),
        "gist_updated_at": gist.get("updated_at", ""),
    }


# ---------------------------------------------------------------------------
# Bootstrap phase
# ---------------------------------------------------------------------------


async def _fetch_all_public_gists(
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    """Fetch all public gists (no ``since`` filter), following pagination.

    Calls ``GET /gists/public?per_page=100&page=N`` starting at page 1 and
    stops when an empty page is returned or the ``Link: rel="next"`` header
    is absent.

    Args:
        client: An authenticated :class:`httpx.AsyncClient` instance.

    Returns:
        List of all public gist summary dicts from the GitHub API.
    """
    all_gists: list[dict[str, Any]] = []
    url: str | None = f"{_GITHUB_API_BASE}/gists/public?per_page=100&page=1"

    while url:
        response = await client.get(url)
        response.raise_for_status()
        page = response.json()
        if not page:
            break
        all_gists.extend(page)
        link_header = response.headers.get("Link", "")
        url = _parse_next_link(link_header)

    return all_gists


async def _run_bootstrap(
    storage: StorageBackend,
    github_token: str,
    min_rating: float,
) -> None:
    """Bootstrap the Qdrant index from all public gists.

    Runs once at startup before the polling loop begins.  Fetches all public
    gists (paginated, no ``since`` filter), filters to those tagged with
    ``[lore-concept]``, optionally skips gists whose average ``outcome`` rating
    is below ``min_rating``, and upserts the remainder into storage.

    This is a full one-time scan — it is not cursor-based.  Running it when
    a cursor already exists is safe; ``upsert_concept`` handles idempotency.

    Unrated gists (empty or missing ``ratings`` list) are always indexed,
    regardless of ``min_rating``.

    Args:
        storage: Active storage backend.
        github_token: GitHub personal access token.  If empty, the bootstrap
            is skipped and a WARNING is logged.
        min_rating: Minimum average ``outcome`` score (1–5).  Gists with a
            computed average below this threshold are skipped.  Pass ``0.0``
            (the default) to index all gists regardless of rating.
    """
    if not github_token:
        logger.warning(
            "LORE_GITHUB_TOKEN is not set — skipping bootstrap phase."
        )
        return

    logger.info("Bootstrap: fetching all public gists…")

    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        async with httpx.AsyncClient(headers=headers) as client:
            try:
                summaries = await _fetch_all_public_gists(client)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Bootstrap: failed to fetch public gists: %s", exc)
                return

            # Filter to [lore-concept] gists.
            candidates = [
                g for g in summaries
                if _LORE_CONCEPT_MARKER in (g.get("description") or "")
            ]
            logger.info(
                "Bootstrap: found %d [lore-concept] gist(s) out of %d total.",
                len(candidates),
                len(summaries),
            )

            indexed = 0
            skipped = 0

            for summary in candidates:
                gist_id: str = summary["id"]

                # Fetch full gist for lore.json content and ratings.
                try:
                    full_gist = await _fetch_full_gist(client, gist_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Bootstrap: failed to fetch full gist %s: %s", gist_id, exc
                    )
                    continue

                # --- Rating filter ---
                if min_rating > 0:
                    lore_json_file = full_gist.get("files", {}).get("lore.json")
                    ratings: list[dict[str, Any]] = []
                    if lore_json_file:
                        try:
                            metadata = json.loads(lore_json_file.get("content", ""))
                            ratings = metadata.get("ratings", [])
                        except (json.JSONDecodeError, AttributeError):
                            pass  # Treat as unrated — will be indexed.

                    if ratings:
                        outcomes = [
                            r["outcome"] for r in ratings
                            if isinstance(r.get("outcome"), (int, float))
                        ]
                        if outcomes:
                            avg = sum(outcomes) / len(outcomes)
                            if avg < min_rating:
                                logger.info(
                                    "Skipping gist %s — avg rating %.1f below threshold %s",
                                    gist_id,
                                    avg,
                                    min_rating,
                                )
                                skipped += 1
                                continue

                payload = _extract_payload(full_gist)
                if payload is None:
                    continue

                try:
                    result = storage.upsert_concept(payload)
                    status = result.get("status", "unknown")
                    logger.info(
                        "Bootstrap: gist %s (%s): %s.",
                        gist_id,
                        payload.get("name", ""),
                        status,
                    )
                    indexed += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Bootstrap: upsert_concept failed for gist %s: %s",
                        gist_id,
                        exc,
                    )

    except Exception as exc:  # noqa: BLE001
        logger.warning("Bootstrap phase failed unexpectedly: %s", exc)
        return

    logger.info(
        "Bootstrap complete: %d indexed, %d skipped (rating filter).",
        indexed,
        skipped,
    )


# ---------------------------------------------------------------------------
# Main watch loop
# ---------------------------------------------------------------------------


async def watch_loop(
    storage: StorageBackend,
    github_token: str,
    interval: int,
    *,
    min_rating: float = 0.0,
) -> None:
    """Poll GitHub public gists API and index ``[lore-concept]`` entries.

    Runs a one-time bootstrap phase first (see :func:`_run_bootstrap`), then
    enters an indefinite polling loop that sleeps for ``interval`` seconds
    between cycles.  It is designed to be started with ``asyncio.create_task``
    and cancelled cleanly on server shutdown via :class:`asyncio.CancelledError`.

    Bootstrap phase (once at startup):
        Fetches all gists owned by the authenticated user and indexes those
        tagged with ``[lore-concept]``.  Gists whose average ``outcome``
        rating is below ``min_rating`` are skipped.  Unrated gists are always
        indexed.

    Each subsequent poll cycle:

    1. Loads the cursor timestamp from ``~/.lore/watcher_cursor.json``.
    2. Fetches public gists updated since the cursor timestamp.
    3. Filters to gists whose description contains ``"[lore-concept]"``.
    4. Deduplicates by gist ID within the cycle.
    5. For each candidate, fetches the full gist and extracts metadata from
       ``lore.json``.
    6. Calls ``storage.upsert_concept`` to index into Qdrant.
    7. Advances the cursor to the latest ``updated_at`` among processed gists.
    8. Sleeps for ``interval`` seconds then repeats.

    Args:
        storage: Active storage backend.  Must implement
            :meth:`~lore.server.storage.base.StorageBackend.upsert_concept`.
        github_token: GitHub personal access token for authenticated API calls.
            If empty, the bootstrap and poll steps are skipped.
        interval: Seconds to sleep between poll cycles.
        min_rating: Minimum average ``outcome`` score for the bootstrap filter.
            Pass ``0.0`` (default) to index all concepts regardless of rating.

    Raises:
        asyncio.CancelledError: Propagated cleanly when the task is cancelled.
    """
    logger.info("Gist watcher starting (interval=%ds).", interval)

    # --- Bootstrap phase: one-time full sync before entering the poll loop ---
    try:
        await _run_bootstrap(storage, github_token, min_rating)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bootstrap phase failed: %s", exc)

    logger.info("Bootstrap complete — entering poll loop.")

    while True:
        try:
            await _run_poll_cycle(storage, github_token)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gist watcher poll cycle failed: %s", exc)

        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("Gist watcher cancelled during sleep — shutting down.")
            raise


async def _run_poll_cycle(storage: StorageBackend, github_token: str) -> None:
    """Execute a single poll cycle.

    Separated from :func:`watch_loop` to make unit testing straightforward.

    Args:
        storage: Active storage backend.
        github_token: GitHub personal access token.  If empty, the HTTP poll
            is skipped and the function returns immediately.
    """
    if not github_token:
        logger.warning(
            "LORE_GITHUB_TOKEN is not set — skipping poll cycle."
        )
        return

    since = _load_cursor()
    logger.info("Polling GitHub public gists since %s.", since)

    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(headers=headers) as client:
        try:
            summaries = await _fetch_public_gists(client, since)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch public gists: %s", exc)
            return

        # Filter to lore-concept gists and dedup within this cycle.
        candidates = [
            g for g in summaries
            if _LORE_CONCEPT_MARKER in (g.get("description") or "")
        ]
        seen_ids: set[str] = set()
        processed_updated_ats: list[str] = []

        for summary in candidates:
            gist_id: str = summary["id"]
            if gist_id in seen_ids:
                logger.info("Skipping duplicate gist %s in this cycle.", gist_id)
                continue
            seen_ids.add(gist_id)

            # Fetch full gist for lore.json content.
            try:
                full_gist = await _fetch_full_gist(client, gist_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to fetch full gist %s: %s", gist_id, exc
                )
                continue

            payload = _extract_payload(full_gist)
            if payload is None:
                # _extract_payload already logged the warning.
                continue

            try:
                result = storage.upsert_concept(payload)
                status = result.get("status", "unknown")
                logger.info(
                    "Gist %s (%s): %s.", gist_id, payload.get("name", ""), status
                )
                updated_at = full_gist.get("updated_at", "")
                if updated_at:
                    processed_updated_ats.append(updated_at)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "upsert_concept failed for gist %s: %s", gist_id, exc
                )

    # Advance cursor to the most recent updated_at, or now if nothing processed.
    if processed_updated_ats:
        new_cursor = max(processed_updated_ats)
    else:
        new_cursor = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    _save_cursor(new_cursor)
    logger.info("Cursor advanced to %s.", new_cursor)
