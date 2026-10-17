"""Input bundle schema for Baton.

A bundle is one interrupted job: an objective, ordered events, artifacts,
receipts, and approvals. Everything downstream (checks, extraction, the
recovery record) reads from this shape, so validation lives here and only here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

EVENT_TYPES = {
    "agent_message",
    "tool_call",
    "tool_result",
    "approval_request",
    "final_response",
    "checkpoint",
}
APPROVAL_STATUSES = {"pending", "approved", "denied", "timed_out", "expired"}
RECEIPT_STATUSES = {"accepted", "delivered", "failed", "unknown"}

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass
class Artifact:
    id: str
    path: str
    content: str
    sha256: str = ""


@dataclass
class Receipt:
    id: str
    event_id: str
    provider: str
    status: str
    message_id: str = ""
    delivered: bool | None = None
    detail: str = ""


@dataclass
class Approval:
    id: str
    event_id: str
    prompt: str
    status: str


@dataclass
class Event:
    id: str
    ts: str
    type: str
    text: str = ""
    artifact_id: str = ""
    receipt_id: str = ""
    approval_id: str = ""
    status: str = ""
    ref_ids: list[str] = field(default_factory=list)


@dataclass
class Bundle:
    id: str
    objective: str
    events: list[Event]
    artifacts: list[Artifact]
    receipts: list[Receipt] = field(default_factory=list)
    approvals: list[Approval] = field(default_factory=list)


class BundleError(ValueError):
    """Raised when a bundle fails validation. Carries every error found."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("invalid bundle: " + "; ".join(errors))
        self.errors = errors


def validate_bundle(data: dict) -> list[str]:
    """Return a list of validation errors (empty means valid). Never raises."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["bundle must be a JSON object"]
    if not data.get("id"):
        errors.append("bundle.id is required")
    if not data.get("objective"):
        errors.append("bundle.objective is required")

    events = data.get("events")
    if not isinstance(events, list) or not events:
        errors.append("bundle.events must be a non-empty list")
        events = []
    seen: set[str] = set()
    prev_ts = ""
    for i, ev in enumerate(events):
        where = f"events[{i}]"
        if not isinstance(ev, dict):
            errors.append(f"{where} must be an object")
            continue
        eid = ev.get("id", "")
        if not eid:
            errors.append(f"{where}.id is required")
        elif eid in seen:
            errors.append(f"duplicate event id: {eid}")
        else:
            seen.add(eid)
        ts = ev.get("ts", "")
        if not _ISO_RE.match(ts or ""):
            errors.append(f"{where}.ts must be ISO-8601: {ts!r}")
        elif ts < prev_ts:
            errors.append(f"{where}.ts is earlier than the previous event")
        else:
            prev_ts = ts
        if ev.get("type") not in EVENT_TYPES:
            errors.append(f"{where}.type is not a known event type: {ev.get('type')!r}")
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            continue
        for ref in ev.get("ref_ids") or []:
            if ref not in seen:
                errors.append(f"events[{i}].ref_ids references unknown event: {ref}")

    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("bundle.artifacts must be a list")
        artifacts = []
    artifact_ids: set[str] = set()
    for i, a in enumerate(artifacts):
        if not isinstance(a, dict):
            errors.append(f"artifacts[{i}] must be an object")
            continue
        if not a.get("id"):
            errors.append(f"artifacts[{i}].id is required")
        else:
            artifact_ids.add(a["id"])
        if not a.get("path"):
            errors.append(f"artifacts[{i}].path is required")
        if "content" not in a:
            errors.append(f"artifacts[{i}].content is required")
        if not _SHA_RE.match(a.get("sha256") or ""):
            errors.append(f"artifacts[{i}].sha256 must be a 64-char hex digest")
    for i, ev in enumerate(events):
        if isinstance(ev, dict) and ev.get("artifact_id") and ev["artifact_id"] not in artifact_ids:
            errors.append(f"events[{i}].artifact_id references unknown artifact: {ev['artifact_id']}")

    receipts = data.get("receipts") or []
    receipt_ids: set[str] = set()
    for i, r in enumerate(receipts):
        if not isinstance(r, dict):
            errors.append(f"receipts[{i}] must be an object")
            continue
        if not r.get("id"):
            errors.append(f"receipts[{i}].id is required")
        else:
            receipt_ids.add(r["id"])
        if r.get("status") not in RECEIPT_STATUSES:
            errors.append(f"receipts[{i}].status is not a known receipt status: {r.get('status')!r}")
        if r.get("event_id") not in seen:
            errors.append(f"receipts[{i}].event_id references unknown event: {r.get('event_id')}")
    for i, ev in enumerate(events):
        if isinstance(ev, dict) and ev.get("receipt_id") and ev["receipt_id"] not in receipt_ids:
            errors.append(f"events[{i}].receipt_id references unknown receipt: {ev['receipt_id']}")

    approvals = data.get("approvals") or []
    approval_ids: set[str] = set()
    for i, ap in enumerate(approvals):
        if not isinstance(ap, dict):
            errors.append(f"approvals[{i}].id is required")
        else:
            approval_ids.add(ap["id"])
        if ap.get("status") not in APPROVAL_STATUSES:
            errors.append(f"approvals[{i}].status is not a known approval status: {ap.get('status')!r}")
        if ap.get("event_id") not in seen:
            errors.append(f"approvals[{i}].event_id references unknown event: {ap.get('event_id')}")
    for i, ev in enumerate(events):
        if isinstance(ev, dict) and ev.get("approval_id") and ev["approval_id"] not in approval_ids:
            errors.append(f"events[{i}].approval_id references unknown approval: {ev['approval_id']}")
    return errors


def parse_bundle(data: dict) -> Bundle:
    """Validate and parse raw JSON into a Bundle. Raises BundleError."""
    errors = validate_bundle(data)
    if errors:
        raise BundleError(errors)
    return Bundle(
        id=data["id"],
        objective=data["objective"],
        events=[
            Event(**{k: v for k, v in ev.items() if k in Event.__dataclass_fields__})
            for ev in data["events"]
        ],
        artifacts=[
            Artifact(**{k: v for k, v in a.items() if k in Artifact.__dataclass_fields__})
            for a in data.get("artifacts", [])
        ],
        receipts=[
            Receipt(**{k: v for k, v in r.items() if k in Receipt.__dataclass_fields__})
            for r in data.get("receipts", [])
        ],
        approvals=[
            Approval(**{k: v for k, v in ap.items() if k in Approval.__dataclass_fields__})
            for ap in data.get("approvals", [])
        ],
    )
