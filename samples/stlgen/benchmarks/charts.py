#!/usr/bin/env python3
"""
Generate SVG charts from Lore benchmark aggregate results.

Reads results/aggregate.json (written by run.py --series N) and produces four
SVG charts in results/charts/:

  pass_rate_by_run.svg       — pass rate per run position across all series
  turns_vs_concepts.svg      — scatter: turns used vs Lore concepts available
  token_cost_vs_concepts.svg — mean total tokens vs concepts available (binned)
  elapsed_vs_concepts.svg    — mean elapsed minutes vs concepts available (binned)

Usage:
  python benchmarks/charts.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

RESULTS_DIR = Path(__file__).parent.parent / "results"
CHARTS_DIR  = RESULTS_DIR / "charts"
AGG_FILE    = RESULTS_DIR / "aggregate.json"

# ---------------------------------------------------------------------------
# Colour palette — works in both light and dark GitHub themes
# ---------------------------------------------------------------------------

_PASS_COLOUR = "#2da44e"   # GitHub green
_FAIL_COLOUR = "#cf222e"   # GitHub red
_LINE_COLOUR = "#0969da"   # GitHub blue
_SHADE_COLOUR = "#0969da22"  # Translucent blue for shading
_GRID_COLOUR = "#d0d7de"   # Light grey grid
_TEXT_COLOUR = "#24292f"   # Near-black text
_BG_COLOUR   = "none"      # Transparent background (looks fine on light + dark)

# ---------------------------------------------------------------------------
# Minimal SVG builder — no third-party deps beyond matplotlib + numpy
# ---------------------------------------------------------------------------

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np
    _HAS_MPLNP = True
except ImportError:
    _HAS_MPLNP = False


def _apply_minimal_style(ax: "plt.Axes", title: str, subtitle: str = "") -> None:
    """Apply a clean, minimal style to a matplotlib axes object."""
    ax.set_facecolor(_BG_COLOUR)
    ax.figure.patch.set_alpha(0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(_GRID_COLOUR)
    ax.spines["bottom"].set_color(_GRID_COLOUR)
    ax.tick_params(colors=_TEXT_COLOUR, labelsize=9)
    ax.xaxis.label.set_color(_TEXT_COLOUR)
    ax.yaxis.label.set_color(_TEXT_COLOUR)
    ax.yaxis.grid(True, color=_GRID_COLOUR, linewidth=0.5, linestyle="--", zorder=0)
    ax.set_axisbelow(True)
    full_title = f"{title}\n{subtitle}" if subtitle else title
    ax.set_title(full_title, color=_TEXT_COLOUR, fontsize=11, fontweight="bold", pad=10)


# ---------------------------------------------------------------------------
# Data extraction
# ---------------------------------------------------------------------------

def _load_aggregate() -> dict:
    """Load and return the aggregate JSON data.

    Returns:
        Parsed JSON dict.

    Raises:
        SystemExit: If the file does not exist or is malformed.
    """
    if not AGG_FILE.exists():
        print(
            f"No aggregate data found at {AGG_FILE}.\n"
            "Run `python benchmarks/run.py --series N` to generate benchmark data first.",
            file=sys.stderr,
        )
        sys.exit(0)

    try:
        data = json.loads(AGG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Failed to read {AGG_FILE}: {exc}", file=sys.stderr)
        sys.exit(1)

    return data


def _all_runs(data: dict) -> list[dict]:
    """Flatten all run records from all series into a single list."""
    runs: list[dict] = []
    for series in data.get("series", []):
        runs.extend(series.get("runs", []))
    return runs


# ---------------------------------------------------------------------------
# Chart 1 — Pass rate by run position
# ---------------------------------------------------------------------------

def chart_pass_rate_by_run(data: dict, out_dir: Path) -> Path:
    """Line chart of pass rate per run position across all series.

    Args:
        data: Parsed aggregate JSON.
        out_dir: Directory to write the SVG into.

    Returns:
        Path to the written SVG file.
    """
    series_list = data.get("series", [])
    n_series = len(series_list)

    # Determine max run count
    max_run = max(
        (r["run"] for s in series_list for r in s.get("runs", [])),
        default=0,
    )
    if max_run == 0:
        print("  [warn] no run data found for pass_rate_by_run chart", file=sys.stderr)
        return out_dir / "pass_rate_by_run.svg"

    run_positions = list(range(1, max_run + 1))
    pass_rates: list[float] = []

    for run_idx in run_positions:
        matching = [
            r
            for s in series_list
            for r in s.get("runs", [])
            if r["run"] == run_idx
        ]
        if not matching:
            pass_rates.append(0.0)
        else:
            rate = sum(1 for r in matching if r["tests_passed"]) / len(matching) * 100
            pass_rates.append(rate)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(
        run_positions, pass_rates,
        color=_LINE_COLOUR, linewidth=2, marker="o", markersize=6, zorder=3,
    )
    for x, y in zip(run_positions, pass_rates):
        ax.annotate(
            f"{y:.0f}%",
            (x, y),
            textcoords="offset points", xytext=(0, 8),
            ha="center", fontsize=8, color=_TEXT_COLOUR,
        )

    ax.set_xlabel("Run Number", fontsize=10)
    ax.set_ylabel("Pass Rate (%)", fontsize=10)
    ax.set_xticks(run_positions)
    ax.set_ylim(-5, 110)
    ax.axhline(50, color=_GRID_COLOUR, linewidth=0.8, linestyle=":")

    _apply_minimal_style(
        ax,
        title="Pass Rate by Run — Lore Knowledge Accumulates",
        subtitle=f"N={n_series} series",
    )

    out_path = out_dir / "pass_rate_by_run.svg"
    fig.savefig(out_path, format="svg", bbox_inches="tight", transparent=True)
    plt.close(fig)
    return out_path


# ---------------------------------------------------------------------------
# Chart 2 — Turns vs concepts available (scatter)
# ---------------------------------------------------------------------------

def chart_turns_vs_concepts(data: dict, out_dir: Path) -> Path:
    """Scatter chart: turns used in main loop vs Lore concepts available.

    Args:
        data: Parsed aggregate JSON.
        out_dir: Directory to write the SVG into.

    Returns:
        Path to the written SVG file.
    """
    runs = _all_runs(data)
    if not runs:
        print("  [warn] no run data for turns_vs_concepts chart", file=sys.stderr)
        return out_dir / "turns_vs_concepts.svg"

    pass_x = [r["concepts_available"] for r in runs if r["tests_passed"]]
    pass_y = [r["turns_main"]         for r in runs if r["tests_passed"]]
    fail_x = [r["concepts_available"] for r in runs if not r["tests_passed"]]
    fail_y = [r["turns_main"]         for r in runs if not r["tests_passed"]]

    n_pass = len(pass_x)
    n_fail = len(fail_x)

    fig, ax = plt.subplots(figsize=(8, 4.5))

    if fail_x:
        ax.scatter(fail_x, fail_y, color=_FAIL_COLOUR, s=55, alpha=0.75, zorder=3, label=f"FAIL (n={n_fail})")
    if pass_x:
        ax.scatter(pass_x, pass_y, color=_PASS_COLOUR, s=55, alpha=0.75, zorder=3, label=f"PASS (n={n_pass})")

    ax.set_xlabel("Lore Concepts Available at Run Start", fontsize=10)
    ax.set_ylabel("Turns Used (Main Loop)", fontsize=10)
    ax.legend(fontsize=9, frameon=False, labelcolor=_TEXT_COLOUR)

    _apply_minimal_style(
        ax,
        title="Turns to Solve vs Lore Concepts Available",
    )

    out_path = out_dir / "turns_vs_concepts.svg"
    fig.savefig(out_path, format="svg", bbox_inches="tight", transparent=True)
    plt.close(fig)
    return out_path


# ---------------------------------------------------------------------------
# Chart 3 & 4 — Token cost / elapsed time vs concepts (binned line charts)
# ---------------------------------------------------------------------------

_BINS = [
    (0,  0,   "0"),
    (1,  5,   "1-5"),
    (6,  10,  "6-10"),
    (11, 15,  "11-15"),
    (16, 20,  "16-20"),
    (21, None, "21+"),
]


def _bin_label(concepts: int) -> str:
    """Return the bin label string for a concepts_available value."""
    for lo, hi, label in _BINS:
        if hi is None and concepts >= lo:
            return label
        if hi is not None and lo <= concepts <= hi:
            return label
    return "?"


def _bin_data(runs: list[dict], y_field: str, scale: float = 1.0) -> tuple[list[str], list[float], list[float]]:
    """Group run values by concept bin and compute mean + std.

    Args:
        runs: List of run result dicts.
        y_field: Key in the run dict to aggregate.
        scale: Multiplier applied to each value before aggregation.

    Returns:
        Tuple of (bin_labels, means, stds) for bins with data.
    """
    from collections import defaultdict
    groups: dict[str, list[float]] = defaultdict(list)
    for r in runs:
        label = _bin_label(r["concepts_available"])
        groups[label].append(r[y_field] * scale)

    labels: list[str] = []
    means:  list[float] = []
    stds:   list[float] = []

    for _, _, label in _BINS:
        if label in groups:
            vals = groups[label]
            labels.append(label)
            means.append(float(np.mean(vals)))
            stds.append(float(np.std(vals)))

    return labels, means, stds


def chart_token_cost_vs_concepts(data: dict, out_dir: Path) -> Path:
    """Line chart: mean total tokens vs Lore concepts available (binned).

    Args:
        data: Parsed aggregate JSON.
        out_dir: Directory to write the SVG into.

    Returns:
        Path to the written SVG file.
    """
    runs = _all_runs(data)
    if not runs:
        print("  [warn] no run data for token_cost_vs_concepts chart", file=sys.stderr)
        return out_dir / "token_cost_vs_concepts.svg"

    labels, means, stds = _bin_data(runs, "total_tokens")
    if not labels:
        return out_dir / "token_cost_vs_concepts.svg"

    xs = list(range(len(labels)))
    means_arr = np.array(means)
    stds_arr  = np.array(stds)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.fill_between(
        xs,
        means_arr - stds_arr,
        means_arr + stds_arr,
        alpha=0.18, color=_LINE_COLOUR, zorder=2,
    )
    ax.plot(xs, means_arr, color=_LINE_COLOUR, linewidth=2, marker="o", markersize=6, zorder=3)

    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_xlabel("Lore Concepts Available (binned)", fontsize=10)
    ax.set_ylabel("Total Tokens (mean ± 1 std)", fontsize=10)

    _apply_minimal_style(ax, title="Token Cost vs Lore Concepts Available")

    out_path = out_dir / "token_cost_vs_concepts.svg"
    fig.savefig(out_path, format="svg", bbox_inches="tight", transparent=True)
    plt.close(fig)
    return out_path


def chart_elapsed_vs_concepts(data: dict, out_dir: Path) -> Path:
    """Line chart: mean elapsed time (minutes) vs Lore concepts available (binned).

    Args:
        data: Parsed aggregate JSON.
        out_dir: Directory to write the SVG into.

    Returns:
        Path to the written SVG file.
    """
    runs = _all_runs(data)
    if not runs:
        print("  [warn] no run data for elapsed_vs_concepts chart", file=sys.stderr)
        return out_dir / "elapsed_vs_concepts.svg"

    # Scale elapsed seconds → minutes
    labels, means, stds = _bin_data(runs, "elapsed", scale=1.0 / 60.0)
    if not labels:
        return out_dir / "elapsed_vs_concepts.svg"

    xs = list(range(len(labels)))
    means_arr = np.array(means)
    stds_arr  = np.array(stds)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.fill_between(
        xs,
        means_arr - stds_arr,
        means_arr + stds_arr,
        alpha=0.18, color=_LINE_COLOUR, zorder=2,
    )
    ax.plot(xs, means_arr, color=_LINE_COLOUR, linewidth=2, marker="o", markersize=6, zorder=3)

    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_xlabel("Lore Concepts Available (binned)", fontsize=10)
    ax.set_ylabel("Elapsed Time (minutes, mean ± 1 std)", fontsize=10)

    _apply_minimal_style(ax, title="Time to Complete vs Lore Concepts Available")

    out_path = out_dir / "elapsed_vs_concepts.svg"
    fig.savefig(out_path, format="svg", bbox_inches="tight", transparent=True)
    plt.close(fig)
    return out_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Generate all four SVG charts from results/aggregate.json."""
    if not _HAS_MPLNP:
        print(
            "matplotlib and numpy are required to generate charts.\n"
            "Install them with: pip install matplotlib numpy",
            file=sys.stderr,
        )
        sys.exit(1)

    data = _load_aggregate()

    series_list = data.get("series", [])
    n_series = len(series_list)
    total_runs = sum(len(s.get("runs", [])) for s in series_list)

    if n_series < 10:
        print(
            f"[warn] Only {n_series} series found (fewer than 10). "
            "Charts will be generated with available data.",
            file=sys.stderr,
        )

    if total_runs == 0:
        print("No run data found in aggregate.json — nothing to chart.", file=sys.stderr)
        sys.exit(0)

    CHARTS_DIR.mkdir(parents=True, exist_ok=True)

    generators = [
        ("pass_rate_by_run.svg",       chart_pass_rate_by_run),
        ("turns_vs_concepts.svg",      chart_turns_vs_concepts),
        ("token_cost_vs_concepts.svg", chart_token_cost_vs_concepts),
        ("elapsed_vs_concepts.svg",    chart_elapsed_vs_concepts),
    ]

    written: list[str] = []
    for filename, fn in generators:
        try:
            out_path = fn(data, CHARTS_DIR)
            written.append(out_path.name)
        except Exception as exc:
            print(f"  [error] failed to generate {filename}: {exc}", file=sys.stderr)

    print(f"\nCharts written to {CHARTS_DIR}/:")
    for name in written:
        print(f"  {name}")


if __name__ == "__main__":
    main()
