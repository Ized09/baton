"""Nebius extractor tests. All HTTP is mocked; no live calls, no real keys."""

import dataclasses
import io
import json
import urllib.error
from pathlib import Path

import pytest

from baton.checks import run_checks
from baton.cost import CostGuard, CostGuardError
from baton.extract import StubExtractor
from baton.nebius import (
    DEFAULT_REASONING_MODEL,
    DEFAULT_SUMMARY_MODEL,
    NebiusExtractionError,
    NebiusExtractor,
    extractor_from_env,
)
from baton.recover import recover
from baton.schema import parse_bundle
from helpers import load_fixture

FAKE_KEY = "test-key-not-real"
SECRET_REASONING = "SECRET CHAIN OF THOUGHT that must never leak"


def _model_output(**overrides):
    data = {
        "said": ["I'll write the release notes."],
        "receipts": [
            {
                "id": "r1",
                "provider": "x",
                "status": "accepted",
                "message_id": "m1",
                "delivered": None,
                "detail": "",
            }
        ],
        "completed": [{"claim": "Wrote notes", "evidence": ["evt-001"], "artifacts": []}],
        "needs_you": [],
        "changed": [],
        "contradictions": [],
        "episode": {
            "previously": "Objective: x",
            "plot_twist": "Twist.",
            "where_we_pick_up": "Report it.",
        },
        "next_step": {"step": "Report it.", "reason": "Done but unreported.", "evidence": ["evt-001"]},
    }
    data.update(overrides)
    return data


_UNSET = object()


def _api_response(content=_UNSET, finish_reason="stop", reasoning=SECRET_REASONING, usage=None):
    if content is _UNSET:
        content = json.dumps(_model_output())
    message = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning"] = reasoning
    return {
        "id": "chatcmpl-test",
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": usage
        if usage is not None
        else {"prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200},
    }


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def _transport_factory(payload, capture):
    def transport(request, timeout=None):
        capture["request"] = request
        capture["timeout"] = timeout
        return FakeResponse(payload)

    return transport


def _bundle_and_checks():
    bundle = parse_bundle(load_fixture("fixture-completed-unreported.json"))
    return bundle, run_checks(bundle)


def _extractor(capture=None, **kwargs):
    kwargs.setdefault("api_key", FAKE_KEY)
    return NebiusExtractor(**kwargs)


def test_successful_extraction_parse_and_request_shape():
    capture: dict = {}
    payload = _api_response(content=json.dumps(_model_output()))
    ext = _extractor(transport=_transport_factory(payload, capture))
    bundle, checks = _bundle_and_checks()
    result = ext.extract(bundle, checks)

    assert result.model == DEFAULT_REASONING_MODEL
    assert result.said == ["I'll write the release notes."]
    assert result.episode["plot_twist"] == "Twist."
    assert result.next_step["step"] == "Report it."
    # The reasoning field is present in the response but must never leak.
    assert SECRET_REASONING not in json.dumps(dataclasses.asdict(result))


def test_failed_field_surfaced_from_model_output():
    capture: dict = {}
    payload = _api_response(
        content=json.dumps(
            _model_output(
                failed=[{"claim": "Migration failed", "evidence": ["evt-003"], "artifacts": []}]
            )
        )
    )
    ext = _extractor(transport=_transport_factory(payload, capture))
    bundle, checks = _bundle_and_checks()
    result = ext.extract(bundle, checks)
    assert len(result.failed) == 1
    assert result.failed[0]["evidence"] == ["evt-003"]


def test_failed_field_optional_in_model_output():
    # _model_output() has no "failed" key; validation must still pass and
    # treat a missing "failed" as an empty list.
    capture: dict = {}
    payload = _api_response(content=json.dumps(_model_output()))
    ext = _extractor(transport=_transport_factory(payload, capture))
    bundle, checks = _bundle_and_checks()
    result = ext.extract(bundle, checks)
    assert result.failed == []

    request = capture["request"]
    assert request.full_url.endswith("/chat/completions")
    body = json.loads(request.data.decode("utf-8"))
    assert body["model"] == DEFAULT_REASONING_MODEL
    assert body["temperature"] == 0
    assert body["max_tokens"] == 2048
    assert body["messages"][0]["role"] == "system"
    assert "NEBIUS_API_KEY" not in json.dumps(body)
    assert capture["timeout"] == 60


def test_invalid_json_failure():
    ext = _extractor(
        transport=_transport_factory(_api_response(content="not json{"), {})
    )
    bundle, checks = _bundle_and_checks()
    with pytest.raises(NebiusExtractionError, match="not valid JSON"):
        ext.extract(bundle, checks)


def test_null_content_failure():
    ext = _extractor(
        transport=_transport_factory(_api_response(content=None), {})
    )
    bundle, checks = _bundle_and_checks()
    with pytest.raises(NebiusExtractionError, match="null or empty content"):
        ext.extract(bundle, checks)


def test_length_finish_failure():
    ext = _extractor(
        transport=_transport_factory(
            _api_response(content=json.dumps(_model_output()), finish_reason="length"), {}
        )
    )
    bundle, checks = _bundle_and_checks()
    with pytest.raises(NebiusExtractionError, match="truncated"):
        ext.extract(bundle, checks)


def test_http_error_failure_never_leaks_key():
    def failing_transport(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"detail": "bad key"}')
        )

    ext = _extractor(transport=failing_transport)
    bundle, checks = _bundle_and_checks()
    with pytest.raises(NebiusExtractionError, match="HTTP 401") as excinfo:
        ext.extract(bundle, checks)
    assert FAKE_KEY not in str(excinfo.value)


def test_cost_guard_precheck_refusal_never_calls_api():
    capture: dict = {}
    guard = CostGuard(max_input_chars=10)
    ext = _extractor(cost_guard=guard, transport=_transport_factory(_api_response(), capture))
    bundle, checks = _bundle_and_checks()
    with pytest.raises(CostGuardError, match="per-call limit"):
        ext.extract(bundle, checks)
    assert "request" not in capture


def test_daily_cap_precheck_refusal_never_calls_api():
    capture: dict = {}
    guard = CostGuard(daily_token_cap=100)
    guard.record(model="m", purpose="other", tokens_in=90, tokens_out=0, estimated=True)
    ext = _extractor(cost_guard=guard, transport=_transport_factory(_api_response(), capture))
    bundle, checks = _bundle_and_checks()
    with pytest.raises(CostGuardError, match="daily token cap"):
        ext.extract(bundle, checks)
    assert "request" not in capture


def test_token_logging_uses_response_usage():
    guard = CostGuard()
    ext = _extractor(
        cost_guard=guard,
        transport=_transport_factory(_api_response(), {}),
    )
    bundle, checks = _bundle_and_checks()
    ext.extract(bundle, checks)
    assert ext.last_usage == {
        "prompt_tokens": 120,
        "completion_tokens": 80,
        "total_tokens": 200,
        "estimated": False,
    }
    assert guard.daily_total() == 200
    assert guard.remaining() == guard.daily_token_cap - 200


def test_corrected_nano_default_id():
    ext = _extractor()
    assert ext.summary_model == "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
    assert DEFAULT_SUMMARY_MODEL == "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
    env_example = (Path(__file__).resolve().parent.parent / ".env.example").read_text()
    summary_lines = [
        line for line in env_example.splitlines() if line.startswith("NEBIUS_MODEL_SUMMARY=")
    ]
    assert summary_lines == ["NEBIUS_MODEL_SUMMARY=nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"]


def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    with pytest.raises(NebiusExtractionError, match="NEBIUS_API_KEY is not set"):
        NebiusExtractor()


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("NEBIUS_MODEL_REASONING", "custom/reasoning")
    monkeypatch.setenv("NEBIUS_MAX_TOKENS", "4096")
    ext = NebiusExtractor(api_key=FAKE_KEY)
    assert ext.reasoning_model == "custom/reasoning"
    assert ext.model == "custom/reasoning"
    assert ext.max_tokens == 4096


def test_extractor_from_env_selection(monkeypatch):
    monkeypatch.delenv("BATON_EXTRACTOR", raising=False)
    assert isinstance(extractor_from_env(), StubExtractor)
    monkeypatch.setenv("BATON_EXTRACTOR", "nebius")
    monkeypatch.setenv("NEBIUS_API_KEY", FAKE_KEY)
    assert isinstance(extractor_from_env(), NebiusExtractor)
    monkeypatch.setenv("BATON_EXTRACTOR", "stub")
    assert isinstance(extractor_from_env(), StubExtractor)


def test_pipeline_records_measured_usage_once(tmp_path):
    guard = CostGuard()
    ext = _extractor(
        cost_guard=guard,
        transport=_transport_factory(_api_response(), {}),
    )
    record = recover(
        load_fixture("fixture-completed-unreported.json"),
        db_path=tmp_path / "b.db",
        extractor=ext,
        cost_guard=guard,
    )
    assert record["extraction"]["estimated"] is False
    assert record["extraction"]["tokens_in"] == 120
    assert record["extraction"]["tokens_out"] == 80
    assert record["extraction"]["total_tokens"] == 200
    # One measured record only: the pipeline must not add an estimated one.
    assert guard.daily_total() == 200
