#!/usr/bin/env python3
"""
Inject synthetic PLATO support data to increase AI treatment cohort (941) size
without modifying cohort definitions.

This script adds, for sampled adult persons:
  - ticagrelor drug_exposure + drug_era at an adult index date
  - ACS condition one day before index (for Rule 1)
  - ST-elevation measurement one day before index (for Rule 2)

Then it clears WebAPI generation cache and regenerates cohort 941.
"""
from __future__ import annotations

import argparse
import os
import time

import numpy as np
import pandas as pd
import requests
from sqlalchemy import create_engine, text

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:mypass@127.0.0.1:5432/postgres")
os.environ.setdefault("WEBAPI_URL", "http://127.0.0.1/WebAPI")

CDM_SCHEMA = "synthea_cdm_plato"
RESULTS_SCHEMA = "synthea_cdm_plato_results"
SOURCE_KEY = "PLATO_BENCHMARK"
COHORT_ID = 941

TICAGRELOR_INGREDIENT_ID = 40241186
ACS_CONCEPT_ID = 312327
ST_ELEVATION_MEASUREMENT_ID = 4089480

DRUG_TYPE_CONCEPT_ID = 32838
CONDITION_TYPE_CONCEPT_ID = 32827
MEASUREMENT_TYPE_CONCEPT_ID = 32817

SOURCE_VALUE = "INJECTED_PLATO_ELIGIBILITY_SUPPORT"
ID_BASE = 300_000_000


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Inject PLATO eligibility support data (cohort 941)")
    p.add_argument("--target-count", type=int, default=500, help="Number of new candidate persons to synthesize")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-regenerate", action="store_true")
    p.add_argument("--db-url", default=os.environ.get("DATABASE_URL"))
    p.add_argument("--webapi-url", default=os.environ.get("WEBAPI_URL"))
    return p.parse_args(argv)


def _candidate_pool(engine) -> pd.DataFrame:
    sql = text(
        f"""
        WITH existing_ticagrelor AS (
          SELECT DISTINCT de.person_id
          FROM {CDM_SCHEMA}.drug_era de
          JOIN {CDM_SCHEMA}.concept_ancestor ca
            ON ca.descendant_concept_id = de.drug_concept_id
          WHERE ca.ancestor_concept_id = :ticagrelor
        ),
        feasible_adult_index AS (
          SELECT
            p.person_id,
            GREATEST(
              op.observation_period_start_date + 365,
              make_date(p.year_of_birth + 18, 1, 1)
            )::date AS index_date,
            op.observation_period_end_date
          FROM {CDM_SCHEMA}.person p
          JOIN {CDM_SCHEMA}.observation_period op
            ON op.person_id = p.person_id
        )
        SELECT fai.person_id, fai.index_date
        FROM feasible_adult_index fai
        LEFT JOIN existing_ticagrelor et
          ON et.person_id = fai.person_id
        WHERE et.person_id IS NULL
          AND fai.index_date <= (fai.observation_period_end_date - 30)
        """
    )
    with engine.connect() as conn:
        return pd.read_sql(sql, conn, params={"ticagrelor": TICAGRELOR_INGREDIENT_ID})


def _next_ids(engine) -> dict[str, int]:
    with engine.connect() as conn:
        max_drug_exposure = conn.execute(
            text(f"SELECT COALESCE(MAX(drug_exposure_id), 0) FROM {CDM_SCHEMA}.drug_exposure")
        ).scalar()
        max_drug_era = conn.execute(
            text(f"SELECT COALESCE(MAX(drug_era_id), 0) FROM {CDM_SCHEMA}.drug_era")
        ).scalar()
        max_condition = conn.execute(
            text(f"SELECT COALESCE(MAX(condition_occurrence_id), 0) FROM {CDM_SCHEMA}.condition_occurrence")
        ).scalar()
        max_measurement = conn.execute(
            text(f"SELECT COALESCE(MAX(measurement_id), 0) FROM {CDM_SCHEMA}.measurement")
        ).scalar()
    return {
        "drug_exposure": max(ID_BASE, int(max_drug_exposure) + 1),
        "drug_era": max(ID_BASE, int(max_drug_era) + 1),
        "condition": max(ID_BASE, int(max_condition) + 1),
        "measurement": max(ID_BASE, int(max_measurement) + 1),
    }


def _cleanup_previous_injections(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                DELETE FROM {CDM_SCHEMA}.drug_exposure
                WHERE drug_exposure_id >= {ID_BASE}
                """
            )
        )
        conn.execute(
            text(
                f"""
                DELETE FROM {CDM_SCHEMA}.drug_era
                WHERE drug_era_id >= {ID_BASE}
                """
            )
        )
        conn.execute(
            text(
                f"""
                DELETE FROM {CDM_SCHEMA}.condition_occurrence
                WHERE condition_occurrence_id >= {ID_BASE}
                  AND condition_source_value = :src
                """
            ),
            {"src": SOURCE_VALUE},
        )
        conn.execute(
            text(
                f"""
                DELETE FROM {CDM_SCHEMA}.measurement
                WHERE measurement_id >= {ID_BASE}
                  AND measurement_source_value = :src
                """
            ),
            {"src": SOURCE_VALUE},
        )


def _inject_rows(engine, sampled: pd.DataFrame) -> dict[str, int]:
    ids = _next_ids(engine)
    drug_exp_rows: list[dict] = []
    drug_era_rows: list[dict] = []
    condition_rows: list[dict] = []
    measurement_rows: list[dict] = []

    for i, row in enumerate(sampled.itertuples(index=False)):
        idx = pd.to_datetime(row.index_date).date()
        pre = idx - pd.Timedelta(days=1)
        end = idx + pd.Timedelta(days=30)
        pid = int(row.person_id)

        drug_exp_rows.append(
            {
                "drug_exposure_id": ids["drug_exposure"] + i,
                "person_id": pid,
                "drug_concept_id": TICAGRELOR_INGREDIENT_ID,
                "drug_exposure_start_date": idx,
                "drug_exposure_end_date": end,
                "drug_type_concept_id": DRUG_TYPE_CONCEPT_ID,
                "days_supply": 30,
                "sig": None,
                "route_concept_id": None,
                "lot_number": None,
                "provider_id": None,
                "visit_occurrence_id": None,
                "visit_detail_id": None,
                "drug_source_value": SOURCE_VALUE,
                "drug_source_concept_id": None,
                "route_source_value": None,
                "dose_unit_source_value": None,
            }
        )
        drug_era_rows.append(
            {
                "drug_era_id": ids["drug_era"] + i,
                "person_id": pid,
                "drug_concept_id": TICAGRELOR_INGREDIENT_ID,
                "drug_era_start_date": idx,
                "drug_era_end_date": end,
                "drug_exposure_count": 1,
                "gap_days": 0,
            }
        )
        condition_rows.append(
            {
                "condition_occurrence_id": ids["condition"] + i,
                "person_id": pid,
                "condition_concept_id": ACS_CONCEPT_ID,
                "condition_start_date": pre,
                "condition_end_date": pre,
                "condition_type_concept_id": CONDITION_TYPE_CONCEPT_ID,
                "stop_reason": None,
                "provider_id": None,
                "visit_occurrence_id": None,
                "visit_detail_id": None,
                "condition_source_value": SOURCE_VALUE,
                "condition_source_concept_id": None,
                "condition_status_source_value": None,
                "condition_status_concept_id": None,
            }
        )
        measurement_rows.append(
            {
                "measurement_id": ids["measurement"] + i,
                "person_id": pid,
                "measurement_concept_id": ST_ELEVATION_MEASUREMENT_ID,
                "measurement_date": pre,
                "measurement_datetime": None,
                "measurement_type_concept_id": MEASUREMENT_TYPE_CONCEPT_ID,
                "operator_concept_id": None,
                "value_as_number": 0.15,
                "value_as_concept_id": None,
                "unit_concept_id": None,
                "range_low": None,
                "range_high": None,
                "provider_id": None,
                "visit_occurrence_id": None,
                "visit_detail_id": None,
                "measurement_source_value": SOURCE_VALUE,
                "measurement_source_concept_id": None,
                "unit_source_value": "mV",
                "unit_source_concept_id": None,
                "value_source_value": "0.15",
                "measurement_event_id": None,
                "meas_event_field_concept_id": None,
            }
        )

    with engine.begin() as conn:
        pd.DataFrame(drug_exp_rows).to_sql(
            "drug_exposure",
            conn,
            schema=CDM_SCHEMA,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=500,
        )
        pd.DataFrame(drug_era_rows).to_sql(
            "drug_era",
            conn,
            schema=CDM_SCHEMA,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=500,
        )
        pd.DataFrame(condition_rows).to_sql(
            "condition_occurrence",
            conn,
            schema=CDM_SCHEMA,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=500,
        )
        pd.DataFrame(measurement_rows).to_sql(
            "measurement",
            conn,
            schema=CDM_SCHEMA,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=500,
        )

    return {
        "drug_exposure": len(drug_exp_rows),
        "drug_era": len(drug_era_rows),
        "condition_occurrence": len(condition_rows),
        "measurement": len(measurement_rows),
    }


def _clear_cache(engine) -> int:
    with engine.begin() as conn:
        deleted = conn.execute(
            text(
                """
                WITH source_row AS (
                  SELECT source_id
                  FROM webapi.source
                  WHERE source_key = :source_key
                )
                DELETE FROM webapi.generation_cache gc
                USING source_row s
                WHERE gc.type = 'COHORT'
                  AND gc.source_id = s.source_id
                """
            ),
            {"source_key": SOURCE_KEY},
        ).rowcount
    return int(deleted or 0)


def _regenerate(webapi_url: str) -> None:
    requests.get(f"{webapi_url}/cohortdefinition/{COHORT_ID}/generate/{SOURCE_KEY}", timeout=30).raise_for_status()


def _poll_generation(engine, timeout_secs: int = 600) -> tuple[int, int]:
    deadline = time.time() + timeout_secs
    status = 0
    person_count = 0
    while time.time() < deadline:
        time.sleep(2)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT cgi.status, cgi.person_count
                    FROM webapi.cohort_generation_info cgi
                    JOIN webapi.source s ON s.source_id = cgi.source_id
                    WHERE cgi.id = :cohort_id
                      AND s.source_key = :source_key
                    ORDER BY cgi.start_time DESC
                    LIMIT 1
                    """
                ),
                {"cohort_id": COHORT_ID, "source_key": SOURCE_KEY},
            ).mappings().first()
        if row:
            status = int(row["status"] or 0)
            person_count = int(row["person_count"] or 0)
            if status == 2:
                break
    return status, person_count


def _current_counts(engine) -> tuple[int, tuple[int, int] | None]:
    with engine.connect() as conn:
        n = conn.execute(
            text(f"SELECT COUNT(DISTINCT subject_id) FROM {RESULTS_SCHEMA}.cohort WHERE cohort_definition_id = :cid"),
            {"cid": COHORT_ID},
        ).scalar()
        row = conn.execute(
            text(
                f"""
                SELECT base_count, final_count
                FROM {RESULTS_SCHEMA}.cohort_summary_stats
                WHERE cohort_definition_id = :cid
                  AND mode_id = 0
                """
            ),
            {"cid": COHORT_ID},
        ).fetchone()
    return int(n or 0), (int(row[0]), int(row[1])) if row else None


def main(argv=None) -> None:
    args = parse_args(argv)
    engine = create_engine(args.db_url)

    before_n, before_stats = _current_counts(engine)
    print(f"[before] cohort {COHORT_ID}: N={before_n}, summary={before_stats}")

    pool = _candidate_pool(engine)
    if pool.empty:
        raise RuntimeError("No eligible candidate pool found for injection.")

    target = min(args.target_count, len(pool))
    rng = np.random.default_rng(args.seed)
    sampled = pool.iloc[rng.choice(len(pool), size=target, replace=False)].copy()
    sampled = sampled.sort_values("person_id").reset_index(drop=True)
    print(f"[plan] candidate pool={len(pool)}, sampled={len(sampled)}")

    if args.dry_run:
        print("[dry-run] no rows injected")
        return

    _cleanup_previous_injections(engine)
    injected = _inject_rows(engine, sampled)
    print(f"[inject] rows={injected}")

    if not args.skip_regenerate:
        deleted = _clear_cache(engine)
        print(f"[cache] cleared rows={deleted}")
        _regenerate(args.webapi_url)
        status, person_count = _poll_generation(engine)
        print(f"[regen] status={status}, person_count={person_count}")

    after_n, after_stats = _current_counts(engine)
    print(f"[after] cohort {COHORT_ID}: N={after_n}, summary={after_stats}")


if __name__ == "__main__":
    main()

