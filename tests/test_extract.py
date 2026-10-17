"""Stub extractor tests."""

import copy

from baton.checks import run_checks
from baton.extract import StubExtractor
from baton.schema import parse_bundle
from helpers import load_fixture


def _extract(name, data=None):
    bundle = parse_bundle(data if data is not None else load_fixture(name))
    return StubExtractor().extract(bundle, run_checks(bundle))


def test_stub_is_deterministic():
    a = _extract("fixture-never-executed.json")
    b = _extract("fixture-never-executed.json")
    assert a == b


def test_stub_labels_itself():
    result = _extract("fixture-never-executed.json")
    assert result.model == "stub-deterministic"


def test_never_executed_twist_is_timed_out_approval():
    result = _extract("fixture-never-executed.json")
    assert any("timed_out" in item["claim"] for item in result.needs_you)
    assert "timed out" in result.episode["plot_twist"]
    assert result.completed  # the draft itself was completed
    assert result.next_step["step"].startswith("Resolve:")


def test_completed_unreported_twist_and_next():
    result = _extract("fixture-completed-unreported.json")
    assert "never reported" in result.episode["plot_twist"]
    assert any("CHANGELOG.md" in item["claim"] for item in result.completed)
    assert result.next_step["step"] == "Report the completed work to the user."
    assert not result.needs_you


def test_accepted_unknown_needs_delivery_confirmation():
    result = _extract("fixture-accepted-unknown.json")
    assert "accepted" in result.episode["plot_twist"]
    assert any("Delivery unconfirmed" in item["claim"] for item in result.needs_you)
    assert not result.completed  # accepted is not completed


def test_recorded_failure_surfaces_as_failed():
    data = {
        "id": "bundle-failure",
        "objective": "Run the migration.",
        "events": [
            {
                "id": "evt-001",
                "ts": "2026-10-13T10:00:00Z",
                "type": "agent_message",
                "text": "I'll run the migration.",
            },
            {
                "id": "evt-002",
                "ts": "2026-10-13T10:01:00Z",
                "type": "tool_call",
                "status": "started",
                "text": "Running the migration.",
            },
            {
                "id": "evt-003",
                "ts": "2026-10-13T10:02:00Z",
                "type": "tool_result",
                "status": "failure",
                "ref_ids": ["evt-002"],
                "text": "Migration failed: table locked.",
            },
        ],
        "artifacts": [],
    }
    result = _extract("fixture-never-executed.json", data)
    assert len(result.failed) == 1
    assert result.failed[0]["evidence"] == ["evt-003"]
    assert "failed" in result.episode["plot_twist"]
    assert result.next_step["step"] == "Review the recovery record."
    assert result.next_step["evidence"] == ["evt-003"]
    assert not result.completed  # a failure is not completed work


def test_tampered_artifact_surfaces_as_changed_and_contradiction():
    data = load_fixture("fixture-completed-unreported.json")
    data["artifacts"][0]["content"] += "tampered line\n"
    result = _extract("fixture-completed-unreported.json", data)
    assert any("art-changelog" in item["claim"] for item in result.changed)
    assert any("changed since" in item["claim"] for item in result.contradictions)
