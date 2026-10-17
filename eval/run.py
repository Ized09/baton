"""Eval runner: 12 cases through Baton and the transcript-summary baseline.

Default run is offline (stub extractor). For the live Nebius mode, set
BATON_EXTRACTOR=nebius with NEBIUS_API_KEY in the environment; the harness
never reads a key itself, it hands selection to extractor_from_env.

Per case, per path: wall-clock latency, token usage, errors (caught and
reported, never fatal), and the scored criteria from score.py. Writes
report.md (human-readable) and report.json (machine-readable) next to this
file unless --out is given. Exits non-zero if any Baton case fails its
ground truth or errors.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# The eval lives next to src/; make both importable when run directly.
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_HERE))

from baton.cost import CostGuard  # noqa: E402
from baton.nebius import extractor_from_env  # noqa: E402
from baton.recover import recover  # noqa: E402

from baseline import run_baseline  # noqa: E402
from score import score_baseline, score_baton  # noqa: E402


def load_cases(cases_dir: Path) -> list[tuple[str, dict, dict]]:
    """Load (name, bundle, ground truth) for every case in the directory."""
    cases = []
    for bundle_path in sorted(cases_dir.glob("*.json")):
        if bundle_path.name.endswith(".ground_truth.json"):
            continue
        name = bundle_path.stem
        gt_path = cases_dir / f"{name}.ground_truth.json"
        if not gt_path.exists():
            raise FileNotFoundError(f"missing ground truth for case {name}")
        cases.append(
            (
                name,
                json.loads(bundle_path.read_text()),
                json.loads(gt_path.read_text()),
            )
        )
    if not cases:
        raise FileNotFoundError(f"no cases found in {cases_dir}")
    return cases


def estimate_tokens(text: str) -> int:
    """Same rough estimate the CostGuard uses: ~4 chars per token."""
    return max(1, len(text) // 4)


def run_one_case(name: str, bundle: dict, gt: dict, extractor, db_path: Path) -> dict:
    """Run both paths on one case. Errors are recorded, never raised."""
    result: dict = {"case": name, "ground_truth": gt}

    # Baton path.
    started = time.perf_counter()
    try:
        record = recover(bundle, db_path=db_path, extractor=extractor)
        baton_error = None
        extraction = record.get("extraction", {})
        baton_tokens = {
            "model": extraction.get("model", "unknown"),
            "tokens_in": extraction.get("tokens_in", 0),
            "tokens_out": extraction.get("tokens_out", 0),
            "estimated": extraction.get("estimated", True),
        }
        baton_score = score_baton(record, bundle, gt)
    except Exception as exc:  # noqa: BLE001 - eval must report, not crash
        record = None
        baton_error = f"{type(exc).__name__}: {exc}"
        baton_tokens = {"model": "unknown", "tokens_in": 0, "tokens_out": 0, "estimated": True}
        baton_score = None
    result["baton"] = {
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "tokens": baton_tokens,
        "score": baton_score,
        "error": baton_error,
    }

    # Baseline path.
    started = time.perf_counter()
    try:
        baseline_out = run_baseline(bundle)
        baseline_error = None
        baseline_score = score_baseline(baseline_out, bundle, gt)
        baseline_tokens = {
            "model": "naive-summary-baseline",
            "tokens_in": estimate_tokens(json.dumps(bundle)),
            "tokens_out": estimate_tokens(baseline_out["summary"]),
            "estimated": True,
        }
    except Exception as exc:  # noqa: BLE001 - eval must report, not crash
        baseline_error = f"{type(exc).__name__}: {exc}"
        baseline_score = None
        baseline_tokens = {"model": "naive-summary-baseline", "tokens_in": 0, "tokens_out": 0, "estimated": True}
        baseline_out = None
    result["baseline"] = {
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "tokens": baseline_tokens,
        "score": baseline_score,
        "error": baseline_error,
        "summary": (baseline_out or {}).get("summary", ""),
    }
    return result


def aggregate(results: list[dict]) -> dict:
    """Totals across cases, computed from the measured per-case results."""
    baton_scores = [r["baton"]["score"] for r in results if r["baton"]["score"]]
    baseline_scores = [r["baseline"]["score"] for r in results if r["baseline"]["score"]]
    inj = [r for r in results if r["ground_truth"].get("injection")]
    baton_inj = [r for r in inj if r["baton"]["score"]]
    baseline_inj = [r for r in inj if r["baseline"]["score"]]
    return {
        "cases": len(results),
        "baton": {
            "verdict_pass": sum(1 for s in baton_scores if s["verdict_correct"]),
            "next_pass": sum(1 for s in baton_scores if s["next_correct"]),
            "source_pass": sum(1 for s in baton_scores if s["source_pass"]),
            "overall_pass": sum(1 for s in baton_scores if s["overall"]),
            "errors": sum(1 for r in results if r["baton"]["error"]),
            "latency_ms": round(sum(r["baton"]["latency_ms"] for r in results), 1),
            "tokens_in": sum(r["baton"]["tokens"]["tokens_in"] for r in results),
            "tokens_out": sum(r["baton"]["tokens"]["tokens_out"] for r in results),
            "injection_resistant": sum(
                1 for r in baton_inj if r["baton"]["score"]["injection_resistant"]
            ),
            "injection_cases": len(baton_inj),
        },
        "baseline": {
            "verdict_pass": sum(1 for s in baseline_scores if s["verdict_correct"]),
            "source_pass": sum(1 for s in baseline_scores if s["source_pass"]),
            "overall_pass": sum(1 for s in baseline_scores if s["overall"]),
            "errors": sum(1 for r in results if r["baseline"]["error"]),
            "latency_ms": round(sum(r["baseline"]["latency_ms"] for r in results), 1),
            "tokens_in": sum(r["baseline"]["tokens"]["tokens_in"] for r in results),
            "tokens_out": sum(r["baseline"]["tokens"]["tokens_out"] for r in results),
            "injection_resistant": sum(
                1 for r in baseline_inj if r["baseline"]["score"]["injection_resistant"]
            ),
            "injection_cases": len(baseline_inj),
        },
    }


def _yn(value: bool | None) -> str:
    if value is None:
        return "n/a"
    return "pass" if value else "FAIL"


def render_report(results: list[dict], agg: dict, extractor_label: str) -> str:
    """Markdown report. Every number comes from the measured run."""
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "# Baton eval: 12 cases, Baton vs transcript-summary baseline",
        "",
        f"Run: {now} (UTC). Extractor: {extractor_label}.",
        "",
        "## Aggregates",
        "",
        "| Metric | Baton | Baseline |",
        "| --- | --- | --- |",
        f"| Cases run | {agg['cases']} | {agg['cases']} |",
        f"| Verdict correct | {agg['baton']['verdict_pass']} / {agg['cases']} | {agg['baseline']['verdict_pass']} / {agg['cases']} |",
        f"| Next step correct | {agg['baton']['next_pass']} / {agg['cases']} | n/a (baseline has no next step) |",
        f"| Source references valid | {agg['baton']['source_pass']} / {agg['cases']} | {agg['baseline']['source_pass']} / {agg['cases']} |",
        f"| Overall pass | {agg['baton']['overall_pass']} / {agg['cases']} | {agg['baseline']['overall_pass']} / {agg['cases']} |",
        f"| Injection resistant | {agg['baton']['injection_resistant']} / {agg['baton']['injection_cases']} | {agg['baseline']['injection_resistant']} / {agg['baseline']['injection_cases']} |",
        f"| Errors | {agg['baton']['errors']} | {agg['baseline']['errors']} |",
        f"| Total latency (ms) | {agg['baton']['latency_ms']} | {agg['baseline']['latency_ms']} |",
        f"| Total tokens in | {agg['baton']['tokens_in']} | {agg['baseline']['tokens_in']} (estimated) |",
        f"| Total tokens out | {agg['baton']['tokens_out']} | {agg['baseline']['tokens_out']} (estimated) |",
        "",
        "Token notes: in stub mode Baton tokens are estimated (input chars / 4, "
        "zero output tokens), labelled estimated in the JSON report. In Nebius "
        "mode they are measured usage from the API response. Baseline tokens "
        "are always estimated the same way, because the baseline makes no "
        "model call.",
        "",
        "## Per-case results",
        "",
        "| Case | Baton verdict (GT) | Baton next (GT) | Baton sources | Baseline verdict (GT) | Injection |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        gt = r["ground_truth"]
        b = r["baton"]["score"]
        bl = r["baseline"]["score"]
        if b is None:
            b_cells = [f"ERROR: {r['baton']['error']}", "-", "-"]
        else:
            b_cells = [
                f"{b['verdict']} ({gt['verdict']}) {_yn(b['verdict_correct'])}",
                f"{b['next_kind']} ({gt['next_kind']}) {_yn(b['next_correct'])}",
                _yn(b["source_pass"]),
            ]
        if bl is None:
            bl_cell = f"ERROR: {r['baseline']['error']}"
        else:
            bl_cell = f"{bl['verdict']} ({gt['verdict']}) {_yn(bl['verdict_correct'])}"
        inj = "n/a"
        if gt.get("injection"):
            inj = f"Baton {_yn(b['injection_resistant']) if b else 'ERROR'}, baseline {_yn(bl['injection_resistant']) if bl else 'ERROR'}"
        lines.append(
            f"| {r['case']} | {b_cells[0]} | {b_cells[1]} | {b_cells[2]} | {bl_cell} | {inj} |"
        )
    lines.append("")
    failures = [
        r for r in results
        if r["baton"]["error"] or (r["baton"]["score"] and not r["baton"]["score"]["overall"])
    ]
    if failures:
        lines.append("## Baton failures (ground truth not met)")
        lines.append("")
        for r in failures:
            gt = r["ground_truth"]
            b = r["baton"]["score"]
            if r["baton"]["error"]:
                lines.append(f"- {r['case']}: Baton path errored: {r['baton']['error']}")
                continue
            reasons = []
            if not b["verdict_correct"]:
                reasons.append(f"verdict {b['verdict']} != ground truth {gt['verdict']}")
            if not b["next_correct"]:
                reasons.append(f"next {b['next_kind']} != ground truth {gt['next_kind']}")
            if not b["source_pass"]:
                if b["cited_invalid"]:
                    reasons.append(f"cited ids not in bundle: {', '.join(b['cited_invalid'])}")
                missing = sorted(set(b["required_evidence"]) - set(b["cited"]))
                if missing:
                    reasons.append(f"required evidence not cited: {', '.join(missing)}")
            if b["injection_resistant"] is False:
                reasons.append("output carried out the injected instruction")
            lines.append(f"- {r['case']}: " + "; ".join(reasons))
        lines.append("")
    else:
        lines.append("## Baton failures")
        lines.append("")
        lines.append("None. Every Baton case met ground truth.")
        lines.append("")
    return "\n".join(lines) + "\n"


def run_eval(
    cases_dir: Path, out_path: Path, json_path: Path | None = None
) -> tuple[list[dict], dict, int]:
    """Run every case through both paths, write reports, return exit code."""
    cases = load_cases(cases_dir)
    extractor = extractor_from_env(cost_guard=CostGuard())
    extractor_label = getattr(extractor, "model", type(extractor).__name__)
    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="baton-eval-") as tmp:
        db_path = Path(tmp) / "eval.db"
        for name, bundle, gt in cases:
            results.append(run_one_case(name, bundle, gt, extractor, db_path))
    agg = aggregate(results)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_report(results, agg, extractor_label))
    if json_path is not None:
        json_path.write_text(
            json.dumps(
                {"extractor": extractor_label, "aggregates": agg, "results": results},
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    failed = any(
        r["baton"]["error"] or not (r["baton"]["score"] or {}).get("overall")
        for r in results
    )
    return results, agg, (1 if failed else 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Baton 12-case eval.")
    parser.add_argument(
        "--cases-dir",
        type=Path,
        default=_HERE / "cases",
        help="Directory holding the case bundles and ground truth files.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_HERE / "report.md",
        help="Where to write the Markdown report.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=_HERE / "report.json",
        help="Where to write the JSON report.",
    )
    args = parser.parse_args(argv)
    _, agg, code = run_eval(args.cases_dir, args.out, args.json)
    print(
        f"Baton: verdict {agg['baton']['verdict_pass']}/{agg['cases']}, "
        f"next {agg['baton']['next_pass']}/{agg['cases']}, "
        f"sources {agg['baton']['source_pass']}/{agg['cases']}, "
        f"errors {agg['baton']['errors']}; "
        f"Baseline: verdict {agg['baseline']['verdict_pass']}/{agg['cases']}, "
        f"errors {agg['baseline']['errors']}. "
        f"Report: {args.out}"
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
