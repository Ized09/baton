"""SQLite persistence for bundles, checks, and recovery records.

One connection per call (this is a small local tool, not a server).
Token usage is NOT mirrored here — CostGuard owns the JSONL token log.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bundles (
    bundle_id TEXT PRIMARY KEY,
    objective TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL,
    bundle_id TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    passed INTEGER NOT NULL,
    detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS records (
    record_id TEXT PRIMARY KEY,
    bundle_id TEXT NOT NULL,
    objective TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def save_bundle(self, bundle_id: str, objective: str, raw_json: str, created_at: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO bundles VALUES (?, ?, ?, ?)",
                (bundle_id, objective, raw_json, created_at),
            )

    def save_checks(self, record_id: str, bundle_id: str, checks: list) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM checks WHERE record_id = ?", (record_id,))
            for c in checks:
                conn.execute(
                    "INSERT INTO checks (record_id, bundle_id, name, kind, passed, detail)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (record_id, bundle_id, c.name, c.kind, int(c.passed), c.detail),
                )

    def save_record(self, record: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO records VALUES (?, ?, ?, ?, ?)",
                (
                    record["record_id"],
                    record["bundle_id"],
                    record["objective"],
                    json.dumps(record),
                    record["created_at"],
                ),
            )

    def get_record(self, record_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT record_json FROM records WHERE record_id = ?", (record_id,)
            ).fetchone()
        return json.loads(row["record_json"]) if row else None

    def list_records(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT record_id, bundle_id, objective, created_at FROM records ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]
