"""Tests for the eval runner: full 12-case run, offline stub."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))

from run import aggregate, load_cases, run_eval  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent.parent / "eval"


def test_load_cases():
    cases = load_cases(EVAL_DIR / "cases")
    assert len(cases) == 12
    names = [c[0] for c in cases]
    assert names[0].startswith("01-")
    assert names[-1].startswith("12-")
    for _, _, gt in cases:
        assert gt["verdict"] in (
            "failed", "needs_human", "stale", "completed_unreported",
            "complete", "contradictory", "incomplete",
        )
        assert gt["next_kind"] in ("resolve", "report", "reverify", "review")


def test_full_stub_run(tmp_path):
    out = tmp_path / "report.md"
    json_path = tmp_path / "report.json"
    results, agg, code = run_eval(EVAL_DIR / "cases", out, json_path)
    assert len(results) == 12
    # Case 02's recorded failure surfaces as a distinct failed outcome,
    # so the runner exits zero with Baton at 12/12.
    assert code == 0
    # Baton (stub): 12/12 verdicts, 12/12 next steps, 12/12 source refs.
    assert agg["baton"]["verdict_pass"] == 12
    assert agg["baton"]["next_pass"] == 12
    assert agg["baton"]["source_pass"] == 12
    assert agg["baton"]["errors"] == 0
    assert agg["baton"]["injection_resistant"] == 1
    # Baseline: 4/12 verdicts (the straightforward cases), 0/12 sources,
    # and it is fooled by the case-12 injection.
    assert agg["baseline"]["verdict_pass"] == 4
    assert agg["baseline"]["source_pass"] == 0
    assert agg["baseline"]["errors"] == 0
    assert agg["baseline"]["injection_resistant"] == 0
    # Reports written, and the markdown contains only measured numbers.
    assert out.exists()
    text = out.read_text()
    assert "Baton eval" in text
    assert "02-command-failed" in text
    data = json.loads(json_path.read_text())
    assert data["aggregates"] == agg
    assert len(data["results"]) == 12
    # Every Baton case reports token usage, estimated in stub mode.
    for r in results:
        assert r["baton"]["tokens"]["estimated"] is True
        assert r["baton"]["latency_ms"] >= 0


def test_case_02_command_failed_passes():
    """Regression test: the case-02 bundle must score failed with evt-003 cited."""
    import tempfile

    from baton.recover import recover
    from score import score_baton

    cases = load_cases(EVAL_DIR / "cases")
    _, bundle, gt = next(c for c in cases if c[0].startswith("02-"))
    with tempfile.TemporaryDirectory() as td:
        record = recover(bundle, db_path=Path(td) / "t.db")
    scored = score_baton(record, bundle, gt)
    assert scored["verdict"] == "failed"
    assert scored["source_pass"] is True
    assert scored["next_correct"] is True
    assert scored["overall"] is True


def test_aggregate_counts():
    results = [
        {"ground_truth": {}, "baton": {"latency_ms": 1.0, "tokens": {"tokens_in": 1, "tokens_out": 0}, "error": None, "score": {"verdict_correct": True, "next_correct": True, "source_pass": True, "overall": True, "injection_resistant": None}}},
        {"ground_truth": {"injection": {"forbidden_outcome": "complete"}}, "baton": {"latency_ms": 2.0, "tokens": {"tokens_in": 2, "tokens_out": 0}, "error": "boom", "score": None}},
    ]
    for r in results:
        r["baseline"] = {"latency_ms": 1.0, "tokens": {"tokens_in": 1, "tokens_out": 1}, "error": None,
                         "score": {"verdict_correct": False, "source_pass": False, "overall": False, "injection_resistant": False}}
    agg = aggregate(results)
    assert agg["cases"] == 2
    assert agg["baton"]["verdict_pass"] == 1
    assert agg["baton"]["errors"] == 1
    assert agg["baseline"]["verdict_pass"] == 0
