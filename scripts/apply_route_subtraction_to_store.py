#!/usr/bin/env python3
"""Apply route subtraction to a store's already-built concept sets.

The subtraction normally runs inside `_recommend_seeded_concept_set`, during
mapping. Re-running mapping to pick it up would also re-roll the concept
selection itself, which is not deterministic -- the six-study run produced
EMPA-REG's liver criterion six times over from one sentence. This applies the
same `TTEService._apply_route_subtraction` to the concept sets already chosen,
so the only change is the isExcluded tail.

Writes to a new store path; the input is never modified.

Usage:
    python scripts/apply_route_subtraction_to_store.py \
        --in /app/tmp/tte_six_fixed/studies.json \
        --out /app/tmp/tte_six_routed/studies.json

See omx_wiki/route-of-administration-overreach.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ARTEMIS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ARTEMIS_DIR))

STUDY_NAMES = {3: "ARISTOTLE", 2: "PLATO", 10: "CAROLINA",
               8: "EMPA-REG", 9: "CARMELINA", 1: "LEADER"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    args = ap.parse_args()

    from src.services.route_qualifier import detect_route_qualifiers
    from src.services.route_subtraction import routes_to_keep
    from src.services.tte_service import TTEService
    from src.services.tte_store import TTEStore

    service = TTEService(TTEStore(args.src))
    data = json.loads(Path(args.src).read_text())

    total_added = 0
    for study in data["studies"]:
        name = STUDY_NAMES.get(study["id"])
        if not name:
            continue
        elig = study.get("eligibility") or {}
        expr = elig.get("structuredExpression")
        if not expr:
            continue
        if isinstance(expr, str):
            expr = json.loads(expr)
        sets_by_id = {cs.get("id"): cs for cs in (expr.get("ConceptSets") or [])}

        for key in ("inclusionCriteria", "exclusionCriteria"):
            for criterion in elig.get(key) or []:
                if (criterion.get("domain") or "") != "Drug":
                    continue
                text = " ".join(
                    ((criterion.get("description") or "") + " "
                     + (criterion.get("sourceText") or "")).split()
                )
                if not routes_to_keep(detect_route_qualifiers(text)):
                    continue
                concept_set = sets_by_id.get(criterion.get("conceptSetId"))
                if concept_set is None:
                    print(f"  {name}: '{text[:44]}' has no concept set — skipped")
                    continue

                items = (concept_set.get("expression") or {}).get("items") or []
                before = len(items)
                service._apply_route_subtraction(items, text, "Drug")
                added = len(items) - before
                total_added += added
                print(f"  {name}: conceptSet {concept_set.get('id')} "
                      f"'{text[:40]}' {before} -> {len(items)} items (+{added} excluded)")

        elig["structuredExpression"] = expr

    out = Path(args.dst)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False))
    print(f"\n{total_added} exclusion items added; wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
