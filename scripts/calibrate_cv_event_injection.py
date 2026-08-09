#!/usr/bin/env python3
"""
Iterative CI-width calibration for AI vs GOLD event injection.

NOT A QUALITY MEASURE (note added 2026-08-09). This drives
scripts/run_gold_vs_ai_comparison.py in a loop and reads its --output-json, and that
script is DEPRECATED: it judges the pipeline by patient counts and hazard ratios on
synthea_cdm_{aristotle,leader,plato}, which are generated FROM data/gold/ by
scripts/generate_synthea_from_gold.py, so a count partly measures the generator. See
AGENTS.md EVALUATION and docs/debugging/2026-08-09_benchmark_cdm_is_not_an_oracle.md.

What this IS still for: tuning how many events to inject so a confidence interval
reaches a target width. That calibration loop is arithmetic on its own output and does
not depend on the HR being a valid quality verdict. What its output is NOT evidence of:
that one pipeline is better than another.

Measure of record for concept-set quality: per-eligibility-criterion 1:1 overlap,
scripts/conceptset_overlap_eval.py --mode closure. Nothing currently replaces
gold-vs-generated HR comparison itself.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import sys
from pathlib import Path


ARTEMIS_DIR = Path(__file__).resolve().parents[1]
INJECT_SCRIPT = ARTEMIS_DIR / "scripts" / "inject_cv_events.py"
COMPARE_SCRIPT = ARTEMIS_DIR / "scripts" / "run_gold_vs_ai_comparison.py"
DEFAULT_RESULTS_JSON = Path("/tmp/gold_vs_ai_results.json")


@dataclasses.dataclass(frozen=True)
class RateParams:
    base_rate: float
    true_hr: float


@dataclasses.dataclass(frozen=True)
class StudyMetrics:
    ai_ci_width: float | None
    gold_ci_width: float | None
    ci_width_ratio: float | None
    ai_events: int | None
    gold_events: int | None


def _ci_width(ci_lower: float | None, ci_upper: float | None) -> float | None:
    if ci_lower is None or ci_upper is None:
        return None
    return float(ci_upper) - float(ci_lower)


def compute_ci_width_ratio(
    ai_ci_lower: float | None,
    ai_ci_upper: float | None,
    gold_ci_lower: float | None,
    gold_ci_upper: float | None,
) -> float | None:
    ai_width = _ci_width(ai_ci_lower, ai_ci_upper)
    gold_width = _ci_width(gold_ci_lower, gold_ci_upper)
    if ai_width is None or gold_width is None or gold_width <= 0:
        return None
    return ai_width / gold_width


def update_rates(
    params: RateParams,
    *,
    ai_ci_width: float | None,
    gold_ci_width: float | None,
    ai_events: int | None,
    gold_events: int | None,
    rate_step: float = 0.02,
    min_base_rate: float = 0.02,
    max_base_rate: float = 0.40,
) -> RateParams:
    """
    Update base event rate to bring AI/GOLD CI widths closer.

    Wider AI CI and fewer AI events -> increase base rate.
    Narrower AI CI and more AI events -> decrease base rate.
    """
    if ai_ci_width is None or gold_ci_width is None:
        return params

    ratio = ai_ci_width / gold_ci_width if gold_ci_width > 0 else None
    if ratio is None:
        return params

    ai_ev = ai_events or 0
    gold_ev = gold_events or 0
    next_base = params.base_rate

    if ratio > 1.10 or ai_ev < gold_ev:
        next_base += rate_step
    elif ratio < 0.90 and ai_ev > gold_ev:
        next_base -= rate_step

    next_base = min(max(next_base, min_base_rate), max_base_rate)
    return RateParams(base_rate=next_base, true_hr=params.true_hr)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate AI/GOLD CI width via event injection reruns")
    parser.add_argument("--studies", nargs="*", default=["LEADER", "PLATO", "ARISTOTLE"])
    parser.add_argument("--max-iters", type=int, default=6)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-rate", type=float, default=0.125)
    parser.add_argument("--true-hr", type=float, default=2.0)
    parser.add_argument("--target-low", type=float, default=0.9)
    parser.add_argument("--target-high", type=float, default=1.1)
    parser.add_argument("--rate-step", type=float, default=0.02)
    parser.add_argument("--skip-regenerate", action="store_true")
    parser.add_argument("--results-json", default=str(DEFAULT_RESULTS_JSON))
    parser.add_argument("--output-json", required=True)
    return parser.parse_args(argv)


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(cmd)}")


def _extract_events(payload: dict) -> int | None:
    tx = payload.get("treatment_events")
    ctrl = payload.get("comparator_events")
    if tx is None and ctrl is None:
        return None
    return int(tx or 0) + int(ctrl or 0)


def _load_study_metrics(results_json: Path, study_name: str) -> StudyMetrics:
    payload = json.loads(results_json.read_text())
    study = payload.get(study_name, {})
    ai = study.get("ai", {})
    gold = study.get("gold", {})

    ai_width = ai.get("ci_width") if ai else _ci_width(ai.get("ci_lower"), ai.get("ci_upper"))
    gold_width = gold.get("ci_width") if gold else _ci_width(gold.get("ci_lower"), gold.get("ci_upper"))

    if ai_width is None:
        ai_width = _ci_width(ai.get("ci_lower"), ai.get("ci_upper"))
    if gold_width is None:
        gold_width = _ci_width(gold.get("ci_lower"), gold.get("ci_upper"))

    ratio = None
    if ai_width is not None and gold_width not in (None, 0):
        ratio = float(ai_width) / float(gold_width)

    return StudyMetrics(
        ai_ci_width=ai_width,
        gold_ci_width=gold_width,
        ci_width_ratio=ratio,
        ai_events=_extract_events(ai),
        gold_events=_extract_events(gold),
    )


def calibrate_study(
    *,
    study: str,
    args: argparse.Namespace,
    initial_rates: RateParams,
) -> list[dict]:
    rates = initial_rates
    history: list[dict] = []
    results_json = Path(args.results_json)

    for iteration in range(1, args.max_iters + 1):
        treatment_rate = min(rates.base_rate * rates.true_hr, 0.95)

        inject_cmd = [
            sys.executable,
            str(INJECT_SCRIPT),
            "--studies",
            study,
            "--seed",
            str(args.seed + iteration),
            "--treatment-rate",
            f"{treatment_rate:.6f}",
            "--comparator-rate",
            f"{rates.base_rate:.6f}",
        ]
        if args.skip_regenerate:
            inject_cmd.append("--skip-regenerate")
        _run(inject_cmd)

        _run(
            [
                sys.executable,
                str(COMPARE_SCRIPT),
                "--studies",
                study,
                "--output-json",
                str(results_json),
            ]
        )

        metrics = _load_study_metrics(results_json, study)
        history.append(
            {
                "study": study,
                "iter": iteration,
                "base_rate": rates.base_rate,
                "true_hr": rates.true_hr,
                "treatment_rate": treatment_rate,
                "ai_ci_width": metrics.ai_ci_width,
                "gold_ci_width": metrics.gold_ci_width,
                "ci_width_ratio": metrics.ci_width_ratio,
                "ai_events": metrics.ai_events,
                "gold_events": metrics.gold_events,
            }
        )

        if metrics.ci_width_ratio is not None and args.target_low <= metrics.ci_width_ratio <= args.target_high:
            break

        rates = update_rates(
            rates,
            ai_ci_width=metrics.ai_ci_width,
            gold_ci_width=metrics.gold_ci_width,
            ai_events=metrics.ai_events,
            gold_events=metrics.gold_events,
            rate_step=args.rate_step,
        )

    return history


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    all_history: list[dict] = []
    for study in [s.upper() for s in args.studies]:
        history = calibrate_study(
            study=study,
            args=args,
            initial_rates=RateParams(base_rate=args.base_rate, true_hr=args.true_hr),
        )
        all_history.extend(history)

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(all_history, indent=2) + "\n")
    print(f"Calibration history written to {output_path}")


if __name__ == "__main__":
    main()
