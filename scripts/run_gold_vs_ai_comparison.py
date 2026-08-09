#!/usr/bin/env python3
# DEPRECATED 2026-08-09.
#
# This measured pipeline quality as patient counts and Cox hazard ratios for the
# generated ("AI") cohort versus the gold cohort, run against
# synthea_cdm_{leader,plato,aristotle}. That is superseded because those CDMs are
# generated FROM data/gold/ by scripts/generate_synthea_from_gold.py, so any count
# on them partly measures that generator's conventions rather than the pipeline:
# gold writes the ARISTOTLE platelet threshold as 100 (thousands/uL) while the
# protocol PDF writes 100,000/mm3, nothing records a unit, and that 1000x gap alone
# took the cohort to 0 patients.
# Run instead: scripts/conceptset_overlap_eval.py --mode closure   (per-criterion 1:1
# overlap against data/gold/, the measure of record; see AGENTS.md EVALUATION).
# Not replaced: nothing currently produces a survival/HR effect-size comparison
# between gold and generated cohorts. The canonical evaluator scores concept sets,
# not outcomes. If an effect-size comparison is needed again it must run against a
# CDM that was NOT generated from data/gold/.
"""
Gold vs AI cohort comparison script.
Runs Agent5 survival analysis for both gold and AI treatment cohorts
and produces a comparison table.

Usage: python3 artemis/scripts/run_gold_vs_ai_comparison.py
"""
import argparse
import os
import sys

# Add artemis/src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:mypass@127.0.0.1:5432/postgres")

import dataclasses
import json
import logging
import random

logging.basicConfig(level=logging.WARNING)

from src.agents.agent5.workflow import Agent5Workflow
from src.analysis.omop_connector import OMOPConnector
from src.pipeline.webapi_client import CohortTableReference

DB_URL = os.environ["DATABASE_URL"]


@dataclasses.dataclass
class StudyConfig:
    name: str
    cdm_schema: str
    results_schema: str
    source_key: str
    ai_treatment_id: int
    gold_treatment_id: int  # 0 if not available
    outcome_id: int
    followup_days: int = 365


STUDIES = [
    StudyConfig(
        name="LEADER",
        cdm_schema="synthea_cdm_leader",
        results_schema="synthea_cdm_leader_results",
        source_key="LEADER_BENCHMARK",
        ai_treatment_id=840,
        gold_treatment_id=1136,
        outcome_id=841,
    ),
    StudyConfig(
        name="PLATO",
        cdm_schema="synthea_cdm_plato",
        results_schema="synthea_cdm_plato_results",
        source_key="PLATO_BENCHMARK",
        ai_treatment_id=941,
        gold_treatment_id=1137,
        outcome_id=943,
    ),
    StudyConfig(
        name="ARISTOTLE",
        cdm_schema="synthea_cdm_aristotle",
        results_schema="synthea_cdm_aristotle_results",
        source_key="ARISTOTLE_BENCHMARK",
        ai_treatment_id=1127,
        gold_treatment_id=1138,
        outcome_id=1128,
    ),
]

PUBLISHED_HR = {
    "LEADER": {"hr": 0.87, "ci_lower": 0.78, "ci_upper": 0.97},
    "PLATO": {"hr": 0.84, "ci_lower": 0.77, "ci_upper": 0.92},
    "ARISTOTLE": {"hr": 0.79, "ci_lower": 0.66, "ci_upper": 0.95},
}


def _ci_width(ci_lower, ci_upper):
    if ci_lower is None or ci_upper is None:
        return None
    return float(ci_upper) - float(ci_lower)


def get_cohort_count(conn_string: str, schema: str, cohort_id: int) -> int:
    """Get distinct patient count from cohort table."""
    import sqlalchemy
    engine = sqlalchemy.create_engine(conn_string)
    with engine.connect() as conn:
        result = conn.execute(
            sqlalchemy.text(
                f"SELECT COUNT(DISTINCT subject_id) FROM {schema}.cohort WHERE cohort_definition_id = :cid"
            ),
            {"cid": cohort_id},
        )
        return result.scalar() or 0


def get_overlap(conn_string: str, schema: str, gold_id: int, ai_id: int) -> dict:
    """Get overlap stats between gold and AI cohorts."""
    import sqlalchemy
    engine = sqlalchemy.create_engine(conn_string)
    with engine.connect() as conn:
        result = conn.execute(
            sqlalchemy.text(f"""
                SELECT
                    COUNT(DISTINCT g.subject_id) as gold_n,
                    COUNT(DISTINCT a.subject_id) as ai_n,
                    COUNT(DISTINCT CASE WHEN a.subject_id IS NOT NULL THEN g.subject_id END) as overlap_n
                FROM {schema}.cohort g
                LEFT JOIN {schema}.cohort a
                    ON g.subject_id = a.subject_id AND a.cohort_definition_id = :ai_id
                WHERE g.cohort_definition_id = :gold_id
            """),
            {"gold_id": gold_id, "ai_id": ai_id},
        )
        row = result.fetchone()
        gold_n = row[0] or 0
        ai_n_check = get_cohort_count(conn_string, schema, ai_id)
        overlap_n = row[2] or 0
        return {
            "gold_n": gold_n,
            "ai_n": ai_n_check,
            "overlap_n": overlap_n,
            "recall": round(overlap_n / gold_n, 3) if gold_n > 0 else None,
            "precision": round(overlap_n / ai_n_check, 3) if ai_n_check > 0 else None,
        }


def get_cohort_person_ids_and_min_date(conn_string: str, schema: str, cohort_id: int) -> tuple[set[int], object]:
    """Get person IDs and minimum cohort_start_date for a cohort."""
    import sqlalchemy
    engine = sqlalchemy.create_engine(conn_string)
    with engine.connect() as conn:
        rows = conn.execute(
            sqlalchemy.text(
                f"""
                SELECT DISTINCT subject_id, cohort_start_date
                FROM {schema}.cohort
                WHERE cohort_definition_id = :cid
                """
            ),
            {"cid": cohort_id},
        ).fetchall()
    ids = {int(r[0]) for r in rows}
    min_date = min((r[1] for r in rows), default=None)
    return ids, min_date


def get_all_cdm_person_ids(conn_string: str, cdm_schema: str) -> set[int]:
    """Get all distinct person IDs in CDM person table."""
    import sqlalchemy
    engine = sqlalchemy.create_engine(conn_string)
    with engine.connect() as conn:
        rows = conn.execute(sqlalchemy.text(f"SELECT DISTINCT person_id FROM {cdm_schema}.person")).fetchall()
    return {int(r[0]) for r in rows}


def build_fixed_rest_comparator_ids(
    *,
    all_person_ids: set[int],
    excluded_ids: set[int],
    max_comparator: int,
    seed: int,
) -> list[int]:
    """
    Build deterministic fixed comparator IDs shared across AI and GOLD runs.
    """
    pool = sorted(all_person_ids - excluded_ids)
    if len(pool) <= max_comparator:
        return pool
    rng = random.Random(seed)
    return sorted(rng.sample(pool, max_comparator))


def run_agent5_for_cohort(
    study: StudyConfig,
    treatment_id: int,
    label: str,
    fixed_comparator_ids: list[int] | None = None,
    fixed_comparator_index_date=None,
) -> dict:
    """Run Agent5 analysis for a given treatment cohort."""
    print(f"  Running Agent5 for {study.name} {label} (treatment={treatment_id}, outcome={study.outcome_id})...")

    connector = OMOPConnector(
        connection_string=DB_URL,
        schema=study.cdm_schema,
    )

    # Check counts
    treatment_n = get_cohort_count(DB_URL, study.results_schema, treatment_id)
    outcome_n = get_cohort_count(DB_URL, study.results_schema, study.outcome_id)
    print(f"    treatment_n={treatment_n}, outcome_n={outcome_n}")

    if treatment_n == 0:
        return {
            "error": f"treatment cohort {treatment_id} is empty",
            "treatment_n": 0,
        }

    target_ref = CohortTableReference(
        cohort_definition_id=treatment_id,
        results_schema=study.results_schema,
        person_count=treatment_n,
        source_key=study.source_key,
        name=f"{study.name} {label} treatment",
    )
    outcome_ref = CohortTableReference(
        cohort_definition_id=study.outcome_id,
        results_schema=study.results_schema,
        person_count=outcome_n,
        source_key=study.source_key,
        name=f"{study.name} primary outcome",
    )

    try:
        dataset = connector.build_analysis_dataset_from_generated_cohorts(
            target_ref=target_ref,
            comparator_ref=None,  # treatment_vs_rest mode
            outcome_ref=outcome_ref,
            followup_days=study.followup_days,
            comparator_person_ids=fixed_comparator_ids,
            comparator_index_date_override=fixed_comparator_index_date,
            comparator_sample_seed=42,
        )
    except Exception as exc:
        return {"error": f"dataset build failed: {exc}", "treatment_n": treatment_n}

    if dataset is None or getattr(dataset, "empty", True):
        return {"error": "empty dataset", "treatment_n": treatment_n}

    treatment_count = int((dataset["treatment"] == 1).sum())
    comparator_count = int((dataset["treatment"] == 0).sum())
    print(f"    dataset: treatment={treatment_count}, comparator={comparator_count}, total={len(dataset)}")

    workflow = Agent5Workflow()
    workflow.configure(
        target_cohort_id=treatment_id,
        comparator_cohort_id=0,
        outcome_definition={"concept_ids": [0], "window_days": study.followup_days},
        analysis_method="iptw",
    )

    try:
        result = workflow.run(data=dataset)
    except Exception as exc:
        return {
            "error": f"Agent5 failed: {exc}",
            "treatment_n": treatment_count,
            "comparator_n": comparator_count,
        }

    hr = result.get("hazard_ratio") or {}
    ci_low = hr.get("ci_lower")
    ci_high = hr.get("ci_upper")
    return {
        "treatment_n": treatment_count,
        "comparator_n": comparator_count,
        "hr": hr.get("hr"),
        "ci_lower": ci_low,
        "ci_upper": ci_high,
        "ci_width": _ci_width(ci_low, ci_high),
        "p_value": hr.get("p_value"),
        "treatment_events": result.get("treatment_events"),
        "comparator_events": result.get("comparator_events"),
        "analysis_method": result.get("analysis_method"),
        "matched_pairs": result.get("n_matched_pairs"),
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run Gold vs AI cohort HR comparison")
    parser.add_argument("--studies", nargs="*", default=[s.name for s in STUDIES])
    parser.add_argument("--output-json", default="/tmp/gold_vs_ai_results.json")
    parser.add_argument(
        "--comparator-mode",
        choices=["fixed_rest", "legacy_rest"],
        default="fixed_rest",
        help="fixed_rest: shared deterministic comparator for AI/GOLD; legacy_rest: per-target REST comparator.",
    )
    parser.add_argument(
        "--comparator-seed",
        type=int,
        default=42,
        help="Seed for deterministic comparator sampling in fixed_rest mode.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    selected_names = {s.upper() for s in args.studies}
    selected_studies = [s for s in STUDIES if s.name in selected_names]
    if not selected_studies:
        raise ValueError(f"No valid studies selected. Available: {[s.name for s in STUDIES]}")

    results = {}

    for study in selected_studies:
        print(f"\n{'='*60}")
        print(f"Study: {study.name}")
        print(f"{'='*60}")

        # Get overlap stats
        gold_n = get_cohort_count(DB_URL, study.results_schema, study.gold_treatment_id)
        ai_n = get_cohort_count(DB_URL, study.results_schema, study.ai_treatment_id)
        print(f"Gold cohort ({study.gold_treatment_id}) count: {gold_n}")

        if gold_n > 0:
            overlap = get_overlap(DB_URL, study.results_schema, study.gold_treatment_id, study.ai_treatment_id)
        else:
            overlap = {
                "gold_n": 0,
                "ai_n": ai_n,
                "overlap_n": 0,
                "recall": None,
                "precision": None,
            }
        print(f"Overlap: {overlap}")

        fixed_comparator_ids = None
        fixed_comparator_index_date = None
        comparator_meta = {"mode": args.comparator_mode}
        if args.comparator_mode == "fixed_rest":
            ai_ids, ai_min_date = get_cohort_person_ids_and_min_date(
                DB_URL,
                study.results_schema,
                study.ai_treatment_id,
            )
            gold_ids, gold_min_date = get_cohort_person_ids_and_min_date(
                DB_URL,
                study.results_schema,
                study.gold_treatment_id,
            )
            all_ids = get_all_cdm_person_ids(DB_URL, study.cdm_schema)
            excluded = ai_ids | gold_ids
            max_comparator = max(max(len(ai_ids), len(gold_ids), 1) * 10, 1)
            fixed_comparator_ids = build_fixed_rest_comparator_ids(
                all_person_ids=all_ids,
                excluded_ids=excluded,
                max_comparator=max_comparator,
                seed=args.comparator_seed,
            )
            min_candidates = [d for d in [ai_min_date, gold_min_date] if d is not None]
            fixed_comparator_index_date = min(min_candidates) if min_candidates else None
            comparator_meta.update(
                {
                    "seed": args.comparator_seed,
                    "excluded_count": len(excluded),
                    "comparator_count": len(fixed_comparator_ids),
                    "max_comparator": max_comparator,
                    "index_date": str(fixed_comparator_index_date) if fixed_comparator_index_date else None,
                }
            )
            print(
                f"Fixed comparator: n={len(fixed_comparator_ids)} "
                f"(excluded={len(excluded)}, max={max_comparator}, seed={args.comparator_seed})"
            )

        # Run AI analysis
        print(f"\n  AI cohort analysis:")
        ai_result = run_agent5_for_cohort(
            study,
            study.ai_treatment_id,
            "AI",
            fixed_comparator_ids=fixed_comparator_ids,
            fixed_comparator_index_date=fixed_comparator_index_date,
        )

        # Run Gold analysis (only if gold has patients)
        if gold_n > 0:
            print(f"\n  Gold cohort analysis:")
            gold_result = run_agent5_for_cohort(
                study,
                study.gold_treatment_id,
                "Gold",
                fixed_comparator_ids=fixed_comparator_ids,
                fixed_comparator_index_date=fixed_comparator_index_date,
            )
        else:
            gold_result = {"error": "gold cohort empty (0 patients - gold criteria too restrictive for Synthea)", "treatment_n": 0}
            print(f"  Skipping Gold analysis (0 patients)")

        results[study.name] = {
            "overlap": overlap,
            "comparator": comparator_meta,
            "ai": ai_result,
            "gold": gold_result,
        }

    # Print summary table
    print(f"\n\n{'='*120}")
    print("SUMMARY TABLE")
    print(f"{'='*120}")
    header = f"{'Study':<12} | {'Gold N':>8} | {'AI N':>6} | {'Overlap':>8} | {'Recall':>8} | {'Precision':>10} | {'Gold HR [95% CI]':<22} | {'AI HR [95% CI]':<22} | {'Published HR':<22}"
    print(header)
    print("-" * 120)

    for study_name, data in results.items():
        overlap = data["overlap"]
        ai = data["ai"]
        gold = data["gold"]
        pub = PUBLISHED_HR.get(study_name)

        gold_n = overlap.get("gold_n", 0)
        ai_n = overlap.get("ai_n", 0)
        overlap_n = overlap.get("overlap_n", 0)
        recall = f"{overlap['recall']:.1%}" if overlap.get("recall") is not None else "N/A"
        precision = f"{overlap['precision']:.1%}" if overlap.get("precision") is not None else "N/A"

        if gold.get("hr") is not None:
            gold_hr_str = f"{gold['hr']:.3f} [{gold['ci_lower']:.3f}, {gold['ci_upper']:.3f}]"
        elif gold.get("error"):
            gold_hr_str = f"N/A ({gold['error'][:30]})"
        else:
            gold_hr_str = "N/A"

        if ai.get("hr") is not None:
            ai_hr_str = f"{ai['hr']:.3f} [{ai['ci_lower']:.3f}, {ai['ci_upper']:.3f}]"
        elif ai.get("error"):
            ai_hr_str = f"N/A ({ai['error'][:30]})"
        else:
            ai_hr_str = "N/A"

        pub_str = (
            f"{pub['hr']} [{pub['ci_lower']}, {pub['ci_upper']}]"
            if pub
            else "N/A"
        )

        print(f"{study_name:<12} | {gold_n:>8} | {ai_n:>6} | {overlap_n:>8} | {recall:>8} | {precision:>10} | {gold_hr_str:<22} | {ai_hr_str:<22} | {pub_str:<22}")

    print()
    print("Notes:")
    print("- Gold cohort uses original trial CIRCE definition (may have low yield on Synthea due to strict eligibility criteria)")
    print("- AI cohort uses artemis-generated CIRCE definition")
    print("- HR computed via IPTW (treatment_vs_rest mode)")
    print("- Injected event rates depend on the latest inject/calibration run settings")
    print("- Published HR: from actual RCT papers (different populations and endpoints)")

    with open(args.output_json, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {args.output_json}")
    return results


if __name__ == "__main__":
    print(
        "\n"
        "=========================================================================\n"
        "DEPRECATED 2026-08-09: run_gold_vs_ai_comparison.py\n"
        "Patient counts / HRs on synthea_cdm_* are NOT evidence of pipeline quality.\n"
        "Those CDMs are generated FROM data/gold/ (generate_synthea_from_gold.py);\n"
        "the unrecorded 1000x platelet-unit gap alone took ARISTOTLE to 0 patients.\n"
        "Measure of record: scripts/conceptset_overlap_eval.py --mode closure\n"
        "(see AGENTS.md EVALUATION). Running anyway.\n"
        "=========================================================================\n",
        file=sys.stderr,
    )
    main()
