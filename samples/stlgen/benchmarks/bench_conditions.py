"""Experimental-condition helpers for the stlgen benchmark (LORE-050, LORE-051).

Pure logic, no network or LLM access, so it can be unit-tested directly.

Conditions
----------
``agentlore``  Relevant knowledge: the existing 10-run AgentLore series (search + capture + wrapup,
               fresh knowledge DB per series).  Called *relevant* in reports.
``control``    No AgentLore tools, concepts, capture or wrapup in any run.  Repeated attempts only.
``random``     No AgentLore tools.  The system prompt carries a seeded dump of *unrelated* concepts
               whose size matches the context the relevant condition supplied for the same
               series/run (token-matched within ``TOKEN_TOLERANCE``).

Token counts
------------
No tokenizer is available offline, so ``estimate_tokens`` uses ``ceil(chars / 4)``.  The same
estimator is applied to the relevant and the random context, so the *match* is meaningful even
though the absolute number is approximate.

Result layout
-------------
``results/``                       legacy location, holds the ``agentlore`` condition
``results/<condition>/``           ``control`` and ``random`` (``series_NNN/`` + ``aggregate.json``)
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from pathlib import Path

CONDITIONS = ("agentlore", "control", "random")
CONDITION_LABELS = {"agentlore": "relevant", "control": "none", "random": "random-context"}

TOKEN_TOLERANCE = 0.10
DEFAULT_SEED = 1812

# A pool concept is excluded when any of these appears in its name, tags or content.
# They cover everything the stlgen task (or the concepts captured for it) can touch.
TASK_KEYWORDS = (
    "stl", "mesh", "3d", "font", "glyph", "trimesh", "triangle", "extrude", "extrusion", "manifold",
    "watertight", "printing", "pillow", "numpy", "packaging", "pyproject", "setuptools",
    "entry point", "entry-point", "console_scripts", "pip install", "cli", "argparse", "pytest",
)

POOL_PATH = Path(__file__).parent / "random_pool.json"

PARITY_KEYS = ("task_sha256", "model", "turn_budget")


class ParityError(RuntimeError):
    """Raised when a condition's settings differ from another condition's."""


class InfeasibleMatch(RuntimeError):
    """Raised when no token-matched random selection exists within tolerance."""


# ---------------------------------------------------------------------------
# Settings parity (LORE-050)
# ---------------------------------------------------------------------------

def settings_fingerprint(task: str, model: str, turn_budget: int) -> dict:
    """Return the settings that must be identical across conditions."""
    return {
        "task_sha256": hashlib.sha256(task.encode("utf-8")).hexdigest(),
        "model": model,
        "turn_budget": int(turn_budget),
    }


def check_parity(candidate: dict, others: dict[str, dict]) -> None:
    """Fail fast if *candidate* settings differ from any other condition's.

    Keys absent from an ``others`` entry (legacy aggregates predate ``task_sha256``) are skipped,
    not treated as mismatches.

    Raises:
        ParityError: listing every differing key per condition.
    """
    problems = []
    for cond, settings in sorted(others.items()):
        for key in PARITY_KEYS:
            if key in settings and settings[key] != candidate.get(key):
                problems.append(f"{cond}.{key}={settings[key]!r} != {candidate.get(key)!r}")
    if problems:
        raise ParityError("settings differ across conditions: " + "; ".join(problems))


def condition_results_dir(results_dir: Path, condition: str) -> Path:
    """Directory holding a condition's series dirs and ``aggregate.json``."""
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition {condition!r}; expected one of {CONDITIONS}")
    return results_dir if condition == "agentlore" else results_dir / condition


def load_other_settings(results_dir: Path, condition: str) -> dict[str, dict]:
    """Read the recorded settings of every *other* condition that already has results."""
    found: dict[str, dict] = {}
    for other in CONDITIONS:
        if other == condition:
            continue
        agg = condition_results_dir(results_dir, other) / "aggregate.json"
        if not agg.exists():
            continue
        try:
            data = json.loads(agg.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        settings = dict(data.get("settings") or {})
        for key in ("model", "turn_budget"):  # legacy aggregates carry these at top level
            if key not in settings and key in data:
                settings[key] = data[key]
        found[other] = settings
    return found


# ---------------------------------------------------------------------------
# Random-context condition (LORE-051)
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Approximate token count (``ceil(chars / 4)``); see module docstring."""
    return math.ceil(len(text) / 4)


def concept_text(concept: dict) -> str:
    """Render one concept the way it appears in the random-context dump."""
    parts = [f"## {concept['name']} ({concept.get('type', 'pattern')})", concept["content"]]
    if concept.get("when_to_use"):
        parts.append(f"When to use: {concept['when_to_use']}")
    return "\n".join(parts)


def format_context(concepts: list[dict]) -> str:
    """Concatenate concepts into the text injected into the system prompt."""
    return "\n\n".join(concept_text(c) for c in concepts)


def is_task_related(concept: dict) -> bool:
    """True if the concept mentions any task keyword (case-insensitive, whole word, optional plural)."""
    haystack = " ".join(
        [concept.get("name", ""), concept.get("content", ""), concept.get("when_to_use", ""),
         " ".join(concept.get("tags", []))]
    ).lower()
    for kw in TASK_KEYWORDS:
        if re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?:s|es|ed|ing)?(?![a-z0-9])", haystack):
            return True
    return False


def load_pool(path: Path = POOL_PATH) -> list[dict]:
    """Load the unrelated-concept pool and drop anything task-related."""
    pool = json.loads(path.read_text(encoding="utf-8"))
    return [c for c in pool if not is_task_related(c)]


def select_random_context(
    pool: list[dict], target_tokens: int, seed: int, tolerance: float = TOKEN_TOLERANCE,
) -> tuple[list[dict], int]:
    """Pick pool concepts whose token total is within ``tolerance`` of ``target_tokens``.

    Deterministic for a given ``(pool, target_tokens, seed)``: the pool is shuffled with a
    seeded RNG and concepts are added greedily, skipping any that would overshoot the upper bound.

    Returns:
        ``(selected concepts, estimated tokens)``.  A target of 0 yields ``([], 0)``.

    Raises:
        InfeasibleMatch: if the pool cannot reach the tolerance band.
    """
    if target_tokens <= 0:
        return [], 0
    lo, hi = target_tokens * (1 - tolerance), target_tokens * (1 + tolerance)
    order = sorted(pool, key=lambda c: c["name"])  # stable base order before the seeded shuffle
    random.Random(seed).shuffle(order)
    chosen: list[dict] = []
    total = 0
    for c in order:
        t = estimate_tokens(concept_text(c)) + 1  # +1: blank-line separator
        if total + t <= hi:
            chosen.append(c)
            total += t
        if total >= lo:
            break
    if not lo <= total <= hi:
        raise InfeasibleMatch(
            f"pool of {len(pool)} concepts reaches {total} tokens; "
            f"cannot match {target_tokens} ±{tolerance:.0%}"
        )
    return chosen, total


def run_seed(base_seed: int, series: int, run: int) -> int:
    """Stable per-(series, run) seed derived from the base seed."""
    digest = hashlib.sha256(f"{base_seed}:{series}:{run}".encode()).hexdigest()
    return int(digest[:12], 16)


def relevant_context_tokens(results_dir: Path, series: int, run: int) -> int:
    """Look up the context tokens the relevant condition supplied for ``(series, run)``.

    Raises:
        InfeasibleMatch: if the reference series/run is not recorded.
    """
    agg = condition_results_dir(results_dir, "agentlore") / "aggregate.json"
    if not agg.exists():
        raise InfeasibleMatch(f"no relevant-condition results at {agg}")
    for s in json.loads(agg.read_text(encoding="utf-8")).get("series", []):
        if s.get("series_id") == series:
            for r in s.get("runs", []):
                if r.get("run") == run and "context_tokens" in r:
                    return int(r["context_tokens"])
    raise InfeasibleMatch(
        f"relevant series {series} run {run} has no recorded context_tokens "
        "(re-run it with this runner, or pass --random-target-tokens)"
    )
