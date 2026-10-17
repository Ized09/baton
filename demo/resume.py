#!/usr/bin/env python3
"""Bounded resume demo: take one verified handoff, do one step, verify it.

Usage:
    python3 demo/resume.py <handoff.json> [--out-dir <dir>]

The script reads the handoff Next step and performs exactly one bounded
action, then verifies the action completed. It knows a small registry of
bounded actions. If the Next step is not a recognized bounded action, the
script refuses and does nothing. It never improvises new actions.

Known bounded actions:
- "Report the completed work to the user." -> write a report file to the
  out dir. The report is written to a file only. It is never sent anywhere.

Exit codes: 0 success, 1 verification failed, 2 bad input, 3 refused.
All errors print a one-line message, never a traceback.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPORT_STEP = "Report the completed work to the user."


def write_report(handoff: dict, out_dir: Path) -> Path:
    """Write the missing report for a completed-unreported handoff."""
    record_id = handoff["record_id"]
    bundle_id = handoff["bundle_id"]
    objective = handoff["objective"]
    completed = handoff.get("completed", [])
    lines = [
        f"# Report: {objective}",
        "",
        f"Record: {record_id}",
        f"Bundle: {bundle_id}",
        "",
        "## Completed work",
        "",
    ]
    if completed:
        for item in completed:
            ev = ", ".join(item.get("evidence", []))
            lines.append(f"- {item.get('claim', '')}" + (f" (evidence: {ev})" if ev else ""))
    else:
        lines.append("No completed items recorded.")
    lines += [
        "",
        "Written by the Baton resume demo from the verified handoff.",
        "This report was not sent anywhere.",
        "",
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"report-{record_id}.md"
    path.write_text("\n".join(lines))
    return path


def verify_report(path: Path, handoff: dict) -> list[str]:
    """Re-read the written report and check it says what it should."""
    problems: list[str] = []
    if not path.is_file():
        return ["report file was not created"]
    text = path.read_text()
    if not text.strip():
        problems.append("report file is empty")
    if handoff["record_id"] not in text:
        problems.append("report is missing the record id")
    for item in handoff.get("completed", []):
        claim = item.get("claim", "")
        if claim and claim not in text:
            problems.append(f"report is missing completed claim: {claim}")
    if "not sent anywhere" not in text:
        problems.append("report is missing the not-sent disclaimer")
    return problems


def run(handoff_path: Path, out_dir: Path) -> int:
    if not handoff_path.is_file():
        print(f"error: no such file: {handoff_path}")
        return 2
    try:
        handoff = json.loads(handoff_path.read_text())
    except json.JSONDecodeError as exc:
        print(f"error: not valid JSON: {exc}")
        return 2
    if not isinstance(handoff, dict):
        print("error: handoff must be a JSON object")
        return 2
    nxt = handoff.get("next") or {}
    step = nxt.get("step")
    if not isinstance(step, str) or not step:
        print("refuses: handoff has no Next step to act on")
        return 3
    if step != REPORT_STEP:
        print(f"refuses: unrecognized Next step, no bounded action applies: {step}")
        return 3
    path = write_report(handoff, out_dir)
    problems = verify_report(path, handoff)
    if problems:
        try:
            path.unlink()
        except OSError:
            pass
        print("verification failed: " + "; ".join(problems))
        return 1
    print(f"did one step: wrote {path}")
    print(f"verified: report exists, names record {handoff['record_id']}, lists the completed work, states it was not sent")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="resume.py", description="Bounded resume demo: do one handoff step and verify it."
    )
    parser.add_argument("handoff", help="Path to a handoff.json file.")
    parser.add_argument("--out-dir", default="resume-out", help="Where to write the report file.")
    args = parser.parse_args(argv)
    return run(Path(args.handoff), Path(args.out_dir))


if __name__ == "__main__":
    raise SystemExit(main())
