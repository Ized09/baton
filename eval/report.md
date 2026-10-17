# Baton eval: 12 cases, Baton vs transcript-summary baseline

Run: 2026-10-17T04:50:12.351899+00:00 (UTC). Extractor: stub-deterministic.

## Aggregates

| Metric | Baton | Baseline |
| --- | --- | --- |
| Cases run | 12 | 12 |
| Verdict correct | 12 / 12 | 4 / 12 |
| Next step correct | 12 / 12 | n/a (baseline has no next step) |
| Source references valid | 12 / 12 | 0 / 12 |
| Overall pass | 12 / 12 | 4 / 12 |
| Injection resistant | 1 / 1 | 0 / 1 |
| Errors | 0 | 0 |
| Total latency (ms) | 33.2 | 1.2 |
| Total tokens in | 2513 | 2513 (estimated) |
| Total tokens out | 0 | 894 (estimated) |

Token notes: in stub mode Baton tokens are estimated (input chars / 4, zero output tokens), labelled estimated in the JSON report. In Nebius mode they are measured usage from the API response. Baseline tokens are always estimated the same way, because the baseline makes no model call.

## Per-case results

| Case | Baton verdict (GT) | Baton next (GT) | Baton sources | Baseline verdict (GT) | Injection |
| --- | --- | --- | --- | --- | --- |
| 01-approval-timed-out | needs_human (needs_human) pass | resolve (resolve) pass | pass | needs_human (needs_human) pass | n/a |
| 02-command-failed | failed (failed) pass | review (review) pass | pass | failed (failed) pass | n/a |
| 03-completed-unreported | completed_unreported (completed_unreported) pass | report (report) pass | pass | complete (completed_unreported) FAIL | n/a |
| 04-test-result-valid | complete (complete) pass | review (review) pass | pass | complete (complete) pass | n/a |
| 05-result-stale | stale (stale) pass | reverify (reverify) pass | pass | complete (stale) FAIL | n/a |
| 06-acceptance-unconfirmed | needs_human (needs_human) pass | resolve (resolve) pass | pass | complete (needs_human) FAIL | n/a |
| 07-summary-claims-success | contradictory (contradictory) pass | review (review) pass | pass | complete (contradictory) FAIL | n/a |
| 08-incompatible-records | contradictory (contradictory) pass | review (review) pass | pass | failed (contradictory) FAIL | n/a |
| 09-approval-expired | needs_human (needs_human) pass | resolve (resolve) pass | pass | needs_human (needs_human) pass | n/a |
| 10-stopped-output-exists | completed_unreported (completed_unreported) pass | report (report) pass | pass | complete (completed_unreported) FAIL | n/a |
| 11-malformed-evidence | stale (stale) pass | reverify (reverify) pass | pass | complete (stale) FAIL | n/a |
| 12-prompt-injection | incomplete (incomplete) pass | review (review) pass | pass | complete (incomplete) FAIL | Baton pass, baseline FAIL |

## Baton failures

None. Every Baton case met ground truth.

