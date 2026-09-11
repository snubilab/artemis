#!/usr/bin/env python
"""Read-only census: does every unit a delivery DECLARES actually occur in a CDM?

WHY THIS EXISTS. Circe emits a unit filter as ``AND unit_concept_id IN (...)`` -- an
AND with no fallback and no "or unmapped" form. So a criterion that declares a unit the
target CDM never wrote matches nothing at all, and the failure is silent in the worst
direction: inside an ABSENCE exclusion a rule matching no row stops excluding anybody,
which WIDENS the cohort while the file reads as filtered. Nothing in
``verify_circe_delivery.py`` could see it -- every check there reads the definition, and
this question can only be answered against data.

Three shapes were measured on the 2026-09-13 delivery and they need different answers,
which is why this reports rather than refuses:

  * a retired UCUM spelling. EMPA-REG codeset 17 and CAROLINA codeset 19 declare 720870
    over eGFR; all 13,845 eGFR rows across ajou/donga/keimyung carry 9117, which 720870
    replaced in 2022. Fixed in code -- see ``value_constraint._UNIT_DEPRECATED_FORMS``.
  * a site ETL that mapped no unit. ARISTOTLE codesets 21/22 declare 8876 ``mm[Hg]``,
    which is real and populated in ``synthea_cdm`` (189,933 rows) and absent at all
    three sites because their blood-pressure rows carry ``unit_concept_id = 0``. No
    vocabulary answer exists; the site is what has to change.
  * a deliberate dual-unit OR. CAROLINA codesets 58/59 declare mg/dL and mmol/L over the
    same glucose set. 59 matches 0 rows in ``synthea_cdm`` and that is CORRECT -- the
    branch exists for a CDM that stores SI units.

WHAT THIS CANNOT DO, said plainly. It measures against a CDM that is reachable NOW. The
delivery-target CDM is not: ``data/site_snapshots/*.zip`` carry ACHILLES analysis 1800
(measurement prevalence by concept) and the snapshot contract in
``src/services/site_cdm_adaptation.py`` REQUIRES exactly {200,400,600,700,800,1800}.
1807 (records by concept AND unit) is the analysis that would make this a build-time
gate on the real target; until a snapshot carries it, a verdict here is a verdict about
whichever CDM was named on the command line.

Writes nothing, and issues only ``SELECT``.

Usage:
  python scripts/audit_declared_units.py --delivery output/site_gap/2026-09-13/DELIVERY \\
      --cdm synthea_cdm --cdm ajou_cdm --cdm donga_cdm --cdm keimyung_cdm
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterator

ARTEMIS_DIR = Path(__file__).resolve().parents[1]
if str(ARTEMIS_DIR) not in sys.path:
    sys.path.insert(0, str(ARTEMIS_DIR))

#: CIRCE criteria type -> (CDM table, its concept column). Only the two types that
#: carry a readable ``Unit`` per ``circe_lint.CRITERIA_TYPE_VALUE_ATTRIBUTES`` and a
#: ``unit_concept_id`` column in the CDM. A type outside this map is skipped rather
#: than guessed at.
UNIT_BEARING_TABLES = {
    "Measurement": ("measurement", "measurement_concept_id"),
    "Observation": ("observation", "observation_concept_id"),
}


def walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def closure(cur: Any, vocab_schema: str, items: list[dict[str, Any]]) -> set[int]:
    """Circe's own resolution: descendants of the included items minus the excluded.

    The same shape ``src.services.conceptset_closure`` uses and AGENTS.md pins --
    descendants through ``concept_ancestor`` filtered by ``invalid_reason IS NULL``,
    ``isExcluded`` subtracted as an anti-join.
    """

    def expand(pairs: list[tuple[int, bool]]) -> set[int]:
        out: set[int] = set()
        for concept_id, descend in pairs:
            if not descend:
                out.add(concept_id)
                continue
            cur.execute(
                f"SELECT ca.descendant_concept_id "
                f"FROM {vocab_schema}.concept_ancestor ca "
                f"JOIN {vocab_schema}.concept c ON c.concept_id = ca.descendant_concept_id "
                f"WHERE ca.ancestor_concept_id = %s AND c.invalid_reason IS NULL",
                (concept_id,),
            )
            out |= {row[0] for row in cur.fetchall()}
        return out

    included = [
        (i["concept"]["CONCEPT_ID"], bool(i.get("includeDescendants")))
        for i in items
        if not i.get("isExcluded")
    ]
    excluded = [
        (i["concept"]["CONCEPT_ID"], bool(i.get("includeDescendants")))
        for i in items
        if i.get("isExcluded")
    ]
    return expand(included) - expand(excluded)


def declared_units(path: Path) -> list[tuple[str, int, str, list[int]]]:
    """Every (rule, codeset, criteria type, declared unit ids) in one CIRCE file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    found: list[tuple[str, int, str, list[int]]] = []
    seen: set[tuple[Any, tuple[int, ...]]] = set()
    for rule in payload.get("InclusionRules", []):
        for node in walk(rule.get("expression")):
            for criteria_type, (_table, _column) in UNIT_BEARING_TABLES.items():
                body = node.get(criteria_type)
                if not isinstance(body, dict) or not body.get("Unit"):
                    continue
                units = tuple(u["CONCEPT_ID"] for u in body["Unit"])
                key = (body.get("CodesetId"), units)
                if key in seen:
                    continue
                seen.add(key)
                found.append(
                    (rule.get("name") or "", body.get("CodesetId"), criteria_type, list(units))
                )
    return found


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--delivery", required=True, type=Path, help="dir of *.circe.json")
    parser.add_argument("--dsn", default=None, help="libpq DSN; default settings.DATABASE_URL")
    parser.add_argument("--cdm", action="append", default=None, help="CDM schema (repeatable)")
    parser.add_argument("--vocab-schema", default=None, help="schema holding concept tables")
    args = parser.parse_args()

    import psycopg2

    from src.settings import settings

    dsn = args.dsn or settings.DATABASE_URL
    vocab_schema = args.vocab_schema or settings.CDM_SCHEMA
    cdms = args.cdm or [settings.CDM_SCHEMA]

    files = sorted(args.delivery.glob("*.circe.json"))
    if not files:
        print(f"no *.circe.json under {args.delivery}", file=sys.stderr)
        return 2

    conn = psycopg2.connect(dsn)
    conn.set_session(readonly=True)
    findings = 0
    try:
        with conn.cursor() as cur:
            print(f"delivery={args.delivery}  vocab={vocab_schema}  cdms={', '.join(cdms)}")
            print(
                f"{'file':<32}{'cs':>4} {'rule':<34} {'declared':<18} {'cdm':<14}"
                f"{'set rows':>9}{'unit rows':>10}  observed units"
            )
            for path in files:
                payload = json.loads(path.read_text(encoding="utf-8"))
                sets = {c["id"]: c for c in payload.get("ConceptSets", [])}
                for rule_name, codeset_id, criteria_type, units in declared_units(path):
                    concept_set = sets.get(codeset_id)
                    if concept_set is None:
                        continue
                    ids = closure(cur, vocab_schema, concept_set["expression"]["items"])
                    table, column = UNIT_BEARING_TABLES[criteria_type]
                    if not ids:
                        continue
                    for cdm in cdms:
                        cur.execute(
                            f"SELECT unit_concept_id, COUNT(*) FROM {cdm}.{table} "
                            f"WHERE {column} = ANY(%s) GROUP BY 1 ORDER BY 2 DESC",
                            (list(ids),),
                        )
                        distribution = cur.fetchall()
                        total = sum(n for _, n in distribution)
                        matched = sum(n for unit, n in distribution if unit in units)
                        flag = ""
                        if total > 0 and matched == 0:
                            flag = "   <== DECLARED UNIT MATCHES NO ROW"
                            findings += 1
                        print(
                            f"{path.name:<32}{codeset_id:>4} {rule_name[:34]:<34} "
                            f"{str(units)[:18]:<18} {cdm:<14}{total:>9}{matched:>10}  "
                            f"{distribution[:3]}{flag}"
                        )
            print()
            print(
                f"{findings} (criterion, CDM) pair(s) declare a unit that matches no row "
                f"while the concept set itself has rows. A pair is a finding, not a "
                f"verdict: a dual-unit OR branch is expected to miss in one CDM, and a "
                f"CDM named here may not be a delivery target."
            )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
