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


def test_tampered_artifact_surfaces_as_changed_and_contradiction():
    data = load_fixture("fixture-completed-unreported.json")
    data["artifacts"][0]["content"] += "tampered line\n"
    result = _extract("fixture-completed-unreported.json", data)
    assert any("art-changelog" in item["claim"] for item in result.changed)
    assert any("changed since" in item["claim"] for item in result.contradictions)
