"""Tests for gists.search_concepts (LORE-012).

Strategy
--------
- All GitHub API calls are mocked via ``unittest.mock.MagicMock`` — no real
  network calls are made.
- ``GistsClient`` is constructed as a MagicMock so the token-validation
  round-trip is bypassed entirely.
- Tests exercise the full search loop: pagination, deduplication, client-side
  filtering, early stop, and error propagation.

Test coverage areas
-------------------
Happy path
    - Returns matching concepts as a list under ``"results"``
    - Full concept dict shape is preserved (delegates to get_concept)

Deduplication
    - Same gist_id on page 1 and page 2 is included exactly once

Type filter
    - Concepts with a non-matching type field are skipped

Language filter
    - Concepts with a non-matching language field are skipped

Rating filter
    - Concepts with avg_rating below min_rating are excluded
    - Unrated concepts (no comments, avg_rating=None) are included regardless

Early stop
    - Stops fetching more pages once limit passing candidates are collected
    - Does not fetch gist detail for candidates beyond limit

Page exhaustion
    - If 3 pages return fewer than limit passing candidates, returns all that matched

Empty results
    - search_gists returns empty list → ``{"results": []}``

GistRateLimitError on search_gists
    - Raises RuntimeError wrapping the rate limit message

GistRateLimitError on get_concept (via get_gist inside get_concept)
    - Raises RuntimeError when rate limit hit fetching concept detail

search_gists pagination params
    - page and per_page are forwarded correctly to search_gists
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest

from lore.mcp.backends.gists import search_concepts
from lore.mcp.backends.gists_client import (
    Comment,
    GistData,
    GistNotFoundError,
    GistRateLimitError,
    GistSummary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client() -> MagicMock:
    """Return a MagicMock acting as a GistsClient."""
    return MagicMock()


def _make_gist_data(
    name: str,
    tags: list[str],
    type: str = "pattern",
    language: str | None = None,
    when_to_use: str = "when you need it",
    content: str = "# Content",
    links: list[dict] | None = None,
) -> GistData:
    """Build a GistData as the gist backend would create it."""
    description = f"[lore-concept] {name} [{', '.join(tags)}]"
    lore_json: dict = {
        "schema_version": "1",
        "type": type,
        "language": language,
        "when_to_use": when_to_use,
        "dont_use_when": None,
        "tags": tags,
        "links": links if links is not None else [],
    }
    return GistData(
        files={
            "concept.md": content,
            "lore.json": json.dumps(lore_json),
        },
        description=description,
    )


def _summary(gist_id: str, name: str = "A Concept") -> GistSummary:
    """Build a GistSummary as returned by search_gists."""
    return GistSummary(
        gist_id=gist_id,
        description=f"[lore-concept] {name} []",
    )


def _rating_comment(outcome: int, hours_saved: float | None = None) -> Comment:
    """Build a rating comment as it would appear on a gist."""
    payload: dict = {"outcome": outcome}
    if hours_saved is not None:
        payload["hours_saved"] = hours_saved
    return Comment(
        id="1",
        body=f"[lore-rating]{json.dumps(payload)}",
        author_login="agent",
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestSearchConceptsHappyPath:
    """Basic happy-path tests for search_concepts."""

    def test_returns_results_key(self):
        """Return value is a dict with a 'results' key."""
        client = _make_client()
        client.search_gists.return_value = [_summary("g1")]
        client.get_gist.return_value = _make_gist_data("WAL Mode", ["sqlite"])
        client.list_comments.return_value = []

        result = search_concepts(client, problem="sqlite concurrency")

        assert "results" in result
        assert isinstance(result["results"], list)

    def test_returns_full_concept_dicts(self):
        """Each result contains the full concept dict fields from get_concept."""
        client = _make_client()
        client.search_gists.return_value = [_summary("g1")]
        client.get_gist.return_value = _make_gist_data(
            "WAL Mode", ["sqlite"], type="pattern", language="python"
        )
        client.list_comments.return_value = []

        result = search_concepts(client, problem="sqlite")

        assert len(result["results"]) == 1
        concept = result["results"][0]
        assert concept["concept_id"] == "g1"
        assert concept["name"] == "WAL Mode"
        assert concept["type"] == "pattern"
        assert concept["language"] == "python"
        assert "when_to_use" in concept
        assert "links" in concept
        assert "avg_rating" in concept

    def test_multiple_results_up_to_limit(self):
        """Returns up to limit results when multiple gists match."""
        client = _make_client()
        summaries = [_summary(f"g{i}") for i in range(5)]
        client.search_gists.return_value = summaries
        client.get_gist.return_value = _make_gist_data("Pattern", ["tag"])
        client.list_comments.return_value = []

        result = search_concepts(client, problem="pattern", limit=3)

        assert len(result["results"]) == 3


# ---------------------------------------------------------------------------
# Empty results
# ---------------------------------------------------------------------------


class TestSearchConceptsEmptyResults:
    """Tests for empty / no-match scenarios."""

    def test_empty_search_returns_empty_results(self):
        """When search_gists returns no items, result is {'results': []}."""
        client = _make_client()
        client.search_gists.return_value = []

        result = search_concepts(client, problem="nothing matches")

        assert result == {"results": []}

    def test_all_filtered_out_returns_empty_results(self):
        """When all candidates are filtered by type, result is {'results': []}."""
        client = _make_client()
        client.search_gists.return_value = [_summary("g1")]
        client.get_gist.return_value = _make_gist_data(
            "Wrong Type", [], type="tool"
        )
        client.list_comments.return_value = []

        result = search_concepts(client, problem="anything", type="pattern")

        assert result == {"results": []}


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    """Deduplication: same gist_id across pages is only included once."""

    def test_duplicate_gist_id_across_pages_included_once(self):
        """A gist_id appearing on both page 1 and page 2 is included exactly once."""
        client = _make_client()

        # Page 1 returns 30 items (full page) with g1 as the first.
        # Page 2 returns g1 again plus g2.
        page1 = [_summary("g1")] + [_summary(f"x{i}") for i in range(29)]
        page2 = [_summary("g1"), _summary("g2")]

        call_count = [0]

        def search_side_effect(query, page=1, per_page=30):
            if page == 1:
                return page1
            return page2

        client.search_gists.side_effect = search_side_effect
        client.get_gist.return_value = _make_gist_data("Pattern", [])
        client.list_comments.return_value = []

        result = search_concepts(client, problem="test", limit=50)

        # Count how many times g1 appears in results.
        g1_count = sum(1 for c in result["results"] if c["concept_id"] == "g1")
        assert g1_count == 1


# ---------------------------------------------------------------------------
# Type filter
# ---------------------------------------------------------------------------


class TestTypeFilter:
    """Client-side type filter tests."""

    def test_wrong_type_skipped(self):
        """A gist with type != requested type is not included."""
        client = _make_client()
        client.search_gists.return_value = [_summary("g1"), _summary("g2")]

        def get_gist_side_effect(gist_id):
            if gist_id == "g1":
                return _make_gist_data("Tool Concept", [], type="tool")
            return _make_gist_data("Pattern Concept", [], type="pattern")

        client.get_gist.side_effect = get_gist_side_effect
        client.list_comments.return_value = []

        result = search_concepts(client, problem="test", type="pattern")

        assert len(result["results"]) == 1
        assert result["results"][0]["concept_id"] == "g2"

    def test_no_type_filter_includes_all_types(self):
        """When type=None, concepts of any type are included."""
        client = _make_client()
        client.search_gists.return_value = [_summary("g1"), _summary("g2")]

        def get_gist_side_effect(gist_id):
            if gist_id == "g1":
                return _make_gist_data("Tool", [], type="tool")
            return _make_gist_data("Pattern", [], type="pattern")

        client.get_gist.side_effect = get_gist_side_effect
        client.list_comments.return_value = []

        result = search_concepts(client, problem="test", type=None, limit=5)

        assert len(result["results"]) == 2


# ---------------------------------------------------------------------------
# Language filter
# ---------------------------------------------------------------------------


class TestLanguageFilter:
    """Client-side language filter tests."""

    def test_wrong_language_skipped(self):
        """A gist with language != requested language is not included."""
        client = _make_client()
        client.search_gists.return_value = [_summary("g1"), _summary("g2")]

        def get_gist_side_effect(gist_id):
            if gist_id == "g1":
                return _make_gist_data("JS Pattern", [], language="javascript")
            return _make_gist_data("Python Pattern", [], language="python")

        client.get_gist.side_effect = get_gist_side_effect
        client.list_comments.return_value = []

        result = search_concepts(client, problem="test", language="python")

        assert len(result["results"]) == 1
        assert result["results"][0]["concept_id"] == "g2"

    def test_no_language_filter_includes_all_languages(self):
        """When language=None, concepts with any language value are included."""
        client = _make_client()
        client.search_gists.return_value = [_summary("g1"), _summary("g2")]

        def get_gist_side_effect(gist_id):
            if gist_id == "g1":
                return _make_gist_data("JS", [], language="javascript")
            return _make_gist_data("Py", [], language="python")

        client.get_gist.side_effect = get_gist_side_effect
        client.list_comments.return_value = []

        result = search_concepts(client, problem="test", language=None, limit=5)

        assert len(result["results"]) == 2


# ---------------------------------------------------------------------------
# Rating filter
# ---------------------------------------------------------------------------


class TestRatingFilter:
    """Client-side rating filter tests."""

    def test_below_min_rating_excluded(self):
        """A gist with avg_rating below min_rating is excluded."""
        client = _make_client()
        client.search_gists.return_value = [_summary("g1"), _summary("g2")]

        def get_gist_side_effect(gist_id):
            return _make_gist_data("Concept", [])

        client.get_gist.side_effect = get_gist_side_effect

        def list_comments_side_effect(gist_id):
            if gist_id == "g1":
                # avg_rating = 1.0, below min_rating=2.0
                return [_rating_comment(outcome=1)]
            # g2 has no ratings → avg_rating=None → included
            return []

        client.list_comments.side_effect = list_comments_side_effect

        result = search_concepts(client, problem="test", min_rating=2.0)

        # g1 excluded (rating 1.0 < 2.0); g2 included (unrated)
        assert len(result["results"]) == 1
        assert result["results"][0]["concept_id"] == "g2"

    def test_unrated_concept_included_regardless_of_min_rating(self):
        """An unrated concept (avg_rating=None) passes the rating filter."""
        client = _make_client()
        client.search_gists.return_value = [_summary("g1")]
        client.get_gist.return_value = _make_gist_data("Unrated Concept", [])
        client.list_comments.return_value = []  # no ratings → avg_rating=None

        result = search_concepts(client, problem="test", min_rating=5.0)

        assert len(result["results"]) == 1

    def test_concept_meeting_min_rating_included(self):
        """A concept with avg_rating >= min_rating is included."""
        client = _make_client()
        client.search_gists.return_value = [_summary("g1")]
        client.get_gist.return_value = _make_gist_data("Good Concept", [])
        client.list_comments.return_value = [_rating_comment(outcome=4)]

        result = search_concepts(client, problem="test", min_rating=3.0)

        assert len(result["results"]) == 1

    def test_concept_at_exact_min_rating_boundary_included(self):
        """A concept with avg_rating exactly equal to min_rating is included."""
        client = _make_client()
        client.search_gists.return_value = [_summary("g1")]
        client.get_gist.return_value = _make_gist_data("Boundary Concept", [])
        client.list_comments.return_value = [_rating_comment(outcome=3)]

        result = search_concepts(client, problem="test", min_rating=3.0)

        assert len(result["results"]) == 1


# ---------------------------------------------------------------------------
# Early stop / pagination
# ---------------------------------------------------------------------------


class TestPagination:
    """Pagination: early stop when limit satisfied; max 3 pages."""

    def test_stops_at_limit_before_fetching_next_page(self):
        """Once limit candidates pass filters, no more pages are fetched."""
        client = _make_client()

        page1 = [_summary(f"g{i}") for i in range(30)]  # full page
        page2 = [_summary(f"h{i}") for i in range(30)]

        def search_side_effect(query, page=1, per_page=30):
            if page == 1:
                return page1
            return page2

        client.search_gists.side_effect = search_side_effect
        client.get_gist.return_value = _make_gist_data("Pattern", [])
        client.list_comments.return_value = []

        search_concepts(client, problem="test", limit=3)

        # With 30 items on page 1 and limit=3, page 2 should never be fetched.
        page_numbers = [
            call_args.kwargs.get("page", call_args.args[1] if len(call_args.args) > 1 else 1)
            for call_args in client.search_gists.call_args_list
        ]
        assert 2 not in page_numbers, (
            "Page 2 was fetched even though limit was satisfied on page 1"
        )

    def test_max_3_pages_fetched(self):
        """At most 3 pages are fetched even if limit is not reached."""
        client = _make_client()

        # Every page returns 30 items but all fail the type filter.
        full_page = [_summary(f"g{i}") for i in range(30)]
        client.search_gists.return_value = full_page
        client.get_gist.return_value = _make_gist_data("Tool", [], type="tool")
        client.list_comments.return_value = []

        result = search_concepts(client, problem="test", type="pattern", limit=5)

        assert client.search_gists.call_count <= 3
        assert result == {"results": []}

    def test_last_page_stops_pagination_early(self):
        """A page with fewer than per_page results ends pagination."""
        client = _make_client()

        # Page 1 returns 5 items (< 30) → last page.
        page1 = [_summary(f"g{i}") for i in range(5)]
        client.search_gists.return_value = page1
        client.get_gist.return_value = _make_gist_data("Pattern", [])
        client.list_comments.return_value = []

        search_concepts(client, problem="test", limit=10)

        # Only 1 page should have been fetched.
        assert client.search_gists.call_count == 1

    def test_page_exhaustion_returns_partial_results(self):
        """If 3 pages produce fewer than limit passing candidates, returns all that matched."""
        client = _make_client()

        # Page 1 and 2 return full pages; page 3 returns 2 items (last page).
        def search_side_effect(query, page=1, per_page=30):
            if page in (1, 2):
                return [_summary(f"p{page}g{i}") for i in range(30)]
            return [_summary("p3g0"), _summary("p3g1")]

        client.search_gists.side_effect = search_side_effect
        client.get_gist.return_value = _make_gist_data("Pattern", [])
        client.list_comments.return_value = []

        result = search_concepts(client, problem="test", limit=100)

        # 30 + 30 + 2 = 62 candidates, all should pass.
        assert len(result["results"]) == 62

    def test_search_gists_called_with_page_and_per_page(self):
        """search_gists is called with correct page and per_page kwargs."""
        client = _make_client()

        def search_side_effect(query, page=1, per_page=30):
            # Return 0 items so we stop immediately after page 1.
            return []

        client.search_gists.side_effect = search_side_effect

        search_concepts(client, problem="test")

        client.search_gists.assert_called_once()
        call_kwargs = client.search_gists.call_args
        # Keyword or positional — check both.
        args, kwargs = call_kwargs
        assert kwargs.get("page", args[1] if len(args) > 1 else None) == 1
        assert kwargs.get("per_page", args[2] if len(args) > 2 else None) == 30


# ---------------------------------------------------------------------------
# GistRateLimitError propagation
# ---------------------------------------------------------------------------


class TestRateLimitError:
    """GistRateLimitError must propagate as RuntimeError."""

    def test_rate_limit_on_search_gists_raises_runtime_error(self):
        """GistRateLimitError from search_gists is wrapped as RuntimeError."""
        client = _make_client()
        client.search_gists.side_effect = GistRateLimitError("rate limit hit")

        with pytest.raises(RuntimeError, match="rate limit"):
            search_concepts(client, problem="test")

    def test_rate_limit_on_get_gist_raises_runtime_error(self):
        """GistRateLimitError from get_gist (inside get_concept) propagates as RuntimeError.

        Note: get_concept catches GistNotFoundError but not GistRateLimitError,
        so a GistRateLimitError raised by client.get_gist propagates up and is
        caught and re-raised by search_concepts.
        """
        client = _make_client()
        client.search_gists.return_value = [_summary("g1")]
        client.get_gist.side_effect = GistRateLimitError("exhausted")

        with pytest.raises(RuntimeError, match="rate limit"):
            search_concepts(client, problem="test")

    def test_runtime_error_message_contains_original_error(self):
        """RuntimeError message includes the original GistRateLimitError text."""
        client = _make_client()
        client.search_gists.side_effect = GistRateLimitError("GitHub API rate limit exhausted (HTTP 429).")

        with pytest.raises(RuntimeError, match="GitHub API rate limit exhausted"):
            search_concepts(client, problem="test")


# ---------------------------------------------------------------------------
# Query construction
# ---------------------------------------------------------------------------


class TestQueryConstruction:
    """The search query is constructed correctly from the problem argument."""

    def test_query_includes_lore_concept_marker_and_problem(self):
        """search_gists is called with '[lore-concept] <problem>' as the query."""
        client = _make_client()
        client.search_gists.return_value = []

        search_concepts(client, problem="sqlite WAL mode")

        args, kwargs = client.search_gists.call_args
        query = args[0] if args else kwargs.get("query", "")
        assert "[lore-concept]" in query
        assert "sqlite WAL mode" in query

    def test_problem_is_appended_after_marker(self):
        """The problem text appears after the [lore-concept] marker in the query."""
        client = _make_client()
        client.search_gists.return_value = []

        search_concepts(client, problem="my specific problem")

        args, kwargs = client.search_gists.call_args
        query = args[0] if args else kwargs.get("query", "")
        assert query == "[lore-concept] my specific problem"
