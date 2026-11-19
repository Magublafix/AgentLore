"""Statistical analysis for the stlgen benchmark (LORE-052).

Runs inside one series are **not independent**: they share a task history and, for the AgentLore
condition, a growing knowledge database.  Treating the 10 runs of a series as 10 independent
Bernoulli trials overstates the evidence.  This module therefore provides:

1. ``fit_mixed_logit`` — logistic regression of pass/fail on run number and condition with a
   per-series random intercept, fitted by maximum marginal likelihood (adaptive-free Gauss–Hermite
   quadrature).  No statsmodels dependency: only numpy and scipy.
2. ``permutation_test`` — permutes outcomes *within* each series and tests the within-series
   run-number/success association; ``bootstrap_ci`` gives a series-level (cluster) bootstrap CI.

Assumptions (also printed in the report)
----------------------------------------
* Series are exchangeable draws within a condition; the unit of replication is the series.
* Mixed model: log-odds are linear in run number, the condition effect is constant across runs
  (no condition×run interaction), random intercepts are Normal.
* Fixed effects get a weak N(0, 10²) ridge prior so estimates stay finite under (quasi-)separation,
  e.g. a control condition that never passes.  Intervals are Wald intervals and are approximate
  with few series.
* Permutation test: under H0 the run order carries no information, so outcomes are exchangeable
  within a series.  It tests association only and says nothing about *why* (knowledge vs. practice).

CLI::

    python bench_stats.py --results ../results [--out ../results/analysis.md]
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import optimize, special, stats

try:  # reuse the layout definition when imported alongside the runner
    from bench_conditions import CONDITIONS, condition_results_dir
except ImportError:  # pragma: no cover - direct execution from another cwd
    CONDITIONS = ("agentlore", "control", "random")

    def condition_results_dir(results_dir: Path, condition: str) -> Path:
        return results_dir if condition == "agentlore" else results_dir / condition

RIDGE_VAR = 100.0
LOG_SIGMA_BOUNDS = (-6.0, 3.0)
ASSUMPTIONS = (
    "Series (not runs) are the independent units; runs within a series are correlated.",
    "Mixed model: log-odds linear in run number, constant condition effect, Normal random "
    "intercept per series, no condition×run interaction.",
    "Weak N(0, 10²) ridge prior on fixed effects; Wald 95% intervals, approximate for few series.",
    "Permutation test: outcomes exchangeable within a series under H0; association only, "
    "not causation.",
)


@dataclass
class Observation:
    """One benchmark run outcome."""
    condition: str
    series: int
    run: int
    passed: bool


@dataclass
class MixedFit:
    """Result of :func:`fit_mixed_logit`."""
    names: list[str]
    coef: np.ndarray
    se: np.ndarray
    ci_low: np.ndarray
    ci_high: np.ndarray
    sigma: float
    sigma_at_bound: bool
    n_obs: int
    n_series: int
    converged: bool
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "n_obs": self.n_obs, "n_series": self.n_series, "sigma": self.sigma,
            "converged": self.converged, "notes": self.notes,
            "coefficients": {
                n: {"estimate": float(c), "se": float(s), "ci95": [float(lo), float(hi)],
                    "odds_ratio": float(math.exp(c))}
                for n, c, s, lo, hi in zip(self.names, self.coef, self.se, self.ci_low, self.ci_high)
            },
        }


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_observations(results_dir: Path) -> list[Observation]:
    """Load every condition's ``aggregate.json`` under *results_dir*.

    The legacy root-level ``aggregate.json`` is the ``agentlore`` condition.  Runs lacking a
    ``tests_passed`` field are skipped.
    """
    obs: list[Observation] = []
    for cond in CONDITIONS:
        agg = condition_results_dir(results_dir, cond) / "aggregate.json"
        if not agg.exists():
            continue
        for s in json.loads(agg.read_text(encoding="utf-8")).get("series", []):
            for r in s.get("runs", []):
                if "tests_passed" in r:
                    obs.append(Observation(cond, int(s["series_id"]), int(r["run"]),
                                           bool(r["tests_passed"])))
    return obs


# ---------------------------------------------------------------------------
# Mixed-effects logistic regression
# ---------------------------------------------------------------------------

def _design(obs: list[Observation], reference: str | None):
    conds = sorted({o.condition for o in obs})
    ref = reference if reference in conds else ("control" if "control" in conds else conds[0])
    others = [c for c in conds if c != ref]
    names = ["intercept", "run"] + [f"condition[{c}]" for c in others]
    X = np.array(
        [[1.0, o.run - 1.0] + [1.0 if o.condition == c else 0.0 for c in others] for o in obs]
    )
    y = np.array([1.0 if o.passed else 0.0 for o in obs])
    keys = sorted({(o.condition, o.series) for o in obs})
    index = {k: i for i, k in enumerate(keys)}
    cluster = np.array([index[(o.condition, o.series)] for o in obs])
    return X, y, cluster, len(keys), names, ref


def _neg_log_lik(theta, X, y, C, nodes, logw):
    beta, log_sigma = theta[:-1], theta[-1]
    eta = X @ beta
    u = math.sqrt(2.0) * math.exp(log_sigma) * nodes                     # (K,)
    z = eta[:, None] + u[None, :]                                          # (N, K)
    ll = y[:, None] * z - np.logaddexp(0.0, z)
    cluster_ll = C @ ll                                                    # (J, K)
    marginal = special.logsumexp(cluster_ll + logw[None, :], axis=1)
    penalty = 0.5 * float(beta @ beta) / RIDGE_VAR
    return -float(marginal.sum()) + penalty


def _num_hessian(f, x, h=1e-4):
    n = len(x)
    H = np.zeros((n, n))
    for i in range(n):
        for j in range(i, n):
            ei, ej = np.eye(n)[i] * h, np.eye(n)[j] * h
            H[i, j] = H[j, i] = (f(x + ei + ej) - f(x + ei - ej) - f(x - ei + ej) + f(x - ei - ej)) / (4 * h * h)
    return H


def fit_mixed_logit(obs: list[Observation], reference: str | None = None,
                    n_quad: int = 25) -> MixedFit:
    """Fit ``logit P(pass) = b0 + b1*(run-1) + condition effects + u_series``.

    Args:
        obs: Observations; the random-effect cluster is ``(condition, series)``.
        reference: Reference condition (default ``control`` if present).
        n_quad: Gauss–Hermite nodes.

    Raises:
        ValueError: with fewer than two series, or if no data.
    """
    if not obs:
        raise ValueError("no observations")
    X, y, cluster, n_series, names, _ = _design(obs, reference)
    if n_series < 2:
        raise ValueError("need at least two series to estimate between-series variance")
    C = np.zeros((n_series, len(y)))
    C[cluster, np.arange(len(y))] = 1.0
    nodes, weights = np.polynomial.hermite.hermgauss(n_quad)
    logw = np.log(weights) - 0.5 * math.log(math.pi)

    p = X.shape[1]
    f = lambda th: _neg_log_lik(th, X, y, C, nodes, logw)
    best = None
    for start in (-0.5, 0.5):  # two starting values guard against a flat-sigma local optimum
        theta0 = np.concatenate([np.zeros(p), [start]])
        res = optimize.minimize(f, theta0, method="L-BFGS-B",
                                bounds=[(None, None)] * p + [LOG_SIGMA_BOUNDS])
        if best is None or res.fun < best.fun:
            best = res
    theta = best.x
    at_bound = bool(theta[-1] <= LOG_SIGMA_BOUNDS[0] + 1e-3)
    notes = []
    H = _num_hessian(f, theta)
    block = slice(0, p) if at_bound else slice(0, p + 1)
    if at_bound:
        notes.append("between-series variance estimated at ~0; standard errors are conditional on sigma≈0")
    try:
        cov = np.linalg.inv(H[block, block])
        se = np.sqrt(np.clip(np.diag(cov)[:p], 0, None))
    except np.linalg.LinAlgError:
        se = np.full(p, np.nan)
        notes.append("Hessian singular; standard errors unavailable")
    if not best.success:
        notes.append(f"optimizer did not fully converge: {best.message}")
    z = stats.norm.ppf(0.975)
    coef = theta[:p]
    return MixedFit(names, coef, se, coef - z * se, coef + z * se, math.exp(theta[-1]),
                    at_bound, len(y), n_series, bool(best.success), notes)


# ---------------------------------------------------------------------------
# Within-series permutation test
# ---------------------------------------------------------------------------

def _series_groups(obs: list[Observation]) -> list[tuple[np.ndarray, np.ndarray]]:
    groups: dict[tuple[str, int], list[Observation]] = {}
    for o in obs:
        groups.setdefault((o.condition, o.series), []).append(o)
    return [(np.array([o.run for o in g], float), np.array([o.passed for o in g], float))
            for g in groups.values()]


def _within_slope(groups) -> float:
    """Pooled within-series slope of success on run number."""
    num = den = 0.0
    for runs, y in groups:
        rc = runs - runs.mean()
        num += float(rc @ (y - y.mean()))
        den += float(rc @ rc)
    return num / den if den > 0 else 0.0


def permutation_test(obs: list[Observation], n_perm: int = 10000, seed: int = 0) -> dict:
    """Two-sided permutation test of the run-number/success relationship, permuting within series.

    Returns:
        ``{"statistic", "p_value", "n_perm", "n_series"}`` where ``statistic`` is the pooled
        within-series slope (change in P(pass) per run).  ``p = (extreme + 1) / (n_perm + 1)``.
    """
    groups = _series_groups(obs)
    rng = np.random.default_rng(seed)
    observed = _within_slope(groups)
    extreme = 0
    for _ in range(n_perm):
        perm = [(r, rng.permutation(y)) for r, y in groups]
        if abs(_within_slope(perm)) >= abs(observed) - 1e-12:
            extreme += 1
    return {"statistic": observed, "p_value": (extreme + 1) / (n_perm + 1),
            "n_perm": n_perm, "n_series": len(groups)}


def bootstrap_ci(obs: list[Observation], n_boot: int = 2000, seed: int = 0,
                 level: float = 0.95) -> tuple[float, float]:
    """Percentile CI for the pooled within-series slope, resampling whole series."""
    groups = _series_groups(obs)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(groups), len(groups))
        vals.append(_within_slope([groups[i] for i in idx]))
    a = (1 - level) / 2
    return float(np.quantile(vals, a)), float(np.quantile(vals, 1 - a))


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def condition_summary(obs: list[Observation]) -> dict[str, dict]:
    """Per-condition series count, run count and pass rate (conditions reported separately)."""
    out: dict[str, dict] = {}
    for cond in sorted({o.condition for o in obs}):
        rows = [o for o in obs if o.condition == cond]
        out[cond] = {
            "series": len({o.series for o in rows}),
            "runs": len(rows),
            "pass_rate": sum(o.passed for o in rows) / len(rows),
        }
    return out


def analyse(results_dir: Path, n_perm: int = 10000, seed: int = 0) -> dict:
    """Run the full analysis on the data under *results_dir*."""
    obs = load_observations(results_dir)
    report: dict = {"assumptions": list(ASSUMPTIONS), "n_obs": len(obs),
                    "conditions": condition_summary(obs)}
    if len({(o.condition, o.series) for o in obs}) >= 2:
        report["mixed_logit"] = fit_mixed_logit(obs).as_dict()
        report["permutation"] = {}
        for cond in report["conditions"]:
            rows = [o for o in obs if o.condition == cond]
            if len({o.series for o in rows}) >= 2:
                res = permutation_test(rows, n_perm=n_perm, seed=seed)
                res["slope_ci95_bootstrap"] = list(bootstrap_ci(rows, seed=seed))
                report["permutation"][cond] = res
    return report


def format_report(report: dict) -> str:
    """Render :func:`analyse` output as markdown."""
    lines = ["# Benchmark statistical analysis", "", "## Assumptions", ""]
    lines += [f"- {a}" for a in report["assumptions"]]
    lines += ["", "## Conditions", "", "| Condition | Series | Runs | Pass rate |", "|---|---|---|---|"]
    for c, s in report["conditions"].items():
        lines.append(f"| {c} | {s['series']} | {s['runs']} | {s['pass_rate']:.1%} |")
    m = report.get("mixed_logit")
    if m:
        lines += ["", "## Mixed-effects logistic regression (series random intercept)", "",
                  f"{m['n_obs']} runs in {m['n_series']} series; between-series SD σ = {m['sigma']:.3f}.", "",
                  "| Term | Estimate | SE | 95% CI | Odds ratio |", "|---|---|---|---|---|"]
        for n, c in m["coefficients"].items():
            lo, hi = c["ci95"]
            lines.append(f"| {n} | {c['estimate']:.3f} | {c['se']:.3f} | [{lo:.3f}, {hi:.3f}] | {c['odds_ratio']:.2f} |")
        lines += [f"", *[f"- Note: {n}" for n in m["notes"]]]
    perm = report.get("permutation")
    if perm:
        lines += ["", "## Within-series permutation test (run number vs. success)", "",
                  "| Condition | Slope / run | Bootstrap 95% CI (series) | p |", "|---|---|---|---|"]
        for c, r in perm.items():
            lo, hi = r["slope_ci95_bootstrap"]
            lines.append(f"| {c} | {r['statistic']:+.4f} | [{lo:+.4f}, {hi:+.4f}] | {r['p_value']:.4f} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", type=Path, default=Path(__file__).parent.parent / "results")
    ap.add_argument("--out", type=Path, help="write markdown here (default: stdout)")
    ap.add_argument("--n-perm", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    text = format_report(analyse(args.results, args.n_perm, args.seed))
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"Analysis → {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
