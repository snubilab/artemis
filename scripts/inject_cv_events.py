#!/usr/bin/env python3
"""
CV Outcome Event Injection for Gold vs AI Cohort Comparison.

Injects synthetic MI (concept_id=4329847) events into CDM condition_occurrence
so that Gold and AI cohort survival analyses produce non-degenerate HRs.

Design: Cohort-blind population injection
  - "treated" = union(gold_cohort, ai_cohort) → treatment_rate events
  - "untreated" = remaining CDM population → comparator_rate events
  - untreated index_date = min(treatment_index_date)  [matches omop_connector:822]
  - event dates in [index_date + 30, index_date + 330] (within 365-day followup)

After injection, triggers WebAPI outcome cohort regeneration so the results schema
reflects the new condition_occurrence rows.

Usage:
    python3 artemis/scripts/inject_cv_events.py
    python3 artemis/scripts/inject_cv_events.py --studies PLATO --dry-run
    python3 artemis/scripts/inject_cv_events.py --treatment-rate 0.30 --comparator-rate 0.15
"""
import argparse
import dataclasses
import json
import logging
import math
import os
import sys
import time
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import requests
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:mypass@127.0.0.1:5432/postgres")
os.environ.setdefault("WEBAPI_URL", "http://127.0.0.1/WebAPI")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

# Per-study outcome concept IDs (must match the outcome cohort CIRCE definition)
# LEADER 841: concept 312327 (Acute myocardial infarction)
# PLATO 943:  concept 4329847 (Myocardial infarction)
# ARISTOTLE 1128: concept 381316 (Cerebrovascular accident / stroke)
MI_CONCEPT_ID = 4329847          # fallback — overridden per study
CONDITION_TYPE_CONCEPT_ID = 32817  # OMOP: EHR record
INJECTED_SOURCE_VALUE = "INJECTED_CV_EVENT"
INJECTED_ID_BASE = 100_000_000   # max existing ID is ~12M; safe to start at 100M
EVENT_WINDOW_START_DAYS = 30     # earliest post-index event day
EVENT_WINDOW_END_DAYS = 330      # latest post-index event day (365 - 35 buffer)

WEBAPI_URL = os.environ.get("WEBAPI_URL", "http://127.0.0.1/WebAPI")
WEBAPI_POLL_INTERVAL = 10
WEBAPI_MAX_POLL_SECS = 3600


# ──────────────────────────────────────────────────────────────────────────────
# Study configuration
# ──────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class StudyConfig:
    name: str
    cdm_schema: str
    results_schema: str
    source_key: str
    ai_treatment_id: int
    gold_treatment_id: int
    outcome_id: int
    outcome_concept_id: int  # concept used in outcome cohort CIRCE definition


STUDIES: list[StudyConfig] = [
    StudyConfig(
        name="LEADER",
        cdm_schema="synthea_cdm_leader",
        results_schema="synthea_cdm_leader_results",
        source_key="LEADER_BENCHMARK",
        ai_treatment_id=840,
        gold_treatment_id=1136,
        outcome_id=841,
        outcome_concept_id=312327,   # Acute myocardial infarction
    ),
    StudyConfig(
        name="PLATO",
        cdm_schema="synthea_cdm_plato",
        results_schema="synthea_cdm_plato_results",
        source_key="PLATO_BENCHMARK",
        ai_treatment_id=941,
        gold_treatment_id=1137,
        outcome_id=943,
        outcome_concept_id=4329847,  # Myocardial infarction
    ),
    StudyConfig(
        name="ARISTOTLE",
        cdm_schema="synthea_cdm_aristotle",
        results_schema="synthea_cdm_aristotle_results",
        source_key="ARISTOTLE_BENCHMARK",
        ai_treatment_id=1127,
        gold_treatment_id=1138,
        outcome_id=1128,
        outcome_concept_id=381316,   # Cerebrovascular accident (stroke)
    ),
]


# ──────────────────────────────────────────────────────────────────────────────
# Core injection logic
# ──────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class OutcomeConceptFilter:
    include_exact: tuple[int, ...]
    include_descendants: tuple[int, ...]
    exclude_exact: tuple[int, ...]
    exclude_descendants: tuple[int, ...]


def _load_outcome_condition_filter(conn, study: StudyConfig) -> OutcomeConceptFilter:
    """
    Parse WebAPI cohort definition JSON and extract concept filters used by
    primary ConditionOccurrence criteria.
    """
    expr_text = conn.execute(
        text("SELECT expression FROM webapi.cohort_definition_details WHERE id = :cid"),
        {"cid": study.outcome_id},
    ).scalar()
    if not expr_text:
        return OutcomeConceptFilter(
            include_exact=(study.outcome_concept_id,),
            include_descendants=(),
            exclude_exact=(),
            exclude_descendants=(),
        )

    expr = json.loads(expr_text)
    concept_sets = {
        int(cs.get("id")): cs
        for cs in (expr.get("ConceptSets") or [])
        if cs.get("id") is not None
    }
    criteria = (expr.get("PrimaryCriteria") or {}).get("CriteriaList") or []
    condition_codeset_ids = {
        int((crit.get("ConditionOccurrence") or {}).get("CodesetId"))
        for crit in criteria
        if (crit.get("ConditionOccurrence") or {}).get("CodesetId") is not None
    }

    include_exact: set[int] = set()
    include_desc: set[int] = set()
    exclude_exact: set[int] = set()
    exclude_desc: set[int] = set()

    for cs_id in condition_codeset_ids:
        cs = concept_sets.get(cs_id) or {}
        items = ((cs.get("expression") or {}).get("items")) or []
        for item in items:
            concept = item.get("concept") or {}
            cid = concept.get("CONCEPT_ID")
            if cid is None:
                continue
            cid = int(cid)
            is_excluded = bool(item.get("isExcluded", False))
            with_desc = bool(item.get("includeDescendants", False))
            if is_excluded:
                if with_desc:
                    exclude_desc.add(cid)
                else:
                    exclude_exact.add(cid)
            else:
                if with_desc:
                    include_desc.add(cid)
                else:
                    include_exact.add(cid)

    if not include_exact and not include_desc:
        include_exact.add(study.outcome_concept_id)

    return OutcomeConceptFilter(
        include_exact=tuple(sorted(include_exact)),
        include_descendants=tuple(sorted(include_desc)),
        exclude_exact=tuple(sorted(exclude_exact)),
        exclude_descendants=tuple(sorted(exclude_desc)),
    )


def _default_observation_period_type(conn, cdm_schema: str) -> int:
    period_type = conn.execute(
        text(
            f"""
            SELECT period_type_concept_id
            FROM {cdm_schema}.observation_period
            GROUP BY period_type_concept_id
            ORDER BY COUNT(*) DESC
            LIMIT 1
            """
        )
    ).scalar()
    return int(period_type or 44814724)


def _next_observation_period_id(conn, cdm_schema: str) -> int:
    max_id = conn.execute(
        text(f"SELECT COALESCE(MAX(observation_period_id), 0) FROM {cdm_schema}.observation_period")
    ).scalar()
    return int(max_id or 0) + 1


def _ensure_observation_window_for_person(
    conn,
    *,
    cdm_schema: str,
    person_id: int,
    min_start: date,
    max_end: date,
    default_period_type: int,
    next_observation_period_id: int,
) -> tuple[int, int]:
    """
    Ensure person has an observation period spanning [min_start, max_end].
    Returns (next_observation_period_id, inserted_count).
    """
    updated = conn.execute(
        text(
            f"""
            UPDATE {cdm_schema}.observation_period
            SET observation_period_start_date = LEAST(observation_period_start_date, :min_start),
                observation_period_end_date = GREATEST(observation_period_end_date, :max_end)
            WHERE person_id = :person_id
            """
        ),
        {"person_id": person_id, "min_start": min_start, "max_end": max_end},
    ).rowcount

    if updated and updated > 0:
        return next_observation_period_id, 0

    conn.execute(
        text(
            f"""
            INSERT INTO {cdm_schema}.observation_period (
                observation_period_id,
                person_id,
                observation_period_start_date,
                observation_period_end_date,
                period_type_concept_id
            ) VALUES (
                :observation_period_id,
                :person_id,
                :start_date,
                :end_date,
                :period_type_concept_id
            )
            """
        ),
        {
            "observation_period_id": next_observation_period_id,
            "person_id": person_id,
            "start_date": min_start,
            "end_date": max_end,
            "period_type_concept_id": default_period_type,
        },
    )
    return next_observation_period_id + 1, 1


def _delete_preindex_outcomes_for_person(
    conn,
    *,
    study: StudyConfig,
    person_id: int,
    index_date: date,
    concept_filter: OutcomeConceptFilter,
) -> int:
    """
    Delete pre-index qualifying outcome-condition rows so injected events can
    become the first qualifying event when outcome cohort uses QualifiedLimit=First.
    """
    include_parts: list[str] = []
    params: dict = {"person_id": person_id, "index_date": index_date}

    if concept_filter.include_exact:
        include_parts.append("co.condition_concept_id = ANY(:include_exact)")
        params["include_exact"] = list(concept_filter.include_exact)
    if concept_filter.include_descendants:
        include_parts.append(
            f"""
            EXISTS (
              SELECT 1
              FROM {study.cdm_schema}.concept_ancestor ca
              WHERE ca.ancestor_concept_id = ANY(:include_desc)
                AND ca.descendant_concept_id = co.condition_concept_id
            )
            """
        )
        params["include_desc"] = list(concept_filter.include_descendants)

    if not include_parts:
        return 0

    exclude_parts: list[str] = []
    if concept_filter.exclude_exact:
        exclude_parts.append("co.condition_concept_id = ANY(:exclude_exact)")
        params["exclude_exact"] = list(concept_filter.exclude_exact)
    if concept_filter.exclude_descendants:
        exclude_parts.append(
            f"""
            EXISTS (
              SELECT 1
              FROM {study.cdm_schema}.concept_ancestor ca
              WHERE ca.ancestor_concept_id = ANY(:exclude_desc)
                AND ca.descendant_concept_id = co.condition_concept_id
            )
            """
        )
        params["exclude_desc"] = list(concept_filter.exclude_descendants)

    include_expr = " OR ".join(f"({part})" for part in include_parts)
    exclude_expr = " OR ".join(f"({part})" for part in exclude_parts) if exclude_parts else "FALSE"

    sql = text(
        f"""
        DELETE FROM {study.cdm_schema}.condition_occurrence co
        WHERE co.person_id = :person_id
          AND co.condition_start_date <= :index_date
          AND ({include_expr})
          AND NOT ({exclude_expr})
          AND co.condition_occurrence_id < {INJECTED_ID_BASE}
        """
    )
    return int(conn.execute(sql, params).rowcount or 0)


def ci_width(ci_lower: float | None, ci_upper: float | None) -> float | None:
    """Return CI width if both bounds are present."""
    if ci_lower is None or ci_upper is None:
        return None
    return float(ci_upper) - float(ci_lower)


def assign_events_label_blind(
    person_df: pd.DataFrame,
    *,
    seed: int,
    base_rate: float,
    true_hr: float,
) -> pd.DataFrame:
    """
    Assign outcome events without using AI/Gold membership labels.

    The probability model uses only treatment flag and baseline clinical covariates.
    """
    if person_df.empty:
        return person_df

    if not 0.0 < base_rate < 1.0:
        raise ValueError(f"base_rate must be in (0,1), got {base_rate}")
    if true_hr <= 0.0:
        raise ValueError(f"true_hr must be > 0, got {true_hr}")

    rng = np.random.default_rng(seed)
    work = person_df.copy()

    # Keep influence bounded so calibration remains stable study-to-study.
    capped_rf = work["risk_factor_count"].fillna(0).clip(lower=0, upper=12).astype(float)
    age_term = 0.02 * (work["age"].fillna(60).astype(float) - 60.0)
    sex_term = 0.15 * work["male"].fillna(0).astype(float)
    risk_term = 0.08 * capped_rf

    baseline_logit = math.log(base_rate / (1.0 - base_rate))
    treatment_term = math.log(true_hr) * work["treated"].fillna(0).astype(float)
    linear = baseline_logit + age_term + sex_term + risk_term + treatment_term

    work["event_prob"] = 1.0 / (1.0 + np.exp(-linear))
    work["event"] = (rng.random(len(work)) < work["event_prob"].to_numpy()).astype(int)
    return work

def inject_study(
    study: StudyConfig,
    engine,
    rng: np.random.Generator,
    treatment_rate: float,
    comparator_rate: float,
    event_window_start_days: int = EVENT_WINDOW_START_DAYS,
    event_window_end_days: int = EVENT_WINDOW_END_DAYS,
    dry_run: bool = False,
) -> dict:
    """
    Inject CV events for one study. Returns a summary dict.
    """
    logger.info(
        "[%s] Starting injection (treatment_rate=%.3f, comparator_rate=%.3f, window=%d-%d days)",
        study.name,
        treatment_rate,
        comparator_rate,
        event_window_start_days,
        event_window_end_days,
    )
    if event_window_start_days < 1 or event_window_end_days < event_window_start_days:
        raise ValueError(
            f"Invalid event window: start={event_window_start_days}, end={event_window_end_days}"
        )

    with engine.connect() as conn:
        if not dry_run:
            deleted = conn.execute(
                text(
                    f"DELETE FROM {study.cdm_schema}.condition_occurrence "
                    f"WHERE condition_occurrence_id >= {INJECTED_ID_BASE}"
                )
            ).rowcount
            conn.commit()
            logger.info("[%s] Cleaned %d previous injected rows", study.name, deleted)

        treated_df = pd.read_sql(
            text(
                f"""
                SELECT subject_id AS person_id, MIN(cohort_start_date) AS index_date
                FROM {study.results_schema}.cohort
                WHERE cohort_definition_id IN (:gold_id, :ai_id)
                GROUP BY subject_id
                """
            ),
            conn,
            params={"gold_id": study.gold_treatment_id, "ai_id": study.ai_treatment_id},
        )

        if treated_df.empty:
            logger.warning("[%s] No treated persons found — skipping", study.name)
            return {
                "study": study.name,
                "cdm_n": 0,
                "treated": 0,
                "untreated": 0,
                "treated_events": 0,
                "untreated_events": 0,
                "total_inserted": 0,
                "dry_run": dry_run,
            }

        treated_df["index_date"] = pd.to_datetime(treated_df["index_date"]).dt.date
        treated_map: dict[int, date] = dict(zip(treated_df["person_id"], treated_df["index_date"]))
        treated_set = set(treated_map.keys())
        min_index_date: date = min(treated_map.values())
        logger.info("[%s] Treated persons (gold∪AI): %d", study.name, len(treated_set))
        logger.info("[%s] min_treatment_index_date = %s", study.name, min_index_date)

        person_df = pd.read_sql(
            text(
                f"""
                SELECT person_id, year_of_birth, gender_concept_id
                FROM {study.cdm_schema}.person
                """
            ),
            conn,
        )
        risk_df = pd.read_sql(
            text(
                f"""
                SELECT person_id, COUNT(*)::int AS risk_factor_count
                FROM {study.cdm_schema}.condition_occurrence
                WHERE condition_start_date < :min_index_date
                GROUP BY person_id
                """
            ),
            conn,
            params={"min_index_date": min_index_date},
        )

    person_df["treated"] = person_df["person_id"].isin(treated_set).astype(int)
    person_df["index_date"] = person_df["person_id"].map(treated_map).fillna(min_index_date)
    person_df = person_df.merge(risk_df, on="person_id", how="left")
    person_df["risk_factor_count"] = person_df["risk_factor_count"].fillna(0).astype(int)
    person_df["male"] = (person_df["gender_concept_id"] == 8507).astype(int)
    person_df["age"] = (
        pd.to_datetime(person_df["index_date"]).dt.year
        - person_df["year_of_birth"].fillna(1970).astype(int)
    ).clip(lower=18, upper=110)

    true_hr = max(treatment_rate / max(comparator_rate, 1e-6), 0.01)
    assigned = assign_events_label_blind(
        person_df,
        seed=int(rng.integers(1, 2_000_000_000)),
        base_rate=comparator_rate,
        true_hr=true_hr,
    )
    event_df = assigned[assigned["event"] == 1].copy()

    rows: list[dict] = []
    next_id = INJECTED_ID_BASE
    for row in event_df.itertuples():
        anchor_date = row.index_date if pd.notna(row.index_date) else min_index_date
        event_date = anchor_date + timedelta(
            days=int(rng.integers(event_window_start_days, event_window_end_days + 1))
        )
        rows.append(
            {
                "condition_occurrence_id": next_id,
                "person_id": int(row.person_id),
                "condition_concept_id": study.outcome_concept_id,
                "condition_start_date": event_date,
                "condition_end_date": event_date,
                "condition_type_concept_id": CONDITION_TYPE_CONCEPT_ID,
                "condition_source_value": INJECTED_SOURCE_VALUE,
            }
        )
        next_id += 1

    treated_events = int(event_df["treated"].sum())
    untreated_events = int((event_df["treated"] == 0).sum())
    total_inserted = len(rows)
    untreated_count = int((person_df["treated"] == 0).sum())
    logger.info(
        "[%s] Events to inject: treated=%d (%.1f%%), untreated=%d (%.1f%%), total=%d",
        study.name,
        treated_events,
        100 * treated_events / max(len(treated_set), 1),
        untreated_events,
        100 * untreated_events / max(untreated_count, 1),
        total_inserted,
    )

    # ── Phase E: Observation-window adjustment + pre-index cleanup + INSERT ──
    if not dry_run and rows:
        df_rows = pd.DataFrame(rows)
        event_window_df = event_df[["person_id", "index_date"]].copy()
        event_window_df["event_date"] = df_rows["condition_start_date"].values
        event_window_df = (
            event_window_df.groupby("person_id", as_index=False)
            .agg(index_date=("index_date", "min"), event_date=("event_date", "max"))
        )

        adjusted_obs_people = 0
        inserted_obs_rows = 0
        deleted_preindex_rows = 0

        with engine.connect() as conn:
            concept_filter = _load_outcome_condition_filter(conn, study)
            default_period_type = _default_observation_period_type(conn, study.cdm_schema)
            next_obs_id = _next_observation_period_id(conn, study.cdm_schema)

            for row in event_window_df.itertuples():
                needed_start = row.index_date - timedelta(days=365)
                needed_end = max(row.event_date, row.index_date + timedelta(days=event_window_end_days))
                next_obs_id, inserted = _ensure_observation_window_for_person(
                    conn,
                    cdm_schema=study.cdm_schema,
                    person_id=int(row.person_id),
                    min_start=needed_start,
                    max_end=needed_end,
                    default_period_type=default_period_type,
                    next_observation_period_id=next_obs_id,
                )
                inserted_obs_rows += inserted
                adjusted_obs_people += 1

                deleted_preindex_rows += _delete_preindex_outcomes_for_person(
                    conn,
                    study=study,
                    person_id=int(row.person_id),
                    index_date=row.index_date,
                    concept_filter=concept_filter,
                )

            df_rows.to_sql(
                "condition_occurrence",
                conn,
                schema=study.cdm_schema,
                if_exists="append",
                index=False,
                method="multi",
                chunksize=1000,
            )
            conn.commit()
        logger.info(
            "[%s] Inserted %d rows into %s.condition_occurrence",
            study.name,
            total_inserted,
            study.cdm_schema,
        )
        logger.info(
            "[%s] Observation windows adjusted for %d injected persons (new periods=%d); deleted %d pre-index qualifying outcome rows",
            study.name,
            adjusted_obs_people,
            inserted_obs_rows,
            deleted_preindex_rows,
        )

    return {
        "study": study.name,
        "cdm_n": len(person_df),
        "treated": len(treated_set),
        "untreated": untreated_count,
        "treated_events": treated_events,
        "untreated_events": untreated_events,
        "total_inserted": total_inserted,
        "dry_run": dry_run,
    }


# ──────────────────────────────────────────────────────────────────────────────
# WebAPI outcome cohort regeneration
# ──────────────────────────────────────────────────────────────────────────────

def _clear_webapi_cache(engine, source_key: str) -> int:
    """Clear WebAPI cohort generation cache for a source and return deleted row count."""
    sql = text(
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
    )
    with engine.connect() as conn:
        deleted = conn.execute(sql, {"source_key": source_key}).rowcount or 0
        conn.commit()
    return int(deleted)


def regenerate_outcome_cohort(study: StudyConfig, engine=None, dry_run: bool = False) -> int:
    """
    Trigger WebAPI to regenerate the outcome cohort for a study.
    Returns the new person count.
    """
    if dry_run:
        logger.info("[%s] [dry-run] Would regenerate outcome cohort %d on %s",
                    study.name, study.outcome_id, study.source_key)
        return -1

    logger.info("[%s] Triggering outcome cohort regeneration (cohort_id=%d, source=%s)...",
                study.name, study.outcome_id, study.source_key)
    triggered_at = datetime.utcnow()

    # Trigger generation
    gen_url = f"{WEBAPI_URL}/cohortdefinition/{study.outcome_id}/generate/{study.source_key}"
    resp = requests.get(gen_url, timeout=30)
    resp.raise_for_status()
    logger.info("[%s] Generation triggered. Polling for COMPLETE...", study.name)

    # Poll until COMPLETE
    info_url = f"{WEBAPI_URL}/cohortdefinition/{study.outcome_id}/info"
    deadline = time.time() + WEBAPI_MAX_POLL_SECS
    while time.time() < deadline:
        time.sleep(WEBAPI_POLL_INTERVAL)
        try:
            # Prefer DB polling keyed by source when engine is available.
            if engine is not None:
                with engine.connect() as conn:
                    row = conn.execute(
                        text(
                            """
                            SELECT cgi.start_time, cgi.status, cgi.person_count, cgi.fail_message
                            FROM webapi.cohort_generation_info cgi
                            JOIN webapi.source s ON s.source_id = cgi.source_id
                            WHERE cgi.id = :cohort_id
                              AND s.source_key = :source_key
                            ORDER BY cgi.start_time DESC
                            LIMIT 1
                            """
                        ),
                        {"cohort_id": study.outcome_id, "source_key": study.source_key},
                    ).mappings().first()
                if row and row["start_time"] and row["start_time"] >= triggered_at:
                    status = int(row["status"] or 0)
                    if status == 2:  # COMPLETE
                        count = int(row["person_count"] or 0)
                        logger.info("[%s] Outcome cohort COMPLETE — personCount=%d", study.name, count)
                        return count
                    if status in (3, 4):  # FAILED / ERROR
                        logger.error("[%s] Outcome cohort generation ERROR: %s", study.name, row["fail_message"])
                        return -1
                    continue

            # Fallback to /info when DB polling isn't available.
            info_resp = requests.get(info_url, timeout=15)
            info_resp.raise_for_status()
            entries = info_resp.json()
            matched = [e for e in entries if e.get("sourceKey") == study.source_key]
            if not matched:
                logger.debug("[%s] No matching /info rows yet for source=%s", study.name, study.source_key)
                continue

            for entry in matched:
                status = entry.get("status", "")
                if status == "ERROR":
                    logger.error("[%s] Outcome cohort generation ERROR: %s", study.name, entry)
                    return -1

            completed = [e for e in matched if e.get("status", "") == "COMPLETE"]
            if completed:
                count = max(int(e.get("personCount", 0) or 0) for e in completed)
                logger.info("[%s] Outcome cohort COMPLETE — personCount=%d", study.name, count)
                return count
        except Exception as exc:
            logger.warning("[%s] Poll error: %s", study.name, exc)

    logger.error("[%s] Timed out waiting for cohort regeneration", study.name)
    return -1


# ──────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inject synthetic CV outcome events for Gold vs AI HR benchmarking"
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed (default: 42)")
    parser.add_argument("--treatment-rate", type=float, default=0.25,
                        help="Event rate for treated persons (gold∪AI) (default: 0.25)")
    parser.add_argument("--comparator-rate", type=float, default=0.125,
                        help="Event rate for untreated persons (default: 0.125)")
    parser.add_argument("--studies", nargs="*", default=["LEADER", "PLATO", "ARISTOTLE"],
                        help="Which studies to process (default: all)")
    parser.add_argument("--db-url", default=None,
                        help="PostgreSQL URL (default: DATABASE_URL env)")
    parser.add_argument("--webapi-url", default=None,
                        help="WebAPI base URL (default: WEBAPI_URL env or http://127.0.0.1/WebAPI)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be injected without writing")
    parser.add_argument("--skip-regenerate", action="store_true",
                        help="Skip WebAPI outcome cohort regeneration step")
    parser.add_argument(
        "--clear-webapi-cache",
        action="store_true",
        help="Clear webapi.generation_cache (COHORT) for each source before regeneration.",
    )
    parser.add_argument(
        "--event-window-start-days",
        type=int,
        default=EVENT_WINDOW_START_DAYS,
        help=f"Earliest post-index event day (default: {EVENT_WINDOW_START_DAYS})",
    )
    parser.add_argument(
        "--event-window-end-days",
        type=int,
        default=EVENT_WINDOW_END_DAYS,
        help=f"Latest post-index event day (default: {EVENT_WINDOW_END_DAYS})",
    )
    # Accepted here for interface consistency with calibration tooling.
    parser.add_argument("--target-ci-ratio-low", type=float, default=0.9,
                        help="Lower CI width ratio target (AI/GOLD).")
    parser.add_argument("--target-ci-ratio-high", type=float, default=1.1,
                        help="Upper CI width ratio target (AI/GOLD).")
    parser.add_argument("--max-calibration-iters", type=int, default=6,
                        help="Max calibration iterations for external orchestrators.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    global WEBAPI_URL
    if args.webapi_url:
        WEBAPI_URL = args.webapi_url

    db_url = args.db_url or os.environ["DATABASE_URL"]
    engine = create_engine(db_url)
    rng = np.random.default_rng(args.seed)

    selected_names = {s.upper() for s in args.studies}
    selected = [s for s in STUDIES if s.name in selected_names]
    if not selected:
        logger.error("No matching studies found. Available: %s", [s.name for s in STUDIES])
        sys.exit(1)

    summaries = []
    for study in selected:
        summary = inject_study(
            study, engine, rng,
            treatment_rate=args.treatment_rate,
            comparator_rate=args.comparator_rate,
            event_window_start_days=args.event_window_start_days,
            event_window_end_days=args.event_window_end_days,
            dry_run=args.dry_run,
        )
        if not args.skip_regenerate:
            if args.clear_webapi_cache and not args.dry_run:
                deleted = _clear_webapi_cache(engine, study.source_key)
                logger.info("[%s] Cleared WebAPI cache rows: %d", study.name, deleted)
            outcome_count = regenerate_outcome_cohort(study, engine=engine, dry_run=args.dry_run)
            summary["outcome_cohort_count"] = outcome_count
        summaries.append(summary)

    # ── Print summary table ──────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("INJECTION SUMMARY")
    print("=" * 80)
    header = (f"{'Study':<12} {'CDM N':>7} {'Treated':>8} {'Untreated':>10} "
              f"{'Tx Events':>10} {'Ctrl Events':>12} {'Outcome N':>10}")
    print(header)
    print("-" * 80)
    for s in summaries:
        tx_pct = 100 * s["treated_events"] / max(s["treated"], 1)
        ctrl_pct = 100 * s["untreated_events"] / max(s["untreated"], 1)
        outcome_n = s.get("outcome_cohort_count", "N/A")
        print(
            f"{s['study']:<12} {s['cdm_n']:>7,} {s['treated']:>8,} {s['untreated']:>10,} "
            f"{s['treated_events']:>7,} ({tx_pct:.1f}%) "
            f"{s['untreated_events']:>8,} ({ctrl_pct:.1f}%) "
            f"{str(outcome_n):>10}"
        )
    print("=" * 80)
    if args.dry_run:
        print("DRY RUN — no data was written")
    else:
        print("Injection complete. Run run_gold_vs_ai_comparison.py to compute HR.")
        # That script is DEPRECATED 2026-08-09: its HR is computed on a CDM
        # generated from data/gold/, so it cannot referee pipeline quality.
        # Injection itself is unaffected. See AGENTS.md EVALUATION.
        print("  NOTE: that comparison is deprecated as a quality measure; "
              "see AGENTS.md EVALUATION.")


if __name__ == "__main__":
    main()
