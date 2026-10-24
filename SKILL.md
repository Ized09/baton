# Baton skill: teach your agent to leave a handoff

Baton answers one question about an agent run: did the agent actually do
what it said it did? It does that by auditing the run's history against
its receipts, not by trusting the agent's own summary.

Install this file into your agent's instructions. No code changes to the
agent are required. The agent only has to keep its diary in Baton's shape.

## When to use Baton

- A session ends, or is about to end, and you want a record of it.
- A session was interrupted and you need to know what is done, what is
  waiting on you, and what comes next, instead of starting over.
- The user asks to diagnose a session: "diagnose this session", "what did
  you actually do", "baton this run".

## While you work: keep the log

Record four kinds of facts as they happen. Do not summarise them away.
The log is the evidence; the summary comes later.

1. **Events**, in order, with ISO-8601 timestamps. Types, exactly:
   `agent_message`, `tool_call`, `tool_result`, `approval_request`,
   `final_response`, `checkpoint`.
2. **Artifacts**: every file the run creates or changes, with its path,
   its full content, and its sha256 digest. Compute the digest, never
   guess it.
3. **Receipts**: for every send or delivery, the provider, the status
   (`accepted`, `delivered`, `failed`, or `unknown`), the message id, and
   whether delivery is confirmed (`true`, `false`, or `null` when
   unconfirmed).
4. **Approvals**: every decision asked of a human, with the prompt and
   the status (`pending`, `approved`, `denied`, `timed_out`, `expired`).

Link events to artifacts, receipts, and approvals by id. Never invent a
receipt, a checksum, or an approval. If something is unknown, say so:
`unknown` and `null` are valid answers. A gap named is better than a gap
filled in.

## When the session ends, or on "diagnose": emit a bundle

Write one JSON file in this shape:

```json
{
  "id": "bundle-my-run",
  "objective": "What you asked the agent to do.",
  "events": [
    {"id": "evt-001", "ts": "2026-10-24T10:00:00Z", "type": "agent_message", "text": "I'll do the thing."},
    {"id": "evt-002", "ts": "2026-10-24T10:01:00Z", "type": "tool_call", "text": "Called the send tool.", "receipt_id": "rcpt-001"},
    {"id": "evt-003", "ts": "2026-10-24T10:02:00Z", "type": "approval_request", "text": "Asked you to confirm.", "approval_id": "appr-001"}
  ],
  "artifacts": [
    {"id": "art-001", "path": "report.md", "content": "...", "sha256": "<real sha256sum of the file>"}
  ],
  "receipts": [
    {"id": "rcpt-001", "event_id": "evt-002", "provider": "mail-provider", "status": "accepted", "message_id": "msg-1042", "delivered": null, "detail": "Accepted, no delivery confirmation."}
  ],
  "approvals": [
    {"id": "appr-001", "event_id": "evt-003", "prompt": "Send it?", "status": "timed_out"}
  ]
}
```

Rules the validator enforces: event ids unique, timestamps non-decreasing,
every `artifact_id`, `receipt_id`, `approval_id`, and `ref_ids` entry must
reference something that exists, artifact sha256 must be 64 hex characters.

## Turn the bundle into a handoff

Hand the bundle to Baton, or tell the user to run:

```bash
baton recover bundle.json --out-dir ./demo-out
```

That writes `handoff.json` and `handoff.md`: what the agent said, what the
receipts show, what changed, what is completed, what failed, what needs a
human, and what comes next. Any handoff renders in the demo UI by pasting
the JSON or choosing the file. Nothing is uploaded; rendering is local.

With a real model instead of the offline stub, set `BATON_EXTRACTOR=nebius`
and `NEBIUS_API_KEY` first. The stub is the default and needs no key.

## What Baton is not

It does not watch a live session. There is no daemon or log tail in v1.
It audits a finished or interrupted run after the fact. If a session was
never logged, Baton cannot recover it. Log from now on, and every future
session becomes diagnosable.
