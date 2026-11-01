"""Tests for the test-only in-memory Qdrant hook (ADR-016)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from lore.server import api
from lore.server.storage.gist_qdrant import GistQdrantBackend

MEM = "LORE_QDRANT_IN_MEMORY"
ALLOW = "LORE_ALLOW_INSECURE_TEST_URLS"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(MEM, raising=False)
    monkeypatch.delenv(ALLOW, raising=False)


def test_unset_is_off(caplog):
    with caplog.at_level(logging.WARNING):
        assert api._in_memory_qdrant_requested() is False
    assert caplog.records == []


def test_requires_opt_in_and_warns(monkeypatch, caplog):
    monkeypatch.setenv(MEM, "1")
    with caplog.at_level(logging.WARNING):
        assert api._in_memory_qdrant_requested() is False
    assert any("Ignoring" in r.message and ALLOW in r.message for r in caplog.records)


@pytest.mark.parametrize("value", ["0", "true", "yes", ""])
def test_only_exact_one_activates(monkeypatch, value):
    monkeypatch.setenv(ALLOW, "1")
    monkeypatch.setenv(MEM, value)
    assert api._in_memory_qdrant_requested() is False


def test_active_with_opt_in_warns_loudly(monkeypatch, caplog):
    monkeypatch.setenv(MEM, "1")
    monkeypatch.setenv(ALLOW, "1")
    with caplog.at_level(logging.WARNING):
        assert api._in_memory_qdrant_requested() is True
    assert any("TEST-ONLY" in r.message and r.levelno == logging.WARNING for r in caplog.records)


def test_factory_passes_flag_to_backend(monkeypatch):
    monkeypatch.setenv(MEM, "1")
    monkeypatch.setenv(ALLOW, "1")
    with patch("lore.server.storage.gist_qdrant.GistQdrantBackend") as backend:
        api._create_backend(MagicMock(), "gist_qdrant")
    assert backend.call_args.kwargs["in_memory"] is True


def test_factory_default_is_remote(monkeypatch):
    monkeypatch.setenv(MEM, "1")  # no opt-in -> ignored
    with patch("lore.server.storage.gist_qdrant.GistQdrantBackend") as backend:
        api._create_backend(MagicMock(), "gist_qdrant")
    assert backend.call_args.kwargs["in_memory"] is False


def test_backend_in_memory_uses_memory_client_and_roundtrips():
    model = MagicMock()
    model.embed.return_value = [0.1] * 384
    with patch("lore.server.storage.gist_qdrant.QdrantClient") as qc:
        GistQdrantBackend("h", 1, model, in_memory=True)
    qc.assert_called_once_with(":memory:")
    b = GistQdrantBackend("h", 1, model, in_memory=True)  # real in-memory client
    assert b.health_check() == {"status": "ok"}
    res = b.upsert_concept({
        "gist_id": "abc", "name": "n", "type": "pattern",
        "when_to_use": "w", "gist_updated_at": "t",
    })
    assert res["status"] == "upserted"
    assert b.search_concepts([0.1] * 384, 3, None, None, 0.0)[0]["concept_id"] == "abc"


def test_backend_remote_by_default():
    with patch("lore.server.storage.gist_qdrant.QdrantClient") as qc:
        GistQdrantBackend("qhost", 6333, MagicMock())
    qc.assert_called_once_with(host="qhost", port=6333)
