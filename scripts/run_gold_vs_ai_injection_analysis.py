#!/usr/bin/env python3
"""
Gold vs AI cohort Cox PH comparison using the SAME injected outcome events.

AI analysis: treatment = drug users, comparator = disease patients without drug
Gold analysis: treatment = WebAPI Gold cohort members, comparator = disease patients NOT in Gold cohort

Both use the same injected outcome events and the same Cox PH (unadjusted) method.

Usage (inside artemis-api container):
    python3 /app/scripts/run_gold_vs_ai_injection_analysis.py
"""
import json
import os
import sys
from datetime import datetime

import pandas as pd
from lifelines import CoxPHFitter
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:mypass@broadsea-atlasdb:5432/postgres",
)

STUDIES = [
    {
        "name": "LEADER",
        "schema": "synthea_cdm_leader",
        "results_schema": "synthea_cdm_leader_results",
        "treatment_drug": 40170911,
        "disease_concept": 201826,  # T2DM
        "outcome_concept": 312327,  # Acute MI
        "gold_cohort_id": 1136,
        "ai_treatment_id": 840,
        "real_hr": 0.87,
        "real_hr_desc": "liraglutide vs placebo",
    },
    {
        "name": "PLATO",
        "schema": "synthea_cdm_plato",
        "results_schema": "synthea_cdm_plato_results",
        "treatment_drug": 40241186,
        "disease_concept": [312327, 4329847],  # ACS (Acute MI or MI)
        "outcome_concept": 4329847,  # Myocardial infarction (injected concept)
        "gold_cohort_id": 1137,
        "ai_treatment_id": 941,
        "real_hr": 0.84,
        "real_hr_desc": "ticagrelor vs clopidogrel",
    },
    {
        "name": "ARISTOTLE",
        "schema": "synthea_cdm_aristotle",
        "results_schema": "synthea_cdm_aristotle_results",
        "treatment_drug": 43013024,
        "disease_concept": 313217,  # AF
        "outcome_concept": 381316,  # Cerebrovascular accident (injected concept)
        "gold_cohort_id": 1138,
        "ai_treatment_id": 1127,
        "real_hr": 0.79,
        "real_hr_desc": "apixaban vs warfarin",
    },
]


def _build_disease_clause(disease) -> str:
    if isinstance(disease, list):
        return f"co.condition_concept_id IN ({','.join(str(d) for d in disease)})"
    return f"co.condition_concept_id = {disease}"


def _get_outcome_events(conn, schema: str, outcome_id: int) -> pd.DataFrame:
    """Get injected outcome events (condition_occurrence_id >= 200M)."""
    sql = text(f"""
        SELECT person_id,
               condition_start_date AS event_date,
               condition_source_value
        FROM {schema}.condition_occurrence
        WHERE condition_occurrence_id >= 100000000
          AND condition_concept_id = :outcome_id
    """)
    return pd.read_sql(sql, conn, params={"outcome_id": outcome_id})


def _run_cox_ph(cohort_df: pd.DataFrame, events_df: pd.DataFrame, label: str) -> dict:
    """Merge cohort with outcomes and run unadjusted Cox PH."""
    cohort_df = cohort_df.copy()
    cohort_df["index_date"] = pd.to_datetime(cohort_df["index_date"])
    events_df = events_df.copy()
    events_df["event_date"] = pd.to_datetime(events_df["event_date"])

    merged = cohort_df.merge(events_df[["person_id", "event_date"]], on="person_id", how="left")
    merged["time_to_event"] = (merged["event_date"] - merged["index_date"]).dt.days
    merged["event"] = merged["time_to_event"].notna() & (merged["time_to_event"] > 0)

    merged.loc[~merged["event"], "time_to_event"] = 365
    merged.loc[merged["time_to_event"] > 365, "event"] = False
    merged.loc[merged["time_to_event"] > 365, "time_to_event"] = 365
    merged.loc[merged["time_to_event"] <= 0, "event"] = False
    merged.loc[merged["time_to_event"] <= 0, "time_to_event"] = 1

    merged["event"] = merged["event"].astype(int)
    merged["time_to_event"] = merged["time_to_event"].astype(float)

    tx_events = merged[(merged["treatment"] == 1) & (merged["event"] == 1)].shape[0]
    cmp_events = merged[(merged["treatment"] == 0) & (merged["event"] == 1)].shape[0]
    tx_total = merged[merged["treatment"] == 1].shape[0]
    cmp_total = merged[merged["treatment"] == 0].shape[0]

    tx_rate = tx_events / tx_total * 100 if tx_total > 0 else 0
    cmp_rate = cmp_events / cmp_total * 100 if cmp_total > 0 else 0
    print(f"    [{label}] TX events: {tx_events}/{tx_total} ({tx_rate:.1f}%)")
    print(f"    [{label}] CMP events: {cmp_events}/{cmp_total} ({cmp_rate:.1f}%)")

    cph_df = merged[["time_to_event", "event", "treatment"]].copy()
    cph = CoxPHFitter()
    try:
        cph.fit(cph_df, duration_col="time_to_event", event_col="event")
        summary = cph.summary
        hr = float(summary.loc["treatment", "exp(coef)"])
        ci_lower = float(summary.loc["treatment", "exp(coef) lower 95%"])
        ci_upper = float(summary.loc["treatment", "exp(coef) upper 95%"])
        p_value = float(summary.loc["treatment", "p"])
    except Exception as e:
        print(f"    [{label}] Cox PH failed: {e}")
        hr = ci_lower = ci_upper = p_value = None

    return {
        "treatment_n": tx_total,
        "comparator_n": cmp_total,
        "treatment_events": tx_events,
        "comparator_events": cmp_events,
        "treatment_event_rate": f"{tx_rate:.1f}%",
        "comparator_event_rate": f"{cmp_rate:.1f}%",
        "hr": hr,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "p_value": p_value,
    }


def analyze_ai(engine, study: dict) -> dict:
    """AI analysis: treatment = drug users, comparator = disease patients without drug."""
    schema = study["schema"]
    drug_id = study["treatment_drug"]
    disease_clause = _build_disease_clause(study["disease_concept"])

    treatment_sql = text(f"""
        SELECT DISTINCT ON (de.person_id)
            de.person_id,
            de.drug_era_start_date AS index_date,
            1 AS treatment
        FROM {schema}.drug_era de
        WHERE de.drug_concept_id = :drug_id
        ORDER BY de.person_id, de.drug_era_start_date
    """)

    comparator_sql = text(f"""
        SELECT DISTINCT ON (co.person_id)
            co.person_id,
            co.condition_start_date AS index_date,
            0 AS treatment
        FROM {schema}.condition_occurrence co
        WHERE {disease_clause}
          AND co.condition_occurrence_id < 100000000
          AND co.person_id NOT IN (
              SELECT person_id FROM {schema}.drug_era WHERE drug_concept_id = :drug_id
          )
        ORDER BY co.person_id, co.condition_start_date
    """)

    with engine.connect() as conn:
        tx_df = pd.read_sql(treatment_sql, conn, params={"drug_id": drug_id})
        cmp_df = pd.read_sql(comparator_sql, conn, params={"drug_id": drug_id})
        cohort_df = pd.concat([tx_df, cmp_df], ignore_index=True)
        events_df = _get_outcome_events(conn, schema, study["outcome_concept"])

    print(f"  AI: Treatment N={len(tx_df)}, Comparator N={len(cmp_df)}")
    return _run_cox_ph(cohort_df, events_df, f"{study['name']} AI")


def analyze_gold(engine, study: dict) -> dict:
    """Gold analysis: treatment = Gold cohort, comparator = disease patients WITHOUT the drug.

    The comparator uses 'disease patients without the drug' (not 'disease patients
    not in Gold cohort') to match the cohort-blind injection design where:
      - TX-rate events were injected into ALL drug users
      - CMP-rate events were injected into disease patients without the drug

    Using 'not in Gold cohort' as comparator would mix non-Gold drug users (who
    received TX-rate injection) into the comparator pool, inverting the HR.
    """
    schema = study["schema"]
    results_schema = study["results_schema"]
    gold_id = study["gold_cohort_id"]
    drug_id = study["treatment_drug"]
    disease_clause = _build_disease_clause(study["disease_concept"])

    # Treatment: Gold cohort members, index_date = cohort_start_date
    treatment_sql = text(f"""
        SELECT DISTINCT ON (c.subject_id)
            c.subject_id AS person_id,
            c.cohort_start_date AS index_date,
            1 AS treatment
        FROM {results_schema}.cohort c
        WHERE c.cohort_definition_id = :gold_id
        ORDER BY c.subject_id, c.cohort_start_date
    """)

    # Comparator: disease patients WITHOUT the drug (matches injection design)
    comparator_sql = text(f"""
        SELECT DISTINCT ON (co.person_id)
            co.person_id,
            co.condition_start_date AS index_date,
            0 AS treatment
        FROM {schema}.condition_occurrence co
        WHERE {disease_clause}
          AND co.condition_occurrence_id < 100000000
          AND co.person_id NOT IN (
              SELECT person_id FROM {schema}.drug_era WHERE drug_concept_id = :drug_id
          )
        ORDER BY co.person_id, co.condition_start_date
    """)

    with engine.connect() as conn:
        tx_df = pd.read_sql(treatment_sql, conn, params={"gold_id": gold_id, "drug_id": drug_id})
        cmp_df = pd.read_sql(comparator_sql, conn, params={"gold_id": gold_id, "drug_id": drug_id})
        cohort_df = pd.concat([tx_df, cmp_df], ignore_index=True)
        events_df = _get_outcome_events(conn, schema, study["outcome_concept"])

    print(f"  Gold: Treatment N={len(tx_df)}, Comparator N={len(cmp_df)}")
    return _run_cox_ph(cohort_df, events_df, f"{study['name']} Gold")


def analyze_overlap(engine, study: dict) -> dict:
    """Compute overlap between Gold and AI cohorts."""
    results_schema = study["results_schema"]
    gold_id = study["gold_cohort_id"]
    schema = study["schema"]
    drug_id = study["treatment_drug"]

    with engine.connect() as conn:
        # Gold members
        gold_rows = conn.execute(
            text(f"SELECT DISTINCT subject_id FROM {results_schema}.cohort WHERE cohort_definition_id = :cid"),
            {"cid": gold_id},
        ).fetchall()
        gold_ids = {int(r[0]) for r in gold_rows}

        # AI members (drug users)
        ai_rows = conn.execute(
            text(f"SELECT DISTINCT person_id FROM {schema}.drug_era WHERE drug_concept_id = :drug_id"),
            {"drug_id": drug_id},
        ).fetchall()
        ai_ids = {int(r[0]) for r in ai_rows}

    overlap = gold_ids & ai_ids
    recall = len(overlap) / len(gold_ids) if gold_ids else 0
    precision = len(overlap) / len(ai_ids) if ai_ids else 0

    return {
        "gold_n": len(gold_ids),
        "ai_n": len(ai_ids),
        "overlap_n": len(overlap),
        "recall": recall,
        "precision": precision,
    }


def main():
    engine = create_engine(DATABASE_URL)
    all_results = []

    print("=" * 80)
    print("Gold vs AI Cox PH Comparison (Injected Outcome Events)")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 80)

    for study in STUDIES:
        print(f"\n{'─'*60}")
        print(f"  {study['name']} ({study['schema']})")
        print(f"{'─'*60}")

        overlap = analyze_overlap(engine, study)
        print(f"  Overlap: Gold={overlap['gold_n']}, AI={overlap['ai_n']}, "
              f"Overlap={overlap['overlap_n']}, "
              f"Recall={overlap['recall']:.1%}, Precision={overlap['precision']:.1%}")

        print()
        ai_result = analyze_ai(engine, study)

        print()
        gold_result = analyze_gold(engine, study)

        all_results.append({
            "study": study["name"],
            "real_hr": study["real_hr"],
            "real_hr_desc": study["real_hr_desc"],
            "overlap": overlap,
            "ai": ai_result,
            "gold": gold_result,
        })

    # Print summary table
    print(f"\n\n{'='*120}")
    print("COMPARISON SUMMARY")
    print(f"{'='*120}")
    header = (
        f"{'Study':<12} | {'Gold HR [95% CI]':<28} | {'AI HR [95% CI]':<28} | "
        f"{'Published HR':<12} | {'Gold-AI Delta':>14} | {'Recall':>8} | {'Precision':>10}"
    )
    print(header)
    print("─" * 120)

    for r in all_results:
        ai = r["ai"]
        gold = r["gold"]
        overlap = r["overlap"]

        if gold["hr"] is not None:
            gold_str = f"{gold['hr']:.3f} [{gold['ci_lower']:.3f}, {gold['ci_upper']:.3f}]"
        else:
            gold_str = "N/A"

        if ai["hr"] is not None:
            ai_str = f"{ai['hr']:.3f} [{ai['ci_lower']:.3f}, {ai['ci_upper']:.3f}]"
        else:
            ai_str = "N/A"

        if gold["hr"] is not None and ai["hr"] is not None:
            delta = gold["hr"] - ai["hr"]
            delta_str = f"{delta:+.3f}"
        else:
            delta_str = "N/A"

        recall_str = f"{overlap['recall']:.1%}" if overlap["recall"] else "N/A"
        precision_str = f"{overlap['precision']:.1%}" if overlap["precision"] else "N/A"

        print(
            f"{r['study']:<12} | {gold_str:<28} | {ai_str:<28} | "
            f"{r['real_hr']:<12} | {delta_str:>14} | {recall_str:>8} | {precision_str:>10}"
        )

    print()
    print("Notes:")
    print("- AI treatment: CDM drug_era users; AI comparator: disease patients without the drug")
    print("- Gold treatment: WebAPI Gold cohort members; Gold comparator: disease patients WITHOUT the drug")
    print("- Both use the SAME injected outcome events and unadjusted Cox PH")
    print("- Gold-AI Delta = Gold HR - AI HR (positive means Gold HR is higher)")
    print("- Published HR: from actual RCT (different population, NOT directly comparable to injection-based HR)")

    # Save results
    output_path = "/app/tmp/gold_vs_ai_injection_comparison.json"
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to: {output_path}")

    return all_results


if __name__ == "__main__":
    main()
