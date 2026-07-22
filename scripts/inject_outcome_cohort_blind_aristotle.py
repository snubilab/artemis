#!/usr/bin/env python3
"""
ARISTOTLE: Cohort-blind outcome injection.

Treatment pool = ALL apixaban drug_era users (3,258 persons)
Comparator pool = ALL AF patients WITHOUT apixaban drug_era (441 persons)

Outcome: Stroke/cerebral infarction (concept 443454)
TX rate: 8%, CMP rate: 12%
Event window: 30-365 days post-index

Usage:
    python3 artemis/scripts/inject_outcome_cohort_blind_aristotle.py
    python3 artemis/scripts/inject_outcome_cohort_blind_aristotle.py --dry-run
"""
import argparse
import logging
import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:mypass@127.0.0.1:5432/postgres")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CDM_SCHEMA = "synthea_cdm_aristotle"
RESULTS_SCHEMA = "synthea_cdm_aristotle_results"
SOURCE_KEY = "ARISTOTLE_BENCHMARK"

APIXABAN_CONCEPT_ID = 43013024
AF_ANCESTOR_CONCEPT_ID = 313217
OUTCOME_CONCEPT_ID = 443454  # Cerebral infarction (stroke)
CONDITION_TYPE_CONCEPT_ID = 32817
INJECTED_SOURCE_VALUE = "INJECTED_CV_EVENT"
INJECTED_ID_BASE = 200_000_000

EVENT_WINDOW_START_DAYS = 30
EVENT_WINDOW_END_DAYS = 365

DEFAULT_TX_RATE = 0.08
DEFAULT_CMP_RATE = 0.12
DEFAULT_SEED = 42


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ARISTOTLE cohort-blind outcome injection")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--tx-rate", type=float, default=DEFAULT_TX_RATE)
    parser.add_argument("--cmp-rate", type=float, default=DEFAULT_CMP_RATE)
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    db_url = args.db_url or os.environ["DATABASE_URL"]
    engine = create_engine(db_url)
    rng = np.random.default_rng(args.seed)

    with engine.connect() as conn:
        # Step 1: Delete existing injections
        if not args.dry_run:
            deleted = conn.execute(
                text(
                    f"DELETE FROM {CDM_SCHEMA}.condition_occurrence "
                    f"WHERE condition_occurrence_id >= {INJECTED_ID_BASE}"
                )
            ).rowcount
            conn.commit()
            logger.info("Deleted %d existing injected rows", deleted)
        else:
            logger.info("[dry-run] Would delete existing injected rows >= %d", INJECTED_ID_BASE)

    with engine.connect() as conn:
        # Step 2: Get treatment pool (ALL apixaban drug_era users)
        tx_df = pd.read_sql(
            text(
                f"""
                SELECT person_id, MIN(drug_era_start_date) AS index_date
                FROM {CDM_SCHEMA}.drug_era
                WHERE drug_concept_id = :drug_id
                GROUP BY person_id
                """
            ),
            conn,
            params={"drug_id": APIXABAN_CONCEPT_ID},
        )
        tx_df["index_date"] = pd.to_datetime(tx_df["index_date"]).dt.date
        tx_set = set(tx_df["person_id"])
        logger.info("Treatment pool (apixaban users): %d persons", len(tx_set))

        # Step 3: Get comparator pool (AF patients WITHOUT apixaban)
        cmp_df = pd.read_sql(
            text(
                f"""
                SELECT DISTINCT co.person_id,
                       MIN(co.condition_start_date) AS index_date
                FROM {CDM_SCHEMA}.condition_occurrence co
                WHERE co.condition_concept_id IN (
                    SELECT descendant_concept_id
                    FROM {CDM_SCHEMA}.concept_ancestor
                    WHERE ancestor_concept_id = :af_id
                )
                AND co.person_id NOT IN (
                    SELECT DISTINCT person_id
                    FROM {CDM_SCHEMA}.drug_era
                    WHERE drug_concept_id = :drug_id
                )
                GROUP BY co.person_id
                """
            ),
            conn,
            params={"af_id": AF_ANCESTOR_CONCEPT_ID, "drug_id": APIXABAN_CONCEPT_ID},
        )
        cmp_df["index_date"] = pd.to_datetime(cmp_df["index_date"]).dt.date
        logger.info("Comparator pool (AF without apixaban): %d persons", len(cmp_df))

    # Step 4: Assign events
    tx_df["group"] = "treatment"
    cmp_df["group"] = "comparator"
    all_df = pd.concat([tx_df, cmp_df], ignore_index=True)

    tx_mask = all_df["group"] == "treatment"
    cmp_mask = all_df["group"] == "comparator"

    tx_events = rng.random(int(tx_mask.sum())) < args.tx_rate
    cmp_events = rng.random(int(cmp_mask.sum())) < args.cmp_rate

    all_df.loc[tx_mask, "has_event"] = tx_events
    all_df.loc[cmp_mask, "has_event"] = cmp_events

    event_df = all_df[all_df["has_event"] == True].copy()  # noqa: E712

    logger.info(
        "Events assigned: TX=%d/%d (%.1f%%), CMP=%d/%d (%.1f%%)",
        int(tx_events.sum()),
        int(tx_mask.sum()),
        100 * tx_events.mean(),
        int(cmp_events.sum()),
        int(cmp_mask.sum()),
        100 * cmp_events.mean(),
    )

    # Step 5: Build condition_occurrence rows
    rows: list[dict] = []
    next_id = INJECTED_ID_BASE
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
                "condition_source_value": INJECTED_SOURCE_VALUE,
            }
        )
        next_id += 1

    logger.info("Total rows to insert: %d", len(rows))

    # Step 6: Insert and clear cache
    if not args.dry_run and rows:
        df_rows = pd.DataFrame(rows)
        with engine.connect() as conn:
            # Ensure observation periods cover event dates
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
        logger.info("Inserted %d rows into %s.condition_occurrence", len(rows), CDM_SCHEMA)

        # Clear WebAPI cache
        with engine.connect() as conn:
            cache_deleted = conn.execute(
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
        logger.info("Cleared %d WebAPI cache rows for %s", cache_deleted, SOURCE_KEY)
    elif args.dry_run:
        logger.info("[dry-run] Would insert %d rows", len(rows))

    # Summary
    print("\n" + "=" * 60)
    print("ARISTOTLE COHORT-BLIND INJECTION SUMMARY")
    print("=" * 60)
    print(f"Treatment pool (apixaban):    {len(tx_set):>6,}")
    print(f"Comparator pool (AF no apix): {len(cmp_df):>6,}")
    print(f"TX events:                    {int(tx_events.sum()):>6,} ({100*tx_events.mean():.1f}%)")
    print(f"CMP events:                   {int(cmp_events.sum()):>6,} ({100*cmp_events.mean():.1f}%)")
    print(f"Total injected:               {len(rows):>6,}")
    print(f"Outcome concept:              {OUTCOME_CONCEPT_ID} (cerebral infarction)")
    if args.dry_run:
        print("DRY RUN -- no data written")
    print("=" * 60)


if __name__ == "__main__":
    main()
