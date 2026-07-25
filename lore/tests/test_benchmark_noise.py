"""Tests for _inject_noise_concepts in samples/stlgen/benchmarks/run.py.

These tests verify that noise injection:
  - submits and rates the requested number of concepts
  - clamps to the available entries when n exceeds len(noise_concepts.json)
  - returns 0 and makes no calls when n=0
  - skips unparseable submit results with a warning rather than crashing
  - raises FileNotFoundError when noise_concepts.json is missing
"""
from __future__ import annotations

import importlib
import json
import sys
import types
import warnings
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Module fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def runner(tmp_path, monkeypatch):
    """Import the benchmark runner with a minimal stub for the anthropic package.

    The runner imports ``anthropic`` at module level.  We inject a stub so the
    test environment does not need the real package installed.
    """
    # Provide a minimal stub for ``anthropic`` if not already installed.
    if "anthropic" not in sys.modules:
        stub = types.ModuleType("anthropic")
        stub.Anthropic = MagicMock()
        sys.modules["anthropic"] = stub

    # Force a fresh import every test so monkeypatches to module-level globals
    # don't leak between tests.
    runner_path = Path(__file__).parents[2] / "samples" / "stlgen" / "benchmarks" / "run.py"
    spec = importlib.util.spec_from_file_location("benchmark_run", runner_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def noise_json(tmp_path):
    """Return a list of 3 minimal noise concept dicts and write them to tmp_path."""
    entries = [
        {
            "name": f"Noise concept {i}",
            "type": "pattern",
            "content": f"This is wrong content for noise concept {i}.",
            "when_to_use": f"When testing noise resilience {i}.",
            "dont_use_when": "Never.",
            "tags": ["stl", "test"],
        }
        for i in range(1, 4)
    ]
    (tmp_path / "noise_concepts.json").write_text(json.dumps(entries), encoding="utf-8")
    return entries


# ---------------------------------------------------------------------------
# Helper to patch the noise_concepts.json path used by the runner
# ---------------------------------------------------------------------------

def _patch_noise_path(runner, tmp_path, monkeypatch):
    """Make __file__ inside the runner point to tmp_path so noise_concepts.json
    is resolved there.
    """
    monkeypatch.setattr(runner, "__file__", str(tmp_path / "run.py"))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInjectNoiseConcepts:
    """Unit tests for _inject_noise_concepts."""

    def test_happy_path_n2(self, runner, noise_json, tmp_path, monkeypatch):
        """n=2 submits exactly 2 concepts and rates each once."""
        _patch_noise_path(runner, tmp_path, monkeypatch)

        submit_results = [
            json.dumps({"concept_id": "cid-001"}),
            json.dumps({"concept_id": "cid-002"}),
        ]
        mock_submit = MagicMock(side_effect=submit_results)
        mock_rate   = MagicMock(return_value=json.dumps({"status": "ok"}))
        monkeypatch.setattr(runner, "handle_submit_concept", mock_submit)
        monkeypatch.setattr(runner, "handle_rate_concept",   mock_rate)

        count = runner._inject_noise_concepts(2)

        assert count == 2
        assert mock_submit.call_count == 2
        assert mock_rate.call_count   == 2

        # Each rating must use outcome=3 and the correct concept_id.
        rate_calls = mock_rate.call_args_list
        assert rate_calls[0] == call({"concept_id": "cid-001", "outcome": 3, "session_id": "noise-inject"})
        assert rate_calls[1] == call({"concept_id": "cid-002", "outcome": 3, "session_id": "noise-inject"})

    def test_happy_path_gist_ids_tracked(self, runner, noise_json, tmp_path, monkeypatch):
        """When backend is 'gists', concept IDs are appended to both tracking lists."""
        _patch_noise_path(runner, tmp_path, monkeypatch)
        monkeypatch.setattr(runner, "_ACTIVE_BACKEND", "gists")
        monkeypatch.setattr(runner, "_SERIES_GIST_IDS", [])
        monkeypatch.setattr(runner, "_NOISE_GIST_IDS",  [])

        mock_submit = MagicMock(side_effect=[
            json.dumps({"concept_id": "cid-001", "gist_id": "gist-aaa"}),
            json.dumps({"concept_id": "cid-002", "gist_id": "gist-bbb"}),
        ])
        mock_rate = MagicMock(return_value=json.dumps({"status": "ok"}))
        monkeypatch.setattr(runner, "handle_submit_concept", mock_submit)
        monkeypatch.setattr(runner, "handle_rate_concept",   mock_rate)

        count = runner._inject_noise_concepts(2)

        assert count == 2
        assert runner._SERIES_GIST_IDS == ["gist-aaa", "gist-bbb"]
        assert runner._NOISE_GIST_IDS  == ["gist-aaa", "gist-bbb"]

    def test_n_exceeds_available_clamps_to_len(self, runner, noise_json, tmp_path, monkeypatch):
        """When n > len(entries), injects only the available entries."""
        _patch_noise_path(runner, tmp_path, monkeypatch)

        # noise_json has 3 entries; request 99
        mock_submit = MagicMock(side_effect=[
            json.dumps({"concept_id": f"cid-{i:03d}"}) for i in range(3)
        ])
        mock_rate = MagicMock(return_value=json.dumps({"status": "ok"}))
        monkeypatch.setattr(runner, "handle_submit_concept", mock_submit)
        monkeypatch.setattr(runner, "handle_rate_concept",   mock_rate)

        count = runner._inject_noise_concepts(99)

        assert count == 3
        assert mock_submit.call_count == 3
        assert mock_rate.call_count   == 3

    def test_n_zero_returns_zero_no_calls(self, runner, noise_json, tmp_path, monkeypatch):
        """n=0 returns 0 immediately without calling submit or rate."""
        _patch_noise_path(runner, tmp_path, monkeypatch)

        mock_submit = MagicMock()
        mock_rate   = MagicMock()
        monkeypatch.setattr(runner, "handle_submit_concept", mock_submit)
        monkeypatch.setattr(runner, "handle_rate_concept",   mock_rate)

        count = runner._inject_noise_concepts(0)

        assert count == 0
        mock_submit.assert_not_called()
        mock_rate.assert_not_called()

    def test_json_parse_failure_skips_concept_continues(self, runner, noise_json, tmp_path, monkeypatch, capsys):
        """When submit returns unparseable JSON, that concept is skipped but others proceed."""
        _patch_noise_path(runner, tmp_path, monkeypatch)

        # First entry: bad JSON; second entry: valid
        mock_submit = MagicMock(side_effect=[
            "this is not json",
            json.dumps({"concept_id": "cid-002"}),
        ])
        mock_rate = MagicMock(return_value=json.dumps({"status": "ok"}))
        monkeypatch.setattr(runner, "handle_submit_concept", mock_submit)
        monkeypatch.setattr(runner, "handle_rate_concept",   mock_rate)

        count = runner._inject_noise_concepts(2)

        # Only 1 concept successfully injected
        assert count == 1
        # Rate called only once (for the valid concept)
        assert mock_rate.call_count == 1
        # Warning printed to stdout
        captured = capsys.readouterr()
        assert "warning" in captured.out.lower() or "warning" in captured.err.lower()

    def test_missing_concept_id_in_result_skips_and_warns(self, runner, noise_json, tmp_path, monkeypatch, capsys):
        """When submit result has no concept_id, concept is skipped with a warning."""
        _patch_noise_path(runner, tmp_path, monkeypatch)

        mock_submit = MagicMock(side_effect=[
            json.dumps({"status": "error", "message": "bad request"}),
            json.dumps({"concept_id": "cid-002"}),
        ])
        mock_rate = MagicMock(return_value=json.dumps({"status": "ok"}))
        monkeypatch.setattr(runner, "handle_submit_concept", mock_submit)
        monkeypatch.setattr(runner, "handle_rate_concept",   mock_rate)

        count = runner._inject_noise_concepts(2)

        assert count == 1
        assert mock_rate.call_count == 1
        captured = capsys.readouterr()
        assert "warning" in captured.out.lower() or "warning" in captured.err.lower()

    def test_missing_noise_json_raises_file_not_found(self, runner, tmp_path, monkeypatch):
        """When noise_concepts.json does not exist, FileNotFoundError is raised."""
        # Point __file__ at a directory that has no noise_concepts.json
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        monkeypatch.setattr(runner, "__file__", str(empty_dir / "run.py"))

        mock_submit = MagicMock()
        mock_rate   = MagicMock()
        monkeypatch.setattr(runner, "handle_submit_concept", mock_submit)
        monkeypatch.setattr(runner, "handle_rate_concept",   mock_rate)

        with pytest.raises(FileNotFoundError):
            runner._inject_noise_concepts(1)
