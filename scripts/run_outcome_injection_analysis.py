#!/usr/bin/env python3
"""
Direct Cox regression analysis for outcome-injected CDM data.
Runs against each study CDM, identifying treatment/comparator arms and
computing HR with 95% CI for the injected outcome events.

Usage (inside artemis-api container):
    python3 /app/scripts/run_outcome_injection_analysis.py
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
        "source_id": 6,
        "treatment_drug": 40170911,
        "disease_concept": 201826,  # T2DM
        "outcome_concept": 312327,  # Acute MI
        "outcome_source_tx": "INJECTED_OUTCOME_LEADER_TX",
        "outcome_source_cmp": "INJECTED_OUTCOME_LEADER_CMP",
        "real_hr": 0.87,
        "real_hr_desc": "liraglutide vs placebo",
        "injected_rate_tx": 0.15,
        "injected_rate_cmp": 0.20,
    },
    {
        "name": "PLATO",
        "schema": "synthea_cdm_plato",
        "source_id": 7,
        "treatment_drug": 40241186,
        "disease_concept": [312327, 4329847],  # ACS (Acute MI or MI)
        "outcome_concept": 312327,  # Acute MI
        "outcome_source_tx": "INJECTED_OUTCOME_PLATO_TX",
        "outcome_source_cmp": "INJECTED_OUTCOME_PLATO_CMP",
        "real_hr": 0.84,
        "real_hr_desc": "ticagrelor vs clopidogrel",
        "injected_rate_tx": 0.10,
        "injected_rate_cmp": 0.14,
    },
    {
        "name": "ARISTOTLE",
        "schema": "synthea_cdm_aristotle",
        "source_id": 8,
        "treatment_drug": 43013024,
        "disease_concept": 313217,  # AF
        "outcome_concept": 443454,  # Cerebral infarction
        "outcome_source_tx": "INJECTED_OUTCOME_ARISTOTLE_TX",
        "outcome_source_cmp": "INJECTED_OUTCOME_ARISTOTLE_CMP",
        "real_hr": 0.79,
        "real_hr_desc": "apixaban vs warfarin",
        "injected_rate_tx": 0.08,
        "injected_rate_cmp": 0.12,
    },
]


def analyze_study(engine, study: dict) -> dict:
    """Build survival dataset and run Cox PH for one study."""
    schema = study["schema"]
    drug_id = study["treatment_drug"]
    disease = study["disease_concept"]
    outcome = study["outcome_concept"]

    if isinstance(disease, list):
        disease_clause = f"co.condition_concept_id IN ({','.join(str(d) for d in disease)})"
    else:
        disease_clause = f"co.condition_concept_id = {disease}"

    # --- Treatment arm ---
    # Index date = earliest drug_era_start_date for treatment drug
    treatment_sql = text(f"""
        SELECT DISTINCT ON (de.person_id)
            de.person_id,
            de.drug_era_start_date AS index_date,
            1 AS treatment
        FROM {schema}.drug_era de
        WHERE de.drug_concept_id = :drug_id
        ORDER BY de.person_id, de.drug_era_start_date
    """)

    # --- Comparator arm ---
    # Disease patients without treatment drug
    # Index date = earliest disease condition date (excluding injected records)
    comparator_sql = text(f"""
        SELECT DISTINCT ON (co.person_id)
            co.person_id,
            co.condition_start_date AS index_date,
            0 AS treatment
        FROM {schema}.condition_occurrence co
        WHERE {disease_clause}
          AND co.condition_occurrence_id < 200000000
          AND co.person_id NOT IN (
              SELECT person_id FROM {schema}.drug_era WHERE drug_concept_id = :drug_id
          )
        ORDER BY co.person_id, co.condition_start_date
    """)

    with engine.connect() as conn:
        tx_df = pd.read_sql(treatment_sql, conn, params={"drug_id": drug_id})
        cmp_df = pd.read_sql(comparator_sql, conn, params={"drug_id": drug_id})
        cohort_df = pd.concat([tx_df, cmp_df], ignore_index=True)
        print(f"  [{study['name']}] Treatment N={len(tx_df)}, Comparator N={len(cmp_df)}")

        # --- Outcome events (injected, post-index) ---
        outcome_sql = text(f"""
            SELECT person_id,
                   condition_start_date AS event_date,
                   condition_source_value
            FROM {schema}.condition_occurrence
            WHERE condition_occurrence_id >= 200000000
              AND condition_concept_id = :outcome_id
        """)
        events_df = pd.read_sql(outcome_sql, conn, params={"outcome_id": outcome})

    # Merge outcome with cohort
    cohort_df["index_date"] = pd.to_datetime(cohort_df["index_date"])
    events_df["event_date"] = pd.to_datetime(events_df["event_date"])

    merged = cohort_df.merge(events_df[["person_id", "event_date"]], on="person_id", how="left")

    # Time to event or censor
    # For patients with event: time = event_date - index_date
    # For patients without event: censor at 365 days
    merged["time_to_event"] = (merged["event_date"] - merged["index_date"]).dt.days
    merged["event"] = merged["time_to_event"].notna() & (merged["time_to_event"] > 0)

    # Censor at 365 days
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

    print(f"  [{study['name']}] TX events: {tx_events}/{tx_total} ({tx_events/tx_total*100:.1f}%)")
    print(f"  [{study['name']}] CMP events: {cmp_events}/{cmp_total} ({cmp_events/cmp_total*100:.1f}%)")

    # Cox PH
    cph_df = merged[["time_to_event", "event", "treatment"]].copy()
    cph = CoxPHFitter()
    try:
        cph.fit(cph_df, duration_col="time_to_event", event_col="event")
        summary = cph.summary
        hr = float(summary.loc["treatment", "exp(coef)"])
        ci_lower = float(summary.loc["treatment", "exp(coef) lower 95%"])
        ci_upper = float(summary.loc["treatment", "exp(coef) upper 95%"])
        p_value = float(summary.loc["treatment", "p"])
        analysis_method = "Cox PH (unadjusted)"
    except Exception as e:
        print(f"  [{study['name']}] Cox PH failed: {e}")
        hr = ci_lower = ci_upper = p_value = None
        analysis_method = f"FAILED: {e}"

    result = {
        "study": study["name"],
        "real_hr": study["real_hr"],
        "real_hr_desc": study["real_hr_desc"],
        "treatment_n": tx_total,
        "comparator_n": cmp_total,
        "treatment_events": tx_events,
        "comparator_events": cmp_events,
        "treatment_event_rate": f"{tx_events/tx_total*100:.1f}%",
        "comparator_event_rate": f"{cmp_events/cmp_total*100:.1f}%",
        "hr": hr,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "p_value": p_value,
        "analysis_method": analysis_method,
    }

    if hr is not None:
        print(f"  [{study['name']}] HR={hr:.3f} (95% CI: {ci_lower:.3f}-{ci_upper:.3f}), p={p_value:.4f}")
        print(f"  [{study['name']}] Real trial HR={study['real_hr']}")
    return result


def main():
    engine = create_engine(DATABASE_URL)
    results = []

    print("=" * 70)
    print("Outcome Injection Analysis - Cox PH Regression")
    print("=" * 70)

    for study in STUDIES:
        print(f"\n--- {study['name']} ({study['schema']}) ---")
        result = analyze_study(engine, study)
        results.append(result)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for r in results:
        hr_str = f"{r['hr']:.3f}" if r["hr"] is not None else "N/A"
        ci_str = f"({r['ci_lower']:.3f}-{r['ci_upper']:.3f})" if r["ci_lower"] is not None else ""
        p_str = f"p={r['p_value']:.4f}" if r["p_value"] is not None else ""
        print(
            f"  {r['study']:12s} | HR={hr_str} {ci_str} {p_str} | "
            f"Real HR={r['real_hr']} | "
            f"TX: {r['treatment_events']}/{r['treatment_n']} | "
            f"CMP: {r['comparator_events']}/{r['comparator_n']}"
        )

    # Save results as JSON
    output_path = "/app/tmp/outcome_injection_analysis_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {output_path}")

    return results


if __name__ == "__main__":
    main()
