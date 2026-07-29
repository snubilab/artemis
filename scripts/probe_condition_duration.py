#!/usr/bin/env python3
"""ADR-031-A scratch validation: expressing "condition present for >= N days before index" in Circe.

Compiles candidate Circe representations through WebAPI (POST /cohortdefinition/sql, then
POST /sqlrender/translate), runs each against a CDM schema, and prints patient counts.

Nothing is persisted: no WebAPI cohort definition is created or deleted, and cohort rows land
in a session-local pg_temp table that is rolled back.

    cd artemis && .venv/bin/python scripts/probe_condition_duration.py
    cd artemis && .venv/bin/python scripts/probe_condition_duration.py --dump-sql

Requires: artemis/.env (OMOP_DB_*), WebAPI reachable at $WEBAPI_BASE.
Every number quoted in docs/adr/ADR-031-A_Condition_Duration.md comes from this script.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

WEBAPI_BASE = os.environ.get("WEBAPI_BASE", "http://172.19.0.5:8080/WebAPI")
DEFAULT_CDM = "synthea_cdm"
INDEX_FROM = "2018-01-01"  # index = first Outpatient Visit on/after this date

FIVE_YEARS = 1826  # 5 * 365 + 1 leap day
TEN_YEARS = 3652
ONE_MONTH = 30

HIV = {
    "CONCEPT_ID": 439727,
    "CONCEPT_NAME": "Human immunodeficiency virus infection",
    "STANDARD_CONCEPT": "S",
    "CONCEPT_CODE": "86406008",
    "DOMAIN_ID": "Condition",
    "VOCABULARY_ID": "SNOMED",
    "CONCEPT_CLASS_ID": "Clinical Finding",
}
OUTPATIENT = {
    "CONCEPT_ID": 9202,
    "CONCEPT_NAME": "Outpatient Visit",
    "STANDARD_CONCEPT": "S",
    "CONCEPT_CODE": "OP",
    "DOMAIN_ID": "Visit",
    "VOCABULARY_ID": "Visit",
    "CONCEPT_CLASS_ID": "Visit",
}
# Gingivitis is clinically irrelevant here; it is the only synthea_cdm concept with enough
# repeat records per person (up to 46) to make First-vs-any observable at all.
GINGIVITIS = {
    "CONCEPT_ID": 4281516,
    "CONCEPT_NAME": "Gingivitis",
    "STANDARD_CONCEPT": "S",
    "CONCEPT_CODE": "66383009",
    "DOMAIN_ID": "Condition",
    "VOCABULARY_ID": "SNOMED",
    "CONCEPT_CLASS_ID": "Clinical Finding",
}
# ART ingredients actually present in synthea_cdm for the HIV patients.
ART = [
    (1703069, "emtricitabine"),
    (1710281, "tenofovir disoproxil"),
    (1738135, "efavirenz"),
    (43560385, "dolutegravir"),
    (1704183, "lamivudine"),
]


# --------------------------------------------------------------------------- env / http


def load_env(path: str = ".env") -> dict[str, str]:
    env: dict[str, str] = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key] = value.strip().strip('"').strip("'")
    return env


def post_json(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{WEBAPI_BASE}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"WebAPI {path} -> {exc.code}: {exc.read()[:400].decode()}") from exc


# --------------------------------------------------------------------------- circe builders


def concept_set(set_id: int, name: str, concepts: list[dict], descendants: bool = True) -> dict:
    return {
        "id": set_id,
        "name": name,
        "expression": {
            "items": [
                {"concept": c, "includeDescendants": descendants, "isExcluded": False, "includeMapped": False}
                for c in concepts
            ]
        },
    }


HIV_CS = concept_set(0, "HIV", [HIV])
VISIT_CS = concept_set(1, "Outpatient visit", [OUTPATIENT], descendants=False)
GING_CS = concept_set(0, "Gingivitis", [GINGIVITIS], descendants=False)
ART_CS = concept_set(
    2,
    "Antiretroviral therapy",
    [
        {
            "CONCEPT_ID": cid,
            "CONCEPT_NAME": nm,
            "STANDARD_CONCEPT": "S",
            "CONCEPT_CODE": str(cid),
            "DOMAIN_ID": "Drug",
            "VOCABULARY_ID": "RxNorm",
            "CONCEPT_CLASS_ID": "Ingredient",
        }
        for cid, nm in ART
    ],
)


def cohort(inclusion: dict | None, concept_sets: list[dict]) -> dict:
    """Shared skeleton. Index = first Outpatient Visit on/after INDEX_FROM."""
    return {
        "cdmVersionRange": ">=5.0.0",
        "PrimaryCriteria": {
            "CriteriaList": [
                {"VisitOccurrence": {"CodesetId": 1, "OccurrenceStartDate": {"Value": INDEX_FROM, "Op": "gte"}}}
            ],
            "ObservationWindow": {"PriorDays": 0, "PostDays": 0},
            "PrimaryCriteriaLimit": {"Type": "First"},
        },
        "ConceptSets": concept_sets,
        "QualifiedLimit": {"Type": "First"},
        "ExpressionLimit": {"Type": "First"},
        "InclusionRules": [] if inclusion is None else [{"name": "criterion under test", "expression": inclusion}],
        "CensoringCriteria": [],
        "CollapseSettings": {"CollapseType": "ERA", "EraPad": 0},
        "CensorWindow": {},
    }


def rule(criteria: dict, start_window: dict, *, end_window: dict | None = None,
         occurrence: dict | None = None, ignore_op: bool = False) -> dict:
    entry = {
        "Criteria": criteria,
        "StartWindow": start_window,
        "RestrictVisit": False,
        "IgnoreObservationPeriod": ignore_op,
        "Occurrence": occurrence or {"Type": 2, "Count": 1},
    }
    if end_window is not None:
        entry["EndWindow"] = end_window
    return {"Type": "ALL", "CriteriaList": [entry], "DemographicCriteriaList": [], "Groups": []}


def window_duration(days: int) -> dict:
    """(-inf .. index - days].  'started at least `days` before index'."""
    return {"Start": {"Coeff": -1}, "End": {"Days": days, "Coeff": -1}, "UseIndexEnd": False, "UseEventEnd": False}


def window_lookback(days: int) -> dict:
    """[index - days .. index].  'started within the last `days`'  -- the misroute."""
    return {
        "Start": {"Days": days, "Coeff": -1},
        "End": {"Days": 0, "Coeff": 1},
        "UseIndexEnd": False,
        "UseEventEnd": False,
    }


def window_all_prior() -> dict:
    return {"Start": {"Coeff": -1}, "End": {"Days": 0, "Coeff": 1}, "UseIndexEnd": False, "UseEventEnd": False}


def window_still_open() -> dict:
    """EndWindow: event end date on/after index -- 'still ongoing at index'."""
    return {"Start": {"Days": 0, "Coeff": -1}, "End": {"Coeff": 1}, "UseIndexEnd": False, "UseEventEnd": True}


# --------------------------------------------------------------------------- compile + run


def compile_sql(expression: dict, cdm: str) -> str:
    template = post_json(
        "/cohortdefinition/sql", {"expression": expression, "options": {"generateStats": False}}
    )["templateSql"]
    rendered = (
        template.replace("@cdm_database_schema", cdm)
        .replace("@vocabulary_database_schema", cdm)
        .replace("@target_database_schema", "pg_temp")
        .replace("@results_database_schema", "pg_temp")
        .replace("@target_cohort_table", "probe_cohort")
        .replace("@target_cohort_id", "1")
    )
    # SqlRender's WebAPI endpoint uses the key "targetdialect" (all lowercase); "targetDialect"
    # returns HTTP 200 with the SQL untranslated.
    return post_json("/sqlrender/translate", {"SQL": rendered, "targetdialect": "postgresql"})["targetSQL"]


def run_sql(conn, sql: str) -> int:
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS pg_temp.probe_cohort")
    cur.execute(
        "CREATE TEMP TABLE probe_cohort (cohort_definition_id int, subject_id bigint, "
        "cohort_start_date date, cohort_end_date date)"
    )
    for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
        cur.execute(stmt)
    cur.execute("SELECT count(DISTINCT subject_id) FROM pg_temp.probe_cohort")
    n = cur.fetchone()[0]
    conn.rollback()
    return n


def measure(conn, label: str, expression: dict, cdm: str, dump: bool = False) -> None:
    try:
        sql = compile_sql(expression, cdm)
        print(f"  {label:46s} {run_sql(conn, sql):7d}")
        if dump:
            for line in sql.splitlines():
                stripped = line.strip()
                if any(t in stripped for t in (str(FIVE_YEARS), str(ONE_MONTH) + "*INTERVAL", "C.ordinal")):
                    print(f"{'':50s}| {stripped[:130]}")
    except Exception as exc:  # noqa: BLE001 - scratch script, surface everything
        conn.rollback()
        print(f"  {label:46s} {'FAIL':>7s}  {str(exc).strip().splitlines()[0][:90]}")


# --------------------------------------------------------------------------- experiments


def main() -> int:
    import psycopg2

    dump = "--dump-sql" in sys.argv
    env = load_env()
    conn = psycopg2.connect(
        host=env["OMOP_DB_HOST"], port=env["OMOP_DB_PORT"], dbname="postgres",
        user=env["OMOP_DB_USER"], password=env["OMOP_DB_PASS"],
    )
    cur = conn.cursor()
    print(f"WebAPI : {WEBAPI_BASE}")
    print(f"index  : first Outpatient Visit on/after {INDEX_FROM}, PrimaryCriteriaLimit=First\n")

    # -- 1. the representations, on synthea_cdm -------------------------------------------
    print(f"[1] HIV duration >= 5 years, competing representations ({DEFAULT_CDM})")
    cases = [
        ("index cohort only", cohort(None, [VISIT_CS])),
        ("HIV any time on/before index", cohort(rule({"ConditionOccurrence": {"CodesetId": 0}}, window_all_prior()), [HIV_CS, VISIT_CS])),
        ("A  ConditionOccurrence, (-inf, ix-1826d]  <= CHOSEN", cohort(rule({"ConditionOccurrence": {"CodesetId": 0}}, window_duration(FIVE_YEARS)), [HIV_CS, VISIT_CS])),
        ("A' same + First:true", cohort(rule({"ConditionOccurrence": {"CodesetId": 0, "First": True}}, window_duration(FIVE_YEARS)), [HIV_CS, VISIT_CS])),
        ("A'' same + IgnoreObservationPeriod:true", cohort(rule({"ConditionOccurrence": {"CodesetId": 0}}, window_duration(FIVE_YEARS), ignore_op=True), [HIV_CS, VISIT_CS])),
        ("B  lookback [ix-1826d, ix]  (the misroute)", cohort(rule({"ConditionOccurrence": {"CodesetId": 0}}, window_lookback(FIVE_YEARS)), [HIV_CS, VISIT_CS])),
        ("C  ConditionEra EraLength > 1826d (gold idiom)", cohort(rule({"ConditionEra": {"CodesetId": 0, "EraLength": {"Value": FIVE_YEARS, "Op": "gt"}}}, window_all_prior()), [HIV_CS, VISIT_CS])),
        ("C' ConditionEra, (-inf, ix-1826d]", cohort(rule({"ConditionEra": {"CodesetId": 0}}, window_duration(FIVE_YEARS)), [HIV_CS, VISIT_CS])),
    ]
    for label, expr in cases:
        measure(conn, label, expr, DEFAULT_CDM, dump)

    # -- 2. First semantics need a multi-record concept -----------------------------------
    print("\n[2] First semantics -- Gingivitis (up to 46 records/person; HIV has exactly 1)")
    for label, win, first in [
        ("duration >=5y, any occurrence", window_duration(FIVE_YEARS), False),
        ("duration >=5y, First:true", window_duration(FIVE_YEARS), True),
        ("lookback <=5y, any occurrence", window_lookback(FIVE_YEARS), False),
        ("lookback <=5y, First:true", window_lookback(FIVE_YEARS), True),
    ]:
        crit = {"CodesetId": 0} | ({"First": True} if first else {})
        measure(conn, label, cohort(rule({"ConditionOccurrence": crit}, win), [GING_CS, VISIT_CS]), DEFAULT_CDM)

    # -- 3. drug analogue: "on ART > 1 month" ---------------------------------------------
    print("\n[3] Drug analogue -- 'on antiretroviral therapy > 1 month'")
    for label, expr in [
        ("D1 DrugEra EraLength > 30d, era starts <= ix", rule({"DrugEra": {"CodesetId": 2, "EraLength": {"Value": ONE_MONTH, "Op": "gt"}}}, window_all_prior())),
        ("D2 DrugExposure, (-inf, ix-30d]", rule({"DrugExposure": {"CodesetId": 2}}, window_duration(ONE_MONTH))),
        ("D3 DrugEra starts <= ix-30d AND open at ix  <= CHOSEN", rule({"DrugEra": {"CodesetId": 2}}, window_duration(ONE_MONTH), end_window=window_still_open())),
        ("D4 DrugEra EraLength > 30d AND open at ix", rule({"DrugEra": {"CodesetId": 2, "EraLength": {"Value": ONE_MONTH, "Op": "gt"}}}, window_all_prior(), end_window=window_still_open())),
    ]:
        measure(conn, label, cohort(expr, [ART_CS, VISIT_CS]), DEFAULT_CDM)

    # -- 4. the same JSON across site CDMs ------------------------------------------------
    print("\n[4] Identical JSON, different sites -- the silent-zero surface")
    for cdm in ("synthea_cdm", "synthea_cdm_benchmark", "ajou_cdm", "keimyung_cdm", "donga_cdm"):
        print(f"  -- {cdm}")
        measure(conn, "    A  HIV >= 5y before index", cohort(rule({"ConditionOccurrence": {"CodesetId": 0}}, window_duration(FIVE_YEARS)), [HIV_CS, VISIT_CS]), cdm)
        measure(conn, "    A  HIV >= 10y before index", cohort(rule({"ConditionOccurrence": {"CodesetId": 0}}, window_duration(TEN_YEARS)), [HIV_CS, VISIT_CS]), cdm)
        measure(conn, "       HIV any time on/before index", cohort(rule({"ConditionOccurrence": {"CodesetId": 0}}, window_all_prior()), [HIV_CS, VISIT_CS]), cdm)
        measure(conn, "    C  ConditionEra EraLength > 1826d", cohort(rule({"ConditionEra": {"CodesetId": 0, "EraLength": {"Value": FIVE_YEARS, "Op": "gt"}}}, window_all_prior()), [HIV_CS, VISIT_CS]), cdm)

    # -- 5. the reviewer's denominator ----------------------------------------------------
    print("\n[5] Reviewer check: does observation history even reach back that far?")
    print(f"  {'cdm':24s} {'index_n':>8s} {'>=5y':>12s} {'>=10y':>12s}")
    for cdm in ("synthea_cdm", "synthea_cdm_benchmark", "ajou_cdm", "keimyung_cdm", "donga_cdm"):
        try:
            cur.execute(f"""
                WITH idx AS (SELECT person_id, min(visit_start_date) ix FROM {cdm}.visit_occurrence
                             WHERE visit_concept_id = 9202 AND visit_start_date >= %s GROUP BY 1)
                SELECT count(*),
                       sum(CASE WHEN idx.ix - op.observation_period_start_date >= %s THEN 1 ELSE 0 END),
                       sum(CASE WHEN idx.ix - op.observation_period_start_date >= %s THEN 1 ELSE 0 END)
                FROM idx JOIN {cdm}.observation_period op USING (person_id)""",
                (INDEX_FROM, FIVE_YEARS, TEN_YEARS))
            n, r5, r10 = cur.fetchone()
            pct = lambda x: f"{x} ({100 * x / n:.1f}%)" if n else "-"  # noqa: E731
            print(f"  {cdm:24s} {n:8d} {pct(r5 or 0):>12s} {pct(r10 or 0):>12s}")
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            print(f"  {cdm:24s} FAIL  {str(exc).strip().splitlines()[0][:70]}")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
