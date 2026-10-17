"""Handoff export tests."""

import json

from baton.handoff import export_handoff, render_markdown
from baton.recover import recover
from helpers import load_fixture


def _record(tmp_path):
    return recover(load_fixture("fixture-never-executed.json"), db_path=tmp_path / "b.db")


def test_handoff_json_round_trips(tmp_path):
    record = _record(tmp_path)
    json_path, _ = export_handoff(record, tmp_path / "out")
    assert json.loads(json_path.read_text())["record_id"] == record["record_id"]


def test_handoff_md_has_all_sections(tmp_path):
    record = _record(tmp_path)
    _, md_path = export_handoff(record, tmp_path / "out")
    text = md_path.read_text()
    for heading in (
        "Previously",
        "Plot twist",
        "Where we pick up",
        "Completed",
        "Needs you",
        "Changed",
        "Next",
        "Replay",
        "Contradictions",
        "Checks",
        "Source index",
    ):
        assert heading in text
    assert "evt-003" in text  # source-linked evidence appears


def test_handoff_md_empty_sections_render(tmp_path):
    record = _record(tmp_path)
    record["changed"] = []
    text = render_markdown(record)
    assert "_None._" in text
