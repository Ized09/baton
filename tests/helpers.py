"""Shared helpers for tests."""

import json
from pathlib import Path

import baton

FIXTURES = Path(baton.__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def fixture_names() -> list[str]:
    return sorted(p.name for p in FIXTURES.glob("*.json"))
