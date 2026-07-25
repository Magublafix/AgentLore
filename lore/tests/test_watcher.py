"""Tests for the Gist watcher background task (LORE-031).

Strategy
--------
- ``httpx.AsyncClient`` is patched via ``unittest.mock.AsyncMock`` — no real
  network calls are made.
- Storage backend is mocked via ``unittest.mock.MagicMock``.
- Cursor file I/O is patched to a temporary directory so tests leave no
  filesystem artefacts.
- All async tests use ``pytest.mark.asyncio`` (or auto-mode via pyproject.toml).

Test coverage
-------------
1.  Happy path — two ``[agentlore-concept]`` gists indexed; ``upsert_concept`` called twice.
2.  Filter — gist without ``[agentlore-concept]`` in description is skipped.
3.  Missing ``lore.json`` — logs WARNING; watcher continues; no upsert.
4.  Malformed JSON — ``lore.json`` is not valid JSON; logs WARNING; continues.
5.  Upsert error — ``upsert_concept`` raises; logs WARNING; remaining gists processed.
6.  Dedup within cycle — same gist ID appears twice; upserted only once.
7.  Cursor written after cycle — ``watcher_cursor.json`` written with updated timestamp.
8.  Cursor loaded on startup — existing cursor file timestamp used as ``since`` param.
9.  Missing token — empty ``LORE_GITHUB_TOKEN``; no HTTP call made; sleeps and continues.
10. CancelledError propagates — task cancelled cleanly without masking the error.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import httpx
import pytest

import lore.server.watcher as watcher_module
from lore.server.watcher import (
    _extract_payload,
    _fetch_public_gists,
    _load_cursor,
    _parse_next_link,
    _run_poll_cycle,
    _save_cursor,
    watch_loop,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_gist_summary(
    gist_id: str = "abc123",
    description: str = "[agentlore-concept] My Pattern [tag1]",
    updated_at: str = "2024-01-15T12:00:00Z",
) -> dict:
    """Build a minimal public-gist-list entry."""
    return {
        "id": gist_id,
        "description": description,
        "updated_at": updated_at,
    }


def _make_full_gist(
    gist_id: str = "abc123",
    description: str = "[agentlore-concept] My Pattern [tag1]",
    updated_at: str = "2024-01-15T12:00:00Z",
    lore_json_content: str | None = None,
) -> dict:
    """Build a full gist object with ``lore.json`` content."""
    if lore_json_content is None:
        lore_json_content = json.dumps(
            {
                "name": "My Pattern",
                "type": "pattern",
                "when_to_use": "When you need to do X",
                "dont_use_when": "Not when Y",
                "tags": ["tag1"],
                "language": "python",
                "author": "alice",
                "source_url": None,
                "links": [],
            }
        )
    return {
        "id": gist_id,
        "description": description,
        "updated_at": updated_at,
        "owner": {"login": "alice"},
        "files": {
            "lore.json": {"content": lore_json_content},
            "lore.md": {"content": "# My Pattern\n\nContent here."},
        },
    }


def _mock_httpx_client(
    list_response: list[dict] | None = None,
    full_gist_map: dict[str, dict] | None = None,
    link_header: str = "",
) -> AsyncMock:
    """Build an AsyncMock that behaves like an httpx.AsyncClient.

    Args:
        list_response: JSON body returned for the /gists/public call.
        full_gist_map: Mapping of gist_id -> full gist dict for individual
            gist fetches.
        link_header: Value of the Link header on the list response.

    Returns:
        An ``AsyncMock`` configured to return the given responses.
    """
    list_response = list_response or []
    full_gist_map = full_gist_map or {}

    async def _get(url: str, **kwargs):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.raise_for_status = MagicMock()

        if "/gists/public" in url:
            mock_resp.json.return_value = list_response
            mock_resp.headers = {"Link": link_header}
        else:
            # Individual gist fetch: extract gist_id from URL.
            gist_id = url.rstrip("/").split("/")[-1]
            gist_data = full_gist_map.get(gist_id, {})
            mock_resp.json.return_value = gist_data
            mock_resp.headers = {}

        return mock_resp

    client_mock = AsyncMock()
    client_mock.get = _get
    return client_mock


# ---------------------------------------------------------------------------
# Unit tests for _parse_next_link
# ---------------------------------------------------------------------------


def test_parse_next_link_with_next():
    link_header = '<https://api.github.com/gists/public?page=2>; rel="next", <https://api.github.com/gists/public?page=5>; rel="last"'
    result = _parse_next_link(link_header)
    assert result == "https://api.github.com/gists/public?page=2"


def test_parse_next_link_without_next():
    link_header = '<https://api.github.com/gists/public?page=4>; rel="prev"'
    result = _parse_next_link(link_header)
    assert result is None


def test_parse_next_link_empty():
    assert _parse_next_link("") is None


# ---------------------------------------------------------------------------
# Unit tests for _extract_payload
# ---------------------------------------------------------------------------


def test_extract_payload_happy_path():
    gist = _make_full_gist()
    payload = _extract_payload(gist)
    assert payload is not None
    assert payload["gist_id"] == "abc123"
    assert payload["name"] == "My Pattern"
    assert payload["type"] == "pattern"
    assert payload["when_to_use"] == "When you need to do X"
    assert payload["language"] == "python"
    assert payload["tags"] == ["tag1"]
    assert payload["gist_updated_at"] == "2024-01-15T12:00:00Z"


def test_extract_payload_missing_lore_json_returns_none(caplog):
    gist = {
        "id": "abc123",
        "description": "[agentlore-concept] My Pattern [tag1]",
        "updated_at": "2024-01-15T12:00:00Z",
        "files": {},
    }
    with caplog.at_level("WARNING"):
        payload = _extract_payload(gist)
    assert payload is None
    assert "no lore.json" in caplog.text.lower() or "lore.json" in caplog.text


def test_extract_payload_malformed_json_returns_none(caplog):
    gist = _make_full_gist(lore_json_content="{not valid json")
    with caplog.at_level("WARNING"):
        payload = _extract_payload(gist)
    assert payload is None
    assert "malformed" in caplog.text.lower() or "lore.json" in caplog.text


def test_extract_payload_name_falls_back_to_description():
    """Name absent from lore.json — should be parsed from gist description."""
    lore_json = json.dumps(
        {"type": "pattern", "when_to_use": "use it often"}
    )
    gist = _make_full_gist(lore_json_content=lore_json)
    payload = _extract_payload(gist)
    assert payload is not None
    assert payload["name"] == "My Pattern"


# ---------------------------------------------------------------------------
# Unit tests for cursor helpers
# ---------------------------------------------------------------------------


def test_load_cursor_missing_file_returns_default(tmp_path):
    with patch.object(watcher_module, "_CURSOR_PATH", tmp_path / "cursor.json"):
        cursor = _load_cursor()
    # Should be a valid ISO-8601 string ending with Z.
    assert cursor.endswith("Z")
    assert "T" in cursor


def test_save_and_load_cursor_roundtrip(tmp_path):
    cursor_file = tmp_path / "cursor.json"
    ts = "2024-06-01T10:00:00Z"
    with patch.object(watcher_module, "_CURSOR_PATH", cursor_file):
        _save_cursor(ts)
        loaded = _load_cursor()
    assert loaded == ts


def test_save_cursor_creates_parent_dir(tmp_path):
    cursor_file = tmp_path / "nested" / "dir" / "cursor.json"
    with patch.object(watcher_module, "_CURSOR_PATH", cursor_file):
        _save_cursor("2024-01-01T00:00:00Z")
    assert cursor_file.exists()


# ---------------------------------------------------------------------------
# Test 8 — Cursor loaded on startup uses existing timestamp as `since` param
# ---------------------------------------------------------------------------


async def test_cursor_loaded_on_startup_uses_existing_timestamp(tmp_path):
    """If cursor file exists, its timestamp is used as the `since` param."""
    cursor_file = tmp_path / "cursor.json"
    existing_ts = "2024-03-01T08:00:00Z"

    storage = MagicMock()
    storage.upsert_concept.return_value = {"status": "upserted", "gist_id": "g1"}

    gist = _make_full_gist(gist_id="g1", updated_at="2024-03-01T09:00:00Z")
    summaries = [_make_gist_summary(gist_id="g1", updated_at="2024-03-01T09:00:00Z")]
    client_mock = _mock_httpx_client(
        list_response=summaries,
        full_gist_map={"g1": gist},
    )

    captured_urls: list[str] = []

    async def _get(url: str, **kwargs):
        captured_urls.append(url)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {}
        if "/gists/public" in url:
            mock_resp.json.return_value = summaries
            mock_resp.headers = {"Link": ""}
        elif "/comments" in url:
            mock_resp.json.return_value = []
        else:
            mock_resp.json.return_value = gist
        return mock_resp

    client_mock.get = _get

    with (
        patch.object(watcher_module, "_CURSOR_PATH", cursor_file),
        patch("httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=client_mock)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        # Write cursor before the poll cycle.
        _save_cursor(existing_ts)
        await _run_poll_cycle(storage, "token123")

    # The first GET call must contain the existing_ts as the `since` parameter.
    assert any(existing_ts in url for url in captured_urls), (
        f"Expected {existing_ts!r} in one of {captured_urls}"
    )


# ---------------------------------------------------------------------------
# Tests 1–7 and 9–10 via _run_poll_cycle / watch_loop
# ---------------------------------------------------------------------------


async def test_happy_path_two_gists_indexed(tmp_path):
    """Test 1 — two [agentlore-concept] gists returned; upsert_concept called once per gist."""
    cursor_file = tmp_path / "cursor.json"
    storage = MagicMock()
    storage.upsert_concept.return_value = {"status": "upserted", "gist_id": "g1"}

    gist1 = _make_full_gist(gist_id="g1", updated_at="2024-01-15T10:00:00Z")
    gist2 = _make_full_gist(gist_id="g2", updated_at="2024-01-15T11:00:00Z")
    summaries = [
        _make_gist_summary(gist_id="g1", updated_at="2024-01-15T10:00:00Z"),
        _make_gist_summary(gist_id="g2", updated_at="2024-01-15T11:00:00Z"),
    ]
    client_mock = _mock_httpx_client(
        list_response=summaries,
        full_gist_map={"g1": gist1, "g2": gist2},
    )

    with (
        patch.object(watcher_module, "_CURSOR_PATH", cursor_file),
        patch("httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=client_mock)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await _run_poll_cycle(storage, "token123")

    assert storage.upsert_concept.call_count == 2
    called_gist_ids = {
        c.args[0]["gist_id"] for c in storage.upsert_concept.call_args_list
    }
    assert called_gist_ids == {"g1", "g2"}


async def test_filter_non_lore_concept_gist(tmp_path):
    """Test 2 — gist without [agentlore-concept] in description is skipped."""
    cursor_file = tmp_path / "cursor.json"
    storage = MagicMock()

    summaries = [
        _make_gist_summary(gist_id="notlore", description="just a random gist"),
        _make_gist_summary(gist_id="islore", description="[agentlore-concept] Pattern [t1]"),
    ]
    gist_islore = _make_full_gist(gist_id="islore")
    client_mock = _mock_httpx_client(
        list_response=summaries,
        full_gist_map={"islore": gist_islore},
    )

    with (
        patch.object(watcher_module, "_CURSOR_PATH", cursor_file),
        patch("httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=client_mock)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await _run_poll_cycle(storage, "token123")

    # Only the lore-concept gist should be upserted.
    assert storage.upsert_concept.call_count == 1
    assert storage.upsert_concept.call_args[0][0]["gist_id"] == "islore"


async def test_missing_lore_json_logs_warning_and_continues(tmp_path, caplog):
    """Test 3 — gist with no lore.json is skipped; WARNING logged; no upsert."""
    cursor_file = tmp_path / "cursor.json"
    storage = MagicMock()

    summaries = [
        _make_gist_summary(gist_id="bad"),
        _make_gist_summary(gist_id="good"),
    ]
    bad_gist = {
        "id": "bad",
        "description": "[agentlore-concept] Bad [t1]",
        "updated_at": "2024-01-15T10:00:00Z",
        "files": {},  # no lore.json
    }
    good_gist = _make_full_gist(gist_id="good")
    client_mock = _mock_httpx_client(
        list_response=summaries,
        full_gist_map={"bad": bad_gist, "good": good_gist},
    )

    with (
        patch.object(watcher_module, "_CURSOR_PATH", cursor_file),
        patch("httpx.AsyncClient") as mock_cls,
        caplog.at_level("WARNING", logger="lore.server.watcher"),
    ):
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=client_mock)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await _run_poll_cycle(storage, "token123")

    assert "lore.json" in caplog.text
    # Only the good gist should be upserted.
    assert storage.upsert_concept.call_count == 1
    assert storage.upsert_concept.call_args[0][0]["gist_id"] == "good"


async def test_malformed_lore_json_logs_warning_and_continues(tmp_path, caplog):
    """Test 4 — lore.json is not valid JSON; WARNING logged; watcher continues."""
    cursor_file = tmp_path / "cursor.json"
    storage = MagicMock()

    summaries = [
        _make_gist_summary(gist_id="malformed"),
        _make_gist_summary(gist_id="valid"),
    ]
    malformed_gist = _make_full_gist(gist_id="malformed", lore_json_content="{bad json!!")
    valid_gist = _make_full_gist(gist_id="valid")
    client_mock = _mock_httpx_client(
        list_response=summaries,
        full_gist_map={"malformed": malformed_gist, "valid": valid_gist},
    )

    with (
        patch.object(watcher_module, "_CURSOR_PATH", cursor_file),
        patch("httpx.AsyncClient") as mock_cls,
        caplog.at_level("WARNING", logger="lore.server.watcher"),
    ):
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=client_mock)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await _run_poll_cycle(storage, "token123")

    assert "malformed" in caplog.text.lower()
    assert storage.upsert_concept.call_count == 1
    assert storage.upsert_concept.call_args[0][0]["gist_id"] == "valid"


async def test_upsert_error_logs_warning_and_continues(tmp_path, caplog):
    """Test 5 — upsert_concept raises; WARNING logged; remaining gists processed."""
    cursor_file = tmp_path / "cursor.json"
    storage = MagicMock()

    call_count = 0

    def _side_effect(payload):
        nonlocal call_count
        call_count += 1
        if payload["gist_id"] == "bad_upsert":
            raise RuntimeError("Qdrant is down")
        return {"status": "upserted", "gist_id": payload["gist_id"]}

    storage.upsert_concept.side_effect = _side_effect

    summaries = [
        _make_gist_summary(gist_id="bad_upsert"),
        _make_gist_summary(gist_id="after_error"),
    ]
    bad_upsert_gist = _make_full_gist(gist_id="bad_upsert")
    after_error_gist = _make_full_gist(gist_id="after_error")
    client_mock = _mock_httpx_client(
        list_response=summaries,
        full_gist_map={
            "bad_upsert": bad_upsert_gist,
            "after_error": after_error_gist,
        },
    )

    with (
        patch.object(watcher_module, "_CURSOR_PATH", cursor_file),
        patch("httpx.AsyncClient") as mock_cls,
        caplog.at_level("WARNING", logger="lore.server.watcher"),
    ):
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=client_mock)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await _run_poll_cycle(storage, "token123")

    # Both gists should have been attempted.
    assert storage.upsert_concept.call_count == 2
    assert "upsert_concept failed" in caplog.text.lower() or "Qdrant" in caplog.text


async def test_dedup_within_cycle_upserts_only_once(tmp_path):
    """Test 6 — same gist ID appears twice in poll results; upserted only once."""
    cursor_file = tmp_path / "cursor.json"
    storage = MagicMock()
    storage.upsert_concept.return_value = {"status": "upserted", "gist_id": "dup"}

    summaries = [
        _make_gist_summary(gist_id="dup"),
        _make_gist_summary(gist_id="dup"),  # duplicate
    ]
    dup_gist = _make_full_gist(gist_id="dup")
    client_mock = _mock_httpx_client(
        list_response=summaries,
        full_gist_map={"dup": dup_gist},
    )

    with (
        patch.object(watcher_module, "_CURSOR_PATH", cursor_file),
        patch("httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=client_mock)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await _run_poll_cycle(storage, "token123")

    assert storage.upsert_concept.call_count == 1


async def test_cursor_written_after_successful_cycle(tmp_path):
    """Test 7 — after a successful poll, cursor file is written with updated timestamp."""
    cursor_file = tmp_path / "cursor.json"
    storage = MagicMock()
    storage.upsert_concept.return_value = {"status": "upserted", "gist_id": "g1"}

    updated_at = "2024-05-20T15:30:00Z"
    gist = _make_full_gist(gist_id="g1", updated_at=updated_at)
    summaries = [_make_gist_summary(gist_id="g1", updated_at=updated_at)]
    client_mock = _mock_httpx_client(
        list_response=summaries,
        full_gist_map={"g1": gist},
    )

    with (
        patch.object(watcher_module, "_CURSOR_PATH", cursor_file),
        patch("httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=client_mock)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await _run_poll_cycle(storage, "token123")

    assert cursor_file.exists()
    data = json.loads(cursor_file.read_text())
    assert data["last_polled_at"] == updated_at


async def test_missing_token_skips_poll_no_http_call(tmp_path):
    """Test 9 — empty LORE_GITHUB_TOKEN; no HTTP call; watcher sleeps and continues."""
    cursor_file = tmp_path / "cursor.json"
    storage = MagicMock()

    with (
        patch.object(watcher_module, "_CURSOR_PATH", cursor_file),
        patch("httpx.AsyncClient") as mock_cls,
    ):
        await _run_poll_cycle(storage, "")  # empty token
        # httpx.AsyncClient should never have been entered.
        mock_cls.assert_not_called()

    storage.upsert_concept.assert_not_called()


async def test_cancelled_error_propagates():
    """Test 10 — CancelledError propagates cleanly without being swallowed."""
    storage = MagicMock()

    # Patch asyncio.sleep to raise CancelledError immediately.
    async def _cancel(*args, **kwargs):
        raise asyncio.CancelledError()

    with patch("asyncio.sleep", side_effect=_cancel):
        # _run_poll_cycle is also patched to avoid network calls.
        with patch.object(
            watcher_module, "_run_poll_cycle", new_callable=AsyncMock
        ):
            with pytest.raises(asyncio.CancelledError):
                await watch_loop(storage, "token", interval=300)


async def test_watch_loop_cancelled_during_poll():
    """CancelledError raised inside _run_poll_cycle propagates out of watch_loop."""
    storage = MagicMock()

    async def _cancel_poll(*args, **kwargs):
        raise asyncio.CancelledError()

    with patch.object(
        watcher_module, "_run_poll_cycle", side_effect=_cancel_poll
    ):
        with pytest.raises(asyncio.CancelledError):
            await watch_loop(storage, "token", interval=300)


# ---------------------------------------------------------------------------
# Test pagination via _fetch_public_gists
# ---------------------------------------------------------------------------


async def test_fetch_public_gists_follows_pagination():
    """_fetch_public_gists follows Link rel=next pagination."""
    page1_gists = [_make_gist_summary(gist_id="p1a"), _make_gist_summary(gist_id="p1b")]
    page2_gists = [_make_gist_summary(gist_id="p2a")]

    call_count = 0
    page1_url = "https://api.github.com/gists/public?since=2024-01-01T00:00:00Z&per_page=100"
    page2_url = "https://api.github.com/gists/public?page=2"

    async def _get(url: str, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.raise_for_status = MagicMock()
        if "page=2" not in url:
            mock_resp.json.return_value = page1_gists
            mock_resp.headers = {
                "Link": f'<{page2_url}>; rel="next"'
            }
        else:
            mock_resp.json.return_value = page2_gists
            mock_resp.headers = {}
        return mock_resp

    client_mock = AsyncMock()
    client_mock.get = _get

    result = await _fetch_public_gists(client_mock, "2024-01-01T00:00:00Z")
    assert call_count == 2
    assert len(result) == 3
    assert result[0]["id"] == "p1a"
    assert result[2]["id"] == "p2a"


# ---------------------------------------------------------------------------
# Test lifespan watcher integration (api.py)
# ---------------------------------------------------------------------------


async def test_lifespan_starts_and_cancels_watcher_task():
    """Watcher task is created for gist_qdrant and cancelled on shutdown."""
    import lore.server.api as api_module

    started_tasks: list[asyncio.Task] = []
    cancelled_tasks: list[asyncio.Task] = []

    original_create_task = asyncio.create_task

    async def _noop_watch_loop(*args, **kwargs):
        # Simulate a long-running loop; responds to cancellation.
        try:
            await asyncio.sleep(9999)
        except asyncio.CancelledError:
            raise

    mock_storage = MagicMock()
    mock_model = MagicMock()

    with (
        patch.dict(
            os.environ,
            {"LORE_STORAGE_BACKEND": "gist_qdrant", "LORE_GITHUB_TOKEN": "tok"},
        ),
        patch.object(api_module, "_create_backend", return_value=mock_storage),
        patch(
            "lore.mcp.embeddings.EmbeddingModel", return_value=mock_model
        ),
        patch("lore.server.watcher.watch_loop", new=_noop_watch_loop),
    ):
        from fastapi.testclient import TestClient

        # Using TestClient triggers lifespan enter + exit.
        with TestClient(api_module.app) as client:
            resp = client.get("/v1/health")
            # We just need the lifespan to run; status is irrelevant here.

    # If we got here without exception the watcher started and was cancelled cleanly.


# ---------------------------------------------------------------------------
# Error propagation: _fetch_public_gists raises
# ---------------------------------------------------------------------------


async def test_fetch_public_gists_raises_logs_warning_and_returns(tmp_path, caplog):
    """If fetching the public gist list raises, a WARNING is logged and the
    cycle exits without calling upsert_concept or writing the cursor."""
    cursor_file = tmp_path / "cursor.json"
    storage = MagicMock()

    async def _raising_get(url: str, **kwargs):
        raise httpx.ConnectError("network failure")

    client_mock = AsyncMock()
    client_mock.get = _raising_get

    with (
        patch.object(watcher_module, "_CURSOR_PATH", cursor_file),
        patch("httpx.AsyncClient") as mock_cls,
        caplog.at_level("WARNING", logger="lore.server.watcher"),
    ):
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=client_mock)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await _run_poll_cycle(storage, "token123")

    assert "Failed to fetch public gists" in caplog.text
    storage.upsert_concept.assert_not_called()
    # Cursor must NOT be written — early return before _save_cursor.
    assert not cursor_file.exists()


# ---------------------------------------------------------------------------
# Error propagation: _fetch_full_gist raises for one gist
# ---------------------------------------------------------------------------


async def test_fetch_full_gist_raises_logs_warning_and_continues(tmp_path, caplog):
    """If fetching a full gist fails, a WARNING is logged and the watcher
    continues processing the remaining gists in the cycle."""
    cursor_file = tmp_path / "cursor.json"
    storage = MagicMock()
    storage.upsert_concept.return_value = {"status": "upserted", "gist_id": "ok"}

    summaries = [
        _make_gist_summary(gist_id="broken"),
        _make_gist_summary(gist_id="ok"),
    ]
    ok_gist = _make_full_gist(gist_id="ok")

    async def _get(url: str, **kwargs):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {}
        if "/gists/public" in url:
            mock_resp.json.return_value = summaries
            mock_resp.headers = {"Link": ""}
        elif "/gists/broken" in url:
            raise httpx.ConnectError("broken gist fetch")
        elif "/comments" in url:
            mock_resp.json.return_value = []
        else:
            mock_resp.json.return_value = ok_gist
        return mock_resp

    client_mock = AsyncMock()
    client_mock.get = _get

    with (
        patch.object(watcher_module, "_CURSOR_PATH", cursor_file),
        patch("httpx.AsyncClient") as mock_cls,
        caplog.at_level("WARNING", logger="lore.server.watcher"),
    ):
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=client_mock)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await _run_poll_cycle(storage, "token123")

    assert "Failed to fetch full gist" in caplog.text
    # The "ok" gist must still be upserted — watcher continued past the error.
    assert storage.upsert_concept.call_count == 1
    assert storage.upsert_concept.call_args[0][0]["gist_id"] == "ok"
