#!/usr/bin/env python3
"""Build the dose-form route dictionary from OMOP, and report what it misses.

An eligibility criterion that says "systemic corticosteroids" becomes a concept
set of RxNorm Ingredients with includeDescendants, which is every form of the
drug -- creams, eye drops, inhalers included. OMOP carries the route
structurally via `RxNorm has dose form`, and the whole vocabulary holds only
~780 dose forms, so classifying those once gives every drug product its route
through one join.

This writes ``data/vocab/dose_form_routes.json`` and prints coverage twice:

- by form, which flatters the result, since most unclassified names are rare
- **by usage**, weighting each form by how many drug products actually link to
  it. That is the number that says whether the dictionary is usable

Unclassified forms are written out with ``systemic: null`` and listed in the
report rather than defaulted. A name like "Powder" states no route; guessing
oral for it would repeat the substitution this dictionary exists to stop.

Usage:
    python3 scripts/build_dose_form_routes.py [--schema omop_vocab] [--check]

``--check`` rebuilds in memory and exits non-zero if the file on disk differs,
for CI after a vocabulary refresh.

See omx_wiki/route-of-administration-overreach.md.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.dose_form_route import classify_dose_form  # noqa: E402

ARTEMIS_DIR = Path(__file__).resolve().parent.parent
OUT_PATH = ARTEMIS_DIR / "data" / "vocab" / "dose_form_routes.json"
PG_CONTAINER = "broadsea-atlasdb"


def _psql(sql: str) -> list[list[str]]:
    """Run SQL in the vocabulary database and return tab-split rows.

    :param sql: a single statement.
    :returns: rows as lists of strings, header suppressed.
    """
    proc = subprocess.run(
        ["docker", "exec", PG_CONTAINER, "psql", "-U", "postgres", "-d", "postgres",
         "-tAF\t", "-c", sql],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"psql failed: {proc.stderr.strip()}")
    return [line.split("\t") for line in proc.stdout.splitlines() if line.strip()]


def build(schema: str) -> dict:
    """Classify every dose form in the vocabulary and weight it by usage.

    :param schema: the OMOP vocabulary schema, e.g. "omop_vocab".
    :returns: the dictionary payload, ready to serialise.
    """
    forms = _psql(f"""
        SELECT c.concept_id, c.concept_class_id, c.concept_name,
               COALESCE(u.n, 0) AS usage_count
        FROM {schema}.concept c
        LEFT JOIN (
            SELECT cr.concept_id_2 AS form_id, COUNT(*) AS n
            FROM {schema}.concept_relationship cr
            WHERE cr.relationship_id = 'RxNorm has dose form'
              AND cr.invalid_reason IS NULL
            GROUP BY cr.concept_id_2
        ) u ON u.form_id = c.concept_id
        WHERE c.concept_class_id IN ('Dose Form', 'Dose Form Group')
          AND c.invalid_reason IS NULL
        ORDER BY c.concept_name, c.concept_id;
    """)

    entries = []
    for concept_id, concept_class, name, usage in forms:
        result = classify_dose_form(name)
        entries.append({
            "conceptId": int(concept_id),
            "conceptClass": concept_class,
            "name": name,
            "routes": sorted(result.routes),
            "systemic": result.systemic,
            "usageCount": int(usage),
        })

    classified = [e for e in entries if e["systemic"] is not None]
    unknown = [e for e in entries if e["systemic"] is None]
    total_usage = sum(e["usageCount"] for e in entries)
    known_usage = sum(e["usageCount"] for e in classified)

    return {
        "schema": schema,
        "sourceRelationship": "RxNorm has dose form",
        "counts": {
            "doseForms": len(entries),
            "classified": len(classified),
            "unknownRoute": len(unknown),
            "usageTotal": total_usage,
            "usageClassified": known_usage,
        },
        "routeHistogram": dict(Counter(r for e in entries for r in e["routes"]).most_common()),
        "doseForms": entries,
    }


def report(payload: dict) -> None:
    """Print form-level and usage-weighted coverage, and the unclassified tail."""
    c = payload["counts"]
    by_form = c["classified"] / c["doseForms"] * 100 if c["doseForms"] else 0
    by_usage = c["usageClassified"] / c["usageTotal"] * 100 if c["usageTotal"] else 0
    print(f"dose forms          : {c['doseForms']}")
    print(f"  classified        : {c['classified']} ({by_form:.1f}% by form)")
    print(f"  unknown route     : {c['unknownRoute']}")
    print(f"drug-product links  : {c['usageTotal']:,}")
    print(f"  covered           : {c['usageClassified']:,} ({by_usage:.1f}% by usage)")
    print("\nroutes:", ", ".join(f"{k}={v}" for k, v in payload["routeHistogram"].items()))

    tail = sorted((e for e in payload["doseForms"] if e["systemic"] is None),
                  key=lambda e: -e["usageCount"])
    used = [e for e in tail if e["usageCount"] > 0]
    print(f"\nunclassified forms that drugs actually use: {len(used)} of {len(tail)}")
    for e in used[:15]:
        print(f"   {e['usageCount']:>8,}  {e['name']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", default="omop_vocab")
    ap.add_argument("--check", action="store_true",
                    help="fail if the file on disk differs from a fresh build")
    args = ap.parse_args()

    payload = build(args.schema)
    serialised = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    if args.check:
        if not OUT_PATH.exists():
            print(f"MISSING {OUT_PATH}", file=sys.stderr)
            return 1
        if OUT_PATH.read_text() != serialised:
            print(f"STALE {OUT_PATH} — rerun without --check", file=sys.stderr)
            return 1
        print(f"up to date: {OUT_PATH}")
        return 0

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(serialised)
    report(payload)
    print(f"\nwrote {OUT_PATH} ({OUT_PATH.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
