#!/usr/bin/env python3
"""Remap exclusion-side demographic criteria in a COPY of a store, and report what changed.

Why this exists rather than a full regeneration: a fix to the exclusion-demographic
build path (the operator-inversion branch inside ``TTEService._build_demographic_rule``
and its ``op == "eq"`` pre-check in ``_build_seeded_target_circe``) is reached by
exactly the exclusion criteria whose ``domain`` falls in ``DEMOGRAPHIC_DOMAINS``
(``Demographics``/``Demographic``/``Age``/``Gender``/``Race``/``Ethnicity``). Nothing
else in the pipeline is touched by that fix, so regenerating six trials end to end
would re-derive several hundred unchanged concept sets and inclusion rules to observe
a change in a handful of demographic criteria, while mixing in every other commit
landed since the store was built and destroying the attribution.

This rebuilds only the exclusion-demographic rules, through the production mapper
(``TTEService._build_demographic_rule``), so the arm difference is the fix and
nothing else. The input store is never mutated: output goes to --out.

Dependency-free by inspection, not by assumption: ``_build_demographic_rule`` reads
only ``criterion["valueConstraint"]`` (``op``, ``value``) and
``criterion.get("description")``, and returns a plain dict or ``None`` -- no DB
call, no LLM/Agent2 call, no ``criterion_cache`` lookup, no I/O of any kind. This
was confirmed by executing it live against real criteria inside the artemis-api
container, not inferred from reading the guard clause alone. That is also why the
``TTEService.__new__(TTEService)`` no-init pattern below is safe: the method holds
no instance state, so a fully-constructed service is unnecessary.

Two outcomes are NOT "changed" and are reported as distinct skip reasons rather
than folded into a single "unsupported" bucket, mirroring the granularity
``_build_seeded_target_circe``'s own ``_record_skip`` closure uses:

  * ``op == "eq"`` -- CIRCE's Age/NumericRange Op enum has no single-op inversion
    for equality, so an exclusion criterion with ``op == "eq"`` is skipped before
    ``_build_demographic_rule`` is even called (production pre-checks this in the
    caller, not inside the mapper -- this script replicates that pre-check).
  * the mapper itself returns ``None`` -- most commonly because
    ``valueConstraint`` is null or carries no ``value`` (a conceptual criterion
    like "pre-menopausal" or "nursing or pregnant" with no numeric Age/Gender
    value CIRCE's DemographicCriteriaList has a field for). No fix to the
    operator-inversion logic changes this outcome; the criterion is unsupported
    with or without the fix.

Attachment shape (see ``_build_demographic_rule`` and ``_build_grouped_inclusion_rule``
in ``src/services/tte_service.py`` for the production originals this mirrors):

  * ``criterion["groupId"] is None`` -- the rule dict returned by
    ``_build_demographic_rule`` is appended directly to
    ``structuredExpression["InclusionRules"]``.
  * ``criterion["groupId"] is not None`` -- production merges the rule's
    ``DemographicCriteriaList`` into the ONE ``InclusionRules`` entry already built
    for that group's non-demographic siblings, as an additional
    ``{"Type": "ALL", "CriteriaList": [], "DemographicCriteriaList": [...], "Groups": []}``
    entry in that rule's ``expression.Groups[]``, and rebuilds the rule's ``name``
    from the join of all member descriptions (truncated at ``_MAX_RULE_NAME_LENGTH``).
    Re-deriving "which existing InclusionRules entry belongs to this groupId" from a
    store that carries no groupId -> rule-index map is exactly the kind of guess this
    script refuses to make silently: it raises rather than writing a shape nobody has
    validated. If a future store actually exercises this path, that raise is the
    signal to build and validate the grouped-merge logic against a real example --
    not to guess it now against none.

Usage:
    docker exec artemis-api python /app/scripts/remap_exclusion_demographic_drops.py \
        --store /app/tmp/mesh_fix/studies.json \
        --out   /app/tmp/mesh_fix_exclusion_remap/studies.json
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

ARTEMIS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ARTEMIS_DIR))

_MAX_RULE_NAME_LENGTH = 255


def _iter_studies(store: dict | list):
    """:returns: the study dicts in a store, whatever the top-level container is."""
    studies = store if isinstance(store, list) else (store.get("studies") or list(store.values()))
    for study in studies if isinstance(studies, list) else []:
        if isinstance(study, dict):
            yield study


def _demo_op(rule: dict[str, Any]) -> tuple[str, str]:
    """:returns: (demographic key, CIRCE Op) of the single DemographicCriteriaList entry."""
    entry = rule["expression"]["DemographicCriteriaList"][0]
    key = next(iter(entry))
    return key, entry[key]["Op"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", required=True, help="input store JSON; never modified")
    ap.add_argument("--out", required=True, help="output store JSON (remapped)")
    args = ap.parse_args(argv)

    from src.api.models.tte import DEMOGRAPHIC_DOMAINS
    from src.services.tte_service import TTEService

    svc = TTEService.__new__(TTEService)  # the mapper needs no instance state

    store = json.loads(Path(args.store).read_text())
    out_store = copy.deepcopy(store)

    n_found = n_eq_skipped = n_none_skipped = n_changed = 0
    print(f"{'study':26s} {'crit id':>7s}  {'description':42s} {'op before->after':17s} status")
    print("-" * 120)

    for study in _iter_studies(out_store):
        eligibility = study.setdefault("eligibility", {})
        exc_criteria = eligibility.get("exclusionCriteria") or []
        structured = eligibility.setdefault("structuredExpression", {})
        inclusion_rules = structured.setdefault("InclusionRules", [])
        name = str(study.get("name"))[:26]

        for criterion in exc_criteria:
            domain = (criterion.get("domain") or "").strip()
            if domain not in DEMOGRAPHIC_DOMAINS:
                continue

            n_found += 1
            crit_id = criterion.get("id")
            desc = (criterion.get("description") or criterion.get("sourceText") or "").strip()[:42]
            vc = criterion.get("valueConstraint")
            raw_op = (vc.get("op") or "").strip().lower() if vc else None

            # Replicate _build_seeded_target_circe's own op=="eq" pre-check: CIRCE has
            # no single-op inversion for equality, so this is skipped before the mapper
            # is even called, under its own distinct reason.
            if raw_op == "eq":
                n_eq_skipped += 1
                print(f"{name:26s} {str(crit_id):>7s}  {desc:42s} {'eq (unsupported)':17s} SKIP")
                continue

            rule = svc._build_demographic_rule(criterion, exclusion=True)
            if rule is None:
                n_none_skipped += 1
                op_disp = f"{raw_op or 'None'}->None"
                print(f"{name:26s} {str(crit_id):>7s}  {desc:42s} {op_disp:17s} SKIP (build returned None)")
                continue

            _, new_op = _demo_op(rule)
            gid = criterion.get("groupId")
            if gid is None:
                inclusion_rules.append(rule)
                n_changed += 1
                op_disp = f"{raw_op}->{new_op}"
                print(f"{name:26s} {str(crit_id):>7s}  {desc:42s} {op_disp:17s} CHANGED (ungrouped)")
            else:
                # No buildable grouped-exclusion example exists in any known store to
                # validate the merge shape against -- see module docstring. Fail loudly
                # rather than write an unvalidated guess into structuredExpression.
                raise NotImplementedError(
                    f"study id={study.get('id')} criterion id={crit_id} groupId={gid!r}: "
                    "grouped exclusion-demographic attach has no validated example in "
                    "this codebase to build against. Refusing to guess the merge shape "
                    "(see module docstring). Build and validate _build_grouped_inclusion_rule "
                    "handling here against a real example before removing this raise."
                )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_store))
    print("-" * 120)
    print(
        f"demographic exclusion criteria found: {n_found}  "
        f"(eq-unsupported: {n_eq_skipped}, build-returned-None: {n_none_skipped}, changed: {n_changed})"
    )
    print(f"-> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
