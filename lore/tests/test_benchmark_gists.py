"""Tests for the gists backend support in the stlgen benchmark runner."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import the runner module under test
# ---------------------------------------------------------------------------

RUNNER_PATH = Path(__file__).parents[2] / "samples" / "stlgen" / "benchmarks" / "run.py"

# Load the module without executing main()
import importlib.util

spec = importlib.util.spec_from_file_location("benchmark_run", RUNNER_PATH)
run_mod = importlib.util.module_from_spec(spec)
# Pre-populate sys.modules so intra-module imports resolve correctly
sys.modules["benchmark_run"] = run_mod
spec.loader.exec_module(run_mod)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_module_state():
    """Reset module-level mutable state between tests."""
    run_mod._ACTIVE_BACKEND = "selfhosted"
    run_mod._SERIES_GIST_IDS.clear()
    run_mod._gists_client_instance = None


# ---------------------------------------------------------------------------
# 1. --backend argparse parsing
# ---------------------------------------------------------------------------

class TestBackendArgparse:
    def _parse(self, argv):
        import argparse
        parser = argparse.ArgumentParser()
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--run", type=int)
        mode.add_argument("--all", action="store_true")
        mode.add_argument("--series", type=int)
        parser.add_argument("--verbose", "-v", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--max-turns", type=int, default=40)
        parser.add_argument("--start-series", type=int, default=1)
        parser.add_argument("--backend", choices=["selfhosted", "gists"], default="selfhosted")
        return parser.parse_args(argv)

    def test_default_is_selfhosted(self):
        args = self._parse(["--run", "1"])
        assert args.backend == "selfhosted"

    def test_gists_flag_parsed(self):
        args = self._parse(["--run", "1", "--backend", "gists"])
        assert args.backend == "gists"

    def test_selfhosted_explicit(self):
        args = self._parse(["--all", "--backend", "selfhosted"])
        assert args.backend == "selfhosted"

    def test_invalid_backend_rejected(self):
        import argparse
        parser = argparse.ArgumentParser()
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--run", type=int)
        mode.add_argument("--all", action="store_true")
        mode.add_argument("--series", type=int)
        parser.add_argument("--backend", choices=["selfhosted", "gists"], default="selfhosted")
        with pytest.raises(SystemExit):
            parser.parse_args(["--run", "1", "--backend", "invalid"])


# ---------------------------------------------------------------------------
# 2. Gist ID tracking accumulates across calls
# ---------------------------------------------------------------------------

class TestGistIdTracking:
    def setup_method(self):
        _reset_module_state()
        run_mod._ACTIVE_BACKEND = "gists"

    def teardown_method(self):
        _reset_module_state()

    def _submit(self, mock_client, side_effect_or_return):
        """Call _handle_submit_concept_gists with gists.submit_concept patched."""
        import lore.mcp.backends.gists as gists_mod
        inputs = {
            "name": "Test Concept",
            "type": "pattern",
            "content": "This is a test concept with enough content.",
            "when_to_use": "testing",
            "tags": ["test"],
        }
        with patch.object(run_mod, "_get_gists_client", return_value=mock_client), \
             patch.object(gists_mod, "submit_concept", side_effect=side_effect_or_return
                          if callable(side_effect_or_return) else None,
                          return_value=side_effect_or_return
                          if not callable(side_effect_or_return) else None) as mock_fn:
            # side_effect takes priority over return_value in mock; set correctly
            mock_fn.side_effect = side_effect_or_return if callable(side_effect_or_return) else None
            mock_fn.return_value = side_effect_or_return if not callable(side_effect_or_return) else None
            return run_mod._handle_submit_concept_gists(inputs)

    def test_single_submit_tracked(self):
        import lore.mcp.backends.gists as gists_mod
        mock_client = MagicMock()
        return_val = {"concept_id": "gist-abc", "status": "created"}

        with patch.object(run_mod, "_get_gists_client", return_value=mock_client), \
             patch.object(gists_mod, "submit_concept", return_value=return_val):
            result = run_mod._handle_submit_concept_gists({
                "name": "Test Concept",
                "type": "pattern",
                "content": "This is a test concept with enough content.",
                "when_to_use": "testing",
                "tags": ["test"],
            })

        data = json.loads(result)
        assert data["concept_id"] == "gist-abc"
        assert "gist-abc" in run_mod._SERIES_GIST_IDS

    def test_multiple_submits_accumulate(self):
        import lore.mcp.backends.gists as gists_mod
        mock_client = MagicMock()
        side_effects = iter([
            {"concept_id": "gist-001", "status": "created"},
            {"concept_id": "gist-002", "status": "created"},
            {"concept_id": "gist-003", "status": "created"},
        ])
        base_inputs = {
            "type": "pattern",
            "content": "Enough content to pass validation minimum length.",
            "when_to_use": "testing",
            "tags": ["test"],
        }

        with patch.object(run_mod, "_get_gists_client", return_value=mock_client), \
             patch.object(gists_mod, "submit_concept", side_effect=side_effects):
            for i in range(3):
                run_mod._handle_submit_concept_gists({"name": f"Concept {i}", **base_inputs})

        assert run_mod._SERIES_GIST_IDS == ["gist-001", "gist-002", "gist-003"]

    def test_duplicate_gist_id_not_added_twice(self):
        import lore.mcp.backends.gists as gists_mod
        mock_client = MagicMock()
        base_inputs = {
            "name": "Same Concept",
            "type": "pattern",
            "content": "Enough content to pass validation minimum length.",
            "when_to_use": "testing",
            "tags": ["test"],
        }

        with patch.object(run_mod, "_get_gists_client", return_value=mock_client), \
             patch.object(gists_mod, "submit_concept",
                          return_value={"concept_id": "gist-dup", "status": "created"}):
            for _ in range(3):
                run_mod._handle_submit_concept_gists(base_inputs)

        assert run_mod._SERIES_GIST_IDS.count("gist-dup") == 1


# ---------------------------------------------------------------------------
# 3. Cleanup loop handles delete_gist failures gracefully
# ---------------------------------------------------------------------------

class TestGistCleanup:
    def setup_method(self):
        _reset_module_state()

    def teardown_method(self):
        _reset_module_state()

    def test_cleanup_deletes_all_tracked_gists(self):
        run_mod._SERIES_GIST_IDS[:] = ["g1", "g2", "g3"]
        mock_client = MagicMock()
        mock_client.delete_gist.return_value = None

        from lore.mcp.backends.gists_client import GistNotFoundError

        with patch.object(run_mod, "_get_gists_client", return_value=mock_client):
            run_mod._cleanup_series_gists()

        assert mock_client.delete_gist.call_count == 3
        assert run_mod._SERIES_GIST_IDS == []

    def test_cleanup_tolerates_not_found(self):
        run_mod._SERIES_GIST_IDS[:] = ["g1", "g-gone", "g3"]
        mock_client = MagicMock()

        from lore.mcp.backends.gists_client import GistNotFoundError

        def _del(gid):
            if gid == "g-gone":
                raise GistNotFoundError(gid)

        mock_client.delete_gist.side_effect = _del

        with patch.object(run_mod, "_get_gists_client", return_value=mock_client):
            run_mod._cleanup_series_gists()  # must not raise

        assert run_mod._SERIES_GIST_IDS == []
        # 3 attempts, 1 raised GistNotFoundError (gracefully swallowed)
        assert mock_client.delete_gist.call_count == 3

    def test_cleanup_tolerates_generic_exception(self):
        run_mod._SERIES_GIST_IDS[:] = ["g1", "g-err", "g3"]
        mock_client = MagicMock()

        def _del(gid):
            if gid == "g-err":
                raise RuntimeError("network error")

        mock_client.delete_gist.side_effect = _del

        with patch.object(run_mod, "_get_gists_client", return_value=mock_client):
            run_mod._cleanup_series_gists()  # must not raise

        assert run_mod._SERIES_GIST_IDS == []

    def test_cleanup_empty_list_is_noop(self):
        run_mod._SERIES_GIST_IDS.clear()
        mock_client = MagicMock()

        with patch.object(run_mod, "_get_gists_client", return_value=mock_client):
            run_mod._cleanup_series_gists()

        mock_client.delete_gist.assert_not_called()


# ---------------------------------------------------------------------------
# 4. `backend` field appears in result dict and written markdown
# ---------------------------------------------------------------------------

class TestBackendField:
    def test_backend_in_result_dict(self):
        _reset_module_state()
        run_mod._ACTIVE_BACKEND = "gists"
        # Verify the module reads _ACTIVE_BACKEND into the result dict (static check)
        # by reading the source — the field is set to _ACTIVE_BACKEND in step_run().
        src = RUNNER_PATH.read_text()
        assert '"backend": _ACTIVE_BACKEND' in src

    def test_backend_in_run_md(self, tmp_path):
        _reset_module_state()
        result = {
            "run": 1,
            "backend": "gists",
            "lore_active": False,
            "concepts_available": 0,
            "concepts_captured": 2,
            "turn_budget": 40,
            "turns_main": 15,
            "turns_wrapup": 5,
            "input_tokens": 1000,
            "output_tokens": 500,
            "total_tokens": 1500,
            "elapsed": 120.0,
            "task_submitted": True,
            "tests_passed": True,
        }
        run_mod._write_run_md(result, "test output", output_dir=tmp_path)
        content = (tmp_path / "run1.md").read_text()
        assert "gists" in content

    def test_backend_in_aggregate_json(self, tmp_path):
        _reset_module_state()
        series_results = [
            {
                "run": 1,
                "backend": "gists",
                "lore_active": False,
                "concepts_available": 0,
                "concepts_captured": 1,
                "turn_budget": 40,
                "turns_main": 20,
                "turns_wrapup": 4,
                "input_tokens": 800,
                "output_tokens": 400,
                "total_tokens": 1200,
                "elapsed": 90.0,
                "task_submitted": True,
                "tests_passed": True,
            }
        ]
        # Patch RESULTS_DIR to tmp_path
        original = run_mod.RESULTS_DIR
        run_mod.RESULTS_DIR = tmp_path
        try:
            run_mod._write_aggregate_json(1, series_results, 40)
        finally:
            run_mod.RESULTS_DIR = original

        data = json.loads((tmp_path / "aggregate.json").read_text())
        assert data["series"][0]["runs"][0]["backend"] == "gists"


# ---------------------------------------------------------------------------
# 5. handle_submit_concept dispatches correctly based on _ACTIVE_BACKEND
# ---------------------------------------------------------------------------

class TestDispatch:
    def setup_method(self):
        _reset_module_state()

    def teardown_method(self):
        _reset_module_state()

    def test_selfhosted_dispatch_calls_selfhosted(self):
        run_mod._ACTIVE_BACKEND = "selfhosted"
        with patch.object(run_mod, "_handle_submit_concept_selfhosted",
                          return_value='{"concept_id": "x"}') as mock_sh:
            run_mod.handle_submit_concept({"name": "X", "content": "Y" * 25, "tags": []})
        mock_sh.assert_called_once()

    def test_gists_dispatch_calls_gists(self):
        run_mod._ACTIVE_BACKEND = "gists"
        with patch.object(run_mod, "_handle_submit_concept_gists",
                          return_value='{"concept_id": "g"}') as mock_g:
            run_mod.handle_submit_concept({"name": "X", "content": "Y" * 25, "tags": []})
        mock_g.assert_called_once()

    def test_search_selfhosted_dispatch(self):
        run_mod._ACTIVE_BACKEND = "selfhosted"
        with patch.object(run_mod, "_handle_search_concepts_selfhosted",
                          return_value='{"results": []}') as mock_sh:
            run_mod.handle_search_concepts({"problem": "test"})
        mock_sh.assert_called_once()

    def test_search_gists_dispatch(self):
        run_mod._ACTIVE_BACKEND = "gists"
        with patch.object(run_mod, "_handle_search_concepts_gists",
                          return_value='{"results": []}') as mock_g:
            run_mod.handle_search_concepts({"problem": "test"})
        mock_g.assert_called_once()
