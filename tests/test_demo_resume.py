"""Tests for demo/resume.py: known action executes + verifies,
unknown action refuses, bad input errors cleanly. All offline."""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RESUME = REPO_ROOT / "demo" / "resume.py"
HANDOFF = REPO_ROOT / "web" / "data" / "completed-unreported.json"


def run_resume(handoff: Path, out_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RESUME), str(handoff), "--out-dir", str(out_dir)],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_known_action_executes_and_verifies(tmp_path):
    out_dir = tmp_path / "out"
    result = run_resume(HANDOFF, out_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr
    assert "verified" in result.stdout
    reports = list(out_dir.glob("report-*.md"))
    assert len(reports) == 1
    text = reports[0].read_text()
    handoff = json.loads(HANDOFF.read_text())
    assert handoff["record_id"] in text
    assert "not sent anywhere" in text
    for item in handoff["completed"]:
        assert item["claim"] in text


def test_unknown_action_refuses_and_writes_nothing(tmp_path):
    handoff = json.loads(HANDOFF.read_text())
    handoff["next"] = {
        "step": "Send the email to everyone.",
        "reason": "Made up for this test.",
        "evidence": [],
    }
    path = tmp_path / "handoff.json"
    path.write_text(json.dumps(handoff))
    out_dir = tmp_path / "out"
    result = run_resume(path, out_dir)
    assert result.returncode == 3
    assert "refuses" in result.stdout
    assert "unrecognized" in result.stdout
    assert not out_dir.exists() or not list(out_dir.iterdir())


def test_other_proof_cases_refuse(tmp_path):
    for name in ("never-executed.json", "accepted-unknown.json"):
        out_dir = tmp_path / name
        result = run_resume(REPO_ROOT / "web" / "data" / name, out_dir)
        assert result.returncode == 3, result.stdout
        assert "refuses" in result.stdout
        assert not out_dir.exists() or not list(out_dir.iterdir())


def test_missing_file_errors_cleanly(tmp_path):
    result = run_resume(tmp_path / "no-such-file.json", tmp_path / "out")
    assert result.returncode == 2
    assert "Traceback" not in result.stdout + result.stderr
    assert "no such file" in result.stdout


def test_malformed_json_errors_cleanly(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    result = run_resume(path, tmp_path / "out")
    assert result.returncode == 2
    assert "Traceback" not in result.stdout + result.stderr
    assert "not valid JSON" in result.stdout


def test_missing_next_step_refuses(tmp_path):
    handoff = json.loads(HANDOFF.read_text())
    del handoff["next"]
    path = tmp_path / "handoff.json"
    path.write_text(json.dumps(handoff))
    result = run_resume(path, tmp_path / "out")
    assert result.returncode == 3
    assert "refuses" in result.stdout
