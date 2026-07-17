"""Tests for lore.mcp.backends.gists.rate_concept (LORE-014).

Strategy
--------
- All GitHub API calls are mocked via ``unittest.mock.MagicMock`` — no real
  network calls are made.
- ``GistsClient`` is constructed as a MagicMock so the token-validation
  round-trip is bypassed entirely.
- ``client.authenticated_login`` is set to ``"test-user"`` on the mock so
  author-matching logic can be exercised.
- ``LORE_FREELOADER`` env var is patched with ``monkeypatch`` to avoid test
  pollution.

Test coverage areas
-------------------
- Happy path — create new rating (no existing [lore-rating] comment)
- Edit-if-exists — updates when the authenticated user already has a rating comment
- Edit-if-exists ignores other users' rating comments
- Edit-if-exists ignores non-rating comments from the authenticated user
- outcome out of range (0, 6) raises ValueError before any API call
- Negative hours_saved raises ValueError before any API call
- LORE_FREELOADER=true returns no-op, no comment calls made
- LORE_FREELOADER=false allows normal operation
- hours_saved included in comment JSON when provided
- notes included in comment JSON when provided
- hours_saved=None and notes=None: neither key appears in comment JSON
- Comment body format: starts with "[lore-rating] " followed by valid JSON
- Integration: submit → search → rate → get full round-trip (all mocked)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call

import pytest

from lore.mcp.backends.gists import (
    get_concept,
    rate_concept,
    search_concepts,
    submit_concept,
)
from lore.mcp.backends.gists_client import Comment, GistData, GistSummary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(login: str = "test-user") -> MagicMock:
    """Return a MagicMock acting as a GistsClient with a known authenticated_login.

    Provides a default ``get_gist`` return value so that ``rate_concept``'s
    internal ``get_concept`` call (which fetches updated aggregates after
    writing the rating comment) succeeds without extra per-test setup.
    """
    client = MagicMock()
    client.authenticated_login = login
    client.list_comments.return_value = []
    # Default get_gist returns a GistData parseable by get_concept so that
    # rate_concept can fetch updated aggregates after writing the comment.
    client.get_gist.return_value = _gist_data_for_concept()
    return client


def _make_comment(
    comment_id: str,
    body: str,
    author_login: str = "test-user",
) -> Comment:
    """Construct a :class:`Comment` dataclass instance."""
    return Comment(id=comment_id, body=body, author_login=author_login)


def _lore_rating_comment(
    outcome: int,
    comment_id: str = "comment-1",
    author_login: str = "test-user",
    hours_saved: float | None = None,
    notes: str | None = None,
) -> Comment:
    """Build a well-formed [lore-rating] comment."""
    payload: dict = {"outcome": outcome}
    if hours_saved is not None:
        payload["hours_saved"] = hours_saved
    if notes is not None:
        payload["notes"] = notes
    body = f"[lore-rating] {json.dumps(payload)}"
    return _make_comment(comment_id, body, author_login)


def _gist_data_for_concept(
    name: str = "Test Concept",
    tags: list[str] | None = None,
    **lore_extras,
) -> GistData:
    """Build a GistData as the gist backend would create it for submit_concept."""
    if tags is None:
        tags = ["test"]
    description = f"[agentlore-concept] {name} [{', '.join(tags)}]"
    lore_json: dict = {
        "schema_version": "1",
        "type": lore_extras.get("type", "pattern"),
        "language": lore_extras.get("language"),
        "when_to_use": lore_extras.get("when_to_use", "use whenever"),
        "dont_use_when": lore_extras.get("dont_use_when"),
        "tags": tags,
        "links": lore_extras.get("links", []),
    }
    return GistData(
        files={
            "concept.md": lore_extras.get("content", "# Content"),
            "lore.json": json.dumps(lore_json),
        },
        description=description,
    )


# ---------------------------------------------------------------------------
# TestRateConceptCreate — no existing rating comment
# ---------------------------------------------------------------------------


class TestRateConceptCreate:
    """rate_concept creates a new comment when no rating comment exists for the user."""

    CONCEPT_ID = "gist-abc"

    def test_create_comment_called_when_no_existing_rating(self):
        """create_comment is called when list_comments returns no [lore-rating] comment."""
        client = _make_client()
        client.list_comments.return_value = []

        rate_concept(client, self.CONCEPT_ID, outcome=4, session_id="sess-1")

        client.create_comment.assert_called_once()

    def test_create_comment_called_with_correct_gist_id(self):
        """create_comment receives the correct concept_id."""
        client = _make_client()
        client.list_comments.return_value = []

        rate_concept(client, self.CONCEPT_ID, outcome=4, session_id="sess-1")

        args, _ = client.create_comment.call_args
        assert args[0] == self.CONCEPT_ID

    def test_returns_created_status(self):
        """Returns {'status': 'created', 'concept_id': ..., 'avg_rating': ..., 'time_saved_avg_hours': ...} on new comment creation."""
        client = _make_client()
        client.list_comments.return_value = []

        result = rate_concept(client, self.CONCEPT_ID, outcome=3, session_id="sess-1")

        assert result["status"] == "created"
        assert result["concept_id"] == self.CONCEPT_ID
        assert "avg_rating" in result
        assert "time_saved_avg_hours" in result

    def test_update_comment_not_called_on_create(self):
        """update_comment must NOT be called when creating a new rating."""
        client = _make_client()
        client.list_comments.return_value = []

        rate_concept(client, self.CONCEPT_ID, outcome=5, session_id="sess-1")

        client.update_comment.assert_not_called()


# ---------------------------------------------------------------------------
# TestRateConceptEditIfExists — existing rating comment by same user
# ---------------------------------------------------------------------------


class TestRateConceptEditIfExists:
    """rate_concept updates an existing comment when the authenticated user already has one."""

    CONCEPT_ID = "gist-abc"

    def test_update_comment_called_when_existing_rating_found(self):
        """update_comment is called when a [lore-rating] comment from authenticated_login exists."""
        client = _make_client()
        existing = _lore_rating_comment(outcome=3, comment_id="comment-99")
        client.list_comments.return_value = [existing]

        rate_concept(client, self.CONCEPT_ID, outcome=5, session_id="sess-1")

        client.update_comment.assert_called_once()

    def test_update_comment_called_with_correct_args(self):
        """update_comment receives (concept_id, comment_id, new_body)."""
        client = _make_client()
        existing = _lore_rating_comment(outcome=3, comment_id="comment-99")
        client.list_comments.return_value = [existing]

        rate_concept(client, self.CONCEPT_ID, outcome=5, session_id="sess-1")

        args, _ = client.update_comment.call_args
        assert args[0] == self.CONCEPT_ID
        assert args[1] == "comment-99"

    def test_returns_updated_status(self):
        """Returns {'status': 'updated', 'concept_id': ..., 'avg_rating': ..., 'time_saved_avg_hours': ...} when updating."""
        client = _make_client()
        existing = _lore_rating_comment(outcome=2, comment_id="comment-77")
        client.list_comments.return_value = [existing]

        result = rate_concept(client, self.CONCEPT_ID, outcome=4, session_id="sess-1")

        assert result["status"] == "updated"
        assert result["concept_id"] == self.CONCEPT_ID
        assert "avg_rating" in result
        assert "time_saved_avg_hours" in result

    def test_create_comment_not_called_on_update(self):
        """create_comment must NOT be called when updating an existing rating."""
        client = _make_client()
        existing = _lore_rating_comment(outcome=1, comment_id="comment-10")
        client.list_comments.return_value = [existing]

        rate_concept(client, self.CONCEPT_ID, outcome=3, session_id="sess-1")

        client.create_comment.assert_not_called()

    def test_edit_if_exists_ignores_other_users_rating_comments(self):
        """A [lore-rating] comment from a different user does not trigger edit-if-exists."""
        client = _make_client(login="test-user")
        other_users_comment = _lore_rating_comment(
            outcome=2, comment_id="other-comment", author_login="other-user"
        )
        client.list_comments.return_value = [other_users_comment]

        result = rate_concept(client, self.CONCEPT_ID, outcome=4, session_id="sess-1")

        # Should create a new comment, not update the other user's
        assert result["status"] == "created"
        client.create_comment.assert_called_once()
        client.update_comment.assert_not_called()

    def test_edit_if_exists_ignores_non_rating_comments_from_same_user(self):
        """A comment from authenticated_login that is NOT a [lore-rating] comment is ignored."""
        client = _make_client(login="test-user")
        non_rating_comment = _make_comment(
            comment_id="non-rating-comment",
            body="Great concept!",
            author_login="test-user",
        )
        client.list_comments.return_value = [non_rating_comment]

        result = rate_concept(client, self.CONCEPT_ID, outcome=4, session_id="sess-1")

        assert result["status"] == "created"
        client.create_comment.assert_called_once()
        client.update_comment.assert_not_called()

    def test_edit_if_exists_matches_first_own_rating_comment(self):
        """When multiple [lore-rating] comments from the same user exist, the first one is updated."""
        client = _make_client(login="test-user")
        first_comment = _lore_rating_comment(outcome=1, comment_id="first")
        second_comment = _lore_rating_comment(outcome=2, comment_id="second")
        client.list_comments.return_value = [first_comment, second_comment]

        rate_concept(client, self.CONCEPT_ID, outcome=5, session_id="sess-1")

        args, _ = client.update_comment.call_args
        assert args[1] == "first"


# ---------------------------------------------------------------------------
# TestRateConceptValidation — input validation
# ---------------------------------------------------------------------------


class TestRateConceptValidation:
    """rate_concept validates inputs before making any API calls."""

    CONCEPT_ID = "gist-abc"

    @pytest.mark.parametrize("outcome", [0, 6, -1, 100])
    def test_outcome_out_of_range_raises_value_error(self, outcome: int):
        """outcome outside 1–5 raises ValueError."""
        client = _make_client()

        with pytest.raises(ValueError, match="outcome must be 1"):
            rate_concept(client, self.CONCEPT_ID, outcome=outcome, session_id="s")

    @pytest.mark.parametrize("outcome", [0, 6])
    def test_outcome_out_of_range_no_api_call(self, outcome: int):
        """No API call is made when outcome is out of range."""
        client = _make_client()

        with pytest.raises(ValueError):
            rate_concept(client, self.CONCEPT_ID, outcome=outcome, session_id="s")

        client.list_comments.assert_not_called()
        client.create_comment.assert_not_called()
        client.update_comment.assert_not_called()

    def test_negative_hours_saved_raises_value_error(self):
        """Negative hours_saved raises ValueError."""
        client = _make_client()

        with pytest.raises(ValueError, match="hours_saved must be non-negative"):
            rate_concept(
                client, self.CONCEPT_ID, outcome=3, session_id="s", hours_saved=-0.1
            )

    def test_negative_hours_saved_no_api_call(self):
        """No API call is made when hours_saved is negative."""
        client = _make_client()

        with pytest.raises(ValueError):
            rate_concept(
                client, self.CONCEPT_ID, outcome=3, session_id="s", hours_saved=-1.0
            )

        client.list_comments.assert_not_called()
        client.create_comment.assert_not_called()

    @pytest.mark.parametrize("outcome", [1, 2, 3, 4, 5])
    def test_all_valid_outcome_values_accepted(self, outcome: int):
        """All integer values 1–5 are accepted without raising."""
        client = _make_client()
        client.list_comments.return_value = []

        result = rate_concept(client, self.CONCEPT_ID, outcome=outcome, session_id="s")

        assert result["status"] == "created"

    def test_zero_hours_saved_is_valid(self):
        """hours_saved=0 is valid (boundary: non-negative means >= 0)."""
        client = _make_client()
        client.list_comments.return_value = []

        result = rate_concept(
            client, self.CONCEPT_ID, outcome=3, session_id="s", hours_saved=0.0
        )

        assert result["status"] == "created"


# ---------------------------------------------------------------------------
# TestRateConceptFreeloader — LORE_FREELOADER env var
# ---------------------------------------------------------------------------


class TestRateConceptFreeloader:
    """rate_concept respects the LORE_FREELOADER environment variable."""

    CONCEPT_ID = "gist-abc"

    def test_freeloader_true_returns_no_op(self, monkeypatch):
        """LORE_FREELOADER=true returns {'status': 'no-op', 'reason': 'LORE_FREELOADER=true', 'avg_rating': None, 'time_saved_avg_hours': None}."""
        monkeypatch.setenv("LORE_FREELOADER", "true")
        client = _make_client()

        result = rate_concept(client, self.CONCEPT_ID, outcome=4, session_id="s")

        assert result["status"] == "no-op"
        assert result["reason"] == "LORE_FREELOADER=true"
        assert result["avg_rating"] is None
        assert result["time_saved_avg_hours"] is None

    def test_freeloader_true_no_comment_calls(self, monkeypatch):
        """No API calls are made when LORE_FREELOADER=true."""
        monkeypatch.setenv("LORE_FREELOADER", "true")
        client = _make_client()

        rate_concept(client, self.CONCEPT_ID, outcome=4, session_id="s")

        client.list_comments.assert_not_called()
        client.create_comment.assert_not_called()
        client.update_comment.assert_not_called()

    def test_freeloader_true_case_insensitive(self, monkeypatch):
        """LORE_FREELOADER=TRUE (uppercase) also triggers no-op."""
        monkeypatch.setenv("LORE_FREELOADER", "TRUE")
        client = _make_client()

        result = rate_concept(client, self.CONCEPT_ID, outcome=4, session_id="s")

        assert result["status"] == "no-op"

    def test_freeloader_false_normal_operation(self, monkeypatch):
        """LORE_FREELOADER=false allows normal comment posting."""
        monkeypatch.setenv("LORE_FREELOADER", "false")
        client = _make_client()
        client.list_comments.return_value = []

        result = rate_concept(client, self.CONCEPT_ID, outcome=4, session_id="s")

        assert result["status"] == "created"
        client.create_comment.assert_called_once()

    def test_freeloader_not_set_normal_operation(self, monkeypatch):
        """When LORE_FREELOADER is not set, normal operation proceeds."""
        monkeypatch.delenv("LORE_FREELOADER", raising=False)
        client = _make_client()
        client.list_comments.return_value = []

        result = rate_concept(client, self.CONCEPT_ID, outcome=3, session_id="s")

        assert result["status"] == "created"

    def test_freeloader_validation_still_runs_before_env_check(self, monkeypatch):
        """Input validation (outcome range) raises ValueError even when LORE_FREELOADER=true."""
        monkeypatch.setenv("LORE_FREELOADER", "true")
        client = _make_client()

        with pytest.raises(ValueError, match="outcome must be 1"):
            rate_concept(client, self.CONCEPT_ID, outcome=0, session_id="s")


# ---------------------------------------------------------------------------
# TestRateConceptCommentBody — comment body format and payload content
# ---------------------------------------------------------------------------


class TestRateConceptCommentBody:
    """rate_concept builds the correct comment body and embeds the right JSON payload."""

    CONCEPT_ID = "gist-abc"

    def _capture_comment_body(self, client: MagicMock) -> str:
        """Return the body string passed to create_comment."""
        args, _ = client.create_comment.call_args
        return args[1]

    def test_comment_body_starts_with_lore_rating_prefix(self):
        """Comment body starts with '[lore-rating] '."""
        client = _make_client()
        client.list_comments.return_value = []

        rate_concept(client, self.CONCEPT_ID, outcome=4, session_id="s")

        body = self._capture_comment_body(client)
        assert body.startswith("[lore-rating] ")

    def test_comment_body_contains_valid_json(self):
        """The part after the prefix is valid JSON."""
        client = _make_client()
        client.list_comments.return_value = []

        rate_concept(client, self.CONCEPT_ID, outcome=4, session_id="s")

        body = self._capture_comment_body(client)
        prefix = "[lore-rating] "
        json_part = body[len(prefix):]
        parsed = json.loads(json_part)
        assert isinstance(parsed, dict)

    def test_comment_body_contains_outcome(self):
        """The comment JSON payload includes the outcome value."""
        client = _make_client()
        client.list_comments.return_value = []

        rate_concept(client, self.CONCEPT_ID, outcome=5, session_id="s")

        body = self._capture_comment_body(client)
        payload = json.loads(body[len("[lore-rating] "):])
        assert payload["outcome"] == 5

    def test_hours_saved_included_when_provided(self):
        """hours_saved appears in the comment JSON when passed."""
        client = _make_client()
        client.list_comments.return_value = []

        rate_concept(client, self.CONCEPT_ID, outcome=3, session_id="s", hours_saved=1.5)

        body = self._capture_comment_body(client)
        payload = json.loads(body[len("[lore-rating] "):])
        assert payload["hours_saved"] == pytest.approx(1.5)

    def test_notes_included_when_provided(self):
        """notes appears in the comment JSON when passed."""
        client = _make_client()
        client.list_comments.return_value = []

        rate_concept(
            client, self.CONCEPT_ID, outcome=3, session_id="s", notes="very useful"
        )

        body = self._capture_comment_body(client)
        payload = json.loads(body[len("[lore-rating] "):])
        assert payload["notes"] == "very useful"

    def test_hours_saved_none_not_in_json(self):
        """When hours_saved=None, the key is absent from the comment JSON."""
        client = _make_client()
        client.list_comments.return_value = []

        rate_concept(client, self.CONCEPT_ID, outcome=3, session_id="s", hours_saved=None)

        body = self._capture_comment_body(client)
        payload = json.loads(body[len("[lore-rating] "):])
        assert "hours_saved" not in payload

    def test_notes_none_not_in_json(self):
        """When notes=None, the key is absent from the comment JSON."""
        client = _make_client()
        client.list_comments.return_value = []

        rate_concept(client, self.CONCEPT_ID, outcome=3, session_id="s", notes=None)

        body = self._capture_comment_body(client)
        payload = json.loads(body[len("[lore-rating] "):])
        assert "notes" not in payload

    def test_both_optional_none_only_outcome_in_json(self):
        """When both hours_saved and notes are None, only 'outcome' appears in the JSON."""
        client = _make_client()
        client.list_comments.return_value = []

        rate_concept(
            client, self.CONCEPT_ID, outcome=2, session_id="s",
            hours_saved=None, notes=None,
        )

        body = self._capture_comment_body(client)
        payload = json.loads(body[len("[lore-rating] "):])
        assert set(payload.keys()) == {"outcome"}

    def test_update_body_contains_new_outcome(self):
        """When updating, the new comment body reflects the new outcome."""
        client = _make_client()
        existing = _lore_rating_comment(outcome=1, comment_id="c1")
        client.list_comments.return_value = [existing]

        rate_concept(client, self.CONCEPT_ID, outcome=5, session_id="s")

        _, update_kwargs = client.update_comment.call_args
        # update_comment(concept_id, comment_id, body) — body is the 3rd positional arg
        update_args, _ = client.update_comment.call_args
        body = update_args[2]
        payload = json.loads(body[len("[lore-rating] "):])
        assert payload["outcome"] == 5


# ---------------------------------------------------------------------------
# TestRateConceptIntegration — full submit → search → rate → get flow
# ---------------------------------------------------------------------------


class TestRateConceptIntegration:
    """Integration test: submit_concept → search_concepts → rate_concept → get_concept.

    All GitHub API calls are mocked.  This verifies the full round-trip
    without real network access.
    """

    GIST_ID = "gist-int-abc"
    CONCEPT_NAME = "Integration Test Pattern"
    OUTCOME = 4
    HOURS_SAVED = 2.0

    def _build_gist_data(self) -> GistData:
        """Build the GistData that get_gist would return for this concept."""
        return _gist_data_for_concept(
            name=self.CONCEPT_NAME,
            tags=["integration", "test"],
            when_to_use="Use in integration tests",
        )

    def test_integration_submit_search_rate_get(self):
        """Full round-trip: submit → search → rate → get returns avg_rating."""
        client = _make_client(login="int-test-user")

        # --- Step 1: submit_concept ---
        client.create_gist.return_value = self.GIST_ID

        submit_result = submit_concept(
            client,
            name=self.CONCEPT_NAME,
            type="pattern",
            content="# Integration Test Pattern\nUse this in tests.",
            when_to_use="Use in integration tests",
            tags=["integration", "test"],
        )

        assert submit_result["concept_id"] == self.GIST_ID
        client.create_gist.assert_called_once()

        # --- Step 2: search_concepts → finds the concept ---
        gist_data = self._build_gist_data()
        client.search_gists.return_value = [
            GistSummary(gist_id=self.GIST_ID, description=gist_data.description)
        ]
        client.get_gist.return_value = gist_data
        client.list_comments.return_value = []

        search_result = search_concepts(client, problem="integration test")

        assert len(search_result["results"]) == 1
        assert search_result["results"][0]["concept_id"] == self.GIST_ID

        # --- Step 3: rate_concept → posts comment ---
        # Reset list_comments to empty before rating.
        client.list_comments.return_value = []

        rate_result = rate_concept(
            client,
            self.GIST_ID,
            outcome=self.OUTCOME,
            session_id="int-session",
            hours_saved=self.HOURS_SAVED,
        )

        assert rate_result["status"] == "created"
        assert rate_result["concept_id"] == self.GIST_ID
        assert "avg_rating" in rate_result
        assert "time_saved_avg_hours" in rate_result

        # Capture the comment body that was created.
        create_args, _ = client.create_comment.call_args
        created_comment_body = create_args[1]

        # --- Step 4: get_concept → returns avg_rating matching the posted rating ---
        # Simulate the comment being present on the gist now.
        posted_comment = Comment(
            id="new-comment-id",
            body=created_comment_body,
            author_login="int-test-user",
        )
        client.list_comments.return_value = [posted_comment]

        get_result = get_concept(client, self.GIST_ID)

        assert get_result["concept_id"] == self.GIST_ID
        assert get_result["avg_rating"] == pytest.approx(float(self.OUTCOME))
        assert get_result["avg_hours_saved"] == pytest.approx(self.HOURS_SAVED)
