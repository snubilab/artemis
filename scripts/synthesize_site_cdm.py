#!/usr/bin/env python3
"""Generate a scaled-down synthetic OMOP CDM whose concept prevalence matches a site.

The local Synthea CDM is clinically nothing like a Korean hospital (zero
empagliflozin prescriptions, for one), so an adapted cohort cannot be exercised
against it. This builds a per-site CDM instead: every concept in the site's
ACHILLES snapshot gets `round(prevalence * N)` distinct persons, sampled
independently. No comorbidity model — the goal is rough prevalence fidelity, not
a joint distribution.

Two things the naive version gets wrong, and how this handles them:

* Events spread uniformly across a 15-year observation period never satisfy the
  relative time windows in a real cohort ("HbA1c within 180 days before index").
  Each person therefore gets a one-year care window and all of their events land
  inside it, which is also how hospital data actually looks.
* Measurements with a NULL value_as_number silently match no value-constrained
  rule, which would make a green run meaningless. Ranges are derived from the
  concept name and skewed toward the normal range via a triangular draw.

Vocabulary tables are exposed as views onto `synthea_cdm` rather than copied;
Circe-generated SQL is schema-qualified, so views satisfy it at no storage cost.

Usage:
    python3 scripts/synthesize_site_cdm.py \
        --snapshot data/site_snapshots/donga.zip --schema donga_cdm \
        --total-persons 1390147 --persons 10000 --seed 42
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import random
import re
import zipfile
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

ANALYSIS_DOMAIN = {
    200: "Visit",
    400: "Condition",
    600: "Procedure",
    700: "Drug",
    800: "Observation",
    1800: "Measurement",
}

DOMAIN_TABLE = {
    "Visit": "visit_occurrence",
    "Condition": "condition_occurrence",
    "Procedure": "procedure_occurrence",
    "Drug": "drug_exposure",
    "Observation": "observation",
    "Measurement": "measurement",
}

VOCABULARY_TABLES = (
    "concept",
    "concept_ancestor",
    "concept_relationship",
    "concept_synonym",
    "concept_class",
    "domain",
    "relationship",
    "vocabulary",
    "source_to_concept_map",
    "drug_strength",
)

# Ajou shipped record counts, not person counts (its export lacks the prevalence
# and records-per-person columns the other two carry). These are the median
# records-per-person of the top count decile in the Dong-A and Keimyung exports,
# used to convert Ajou's record counts back to persons. Head-decile rather than
# overall median because prevalence only matters for common concepts, and the
# long tail of rare concepts drags the overall median to ~1.
PEER_RECORDS_PER_PERSON = {
    "Visit": 14.15,
    "Condition": 6.21,
    "Procedure": 1.89,
    "Drug": 5.09,
    "Observation": 2.90,
    "Measurement": 6.63,
}

# keywords, low, high, mode, unit_concept_id. First keyword match wins, so the
# specific entries ("hemoglobin a1c") must precede the general ones ("hemoglobin").
MEASUREMENT_VALUES: tuple[tuple[tuple[str, ...], float, float, float, int], ...] = (
    (("hemoglobin a1c", "hba1c"), 4.5, 13.0, 6.4, 8554),
    (("body mass index",), 16.0, 45.0, 24.0, 9531),
    (("glomerular filtration",), 15.0, 130.0, 92.0, 9117),
    (("ratio",), 0.2, 3.5, 0.9, 0),
    (("glucose [moles", "glucose [moles/volume]"), 3.0, 18.0, 5.4, 8753),
    (("glucose",), 55.0, 320.0, 98.0, 8840),
    (("aminotransferase", "alkaline phosphatase"), 8.0, 200.0, 26.0, 8645),
    (("creatinine",), 0.3, 4.0, 0.9, 8840),
    (("hemoglobin",), 7.0, 18.0, 13.5, 8713),
    (("cholesterol", "triglyceride"), 40.0, 350.0, 165.0, 8840),
    (("sodium", "potassium", "chloride", "bicarbonate"), 3.0, 150.0, 100.0, 8753),
)
FALLBACK_VALUE = ((), 0.1, 100.0, 20.0, 0)

OBSERVATION_START = date(2010, 1, 1)
OBSERVATION_END = date(2024, 12, 31)
CARE_WINDOW_DAYS = 365
CARE_START_EARLIEST = date(2012, 1, 1)
CARE_START_LATEST = date(2023, 12, 31)

GENDER_CONCEPTS = (8507, 8532)
RACE_CONCEPT = 0
ETHNICITY_CONCEPT = 0
BIRTH_YEAR_RANGE = (1930, 2006, 1958)  # low, high, mode — hospital populations skew older

TYPE_CONCEPTS = {
    "observation_period": 44814724,
    "condition_occurrence": 32020,
    "drug_exposure": 38000177,
    "measurement": 44818702,
    "procedure_occurrence": 38000275,
    "observation": 38000280,
    "visit_occurrence": 32817,
}

COLUMNS = {
    "person": (
        "person_id", "gender_concept_id", "year_of_birth", "month_of_birth",
        "day_of_birth", "race_concept_id", "ethnicity_concept_id", "person_source_value",
    ),
    "observation_period": (
        "observation_period_id", "person_id", "observation_period_start_date",
        "observation_period_end_date", "period_type_concept_id",
    ),
    "condition_occurrence": (
        "condition_occurrence_id", "person_id", "condition_concept_id",
        "condition_start_date", "condition_end_date", "condition_type_concept_id",
    ),
    "drug_exposure": (
        "drug_exposure_id", "person_id", "drug_concept_id", "drug_exposure_start_date",
        "drug_exposure_end_date", "drug_type_concept_id",
    ),
    "measurement": (
        "measurement_id", "person_id", "measurement_concept_id", "measurement_date",
        "measurement_type_concept_id", "value_as_number", "unit_concept_id",
    ),
    "procedure_occurrence": (
        "procedure_occurrence_id", "person_id", "procedure_concept_id",
        "procedure_date", "procedure_type_concept_id",
    ),
    "observation": (
        "observation_id", "person_id", "observation_concept_id", "observation_date",
        "observation_type_concept_id",
    ),
    "visit_occurrence": (
        "visit_occurrence_id", "person_id", "visit_concept_id", "visit_start_date",
        "visit_end_date", "visit_type_concept_id",
    ),
}


def scale_count(count_value: int, total_persons: int, target_persons: int,
                records_per_person: float = 1.0) -> int:
    """Persons to synthesize for one concept, capped at the cohort size."""
    if total_persons <= 0 or count_value <= 0:
        return 0
    prevalence = (count_value / records_per_person) / total_persons
    return min(target_persons, round(prevalence * target_persons))


def route_table(domain: str) -> str | None:
    return DOMAIN_TABLE.get(domain)


def measurement_value(concept_name: str, rng: random.Random) -> tuple[float, int]:
    """Plausible (value, unit_concept_id) for a measurement concept.

    Triangular rather than uniform so that thresholds like "eGFR < 30" or
    "HbA1c >= 10" exclude a realistic minority instead of a third of the cohort.
    """
    name = concept_name.lower()
    for keywords, low, high, mode, unit in MEASUREMENT_VALUES:
        if any(keyword in name for keyword in keywords):
            return round(rng.triangular(low, high, mode), 2), unit
    _, low, high, mode, unit = FALLBACK_VALUE
    return round(rng.triangular(low, high, mode), 2), unit


def read_snapshot(path: Path) -> list[tuple[str, int, int]]:
    """(domain, concept_id, count_value) triples from a normalized snapshot ZIP."""
    with zipfile.ZipFile(path) as archive:
        raw = archive.read("achilles_prevalence.csv").decode("utf-8-sig")
    rows = []
    for row in csv.DictReader(io.StringIO(raw)):
        domain = ANALYSIS_DOMAIN.get(int(row["analysis_id"]))
        if domain is None:
            continue
        rows.append((domain, int(row["stratum_1"]), int(row["count_value"])))
    return rows


def build_persons(target: int, rng: random.Random) -> tuple[list[tuple], list[tuple], list[date]]:
    """Persons, observation periods, and each person's care-window start date."""
    persons, periods, care_starts = [], [], []
    span = (CARE_START_LATEST - CARE_START_EARLIEST).days
    for person_id in range(1, target + 1):
        year = int(rng.triangular(*BIRTH_YEAR_RANGE))
        month, day = rng.randint(1, 12), rng.randint(1, 28)
        persons.append((person_id, rng.choice(GENDER_CONCEPTS), year, month, day,
                        RACE_CONCEPT, ETHNICITY_CONCEPT, f"synthetic-{person_id}"))
        periods.append((person_id, person_id, OBSERVATION_START, OBSERVATION_END,
                        TYPE_CONCEPTS["observation_period"]))
        care_starts.append(CARE_START_EARLIEST + timedelta(days=rng.randint(0, span)))
    return persons, periods, care_starts


def build_event(table: str, event_id: int, person_id: int, concept_id: int,
                event_date: date, concept_name: str, rng: random.Random) -> tuple:
    type_concept = TYPE_CONCEPTS[table]
    if table == "measurement":
        value, unit = measurement_value(concept_name, rng)
        return (event_id, person_id, concept_id, event_date, type_concept, value, unit)
    if table in ("condition_occurrence", "drug_exposure", "visit_occurrence"):
        end = event_date + timedelta(days=rng.randint(1, 30))
        return (event_id, person_id, concept_id, event_date, end, type_concept)
    return (event_id, person_id, concept_id, event_date, type_concept)


def connection_params(database: str) -> dict[str, object]:
    """Credentials from $DATABASE_URL, falling back to the repo .env."""
    url = os.environ.get("DATABASE_URL")
    if not url and ENV_FILE.exists():
        match = re.search(r"^DATABASE_URL\s*=\s*(\S+)", ENV_FILE.read_text(), re.M)
        url = match.group(1).strip("\"'") if match else None
    if not url:
        raise SystemExit("DATABASE_URL not set and not found in .env")
    parsed = urlparse(url)
    return {"host": parsed.hostname or "localhost", "port": parsed.port or 5432,
            "dbname": database, "user": parsed.username, "password": parsed.password}


def create_schema(cursor, schema: str, source_schema: str) -> None:
    cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    cursor.execute(f'CREATE SCHEMA "{schema}"')
    for table in COLUMNS:
        cursor.execute(
            f'CREATE TABLE "{schema}".{table} '
            f'(LIKE "{source_schema}".{table} INCLUDING DEFAULTS)'
        )
    for table in VOCABULARY_TABLES:
        cursor.execute(
            "select 1 from information_schema.tables where table_schema=%s and table_name=%s",
            (source_schema, table),
        )
        if cursor.fetchone():
            cursor.execute(
                f'CREATE VIEW "{schema}".{table} AS SELECT * FROM "{source_schema}".{table}'
            )


def copy_rows(cursor, schema: str, table: str, rows: list[tuple]) -> None:
    if not rows:
        return
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows(rows)
    buffer.seek(0)
    columns = ", ".join(COLUMNS[table])
    cursor.copy_expert(f'COPY "{schema}".{table} ({columns}) FROM STDIN WITH CSV', buffer)


def index_schema(cursor, schema: str) -> None:
    """Only the indexes Circe actually scans on — person_id and concept_id."""
    cursor.execute(f'ALTER TABLE "{schema}".person ADD PRIMARY KEY (person_id)')
    cursor.execute(
        f'CREATE INDEX ON "{schema}".observation_period (person_id)'
    )
    for table, concept_column in (
        ("condition_occurrence", "condition_concept_id"),
        ("drug_exposure", "drug_concept_id"),
        ("measurement", "measurement_concept_id"),
        ("procedure_occurrence", "procedure_concept_id"),
        ("observation", "observation_concept_id"),
        ("visit_occurrence", "visit_concept_id"),
    ):
        cursor.execute(f'CREATE INDEX ON "{schema}".{table} ({concept_column})')
        cursor.execute(f'CREATE INDEX ON "{schema}".{table} (person_id)')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--total-persons", required=True, type=int,
                        help="the site's real person count (prevalence denominator)")
    parser.add_argument("--persons", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--counts-are-records", action="store_true",
                        help="snapshot holds record counts; divide by PEER_RECORDS_PER_PERSON")
    parser.add_argument("--source-schema", default="synthea_cdm",
                        help="schema supplying the CDM DDL and vocabulary tables")
    parser.add_argument("--database", default="postgres")
    args = parser.parse_args()

    import psycopg2  # imported late so the pure logic stays unit-testable without a DB

    rng = random.Random(args.seed)
    snapshot = read_snapshot(args.snapshot)

    connection = psycopg2.connect(**connection_params(args.database))
    connection.autocommit = False
    cursor = connection.cursor()

    concept_ids = sorted({concept_id for _, concept_id, _ in snapshot})
    cursor.execute(
        f'SELECT concept_id, concept_name FROM "{args.source_schema}".concept '
        "WHERE concept_id = ANY(%s)", (concept_ids,)
    )
    names = dict(cursor.fetchall())

    create_schema(cursor, args.schema, args.source_schema)

    persons, periods, care_starts = build_persons(args.persons, rng)
    copy_rows(cursor, args.schema, "person", persons)
    copy_rows(cursor, args.schema, "observation_period", periods)

    pending: dict[str, list[tuple]] = {table: [] for table in DOMAIN_TABLE.values()}
    counters = {table: 0 for table in pending}
    written = {table: 0 for table in pending}
    skipped_unknown = 0

    for domain, concept_id, count_value in snapshot:
        if concept_id not in names:
            skipped_unknown += 1
            continue
        table = route_table(domain)
        if table is None:
            continue
        rpp = PEER_RECORDS_PER_PERSON[domain] if args.counts_are_records else 1.0
        k = scale_count(count_value, args.total_persons, args.persons, rpp)
        if k == 0:
            continue
        for person_id in rng.sample(range(1, args.persons + 1), k):
            counters[table] += 1
            offset = rng.randint(0, CARE_WINDOW_DAYS)
            event_date = care_starts[person_id - 1] + timedelta(days=offset)
            pending[table].append(build_event(
                table, counters[table], person_id, concept_id, event_date,
                names[concept_id], rng,
            ))
        if len(pending[table]) >= 200_000:
            copy_rows(cursor, args.schema, table, pending[table])
            written[table] += len(pending[table])
            pending[table] = []

    for table, rows in pending.items():
        copy_rows(cursor, args.schema, table, rows)
        written[table] += len(rows)

    index_schema(cursor, args.schema)
    connection.commit()
    connection.close()

    print(f"[{args.schema}] persons={args.persons:,} seed={args.seed} "
          f"denominator={args.total_persons:,}")
    print(f"  concepts in snapshot={len(snapshot):,} "
          f"skipped (absent from vocabulary)={skipped_unknown:,}")
    for table in sorted(written):
        print(f"  {table:22s} {written[table]:>10,}")


if __name__ == "__main__":
    main()
