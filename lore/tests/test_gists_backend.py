"""Tests for lore.mcp.backends.gists (LORE-011).

Strategy
--------
- All GitHub API calls are mocked via ``unittest.mock.MagicMock`` — no real
  network calls are made.
- ``GistsClient`` is constructed as a MagicMock so the token-validation
  round-trip is bypassed entirely.
- Tests cover: ``submit_concept``, ``get_concept``, and
  ``_parse_name_from_description``.

Test coverage areas
-------------------
submit_concept
    - Description format encoding name + tags
    - Files dict contains both ``concept.md`` and ``lore.json``
    - ``lore.json`` structure: schema_version, type, language=None, tags, links=[]
    - Return shape: concept_id, name, source_url

get_concept
    - Happy path: all fields present, links resolved (depth 1), ratings aggregated
    - ``avg_hours_saved`` computed from comments with hours_saved field
    - Not found: returns ``None``
    - Unavailable linked concept: ``{"gist_id": "...", "status": "unavailable"}``
    - Max 10 links: only first 10 resolved even when 12 exist in lore_json
    - Malformed rating comment: skipped without crash; valid ratings still computed
    - No ratings: avg_rating and avg_hours_saved are both None

_parse_name_from_description
    - Full format with tags parsed correctly
    - Name without tags preserved
    - Malformed input (no prefix) returned verbatim
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call

import pytest

from lore.mcp.backends.gists import (
    _parse_name_from_description,
    get_concept,
    submit_concept,
)
from lore.mcp.backends.gists_client import Comment, GistData, GistNotFoundError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client() -> MagicMock:
    """Return a MagicMock acting as a GistsClient."""
    return MagicMock()


def _make_gist_data(name: str, tags: list[str], **lore_extras) -> GistData:
    """Build a GistData as the gist backend would create it."""
    description = f"[agentlore-concept] {name} [{', '.join(tags)}]"
    lore_json: dict = {
        "schema_version": "1",
        "type": lore_extras.get("type", "pattern"),
        "language": lore_extras.get("language"),
        "when_to_use": lore_extras.get("when_to_use", "when you need it"),
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
# _parse_name_from_description
# ---------------------------------------------------------------------------


class TestParseNameFromDescription:
    """Unit tests for the private helper ``_parse_name_from_description``."""

    def test_full_format_with_tags(self):
        """Standard format with name and tags parses correctly."""
        result = _parse_name_from_description("[agentlore-concept] My Pattern [tag1, tag2]")
        assert result == "My Pattern"

    def test_name_without_trailing_tags(self):
        """A description with no tag suffix returns the bare name."""
        result = _parse_name_from_description("[agentlore-concept] Simple Name")
        assert result == "Simple Name"

    def test_malformed_no_prefix_returns_full_string(self):
        """A description without the [agentlore-concept] prefix is returned verbatim."""
        raw = "Some random description without prefix"
        result = _parse_name_from_description(raw)
        assert result == raw

    def test_empty_string_returns_empty(self):
        """Empty string returns empty string (no prefix → verbatim)."""
        assert _parse_name_from_description("") == ""

    def test_name_with_brackets_in_name_uses_last_bracket(self):
        """When the name itself contains '[', the LAST ' [' is stripped."""
        result = _parse_name_from_description("[agentlore-concept] Name [note] [t1, t2]")
        assert result == "Name [note]"


# ---------------------------------------------------------------------------
# submit_concept
# ---------------------------------------------------------------------------


class TestSubmitConcept:
    """Tests for ``submit_concept``."""

    _BASE_ARGS = dict(
        name="WAL Mode",
        type="pattern",
        content="Enable WAL mode for concurrent writes.",
        when_to_use="When you need concurrent SQLite access.",
        tags=["sqlite", "concurrency"],
    )

    def test_description_format_with_tags(self):
        """Gist description encodes name and tags in the expected format."""
        client = _make_client()
        client.create_gist.return_value = "gist-abc"

        submit_concept(client, **self._BASE_ARGS)

        _, kwargs = client.create_gist.call_args
        assert kwargs["description"] == "[agentlore-concept] WAL Mode [sqlite, concurrency]"

    def test_files_contains_concept_md_and_lore_json(self):
        """Created files dict must have exactly concept.md and lore.json keys."""
        client = _make_client()
        client.create_gist.return_value = "gist-abc"

        submit_concept(client, **self._BASE_ARGS)

        _, kwargs = client.create_gist.call_args
        files = kwargs["files"]
        assert "concept.md" in files
        assert "lore.json" in files

    def test_concept_md_starts_with_content(self):
        """concept.md starts with the ``content`` argument and ends with attribution footer."""
        client = _make_client()
        client.create_gist.return_value = "gist-abc"

        submit_concept(client, **self._BASE_ARGS)

        _, kwargs = client.create_gist.call_args
        concept_md = kwargs["files"]["concept.md"]
        assert concept_md.startswith("Enable WAL mode for concurrent writes.")
        assert "mcp-server-lore" in concept_md
        assert "github.com/Magublafix/AgentLore" in concept_md

    def test_lore_json_structure_schema_version(self):
        """lore.json has schema_version='1'."""
        client = _make_client()
        client.create_gist.return_value = "gist-abc"

        submit_concept(client, **self._BASE_ARGS)

        _, kwargs = client.create_gist.call_args
        lore_data = json.loads(kwargs["files"]["lore.json"])
        assert lore_data["schema_version"] == "1"

    def test_lore_json_language_is_none_when_not_provided(self):
        """lore.json language is null when not provided."""
        client = _make_client()
        client.create_gist.return_value = "gist-abc"

        submit_concept(client, **self._BASE_ARGS)

        _, kwargs = client.create_gist.call_args
        lore_data = json.loads(kwargs["files"]["lore.json"])
        assert lore_data["language"] is None

    def test_lore_json_language_stored_when_provided(self):
        """lore.json language reflects the provided value."""
        client = _make_client()
        client.create_gist.return_value = "gist-abc"

        submit_concept(client, **self._BASE_ARGS, language="python")

        _, kwargs = client.create_gist.call_args
        lore_data = json.loads(kwargs["files"]["lore.json"])
        assert lore_data["language"] == "python"

    def test_lore_json_dont_use_when_is_none_when_not_provided(self):
        """lore.json dont_use_when is null when not provided."""
        client = _make_client()
        client.create_gist.return_value = "gist-abc"

        submit_concept(client, **self._BASE_ARGS)

        _, kwargs = client.create_gist.call_args
        lore_data = json.loads(kwargs["files"]["lore.json"])
        assert lore_data["dont_use_when"] is None

    def test_lore_json_links_defaults_to_empty_list(self):
        """lore.json links is [] when not provided."""
        client = _make_client()
        client.create_gist.return_value = "gist-abc"

        submit_concept(client, **self._BASE_ARGS)

        _, kwargs = client.create_gist.call_args
        lore_data = json.loads(kwargs["files"]["lore.json"])
        assert lore_data["links"] == []

    def test_lore_json_tags_stored(self):
        """lore.json tags reflect the provided list."""
        client = _make_client()
        client.create_gist.return_value = "gist-abc"

        submit_concept(client, **self._BASE_ARGS)

        _, kwargs = client.create_gist.call_args
        lore_data = json.loads(kwargs["files"]["lore.json"])
        assert lore_data["tags"] == ["sqlite", "concurrency"]

    def test_lore_json_type_stored(self):
        """lore.json type reflects the provided value."""
        client = _make_client()
        client.create_gist.return_value = "gist-abc"

        submit_concept(client, **self._BASE_ARGS)

        _, kwargs = client.create_gist.call_args
        lore_data = json.loads(kwargs["files"]["lore.json"])
        assert lore_data["type"] == "pattern"

    def test_return_shape_concept_id(self):
        """Return dict has concept_id equal to the gist id."""
        client = _make_client()
        client.create_gist.return_value = "gist-xyz"

        result = submit_concept(client, **self._BASE_ARGS)

        assert result["concept_id"] == "gist-xyz"

    def test_return_shape_name(self):
        """Return dict has name equal to the submitted name."""
        client = _make_client()
        client.create_gist.return_value = "gist-xyz"

        result = submit_concept(client, **self._BASE_ARGS)

        assert result["name"] == "WAL Mode"

    def test_return_shape_source_url(self):
        """Return dict has source_url pointing to the public gist URL."""
        client = _make_client()
        client.create_gist.return_value = "gist-xyz"

        result = submit_concept(client, **self._BASE_ARGS)

        assert result["source_url"] == "https://gist.github.com/gist-xyz"

    def test_gist_is_created_as_public(self):
        """The gist is always created as public=True."""
        client = _make_client()
        client.create_gist.return_value = "gist-abc"

        submit_concept(client, **self._BASE_ARGS)

        _, kwargs = client.create_gist.call_args
        assert kwargs["public"] is True

    def test_links_stored_when_provided(self):
        """lore.json links reflect provided link list."""
        client = _make_client()
        client.create_gist.return_value = "gist-abc"
        links = [{"gist_id": "other-gist", "rel": "uses"}]

        submit_concept(client, **self._BASE_ARGS, links=links)

        _, kwargs = client.create_gist.call_args
        lore_data = json.loads(kwargs["files"]["lore.json"])
        assert lore_data["links"] == links


# ---------------------------------------------------------------------------
# get_concept
# ---------------------------------------------------------------------------


class TestGetConcept:
    """Tests for ``get_concept``."""

    def test_happy_path_all_fields_present(self):
        """Happy path: all expected fields are present in the result."""
        client = _make_client()
        gist_data = _make_gist_data(
            name="WAL Mode",
            tags=["sqlite"],
            type="pattern",
            language="python",
            when_to_use="Use for concurrent writes.",
            dont_use_when="Avoid on read-only workloads.",
            content="# WAL Mode\nEnable it.",
        )
        client.get_gist.return_value = gist_data
        client.list_comments.return_value = []

        result = get_concept(client, "gist-001")

        assert result["concept_id"] == "gist-001"
        assert result["name"] == "WAL Mode"
        assert result["type"] == "pattern"
        assert result["language"] == "python"
        assert result["content"] == "# WAL Mode\nEnable it."
        assert result["when_to_use"] == "Use for concurrent writes."
        assert result["dont_use_when"] == "Avoid on read-only workloads."
        assert result["tags"] == ["sqlite"]
        assert result["source_url"] == "https://gist.github.com/gist-001"
        assert result["links"] == []

    def test_name_parsed_from_description(self):
        """Name is parsed from the gist description using _parse_name_from_description."""
        client = _make_client()
        gist_data = _make_gist_data(name="My Pattern", tags=["t1", "t2"])
        client.get_gist.return_value = gist_data
        client.list_comments.return_value = []

        result = get_concept(client, "gist-001")

        assert result["name"] == "My Pattern"

    def test_not_found_returns_none(self):
        """GistNotFoundError returns None (uniform not-found contract)."""
        client = _make_client()
        client.get_gist.side_effect = GistNotFoundError("not found")

        result = get_concept(client, "missing-gist")

        assert result is None

    def test_links_resolved_at_depth_1(self):
        """Linked concepts are resolved inline (depth 1) — not just IDs."""
        client = _make_client()
        linked_gist = _make_gist_data(
            name="Linked Concept",
            tags=["link-tag"],
            when_to_use="Use this linked concept.",
        )

        primary_link = {"gist_id": "linked-gist-id", "rel": "uses"}
        primary_gist = _make_gist_data(
            name="Primary",
            tags=["p"],
            links=[primary_link],
        )

        def get_gist_side_effect(gist_id):
            if gist_id == "gist-main":
                return primary_gist
            if gist_id == "linked-gist-id":
                return linked_gist
            raise GistNotFoundError("not found")

        client.get_gist.side_effect = get_gist_side_effect
        client.list_comments.return_value = []

        result = get_concept(client, "gist-main")

        assert len(result["links"]) == 1
        link = result["links"][0]
        assert link["name"] == "Linked Concept"
        assert link["when_to_use"] == "Use this linked concept."
        assert link["rel"] == "uses"

    def test_unavailable_linked_concept_has_status_field(self):
        """A linked gist that raises an error is represented with status=unavailable."""
        client = _make_client()
        primary_gist = _make_gist_data(
            name="Primary",
            tags=[],
            links=[{"gist_id": "broken-link", "rel": "uses"}],
        )

        def get_gist_side_effect(gist_id):
            if gist_id == "gist-main":
                return primary_gist
            raise GistNotFoundError("not found")

        client.get_gist.side_effect = get_gist_side_effect
        client.list_comments.return_value = []

        result = get_concept(client, "gist-main")

        assert len(result["links"]) == 1
        assert result["links"][0] == {"gist_id": "broken-link", "status": "unavailable"}

    def test_max_10_links_resolved(self):
        """Only the first 10 links are resolved even when lore_json has 12."""
        client = _make_client()

        linked_gist = _make_gist_data(name="Linked", tags=[])

        all_links = [{"gist_id": f"linked-{i}", "rel": "uses"} for i in range(12)]
        primary_gist = _make_gist_data(name="Primary", tags=[], links=all_links)

        def get_gist_side_effect(gist_id):
            if gist_id == "gist-main":
                return primary_gist
            return linked_gist

        client.get_gist.side_effect = get_gist_side_effect
        client.list_comments.return_value = []

        result = get_concept(client, "gist-main")

        assert len(result["links"]) == 10

    def test_avg_rating_computed_from_comments(self):
        """avg_rating is the mean of outcome values from rating comments."""
        client = _make_client()
        gist_data = _make_gist_data(name="X", tags=[])
        client.get_gist.return_value = gist_data
        client.list_comments.return_value = [
            _rating_comment(outcome=4),
            _rating_comment(outcome=2),
        ]

        result = get_concept(client, "gist-001")

        assert result["avg_rating"] == pytest.approx(3.0)

    def test_avg_hours_saved_computed_from_comments_with_field(self):
        """avg_hours_saved is the mean of hours_saved across comments that provide it."""
        client = _make_client()
        gist_data = _make_gist_data(name="X", tags=[])
        client.get_gist.return_value = gist_data
        client.list_comments.return_value = [
            _rating_comment(outcome=5, hours_saved=2.0),
            _rating_comment(outcome=3, hours_saved=4.0),
            _rating_comment(outcome=4),  # no hours_saved
        ]

        result = get_concept(client, "gist-001")

        assert result["avg_hours_saved"] == pytest.approx(3.0)

    def test_no_ratings_gives_none_averages(self):
        """When there are no rating comments, both averages are None."""
        client = _make_client()
        gist_data = _make_gist_data(name="X", tags=[])
        client.get_gist.return_value = gist_data
        client.list_comments.return_value = []

        result = get_concept(client, "gist-001")

        assert result["avg_rating"] is None
        assert result["avg_hours_saved"] is None

    def test_malformed_rating_comment_skipped(self):
        """A malformed rating comment is skipped; valid ones are still computed."""
        client = _make_client()
        gist_data = _make_gist_data(name="X", tags=[])
        client.get_gist.return_value = gist_data
        client.list_comments.return_value = [
            Comment(id="1", body="[lore-rating]{bad json{{", author_login="agent"),
            _rating_comment(outcome=5),
        ]

        result = get_concept(client, "gist-001")

        # The malformed comment is skipped; the valid one gives avg_rating=5.0
        assert result["avg_rating"] == pytest.approx(5.0)

    def test_non_rating_comments_ignored(self):
        """Comments not starting with [lore-rating] are ignored for rating aggregation."""
        client = _make_client()
        gist_data = _make_gist_data(name="X", tags=[])
        client.get_gist.return_value = gist_data
        client.list_comments.return_value = [
            Comment(id="1", body="This is a regular comment.", author_login="user"),
            _rating_comment(outcome=3),
        ]

        result = get_concept(client, "gist-001")

        assert result["avg_rating"] == pytest.approx(3.0)

    def test_avg_hours_saved_none_when_no_comment_has_hours(self):
        """avg_hours_saved is None when no rating comment includes hours_saved."""
        client = _make_client()
        gist_data = _make_gist_data(name="X", tags=[])
        client.get_gist.return_value = gist_data
        client.list_comments.return_value = [
            _rating_comment(outcome=4),
            _rating_comment(outcome=2),
        ]

        result = get_concept(client, "gist-001")

        assert result["avg_hours_saved"] is None

    def test_single_rating_gives_correct_avg(self):
        """A single rating comment results in avg_rating equal to that rating."""
        client = _make_client()
        gist_data = _make_gist_data(name="X", tags=[])
        client.get_gist.return_value = gist_data
        client.list_comments.return_value = [_rating_comment(outcome=5, hours_saved=1.0)]

        result = get_concept(client, "gist-001")

        assert result["avg_rating"] == pytest.approx(5.0)
        assert result["avg_hours_saved"] == pytest.approx(1.0)
