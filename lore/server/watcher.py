"""Background Gist watcher for the Lore knowledge graph (LORE-031).

Two mechanisms feed the index:

* **Bootstrap (once at startup)** - discovers every existing public
  ``[agentlore-concept]`` gist through the unofficial gist web search
  (``gist.github.com/search``), then fetches each through the authenticated
  API and indexes it.  Fail-soft: it never prevents the poll loop starting.
* **Poll loop** - polls ``GET /gists/public?since=<cursor>`` for new/updated
  ``[agentlore-concept]`` gists and indexes them via ``upsert_concept``.
  GitHub caps that feed at 30 pages (~3000 gists, roughly 13 minutes of
  global gist activity), so ``LORE_WATCH_INTERVAL`` must stay short; a gap
  longer than that loses concepts until the next bootstrap.

This module is started as an asyncio background task by the unified FastAPI
server's ``lifespan`` context manager when ``LORE_STORAGE_BACKEND=gist_qdrant``.

Environment variables consumed
-------------------------------
``LORE_GITHUB_TOKEN``
    Required.  GitHub personal access token used for authenticated API calls.
    If absent the watcher logs a WARNING and sleeps without polling (rate-limit
    protection for unauthenticated calls).

``LORE_WATCH_INTERVAL``
    Poll interval in seconds.  Defaults to ``300`` (5 minutes).  Keep it well
    below the ~13 minutes the capped public feed covers.

``LORE_BOOTSTRAP_DELAY``
    Seconds between gist web-search page requests (default ``2``; lower values
    are raised to ``2``).

``LORE_BOOTSTRAP_MAX_PAGES``
    Hard bound on search pages requested (default ``100``).

``LORE_BOOTSTRAP_MAX_PER_OWNER``
    Maximum gists considered per owner during bootstrap (default ``300``).

Cursor persistence
------------------
The watcher maintains a cursor in ``~/.lore/watcher_cursor.json`` with a
single key ``last_polled_at`` (ISO-8601 timestamp).  On first run the cursor
defaults to 24 hours ago, but the public feed only reaches back as far as its
30-page cap allows (~13 minutes of activity), so that default is an upper
bound, not a guarantee; the bootstrap is what covers older concepts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
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
    24 hours before the current UTC time.  Note the public feed is capped at
    ~3000 gists, so in practice this reaches back only ~13 minutes.

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


async def _fetch_public_gists(
    client: httpx.AsyncClient,
    since: str,
) -> list[dict[str, Any]]:
    """Fetch all public gists updated since ``since``, following pagination.

    Follows ``Link: <url>; rel="next"`` headers to paginate through all
    available results.  At most 100 gists are fetched per page.  GitHub caps
    the feed at 30 pages (3000 gists); if the cap is reached and more pages exist a WARNING is
    logged because concepts may have been missed.

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
    pages = 0

    while url:
        response = await client.get(url)
        response.raise_for_status()
        all_gists.extend(response.json())
        pages += 1

        # Parse Link header for next page URL.
        link_header = response.headers.get("Link", "")
        url = _parse_next_link(link_header)

        if pages >= _PUBLIC_FEED_MAX_PAGES:
            if url:
                logger.warning(
                    "Public gist feed returned %d pages (the GitHub cap) and "
                    "more pages exist; concepts may have been missed — shorten "
                    "LORE_WATCH_INTERVAL.",
                    pages,
                )
            # GitHub rejects page 31+ for this resource; stop and keep the
            # 30 pages already fetched instead of looping or failing the cycle.
            break

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
    """Fetch the full gist object (including file contents) from GitHub."""
    response = await client.get(f"{_GITHUB_API_BASE}/gists/{gist_id}")
    response.raise_for_status()
    return response.json()


_LORE_RATING_PREFIX = "[lore-rating]"


async def _fetch_rating_aggregates(
    client: httpx.AsyncClient,
    gist_id: str,
) -> tuple[float | None, float | None]:
    """Fetch gist comments and return (avg_rating, avg_hours_saved) from ``[lore-rating]`` entries.

    Returns (None, None) if there are no rating comments or on fetch failure.
    """
    try:
        response = await client.get(f"{_GITHUB_API_BASE}/gists/{gist_id}/comments")
        response.raise_for_status()
        comments = response.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch comments for gist %s: %s", gist_id, exc)
        return None, None

    outcomes: list[float] = []
    hours_list: list[float] = []
    for comment in comments:
        body = comment.get("body", "")
        if not body.startswith(_LORE_RATING_PREFIX):
            continue
        raw = body[len(_LORE_RATING_PREFIX):]
        try:
            data = json.loads(raw)
            outcomes.append(float(data["outcome"]))
            if data.get("hours_saved") is not None:
                hours_list.append(float(data["hours_saved"]))
        except Exception:  # noqa: BLE001
            pass

    avg_rating = sum(outcomes) / len(outcomes) if outcomes else None
    avg_hours_saved = sum(hours_list) / len(hours_list) if hours_list else None
    return avg_rating, avg_hours_saved


# ---------------------------------------------------------------------------
# Concept extraction
# ---------------------------------------------------------------------------


def _extract_payload(
    gist: dict[str, Any],
    avg_rating: float | None = None,
    avg_hours_saved: float | None = None,
) -> dict[str, Any] | None:
    """Extract a upsert payload dict from a full GitHub gist object.

    Reads ``lore.json`` from the gist's files, parses it, and builds the
    payload dict expected by :meth:`~lore.server.storage.base.StorageBackend.upsert_concept`.
    Rating aggregates computed from gist comments are passed in explicitly so
    the caller controls when to fetch them.

    Args:
        gist: Full gist dict from the GitHub API (``GET /gists/{id}``).
        avg_rating: Pre-computed average rating from comments, or ``None``.
        avg_hours_saved: Pre-computed average hours saved, or ``None``.

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
        "avg_rating": avg_rating,
        "avg_hours_saved": avg_hours_saved,
    }


# ---------------------------------------------------------------------------
# Bootstrap phase (LORE-056)
# ---------------------------------------------------------------------------

_GIST_SEARCH_URL = "https://gist.github.com/search"
_GIST_SEARCH_QUERY = '"agentlore-concept"'
_USER_AGENT = (
    "AgentLore-watcher/1.0 (+https://github.com/Magublafix/AgentLore; "
    "bootstrap discovery of [agentlore-concept] gists, rate-limited)"
)

_DEFAULT_BOOTSTRAP_DELAY = 2.0
_DEFAULT_BOOTSTRAP_MAX_PAGES = 100
_DEFAULT_BOOTSTRAP_MAX_PER_OWNER = 300
_MIN_BOOTSTRAP_DELAY = 2.0

# ``/<owner>/<gist_id>`` links on a result page.  Gist ids are 20-40 hex chars
# (legacy numeric ids are far shorter and are not returned by the search).
_GIST_LINK_RE = re.compile(
    r'href=["\']/([A-Za-z0-9][A-Za-z0-9-]{0,38})/([0-9a-f]{20,40})(?=["\'#/?])'
)
_EMPTY_PAGE_MARKERS = ("blankslate", "find any gists")
_BLOCKED_PAGE_MARKERS = (
    "captcha",
    "are you a robot",
    "unusual traffic",
    "rate limit",
    "too many requests",
    "temporarily restricted",
)

# The public feed returns at most 30 pages of 100 gists.
_PUBLIC_FEED_MAX_PAGES = 30


def _env_number(name: str, default: float, minimum: float = 0.0) -> float:
    """Read a numeric environment variable, falling back on bad input.

    Args:
        name: Environment variable name.
        default: Value used when the variable is unset or not a number.
        minimum: Lower bound; smaller values are clamped to it.

    Returns:
        The parsed (and clamped) value, or ``default``.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r (using %s).", name, raw, default)
        return default
    return max(value, minimum)


def _parse_search_page(html: str) -> list[tuple[str, str]]:
    """Extract ``(owner, gist_id)`` pairs from a gist.github.com search page.

    This is the only function that knows the markup of the (unofficial) web
    search.  It never raises: if no result links are found and the page is not
    the recognised "no results" page, a WARNING is logged and an empty list is
    returned.  Results are de-duplicated and keep page order.

    Args:
        html: Raw HTML of one search result page.

    Returns:
        List of ``(owner, gist_id)`` tuples; empty for the last/empty page.
    """
    try:
        found: list[tuple[str, str]] = []
        seen: set[str] = set()
        for owner, gist_id in _GIST_LINK_RE.findall(html or ""):
            if gist_id in seen:
                continue
            seen.add(gist_id)
            found.append((owner, gist_id))
        if not found and not any(m in (html or "") for m in _EMPTY_PAGE_MARKERS):
            logger.warning(
                "Bootstrap: unexpected gist search markup (no results and no "
                "'no results' marker) — the page format may have changed."
            )
        return found
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bootstrap: failed to parse gist search page: %s", exc)
        return []


def _looks_blocked(html: str) -> bool:
    """Return ``True`` if a result-less 200 page looks like a block page.

    Only call this for pages that yielded no result links: a genuine result
    page may legitimately mention "rate limit" or "CAPTCHA" in a snippet, so
    free text inside results must never count as a block.
    """
    lowered = (html or "").lower()
    return any(m in lowered for m in _BLOCKED_PAGE_MARKERS)


async def _discover_concept_gists(
    web_client: httpx.AsyncClient,
    *,
    delay: float,
    max_pages: int,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> list[tuple[str, str]]:
    """Page through the gist web search and collect ``(owner, gist_id)``.

    Stops at the first empty page, when a page adds no new ids, or after
    ``max_pages``.  Stops with a WARNING (keeping everything found so far) on
    HTTP 429/403, any other non-200 status, a CAPTCHA/interstitial page, or a
    network error.  Waits ``delay`` seconds between page requests.

    Args:
        web_client: Unauthenticated client (the token is never sent to the web).
        delay: Seconds to wait between consecutive page requests.
        max_pages: Hard safety bound on the number of pages requested.
        sleep: Awaitable sleep function (injectable for tests).

    Returns:
        De-duplicated ``(owner, gist_id)`` list in discovery order.
    """
    results: list[tuple[str, str]] = []
    seen: set[str] = set()

    for page in range(1, max_pages + 1):
        if page > 1:
            await sleep(delay)
        try:
            response = await web_client.get(
                _GIST_SEARCH_URL, params={"q": _GIST_SEARCH_QUERY, "p": page}
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "Bootstrap: gist search request failed on page %d: %s — "
                "keeping %d result(s).", page, exc, len(results),
            )
            return results

        if response.status_code != 200:
            kind = (
                "rate-limited/forbidden"
                if response.status_code in (403, 429)
                else "unexpected status"
            )
            retry_after = response.headers.get("Retry-After")
            logger.warning(
                "Bootstrap: gist search returned HTTP %d (%s) on page %d%s — "
                "stopping and keeping %d result(s).",
                response.status_code, kind, page,
                f" (Retry-After: {retry_after})" if retry_after else "",
                len(results),
            )
            return results

        html = response.text
        entries = _parse_search_page(html)
        if not entries and _looks_blocked(html):
            logger.warning(
                "Bootstrap: gist search page %d looks like a CAPTCHA/rate-limit "
                "page — stopping and keeping %d result(s).", page, len(results),
            )
            return results
        if not entries:
            return results
        new = [(o, g) for o, g in entries if g not in seen]
        if not new:
            logger.warning(
                "Bootstrap: gist search page %d repeated known results — stopping.",
                page,
            )
            return results
        for owner, gist_id in new:
            seen.add(gist_id)
            results.append((owner, gist_id))

    logger.warning(
        "Bootstrap: reached the page limit (%d) of the gist search; further "
        "concepts may exist (raise LORE_BOOTSTRAP_MAX_PAGES).", max_pages,
    )
    return results


async def _run_bootstrap(
    storage: StorageBackend,
    github_token: str,
    min_rating: float,
    *,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> dict[str, int]:
    """Bootstrap the index from every public ``[agentlore-concept]`` gist.

    Runs once before the poll loop.  Discovery uses the unofficial gist web
    search (code search does not index gists, and ``/gists/public`` only
    reaches ~3000 recent gists); content always comes from the authenticated
    API (``GET /gists/{id}``) and goes through :func:`_extract_payload` and
    ``storage.upsert_concept``.  The web page is never used as content.

    Fail-soft: any error is logged and whatever was discovered is still
    processed; this function never raises (except ``CancelledError``), so the
    poll loop always starts.  Idempotent: ``upsert_concept`` reports
    unchanged concepts as ``skipped``.

    Environment variables:
        ``LORE_BOOTSTRAP_DELAY`` seconds between search pages (default 2,
        values below 2 are raised to 2); ``LORE_BOOTSTRAP_MAX_PAGES`` hard
        page bound (default 100); ``LORE_BOOTSTRAP_MAX_PER_OWNER`` maximum
        gists considered per owner (default 300, spam limit).

    Args:
        storage: Active storage backend.
        github_token: GitHub token for the API fetches.  If empty, the
            bootstrap is skipped with a WARNING.
        min_rating: Minimum average ``outcome`` (1-5); unrated gists always
            pass.  ``0.0`` disables the filter.
        sleep: Awaitable sleep function (injectable for tests).

    Returns:
        Counters: ``discovered``, ``indexed``, ``unchanged``, ``skipped``
        (rating filter), ``rejected`` (no marker / invalid), ``capped``.
    """
    stats = {
        "discovered": 0, "indexed": 0, "unchanged": 0,
        "skipped": 0, "rejected": 0, "capped": 0,
    }
    if not github_token:
        logger.warning(
            "LORE_GITHUB_TOKEN is not set — skipping bootstrap phase."
        )
        return stats

    delay = _env_number(
        "LORE_BOOTSTRAP_DELAY", _DEFAULT_BOOTSTRAP_DELAY, _MIN_BOOTSTRAP_DELAY
    )
    max_pages = int(_env_number(
        "LORE_BOOTSTRAP_MAX_PAGES", _DEFAULT_BOOTSTRAP_MAX_PAGES, 1
    ))
    max_per_owner = int(_env_number(
        "LORE_BOOTSTRAP_MAX_PER_OWNER", _DEFAULT_BOOTSTRAP_MAX_PER_OWNER, 1
    ))

    logger.info("Bootstrap: discovering [agentlore-concept] gists via gist web search…")

    candidates: list[tuple[str, str]] = []
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT}, timeout=30.0
        ) as web_client:
            candidates = await _discover_concept_gists(
                web_client, delay=delay, max_pages=max_pages, sleep=sleep
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bootstrap: gist discovery failed: %s", exc)

    stats["discovered"] = len(candidates)
    logger.info("Bootstrap: discovered %d candidate gist(s).", len(candidates))
    if not candidates:
        return stats

    per_owner: dict[str, int] = {}
    selected: list[str] = []
    for owner, gist_id in candidates:
        key = owner.lower()
        if per_owner.get(key, 0) >= max_per_owner:
            stats["capped"] += 1
            continue
        per_owner[key] = per_owner.get(key, 0) + 1
        selected.append(gist_id)
    if stats["capped"]:
        logger.warning(
            "Bootstrap: per-owner cap (%d) dropped %d gist(s).",
            max_per_owner, stats["capped"],
        )

    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
            for gist_id in selected:
                try:
                    full_gist = await _fetch_full_gist(client, gist_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Bootstrap: failed to fetch full gist %s: %s", gist_id, exc
                    )
                    continue

                if _LORE_CONCEPT_MARKER not in (full_gist.get("description") or ""):
                    logger.info("Bootstrap: gist %s lacks the marker — skipping.", gist_id)
                    stats["rejected"] += 1
                    continue

                avg_rating, avg_hours_saved = await _fetch_rating_aggregates(client, gist_id)

                if min_rating > 0 and avg_rating is not None and avg_rating < min_rating:
                    logger.info(
                        "Skipping gist %s — avg rating %.1f below threshold %s",
                        gist_id, avg_rating, min_rating,
                    )
                    stats["skipped"] += 1
                    continue

                payload = _extract_payload(
                    full_gist, avg_rating=avg_rating, avg_hours_saved=avg_hours_saved
                )
                if payload is None:
                    stats["rejected"] += 1
                    continue

                try:
                    result = storage.upsert_concept(payload)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Bootstrap: upsert_concept failed for gist %s: %s", gist_id, exc
                    )
                    continue
                status = result.get("status", "unknown")
                logger.info(
                    "Bootstrap: gist %s (%s): %s.", gist_id, payload.get("name", ""), status
                )
                if status == "skipped":
                    stats["unchanged"] += 1
                else:
                    stats["indexed"] += 1
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bootstrap phase failed unexpectedly: %s", exc)

    logger.info(
        "Bootstrap complete: %d discovered, %d indexed, %d unchanged, "
        "%d skipped (rating filter), %d rejected, %d dropped by owner cap.",
        stats["discovered"], stats["indexed"], stats["unchanged"],
        stats["skipped"], stats["rejected"], stats["capped"],
    )
    return stats


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
    """Poll GitHub public gists API and index ``[agentlore-concept]`` entries.

    Runs a one-time bootstrap phase first (see :func:`_run_bootstrap`), then
    enters an indefinite polling loop that sleeps for ``interval`` seconds
    between cycles.  It is designed to be started with ``asyncio.create_task``
    and cancelled cleanly on server shutdown via :class:`asyncio.CancelledError`.

    Bootstrap phase (once at startup):
        Discovers all public ``[agentlore-concept]`` gists via the gist web
        search and indexes the valid ones (see :func:`_run_bootstrap`).  Gists
        whose average ``outcome`` rating is below ``min_rating`` are skipped.
        Unrated gists are always indexed.  A failed or partial bootstrap is
        logged and the poll loop starts regardless.

    Each subsequent poll cycle:

    1. Loads the cursor timestamp from ``~/.lore/watcher_cursor.json``.
    2. Fetches public gists updated since the cursor timestamp.
    3. Filters to gists whose description contains ``"[agentlore-concept]"``.
    4. Deduplicates by gist ID within the cycle.
    5. For each candidate, fetches the full gist and extracts metadata from
       ``lore.json``.
    6. Calls ``storage.upsert_concept`` to index into Qdrant.
    7. Advances the cursor to the latest ``updated_at`` among processed gists.
    8. Sleeps for ``interval`` seconds then repeats.

    The public feed is capped at 30 pages (~3000 gists, about 13 minutes of
    global activity), so ``interval`` must stay well below that or concepts
    can be missed; a WARNING is logged when a poll hits the cap.

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

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
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

            # Fetch full gist and comment-based rating aggregates.
            try:
                full_gist = await _fetch_full_gist(client, gist_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to fetch full gist %s: %s", gist_id, exc
                )
                continue

            avg_rating, avg_hours_saved = await _fetch_rating_aggregates(client, gist_id)
            payload = _extract_payload(full_gist, avg_rating=avg_rating, avg_hours_saved=avg_hours_saved)
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
