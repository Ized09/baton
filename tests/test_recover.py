"""Session-1 done-criterion tests.

One fixture bundle in -> one source-linked recovery record out, with status
Completed / Needs you / Changed / Next, persisted in SQLite, exportable to
handoff.json + handoff.md.
"""

from baton.handoff import export_handoff
from baton.recover import recover
from baton.store import Store
from helpers import fixture_names, load_fixture

SECTIONS = ("completed", "needs_you", "changed")


def test_done_criterion_for_all_fixtures(tmp_path):
    db = tmp_path / "baton.db"
    for name in fixture_names():
        record = recover(load_fixture(name), db_path=db, token_log=tmp_path / "tokens.jsonl")
        # The four sections exist.
        for section in SECTIONS:
            assert section in record and isinstance(record[section], list)
        assert "next" in record and record["next"]["step"]
        # Episode framing exists.
        assert set(record["episode"]) == {"previously", "plot_twist", "where_we_pick_up"}
        # Replay: said vs receipts vs changed.
        assert set(record["replay"]) == {"said", "receipts", "changed"}
        # Persisted in SQLite.
        stored = Store(db).get_record(record["record_id"])
        assert stored is not None
        assert stored["record_id"] == record["record_id"]
        assert stored["bundle_id"] == record["bundle_id"]
        # Exportable to handoff.json + handoff.md.
        out = tmp_path / name.replace(".json", "")
        json_path, md_path = export_handoff(record, out)
        assert json_path.exists() and md_path.exists()
        assert record["objective"] in md_path.read_text()


def test_never_executed_record_content(tmp_path):
    record = recover(load_fixture("fixture-never-executed.json"), db_path=tmp_path / "b.db")
    assert any("timed_out" in item["claim"] for item in record["needs_you"])
    assert record["next"]["evidence"]  # next step is source-linked


def test_completed_unreported_record_content(tmp_path):
    record = recover(load_fixture("fixture-completed-unreported.json"), db_path=tmp_path / "b.db")
    assert record["completed"]
    assert record["completed"][0]["evidence"] == ["evt-003"]
    assert record["next"]["step"] == "Report the completed work to the user."


def test_accepted_unknown_record_content(tmp_path):
    record = recover(load_fixture("fixture-accepted-unknown.json"), db_path=tmp_path / "b.db")
    assert any("Delivery unconfirmed" in item["claim"] for item in record["needs_you"])
    assert record["replay"]["receipts"][0]["status"] == "accepted"


def test_record_lists_all_checks(tmp_path):
    record = recover(load_fixture("fixture-never-executed.json"), db_path=tmp_path / "b.db")
    names = {c["name"] for c in record["checks"]}
    assert {"timestamps_ordered", "checksums_match", "delivery_confirmed"}.issubset(names)


def test_list_records(tmp_path):
    db = tmp_path / "b.db"
    for name in fixture_names():
        recover(load_fixture(name), db_path=db)
    assert len(Store(db).list_records()) == 3
