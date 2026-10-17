"""CLI end-to-end tests (offline, temp dirs only)."""

import json
from pathlib import Path

from baton.cli import main
from baton.store import Store
from helpers import FIXTURES


def test_cli_recover_end_to_end(tmp_path):
    out = tmp_path / "out"
    rc = main(["recover", str(FIXTURES / "fixture-never-executed.json"), "--db", str(tmp_path / "b.db"), "--out-dir", str(out)])
    assert rc == 0
    assert (out / "handoff.json").exists()
    assert (out / "handoff.md").exists()
    assert (tmp_path / "token_log.jsonl").exists()
    assert len(Store(tmp_path / "b.db").list_records()) == 1


def test_cli_export_round_trip(tmp_path, capsys):
    db = tmp_path / "b.db"
    main(["recover", str(FIXTURES / "fixture-completed-unreported.json"), "--db", str(db), "--out-dir", str(tmp_path / "a")])
    record_id = Store(db).list_records()[0]["record_id"]
    out = tmp_path / "b"
    rc = main(["export", record_id, "--db", str(db), "--out-dir", str(out)])
    assert rc == 0
    assert json.loads((out / "handoff.json").read_text())["record_id"] == record_id


def test_cli_export_unknown_id_fails(tmp_path):
    rc = main(["export", "no-such-id", "--db", str(tmp_path / "b.db"), "--out-dir", str(tmp_path)])
    assert rc == 1
