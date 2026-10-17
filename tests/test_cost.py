"""Cost guard tests."""

import json

import pytest

from baton.cost import CostGuard, CostGuardError


def test_estimate_is_chars_over_four():
    assert CostGuard.estimate_tokens("a" * 400) == 100


def test_input_limit_enforced():
    guard = CostGuard(max_input_chars=10)
    with pytest.raises(CostGuardError, match="per-call limit"):
        guard.check_input("this input is far too long")


def test_input_within_limit_returns_estimate():
    guard = CostGuard(max_input_chars=1000)
    assert guard.check_input("hello world, this is a test") > 0


def test_record_and_daily_total(tmp_path):
    guard = CostGuard(daily_token_cap=10_000, log_path=tmp_path / "tokens.jsonl")
    guard.record(model="m", purpose="extract", tokens_in=100, tokens_out=50, estimated=True)
    assert guard.daily_total() == 150
    assert guard.remaining() == 10_000 - 150


def test_daily_cap_enforced():
    guard = CostGuard(daily_token_cap=100)
    guard.record(model="m", purpose="extract", tokens_in=60, tokens_out=0, estimated=True)
    with pytest.raises(CostGuardError, match="daily token cap"):
        guard.record(model="m", purpose="extract", tokens_in=60, tokens_out=0, estimated=True)


def test_log_file_is_jsonl(tmp_path):
    log = tmp_path / "tokens.jsonl"
    guard = CostGuard(log_path=log)
    guard.record(model="stub", purpose="extract", tokens_in=10, tokens_out=0, estimated=True)
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["model"] == "stub"
    assert entry["estimated"] is True


def test_log_reloads_on_init(tmp_path):
    log = tmp_path / "tokens.jsonl"
    guard = CostGuard(log_path=log)
    guard.record(model="m", purpose="extract", tokens_in=25, tokens_out=5, estimated=True)
    guard2 = CostGuard(log_path=log)
    assert guard2.daily_total() == 30
