"""GitHub Gists API client for the Lore gists backend.

This module provides a thin, typed wrapper around the GitHub REST API v3 Gists
endpoints.  All HTTP errors are translated into typed exceptions so callers
never have to inspect raw ``requests.Response`` objects for error handling.

Environment variables:
    LORE_GITHUB_TOKEN: Personal-access token (or fine-grained PAT) with gist
        read/write scope.  Required — ``GistAuthError`` is raised on startup if
        this variable is absent or produces a 401/403 on the validation call.
"""

from __future__ import annotations

import os
import re as _re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests


def _parse_next_link(link_header: str) -> str | None:
    """Parse the ``rel="next"`` URL from a GitHub ``Link`` response header.

    Args:
        link_header: Raw value of the ``Link`` HTTP header.

    Returns:
        The next-page URL string, or ``None`` if no ``rel="next"`` entry
        is present.
    """
    for part in link_header.split(","):
        if 'rel="next"' in part:
            m = _re.search(r"<([^>]+)>", part)
            if m:
                return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------


class GistAuthError(Exception):
    """Raised when the GitHub token is missing, invalid, or forbidden.

    This covers:
    - ``LORE_GITHUB_TOKEN`` not set in the environment.
    - The token exists but the ``GET /user`` validation call returns 401/403.
    - Any subsequent 401/403 response on any endpoint.
    """


class GistNotFoundError(Exception):
    """Raised when a requested gist or comment does not exist (HTTP 404)."""


class GistRateLimitError(Exception):
    """Raised when the GitHub API rate limit is exhausted.

    Triggered by:
    - An HTTP 429 response (regardless of rate-limit headers).
    - An HTTP response where the ``X-RateLimit-Remaining`` header equals ``"0"``.
    """


class GistAPIError(Exception):
    """Catch-all for unexpected GitHub API errors not covered by the above.

    This is raised for:
    - HTTP 5xx errors after the single retry (502/503).
    - Any other 4xx that is not 401, 403, 404, or 429.
    """


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class GistData:
    """Content returned by :meth:`GistsClient.get_gist`.

    Attributes:
        files: Mapping of filename to file content string.
        description: The gist's description text.
    """

    files: dict[str, str]
    description: str


@dataclass
class GistSummary:
    """Lightweight summary returned by :meth:`GistsClient.search_gists`.

    Callers are responsible for filtering the returned list; the client
    returns all gists owned by the authenticated user without any
    server-side keyword filtering.

    Attributes:
        gist_id: The GitHub gist identifier.
        description: The gist's description text.
    """

    gist_id: str
    description: str


@dataclass
class Comment:
    """A single comment on a gist.

    Attributes:
        id: The comment identifier (stringified GitHub integer id).
        body: Comment body text.
        author_login: GitHub login of the comment author.
    """

    id: str
    body: str
    author_login: str


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class GistsClient:
    """Authenticated GitHub Gists API client.

    On construction the client reads ``LORE_GITHUB_TOKEN`` from the
    environment, builds an authorised ``requests.Session``, and validates the
    token with ``GET /user``.  Any failure during this process raises
    :class:`GistAuthError` so that misconfiguration is detected at startup
    rather than at first use.

    All public methods route through the private :meth:`_request` helper which
    implements unified error handling, rate-limit detection, and a single retry
    for transient 502/503 responses.

    Attributes:
        authenticated_login: The GitHub ``login`` field returned by ``GET /user``
            at construction time.
    """

    _base_url: str = "https://api.github.com"

    def __init__(self) -> None:
        """Initialise the client and validate the GitHub token.

        Raises:
            GistAuthError: If ``LORE_GITHUB_TOKEN`` is not set or if the token
                fails the ``GET /user`` validation call.
        """
        token = os.environ.get("LORE_GITHUB_TOKEN")
        if not token:
            raise GistAuthError(
                "LORE_GITHUB_TOKEN is not set. "
                "Export a GitHub personal-access token with gist scope."
            )

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            }
        )

        resp = self._request("GET", "/user")
        self.authenticated_login: str = resp.json()["login"]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_gist(
        self, files: dict[str, str], description: str, public: bool
    ) -> str:
        """Create a new gist and return its id.

        Args:
            files: Mapping of filename to file content string.
            description: Short description for the gist.
            public: Whether the gist should be publicly visible.

        Returns:
            The newly created gist's id string.

        Raises:
            GistAPIError: On unexpected HTTP errors.
            GistAuthError: On 401/403.
            GistRateLimitError: When the rate limit is exhausted.
        """
        payload = {
            "files": {name: {"content": content} for name, content in files.items()},
            "description": description,
            "public": public,
        }
        resp = self._request("POST", "/gists", json=payload)
        return resp.json()["id"]

    def get_gist(self, gist_id: str) -> GistData:
        """Fetch a gist by id.

        Args:
            gist_id: The gist identifier.

        Returns:
            A :class:`GistData` instance with the gist's files and description.

        Raises:
            GistNotFoundError: If the gist does not exist (404).
            GistAuthError: On 401/403.
            GistRateLimitError: When the rate limit is exhausted.
            GistAPIError: On other unexpected errors.
        """
        resp = self._request("GET", f"/gists/{gist_id}")
        body = resp.json()
        files = {
            fname: fdata["content"]
            for fname, fdata in body["files"].items()
        }
        return GistData(files=files, description=body["description"])

    def update_gist(self, gist_id: str, files: dict[str, str]) -> None:
        """Update files in an existing gist.

        Only the specified files are updated; other files in the gist are left
        unchanged (standard GitHub PATCH semantics).

        Args:
            gist_id: The gist identifier.
            files: Mapping of filename to new content string.

        Raises:
            GistNotFoundError: If the gist does not exist (404).
            GistAuthError: On 401/403.
            GistRateLimitError: When the rate limit is exhausted.
            GistAPIError: On other unexpected errors.
        """
        payload = {
            "files": {name: {"content": content} for name, content in files.items()}
        }
        self._request("PATCH", f"/gists/{gist_id}", json=payload)

    def search_gists(
        self, query: str, page: int = 1, per_page: int = 100
    ) -> list[GistSummary]:
        """List all gists owned by the authenticated user.

        Uses ``GET /gists`` with pagination via ``Link`` headers, fetching
        every page until exhaustion.  The ``query`` and ``page`` parameters
        are accepted for interface compatibility but are **not** used for
        server-side filtering — callers must perform their own filtering on
        the returned list.

        Args:
            query: Ignored.  Accepted for interface compatibility only.
            page: Ignored.  Accepted for interface compatibility only.
            per_page: Number of results per API page.  Defaults to ``100``
                (the GitHub maximum).

        Returns:
            List of :class:`GistSummary` objects for every gist owned by the
            authenticated user.  Returns an empty list when the user has no
            gists.

        Raises:
            GistAuthError: On 401/403.
            GistRateLimitError: When the rate limit is exhausted.
            GistAPIError: On unexpected errors.
        """
        results: list[GistSummary] = []
        url: str | None = f"{self._base_url}/gists"
        params: dict = {"per_page": per_page}

        while url is not None:
            resp = self._session.request("GET", url, params=params)
            # Re-use the error handling logic by delegating to _request only
            # on the first call; for subsequent pages use the absolute URL
            # directly and manually check status.
            params = {}  # params already encoded in the Link-derived URL

            # Mirror _request error handling for paginated responses.
            if resp.status_code in (502, 503):
                time.sleep(1)
                resp = self._session.request("GET", url)
                if resp.status_code in (502, 503):
                    raise GistAPIError(
                        f"GitHub API returned {resp.status_code} on GET {url} after retry."
                    )

            remaining = resp.headers.get("X-RateLimit-Remaining")
            if resp.status_code == 429:
                raise GistRateLimitError("GitHub API rate limit exhausted (HTTP 429).")
            if remaining is not None and int(remaining) == 0:
                raise GistRateLimitError(
                    "GitHub API rate limit exhausted (X-RateLimit-Remaining: 0)."
                )
            if resp.status_code in (401, 403):
                raise GistAuthError(
                    f"GitHub authentication/authorisation error (HTTP {resp.status_code})."
                )
            if resp.status_code == 404:
                raise GistNotFoundError("GitHub resource not found: GET /gists")
            if resp.status_code >= 400:
                raise GistAPIError(f"GitHub API error {resp.status_code} on GET {url}.")

            for item in resp.json():
                results.append(
                    GistSummary(
                        gist_id=item["id"],
                        description=item.get("description") or "",
                    )
                )

            link_header = resp.headers.get("Link", "")
            url = _parse_next_link(link_header) if link_header else None

        return results

    def list_comments(self, gist_id: str) -> list[Comment]:
        """List all comments on a gist.

        Args:
            gist_id: The gist identifier.

        Returns:
            List of :class:`Comment` instances, in API-returned order.

        Raises:
            GistNotFoundError: If the gist does not exist (404).
            GistAuthError: On 401/403.
            GistRateLimitError: When the rate limit is exhausted.
            GistAPIError: On unexpected errors.
        """
        resp = self._request("GET", f"/gists/{gist_id}/comments")
        return [
            Comment(
                id=str(item["id"]),
                body=item["body"],
                author_login=item["user"]["login"],
            )
            for item in resp.json()
        ]

    def create_comment(self, gist_id: str, body: str) -> str:
        """Post a new comment on a gist.

        Args:
            gist_id: The gist identifier.
            body: Comment body text.

        Returns:
            The new comment's id as a string.

        Raises:
            GistNotFoundError: If the gist does not exist (404).
            GistAuthError: On 401/403.
            GistRateLimitError: When the rate limit is exhausted.
            GistAPIError: On unexpected errors.
        """
        resp = self._request(
            "POST", f"/gists/{gist_id}/comments", json={"body": body}
        )
        return str(resp.json()["id"])

    def delete_gist(self, gist_id: str) -> None:
        """Delete a gist by id.

        Args:
            gist_id: The gist identifier.

        Raises:
            GistNotFoundError: If the gist does not exist (404).
            GistAuthError: On 401/403.
            GistRateLimitError: When the rate limit is exhausted.
            GistAPIError: On unexpected errors.
        """
        self._request("DELETE", f"/gists/{gist_id}")

    def update_comment(self, gist_id: str, comment_id: str, body: str) -> None:
        """Edit an existing comment on a gist.

        Args:
            gist_id: The gist identifier.
            comment_id: The comment identifier.
            body: New comment body text.

        Raises:
            GistNotFoundError: If the gist or comment does not exist (404).
            GistAuthError: On 401/403.
            GistRateLimitError: When the rate limit is exhausted.
            GistAPIError: On unexpected errors.
        """
        self._request(
            "PATCH",
            f"/gists/{gist_id}/comments/{comment_id}",
            json={"body": body},
        )

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Execute an authenticated GitHub API request with error handling.

        Implements:
        - One automatic retry for 502/503 (transient server errors) after a
          1-second sleep.
        - Rate-limit detection via the ``X-RateLimit-Remaining`` header and
          HTTP 429 status.
        - A stderr warning when fewer than 10 API calls remain before reset.
        - Typed exception mapping for 401, 403, 404, and unexpected 4xx/5xx.

        Args:
            method: HTTP method string (``"GET"``, ``"POST"``, etc.).
            path: API path relative to the base URL (must start with ``"/``).
            **kwargs: Additional keyword arguments forwarded to
                ``requests.Session.request`` (e.g. ``json``, ``params``).

        Returns:
            The successful :class:`requests.Response` object.

        Raises:
            GistAuthError: On 401 or 403.
            GistNotFoundError: On 404.
            GistRateLimitError: On 429 or when ``X-RateLimit-Remaining == "0"``.
            GistAPIError: On 502/503 after retry, or any other 4xx/5xx.
        """
        resp = self._session.request(method, self._base_url + path, **kwargs)

        # Single retry for transient gateway errors.
        if resp.status_code in (502, 503):
            time.sleep(1)
            resp = self._session.request(method, self._base_url + path, **kwargs)
            if resp.status_code in (502, 503):
                raise GistAPIError(
                    f"GitHub API returned {resp.status_code} on {method} {path} "
                    "after retry."
                )

        # Rate-limit checks — evaluated before other error checks so that a
        # 429 response always raises GistRateLimitError regardless of body.
        remaining = resp.headers.get("X-RateLimit-Remaining")

        if resp.status_code == 429:
            raise GistRateLimitError(
                "GitHub API rate limit exhausted (HTTP 429)."
            )

        if remaining is not None:
            remaining_int = int(remaining)
            if remaining_int == 0:
                raise GistRateLimitError(
                    "GitHub API rate limit exhausted (X-RateLimit-Remaining: 0)."
                )
            if remaining_int < 10:
                reset_header = resp.headers.get("X-RateLimit-Reset", "0")
                reset_utc = datetime.utcfromtimestamp(int(reset_header)).strftime(
                    "%Y-%m-%d %H:%M:%S UTC"
                )
                print(
                    f"[lore] GitHub rate limit low: {remaining} requests remaining, "
                    f"resets at {reset_utc}",
                    file=sys.stderr,
                )

        # Map HTTP error codes to typed exceptions.
        if resp.status_code == 404:
            raise GistNotFoundError(
                f"GitHub resource not found: {method} {path}"
            )
        if resp.status_code in (401, 403):
            raise GistAuthError(
                f"GitHub authentication/authorisation error "
                f"(HTTP {resp.status_code}) on {method} {path}."
            )
        if resp.status_code >= 400:
            raise GistAPIError(
                f"GitHub API error {resp.status_code} on {method} {path}."
            )

        return resp
