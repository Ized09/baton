"""The recovery pipeline: validate -> check -> extract -> persist.

Stage order matters: the bundle and its checks are persisted BEFORE any
extraction runs, so a failed or interrupted extraction never loses the
evidence. The stub extraction in Session 1 never calls a network API.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .checks import run_checks
from .cost import CostGuard
from .extract import Extractor, StubExtractor
from .schema import parse_bundle
from .store import Store


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def recover(
    bundle_data: dict,
    *,
    db_path: Path | str,
    extractor: Extractor | None = None,
    cost_guard: CostGuard | None = None,
    token_log: Path | str | None = None,
) -> dict:
    """Run one bundle through the pipeline. Returns the recovery record."""
    record_id = uuid.uuid4().hex[:12]
    bundle = parse_bundle(bundle_data)
    created_at = _now_iso()

    store = Store(db_path)
    store.init()
    store.save_bundle(bundle.id, bundle.objective, json.dumps(bundle_data), created_at)
    checks = run_checks(bundle)
    store.save_checks(record_id, bundle.id, checks)

    cost = cost_guard or CostGuard(log_path=token_log)
    tokens_in = cost.check_input(json.dumps(bundle_data))
    ext = extractor or StubExtractor()
    if hasattr(ext, "set_cost_guard"):
        # NebiusExtractor shares the pipeline guard so usage is logged once.
        ext.set_cost_guard(cost)
    result = ext.extract(bundle, checks)
    usage = getattr(ext, "last_usage", None)
    if usage is None:
        # The stub generates no tokens; record the input estimate honestly.
        cost.record(
            model=result.model,
            purpose="extract",
            tokens_in=tokens_in,
            tokens_out=0,
            estimated=True,
        )
        extraction_meta = {
            "model": result.model,
            "tokens_in": tokens_in,
            "tokens_out": 0,
            "estimated": True,
        }
    else:
        # NebiusExtractor already recorded measured (or estimated-fallback)
        # usage through the shared guard; do not record a second entry.
        extraction_meta = {
            "model": result.model,
            "tokens_in": usage["prompt_tokens"],
            "tokens_out": usage["completion_tokens"],
            "total_tokens": usage["total_tokens"],
            "estimated": usage["estimated"],
        }

    record = {
        "record_id": record_id,
        "bundle_id": bundle.id,
        "objective": bundle.objective,
        "created_at": created_at,
        "episode": result.episode,
        "replay": {
            "said": result.said,
            "receipts": result.receipts,
            "changed": result.changed,
        },
        "completed": result.completed,
        "failed": result.failed,
        "needs_you": result.needs_you,
        "changed": result.changed,
        "next": result.next_step,
        "contradictions": result.contradictions,
        "checks": [c.to_dict() for c in checks],
        "extraction": extraction_meta,
    }
    store.save_record(record)
    return record
