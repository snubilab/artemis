#!/usr/bin/env python3
"""Re-map each study's entry-drug concept set in a COPY of a store, and report what moved.

Why this exists rather than a full regeneration: 991c11c changed one gate, and that
gate is reached by exactly one concept set per study -- the PrimaryCriteria drug that
``_build_seeded_target_circe`` maps from ``targetCohortName`` with no
``expected_domain``. Nothing else in the pipeline is affected, so regenerating six
trials (hours on the local vLLM) would re-derive ~370 unchanged concept sets to observe
a change in 2 of them, while mixing in every other commit landed since the store was
built and destroying the attribution.

This rebuilds only the entry set, through the production mapper
(``TTEService._recommend_seeded_concept_set``), so the arm difference is the gate and
nothing else. The input store is never mutated: output goes to --out.

Seeds that have no unique standard RxNorm Ingredient (investigational codes such as
'BI 10773') fall through to the embedding path exactly as in production, and are
reported as unchanged rather than silently skipped.

Usage:
    DATABASE_URL=postgresql://postgres:mypass@localhost:5432/postgres \
    CDM_SCHEMA=synthea_cdm \
    python3 scripts/rebuild_entry_concept_sets.py \
        --store tmp/tte_six_deliver/studies.json \
        --out   tmp/tte_six_arm_a/studies.json
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ARTEMIS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ARTEMIS_DIR))


def _iter_studies(store: dict | list):
    """:returns: the study dicts in a store, whatever the top-level container is."""
    studies = store if isinstance(store, list) else (store.get("studies") or list(store.values()))
    for study in studies if isinstance(studies, list) else []:
        if isinstance(study, dict):
            yield study


def _items(concept_set: dict) -> list[tuple[int, str]]:
    """:returns: (concept_id, concept_name) pairs of a concept set, for reporting."""
    return [
        (i.get("concept", {}).get("CONCEPT_ID"), i.get("concept", {}).get("CONCEPT_NAME"))
        for i in (concept_set.get("expression") or {}).get("items", [])
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", required=True, help="input store JSON; never modified")
    ap.add_argument("--out", required=True, help="output store JSON (arm A)")
    args = ap.parse_args(argv)

    from src.services.tte_service import TTEService

    svc = TTEService.__new__(TTEService)  # the mapper needs no instance state

    store = json.loads(Path(args.store).read_text())
    out_store = copy.deepcopy(store)

    changed = unchanged = 0
    print(f"{'study':34s} {'target':16s} before -> after")
    print("-" * 110)
    for study in _iter_studies(out_store):
        eligibility = study.get("eligibility") or {}
        structured = eligibility.get("structuredExpression") or {}
        concept_sets = structured.get("ConceptSets") or []
        target = (eligibility.get("targetCohortName") or "").strip()
        if not target or not concept_sets:
            continue

        entry = concept_sets[0]
        before = _items(entry)
        mapped = svc._exact_ingredient_mapping(target)
        name = str(study.get("name"))[:32]

        if mapped is None:
            unchanged += 1
            print(f"{name:34s} {target:16s} {before} -> (no unique ingredient; embedding path kept)")
            continue

        after = _items({"expression": mapped["expression"]})
        if before == after:
            unchanged += 1
            print(f"{name:34s} {target:16s} {before} -> unchanged")
            continue

        entry["name"] = mapped["name"]
        entry["expression"] = copy.deepcopy(mapped["expression"])
        changed += 1
        print(f"{name:34s} {target:16s} {before} -> {after}   CHANGED")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_store))
    print("-" * 110)
    print(f"changed {changed}, unchanged {unchanged}  ->  {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
