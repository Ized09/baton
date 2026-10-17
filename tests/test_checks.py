"""Deterministic checks tests."""

import copy

from baton.checks import run_checks
from baton.schema import parse_bundle
from helpers import load_fixture


def _checks(name):
    return {c.name: c for c in run_checks(parse_bundle(load_fixture(name)))}


def test_fixtures_pass_all_integrity_checks():
    for name in ("fixture-never-executed.json", "fixture-completed-unreported.json", "fixture-accepted-unknown.json"):
        for c in _checks(name).values():
            if c.kind == "integrity":
                assert c.passed, f"{name}: {c.name} failed: {c.detail}"


def test_tampered_artifact_fails_checksum_check():
    data = load_fixture("fixture-completed-unreported.json")
    data["artifacts"][0]["content"] += "tampered line\n"
    (check,) = [c for c in run_checks(parse_bundle(data)) if c.name == "checksums_match"]
    assert not check.passed
    assert "art-changelog" in check.evidence


def test_accepted_without_delivery_is_a_signal():
    checks = _checks("fixture-accepted-unknown.json")
    assert not checks["delivery_confirmed"].passed
    assert checks["delivery_confirmed"].kind == "signal"
    assert "rcpt-001" in checks["delivery_confirmed"].evidence


def test_no_final_response_is_a_signal():
    checks = _checks("fixture-completed-unreported.json")
    assert not checks["final_response_present"].passed
    assert checks["final_response_present"].kind == "signal"


def test_timed_out_approval_is_a_signal():
    checks = _checks("fixture-never-executed.json")
    assert not checks["all_approvals_resolved"].passed
    assert "appr-001" in checks["all_approvals_resolved"].evidence


def test_delivered_receipt_passes_delivery_signal():
    data = load_fixture("fixture-accepted-unknown.json")
    data["receipts"][0]["status"] = "delivered"
    data["receipts"][0]["delivered"] = True
    (check,) = [c for c in run_checks(parse_bundle(data)) if c.name == "delivery_confirmed"]
    assert check.passed


def test_no_receipts_passes_delivery_signal_vacuously():
    checks = _checks("fixture-completed-unreported.json")
    assert checks["delivery_confirmed"].passed
