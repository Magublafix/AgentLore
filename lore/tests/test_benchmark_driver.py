"""Tests for the resumable benchmark driver (samples/stlgen/benchmarks/bench_driver.py)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).parents[2] / "samples" / "stlgen" / "benchmarks"
sys.path.insert(0, str(BENCH))
try:
    import bench_driver as bd  # noqa: E402
finally:
    sys.path.remove(str(BENCH))


@pytest.fixture(autouse=True)
def _no_real_pip_freeze(request, monkeypatch):
    """run_series snapshots the agent's user site; keep that off the real interpreter in tests."""
    if request.cls is not None and request.cls.__name__ == "TestEnvDrift":
        return
    monkeypatch.setattr(bd, "env_snapshot", lambda *a, **k: {})


def _agg(path: Path, ids):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"series": [{"series_id": i} for i in ids]}))


class TestResume:
    def test_agentlore_uses_legacy_location_others_subdir(self, tmp_path):
        assert bd.cond_dir(tmp_path, "agentlore") == tmp_path
        assert bd.cond_dir(tmp_path, "random") == tmp_path / "random"

    def test_pending_skips_completed(self, tmp_path):
        _agg(tmp_path / "aggregate.json", [1, 2, 4])
        assert bd.pending_series(tmp_path, "agentlore", 5) == [3, 5]

    def test_pending_all_when_nothing_done(self, tmp_path):
        assert bd.pending_series(tmp_path, "control", 3) == [1, 2, 3]

    def test_corrupt_aggregate_treated_as_empty(self, tmp_path):
        (tmp_path / "aggregate.json").write_text("{not json")
        assert bd.completed_series(tmp_path, "agentlore") == set()

    def test_status_lists_every_condition(self, tmp_path):
        _agg(tmp_path / "random" / "aggregate.json", [1])
        out = bd.status(tmp_path, 3)
        assert "random" in out and "1/3" in out and "agentlore" in out and "control" in out


class TestPrivateBackendOnly:
    SECRETS = {"LORE_GITHUB_TOKEN": "x", "GITHUB_TOKEN": "x", "GH_TOKEN": "x",
               "LORE_SEMANTIC_URL": "http://x", "KEEP": "1"}

    def test_secrets_removed_for_runner_and_server(self, tmp_path):
        for env in (bd.runner_env(self.SECRETS, tmp_path), bd.server_env(self.SECRETS, tmp_path)):
            assert not set(bd.SECRET_ENV) & set(env)
            assert env["KEEP"] == "1"

    @pytest.mark.parametrize("cond", bd.CONDITIONS)
    def test_every_command_forces_selfhosted_backend(self, cond):
        cmd = bd.series_command("py", cond, 4, [])
        assert cmd[cmd.index("--backend") + 1] == "selfhosted"
        assert "gists" not in cmd

    def test_random_matches_same_numbered_relevant_series(self):
        cmd = bd.series_command("py", "random", 7, [])
        assert cmd[cmd.index("--match-series") + 1] == "7"
        assert cmd[cmd.index("--start-series") + 1] == "7"
        assert "--match-series" not in bd.series_command("py", "control", 7, [])

    def test_runner_env_points_at_private_server_and_local_model(self, tmp_path):
        env = bd.runner_env({}, tmp_path)
        assert env["LORE_LLM_PROVIDER"] == "local"
        assert env["LORE_LOCAL_BASE_URL"] == bd.LLM_BASE_URL
        assert env["LORE_API_URL"].startswith("http://127.0.0.1:")
        assert env["LORE_SESSION_FILE"].startswith(str(tmp_path))

    def test_server_uses_sqlite_and_embedded_qdrant_on_disk(self, tmp_path):
        env = bd.server_env({}, tmp_path)
        assert env["LORE_STORAGE_BACKEND"] == "sqlite_qdrant"     # never gist_qdrant
        assert env["LORE_DB_PATH"] == str(tmp_path / "lore.db")
        assert env["LORE_BENCH_QDRANT_PATH"] == str(tmp_path / "qdrant")


class TestRunSeries:
    def test_retries_until_series_recorded(self, tmp_path, monkeypatch):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if len(calls) == 2:                      # second attempt succeeds
                _agg(tmp_path / "aggregate.json", [1])

        monkeypatch.setattr(bd.subprocess, "run", fake_run)
        assert bd.run_series("py", "agentlore", 1, [], None, tmp_path, {}, retries=3) is True
        assert len(calls) == 2

    def test_gives_up_after_retries(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bd.subprocess, "run", lambda *a, **k: None)
        assert bd.run_series("py", "control", 1, [], None, tmp_path, {}, retries=2) is False
        assert (tmp_path / "logs" / "control_series_001.log").exists()

    def test_server_ensured_before_each_attempt(self, tmp_path, monkeypatch):
        class S:
            n = 0
            def ensure(self): S.n += 1
        monkeypatch.setattr(bd.subprocess, "run", lambda *a, **k: None)
        bd.run_series("py", "agentlore", 1, [], S(), tmp_path, {}, retries=2)
        assert S.n == 2


class TestDegenerateSeries:
    def _write(self, tmp_path, turns):
        (tmp_path / "aggregate.json").write_text(json.dumps(
            {"series": [{"series_id": 1, "runs": [{"turns_main": t} for t in turns]}]}))

    def test_all_zero_turns_is_degenerate(self, tmp_path):
        self._write(tmp_path, [0, 0, 0])
        assert bd.series_is_degenerate(tmp_path, "agentlore", 1)

    def test_any_real_turn_is_not_degenerate(self, tmp_path):
        self._write(tmp_path, [0, 7, 0])
        assert not bd.series_is_degenerate(tmp_path, "agentlore", 1)

    def test_degenerate_series_is_discarded_and_reported_failed(self, tmp_path, monkeypatch):
        def fake_run(cmd, **kw):
            self._write(tmp_path, [0] * 10)
        monkeypatch.setattr(bd.subprocess, "run", fake_run)
        assert bd.run_series("py", "agentlore", 1, [], None, tmp_path, {}, retries=3) is False
        assert bd.completed_series(tmp_path, "agentlore") == set()   # not left to be skipped on resume


class TestEmbeddedQdrantLauncher:
    def test_collection_recreated_after_delete(self, tmp_path):
        """Admin reset must not leave later queries hitting a missing collection (was HTTP 500)."""
        sys.path.insert(0, str(BENCH))
        try:
            import bench_server
        finally:
            sys.path.remove(str(BENCH))
        import lore.server.storage.sqlite_qdrant as sq
        original = sq.QdrantClient
        try:
            bench_server.patch_qdrant(str(tmp_path / "q"))
            client = sq.QdrantClient(host="ignored", port=1)
            from lore.selfhosted.vector_store import init_qdrant_collection
            init_qdrant_collection(client, collection_name="concepts")
            client.delete_collection("concepts")
            names = [c.name for c in client.get_collections().collections]
            assert "concepts" in names
        finally:
            sq.QdrantClient = original

    def test_requires_path_env(self, monkeypatch):
        sys.path.insert(0, str(BENCH))
        try:
            import bench_server
        finally:
            sys.path.remove(str(BENCH))
        monkeypatch.delenv("LORE_BENCH_QDRANT_PATH", raising=False)
        with pytest.raises(SystemExit):
            bench_server.main()


class TestEnvDrift:
    def test_diff_reports_added_removed_changed(self):
        d = bd.env_diff({"a": "1", "b": "1", "c": "1"}, {"a": "1", "b": "2", "d": "1"})
        assert d == {"added": ["d"], "removed": ["c"], "changed": ["b: 1 -> 2"]}

    def test_no_drift_is_all_empty(self):
        assert not any(bd.env_diff({"a": "1"}, {"a": "1"}).values())

    def test_snapshot_parses_freeze_output(self, monkeypatch):
        class R:
            stdout = "numpy==2.5.5\nTrimesh==5.2.1\n# comment\n-e git+x#egg=y\n"
        monkeypatch.setattr(bd.subprocess, "run", lambda *a, **k: R())
        assert bd.env_snapshot() == {"numpy": "2.5.5", "trimesh": "5.2.1"}

    def test_snapshot_failure_is_empty_not_fatal(self, monkeypatch):
        def boom(*a, **k): raise OSError("no python")
        monkeypatch.setattr(bd.subprocess, "run", boom)
        assert bd.env_snapshot() == {}

    def test_drift_logged_by_run_series(self, tmp_path, monkeypatch):
        snaps = iter([{"a": "1"}, {"a": "1", "rtree": "1.4"}])
        monkeypatch.setattr(bd, "env_snapshot", lambda *a, **k: next(snaps))
        monkeypatch.setattr(bd.subprocess, "run", lambda *a, **k: None)
        bd.run_series("py", "control", 1, [], None, tmp_path, {}, retries=1)
        rec = json.loads((tmp_path / "logs" / "env_drift.jsonl").read_text())
        assert rec["added"] == ["rtree"] and rec["condition"] == "control"

    def test_snapshot_ignores_freeze_comments_containing_double_equals(self, monkeypatch):
        class R:
            stdout = "numpy==2.5.5\n# Editable install with no version control (text2stl==0.1.0)\n-e /tmp/x\n"
        monkeypatch.setattr(bd.subprocess, "run", lambda *a, **k: R())
        assert bd.env_snapshot() == {"numpy": "2.5.5"}
