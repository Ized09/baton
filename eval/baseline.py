"""Transcript-summary baseline for the Baton eval.

This is the naive path: a plain "summarize this transcript" pass over the
same bundle the Baton pipeline sees. It reads the events, approvals,
receipts, and artifact contents and writes a free-text summary. It
deliberately has:

- NO source links (cited_ids is always empty),
- NO deterministic checks (it never verifies a checksum, a receipt, or a
  final response),
- NO contradiction detection (it narrates conflicting claims side by side
  without flagging them),
- NO next step.

It TRUSTS claims in the text: if any text says the work was sent, done, or
passed, the summary says so. That is not a planted bug; it is how a plain
summarizer behaves. The eval exists to show where that trust breaks down.

The verdict is derived from the summary by simple keyword rules, in this
order: a failure word wins, then a success word, then an approval word,
otherwise incomplete. This mirrors taking the summary at face value.
"""
from __future__ import annotations

import re

_FAILURE_RE = re.compile(r"\b(failed|failure|error)\b")
_SUCCESS_RE = re.compile(
    r"\b(completed|complete|sent|success|passed|wrote|written|generated|created|done)\b"
)
_APPROVAL_RE = re.compile(r"\b(approval|timed out|expired|pending)\b")


def verdict_from_summary(summary: str) -> str:
    """Naive verdict from free text. Ordered: failure, success, approval."""
    text = summary.lower().replace("_", " ")
    if _FAILURE_RE.search(text):
        return "failed"
    if _SUCCESS_RE.search(text):
        return "complete"
    if _APPROVAL_RE.search(text):
        return "needs_human"
    return "incomplete"


def run_baseline(bundle: dict) -> dict:
    """Summarize one bundle. Returns summary, verdict, cited_ids, next_step."""
    events = bundle.get("events", [])
    said = [
        e.get("text", "")
        for e in events
        if e.get("type") == "agent_message" and e.get("text")
    ]
    actions = [
        e.get("text", "")
        for e in events
        if e.get("type") in ("tool_call", "tool_result", "checkpoint") and e.get("text")
    ]
    finals = [
        e.get("text", "")
        for e in events
        if e.get("type") == "final_response" and e.get("text")
    ]

    parts = [f"Objective: {bundle.get('objective', '')}."]
    if said:
        parts.append("The agent said: " + " ".join(said))
    if actions:
        parts.append("Recorded actions: " + " ".join(actions))
    approvals = bundle.get("approvals", [])
    if approvals:
        aparts = [
            f"{a.get('prompt', '')} ({a.get('status', '')})" for a in approvals
        ]
        parts.append("Approvals: " + " ".join(aparts))
    receipts = bundle.get("receipts", [])
    if receipts:
        rparts = [
            f"{r.get('provider', '')} {r.get('status', '')} ({r.get('detail', '')})"
            for r in receipts
        ]
        parts.append("Receipts: " + " ".join(rparts))
    artifacts = bundle.get("artifacts", [])
    if artifacts:
        aparts = [
            f"{a.get('path', '')}: {a.get('content', '')[:200]}" for a in artifacts
        ]
        parts.append("Files: " + " ".join(aparts))
    if finals:
        parts.append("Final response: " + " ".join(finals))

    summary = " ".join(parts)
    return {
        "summary": summary,
        "verdict": verdict_from_summary(summary),
        "cited_ids": [],
        "next_step": None,
    }
