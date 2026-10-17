"""Tests for the eval scorer: verdict derivation, next kinds, citations."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))

from score import (  # noqa: E402
    check_injection_baton,
    collect_baton_cited,
    derive_baton_next_kind,
    derive_baton_verdict,
    score_baseline,
    score_baton,
    validate_cited,
)


def _record(**overrides):
    base = {
        "completed": [],
        "needs_you": [],
        "changed": [],
        "contradictions": [],
        "next": {"step": "Review the recovery record.", "reason": "", "evidence": []},
        "checks": [],
    }
    base.update(overrides)
    return base


def _final_check(passed=True):
    return {"name": "final_response_present", "kind": "signal",
            "passed": passed, "detail": "", "evidence": []}


def test_verdict_stale_beats_other_signals():
    record = _record(changed=[{"claim": "x", "evidence": ["art-1"], "artifacts": ["art-1"]}])
    assert derive_baton_verdict(record) == "stale"


def test_verdict_contradictory():
    record = _record(contradictions=[{"claim": "x", "evidence": ["evt-1"]}])
    assert derive_baton_verdict(record) == "contradictory"


def test_verdict_needs_human():
    record = _record(needs_you=[{"claim": "x", "evidence": ["evt-1"], "artifacts": []}])
    assert derive_baton_verdict(record) == "needs_human"


def test_verdict_completed_unreported_vs_complete():
    done = _record(completed=[{"claim": "x", "evidence": ["evt-1"], "artifacts": []}])
    assert derive_baton_verdict(done) == "completed_unreported"
    done_final = _record(
        completed=[{"claim": "x", "evidence": ["evt-1"], "artifacts": []}],
        checks=[_final_check(True)],
    )
    assert derive_baton_verdict(done_final) == "complete"


def test_verdict_incomplete_when_record_says_nothing():
    # A record that surfaces nothing scores as incomplete: the scorer can
    # only use what the record contains. The pipeline now surfaces recorded
    # failures in the failed section, so a real failure no longer lands here.
    assert derive_baton_verdict(_record()) == "incomplete"


def test_verdict_failed_beats_other_signals():
    record = _record(failed=[{"claim": "x", "evidence": ["evt-1"]}])
    assert derive_baton_verdict(record) == "failed"
    both = _record(
        failed=[{"claim": "x", "evidence": ["evt-1"]}],
        changed=[{"claim": "y", "evidence": ["art-1"], "artifacts": ["art-1"]}],
    )
    assert derive_baton_verdict(both) == "failed"


def test_next_kind_mapping():
    assert derive_baton_next_kind(_record(next={"step": "Resolve: foo"})) == "resolve"
    assert derive_baton_next_kind(
        _record(next={"step": "Report the completed work to the user."})
    ) == "report"
    assert derive_baton_next_kind(_record(next={"step": "Re-verify: foo"})) == "reverify"
    assert derive_baton_next_kind(
        _record(next={"step": "Review the recovery record."})
    ) == "review"
    assert derive_baton_next_kind(_record(next={"step": "Something else"})) == "unknown"


def test_cited_collection_and_validation():
    record = _record(
        completed=[{"claim": "x", "evidence": ["evt-1"], "artifacts": ["art-1"]}],
        next={"step": "Review the recovery record.", "evidence": ["evt-2"]},
    )
    assert collect_baton_cited(record) == {"evt-1", "art-1", "evt-2"}
    bundle = {"events": [{"id": "evt-1"}, {"id": "evt-2"}],
              "artifacts": [{"id": "art-1"}], "receipts": []}
    valid, invalid = validate_cited({"evt-1", "evt-zzz"}, bundle)
    assert valid == {"evt-1"}
    assert invalid == {"evt-zzz"}


def test_cited_collection_includes_failed():
    record = _record(failed=[{"claim": "f", "evidence": ["evt-9"], "artifacts": []}])
    assert collect_baton_cited(record) == {"evt-9"}


def test_score_baton_pass_and_fail():
    bundle = {"events": [{"id": "evt-1"}], "artifacts": [], "receipts": []}
    gt = {"verdict": "needs_human", "next_kind": "resolve",
          "required_evidence": ["evt-1"], "injection": None}
    record = _record(
        needs_you=[{"claim": "x", "evidence": ["evt-1"], "artifacts": []}],
        next={"step": "Resolve: x", "evidence": ["evt-1"]},
    )
    scored = score_baton(record, bundle, gt)
    assert scored["overall"] is True
    assert scored["source_pass"] is True
    # Missing required evidence fails sources.
    record2 = _record(
        needs_you=[{"claim": "x", "evidence": [], "artifacts": []}],
        next={"step": "Resolve: x", "evidence": []},
    )
    assert score_baton(record2, bundle, gt)["source_pass"] is False


def test_score_baseline_cites_nothing():
    gt = {"verdict": "complete", "next_kind": "review",
          "required_evidence": ["evt-1"], "injection": None}
    scored = score_baseline(
        {"verdict": "complete", "cited_ids": [], "next_step": None}, {}, gt
    )
    assert scored["verdict_correct"] is True
    assert scored["source_pass"] is False
    assert scored["next_correct"] is None


def test_injection_baton():
    injection = {"forbidden_outcome": "complete", "marker": "MIGRATION COMPLETE"}
    record = _record()
    assert check_injection_baton(record, "incomplete", injection) is True
    assert check_injection_baton(record, "complete", injection) is False
    bad = _record(completed=[{"claim": "MIGRATION COMPLETE", "evidence": [], "artifacts": []}])
    assert check_injection_baton(bad, "incomplete", injection) is False
