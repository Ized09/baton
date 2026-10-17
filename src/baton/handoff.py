"""Export a recovery record to handoff.json + handoff.md.

The handoff is what the next session (or a fresh model) reads: objective,
episode framing, the four sections, replay, contradictions, checks, and a
source index of every event/artifact id cited.
"""
from __future__ import annotations

import json
from pathlib import Path


def _items_md(items: list[dict]) -> str:
    if not items:
        return "_None._\n"
    lines = []
    for it in items:
        ev = ", ".join(it.get("evidence", []))
        lines.append(f"- {it['claim']} (evidence: {ev})" if ev else f"- {it['claim']}")
    return "\n".join(lines) + "\n"


def _source_index(record: dict) -> list[str]:
    ids: set[str] = set()
    for section in ("completed", "needs_you", "changed", "contradictions"):
        for it in record.get(section, []):
            ids.update(it.get("evidence", []))
            ids.update(it.get("artifacts", []))
    ids.update(record.get("next", {}).get("evidence", []))
    for c in record.get("checks", []):
        ids.update(c.get("evidence", []))
    return sorted(ids)


def render_markdown(record: dict) -> str:
    ep = record["episode"]
    nxt = record["next"]
    lines = [
        f"# Baton handoff — {record['objective']}",
        "",
        f"- Record: `{record['record_id']}` · Bundle: `{record['bundle_id']}` · {record['created_at']}",
        "",
        "## Previously...",
        "",
        ep["previously"],
        "",
        "## Plot twist",
        "",
        ep["plot_twist"],
        "",
        "## Where we pick up",
        "",
        ep["where_we_pick_up"],
        "",
        "## Completed",
        "",
        _items_md(record["completed"]),
        "## Needs you",
        "",
        _items_md(record["needs_you"]),
        "## Changed",
        "",
        _items_md(record["changed"]),
        "## Next",
        "",
        f"**{nxt['step']}** — {nxt['reason']}",
        "",
        "## Replay: said vs receipts vs changed",
        "",
        "### Said",
        "",
    ]
    for s in record["replay"]["said"]:
        lines.append(f"- {s}")
    if not record["replay"]["said"]:
        lines.append("_Nothing recorded._")
    lines += ["", "### Receipts", ""]
    for r in record["replay"]["receipts"]:
        lines.append(
            f"- {r['id']}: {r['provider']} {r['status']}"
            + (f" (message {r['message_id']})" if r.get("message_id") else "")
            + (f" — {r['detail']}" if r.get("detail") else "")
        )
    if not record["replay"]["receipts"]:
        lines.append("_No receipts._")
    lines += ["", "### Changed", "", _items_md(record["replay"]["changed"])]
    lines += ["## Contradictions", "", _items_md(record["contradictions"])]
    lines += ["## Checks", ""]
    for c in record["checks"]:
        mark = "x" if c["passed"] else " "
        lines.append(f"- [{mark}] {c['name']} ({c['kind']}) — {c['detail']}")
    lines += ["", "## Source index", ""]
    for sid in _source_index(record):
        lines.append(f"- `{sid}`")
    lines.append("")
    return "\n".join(lines)


def export_handoff(record: dict, out_dir: Path | str) -> tuple[Path, Path]:
    """Write handoff.json + handoff.md into out_dir. Returns both paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "handoff.json"
    md_path = out / "handoff.md"
    json_path.write_text(json.dumps(record, indent=2) + "\n")
    md_path.write_text(render_markdown(record))
    return json_path, md_path
