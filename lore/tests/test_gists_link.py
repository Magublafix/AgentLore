"""Tests for lore.mcp.backends.gists.link_concepts (LORE-011).

Strategy
--------
- All GitHub API calls are mocked via ``unittest.mock.MagicMock`` — no real
  network calls are made.
- ``GistsClient`` is constructed as a MagicMock so the token-validation
  round-trip is bypassed entirely.
- ``client.get_gist`` is wired as a ``side_effect`` function that returns
  different ``GistData`` instances depending on whether the argument is
  ``to_id`` or ``from_id``.

Test coverage areas
-------------------
- Happy path: link created, update_gist called once with correct args
- Link entry appears in the updated lore.json passed to update_gist
- Idempotency: same (to_id, rel) pair → already_exists, update_gist not called
- Idempotency only fires on exact (to_id, rel) match: same to_id, different rel → creates
- Invalid rel raises ValueError before any network call
- to_id description missing [lore-concept] → ValueError containing to_id
- to_id GistNotFoundError propagates
- from_id GistNotFoundError propagates (to_id valid)
- Max 20 links exceeded → max_links_exceeded dict, update_gist not called
- Exactly 19 links → link created successfully
- label=None stored as null in lore.json
- label with value stored correctly in lore.json
- All five valid rel values accepted (parametrized)
- link_id format: "<from_id>:<to_id>:<rel>"
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call

import pytest

from lore.mcp.backends.gists import link_concepts
from lore.mcp.backends.gists_client import GistData, GistNotFoundError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client() -> MagicMock:
    """Return a MagicMock acting as a GistsClient."""
    return MagicMock()


def _make_gist_data(name: str, tags: list[str], **lore_extras) -> GistData:
    """Build a GistData as the gist backend would create it."""
    description = f"[lore-concept] {name} [{', '.join(tags)}]"
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
        files={"concept.md": lore_extras.get("content", "# Content"), "lore.json": json.dumps(lore_json)},
        description=description,
    )


def _make_non_lore_gist() -> GistData:
    """Return a GistData whose description does NOT contain [lore-concept]."""
    return GistData(
        files={"README.md": "# Not a lore concept"},
        description="Some random public gist",
    )


def _client_with_gists(from_gist: GistData, to_gist: GistData, from_id: str, to_id: str) -> MagicMock:
    """Wire a mock client so get_gist returns the right GistData per id."""
    client = _make_client()

    def _get_gist(gist_id: str) -> GistData:
        if gist_id == to_id:
            return to_gist
        if gist_id == from_id:
            return from_gist
        raise GistNotFoundError(f"gist {gist_id!r} not found")

    client.get_gist.side_effect = _get_gist
    return client


# ---------------------------------------------------------------------------
# TestLinkConcepts
# ---------------------------------------------------------------------------


class TestLinkConcepts:
    """Tests for ``link_concepts`` in the gists backend."""

    # Fixed identifiers used across most tests.
    FROM_ID = "from-gist-abc"
    TO_ID = "to-gist-xyz"

    def _standard_client(
        self,
        from_links: list[dict] | None = None,
        to_description_marker: str = "[lore-concept]",
    ) -> MagicMock:
        """Return a wired mock client for the standard (from_id, to_id) scenario."""
        to_gist = GistData(
            files={"concept.md": "# Target"},
            description=f"{to_description_marker} Target Concept [t1]",
        )
        from_gist = _make_gist_data(
            name="Source Concept",
            tags=["s1"],
            links=from_links if from_links is not None else [],
        )
        return _client_with_gists(from_gist, to_gist, self.FROM_ID, self.TO_ID)

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    def test_happy_path_returns_created_status(self):
        """Happy path: link created returns status='created'."""
        client = self._standard_client()

        result = link_concepts(client, self.FROM_ID, self.TO_ID, "uses")

        assert result["status"] == "created"

    def test_happy_path_update_gist_called_once(self):
        """update_gist is called exactly once on the from_id gist."""
        client = self._standard_client()

        link_concepts(client, self.FROM_ID, self.TO_ID, "uses")

        client.update_gist.assert_called_once()
        call_args = client.update_gist.call_args
        assert call_args[0][0] == self.FROM_ID

    def test_happy_path_link_id_format(self):
        """Returned link_id is '<from_id>:<to_id>:<rel>'."""
        client = self._standard_client()

        result = link_concepts(client, self.FROM_ID, self.TO_ID, "uses")

        assert result["link_id"] == f"{self.FROM_ID}:{self.TO_ID}:uses"

    def test_link_appears_in_updated_lore_json(self):
        """The lore.json passed to update_gist contains the new link entry."""
        client = self._standard_client()

        link_concepts(client, self.FROM_ID, self.TO_ID, "uses", label="depends on")

        call_args = client.update_gist.call_args
        files_dict: dict = call_args[0][1]
        lore_json = json.loads(files_dict["lore.json"])

        links = lore_json["links"]
        assert len(links) == 1
        assert links[0]["gist_id"] == self.TO_ID
        assert links[0]["rel"] == "uses"
        assert links[0]["label"] == "depends on"

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    def test_idempotency_same_pair_returns_already_exists(self):
        """Same (to_id, rel) pair already in links → already_exists, no update."""
        existing_links = [{"gist_id": self.TO_ID, "rel": "uses", "label": None}]
        client = self._standard_client(from_links=existing_links)

        result = link_concepts(client, self.FROM_ID, self.TO_ID, "uses")

        assert result == {"link_id": None, "status": "already_exists"}

    def test_idempotency_does_not_call_update_gist(self):
        """update_gist must NOT be called when the link already exists."""
        existing_links = [{"gist_id": self.TO_ID, "rel": "uses", "label": None}]
        client = self._standard_client(from_links=existing_links)

        link_concepts(client, self.FROM_ID, self.TO_ID, "uses")

        client.update_gist.assert_not_called()

    def test_idempotency_same_to_id_different_rel_creates_link(self):
        """Same to_id but different rel does NOT trigger idempotency — creates a new link."""
        existing_links = [{"gist_id": self.TO_ID, "rel": "uses", "label": None}]
        client = self._standard_client(from_links=existing_links)

        result = link_concepts(client, self.FROM_ID, self.TO_ID, "extends")

        assert result["status"] == "created"
        client.update_gist.assert_called_once()

    def test_idempotency_different_to_id_same_rel_creates_link(self):
        """Same rel but different to_id does NOT trigger idempotency."""
        other_to_id = "other-gist-999"
        existing_links = [{"gist_id": other_to_id, "rel": "uses", "label": None}]
        client = self._standard_client(from_links=existing_links)

        result = link_concepts(client, self.FROM_ID, self.TO_ID, "uses")

        assert result["status"] == "created"

    # ------------------------------------------------------------------
    # Invalid rel — must reject before any network call
    # ------------------------------------------------------------------

    def test_invalid_rel_raises_value_error(self):
        """An unrecognised rel raises ValueError."""
        client = self._standard_client()

        with pytest.raises(ValueError, match="invalid_rel"):
            link_concepts(client, self.FROM_ID, self.TO_ID, "invalid_rel")

    def test_invalid_rel_error_message_names_rel(self):
        """ValueError message for invalid rel contains the bad rel value."""
        client = self._standard_client()

        with pytest.raises(ValueError, match="bad_rel"):
            link_concepts(client, self.FROM_ID, self.TO_ID, "bad_rel")

    def test_invalid_rel_get_gist_not_called(self):
        """get_gist must NOT be called when rel is invalid."""
        client = self._standard_client()

        with pytest.raises(ValueError):
            link_concepts(client, self.FROM_ID, self.TO_ID, "not_a_rel")

        client.get_gist.assert_not_called()

    # ------------------------------------------------------------------
    # to_id validation
    # ------------------------------------------------------------------

    def test_to_id_not_lore_concept_raises_value_error(self):
        """to_id description missing [lore-concept] → ValueError."""
        client = self._standard_client(to_description_marker="NOT_LORE")

        with pytest.raises(ValueError, match=self.TO_ID):
            link_concepts(client, self.FROM_ID, self.TO_ID, "uses")

    def test_to_id_gist_not_found_propagates(self):
        """GistNotFoundError from client.get_gist(to_id) propagates unmodified."""
        client = _make_client()
        client.get_gist.side_effect = GistNotFoundError("to gist missing")

        with pytest.raises(GistNotFoundError):
            link_concepts(client, self.FROM_ID, self.TO_ID, "uses")

    def test_to_id_gist_not_found_checked_first(self):
        """to_id is fetched before from_id — GistNotFoundError on to_id propagates
        even when from_id exists."""
        # get_gist always raises, so to_id is checked first (call order matters)
        client = _make_client()
        client.get_gist.side_effect = GistNotFoundError("not found")

        with pytest.raises(GistNotFoundError):
            link_concepts(client, self.FROM_ID, self.TO_ID, "uses")

        # Only one get_gist call should have been made (for to_id)
        assert client.get_gist.call_count == 1
        assert client.get_gist.call_args[0][0] == self.TO_ID

    # ------------------------------------------------------------------
    # from_id validation
    # ------------------------------------------------------------------

    def test_from_id_gist_not_found_propagates(self):
        """GistNotFoundError from client.get_gist(from_id) propagates unmodified."""
        to_gist = GistData(
            files={"concept.md": "# Target"},
            description="[lore-concept] Target [t1]",
        )

        def _get_gist(gist_id: str) -> GistData:
            if gist_id == self.TO_ID:
                return to_gist
            raise GistNotFoundError(f"from gist {gist_id!r} not found")

        client = _make_client()
        client.get_gist.side_effect = _get_gist

        with pytest.raises(GistNotFoundError, match="from gist"):
            link_concepts(client, self.FROM_ID, self.TO_ID, "uses")

    # ------------------------------------------------------------------
    # Max links guard
    # ------------------------------------------------------------------

    def test_max_20_links_returns_max_links_exceeded(self):
        """Source gist with 20 existing links returns max_links_exceeded dict."""
        twenty_links = [{"gist_id": f"other-{i}", "rel": "uses", "label": None} for i in range(20)]
        client = self._standard_client(from_links=twenty_links)

        result = link_concepts(client, self.FROM_ID, self.TO_ID, "uses")

        assert result["code"] == "max_links_exceeded"
        assert "error" in result

    def test_max_20_links_update_gist_not_called(self):
        """update_gist must NOT be called when max links is exceeded."""
        twenty_links = [{"gist_id": f"other-{i}", "rel": "uses", "label": None} for i in range(20)]
        client = self._standard_client(from_links=twenty_links)

        link_concepts(client, self.FROM_ID, self.TO_ID, "uses")

        client.update_gist.assert_not_called()

    def test_exactly_19_links_allows_one_more(self):
        """A source gist with exactly 19 links can accept one more — creates successfully."""
        nineteen_links = [{"gist_id": f"other-{i}", "rel": "uses", "label": None} for i in range(19)]
        client = self._standard_client(from_links=nineteen_links)

        result = link_concepts(client, self.FROM_ID, self.TO_ID, "uses")

        assert result["status"] == "created"
        client.update_gist.assert_called_once()

    def test_exactly_19_links_updated_lore_json_has_20_entries(self):
        """After adding a link to a 19-link source, the updated lore.json has 20 links."""
        nineteen_links = [{"gist_id": f"other-{i}", "rel": "uses", "label": None} for i in range(19)]
        client = self._standard_client(from_links=nineteen_links)

        link_concepts(client, self.FROM_ID, self.TO_ID, "uses")

        call_args = client.update_gist.call_args
        files_dict: dict = call_args[0][1]
        lore_json = json.loads(files_dict["lore.json"])
        assert len(lore_json["links"]) == 20

    # ------------------------------------------------------------------
    # label handling
    # ------------------------------------------------------------------

    def test_label_none_stored_as_null(self):
        """When label=None (default), the link entry in lore.json has 'label': null."""
        client = self._standard_client()

        link_concepts(client, self.FROM_ID, self.TO_ID, "uses", label=None)

        call_args = client.update_gist.call_args
        files_dict: dict = call_args[0][1]
        lore_json = json.loads(files_dict["lore.json"])

        assert lore_json["links"][0]["label"] is None

    def test_label_with_value_stored_correctly(self):
        """When label='my label', the link entry in lore.json has that label value."""
        client = self._standard_client()

        link_concepts(client, self.FROM_ID, self.TO_ID, "uses", label="my label")

        call_args = client.update_gist.call_args
        files_dict: dict = call_args[0][1]
        lore_json = json.loads(files_dict["lore.json"])

        assert lore_json["links"][0]["label"] == "my label"

    def test_label_default_is_none(self):
        """Calling link_concepts without label stores null in the link entry."""
        client = self._standard_client()

        # No label argument — tests the default parameter value
        link_concepts(client, self.FROM_ID, self.TO_ID, "uses")

        call_args = client.update_gist.call_args
        files_dict: dict = call_args[0][1]
        lore_json = json.loads(files_dict["lore.json"])

        assert lore_json["links"][0]["label"] is None

    # ------------------------------------------------------------------
    # All valid rel values accepted
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("rel", ["uses", "tested_by", "extends", "alternative_to", "requires"])
    def test_all_valid_rel_values_accepted(self, rel: str):
        """Every valid rel value produces a 'created' result without raising."""
        client = self._standard_client()

        result = link_concepts(client, self.FROM_ID, self.TO_ID, rel)

        assert result["status"] == "created"

    @pytest.mark.parametrize("rel", ["uses", "tested_by", "extends", "alternative_to", "requires"])
    def test_link_id_includes_rel(self, rel: str):
        """link_id embeds the rel correctly for every valid value."""
        client = self._standard_client()

        result = link_concepts(client, self.FROM_ID, self.TO_ID, rel)

        assert result["link_id"] == f"{self.FROM_ID}:{self.TO_ID}:{rel}"

    # ------------------------------------------------------------------
    # Existing links are preserved after write-back
    # ------------------------------------------------------------------

    def test_existing_links_preserved_after_new_link_added(self):
        """Pre-existing links in lore.json are preserved in the write-back payload."""
        existing_link = {"gist_id": "pre-existing-gist", "rel": "requires", "label": "prereq"}
        client = self._standard_client(from_links=[existing_link])

        link_concepts(client, self.FROM_ID, self.TO_ID, "uses")

        call_args = client.update_gist.call_args
        files_dict: dict = call_args[0][1]
        lore_json = json.loads(files_dict["lore.json"])

        assert len(lore_json["links"]) == 2
        assert lore_json["links"][0] == existing_link

    # ------------------------------------------------------------------
    # update_gist receives the correct file key
    # ------------------------------------------------------------------

    def test_update_gist_updates_lore_json_file(self):
        """The files dict passed to update_gist has the 'lore.json' key."""
        client = self._standard_client()

        link_concepts(client, self.FROM_ID, self.TO_ID, "uses")

        call_args = client.update_gist.call_args
        files_dict: dict = call_args[0][1]
        assert "lore.json" in files_dict
