"""Tests for benchmark conditions (LORE-050/051): bench_conditions.py and run.py integration."""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BENCH = Path(__file__).parents[2] / "samples" / "stlgen" / "benchmarks"
# Import the production module without leaving BENCH on sys.path afterwards. It stays in
# sys.modules so run.py's own ``import bench_conditions`` resolves to this same module object
# (needed so InfeasibleMatch / ParityError are the same classes in both).
sys.path.insert(0, str(BENCH))
try:
    import bench_conditions as bc  # noqa: E402
finally:
    sys.path.remove(str(BENCH))


def _concept(name, n_words=40, **kw):
    c = {"name": name, "type": "pattern", "content": "word " * n_words,
         "when_to_use": "when testing", "tags": ["misc"]}
    c.update(kw)
    return c


# ---------------------------------------------------------------------------
# Parity
# ---------------------------------------------------------------------------

class TestParity:
    def test_fingerprint_changes_with_each_setting(self):
        base = bc.settings_fingerprint("task", "m", 40)
        assert base != bc.settings_fingerprint("task2", "m", 40)
        assert base != bc.settings_fingerprint("task", "m2", 40)
        assert base != bc.settings_fingerprint("task", "m", 30)

    def test_match_passes(self):
        fp = bc.settings_fingerprint("t", "m", 40)
        bc.check_parity(fp, {"control": dict(fp)})

    @pytest.mark.parametrize("other", [
        {"model": "other"}, {"turn_budget": 30}, {"task_sha256": "x"},
    ])
    def test_mismatch_fails_fast(self, other):
        fp = bc.settings_fingerprint("t", "m", 40)
        with pytest.raises(bc.ParityError, match="control"):
            bc.check_parity(fp, {"control": {**fp, **other}})

    def test_legacy_missing_keys_skipped(self):
        fp = bc.settings_fingerprint("t", "m", 40)
        bc.check_parity(fp, {"agentlore": {"model": "m", "turn_budget": 40}})

    def test_no_others_is_ok(self):
        bc.check_parity(bc.settings_fingerprint("t", "m", 40), {})


class TestLayoutAndLoading:
    def test_condition_dirs(self, tmp_path):
        assert bc.condition_results_dir(tmp_path, "agentlore") == tmp_path
        assert bc.condition_results_dir(tmp_path, "control") == tmp_path / "control"
        with pytest.raises(ValueError):
            bc.condition_results_dir(tmp_path, "bogus")

    def test_load_other_settings_legacy_and_new(self, tmp_path):
        (tmp_path / "aggregate.json").write_text(json.dumps({"model": "m", "turn_budget": 40, "series": []}))
        (tmp_path / "control").mkdir()
        (tmp_path / "control" / "aggregate.json").write_text(
            json.dumps({"settings": {"model": "m", "turn_budget": 40, "task_sha256": "h"}}))
        assert bc.load_other_settings(tmp_path, "random") == {
            "agentlore": {"model": "m", "turn_budget": 40},
            "control": {"model": "m", "turn_budget": 40, "task_sha256": "h"},
        }
        assert "control" not in bc.load_other_settings(tmp_path, "control")

    def test_corrupt_aggregate_ignored(self, tmp_path):
        (tmp_path / "aggregate.json").write_text("{not json")
        assert bc.load_other_settings(tmp_path, "control") == {}


# ---------------------------------------------------------------------------
# Random context
# ---------------------------------------------------------------------------

class TestRandomContext:
    def test_pool_has_no_task_related_concepts(self):
        raw = json.loads(bc.POOL_PATH.read_text())
        assert len(raw) >= 20
        assert [c["name"] for c in raw if bc.is_task_related(c)] == []

    @pytest.mark.parametrize("text", ["Build an STL file", "uses trimesh", "a CLI tool",
                                      "Pillow fonts", "pyproject.toml packaging", "3D printing"])
    def test_task_related_detected(self, text):
        assert bc.is_task_related(_concept("x", content=text))

    def test_tags_checked_and_no_substring_false_positive(self):
        assert bc.is_task_related(_concept("x", tags=["mesh"]))
        assert not bc.is_task_related(_concept("x", content="HTTP client and clinical notes"))

    def test_load_pool_filters_related(self, tmp_path):
        p = tmp_path / "pool.json"
        p.write_text(json.dumps([_concept("ok"), _concept("bad", content="stl mesh")]))
        assert [c["name"] for c in bc.load_pool(p)] == ["ok"]

    def test_selection_within_tolerance(self):
        pool = bc.load_pool()
        for target in (300, 800, 1500):
            chosen, tokens = bc.select_random_context(pool, target, seed=1)
            assert abs(tokens - target) <= target * bc.TOKEN_TOLERANCE
            rendered = bc.estimate_tokens(bc.format_context(chosen))
            assert abs(rendered - target) <= target * bc.TOKEN_TOLERANCE

    def test_seeded_and_reproducible(self):
        pool = bc.load_pool()
        a = bc.select_random_context(pool, 800, seed=7)
        b = bc.select_random_context(pool, 800, seed=7)
        assert [c["name"] for c in a[0]] == [c["name"] for c in b[0]]
        names = [c["name"] for c in a[0]]
        others = [[c["name"] for c in bc.select_random_context(pool, 800, seed=sd)[0]]
                  for sd in range(8, 16)]
        assert any(o != names for o in others)    # a single other seed could collide by chance

    def test_pool_order_does_not_change_selection(self):
        pool = bc.load_pool()
        a = bc.select_random_context(pool, 800, seed=3)[0]
        b = bc.select_random_context(list(reversed(pool)), 800, seed=3)[0]
        assert [c["name"] for c in a] == [c["name"] for c in b]

    def test_zero_target_is_empty(self):
        assert bc.select_random_context(bc.load_pool(), 0, seed=1) == ([], 0)

    def test_infeasible_when_pool_too_small(self):
        with pytest.raises(bc.InfeasibleMatch):
            bc.select_random_context([_concept("a")], 100000, seed=1)

    def test_infeasible_when_single_concept_overshoots(self):
        with pytest.raises(bc.InfeasibleMatch):
            bc.select_random_context([_concept("a", n_words=2000)], 50, seed=1)

    def test_run_seed_stable_and_distinct(self):
        assert bc.run_seed(1, 2, 3) == bc.run_seed(1, 2, 3)
        assert len({bc.run_seed(1, s, r) for s in range(3) for r in range(1, 4)}) == 9

    def test_relevant_context_tokens_lookup(self, tmp_path):
        agg = {"series": [{"series_id": 2, "runs": [{"run": 1, "context_tokens": 0},
                                                   {"run": 2, "context_tokens": 640}]}]}
        (tmp_path / "aggregate.json").write_text(json.dumps(agg))
        assert bc.relevant_context_tokens(tmp_path, 2, 2) == 640
        with pytest.raises(bc.InfeasibleMatch):
            bc.relevant_context_tokens(tmp_path, 9, 2)
        with pytest.raises(bc.InfeasibleMatch):
            bc.relevant_context_tokens(tmp_path / "nowhere", 2, 2)

    def test_legacy_runs_without_context_tokens_rejected(self, tmp_path):
        (tmp_path / "aggregate.json").write_text(
            json.dumps({"series": [{"series_id": 1, "runs": [{"run": 1}]}]}))
        with pytest.raises(bc.InfeasibleMatch, match="context_tokens"):
            bc.relevant_context_tokens(tmp_path, 1, 1)


# ---------------------------------------------------------------------------
# Runner integration
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def _run_module():
    """Execute run.py once per test module (it is ~2000 lines); per-test state is reset in ``runner``."""
    with pytest.MonkeyPatch.context() as mp:
        if "anthropic" not in sys.modules:
            stub = types.ModuleType("anthropic")
            stub.Anthropic = MagicMock()
            mp.setitem(sys.modules, "anthropic", stub)
        mp.setattr(sys, "path", list(sys.path))      # run.py inserts into sys.path; undone on exit
        mp.syspath_prepend(str(BENCH))
        spec = importlib.util.spec_from_file_location("benchmark_run_cond", BENCH / "run.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def runner(_run_module, tmp_path, monkeypatch):
    mod = _run_module
    monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(mod, "SESSION_FILE", tmp_path / "session.json")
    # Module-level mutable state touched by step_run / main: fresh per test, restored afterwards.
    for name, fresh in (("_SERIES_GIST_IDS", []), ("_RUN_CONTEXT_TEXT", []), ("_ALL_WORKDIRS", []),
                        ("_RUN_SUBMITTED_IDS", []), ("_CURRENT_SESSION_ID", None),
                        ("_ACTIVE_BACKEND", mod._ACTIVE_BACKEND), ("_gists_client_instance", None)):
        monkeypatch.setattr(mod, name, fresh)
    calls = {}

    def fake_agent(system, tools, task_prompt, workdir, max_turns, verbose, **kw):
        calls.update(system=system, tools=tools, task_prompt=task_prompt, max_turns=max_turns)
        mod._RUN_CONTEXT_TEXT.append("x" * 400)  # pretend a search returned 100 tokens
        return 10, 5, 3, True, []

    monkeypatch.setattr(mod, "run_agent", fake_agent)
    monkeypatch.setattr(mod, "run_tests", lambda w: (True, "ok"))
    monkeypatch.setattr(mod, "_clear_db", MagicMock(name="clear_db"))
    monkeypatch.setattr(mod, "_count_concepts", lambda: 4)
    monkeypatch.setattr(mod, "run_wrapup_phase", MagicMock(name="wrapup", return_value=(1, 1, 1)))
    monkeypatch.setattr(mod, "_calls", calls, raising=False)
    return mod


LORE_TOOLS = {"search_concepts", "submit_concept", "rate_concept"}


class TestRunnerConditions:
    def test_control_has_no_lore_anywhere(self, runner, tmp_path):
        res = runner.step_run(3, False, False, output_dir=tmp_path, condition="control")
        names = {t["name"] for t in runner._calls["tools"]}
        assert not names & LORE_TOOLS
        text = (runner._calls["system"] + runner._calls["task_prompt"]).lower()
        assert "lore" not in text and "concept" not in text
        runner._clear_db.assert_not_called()
        runner.run_wrapup_phase.assert_not_called()
        assert res["condition"] == "control" and res["lore_active"] is False
        assert res["concepts_available"] == 0 and res["concepts_captured"] == 0
        assert res["turns_wrapup"] == 0

    def test_control_run1_does_not_reset_db(self, runner, tmp_path):
        runner.step_run(1, False, False, output_dir=tmp_path, condition="control")
        runner._clear_db.assert_not_called()

    def test_control_uses_same_task_and_budget(self, runner, tmp_path):
        runner.step_run(2, False, False, max_turns=40, output_dir=tmp_path, condition="control")
        assert runner._calls["task_prompt"].startswith(runner._TASK)
        assert runner._calls["max_turns"] == 40

    def test_agentlore_run1_still_resets_and_wraps_up(self, runner, tmp_path):
        res = runner.step_run(1, False, False, output_dir=tmp_path)
        runner._clear_db.assert_called_once()
        runner.run_wrapup_phase.assert_called_once()
        assert res["condition"] == "agentlore"

    def test_agentlore_records_retrieved_context_tokens(self, runner, tmp_path):
        res = runner.step_run(2, False, False, output_dir=tmp_path)
        assert "search_concepts" in {t["name"] for t in runner._calls["tools"]}
        assert res["context_tokens"] == 100

    def test_random_injects_matched_unrelated_context(self, runner, tmp_path):
        res = runner.step_run(2, False, False, output_dir=tmp_path, series_num=4, condition="random",
                              random_target_tokens=800, random_seed=5)
        assert not {t["name"] for t in runner._calls["tools"]} & LORE_TOOLS
        assert abs(res["context_tokens"] - 800) <= 80
        assert res["random_seed"] == bc.run_seed(5, 4, 2)
        assert res["random_target_tokens"] == 800
        assert res["random_concepts"]
        assert all(n in runner._calls["system"] for n in res["random_concepts"])
        runner.run_wrapup_phase.assert_not_called()
        runner._clear_db.assert_not_called()
        md = (tmp_path / "run2.md").read_text()
        assert "| Condition | random |" in md
        assert f"| Context tokens supplied | {res['context_tokens']} |" in md
        assert "| Lore search active | no |" in md

    def test_random_system_prompt_and_task_are_baseline(self, runner, tmp_path):
        res = runner.step_run(2, False, False, output_dir=tmp_path, series_num=4, condition="random",
                              random_target_tokens=800, random_seed=5)
        assert runner._calls["task_prompt"].startswith(runner._TASK)
        assert runner._calls["max_turns"] == 40
        pool = {c["name"]: c for c in bc.load_pool()}
        injected = bc.format_context([pool[n] for n in res["random_concepts"]])
        assert injected in runner._calls["system"]
        rest = runner._calls["system"].replace(injected, "").lower()
        assert "lore" not in rest and "concept" not in rest
        assert "lore" not in runner._calls["task_prompt"].lower()

    def test_random_without_target_raises(self, runner, tmp_path):
        with pytest.raises(ValueError):
            runner.step_run(2, False, False, output_dir=tmp_path, condition="random")

    def test_random_infeasible_target_propagates(self, runner, tmp_path):
        with pytest.raises(bc.InfeasibleMatch):
            runner.step_run(2, False, False, output_dir=tmp_path, condition="random",
                            random_target_tokens=10**7)

    def test_dry_run_returns_none(self, runner, tmp_path):
        assert runner.step_run(2, False, True, output_dir=tmp_path, condition="control") is None


class TestRunContextWiring:
    def test_search_handler_result_is_recorded(self, runner, monkeypatch):
        monkeypatch.setattr(runner, "handle_search_concepts", lambda inputs: "found: abc")
        assert runner._RUN_CONTEXT_TEXT == []
        out = runner.handle_tool("search_concepts", {"query": "q"}, None)
        assert out == "found: abc"
        assert runner._RUN_CONTEXT_TEXT == ["found: abc"]
        runner.handle_tool("search_concepts", {"query": "q2"}, None)
        assert runner._RUN_CONTEXT_TEXT == ["found: abc", "found: abc"]

    def test_non_search_tools_do_not_record(self, runner):
        runner.handle_tool("submit", {}, None)
        assert runner._RUN_CONTEXT_TEXT == []

    def test_step_run_clears_context_between_runs(self, runner, tmp_path):
        runner._RUN_CONTEXT_TEXT.append("y" * 4000)         # leftover from a previous run
        res1 = runner.step_run(2, False, False, output_dir=tmp_path)
        assert res1["context_tokens"] == 100               # only this run's 400 chars
        assert runner._RUN_CONTEXT_TEXT == ["x" * 400]
        res2 = runner.step_run(3, False, False, output_dir=tmp_path)
        assert res2["context_tokens"] == 100               # not 200: run 2's text was cleared
        assert runner._RUN_CONTEXT_TEXT == ["x" * 400]


class TestAggregatePerCondition:
    def _result(self, runner, tmp_path, cond, **kw):
        return runner.step_run(2, False, False, output_dir=tmp_path, condition=cond, **kw)

    def test_written_per_condition_with_settings(self, runner, tmp_path):
        ctrl = self._result(runner, tmp_path, "control")
        runner._write_aggregate_json(1, [ctrl], 40, condition="control")
        rel = self._result(runner, tmp_path, "agentlore")
        runner._write_aggregate_json(1, [rel], 40)
        rnd = self._result(runner, tmp_path, "random", random_target_tokens=500)
        runner._write_aggregate_json(1, [rnd], 40, condition="random")
        root = runner.RESULTS_DIR
        for path, cond in ((root / "aggregate.json", "agentlore"),
                           (root / "control" / "aggregate.json", "control"),
                           (root / "random" / "aggregate.json", "random")):
            data = json.loads(path.read_text())
            assert data["condition"] == cond and data["series"][0]["condition"] == cond
            assert data["settings"]["turn_budget"] == 40
        rr = json.loads((root / "random" / "aggregate.json").read_text())["series"][0]["runs"][0]
        assert rr["random_seed"] and rr["random_target_tokens"] == 500 and rr["random_concepts"]
        # the three condition files agree on every parity key
        sets = [json.loads(p.read_text())["settings"] for p in (
            root / "aggregate.json", root / "control" / "aggregate.json", root / "random" / "aggregate.json")]
        assert sets[0] == sets[1] == sets[2]

    def test_series_appended_not_overwritten(self, runner, tmp_path):
        r = self._result(runner, tmp_path, "control")
        runner._write_aggregate_json(1, [r], 40, condition="control")
        runner._write_aggregate_json(2, [r], 40, condition="control")
        data = json.loads((runner.RESULTS_DIR / "control" / "aggregate.json").read_text())
        assert [s["series_id"] for s in data["series"]] == [1, 2]


class TestMainGuards:
    def _run_main(self, runner, monkeypatch, argv):
        monkeypatch.setattr(sys, "argv", ["run.py", *argv])
        runner.main()

    def test_random_requires_target_source(self, runner, monkeypatch):
        with pytest.raises(SystemExit):
            self._run_main(runner, monkeypatch, ["--run", "1", "--condition", "random", "--dry-run"])

    def test_unknown_condition_rejected(self, runner, monkeypatch):
        step = MagicMock()
        monkeypatch.setattr(runner, "step_run", step)
        with pytest.raises(SystemExit) as exc:
            self._run_main(runner, monkeypatch, ["--run", "1", "--condition", "bogus"])
        assert exc.value.code == 2
        step.assert_not_called()

    def test_parity_mismatch_aborts_before_running(self, runner, monkeypatch):
        agg = runner.RESULTS_DIR / "aggregate.json"
        agg.parent.mkdir(parents=True)
        agg.write_text(json.dumps({"model": runner.MODEL, "turn_budget": 40, "series": []}))
        step = MagicMock()
        monkeypatch.setattr(runner, "step_run", step)
        with pytest.raises(SystemExit):
            self._run_main(runner, monkeypatch,
                           ["--run", "1", "--condition", "control", "--max-turns", "30"])
        step.assert_not_called()

    def test_matching_settings_proceed(self, runner, monkeypatch):
        agg = runner.RESULTS_DIR / "aggregate.json"
        agg.parent.mkdir(parents=True)
        agg.write_text(json.dumps({"model": runner.MODEL, "turn_budget": 40, "series": []}))
        step = MagicMock(return_value=None)
        monkeypatch.setattr(runner, "step_run", step)
        self._run_main(runner, monkeypatch, ["--run", "1", "--condition", "control"])
        assert step.call_args.kwargs["condition"] == "control"


class TestMultiSeriesMain:
    """End-to-end through main(): fresh KB per AgentLore series, per-series dirs, match-series wiring."""

    def _go(self, runner, monkeypatch, argv):
        monkeypatch.setattr(sys, "argv", ["run.py", *argv])
        monkeypatch.setattr(runner, "_write_comparison", lambda *a, **k: None)
        monkeypatch.setattr(runner, "_print_series_summary", lambda *a, **k: None)
        monkeypatch.setattr(runner, "_cleanup_all_workdirs", lambda: None)
        monkeypatch.setattr(runner, "_cleanup_series_gists", lambda: None)
        runner.main()

    def test_agentlore_resets_db_exactly_once_per_series(self, runner, monkeypatch):
        self._go(runner, monkeypatch, ["--series", "2", "--condition", "agentlore"])
        assert runner._clear_db.call_count == 2          # one per series, not per run
        agg = json.loads((runner.RESULTS_DIR / "aggregate.json").read_text())
        assert [s["series_id"] for s in agg["series"]] == [1, 2]
        assert all(len(s["runs"]) == 10 for s in agg["series"])
        assert (runner.RESULTS_DIR / "series_001").is_dir()
        assert (runner.RESULTS_DIR / "series_002").is_dir()

    @pytest.mark.parametrize("cond", ["control", "random"])
    def test_baselines_never_reset_or_use_lore(self, runner, monkeypatch, cond):
        self._go(runner, monkeypatch,
                 ["--series", "2", "--condition", cond, "--random-target-tokens", "300"])
        runner._clear_db.assert_not_called()
        runner.run_wrapup_phase.assert_not_called()
        root = runner.RESULTS_DIR / cond
        assert (root / "series_001").is_dir() and (root / "series_002").is_dir()
        agg = json.loads((root / "aggregate.json").read_text())
        assert {s["condition"] for s in agg["series"]} == {cond}
        assert not (runner.RESULTS_DIR / "aggregate.json").exists()   # no leakage into agentlore

    def test_random_match_series_uses_recorded_relevant_tokens(self, runner, monkeypatch):
        runs = [{"run": r, "context_tokens": 200 * r} for r in range(1, 11)]
        runs2 = [{"run": r, "context_tokens": 100 * r} for r in range(1, 11)]
        agg = runner.RESULTS_DIR / "aggregate.json"
        agg.parent.mkdir(parents=True)
        agg.write_text(json.dumps({
            "model": runner.MODEL, "turn_budget": 40,
            "series": [{"series_id": 3, "runs": runs}, {"series_id": 4, "runs": runs2}]}))
        self._go(runner, monkeypatch,
                 ["--series", "2", "--start-series", "1", "--condition", "random",
                  "--match-series", "3"])
        data = json.loads((runner.RESULTS_DIR / "random" / "aggregate.json").read_text())
        by_id = {s["series_id"]: s for s in data["series"]}
        # random series 1 matches relevant series 3, random series 2 matches relevant series 4
        assert by_id[1]["runs"][1]["random_target_tokens"] == 400
        assert by_id[2]["runs"][1]["random_target_tokens"] == 200
        for s in data["series"]:
            for r in s["runs"]:
                if r["random_target_tokens"]:
                    assert abs(r["context_tokens"] - r["random_target_tokens"]) \
                        <= r["random_target_tokens"] * bc.TOKEN_TOLERANCE
        # per-(series, run) seeds are recorded and distinct
        seeds = {r["random_seed"] for s in data["series"] for r in s["runs"]}
        assert len(seeds) == 20

    def test_failed_runs_are_listed_not_dropped(self, runner, monkeypatch):
        """A crash (e.g. InfeasibleMatch) mid-series is recorded in aggregate.json."""
        real = runner.step_run

        def flaky(run_num, *a, **k):
            if run_num == 3:
                raise bc.InfeasibleMatch("pool too small for run 3")
            if run_num == 5:
                return None
            return real(run_num, *a, **k)

        monkeypatch.setattr(runner, "step_run", flaky)
        self._go(runner, monkeypatch, ["--series", "1", "--condition", "agentlore"])
        agg = json.loads((runner.RESULTS_DIR / "aggregate.json").read_text())
        series = agg["series"][0]
        assert len(series["runs"]) == 8
        failed = {f["run"]: f for f in series["failed_runs"]}
        assert set(failed) == {3, 5}
        assert failed[3]["error_type"] == "InfeasibleMatch"
        assert "pool too small" in failed[3]["reason"]
        assert failed[5]["error_type"] == "NoResult"

    def test_series_with_only_failures_still_recorded(self, runner, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("llm down")

        monkeypatch.setattr(runner, "step_run", boom)
        self._go(runner, monkeypatch, ["--series", "1", "--condition", "agentlore"])
        agg = json.loads((runner.RESULTS_DIR / "aggregate.json").read_text())
        assert agg["series"][0]["runs"] == []
        assert len(agg["series"][0]["failed_runs"]) == 10

    def test_rerun_of_a_series_replaces_not_duplicates(self, runner, monkeypatch):
        self._go(runner, monkeypatch, ["--series", "2", "--condition", "agentlore"])
        self._go(runner, monkeypatch, ["--series", "1", "--start-series", "2", "--condition", "agentlore"])
        agg = json.loads((runner.RESULTS_DIR / "aggregate.json").read_text())
        assert [s["series_id"] for s in agg["series"]] == [1, 2]

    def test_runs_jsonl_written_per_run_and_reset_on_series_restart(self, runner, monkeypatch):
        self._go(runner, monkeypatch, ["--series", "1", "--condition", "agentlore"])
        f = runner.RESULTS_DIR / "series_001" / "runs.jsonl"
        recs = [json.loads(line) for line in f.read_text().splitlines()]
        assert [r["run"] for r in recs] == list(range(1, 11))
        assert {r["condition"] for r in recs} == {"agentlore"}
        self._go(runner, monkeypatch, ["--series", "1", "--condition", "agentlore"])
        assert len(f.read_text().splitlines()) == 10        # truncated, not appended

    def test_random_run_is_reproducible_across_invocations(self, runner, tmp_path):
        a = runner.step_run(2, False, False, output_dir=tmp_path / "a", series_num=2,
                            condition="random", random_target_tokens=900, random_seed=11)
        b = runner.step_run(2, False, False, output_dir=tmp_path / "b", series_num=2,
                            condition="random", random_target_tokens=900, random_seed=11)
        c = runner.step_run(2, False, False, output_dir=tmp_path / "c", series_num=3,
                            condition="random", random_target_tokens=900, random_seed=11)
        assert a["random_concepts"] == b["random_concepts"]
        assert a["random_seed"] == b["random_seed"] != c["random_seed"]

    def test_random_selection_never_contains_task_related_concepts(self, runner, tmp_path):
        pool = {c["name"]: c for c in bc.load_pool()}
        for seed in range(10):
            res = runner.step_run(2, False, False, output_dir=tmp_path, condition="random",
                                  random_target_tokens=1200, random_seed=seed)
            assert res["random_concepts"]
            assert not any(bc.is_task_related(pool[n]) for n in res["random_concepts"])

    @pytest.mark.parametrize("cond", ["agentlore", "control", "random"])
    def test_parity_checked_for_every_condition(self, runner, monkeypatch, cond):
        other = "control" if cond != "control" else "random"
        agg = bc.condition_results_dir(runner.RESULTS_DIR, other) / "aggregate.json"
        agg.parent.mkdir(parents=True)
        agg.write_text(json.dumps({"settings": {"model": runner.MODEL, "turn_budget": 25}}))
        step = MagicMock()
        monkeypatch.setattr(runner, "step_run", step)
        monkeypatch.setattr(sys, "argv", ["run.py", "--run", "1", "--condition", cond,
                                          "--random-target-tokens", "300"])
        with pytest.raises(SystemExit):
            runner.main()
        step.assert_not_called()

    def test_task_change_detected_via_hash(self, runner, monkeypatch):
        fp_old = bc.settings_fingerprint("old task", runner.MODEL, 40)
        agg = runner.RESULTS_DIR / "control" / "aggregate.json"
        agg.parent.mkdir(parents=True)
        agg.write_text(json.dumps({"settings": fp_old, "series": []}))
        step = MagicMock()
        monkeypatch.setattr(runner, "step_run", step)
        monkeypatch.setattr(sys, "argv", ["run.py", "--run", "1", "--condition", "agentlore"])
        with pytest.raises(SystemExit):
            runner.main()
        step.assert_not_called()
