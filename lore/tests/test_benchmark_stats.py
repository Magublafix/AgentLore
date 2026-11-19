"""Tests for bench_stats.py (LORE-052) using synthetic data with known effects."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest

BENCH = Path(__file__).parents[2] / "samples" / "stlgen" / "benchmarks"
# Import the production module without leaving BENCH on sys.path afterwards.
sys.path.insert(0, str(BENCH))
try:
    import bench_stats as bs  # noqa: E402
finally:
    sys.path.remove(str(BENCH))


def simulate(cond="agentlore", n_series=40, n_runs=10, b0=-0.5, slope=0.0, cond_effect=0.0,
             sigma=1.0, seed=0, start_id=1):
    rng = np.random.default_rng(seed)
    obs = []
    for s in range(n_series):
        u = rng.normal(0, sigma)
        for r in range(1, n_runs + 1):
            eta = b0 + slope * (r - 1) + cond_effect + u
            obs.append(bs.Observation(cond, start_id + s, r, bool(rng.random() < 1 / (1 + np.exp(-eta)))))
    return obs


class TestMixedLogit:
    def test_recovers_known_run_effect_and_sigma(self):
        """Replicated recovery of the run slope (0.3) and sigma (1.0), loose bounds."""
        coefs, sigmas, hits = [], [], 0
        for k in range(8):
            fit = bs.fit_mixed_logit(simulate(n_series=40, slope=0.3, sigma=1.0, seed=300 + k))
            i = fit.names.index("run")
            coefs.append(fit.coef[i])
            sigmas.append(fit.sigma)
            hits += fit.ci_low[i] < 0.3 < fit.ci_high[i]
            assert fit.converged and fit.n_series == 40 and fit.n_obs == 400
        assert abs(np.mean(coefs) - 0.3) < 0.12
        assert 0.6 < np.mean(sigmas) < 1.5
        assert hits >= 6                      # nominal 95% coverage, loose bound for 8 replicates

    def test_null_run_effect_ci_covers_zero(self):
        """Replicated null: the run CI covers 0 in most datasets (nominal 95%; >=8/10 is loose)."""
        hits = 0
        for k in range(10):
            fit = bs.fit_mixed_logit(simulate(n_series=30, slope=0.0, seed=700 + k))
            i = fit.names.index("run")
            hits += fit.ci_low[i] < 0 < fit.ci_high[i]
        assert hits >= 8

    def test_recovers_condition_effect(self):
        """Replicated recovery: a single dataset misses a 95% CI ~5% of the time by design."""
        est, hits = [], 0
        for k in range(6):
            obs = (simulate("control", 40, seed=100 + k) +
                   simulate("agentlore", 40, cond_effect=1.2, seed=500 + k))
            fit = bs.fit_mixed_logit(obs, reference="control")
            i = fit.names.index("condition[agentlore]")
            est.append(fit.coef[i])
            hits += fit.ci_low[i] < 1.2 < fit.ci_high[i]
        assert abs(np.mean(est) - 1.2) < 0.3
        assert hits >= 4                          # nominal 95% coverage, loose bound for n=6

    def test_default_reference_is_control(self):
        obs = simulate("agentlore", 5, seed=1) + simulate("control", 5, seed=2)
        assert "condition[agentlore]" in bs.fit_mixed_logit(obs).names

    def test_condition_se_reflects_between_series_variance(self):
        """With large sigma the condition SE must far exceed the naive independence SE.

        The naive SE is that of the log odds ratio of the pooled 2x2 table, which treats every
        run as an independent observation. Ten correlated runs per series carry far less
        information, so the mixed model's SE must be several times larger.
        """
        obs = (simulate("control", 30, sigma=2.0, seed=5) +
               simulate("agentlore", 30, sigma=2.0, seed=6))
        fit = bs.fit_mixed_logit(obs, reference="control")
        counts = {}
        for cond in ("control", "agentlore"):
            passed = sum(o.passed for o in obs if o.condition == cond)
            counts[cond] = (passed, 300 - passed)
        naive_se = np.sqrt(sum(1 / n for pair in counts.values() for n in pair))
        assert fit.sigma > 1.0
        assert fit.se[fit.names.index("condition[agentlore]")] > 2 * naive_se

    def test_separation_stays_finite(self):
        obs = simulate("control", 10, b0=-30, seed=1) + simulate("agentlore", 10, b0=0, seed=2)
        fit = bs.fit_mixed_logit(obs, reference="control")
        assert np.all(np.isfinite(fit.coef))

    def test_no_between_series_variance_flagged(self):
        fit = bs.fit_mixed_logit(simulate(n_series=40, sigma=0.0, seed=6))
        assert fit.sigma < 0.5
        assert fit.sigma_at_bound
        assert any("variance" in n for n in fit.notes)

    def test_errors(self):
        with pytest.raises(ValueError):
            bs.fit_mixed_logit([])
        with pytest.raises(ValueError, match="two series"):
            bs.fit_mixed_logit(simulate(n_series=1))

    def test_same_series_id_in_two_conditions_are_distinct_clusters(self):
        obs = simulate("control", 3, seed=1) + simulate("agentlore", 3, seed=2)
        assert bs.fit_mixed_logit(obs).n_series == 6


class TestPermutation:
    def test_detects_known_trend(self):
        """Pinned-seed regression test (seeds fixed in simulate and permutation_test)."""
        res = bs.permutation_test(simulate(n_series=40, slope=0.4, seed=7), n_perm=2000, seed=1)
        assert res["p_value"] < 0.01 and res["statistic"] > 0

    def test_trend_detected_across_replicates(self):
        sig = sum(bs.permutation_test(simulate(n_series=40, slope=0.4, seed=800 + k),
                                      n_perm=300, seed=1)["p_value"] < 0.05 for k in range(5))
        assert sig >= 4

    def test_null_rarely_significant(self):
        """Replicated null: false positives at alpha=0.05 should be rare (expected 0.4 of 8)."""
        fp = sum(bs.permutation_test(simulate(n_series=40, slope=0.0, seed=900 + k),
                                     n_perm=300, seed=1)["p_value"] < 0.05 for k in range(8))
        assert fp <= 2

    def test_deterministic_with_seed(self):
        obs = simulate(n_series=10, slope=0.2, seed=9)
        assert bs.permutation_test(obs, 300, seed=4) == bs.permutation_test(obs, 300, seed=4)

    def test_permutes_within_series_only(self):
        """Near-constant series with very different base rates and a small consistent
        within-series trend: only a within-series permutation has a null narrow enough to detect it.

        Half the series are all-fail, half all-pass; three of each have a single flipped run
        (a pass at run 10 / a fail at run 1), both a positive within-series trend. Shuffling
        outcomes across series would mix the 0/1 series together, inflate the null variance and
        give p ~ 0.3-0.5 (verified with a throwaway cross-series shuffle).
        """
        obs = []
        for s in range(40):
            for r in range(1, 11):
                if s % 2 == 0:
                    passed = r == 10 and s < 6
                else:
                    passed = not (r == 1 and s < 6)
                obs.append(bs.Observation("c", s, r, passed))
        res = bs.permutation_test(obs, n_perm=500, seed=0)
        assert res["statistic"] > 0
        assert res["p_value"] < 0.01

    def test_between_series_differences_alone_not_significant(self):
        """Wildly different series base rates with no within-series trend must not look significant."""
        rng = np.random.default_rng(3)
        obs = [bs.Observation("c", s, r, bool(rng.random() < (0.05 if s % 2 else 0.95)))
               for s in range(40) for r in range(1, 11)]
        assert bs.permutation_test(obs, n_perm=500, seed=0)["p_value"] > 0.05

    def test_p_value_never_zero(self):
        obs = [bs.Observation("c", s, r, r > 5) for s in range(10) for r in range(1, 11)]
        res = bs.permutation_test(obs, n_perm=200, seed=0)
        assert res["p_value"] == pytest.approx(1 / 201)

    def test_bootstrap_ci_brackets_estimate_and_is_tight(self):
        obs = simulate(n_series=60, slope=0.4, seed=10)
        est = bs.permutation_test(obs, n_perm=10, seed=0)["statistic"]
        lo, hi = bs.bootstrap_ci(obs, n_boot=500, seed=1)
        assert 0 < lo < est < hi
        assert hi - lo < 0.08                       # observed width ~0.023
        lo50, hi50 = bs.bootstrap_ci(obs, n_boot=500, seed=1, level=0.5)
        assert lo < lo50 < hi50 < hi                # higher level -> strictly wider interval
        assert bs.bootstrap_ci(obs, n_boot=200, seed=2) == bs.bootstrap_ci(obs, n_boot=200, seed=2)

    def test_constant_runs_zero_statistic(self):
        obs = [bs.Observation("c", s, 1, True) for s in range(3)]
        assert bs.permutation_test(obs, 50)["statistic"] == 0.0


class TestLoadAndReport:
    def _write(self, d: Path, series):
        d.mkdir(parents=True, exist_ok=True)
        (d / "aggregate.json").write_text(json.dumps({"series": series}))

    def test_load_all_conditions(self, tmp_path):
        runs = lambda *p: [{"run": i + 1, "tests_passed": v} for i, v in enumerate(p)]
        self._write(tmp_path, [{"series_id": 1, "runs": runs(True, False)}])
        self._write(tmp_path / "control", [{"series_id": 1, "runs": runs(False)}])
        self._write(tmp_path / "random", [{"series_id": 1, "runs": [{"run": 1}]}])  # skipped: no outcome
        obs = bs.load_observations(tmp_path)
        assert [(o.condition, o.series, o.run, o.passed) for o in obs] == [
            ("agentlore", 1, 1, True), ("agentlore", 1, 2, False), ("control", 1, 1, False)]

    def test_load_missing_dir_empty(self, tmp_path):
        assert bs.load_observations(tmp_path) == []

    def test_report_states_assumptions_and_cis(self, tmp_path):
        obs = simulate("agentlore", 12, slope=0.3, seed=11) + simulate("control", 12, seed=12)
        for cond in ("agentlore", "control"):
            series = {}
            for o in obs:
                if o.condition == cond:
                    series.setdefault(o.series, []).append({"run": o.run, "tests_passed": o.passed})
            self._write(bs.condition_results_dir(tmp_path, cond),
                        [{"series_id": k, "runs": v} for k, v in series.items()])
        text = bs.format_report(bs.analyse(tmp_path, n_perm=200))
        assert "## Assumptions" in text
        assert "runs within a series are correlated" in text
        assert "Series (not runs) are the independent units" in text
        assert "95% CI" in text and "condition[agentlore]" in text
        assert "Bootstrap 95% CI" in text and "| control |" in text

    def test_analyse_single_series_skips_models(self, tmp_path):
        self._write(tmp_path, [{"series_id": 1, "runs": [{"run": 1, "tests_passed": True}]}])
        rep = bs.analyse(tmp_path, n_perm=10)
        assert "mixed_logit" not in rep and rep["n_obs"] == 1
        assert "Assumptions" in bs.format_report(rep)

    def test_baseline_on_real_ten_series_data(self):
        results = Path(__file__).parents[2] / "samples" / "stlgen" / "results"
        if not (results / "aggregate.json").exists():
            pytest.skip("baseline data absent")
        rep = bs.analyse(results, n_perm=200)
        assert rep["mixed_logit"]["n_series"] >= 10
        assert "agentlore" in rep["permutation"]
        text = bs.format_report(rep)
        assert "| Term | Estimate | SE | 95% CI | Odds ratio |" in text
        # the run coefficient row carries a CI bracket and an odds ratio
        assert re.search(r"\| run \| -?\d+\.\d+ \| \d+\.\d+ \| \[-?\d+\.\d+, -?\d+\.\d+\] \| \d+\.\d+ \|", text)
        assert re.search(r"\| agentlore \| [+-]\d+\.\d+ \| \[[+-]\d", text)  # bootstrap CI row
