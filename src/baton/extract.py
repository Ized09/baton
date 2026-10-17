"""Extraction interface + deterministic stub.

The LLM pass (Nemotron via Nebius Token Factory) sits behind the Extractor
protocol. Session 1 ships StubExtractor: plain-code rules over the structured
events, so the pipeline runs fully offline. The stub never pretends to be a
model: its output is labelled model="stub-deterministic".

A future NebiusExtractor implements the same interface — extract(bundle,
checks) -> ExtractionResult — and the pipeline needs no restructuring.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from .checks import CheckResult
from .schema import Bundle

_SENT_WORD = re.compile(r"\bsent\b", re.IGNORECASE)


@dataclass
class ExtractionResult:
    model: str
    said: list[str] = field(default_factory=list)
    receipts: list[dict] = field(default_factory=list)
    completed: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    needs_you: list[dict] = field(default_factory=list)
    changed: list[dict] = field(default_factory=list)
    contradictions: list[dict] = field(default_factory=list)
    episode: dict = field(default_factory=dict)
    next_step: dict = field(default_factory=dict)


class Extractor(Protocol):
    def extract(self, bundle: Bundle, checks: list[CheckResult]) -> ExtractionResult:
        ...


class StubExtractor:
    """Rule-based extraction over structured events. Deterministic, offline."""

    model = "stub-deterministic"

    def extract(self, bundle: Bundle, checks: list[CheckResult]) -> ExtractionResult:
        artifacts = {a.id: a for a in bundle.artifacts}
        said = [e.text for e in bundle.events if e.type == "agent_message" and e.text]
        receipts = [
            {
                "id": r.id,
                "provider": r.provider,
                "status": r.status,
                "message_id": r.message_id,
                "delivered": r.delivered,
                "detail": r.detail,
            }
            for r in bundle.receipts
        ]

        referenced_calls = {
            ref for e in bundle.events if e.type == "tool_result" for ref in e.ref_ids
        }
        completed: list[dict] = []
        for e in bundle.events:
            if e.type == "tool_result" and e.status == "success":
                completed.append(self._work_item(e, artifacts))
            elif (
                e.type == "tool_call"
                and e.status == "success"
                and e.id not in referenced_calls
            ):
                completed.append(self._work_item(e, artifacts))

        # A recorded failure is its own outcome, not incomplete. Incomplete
        # means the work never finished; failed means it ran and failed.
        # A failed tool_call already referenced by a failed tool_result is
        # the same failure, so it is listed once, under the result.
        failed_result_refs = {
            ref
            for e in bundle.events
            if e.type == "tool_result" and e.status == "failure"
            for ref in e.ref_ids
        }
        failed: list[dict] = []
        for e in bundle.events:
            if e.type == "tool_result" and e.status == "failure":
                failed.append(self._work_item(e, artifacts))
            elif (
                e.type == "tool_call"
                and e.status == "failure"
                and e.id not in failed_result_refs
            ):
                failed.append(self._work_item(e, artifacts))

        needs_you: list[dict] = []
        for ap in bundle.approvals:
            if ap.status in ("pending", "timed_out", "expired"):
                needs_you.append(
                    {
                        "claim": f"Approval unresolved ({ap.status}): {ap.prompt}",
                        "evidence": [ap.event_id],
                        "artifacts": [],
                    }
                )
        for r in bundle.receipts:
            if r.status == "accepted" and r.delivered is not True:
                needs_you.append(
                    {
                        "claim": f"Delivery unconfirmed for {r.message_id or r.id} "
                        f"(provider {r.provider} accepted it).",
                        "evidence": [r.event_id],
                        "artifacts": [],
                    }
                )

        mismatch = next(
            (c.evidence for c in checks if c.name == "checksums_match" and not c.passed),
            [],
        )
        changed = [
            {
                "claim": f"Artifact {aid} differs from its recorded checksum.",
                "evidence": [aid],
                "artifacts": [aid],
            }
            for aid in mismatch
        ]

        contradictions: list[dict] = []
        success_artifacts = {
            e.artifact_id
            for e in bundle.events
            if e.type == "tool_result" and e.status == "success" and e.artifact_id
        }
        for aid in mismatch:
            if aid in success_artifacts:
                contradictions.append(
                    {
                        "claim": f"A result claimed success, but artifact {aid} changed since.",
                        "evidence": [aid],
                    }
                )
        if any(_SENT_WORD.search(m) for m in said) and not any(
            r.status in ("accepted", "delivered") for r in bundle.receipts
        ):
            contradictions.append(
                {
                    "claim": "The agent said it sent something, but no receipt confirms it.",
                    "evidence": [e.id for e in bundle.events if e.type == "agent_message"],
                }
            )

        has_final = any(e.type == "final_response" for e in bundle.events)
        if any(ap.status in ("timed_out", "expired") for ap in bundle.approvals):
            twist = "An approval timed out before the command ran."
        elif failed:
            twist = "The command ran and failed."
        elif completed and not has_final:
            twist = "The work was completed but never reported."
        elif any(r.status == "accepted" and r.delivered is not True for r in bundle.receipts):
            twist = "The send was accepted but delivery was never confirmed."
        elif changed:
            twist = "An artifact changed after it was recorded."
        else:
            twist = "No single twist: review the record."
        episode = {
            "previously": "Objective: " + bundle.objective
            + ((" " + " ".join(said[:2])) if said else ""),
            "plot_twist": twist,
            "where_we_pick_up": "",
        }

        if needs_you:
            first = needs_you[0]
            next_step = {
                "step": f"Resolve: {first['claim']}",
                "reason": "Something still needs you before this job can finish.",
                "evidence": first["evidence"],
            }
        elif failed:
            next_step = {
                "step": "Review the recovery record.",
                "reason": "A recorded failure needs review before this job can continue.",
                "evidence": failed[0]["evidence"],
            }
        elif completed and not has_final:
            next_step = {
                "step": "Report the completed work to the user.",
                "reason": "The work is done and verified, but the session ended before it was reported.",
                "evidence": completed[0]["evidence"],
            }
        elif changed:
            next_step = {
                "step": f"Re-verify: {changed[0]['claim']}",
                "reason": "Recorded evidence no longer matches the artifact.",
                "evidence": changed[0]["evidence"],
            }
        else:
            next_step = {
                "step": "Review the recovery record.",
                "reason": "No blocking gap found.",
                "evidence": [],
            }
        episode["where_we_pick_up"] = next_step["step"]

        return ExtractionResult(
            model=self.model,
            said=said,
            receipts=receipts,
            completed=completed,
            failed=failed,
            needs_you=needs_you,
            changed=changed,
            contradictions=contradictions,
            episode=episode,
            next_step=next_step,
        )

    @staticmethod
    def _work_item(event, artifacts: dict) -> dict:
        claim = event.text or "Work recorded"
        art = artifacts.get(event.artifact_id)
        if art:
            claim += f" ({art.path})"
        return {
            "claim": claim,
            "evidence": [event.id],
            "artifacts": [event.artifact_id] if event.artifact_id else [],
        }
