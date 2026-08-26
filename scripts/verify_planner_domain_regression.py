"""SPEC-INFRA-007 M2B/M6: Planner domain-classification regression harness
(REQ-003, REQ-008's domain-diff half).

Not a pytest test -- an operator script, matching test_corpus_regression.py's
own "contract" convention. `test_corpus_regression.py` asserts only Agent 1's
PDF-extraction counts and never invokes the Planner (plan-audit D1), so it
cannot verify REQ-003 on its own; this script is what actually re-runs the
Planner's decomposition and diffs domain assignments before/after this SPEC's
fix.

Composite key (plan.md M2B -- NOT `criterion_id`, which does not exist on the
`Criteria` model, ir.py:66-99):

    (study, cohort_label, rule_type, parent_key, sub_key)

    cohort_label := "target"   -- the persisted evidence store's eligibility
                                  structure exposes one unified criteria list
                                  per study, not a separately-modeled
                                  comparator-cohort criteria set; this is
                                  disclosed rather than silently assumed
    rule_type    := "inclusion" | "exclusion"
    parent_key   := (position_in_rule_list, parent.entity_text or parent.name)
    sub_key      := None                                       -- atomic, OR
                  := (sub_index, sub.entity_text or sub.name)   -- decomposed

Usage:
    python scripts/verify_planner_domain_regression.py --corpus <export.json> --out <baseline.json>
    python scripts/verify_planner_domain_regression.py --corpus <export.json> --diff <baseline.json>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.planner.decomposer import CriteriaPlanner  # noqa: E402
from src.models.ir import Criteria  # noqa: E402


def _run_corpus(corpus: dict) -> dict[str, dict]:
    """Decompose every top-level criterion in the corpus export; return a
    flat dict keyed by the composite key (JSON-encoded), valued by domain
    (and, for sub-items, entity_text + value_constraint presence)."""
    planner = CriteriaPlanner()
    records: dict[str, dict] = {}

    for study, data in corpus.items():
        cohort_label = "target"
        for rule_type in ("inclusion", "exclusion"):
            for item in data["target"][rule_type]:
                parent_key = [item["position_in_rule_list"], item["entity_text"] or item["name"]]
                composite = json.dumps([study, cohort_label, rule_type, parent_key, None])
                records[composite] = {
                    "study": study,
                    "domain": item["domain"],
                    "entity_text": item["entity_text"],
                    "kind": "parent",
                }

                criterion = Criteria(
                    name=item["name"] or "",
                    domain=item["domain"] or "",
                    entity_text=item["entity_text"] or "",
                    logic_type=item["logic_type"] or "PRESENCE",
                )
                result = planner._decompose_criterion(criterion)
                for sub_index, sc in enumerate(result.sub_criteria):
                    sub_key = [sub_index, sc.entity_text or sc.name]
                    sub_composite = json.dumps(
                        [study, cohort_label, rule_type, parent_key, sub_key]
                    )
                    vc = sc.value_constraint
                    records[sub_composite] = {
                        "study": study,
                        "domain": sc.domain,
                        "entity_text": sc.entity_text,
                        "kind": "sub",
                        "value_constraint": None if vc is None else {
                            "op": vc.op, "value": vc.value, "reference_bound": vc.reference_bound,
                        },
                    }
    return records


def _diff(before: dict[str, dict], after: dict[str, dict]) -> dict:
    changed_domain = []
    missing_after = []
    new_in_after = []

    for key, rec in before.items():
        if key not in after:
            missing_after.append({"key": key, "before": rec})
            continue
        after_rec = after[key]
        if rec["domain"] != after_rec["domain"]:
            changed_domain.append({
                "key": key, "study": rec["study"], "kind": rec["kind"],
                "entity_text": rec["entity_text"],
                "domain_before": rec["domain"], "domain_after": after_rec["domain"],
            })

    for key in after:
        if key not in before:
            new_in_after.append({"key": key, "after": after[key]})

    return {
        "changed_domain": changed_domain,
        "missing_after": missing_after,
        "new_in_after": new_in_after,
        "total_before": len(before),
        "total_after": len(after),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus", required=True, help="path to the top-level criteria export JSON"
    )
    parser.add_argument("--out", help="write the captured baseline to this path")
    parser.add_argument("--diff", help="diff the current run against this prior baseline path")
    args = parser.parse_args()

    corpus = json.loads(Path(args.corpus).read_text())
    records = _run_corpus(corpus)

    if args.out:
        Path(args.out).write_text(json.dumps(records, indent=2))
        print(f"captured {len(records)} records -> {args.out}", file=sys.stderr)
    elif args.diff:
        before = json.loads(Path(args.diff).read_text())
        result = _diff(before, records)
        print(json.dumps(result, indent=2))
    else:
        parser.error("one of --out or --diff is required")


if __name__ == "__main__":
    main()
