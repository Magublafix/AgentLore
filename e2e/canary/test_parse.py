"""Unit tests for the canary parser. Sample events are hand-built, NOT captured from a real run."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import parse  # noqa: E402

T = parse.TOOL
C = parse.SEED_CONCEPT


def ev(*events):
    return "\n".join(json.dumps(e) for e in events) + "\n"


INIT = {"type": "system", "subtype": "init", "mcp_servers": [{"name": "lore", "status": "connected"}]}
USE = {"type": "assistant", "message": {"content": [
    {"type": "text", "text": "Searching."},
    {"type": "tool_use", "id": "tu1", "name": T, "input": {"query": "REST CLI"}}]}}


def res(content, err=False, tid="tu1"):
    b = {"type": "tool_result", "tool_use_id": tid, "content": content}
    if err:
        b["is_error"] = True
    return {"type": "user", "message": {"content": [b]}}


DONE = {"type": "result", "subtype": "success", "is_error": False, "result": C, "total_cost_usd": 0.01}


def test_success_string_content():
    r = parse.analyze(ev(INIT, USE, res(f'[{{"name": "{C}"}}]'), DONE))
    assert r.ok and r.cost_usd == 0.01 and "PASS" in parse.summary(r)


def test_success_list_content():
    r = parse.analyze(ev(INIT, USE, res([{"type": "text", "text": f"1. {C}"}]), DONE))
    assert r.ok


def test_tool_not_called():
    r = parse.analyze(ev(INIT, DONE))
    assert not r.ok and not r.tool_called


def test_tool_error():
    r = parse.analyze(ev(INIT, USE, res("boom", err=True), DONE))
    assert not r.ok and r.tool_error


def test_concept_missing():
    r = parse.analyze(ev(INIT, USE, res("[]"), DONE))
    assert not r.ok and not r.concept_found


def test_result_error_and_missing():
    bad = dict(DONE, is_error=True, subtype="error_max_budget_usd")
    assert not parse.analyze(ev(USE, res(C), bad)).ok
    assert not parse.analyze(ev(USE, res(C))).ok


def test_unmatched_result_id_ignored():
    assert not parse.analyze(ev(USE, res(C, tid="other"), DONE)).ok


def test_malformed_and_unknown_tolerated():
    raw = "garbage\n[1]\n" + ev({"type": "weird"}, {"type": "assistant"}, USE, res(None), DONE)
    r = parse.analyze(raw)
    assert r.malformed_lines == 2 and not r.ok  # null content -> concept missing
    assert parse.analyze("garbage\n" + ev(INIT, USE, res(C), DONE)).ok


def test_secret_in_log():
    r = parse.analyze(ev(INIT, USE, res(C), DONE) + "sk-ant-SECRET\n", secret="sk-ant-SECRET")
    assert r.secret_found and not r.ok


def test_cli_exit_codes(tmp_path, monkeypatch):
    p = tmp_path / "l.jsonl"
    p.write_text(ev(USE, res(C), DONE))
    assert parse.main([str(p)]) == 0
    monkeypatch.setenv("K", "zzz")
    p.write_text(ev(USE, res(C), DONE) + "zzz")
    assert parse.main([str(p), "--secret-env", "K"]) == 2
    p.write_text(ev(DONE))
    assert parse.main([str(p)]) == 1


def test_model_rejected_specific_only():
    # benign `model` fields never trigger a retry
    assert not parse.model_rejected(ev(INIT | {"model": "x"}, DONE))
    assert not parse.model_rejected("", "some model warning: network down")
    assert parse.model_rejected("", "There's an issue with the selected model (foo)")
    bad = {"type": "result", "subtype": "success", "is_error": True,
           "result": "API Error: 404 not_found_error: model: foo"}
    assert parse.model_rejected(ev(bad))
    assert not parse.model_rejected(ev(dict(bad, is_error=False)))


def test_cli_model_rejected(tmp_path):
    log, err = tmp_path / "l", tmp_path / "e"
    log.write_text("")
    err.write_text("Invalid model: foo")
    assert parse.main([str(log), "--model-rejected", "--stderr", str(err)]) == 0
    err.write_text("boom")
    assert parse.main([str(log), "--model-rejected", "--stderr", str(err)]) == 1
