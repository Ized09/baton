"""Nebius Token Factory extraction: a real LLM pass behind the Extractor protocol.

NebiusExtractor implements the same ``extract(bundle, checks)`` interface as
StubExtractor, so the pipeline needs no restructuring. It is selected
explicitly only: ``BATON_EXTRACTOR=nebius`` (see :func:`extractor_from_env`),
the CLI ``--extractor nebius`` flag, or direct construction. The stub stays
the default; nothing silently swaps it out.

Privacy rule: Nemotron responses carry a ``message.reasoning`` field (the
model's internal chain of thought). This module reads ``message.content``
ONLY. ``reasoning`` is never stored, logged, or exposed anywhere — not in
records, handoffs, or logs.

Cost rule: the prompt is checked against CostGuard (per-call input limit
and daily token cap) BEFORE any network call, and measured usage from the
API response is logged AFTER the call. On invalid JSON, null content, a
``length`` finish, or an HTTP error, extraction raises
NebiusExtractionError. It never silently falls back to the stub.

Stdlib only (urllib). No new dependencies. No live calls happen in tests:
pass a fake ``transport`` or mock ``urllib.request.urlopen``.
"""
from __future__ import annotations

import dataclasses
import json
import os
import urllib.error
import urllib.request
from typing import Callable

from .checks import CheckResult
from .cost import CostGuard, CostGuardError
from .extract import ExtractionResult, StubExtractor
from .schema import Bundle

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
DEFAULT_REASONING_MODEL = "nvidia/nemotron-3-super-120b-a12b"
# Verified against the live Token Factory models list: the old default
# nvidia/nemotron-3-nano-30b-a12b is NOT a served model id. Use this one.
DEFAULT_SUMMARY_MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
DEFAULT_MAX_TOKENS = 2048

_SYSTEM_PROMPT = """You are Baton's extraction pass. You read one interrupted agent job
(a bundle of events, artifacts, receipts, approvals) plus deterministic
check results, and you report what the agent said versus what the receipts
show. You never certify a claim the evidence does not support.

Return ONLY a JSON object, no prose, no markdown fences, with exactly these
top-level fields:

- "said": list of strings, one per agent_message event, in order.
- "receipts": list of objects, one per receipt: {"id", "provider", "status",
  "message_id", "delivered", "detail"}.
- "completed": list of objects, one per piece of work the evidence shows was
  actually done: {"claim", "evidence", "artifacts"}. "evidence" is a list of
  event ids. "artifacts" is a list of artifact ids (may be empty).
- "failed": list of objects, one per piece of work the evidence shows ran
  and failed: {"claim", "evidence", "artifacts"}. A tool_result with status
  "failure" is a recorded failure: report it here, cite the failure event,
  and never relabel it as incomplete. Incomplete means the work never
  finished; failed means it ran and failed. Never put a recorded failure
  in "completed".
- "needs_you": list of objects, one per gap only a human can close:
  {"claim", "evidence", "artifacts"}.
- "changed": list of objects, one per artifact that differs from its recorded
  checksum: {"claim", "evidence", "artifacts"}.
- "contradictions": list of objects, one per place the agent's words and the
  receipts disagree: {"claim", "evidence", "artifacts"}.
- "episode": {"previously": string, "plot_twist": string,
  "where_we_pick_up": string}. "previously" states the objective plus what
  the agent said it was doing. "plot_twist" is the one surprising fact about
  what actually happened. "where_we_pick_up" is the next step, as a sentence.
- "next_step": {"step": string, "reason": string, "evidence": list of ids}.

Every claim must cite evidence: event ids, artifact ids, or receipt ids
present in the bundle. Never invent ids. Never claim work is complete
without evidence. If a tool result records a failure, report it in
"failed", never in "completed", and never describe it as incomplete.
If a send was accepted but delivery is unconfirmed, say
so; do not upgrade it to delivered."""

_CLAIM_LIST_FIELDS = ("completed", "needs_you", "changed", "contradictions")
# "failed" follows the same claim-object rules as the other lists, but it
# is optional in model output: older outputs that predate the field still
# validate, and the pipeline treats a missing "failed" as an empty list.
_OPTIONAL_CLAIM_LIST_FIELDS = ("failed",)
_TOP_LEVEL_FIELDS = (
    "said",
    "receipts",
    "completed",
    "needs_you",
    "changed",
    "contradictions",
    "episode",
    "next_step",
)


class NebiusExtractionError(RuntimeError):
    """Raised when a Nebius extraction cannot produce a validated result."""


class NebiusExtractor:
    """LLM extraction via Nebius Token Factory (OpenAI-compatible API).

    ``measured_tokens`` tells the pipeline (recover.py) that this extractor
    records its own usage, so the pipeline must not add a second estimated
    record for the same call.
    """

    measured_tokens = True
    model = DEFAULT_REASONING_MODEL

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        reasoning_model: str | None = None,
        summary_model: str | None = None,
        max_tokens: int | None = None,
        cost_guard: CostGuard | None = None,
        transport: Callable | None = None,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("NEBIUS_API_KEY")
        if not key:
            raise NebiusExtractionError(
                "NEBIUS_API_KEY is not set; cannot create NebiusExtractor"
            )
        self._api_key = key
        self.base_url = (
            base_url if base_url is not None else os.environ.get("NEBIUS_BASE_URL", DEFAULT_BASE_URL)
        ).rstrip("/")
        self.reasoning_model = (
            reasoning_model
            if reasoning_model is not None
            else os.environ.get("NEBIUS_MODEL_REASONING", DEFAULT_REASONING_MODEL)
        )
        # Config for a later cheap-summary pass; extraction itself uses the
        # reasoning model. The default is the verified served model id.
        self.summary_model = (
            summary_model
            if summary_model is not None
            else os.environ.get("NEBIUS_MODEL_SUMMARY", DEFAULT_SUMMARY_MODEL)
        )
        if max_tokens is not None:
            self.max_tokens = int(max_tokens)
        else:
            self.max_tokens = int(os.environ.get("NEBIUS_MAX_TOKENS", DEFAULT_MAX_TOKENS))
        self.model = self.reasoning_model
        self.cost_guard = cost_guard or CostGuard()
        self._transport = transport or urllib.request.urlopen
        self.last_usage: dict | None = None

    def set_cost_guard(self, cost_guard: CostGuard) -> None:
        """Let the pipeline share one CostGuard with this extractor."""
        self.cost_guard = cost_guard

    def extract(self, bundle: Bundle, checks: list[CheckResult]) -> ExtractionResult:
        prompt = self._build_prompt(bundle, checks)
        # Cost guard BEFORE any network call: input limit, then daily cap.
        estimated_in = self.cost_guard.check_input(prompt)
        if self.cost_guard.remaining() < estimated_in:
            raise CostGuardError(
                "daily token cap has insufficient remaining budget for this "
                f"extraction (estimated {estimated_in} input tokens, "
                f"{self.cost_guard.remaining()} remaining)"
            )
        body = {
            "model": self.reasoning_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": self.max_tokens,
        }
        response = self._post(body)
        choices = response.get("choices") or []
        if not choices:
            raise NebiusExtractionError("Nebius response has no choices")
        message = choices[0].get("message") or {}
        # Read content ONLY. message.reasoning (chain of thought) is never
        # touched, stored, logged, or exposed.
        content = message.get("content")
        finish_reason = choices[0].get("finish_reason")
        if finish_reason == "length":
            raise NebiusExtractionError(
                "Nebius extraction was truncated (finish_reason=length); "
                "increase NEBIUS_MAX_TOKENS and retry"
            )
        if content is None or not str(content).strip():
            raise NebiusExtractionError(
                "Nebius extraction returned null or empty content"
            )
        result = self._validate(str(content))
        self._record_usage(response.get("usage") or {}, prompt, str(content))
        return result

    def _build_prompt(self, bundle: Bundle, checks: list[CheckResult]) -> str:
        payload = {
            "objective": bundle.objective,
            "events": [dataclasses.asdict(e) for e in bundle.events],
            "artifacts": [dataclasses.asdict(a) for a in bundle.artifacts],
            "receipts": [dataclasses.asdict(r) for r in bundle.receipts],
            "approvals": [dataclasses.asdict(a) for a in bundle.approvals],
            "checks": [c.to_dict() for c in checks],
        }
        return json.dumps(payload, indent=1)

    def _post(self, body: dict) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self._transport(request, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:500]
            except Exception:
                pass
            # Never echo headers or the request body: they carry the key.
            raise NebiusExtractionError(
                f"Nebius API returned HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise NebiusExtractionError(f"Nebius API request failed: {exc.reason}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise NebiusExtractionError(f"Nebius API returned invalid JSON: {exc}") from exc

    def _record_usage(self, usage: dict, prompt: str, content: str) -> None:
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
            estimated = False
        else:
            prompt_tokens = CostGuard.estimate_tokens(prompt)
            completion_tokens = CostGuard.estimate_tokens(content)
            estimated = True
        total = usage.get("total_tokens")
        if not isinstance(total, int):
            total = prompt_tokens + completion_tokens
        self.cost_guard.record(
            model=self.reasoning_model,
            purpose="extract",
            tokens_in=prompt_tokens,
            tokens_out=completion_tokens,
            estimated=estimated,
        )
        self.last_usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total,
            "estimated": estimated,
        }

    def _validate(self, content: str) -> ExtractionResult:
        text = content.strip()
        if text.startswith("```"):
            # Tolerate a fenced block; the prompt asks for raw JSON.
            text = text.strip("`").strip()
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise NebiusExtractionError(f"model output is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise NebiusExtractionError("model output must be a JSON object")
        unknown = sorted(
            set(data) - set(_TOP_LEVEL_FIELDS) - set(_OPTIONAL_CLAIM_LIST_FIELDS)
        )
        if unknown:
            raise NebiusExtractionError(
                f"model output has unexpected top-level fields: {unknown}"
            )
        for field_name in _TOP_LEVEL_FIELDS:
            if field_name not in data:
                raise NebiusExtractionError(
                    f"model output is missing required field: {field_name}"
                )
        said = data["said"]
        if not isinstance(said, list) or not all(isinstance(s, str) for s in said):
            raise NebiusExtractionError('model output "said" must be a list of strings')
        receipts = data["receipts"]
        if not isinstance(receipts, list) or not all(
            isinstance(r, dict) and "id" in r and "status" in r for r in receipts
        ):
            raise NebiusExtractionError(
                'model output "receipts" must be a list of objects with id and status'
            )
        claim_lists: dict[str, list[dict]] = {}
        for field_name in _CLAIM_LIST_FIELDS + _OPTIONAL_CLAIM_LIST_FIELDS:
            items = data.get(field_name, [])
            if not isinstance(items, list):
                raise NebiusExtractionError(f'model output "{field_name}" must be a list')
            for item in items:
                if not isinstance(item, dict):
                    raise NebiusExtractionError(
                        f'model output "{field_name}" items must be objects'
                    )
                if not isinstance(item.get("claim"), str):
                    raise NebiusExtractionError(
                        f'model output "{field_name}" items need a string "claim"'
                    )
                if not isinstance(item.get("evidence"), list):
                    raise NebiusExtractionError(
                        f'model output "{field_name}" items need a list "evidence"'
                    )
            claim_lists[field_name] = items
        episode = data["episode"]
        if not isinstance(episode, dict) or not all(
            isinstance(episode.get(k), str)
            for k in ("previously", "plot_twist", "where_we_pick_up")
        ):
            raise NebiusExtractionError(
                'model output "episode" needs string previously/plot_twist/where_we_pick_up'
            )
        next_step = data["next_step"]
        if (
            not isinstance(next_step, dict)
            or not isinstance(next_step.get("step"), str)
            or not isinstance(next_step.get("reason"), str)
            or not isinstance(next_step.get("evidence"), list)
        ):
            raise NebiusExtractionError(
                'model output "next_step" needs string step/reason and list evidence'
            )
        return ExtractionResult(
            model=self.reasoning_model,
            said=said,
            receipts=receipts,
            completed=claim_lists["completed"],
            failed=claim_lists["failed"],
            needs_you=claim_lists["needs_you"],
            changed=claim_lists["changed"],
            contradictions=claim_lists["contradictions"],
            episode=episode,
            next_step=next_step,
        )


def extractor_from_env(*, cost_guard: CostGuard | None = None):
    """Select the extractor explicitly.

    ``BATON_EXTRACTOR=nebius`` returns a NebiusExtractor (requires
    NEBIUS_API_KEY). Anything else returns the offline StubExtractor.
    """
    if os.environ.get("BATON_EXTRACTOR", "").strip().lower() == "nebius":
        return NebiusExtractor(cost_guard=cost_guard)
    return StubExtractor()
