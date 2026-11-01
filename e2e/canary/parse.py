"""Tolerant parser/asserter for `claude -p --output-format stream-json --verbose` logs.

UNTESTED against real output until the first live run (see e2e/CANARY.md).
Usage: python e2e/canary/parse.py LOG [--summary OUT] [--secret-env NAME]
Exit codes: 0 pass, 1 assertion failed, 2 secret found in log.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field

TOOL = "mcp__lore__search_concepts"
SEED_CONCEPT = "REST CLI around a REST API"


@dataclass
class Report:
    tool_called: bool = False
    tool_result_seen: bool = False
    tool_error: bool = False
    concept_found: bool = False
    result_seen: bool = False
    result_error: bool = False
    final_text: str = ""
    cost_usd: float | None = None
    malformed_lines: int = 0
    secret_found: bool = False
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures and not self.secret_found


def _blocks(event: dict) -> list[dict]:
    msg = event.get("message")
    content = msg.get("content") if isinstance(msg, dict) else event.get("content")
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _text(content) -> str:
    """tool_result content may be a string or a list of blocks (or None)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict):
                t = b.get("text")
                parts.append(t if isinstance(t, str) else json.dumps(b, ensure_ascii=False))
        return "\n".join(parts)
    return "" if content is None else json.dumps(content, ensure_ascii=False)


def analyze(raw: str, secret: str = "") -> Report:
    r = Report()
    if secret and secret in raw:
        r.secret_found = True
        r.failures.append("secret value present in log")
        return r
    ids: set[str] = set()
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            r.malformed_lines += 1
            continue
        if not isinstance(ev, dict):
            r.malformed_lines += 1
            continue
        etype = ev.get("type")
        if etype in ("assistant", "user"):
            for b in _blocks(ev):
                if b.get("type") == "tool_use" and b.get("name") == TOOL:
                    r.tool_called = True
                    if isinstance(b.get("id"), str):
                        ids.add(b["id"])
                elif b.get("type") == "tool_result":
                    tid = b.get("tool_use_id")
                    if tid in ids:
                        r.tool_result_seen = True
                        if b.get("is_error"):
                            r.tool_error = True
                        if SEED_CONCEPT in _text(b.get("content")):
                            r.concept_found = True
        elif etype == "result":
            r.result_seen = True
            r.result_error = bool(ev.get("is_error")) or (
                isinstance(ev.get("subtype"), str) and ev["subtype"] != "success"
            )
            if isinstance(ev.get("result"), str):
                r.final_text = ev["result"]
            c = ev.get("total_cost_usd", ev.get("cost_usd"))
            if isinstance(c, (int, float)):
                r.cost_usd = float(c)
    if not r.tool_called:
        r.failures.append(f"{TOOL} was never called")
    elif not r.tool_result_seen:
        r.failures.append("no tool_result matched the tool call")
    if r.tool_error:
        r.failures.append("tool_result reported is_error")
    if r.tool_result_seen and not r.tool_error and not r.concept_found:
        r.failures.append(f"tool_result lacks seed concept {SEED_CONCEPT!r}")
    if not r.result_seen:
        r.failures.append("no final result event")
    elif r.result_error:
        r.failures.append("final result event is an error")
    return r


_REJECT_MARKERS = (
    "issue with the selected model",
    "invalid model",
    "unknown model",
    "model not found",
    "model_not_found",
    "not_found_error",
)


def model_rejected(log_text: str, stderr_text: str = "") -> bool:
    """True only if stderr or an error result event says the model id was rejected.

    Deliberately ignores the benign `model` field of init/assistant events.
    """
    if any(m in stderr_text.lower() for m in _REJECT_MARKERS):
        return True
    for line in log_text.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict) or ev.get("type") != "result":
            continue
        if ev.get("is_error") or (isinstance(ev.get("subtype"), str) and ev["subtype"] != "success"):
            res = ev.get("result")
            if isinstance(res, str) and any(m in res.lower() for m in _REJECT_MARKERS):
                return True
    return False


def summary(r: Report) -> str:
    cost = f"{r.cost_usd:.4f}" if r.cost_usd is not None else "n/a"
    lines = [
        f"tool called: {r.tool_called}",
        f"tool result ok: {r.tool_result_seen and not r.tool_error}",
        f"seed concept seen: {r.concept_found}",
        f"final result error: {r.result_error if r.result_seen else 'no result event'}",
        f"cost usd: {cost}",
        f"malformed lines: {r.malformed_lines}",
        f"model text (informational): {r.final_text[:200]!r}",
        "RESULT: " + ("PASS" if r.ok else "FAIL"),
    ]
    lines += [f"  - {f}" for f in r.failures]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--summary")
    ap.add_argument("--secret-env", default="")
    ap.add_argument("--stderr", default="", help="with --model-rejected: stderr file")
    ap.add_argument("--model-rejected", action="store_true",
                    help="exit 0 if the run failed because the model id was rejected, else 1")
    a = ap.parse_args(argv)
    if a.model_rejected:
        err = ""
        if a.stderr and os.path.exists(a.stderr):
            err = open(a.stderr, encoding="utf-8", errors="replace").read()
        raw = open(a.log, encoding="utf-8", errors="replace").read() if os.path.exists(a.log) else ""
        return 0 if model_rejected(raw, err) else 1
    secret = os.environ.get(a.secret_env, "") if a.secret_env else ""
    with open(a.log, encoding="utf-8", errors="replace") as fh:
        r = analyze(fh.read(), secret)
    text = summary(r)
    print(text)
    if a.summary:
        with open(a.summary, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 2 if r.secret_found else (0 if r.ok else 1)


if __name__ == "__main__":
    sys.exit(main())
