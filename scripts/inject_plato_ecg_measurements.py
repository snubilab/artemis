#!/usr/bin/env python3
"""
ECG ST Elevation Measurement Injection for PLATO Benchmark CDM.

PLATO AI cohort (941) requires Rule 2: "ST-segment elevation of at least 0.1 mV
in two contiguous leads OR new LBBB" — specifically Measurement concept_ids
(4089480, 4146761, 37021258) with value_as_number >= 0.1.

Synthea does not generate ECG measurements, so cohort 941 gets 0 patients.
This script injects synthetic ECG measurements for patients who:
  - Have a ticagrelor drug era (primary criteria for cohort 941)
  - Have an ACS/NSTEMI condition occurrence (Rule 1 of cohort 941)

Measurements are placed on the same date as the earliest matching ACS condition.

Usage:
    python3 artemis/scripts/inject_plato_ecg_measurements.py
    python3 artemis/scripts/inject_plato_ecg_measurements.py --dry-run
    python3 artemis/scripts/inject_plato_ecg_measurements.py --regen-cohort 941
"""
import argparse
import logging
import os
import time

import pandas as pd
import requests
from sqlalchemy import create_engine, text

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:mypass@127.0.0.1:5432/postgres")
os.environ.setdefault("WEBAPI_URL", "http://127.0.0.1/WebAPI")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

# Concept IDs for ST elevation measurement (from cohort 941 concept set 5)
ST_ELEVATION_CONCEPT_ID = 4089480  # "Segment deviation (ECG)" [Measurement]

# ACS/NSTEMI concept IDs present in PLATO CDM (from cohort 941 concept sets 2/3/4)
ACS_CONCEPT_IDS = [
    4270024,  # Acute non-ST segment elevation myocardial infarction
    312327,   # Acute myocardial infarction
    4296653,  # Acute ST segment elevation myocardial infarction
    604425,   # AMI due to occlusion of circumflex branch
    3655133,  # Acute STEMI due to occlusion of intermediate artery
    315296,   # Preinfarction syndrome (unstable angina)
]

# Ticagrelor concept ID
TICAGRELOR_CONCEPT_ID = 40241186

# EHR record type concept
MEASUREMENT_TYPE_CONCEPT_ID = 32817  # EHR

# Safe ID base (max existing measurement_id is ~84, this is very safe)
INJECTED_ID_BASE = 10_000_000

INJECTED_SOURCE_VALUE = "INJECTED_ST_ELEVATION"

# Value to inject: 0.15 mV (well above 0.1 threshold)
ST_ELEVATION_VALUE = 0.15

# Unit concept for millivolts (if available; 0 = unknown)
UNIT_CONCEPT_ID = 0  # mV unit not critical for cohort definition

WEBAPI_URL = os.environ.get("WEBAPI_URL", "http://127.0.0.1/WebAPI")
WEBAPI_POLL_INTERVAL = 10
WEBAPI_MAX_POLL_SECS = 300


def get_engine():
    db_url = os.environ.get("DATABASE_URL", "postgresql://postgres:mypass@127.0.0.1:5432/postgres")
    return create_engine(db_url)


def find_target_patients(engine) -> pd.DataFrame:
    """Find patients with ticagrelor + ACS who need ECG measurement injection.

    Returns DataFrame with columns: person_id, acs_date (earliest ACS condition date).
    """
    acs_ids_str = ", ".join(str(c) for c in ACS_CONCEPT_IDS)
    sql = text(f"""
        SELECT DISTINCT
            de.person_id,
            MIN(co.condition_start_date) AS acs_date
        FROM synthea_cdm_plato.drug_era de
        JOIN synthea_cdm_plato.condition_occurrence co
            ON co.person_id = de.person_id
        WHERE de.drug_concept_id = :ticagrelor
          AND de.drug_era_start_date >= '2011-07-22'
          AND (de.drug_era_end_date - de.drug_era_start_date) >= 7
          AND co.condition_concept_id IN ({acs_ids_str})
        GROUP BY de.person_id
    """)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"ticagrelor": TICAGRELOR_CONCEPT_ID})
    logger.info("Found %d target patients with ticagrelor + ACS", len(df))
    return df


def already_has_ecg(engine, person_ids: list) -> set:
    """Return set of person_ids that already have ST elevation measurements."""
    if not person_ids:
        return set()
    ids_str = ", ".join(str(p) for p in person_ids)
    sql = text(f"""
        SELECT DISTINCT person_id
        FROM synthea_cdm_plato.measurement
        WHERE measurement_concept_id = :concept_id
          AND value_as_number >= 0.1
          AND person_id IN ({ids_str})
    """)
    with engine.connect() as conn:
        result = conn.execute(sql, {"concept_id": ST_ELEVATION_CONCEPT_ID})
        return {row[0] for row in result}


def inject_measurements(engine, patients: pd.DataFrame, dry_run: bool = False) -> int:
    """Inject ST elevation measurements for all target patients.

    Returns number of rows injected.
    """
    if patients.empty:
        logger.info("No patients to inject measurements for.")
        return 0

    with engine.connect() as conn:
        result = conn.execute(text("SELECT COALESCE(MAX(measurement_id), 0) FROM synthea_cdm_plato.measurement"))
        max_id = result.scalar()

    start_id = max(INJECTED_ID_BASE, max_id + 1)
    logger.info("Using measurement_id starting at %d (max existing: %d)", start_id, max_id)

    rows = []
    for i, row in enumerate(patients.itertuples(index=False)):
        rows.append({
            "measurement_id": start_id + i,
            "person_id": row.person_id,
            "measurement_concept_id": ST_ELEVATION_CONCEPT_ID,
            "measurement_date": row.acs_date,
            "measurement_datetime": None,
            "measurement_type_concept_id": MEASUREMENT_TYPE_CONCEPT_ID,
            "operator_concept_id": None,
            "value_as_number": ST_ELEVATION_VALUE,
            "value_as_concept_id": None,
            "unit_concept_id": UNIT_CONCEPT_ID if UNIT_CONCEPT_ID else None,
            "range_low": None,
            "range_high": None,
            "provider_id": None,
            "visit_occurrence_id": None,
            "visit_detail_id": None,
            "measurement_source_value": INJECTED_SOURCE_VALUE,
            "measurement_source_concept_id": None,
            "unit_source_value": "mV",
            "unit_source_concept_id": None,
            "value_source_value": str(ST_ELEVATION_VALUE),
            "measurement_event_id": None,
            "meas_event_field_concept_id": None,
        })

    df_insert = pd.DataFrame(rows)
    logger.info("Prepared %d measurement rows for injection", len(df_insert))

    if dry_run:
        logger.info("[DRY RUN] Would insert %d rows. First row: %s", len(df_insert), rows[0])
        return len(df_insert)

    df_insert.to_sql(
        "measurement",
        engine,
        schema="synthea_cdm_plato",
        if_exists="append",
        index=False,
        method="multi",
        chunksize=500,
    )
    logger.info("Inserted %d ST elevation measurement rows into synthea_cdm_plato.measurement", len(df_insert))
    return len(df_insert)


def clear_webapi_cache(source_id: int = 7) -> None:
    """Clear WebAPI generation cache for PLATO source."""
    db_url = os.environ.get("DATABASE_URL", "postgresql://postgres:mypass@127.0.0.1:5432/postgres")
    engine = create_engine(db_url)
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM webapi.generation_cache WHERE source_id = :sid"),
            {"sid": source_id},
        )
        logger.info("Cleared %d WebAPI cache rows for source_id=%d", result.rowcount, source_id)


def regenerate_cohort(cohort_id: int, source_key: str = "PLATO_BENCHMARK") -> bool:
    """Trigger WebAPI cohort regeneration and poll until complete."""
    url = f"{WEBAPI_URL}/cohortdefinition/{cohort_id}/generate/{source_key}"
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        logger.error("Failed to trigger generation for cohort %d: %s", cohort_id, resp.text[:200])
        return False

    logger.info("Triggered generation for cohort %d on %s", cohort_id, source_key)

    # Poll until complete
    info_url = f"{WEBAPI_URL}/cohortdefinition/{cohort_id}/info"
    deadline = time.time() + WEBAPI_MAX_POLL_SECS
    while time.time() < deadline:
        time.sleep(WEBAPI_POLL_INTERVAL)
        try:
            info_resp = requests.get(info_url, timeout=15)
            infos = info_resp.json()
            for info in infos:
                if info["id"]["sourceId"] == 7:  # PLATO source
                    status = info.get("status", "UNKNOWN")
                    persons = info.get("personCount", 0)
                    logger.info("Cohort %d: status=%s, persons=%d", cohort_id, status, persons)
                    if status == "COMPLETE":
                        return True
                    if status in ("FAILED", "CANCELED"):
                        logger.error("Cohort %d generation failed: %s", cohort_id, status)
                        return False
        except Exception as e:
            logger.warning("Poll error: %s", e)

    logger.error("Cohort %d generation timed out after %ds", cohort_id, WEBAPI_MAX_POLL_SECS)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject ECG ST elevation measurements into PLATO CDM")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no DB writes")
    parser.add_argument("--regen-cohort", type=int, default=941,
                        help="Cohort ID to regenerate after injection (default: 941)")
    parser.add_argument("--skip-regen", action="store_true", help="Skip WebAPI cohort regeneration")
    args = parser.parse_args()

    engine = get_engine()

    # Find target patients
    patients = find_target_patients(engine)
    if patients.empty:
        logger.warning("No target patients found. Check CDM data.")
        return

    # Skip patients who already have ECG measurements
    existing = already_has_ecg(engine, list(patients["person_id"]))
    if existing:
        logger.info("Skipping %d patients who already have ECG measurements", len(existing))
        patients = patients[~patients["person_id"].isin(existing)]

    # Inject measurements
    n_injected = inject_measurements(engine, patients, dry_run=args.dry_run)
    logger.info("Injection complete: %d measurements", n_injected)

    if args.dry_run or args.skip_regen:
        return

    # Clear WebAPI cache and regenerate cohort
    clear_webapi_cache(source_id=7)
    ok = regenerate_cohort(args.regen_cohort)
    if ok:
        logger.info("Cohort %d regenerated successfully.", args.regen_cohort)
    else:
        logger.error("Cohort %d regeneration failed or timed out.", args.regen_cohort)


if __name__ == "__main__":
    main()
