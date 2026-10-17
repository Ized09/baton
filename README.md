# AOS Baton: Director's Cut

**AI agents remember what they said. Baton helps you see what they did.**

Baton takes one interrupted agent job — its events, artifacts, receipts, and
approvals — and answers one question: **did the agent actually do it?**
Replay shows three things side by side: what the agent said, what the
receipts show, and what changed afterward. Every claim links back to its
source event or artifact.

Built for the NVIDIA x Nebius Global AI Hackathon (track: Best Apps & Agents).
Public repo: `Ized09/baton`. License: MIT.

## Status: Session 1 scaffold (local, offline)

Session 1 proves the core loop on fixtures: one bundle in → one source-linked
recovery record out, persisted in SQLite, exportable to `handoff.json` +
`handoff.md`. Extraction is **stubbed** (deterministic rules, no network).
The real Nebius/Nemotron adapter plugs into the `Extractor` interface in a
later session without restructuring.

## Quickstart

```bash
cd baton
python -m pytest                    # run the test suite
python -m baton.cli recover src/baton/fixtures/fixture-never-executed.json --db /tmp/baton.db --out-dir /tmp/out
python -m baton.cli export <record_id> --db /tmp/baton.db --out-dir /tmp/out
```

Or install editable: `pip install -e .` then use the `baton` command.

## The recovery record

Each record has four sections plus episode framing:

- **Completed** — work with supporting evidence.
- **Needs you** — a decision or approval genuinely pending.
- **Changed** — artifacts differing from their recorded checksum.
- **Next** — one concrete step, with reason and source evidence.
- **Episode** — Previously... / Plot twist / Where we pick up.
- **Replay** — said vs receipts vs changed, side by side.

## Input bundle

One JSON file: `id`, `objective`, ordered `events` (agent_message, tool_call,
tool_result, approval_request, final_response, checkpoint), `artifacts`
(path + content + sha256), `receipts` (provider, status, delivery), `approvals`.
See `src/baton/fixtures/` for the three proof cases: never-executed,
completed-unreported, accepted-unknown. Schema validation lives in
`baton/schema.py`.

## Deterministic checks

`baton/checks.py` runs in plain code before any extraction: timestamps ordered,
references resolve, artifacts present, checksums match, receipts/approvals
linked (integrity), plus signals for final response, delivery confirmation,
and unresolved approvals. A model never certifies its own claim.

## Cost guard

`baton/cost.py`: per-call input limit (default 120,000 chars), daily token cap
(default 200,000), JSONL token log. Estimates are always labelled
`estimated=True`; the real adapter will report measured usage from the API
response. Configure via `.env` (see `.env.example`; placeholder values only,
never a real key).

## Layout

```
src/baton/
  schema.py    input bundle + validation
  checks.py    deterministic checks (integrity + signals)
  extract.py   Extractor protocol + deterministic StubExtractor
  cost.py      per-call limit, daily cap, token logging
  store.py     SQLite persistence (bundles, checks, records)
  recover.py   pipeline: validate -> check -> extract -> persist
  handoff.py   handoff.json + handoff.md export
  cli.py       `baton recover` / `baton export`
  fixtures/    3 proof-case bundles
tests/         suite covering the Session-1 done criterion
```

## What's next (later sessions)

- Nebius wiring: `NebiusExtractor` (Nemotron-3-Super for reasoning, Nano for
  cheap summaries) behind the `Extractor` interface, using Token Factory.
- Replay UI: the three-way side-by-side view.
- Bounded resume demo: Baton writes a verified handoff, restarts a small
  local task, completes its unfinished step.
- Evaluation: the 12-case suite from the Codex brief (transcript-summary
  baseline vs Baton).
- Optional Tavily bonus: one functional runtime Tavily call ("restore with
  fresh context").
- Demo video (under 3 min) + submission. Never on the last day.
