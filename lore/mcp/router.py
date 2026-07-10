"""Backend router for Lore MCP tools.

Routes all MCP tool calls to the configured backend based on the
``LORE_BACKEND`` environment variable.

Supported backends:

- ``selfhosted``: delegates via httpx to the selfhosted FastAPI service.
- ``gists``: delegates to the GitHub Gists backend (LORE-010/011).

The router is instantiated once at server start-up; backends are validated
lazily (inside each method) so that an unknown backend value raises
:class:`ValueError` only when a tool is actually invoked, not at import time.

GistsClient is also lazy — it is not constructed until the first gists-backend
call, allowing the server module to import without a valid ``LORE_GITHUB_TOKEN``
when the gists backend is selected.
"""

from __future__ import annotations

from typing import Optional

import httpx

from lore.mcp.backends import gists as gists_backend
from lore.mcp.backends.gists_client import GistsClient


class BackendRouter:
    """Routes MCP tool calls to the configured backend.

    The router delegates each MCP operation to either the selfhosted FastAPI
    service (via httpx) or the GitHub Gists backend module.

    Args:
        backend: Backend name.  One of ``"selfhosted"``, ``"gists"``.
        selfhosted_url: Base URL for the selfhosted FastAPI service.
            Only used when ``backend == "selfhosted"``.

    Raises:
        ValueError: On any method call if ``backend`` is not a known value.
    """

    def __init__(self, backend: str, selfhosted_url: str) -> None:
        """Initialise the router.

        Args:
            backend: Backend selector string (e.g. ``"selfhosted"``).
            selfhosted_url: Base URL of the selfhosted FastAPI service.
        """
        self._backend = backend
        self._selfhosted_url = selfhosted_url
        self.__gists_client: Optional[GistsClient] = None

    # ------------------------------------------------------------------
    # Private helpers — selfhosted
    # ------------------------------------------------------------------

    def _client(self) -> httpx.Client:
        """Return a short-lived synchronous HTTP client pointed at the selfhosted API.

        Returns:
            A configured :class:`httpx.Client` with a 30-second timeout.
        """
        return httpx.Client(base_url=self._selfhosted_url, timeout=30.0)

    def _raise_for_error(self, response: httpx.Response) -> None:
        """Raise a :class:`RuntimeError` with a human-readable message on HTTP errors.

        Args:
            response: The :class:`httpx.Response` to inspect.

        Raises:
            RuntimeError: If the response status code indicates an error (4xx or 5xx).
        """
        if response.is_error:
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            raise RuntimeError(
                f"Selfhosted API error {response.status_code}: {detail}"
            )

    # ------------------------------------------------------------------
    # Private helpers — gists
    # ------------------------------------------------------------------

    @property
    def _gists_client(self) -> GistsClient:
        """Lazily initialise :class:`GistsClient` on first access.

        Returns:
            An authenticated :class:`GistsClient` instance.

        Raises:
            GistAuthError: If ``LORE_GITHUB_TOKEN`` is not set or invalid.
        """
        if self.__gists_client is None:
            self.__gists_client = GistsClient()
        return self.__gists_client

    # ------------------------------------------------------------------
    # Routed tool methods
    # ------------------------------------------------------------------

    def search_concepts(
        self,
        problem: str,
        type: Optional[str] = None,
        language: Optional[str] = None,
        limit: int = 3,
        min_rating: float = 2.0,
        session_id: Optional[str] = None,
    ) -> dict:
        """Route ``search_concepts`` to the configured backend.

        Args:
            problem: Natural language description of the problem to search for.
            type: Optional concept type filter.
            language: Optional programming language filter.
            limit: Maximum number of results to return.
            min_rating: Minimum average rating threshold.
            session_id: Optional session identifier for analytics logging.

        Returns:
            A dict with a ``results`` key containing matching concept records.

        Raises:
            ValueError: For unknown backend values.
            RuntimeError: On selfhosted HTTP errors or gists rate limit.
        """
        if self._backend == "selfhosted":
            payload: dict = {
                "problem": problem,
                "limit": limit,
                "min_rating": min_rating,
            }
            if type is not None:
                payload["type"] = type
            if language is not None:
                payload["language"] = language

            headers: dict = {}
            if session_id:
                headers["X-Session-ID"] = session_id

            with self._client() as client:
                response = client.post("/v1/concepts/search", json=payload, headers=headers)
                self._raise_for_error(response)
                return response.json()

        if self._backend == "gists":
            return gists_backend.search_concepts(
                self._gists_client,
                problem,
                type=type,
                language=language,
                limit=limit,
                min_rating=min_rating,
            )

        raise ValueError(f"Unknown LORE_BACKEND: {self._backend!r}")

    def get_concept(self, concept_id: str) -> dict:
        """Route ``get_concept`` to the configured backend.

        Args:
            concept_id: The concept identifier (UUID for selfhosted, gist id for gists).

        Returns:
            The full concept record as a dict including a ``links`` list.

        Raises:
            NotImplementedError: Not applicable — both backends implement this.
            ValueError: For unknown backend values.
            RuntimeError: On selfhosted HTTP errors.
        """
        if self._backend == "selfhosted":
            with self._client() as client:
                response = client.get(f"/v1/concepts/{concept_id}")
                self._raise_for_error(response)
                return response.json()

        if self._backend == "gists":
            return gists_backend.get_concept(self._gists_client, concept_id)

        raise ValueError(f"Unknown LORE_BACKEND: {self._backend!r}")

    def submit_concept(
        self,
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
        """Route ``submit_concept`` to the configured backend.

        Args:
            name: Short human-readable name for the concept.
            type: Concept type string.
            content: Markdown body describing the concept.
            when_to_use: Natural-language description of ideal use context.
            tags: List of tag strings.
            language: Programming language context.  Optional.
            dont_use_when: Known anti-cases / counter-indications.  Optional.
            source_url: Origin URL.  Optional.
            links: Optional list of initial link dicts.

        Returns:
            On success: a dict with at least ``concept_id`` and ``name``.
            On semantic duplicate (selfhosted only): the 409 response body.

        Raises:
            ValueError: On 422 from selfhosted (backend scanner rejection),
                or for unknown backend values.
            RuntimeError: On unexpected selfhosted HTTP errors.
        """
        if self._backend == "selfhosted":
            payload: dict = {
                "name": name,
                "type": type,
                "content": content,
                "when_to_use": when_to_use,
                "tags": tags,
                "links": links or [],
            }
            if language is not None:
                payload["language"] = language
            if dont_use_when is not None:
                payload["dont_use_when"] = dont_use_when
            if source_url is not None:
                payload["source_url"] = source_url

            with self._client() as client:
                response = client.post("/v1/concepts", json=payload)
                if response.status_code == 409:
                    # Semantic duplicate — return structured response so callers
                    # can track the existing_concept_id for rating.
                    return response.json()
                if response.status_code == 422:
                    data = response.json()
                    raise ValueError(
                        f"Submission rejected by backend scanner: "
                        f"{data.get('error', 'unknown')} "
                        f"— violations: {data.get('matches', [])}"
                    )
                self._raise_for_error(response)
                return response.json()

        if self._backend == "gists":
            return gists_backend.submit_concept(
                self._gists_client,
                name=name,
                type=type,
                content=content,
                when_to_use=when_to_use,
                tags=tags,
                language=language,
                dont_use_when=dont_use_when,
                source_url=source_url,
                links=links,
            )

        raise ValueError(f"Unknown LORE_BACKEND: {self._backend!r}")

    def link_concepts(
        self,
        from_id: str,
        to_id: str,
        rel: str,
        label: str,
    ) -> dict:
        """Route ``link_concepts`` to the configured backend.

        Args:
            from_id: Identifier of the source concept.
            to_id: Identifier of the target concept.
            rel: Relationship type string.
            label: Human-readable edge description.

        Returns:
            A dict with a ``link_id`` key confirming the created link.

        Raises:
            NotImplementedError: For the ``gists`` backend (not yet implemented).
            ValueError: For unknown backend values.
            RuntimeError: On selfhosted HTTP errors.
        """
        if self._backend == "selfhosted":
            payload = {
                "from_id": from_id,
                "to_id": to_id,
                "rel": rel,
                "label": label,
            }
            with self._client() as client:
                response = client.post("/v1/links", json=payload)
                self._raise_for_error(response)
                return response.json()

        if self._backend == "gists":
            return gists_backend.link_concepts(self._gists_client, from_id, to_id, rel, label)

        raise ValueError(f"Unknown LORE_BACKEND: {self._backend!r}")

    def rate_concept(
        self,
        concept_id: str,
        outcome: int,
        session_id: str,
        hours_saved: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """Route ``rate_concept`` to the configured backend.

        Args:
            concept_id: Identifier of the concept to rate.
            outcome: Integer score 1–5.
            session_id: The current agent session identifier.
            hours_saved: Estimated hours saved.  Optional.
            notes: Free-text notes.  Optional.

        Returns:
            A dict with updated aggregate rating statistics.

        Raises:
            NotImplementedError: For the ``gists`` backend (not yet implemented).
            ValueError: For unknown backend values.
            RuntimeError: On selfhosted HTTP errors.
        """
        if self._backend == "selfhosted":
            payload: dict = {"outcome": outcome, "session_id": session_id}
            if hours_saved is not None:
                payload["hours_saved"] = hours_saved
            if notes is not None:
                payload["notes"] = notes

            with self._client() as client:
                response = client.post(f"/v1/concepts/{concept_id}/rate", json=payload)
                self._raise_for_error(response)
                return response.json()

        if self._backend == "gists":
            return gists_backend.rate_concept(
                self._gists_client,
                concept_id,
                outcome,
                session_id,
                hours_saved=hours_saved,
                notes=notes,
            )

        raise ValueError(f"Unknown LORE_BACKEND: {self._backend!r}")
