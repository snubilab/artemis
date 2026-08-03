#!/usr/bin/env python3
"""Register the exported circe-be in WebAPI, generate, and report attrition.

Takes the circe JSON written by the six-study run, creates a cohort definition
per study, generates it against that study's benchmark source, and prints the
patient count next to the per-rule attrition. The attrition is the point: a
cohort that returns zero says nothing on its own, and the rule-level counts say
which criterion emptied it — that is how ARISTOTLE's four running-header rules
were found.

Per-study source. ARISTOTLE, PLATO and LEADER have dedicated benchmark CDMs;
the three diabetes trials fall back to SYNTHEA_CDM_BENCHMARK, which was not
built for them, so their counts are weaker evidence and are labelled as such.

Usage:
    python3 scripts/register_and_generate_circe.py                # all six
    python3 scripts/register_and_generate_circe.py --studies 3,2  # a subset
    python3 scripts/register_and_generate_circe.py --dry-run      # register only

Generation runs against a live WebAPI and writes cohort definitions. Nothing is
deleted; each run creates new definition ids.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ARTEMIS_DIR = Path(__file__).resolve().parent.parent
CIRCE_DIR = ARTEMIS_DIR / "output" / "circe_be" / "2026-08-03"
sys.path.insert(0, str(ARTEMIS_DIR))

# study id -> (name, nct, circe file stem, WebAPI source key, dedicated benchmark?)
STUDIES = {
    3: ("ARISTOTLE", "NCT00412984", "ARISTOTLE_BENCHMARK", True),
    2: ("PLATO", "NCT00391872", "PLATO_BENCHMARK", True),
    1: ("LEADER", "NCT01179048", "LEADER_BENCHMARK", True),
    10: ("CAROLINA", "NCT01243424", "SYNTHEA_CDM_BENCHMARK", False),
    8: ("EMPA-REG", "NCT01131676", "SYNTHEA_CDM_BENCHMARK", False),
    9: ("CARMELINA", "NCT01897532", "SYNTHEA_CDM_BENCHMARK", False),
}


def _psql(sql: str) -> list[list]:
    """Run a read query against the WebAPI database.

    Uses psycopg2 rather than `docker exec psql` so the script runs inside the
    `artemis-api` container, which is where WebAPI is reachable.

    :param sql: a single SELECT.
    :returns: rows as lists.
    """
    import psycopg2

    from src.settings import settings

    conn = psycopg2.connect(settings.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            return [list(row) for row in cur.fetchall()]
    finally:
        conn.close()


def schemas_for(source_key: str) -> tuple[int, str]:
    """Source id and results schema for a source key.

    :param source_key: e.g. "ARISTOTLE_BENCHMARK".
    :returns: (source_id, results_schema).
    """
    rows = _psql(f"""
        SELECT s.source_id,
               MAX(CASE WHEN sd.daimon_type = 2 THEN sd.table_qualifier END)
        FROM webapi.source s
        JOIN webapi.source_daimon sd ON sd.source_id = s.source_id
        WHERE s.source_key = '{source_key}'
        GROUP BY s.source_id;
    """)
    if not rows:
        raise SystemExit(f"no such source: {source_key}")
    return int(rows[0][0]), rows[0][1]


def attrition(results_schema: str, generation_id: int) -> list[tuple[int, str, int]]:
    """Per-rule person counts for a generated cohort.

    :param results_schema: the source's results schema.
    :param generation_id: the cohort definition id that was generated.
    :returns: (rule_sequence, rule_name, person_count), ordered.
    """
    rows = _psql(f"""
        SELECT DISTINCT s.rule_sequence, COALESCE(LEFT(i.name, 54), '?'), s.person_count
        FROM {results_schema}.cohort_inclusion_stats s
        LEFT JOIN {results_schema}.cohort_inclusion i
          ON i.cohort_definition_id = s.cohort_definition_id
         AND i.rule_sequence = s.rule_sequence
        WHERE s.cohort_definition_id = {generation_id}
        ORDER BY 1;
    """)
    return [(int(r[0]), r[1], int(r[2])) for r in rows]


def summary(results_schema: str, generation_id: int) -> tuple[int, int]:
    """Base and final counts for a generated cohort.

    :returns: (base_count, final_count); (-1, -1) when no row exists.
    """
    rows = _psql(f"""
        SELECT base_count, final_count
        FROM {results_schema}.cohort_summary_stats
        WHERE cohort_definition_id = {generation_id} LIMIT 1;
    """)
    return (int(rows[0][0]), int(rows[0][1])) if rows else (-1, -1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--studies", default="", help="comma-separated study ids; default all")
    ap.add_argument("--dry-run", action="store_true", help="register but do not generate")
    ap.add_argument("--circe-dir", default=str(CIRCE_DIR),
                    help="where the circe JSON lives; /app/output is not mounted in the "
                         "container, so pass a path under /app/tmp when running there")
    args = ap.parse_args()

    wanted = {int(x) for x in args.studies.split(",") if x.strip()} or set(STUDIES)
    unknown = wanted - set(STUDIES)
    if unknown:
        raise SystemExit(f"unknown study ids {sorted(unknown)}; known {sorted(STUDIES)}")

    from src.pipeline.webapi_client import WebAPIClient

    circe_dir = Path(args.circe_dir)
    if not circe_dir.is_dir():
        raise SystemExit(f"no circe directory at {circe_dir}")

    results = []
    for sid in sorted(wanted):
        name, nct, source_key, dedicated = STUDIES[sid]
        path = next(circe_dir.glob(f"{name}_*_circe.json"), None)
        if path is None:
            print(f"{name}: no circe file in {circe_dir}", file=sys.stderr)
            continue
        circe = json.loads(path.read_text())
        source_id, results_schema = schemas_for(source_key)

        print(f"\n=== {name} (study {sid}, {nct}) ===", flush=True)
        print(f"  source     : {source_key} (id {source_id})"
              f"{'' if dedicated else '   [generic benchmark, weaker evidence]'}")
        print(f"  circe      : ConceptSets={len(circe.get('ConceptSets') or [])} "
              f"InclusionRules={len(circe.get('InclusionRules') or [])}", flush=True)

        client = WebAPIClient(source_key=source_key)
        created = client.create_cohort_definition(
            name=f"ARTEMIS {name} eligibility 2026-08-03",
            expression=circe,
            description=f"Generated from {path.name} by the six-study run",
        )
        cohort_id = created["id"] if isinstance(created, dict) else created
        print(f"  definition : {cohort_id}", flush=True)

        if args.dry_run:
            results.append((name, cohort_id, None, None))
            continue

        client.start_generation(cohort_id)
        client._wait_for_generation(cohort_id)
        base, final = summary(results_schema, cohort_id)
        print(f"  patients   : base {base:,} -> final {final:,}", flush=True)

        rules = attrition(results_schema, cohort_id)
        zeros = [r for r in rules if r[2] == 0]
        print(f"  rules      : {len(rules)} total, {len(zeros)} matching zero people")
        for seq, rname, cnt in zeros[:12]:
            print(f"      [{seq:>3}] {cnt:>7}  {rname}")
        results.append((name, cohort_id, final, len(zeros)))

    print("\n" + "=" * 62)
    print(f"{'study':<12}{'definition':>11}{'patients':>10}{'zero rules':>12}")
    print("-" * 62)
    for name, cid, final, zeros in results:
        print(f"{name:<12}{cid:>11}{('-' if final is None else f'{final:,}'):>10}"
              f"{('-' if zeros is None else zeros):>12}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
