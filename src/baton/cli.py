"""Baton CLI: recover a bundle, export a record.

Usage:
    baton recover bundle.json [--db baton.db] [--out-dir .] [--extractor stub|nebius]
    baton export <record_id> [--db baton.db] [--out-dir .]

The default extractor is the offline stub. Pass --extractor nebius (or set
BATON_EXTRACTOR=nebius) for the real Nebius LLM pass; it needs NEBIUS_API_KEY.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .handoff import export_handoff
from .recover import recover
from .store import Store


def _extractor_choice() -> str:
    choice = os.environ.get("BATON_EXTRACTOR", "stub").strip().lower()
    return choice if choice in ("stub", "nebius") else "stub"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="baton", description="Recover interrupted agent work.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_recover = sub.add_parser("recover", help="Recover one input bundle.")
    p_recover.add_argument("bundle", help="Path to a bundle JSON file.")
    p_recover.add_argument("--db", default="baton.db", help="SQLite database path.")
    p_recover.add_argument("--out-dir", default=".", help="Where to write handoff.json + handoff.md.")
    p_recover.add_argument(
        "--extractor",
        choices=["stub", "nebius"],
        default=_extractor_choice(),
        help="Extraction backend (default: $BATON_EXTRACTOR or stub).",
    )
    p_export = sub.add_parser("export", help="Re-export a stored record.")
    p_export.add_argument("record_id", help="Record id from a previous recover run.")
    p_export.add_argument("--db", default="baton.db", help="SQLite database path.")
    p_export.add_argument("--out-dir", default=".", help="Where to write handoff.json + handoff.md.")
    args = parser.parse_args(argv)

    if args.cmd == "recover":
        data = json.loads(Path(args.bundle).read_text())
        token_log = Path(args.db).parent / "token_log.jsonl"
        extractor = None
        if args.extractor == "nebius":
            from .nebius import NebiusExtractor

            extractor = NebiusExtractor()
        record = recover(data, db_path=args.db, token_log=token_log, extractor=extractor)
        json_path, md_path = export_handoff(record, args.out_dir)
        print(f"record {record['record_id']} (bundle {record['bundle_id']})")
        print(f"next: {record['next']['step']}")
        print(f"wrote {json_path} and {md_path}")
        return 0

    store = Store(args.db)
    store.init()
    record = store.get_record(args.record_id)
    if record is None:
        print(f"no record with id {args.record_id}", file=sys.stderr)
        return 1
    json_path, md_path = export_handoff(record, args.out_dir)
    print(f"wrote {json_path} and {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
