"""Deterministic checks over a bundle.

Two kinds of check:
- integrity: the bundle's own internal consistency (ids resolve, checksums
  match). A failed integrity check means the record cannot be trusted.
- signal: a fact about the job's state (final response present? delivery
  confirmed?). Signals feed the recovery record; they are not failures.

A model must never certify its own claim. These checks run in plain code,
before any extraction, and their results are persisted with the record.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .schema import Bundle


@dataclass
class CheckResult:
    name: str
    kind: str  # "integrity" | "signal"
    passed: bool
    detail: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "passed": self.passed,
            "detail": self.detail,
            "evidence": self.evidence,
        }


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_checks(bundle: Bundle) -> list[CheckResult]:
    results: list[CheckResult] = []
    event_ids = {e.id for e in bundle.events}
    artifact_ids = {a.id for a in bundle.artifacts}
    receipt_ids = {r.id for r in bundle.receipts}
    approval_ids = {a.id for a in bundle.approvals}

    ordered = all(
        bundle.events[i].ts <= bundle.events[i + 1].ts
        for i in range(len(bundle.events) - 1)
    )
    results.append(
        CheckResult(
            "timestamps_ordered",
            "integrity",
            ordered,
            "Events are in non-decreasing timestamp order." if ordered else "Events are out of timestamp order.",
        )
    )

    bad_refs: list[str] = []
    for e in bundle.events:
        for ref in e.ref_ids:
            if ref not in event_ids:
                bad_refs.append(f"{e.id} -> {ref}")
        if e.artifact_id and e.artifact_id not in artifact_ids:
            bad_refs.append(f"{e.id} -> artifact {e.artifact_id}")
        if e.receipt_id and e.receipt_id not in receipt_ids:
            bad_refs.append(f"{e.id} -> receipt {e.receipt_id}")
        if e.approval_id and e.approval_id not in approval_ids:
            bad_refs.append(f"{e.id} -> approval {e.approval_id}")
    results.append(
        CheckResult(
            "references_resolve",
            "integrity",
            not bad_refs,
            "All event references resolve." if not bad_refs else f"Unresolved references: {', '.join(bad_refs)}",
            bad_refs,
        )
    )

    referenced = {e.artifact_id for e in bundle.events if e.artifact_id}
    missing = sorted(referenced - artifact_ids)
    results.append(
        CheckResult(
            "artifacts_present",
            "integrity",
            not missing,
            "Every referenced artifact is present." if not missing else f"Missing artifacts: {', '.join(missing)}",
            missing,
        )
    )

    mismatched = sorted(
        a.id for a in bundle.artifacts if sha256_hex(a.content) != a.sha256
    )
    results.append(
        CheckResult(
            "checksums_match",
            "integrity",
            not mismatched,
            "All artifact checksums match their content." if not mismatched else f"Artifacts differ from recorded checksum: {', '.join(mismatched)}",
            mismatched,
        )
    )

    bad_receipts = [r.id for r in bundle.receipts if r.event_id not in event_ids]
    results.append(
        CheckResult(
            "receipts_linked",
            "integrity",
            not bad_receipts,
            "Every receipt links to a real event." if not bad_receipts else f"Receipts with unknown events: {', '.join(bad_receipts)}",
            bad_receipts,
        )
    )

    bad_approvals = [a.id for a in bundle.approvals if a.event_id not in event_ids]
    results.append(
        CheckResult(
            "approvals_linked",
            "integrity",
            not bad_approvals,
            "Every approval links to a real event." if not bad_approvals else f"Approvals with unknown events: {', '.join(bad_approvals)}",
            bad_approvals,
        )
    )

    has_final = any(e.type == "final_response" for e in bundle.events)
    results.append(
        CheckResult(
            "final_response_present",
            "signal",
            has_final,
            "Session ended with a final response." if has_final else "Session ended with no final response.",
        )
    )

    accepted = [r for r in bundle.receipts if r.status == "accepted"]
    delivered = [r for r in bundle.receipts if r.status == "delivered" or r.delivered is True]
    if not accepted:
        results.append(
            CheckResult("delivery_confirmed", "signal", True, "No accepted sends to confirm.")
        )
    elif delivered:
        results.append(
            CheckResult("delivery_confirmed", "signal", True, "At least one send is confirmed delivered.")
        )
    else:
        results.append(
            CheckResult(
                "delivery_confirmed",
                "signal",
                False,
                "A send was accepted by the provider but delivery was never confirmed.",
                [r.id for r in accepted],
            )
        )

    open_approvals = [
        a.id for a in bundle.approvals if a.status in ("pending", "timed_out", "expired")
    ]
    results.append(
        CheckResult(
            "all_approvals_resolved",
            "signal",
            not open_approvals,
            "All approvals resolved." if not open_approvals else f"Unresolved approvals: {', '.join(open_approvals)}",
            open_approvals,
        )
    )
    return results
