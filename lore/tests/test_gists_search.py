"""Tests for gists.search_concepts (LORE-012).

Strategy
--------
- All GitHub API calls are mocked via ``unittest.mock.MagicMock`` — no real
  network calls are made.
- ``GistsClient`` is constructed as a MagicMock so the token-validation
  round-trip is bypassed entirely.
- ``search_concepts`` now calls ``client.search_gists("")`` once and receives
  the full gist list; filtering and relevance ranking happen locally.
- Tests exercise: marker filtering, type/language/rating filters, relevance
  ranking, deduplication, limit enforcement, and error propagation.

Test coverage areas
-------------------
Happy path
    - Returns matching concepts as a list under ``"results"``
    - Full concept dict shape is preserved (delegates to get_concept)
    - Only gists with [agentlore-concept] in description are considered

Deduplication
    - Duplicate gist_id in the list returned by search_gists is included once

Type filter
    - Concepts with a non-matching type field are skipped

Language filter
    - Concepts with a non-matching language field are skipped

Rating filter
    - Concepts with avg_rating below min_rating are excluded
    - Unrated concepts (no comments, avg_rating=None) are included regardless

Limit enforcement
    - search_concepts stops processing candidates once limit results collected

Relevance ranking
    - Candidates whose description matches more problem words rank first

Empty results
    - search_gists returns empty list → ``{"results": []}``
    - search_gists returns only non-concept gists → ``{"results": []}``

GistRateLimitError on search_gists
    - Raises RuntimeError wrapping the rate limit message

GistRateLimitError on get_concept (via get_gist inside get_concept)
    - Raises RuntimeError when rate limit hit fetching concept detail
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call

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
    description = f"[agentlore-concept] {name} [{', '.join(tags)}]"
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


def _concept_summary(gist_id: str, name: str = "A Concept") -> GistSummary:
    """Build a GistSummary for a lore concept gist (has the marker)."""
    return GistSummary(
        gist_id=gist_id,
        description=f"[agentlore-concept] {name} []",
    )


def _non_concept_summary(gist_id: str) -> GistSummary:
    """Build a GistSummary for a gist that is NOT a lore concept."""
    return GistSummary(
        gist_id=gist_id,
        description="Some random gist without the marker",
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
        client.search_gists.return_value = [_concept_summary("g1")]
        client.get_gist.return_value = _make_gist_data("WAL Mode", ["sqlite"])
        client.list_comments.return_value = []

        result = search_concepts(client, problem="sqlite concurrency")

        assert "results" in result
        assert isinstance(result["results"], list)

    def test_returns_full_concept_dicts(self):
        """Each result contains the full concept dict fields from get_concept."""
        client = _make_client()
        client.search_gists.return_value = [_concept_summary("g1")]
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
        summaries = [_concept_summary(f"g{i}") for i in range(5)]
        client.search_gists.return_value = summaries
        client.get_gist.return_value = _make_gist_data("Pattern", ["tag"])
        client.list_comments.return_value = []

        result = search_concepts(client, problem="pattern", limit=3)

        assert len(result["results"]) == 3

    def test_non_concept_gists_ignored(self):
        """Gists without the [agentlore-concept] marker are filtered out."""
        client = _make_client()
        client.search_gists.return_value = [
            _non_concept_summary("x1"),
            _concept_summary("g1"),
            _non_concept_summary("x2"),
        ]
        client.get_gist.return_value = _make_gist_data("A Concept", [])
        client.list_comments.return_value = []

        result = search_concepts(client, problem="test")

        assert len(result["results"]) == 1
        assert result["results"][0]["concept_id"] == "g1"

    def test_search_gists_called_once_with_empty_query(self):
        """search_gists is called exactly once, with an empty string query."""
        client = _make_client()
        client.search_gists.return_value = []

        search_concepts(client, problem="anything")

        client.search_gists.assert_called_once_with("")


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

    def test_only_non_concept_gists_returns_empty_results(self):
        """When all gists lack the marker, result is {'results': []}."""
        client = _make_client()
        client.search_gists.return_value = [
            _non_concept_summary("x1"),
            _non_concept_summary("x2"),
        ]

        result = search_concepts(client, problem="anything")

        assert result == {"results": []}

    def test_all_filtered_out_returns_empty_results(self):
        """When all candidates are filtered by type, result is {'results': []}."""
        client = _make_client()
        client.search_gists.return_value = [_concept_summary("g1")]
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
    """Deduplication: same gist_id in the list is only included once."""

    def test_duplicate_gist_id_included_once(self):
        """A gist_id appearing twice in the list is included exactly once."""
        client = _make_client()

        # search_gists now returns a flat list — duplicate g1 in the list.
        summaries = [_concept_summary("g1"), _concept_summary("g1"), _concept_summary("g2")]
        client.search_gists.return_value = summaries
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
        client.search_gists.return_value = [_concept_summary("g1"), _concept_summary("g2")]

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
        client.search_gists.return_value = [_concept_summary("g1"), _concept_summary("g2")]

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
        client.search_gists.return_value = [_concept_summary("g1"), _concept_summary("g2")]

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
        client.search_gists.return_value = [_concept_summary("g1"), _concept_summary("g2")]

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
        client.search_gists.return_value = [_concept_summary("g1"), _concept_summary("g2")]

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
        client.search_gists.return_value = [_concept_summary("g1")]
        client.get_gist.return_value = _make_gist_data("Unrated Concept", [])
        client.list_comments.return_value = []  # no ratings → avg_rating=None

        result = search_concepts(client, problem="test", min_rating=5.0)

        assert len(result["results"]) == 1

    def test_concept_meeting_min_rating_included(self):
        """A concept with avg_rating >= min_rating is included."""
        client = _make_client()
        client.search_gists.return_value = [_concept_summary("g1")]
        client.get_gist.return_value = _make_gist_data("Good Concept", [])
        client.list_comments.return_value = [_rating_comment(outcome=4)]

        result = search_concepts(client, problem="test", min_rating=3.0)

        assert len(result["results"]) == 1

    def test_concept_at_exact_min_rating_boundary_included(self):
        """A concept with avg_rating exactly equal to min_rating is included."""
        client = _make_client()
        client.search_gists.return_value = [_concept_summary("g1")]
        client.get_gist.return_value = _make_gist_data("Boundary Concept", [])
        client.list_comments.return_value = [_rating_comment(outcome=3)]

        result = search_concepts(client, problem="test", min_rating=3.0)

        assert len(result["results"]) == 1


# ---------------------------------------------------------------------------
# Limit enforcement
# ---------------------------------------------------------------------------


class TestLimitEnforcement:
    """Limit is respected — once satisfied, remaining candidates are skipped."""

    def test_stops_at_limit(self):
        """Returns exactly limit results from a longer candidate list."""
        client = _make_client()
        summaries = [_concept_summary(f"g{i}") for i in range(10)]
        client.search_gists.return_value = summaries
        client.get_gist.return_value = _make_gist_data("Pattern", [])
        client.list_comments.return_value = []

        result = search_concepts(client, problem="test", limit=3)

        assert len(result["results"]) == 3

    def test_fewer_candidates_than_limit_returns_all(self):
        """When fewer candidates exist than limit, all passing ones are returned."""
        client = _make_client()
        client.search_gists.return_value = [_concept_summary("g1"), _concept_summary("g2")]
        client.get_gist.return_value = _make_gist_data("Pattern", [])
        client.list_comments.return_value = []

        result = search_concepts(client, problem="test", limit=10)

        assert len(result["results"]) == 2

    def test_get_gist_not_called_beyond_limit(self):
        """get_gist is not called for candidates beyond the limit."""
        client = _make_client()
        summaries = [_concept_summary(f"g{i}") for i in range(10)]
        client.search_gists.return_value = summaries
        client.get_gist.return_value = _make_gist_data("Pattern", [])
        client.list_comments.return_value = []

        search_concepts(client, problem="test", limit=2)

        # With limit=2 and all candidates passing, get_gist should only be
        # called for the first 2 candidates.
        assert client.get_gist.call_count == 2


# ---------------------------------------------------------------------------
# Relevance ranking
# ---------------------------------------------------------------------------


class TestRelevanceRanking:
    """Candidates are ranked by keyword overlap with problem before detail fetch."""

    def test_higher_relevance_returned_first(self):
        """Gist whose description matches more problem words ranks first."""
        client = _make_client()

        # g1 description matches 1 word ("sqlite"); g2 matches 2 ("sqlite" + "wal")
        s1 = GistSummary(gist_id="g1", description="[agentlore-concept] sqlite pattern []")
        s2 = GistSummary(gist_id="g2", description="[agentlore-concept] sqlite wal mode []")
        client.search_gists.return_value = [s1, s2]

        def get_gist_side_effect(gist_id):
            if gist_id == "g1":
                return _make_gist_data("SQLite Pattern", ["sqlite"])
            return _make_gist_data("SQLite WAL Mode", ["sqlite", "wal"])

        client.get_gist.side_effect = get_gist_side_effect
        client.list_comments.return_value = []

        result = search_concepts(client, problem="sqlite wal", limit=2)

        assert len(result["results"]) == 2
        # g2 should be first (2 matching words vs 1)
        assert result["results"][0]["concept_id"] == "g2"
        assert result["results"][1]["concept_id"] == "g1"

    def test_zero_relevance_candidates_still_returned(self):
        """Candidates with no matching words are still returned when no better option."""
        client = _make_client()
        client.search_gists.return_value = [_concept_summary("g1", "Unrelated Topic")]
        client.get_gist.return_value = _make_gist_data("Unrelated Topic", [])
        client.list_comments.return_value = []

        result = search_concepts(client, problem="completelydifferentword", limit=1)

        assert len(result["results"]) == 1


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
        client.search_gists.return_value = [_concept_summary("g1")]
        client.get_gist.side_effect = GistRateLimitError("exhausted")

        with pytest.raises(RuntimeError, match="rate limit"):
            search_concepts(client, problem="test")

    def test_runtime_error_message_contains_original_error(self):
        """RuntimeError message includes the original GistRateLimitError text."""
        client = _make_client()
        client.search_gists.side_effect = GistRateLimitError("GitHub API rate limit exhausted (HTTP 429).")

        with pytest.raises(RuntimeError, match="GitHub API rate limit exhausted"):
            search_concepts(client, problem="test")
