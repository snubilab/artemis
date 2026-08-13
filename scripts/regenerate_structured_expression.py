#!/usr/bin/env python3
"""Rewrite the stored structuredExpression for the canonical Gold studies (D3-b).

The ADR-031 fix lives in `build_measurement_value_filter`, and the A/B that proved
it assembled both arms in memory. The artifacts on disk were never rewritten, so
the six studies a reader opens in the service still carry the original defect:

    EMPA-REG   RangeHighRatio=0  ValueAsNumber=8
    CARMELINA  RangeHighRatio=0  ValueAsNumber=7

Their `x ULN` criteria therefore still compile to `ValueAsNumber {Value: 3.0}` — an
absolute 3 U/L that essentially every patient exceeds, which excluded 2,841 of
2,841 patients where 24 was correct.

This calls the same service path the API calls, so concept sets are rebuilt rather
than patched. Patching the fragments in place would be cheaper, but a stored Circe
criterion carries only a CodesetId, so matching one back to its source criterion is
guesswork — and a wrong match here silently changes a cohort.

Cost note: mapping goes through the criterion cache, whose key includes LLM_MODEL.
Run with the model the benchmark queue is currently serving and the cache is warm,
so this adds little load to a busy GPU. Run it with a different model and it
re-maps everything.

    docker exec -e LLM_MODEL=vllm/<served-model> artemis-api \
        python /app/scripts/regenerate_structured_expression.py --apply

Without --apply it reports what would change and writes nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ARTEMIS_DIR = Path(__file__).resolve().parents[1]
if str(ARTEMIS_DIR) not in sys.path:
    sys.path.insert(0, str(ARTEMIS_DIR))

STUDIES: dict[int, str] = {
    8: "EMPA-REG OUTCOME",
    9: "CARMELINA",
    1: "LEADER",
    2: "PLATO",
    3: "ARISTOTLE",
    10: "CAROLINA",
}

VALUE_KEYS = ("RangeHighRatio", "RangeLowRatio", "ValueAsNumber", "Unit")


def walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def counts(circe: Any) -> dict[str, int]:
    out = {key: 0 for key in VALUE_KEYS}
    for node in walk(circe):
        for key in out:
            if key in node:
                out[key] += 1
    return out


def alias_terms_for(study: dict) -> list[str]:
    """The trial's MeSH intervention terms as the entry-drug mapper expects them.

    Production reads exactly this field and hands it to the mapper as
    ``alias_candidates``; without it a development-code target ('BI 10773') has
    no way to reach its ingredient and falls through to embedding search.

    :param study: A study record from the TTE store.
    :returns: The MeSH terms, or an empty list when the store carries none.
    """
    return list((study.get("trialMetadata") or {}).get("interventionMeshTerms") or [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write the result back")
    parser.add_argument("--studies", default="", help="Comma-separated ids (default: all six)")
    args = parser.parse_args()

    store_path = Path(os.environ.get("TTE_STORE_PATH") or "/app/tmp/tte/studies.json")
    if not store_path.exists():
        raise SystemExit(f"No store at {store_path}")

    selected = STUDIES
    if args.studies:
        wanted = [int(p) for p in args.studies.split(",") if p.strip()]
        selected = {sid: STUDIES[sid] for sid in wanted if sid in STUDIES}

    if args.apply:
        # A dated copy, not an overwrite. This is live service data.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = store_path.with_name(f"{store_path.stem}.pre-d3b-{stamp}.json")
        shutil.copy2(store_path, backup)
        print(f"backup: {backup}")

    from src.services.tte_service import TTEService
    from src.services.tte_store import TTEStore

    service = TTEService(TTEStore(str(store_path)))
    model = os.environ.get("LLM_MODEL", "unset")
    print(f"model: {model}   apply: {args.apply}\n")

    changed = 0
    without_aliases: list[str] = []
    for study_id, name in selected.items():
        study = service.store.get_study(study_id)
        eligibility = study.get("eligibility") or {}
        before = counts(eligibility.get("structuredExpression") or {})

        # Fresh copy: _build_seeded_target_circe pops keys off its input.
        draft = json.loads(json.dumps(eligibility))
        # Production injects the trial's MeSH intervention terms right here
        # (tte_service._process_eligibility, the `_interventionAliases` assignment)
        # and _build_seeded_target_circe pops them again inside the entry-drug
        # mapper. Skipping it ran this harness with alias_candidates=None, which
        # silently disables the MeSH path for a development-code target: EMPA-REG's
        # 'BI 10773' then fell through to embedding search and its target arm came
        # back as HIV and cystic-fibrosis drugs. The benchmark must exercise the
        # same path production does.
        mesh_terms = alias_terms_for(study)
        if mesh_terms:
            draft["_interventionAliases"] = mesh_terms
        else:
            without_aliases.append(name)

        circe = service._build_seeded_target_circe(draft)
        after = counts(circe)

        moved = after["RangeHighRatio"] - before["RangeHighRatio"]
        print(f"{name:<20} RHR {before['RangeHighRatio']} -> {after['RangeHighRatio']}   "
              f"VAN {before['ValueAsNumber']} -> {after['ValueAsNumber']}   "
              f"Unit {before['Unit']} -> {after['Unit']}"
              f"{'   <- ratio recovered' if moved > 0 else ''}")

        if args.apply:
            eligibility["structuredExpression"] = circe
            service.store.update_study(study_id, {"eligibility": eligibility})
            changed += 1

    if without_aliases:
        # Loud, not a footnote: a run without aliases measures a different pipeline
        # than production runs, and the difference only shows on code-named drugs.
        print(f"\n!! {len(without_aliases)} studies carry no trialMetadata."
              f"interventionMeshTerms, so the MeSH alias path was INACTIVE for them:")
        for name in without_aliases:
            print(f"     {name}")
        print("   Backfill with scripts/backfill_intervention_mesh_terms.py before "
              "trusting an entry-drug result from this run.")

    print(f"\n{'written' if args.apply else 'dry run'}: {changed} studies")
    if not args.apply:
        print("re-run with --apply to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
