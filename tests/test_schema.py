"""Schema validation tests."""

import copy

import pytest

from baton.schema import BundleError, parse_bundle, validate_bundle
from helpers import load_fixture


def test_all_fixtures_validate():
    for name in ("fixture-never-executed.json", "fixture-completed-unreported.json", "fixture-accepted-unknown.json"):
        assert validate_bundle(load_fixture(name)) == []


def test_missing_objective_is_an_error():
    data = load_fixture("fixture-never-executed.json")
    del data["objective"]
    assert any("objective" in e for e in validate_bundle(data))
    with pytest.raises(BundleError):
        parse_bundle(data)


def test_duplicate_event_id_is_an_error():
    data = load_fixture("fixture-never-executed.json")
    data["events"].append(dict(data["events"][0]))
    assert any("duplicate" in e for e in validate_bundle(data))


def test_unknown_artifact_reference_is_an_error():
    data = load_fixture("fixture-never-executed.json")
    data["events"][1]["artifact_id"] = "art-missing"
    assert any("unknown artifact" in e for e in validate_bundle(data))


def test_bad_checksum_format_is_an_error():
    data = load_fixture("fixture-never-executed.json")
    data["artifacts"][0]["sha256"] = "not-a-hash"
    assert any("sha256" in e for e in validate_bundle(data))


def test_out_of_order_timestamps_is_an_error():
    data = load_fixture("fixture-never-executed.json")
    data["events"][0]["ts"], data["events"][1]["ts"] = data["events"][1]["ts"], data["events"][0]["ts"]
    assert any("earlier than" in e for e in validate_bundle(data))


def test_unknown_ref_id_is_an_error():
    data = load_fixture("fixture-completed-unreported.json")
    data["events"][2]["ref_ids"] = ["evt-nope"]
    assert any("unknown event" in e for e in validate_bundle(data))


def test_parse_returns_typed_bundle():
    bundle = parse_bundle(load_fixture("fixture-never-executed.json"))
    assert bundle.id == "bundle-never-executed"
    assert len(bundle.events) == 3
    assert bundle.approvals[0].status == "timed_out"


def test_validation_collects_multiple_errors():
    data = copy.deepcopy(load_fixture("fixture-never-executed.json"))
    del data["objective"]
    data["events"][0]["id"] = data["events"][1]["id"]
    assert len(validate_bundle(data)) >= 2
