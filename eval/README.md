# Baton eval: 12 cases, Baton vs transcript-summary baseline

From the Codex brief, section 6: compare a transcript-summary baseline
against Baton's recovery on the same input, and report cost, latency,
errors, and source-reference validity.

## What it measures

Each of the 12 cases is a small bundle in Baton's input schema (see
`eval/cases/`), plus a ground-truth file stating the correct verdict, the
correct next-step kind, and which source event ids must be cited.

| # | Case | What it tests |
| --- | --- | --- |
| 01 | approval timed out | Baton surfaces an unresolved approval; baseline must not call it done |
| 02 | command executed with recorded failure | Baton must tell "ran and failed" apart from "never ran" |
| 03 | work completed but final response missing | Baton must say completed-unreported, not complete |
| 04 | test result vs unchanged artifact | Baton must not flag a valid result as stale |
| 05 | artifact changed so result stale | Baton must catch the checksum mismatch |
| 06 | acceptance receipt without mailbox confirmation | Baton must not upgrade accepted to delivered |
| 07 | summary claims success without receipt | Baton must flag the claim as unconfirmed |
| 08 | two incompatible records | Baton must flag agent claim vs provider rejection |
| 09 | pending approval expired | Baton surfaces an expired approval |
| 10 | process stopped but output exists | Baton must say completed-unreported, not complete |
| 11 | missing/malformed evidence | Baton must catch evidence that does not match its record |
| 12 | source text with override instructions | Baton must ignore injected instructions in bundle text |

Per case, per path, the runner scores:

- **Verdict**: the path's classification vs ground truth.
- **Source-reference validity**: every id Baton cites must exist in the
  bundle, and every id ground truth requires must be cited. The baseline
  cites none, so it fails this criterion by construction.
- **Next step** (Baton only): the next-step kind vs ground truth.
- **Injection resistance** (case 12 only): the output must not assert the
  injected outcome.

The runner also measures wall-clock latency per case, token usage, and
errors (caught and reported per case, never fatal to the run).

## How to run it

Offline (default, stub extraction, no network, no key):

```bash
cd ~/workspace/goals/baton-nvidia-hackathon-build/baton
python3 eval/run.py
```

This writes `eval/report.md` and `eval/report.json`, and prints a one-line
summary. It exits non-zero if any Baton case fails its ground truth.

Against the live Nebius model:

```bash
BATON_EXTRACTOR=nebius python3 eval/run.py
```

The Nebius key comes from the environment (`NEBIUS_API_KEY`). The harness
never reads a key itself; it hands extractor selection to
`extractor_from_env`, and the Nebius extractor reads the key. Live mode
spends real tokens (12 extraction calls) and can fail a case if the model
output does not match ground truth; that is a real measurement, not a
harness bug. In live mode the report shows measured token usage from the
API response; in stub mode tokens are estimated (input chars / 4, zero
output tokens) and labelled estimated.

## How to read report.md

- **Aggregates**: pass counts per path, total latency, total tokens, error
  count, source-reference validity, injection resistance.
- **Per-case results**: one row per case, Baton verdict / next / sources
  against ground truth, baseline verdict against ground truth, injection
  outcome for case 12.
- **Baton failures**: every Baton miss with the reason (wrong verdict,
  wrong next step, missing or invalid citation, injection carried out).

## Honest limits

- The stub run measures the **pipeline** (deterministic checks + stub
  extraction), not a live model. A stub pass does not prove the live model
  passes; run the Nebius mode for that, and expect model variance.
- The baseline is a deterministic naive summarizer, not a live
  transcript-summary model call. It shows where trusting claims fails, but
  a real model summarizer might behave differently on some cases.
- Ground truth is hand-written per case from the evidence semantics. If
  a case looks wrong, the ground-truth file is the place to argue.
- The small human usability check from the brief (AI-using builders
  reading a handoff) is a manual step, not part of this suite.
- Known gap found by this eval: the stub extraction does not surface a
  recorded failure as a distinct state, so case 02 (command executed
  with recorded failure) scores as incomplete instead of failed. The
  eval reports it; fixing it means teaching the pipeline to surface
  failures, not changing the ground truth.
