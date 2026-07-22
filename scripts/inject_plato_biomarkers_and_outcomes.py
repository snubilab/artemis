#!/usr/bin/env python3
"""
PLATO: Two-phase injection to increase Gold cohort size and inject cohort-blind outcomes.

Phase 1 -- Biomarker injection:
  Inject TnT (Troponin T cardiac, concept 3019800) measurements for ACS-path
  ticagrelor users who currently lack biomarker data. This satisfies Gold cohort
  1137's inclusion rule 0 (ACS + elevated biomarkers), increasing Gold from 436.

  The measurement is injected with range_high populated so that
  value_as_number / range_high > 1 (the CIRCE RangeHighRatio > 1 criterion).

Phase 2 -- Cohort-blind outcome injection:
  TX = ALL ticagrelor drug_era users
  CMP = ACS patients WITHOUT ticagrelor
  TX rate: 10%, CMP rate: 14%
  Outcome: Acute MI (concept 312327)

Usage:
    python3 artemis/scripts/inject_plato_biomarkers_and_outcomes.py
    python3 artemis/scripts/inject_plato_biomarkers_and_outcomes.py --dry-run
    python3 artemis/scripts/inject_plato_biomarkers_and_outcomes.py --phase biomarkers
    python3 artemis/scripts/inject_plato_biomarkers_and_outcomes.py --phase outcomes
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
from sqlalchemy import create_engine, text

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:mypass@127.0.0.1:5432/postgres")
os.environ.setdefault("WEBAPI_URL", "http://127.0.0.1/WebAPI")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CDM_SCHEMA = "synthea_cdm_plato"
RESULTS_SCHEMA = "synthea_cdm_plato_results"
SOURCE_KEY = "PLATO_BENCHMARK"
GOLD_TREATMENT_ID = 1137

TICAGRELOR_CONCEPT_ID = 40241186
ACS_NSTEMI_CONCEPTS = (4270024, 315296)  # NSTE-ACS concepts in Gold definition
ACS_ALL_CONCEPTS = (4270024, 312327, 4329847)  # All ACS concepts for comparator pool

TNT_CONCEPT_ID = 3019800  # Troponin T.cardiac [Mass/volume] in Serum or Plasma
MEASUREMENT_TYPE_CONCEPT_ID = 32817  # EHR record
INJECTED_MEAS_SOURCE_VALUE = "INJECTED_TNT_BIOMARKER"
INJECTED_MEAS_ID_BASE = 200_000_000

OUTCOME_CONCEPT_ID = 312327  # Acute myocardial infarction
CONDITION_TYPE_CONCEPT_ID = 32817
INJECTED_COND_SOURCE_VALUE = "INJECTED_CV_EVENT"
INJECTED_COND_ID_BASE = 200_000_000

EVENT_WINDOW_START_DAYS = 30
EVENT_WINDOW_END_DAYS = 365

DEFAULT_TX_RATE = 0.10
DEFAULT_CMP_RATE = 0.14
DEFAULT_SEED = 42

WEBAPI_URL = os.environ.get("WEBAPI_URL", "http://127.0.0.1/WebAPI")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PLATO biomarker + cohort-blind outcome injection")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--tx-rate", type=float, default=DEFAULT_TX_RATE)
    parser.add_argument("--cmp-rate", type=float, default=DEFAULT_CMP_RATE)
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--phase", choices=["all", "biomarkers", "outcomes"], default="all")
    parser.add_argument("--skip-regenerate", action="store_true")
    return parser.parse_args(argv)


def _clear_cache(engine) -> int:
    with engine.connect() as conn:
        deleted = conn.execute(
            text(
                """
                WITH source_row AS (
                    SELECT source_id FROM webapi.source WHERE source_key = :source_key
                )
                DELETE FROM webapi.generation_cache gc
                USING source_row s
                WHERE gc.type = 'COHORT' AND gc.source_id = s.source_id
                """
            ),
            {"source_key": SOURCE_KEY},
        ).rowcount
        conn.commit()
    return int(deleted or 0)


def _regenerate_cohort(cohort_id: int, engine) -> int:
    """Trigger WebAPI cohort regeneration and wait for completion."""
    logger.info("Triggering cohort %d regeneration on %s...", cohort_id, SOURCE_KEY)
    triggered_at = datetime.utcnow()

    gen_url = f"{WEBAPI_URL}/cohortdefinition/{cohort_id}/generate/{SOURCE_KEY}"
    resp = requests.get(gen_url, timeout=30)
    resp.raise_for_status()

    deadline = time.time() + 600
    while time.time() < deadline:
        time.sleep(10)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT cgi.start_time, cgi.status, cgi.person_count, cgi.fail_message
                    FROM webapi.cohort_generation_info cgi
                    JOIN webapi.source s ON s.source_id = cgi.source_id
                    WHERE cgi.id = :cohort_id AND s.source_key = :source_key
                    ORDER BY cgi.start_time DESC LIMIT 1
                    """
                ),
                {"cohort_id": cohort_id, "source_key": SOURCE_KEY},
            ).mappings().first()
        if row and row["start_time"] and row["start_time"] >= triggered_at:
            status = int(row["status"] or 0)
            if status == 2:
                count = int(row["person_count"] or 0)
                logger.info("Cohort %d COMPLETE: %d persons", cohort_id, count)
                return count
            if status in (3, 4):
                logger.error("Cohort %d FAILED: %s", cohort_id, row["fail_message"])
                return -1

    logger.error("Timeout waiting for cohort %d", cohort_id)
    return -1


def phase_biomarkers(engine, rng: np.random.Generator, dry_run: bool = False) -> int:
    """
    Inject TnT measurements for ACS-path ticagrelor users.

    Returns the number of measurements injected.
    """
    logger.info("=== Phase 1: Biomarker Injection ===")

    with engine.connect() as conn:
        # Find ACS-path ticagrelor users who lack TnT measurements
        acs_tic_df = pd.read_sql(
            text(
                f"""
                WITH tic_valid AS (
                    SELECT person_id, MIN(drug_era_start_date) AS index_date
                    FROM {CDM_SCHEMA}.drug_era
                    WHERE drug_concept_id = :tic_id
                      AND drug_era_start_date >= '2011-07-22'
                      AND (drug_era_end_date - drug_era_start_date) >= 7
                    GROUP BY person_id
                ),
                acs_tic AS (
                    SELECT DISTINCT t.person_id, t.index_date
                    FROM tic_valid t
                    JOIN {CDM_SCHEMA}.condition_occurrence co
                      ON co.person_id = t.person_id
                    WHERE co.condition_concept_id IN (
                        SELECT descendant_concept_id
                        FROM {CDM_SCHEMA}.concept_ancestor
                        WHERE ancestor_concept_id IN :acs_concepts
                    )
                    AND co.condition_start_date BETWEEN t.index_date - 7 AND t.index_date
                ),
                already_has_tnt AS (
                    SELECT DISTINCT a.person_id
                    FROM acs_tic a
                    JOIN {CDM_SCHEMA}.measurement m ON m.person_id = a.person_id
                    WHERE m.measurement_concept_id = :tnt_id
                      AND m.measurement_date BETWEEN a.index_date - 7 AND a.index_date
                )
                SELECT a.person_id, a.index_date
                FROM acs_tic a
                WHERE a.person_id NOT IN (SELECT person_id FROM already_has_tnt)
                """
            ),
            conn,
            params={
                "tic_id": TICAGRELOR_CONCEPT_ID,
                "acs_concepts": tuple(ACS_NSTEMI_CONCEPTS),
                "tnt_id": TNT_CONCEPT_ID,
            },
        )
        acs_tic_df["index_date"] = pd.to_datetime(acs_tic_df["index_date"]).dt.date

        # Get next measurement_id
        max_meas_id = conn.execute(
            text(f"SELECT COALESCE(MAX(measurement_id), 0) FROM {CDM_SCHEMA}.measurement")
        ).scalar()

    next_id = max(int(max_meas_id or 0) + 1, INJECTED_MEAS_ID_BASE)
    logger.info("ACS-path ticagrelor users needing TnT: %d", len(acs_tic_df))

    # Build measurement rows
    # TnT normal range_high is ~0.04 ng/mL. We inject values 2-10x above range_high
    # to satisfy RangeHighRatio > 1 criterion.
    rows: list[dict] = []
    for row in acs_tic_df.itertuples():
        # Measurement within 7 days before index
        meas_date = row.index_date - timedelta(days=int(rng.integers(0, 7)))
        range_high = 0.04  # ng/mL, standard upper limit
        value = range_high * float(rng.uniform(1.5, 10.0))  # Elevated, ratio > 1

        rows.append(
            {
                "measurement_id": next_id,
                "person_id": int(row.person_id),
                "measurement_concept_id": TNT_CONCEPT_ID,
                "measurement_date": meas_date,
                "measurement_datetime": None,
                "measurement_time": None,
                "measurement_type_concept_id": MEASUREMENT_TYPE_CONCEPT_ID,
                "operator_concept_id": 0,
                "value_as_number": round(value, 4),
                "value_as_concept_id": 0,
                "unit_concept_id": 8842,  # nanogram per milliliter
                "range_low": 0.0,
                "range_high": range_high,
                "provider_id": None,
                "visit_occurrence_id": None,
                "visit_detail_id": None,
                "measurement_source_value": INJECTED_MEAS_SOURCE_VALUE,
                "measurement_source_concept_id": 0,
                "unit_source_value": "ng/mL",
                "unit_source_concept_id": 0,
                "value_source_value": str(round(value, 4)),
                "measurement_event_id": None,
                "meas_event_field_concept_id": 0,
            }
        )
        next_id += 1

    logger.info("TnT measurements to inject: %d", len(rows))

    if not dry_run and rows:
        df_rows = pd.DataFrame(rows)
        with engine.connect() as conn:
            df_rows.to_sql(
                "measurement",
                conn,
                schema=CDM_SCHEMA,
                if_exists="append",
                index=False,
                method="multi",
                chunksize=500,
            )
            conn.commit()
        logger.info("Inserted %d TnT measurements", len(rows))
    elif dry_run:
        logger.info("[dry-run] Would insert %d TnT measurements", len(rows))

    return len(rows)


def phase_outcomes(
    engine,
    rng: np.random.Generator,
    tx_rate: float,
    cmp_rate: float,
    dry_run: bool = False,
) -> dict:
    """
    Inject cohort-blind outcome events.

    TX = ALL ticagrelor users, CMP = ACS patients WITHOUT ticagrelor
    """
    logger.info("=== Phase 2: Cohort-blind Outcome Injection ===")

    with engine.connect() as conn:
        # Delete existing outcome injections
        if not dry_run:
            deleted = conn.execute(
                text(
                    f"DELETE FROM {CDM_SCHEMA}.condition_occurrence "
                    f"WHERE condition_occurrence_id >= {INJECTED_COND_ID_BASE}"
                )
            ).rowcount
            conn.commit()
            logger.info("Deleted %d existing injected condition rows", deleted)

        # TX pool: ALL ticagrelor users
        tx_df = pd.read_sql(
            text(
                f"""
                SELECT person_id, MIN(drug_era_start_date) AS index_date
                FROM {CDM_SCHEMA}.drug_era
                WHERE drug_concept_id = :tic_id
                GROUP BY person_id
                """
            ),
            conn,
            params={"tic_id": TICAGRELOR_CONCEPT_ID},
        )
        tx_df["index_date"] = pd.to_datetime(tx_df["index_date"]).dt.date
        tx_set = set(tx_df["person_id"])
        logger.info("Treatment pool (ticagrelor users): %d", len(tx_set))

        # CMP pool: ACS patients WITHOUT ticagrelor
        cmp_df = pd.read_sql(
            text(
                f"""
                SELECT co.person_id, MIN(co.condition_start_date) AS index_date
                FROM {CDM_SCHEMA}.condition_occurrence co
                WHERE co.condition_concept_id IN :acs_concepts
                AND co.person_id NOT IN (
                    SELECT DISTINCT person_id
                    FROM {CDM_SCHEMA}.drug_era
                    WHERE drug_concept_id = :tic_id
                )
                GROUP BY co.person_id
                """
            ),
            conn,
            params={"acs_concepts": tuple(ACS_ALL_CONCEPTS), "tic_id": TICAGRELOR_CONCEPT_ID},
        )
        cmp_df["index_date"] = pd.to_datetime(cmp_df["index_date"]).dt.date
        logger.info("Comparator pool (ACS without ticagrelor): %d", len(cmp_df))

    # Assign events
    tx_df["group"] = "treatment"
    cmp_df["group"] = "comparator"
    all_df = pd.concat([tx_df, cmp_df], ignore_index=True)

    tx_mask = all_df["group"] == "treatment"
    cmp_mask = all_df["group"] == "comparator"

    tx_events = rng.random(int(tx_mask.sum())) < tx_rate
    cmp_events = rng.random(int(cmp_mask.sum())) < cmp_rate

    all_df.loc[tx_mask, "has_event"] = tx_events
    all_df.loc[cmp_mask, "has_event"] = cmp_events

    event_df = all_df[all_df["has_event"] == True].copy()  # noqa: E712

    logger.info(
        "Events: TX=%d/%d (%.1f%%), CMP=%d/%d (%.1f%%)",
        int(tx_events.sum()), int(tx_mask.sum()), 100 * tx_events.mean(),
        int(cmp_events.sum()), int(cmp_mask.sum()), 100 * cmp_events.mean(),
    )

    # Build rows
    rows: list[dict] = []
    next_id = INJECTED_COND_ID_BASE
    for row in event_df.itertuples():
        event_date = row.index_date + timedelta(
            days=int(rng.integers(EVENT_WINDOW_START_DAYS, EVENT_WINDOW_END_DAYS + 1))
        )
        rows.append(
            {
                "condition_occurrence_id": next_id,
                "person_id": int(row.person_id),
                "condition_concept_id": OUTCOME_CONCEPT_ID,
                "condition_start_date": event_date,
                "condition_end_date": event_date,
                "condition_type_concept_id": CONDITION_TYPE_CONCEPT_ID,
                "condition_source_value": INJECTED_COND_SOURCE_VALUE,
            }
        )
        next_id += 1

    if not dry_run and rows:
        df_rows = pd.DataFrame(rows)
        with engine.connect() as conn:
            for r in rows:
                conn.execute(
                    text(
                        f"""
                        UPDATE {CDM_SCHEMA}.observation_period
                        SET observation_period_end_date = GREATEST(observation_period_end_date, :end_date)
                        WHERE person_id = :person_id
                        """
                    ),
                    {"person_id": r["person_id"], "end_date": r["condition_start_date"]},
                )

            df_rows.to_sql(
                "condition_occurrence",
                conn,
                schema=CDM_SCHEMA,
                if_exists="append",
                index=False,
                method="multi",
                chunksize=500,
            )
            conn.commit()
        logger.info("Inserted %d outcome rows", len(rows))

        # Clear cache
        cache_deleted = _clear_cache(engine)
        logger.info("Cleared %d WebAPI cache rows", cache_deleted)

    return {
        "tx_pool": len(tx_df),
        "cmp_pool": len(cmp_df),
        "tx_events": int(tx_events.sum()),
        "cmp_events": int(cmp_events.sum()),
        "total_inserted": len(rows),
    }


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    db_url = args.db_url or os.environ["DATABASE_URL"]
    engine = create_engine(db_url)
    rng = np.random.default_rng(args.seed)

    global WEBAPI_URL
    if os.environ.get("WEBAPI_URL"):
        WEBAPI_URL = os.environ["WEBAPI_URL"]

    biomarker_count = 0
    outcome_summary = {}

    if args.phase in ("all", "biomarkers"):
        biomarker_count = phase_biomarkers(engine, rng, dry_run=args.dry_run)

        if not args.dry_run and not args.skip_regenerate and biomarker_count > 0:
            # Clear cache and regenerate Gold cohort to pick up new biomarkers
            cache_deleted = _clear_cache(engine)
            logger.info("Cleared %d cache rows before Gold regeneration", cache_deleted)
            gold_count = _regenerate_cohort(GOLD_TREATMENT_ID, engine)
            logger.info("Gold cohort 1137 new count: %d (was 436)", gold_count)
        elif args.dry_run:
            logger.info("[dry-run] Would regenerate Gold cohort 1137 after biomarker injection")

    if args.phase in ("all", "outcomes"):
        outcome_summary = phase_outcomes(
            engine, rng,
            tx_rate=args.tx_rate,
            cmp_rate=args.cmp_rate,
            dry_run=args.dry_run,
        )

    # Summary
    print("\n" + "=" * 60)
    print("PLATO INJECTION SUMMARY")
    print("=" * 60)
    if biomarker_count:
        print(f"Phase 1 - TnT measurements injected: {biomarker_count}")
    if outcome_summary:
        print(f"Phase 2 - TX pool (ticagrelor):      {outcome_summary.get('tx_pool', 0):>6,}")
        print(f"Phase 2 - CMP pool (ACS no tic):     {outcome_summary.get('cmp_pool', 0):>6,}")
        print(f"Phase 2 - TX events:                 {outcome_summary.get('tx_events', 0):>6,}")
        print(f"Phase 2 - CMP events:                {outcome_summary.get('cmp_events', 0):>6,}")
        print(f"Phase 2 - Total outcome rows:        {outcome_summary.get('total_inserted', 0):>6,}")
    if args.dry_run:
        print("DRY RUN -- no data written")
    print("=" * 60)


if __name__ == "__main__":
    main()
