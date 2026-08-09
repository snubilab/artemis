#!/usr/bin/env python3
"""Compare gold (TROY v1.1) vs AI-generated Circe cohort definitions.

RAW-ITEM comparison only (no DB / WebAPI): concepts are the ids as *listed* in
each ConceptSet, not Circe's resolved closure. For each trial and role it pairs
the gold Circe JSON against the generated one and reports ConceptSet counts,
unique concept overlap, and InclusionRule counts.

Outputs a single comparison.json consumed by the HTML dashboard
(scripts/build_diagnosis_data.py -> scripts/build_diagnosis_dashboard.py).

Raw-item overlap and closure overlap are NOT interchangeable -- they differ by
1.5x-3x on every trial. The closure-level evaluation that AGENTS.md (EVALUATION)
requires lives in scripts/conceptset_overlap_eval.py; the JSON written here is
stamped "mode": "raw_items" so the two can never be confused. The existing six
treatment/comparator rows keep raw-item semantics precisely because
build_diagnosis_data.py publishes their numbers.

Usage:
    python3 artemis/scripts/compare_gold_vs_generated_circe.py
    python3 artemis/scripts/compare_gold_vs_generated_circe.py --generated-dir tmp/circe_b
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ARTEMIS_DIR = Path(__file__).resolve().parents[1]
if str(ARTEMIS_DIR) not in sys.path:
    sys.path.insert(0, str(ARTEMIS_DIR))

from scripts.conceptset_overlap_eval import TRIALS as STUDY_TRIALS  # noqa: E402
from src.services.conceptset_closure import all_item_ids  # noqa: E402

GOLD_DIR = ARTEMIS_DIR / "data" / "gold"
GEN_DIR = ARTEMIS_DIR / "data" / "generated"
DEFAULT_STUDY_DIR = ARTEMIS_DIR / "tmp" / "circe_b"
OUT_DIR = ARTEMIS_DIR / "output" / "gold_vs_generated"

CLOSURE_REPORT = "scripts/conceptset_overlap_eval.py --mode closure"

# (trial_label, role, gold_file_relative, generated_file_relative)
# Mapping follows each trial's design: treatment = study drug, comparator = active control.
PAIRS = [
    ("CAROLINA", "treatment",
     "CAROLINA/[TROY v1.1] Linagliptin (CAROLINA).json",
     "carolina/carolina_treatment.circe.json"),
    ("CAROLINA", "comparator",
     "CAROLINA/[TROY v1.1] Glimepiride (CAROLINA).json",
     "carolina/carolina_comparator.circe.json"),
    ("CARMELINA", "treatment",
     "CARMELINA/[TROY v1.1] Linagliptin (CARMELINA).json",
     "carmelina/carmelina_treatment.circe.json"),
    ("CARMELINA", "comparator",
     "CARMELINA/[TROY v1.1] Sulfonylureas (CARMELINA).json",
     "carmelina/carmelina_comparator.circe.json"),
    ("EMPA-REG OUTCOME", "treatment",
     "EMPA-REG OUTCOME/[TROY v1.1] Empagliflozin (EMPA-REG OUTCOME).json",
     "empa_reg/empa_reg_treatment.circe.json"),
    ("EMPA-REG OUTCOME", "comparator",
     "EMPA-REG OUTCOME/[TROY v1.1] DPP-4 (EMPA-REG OUTCOME).json",
     "empa_reg/empa_reg_comparator.circe.json"),
]


def extract_concepts(cohort: dict) -> dict[int, str]:
    """concept_id -> concept_name across all ConceptSets.

    Which ids a concept set *lists* is decided once, in
    ``src.services.conceptset_closure.all_item_ids``; this function only adds the
    display names, which the resolver has no reason to carry.

    ``all_item_ids`` and not ``raw_item_ids``: this comparison has always counted
    ``isExcluded`` items too, and the published dashboard reads these numbers.
    Gold CAROLINA alone carries 160 excluded items, so switching primitives would
    silently move a published figure for unchanged input. The non-excluded
    variant (``raw_item_ids``) is what ``conceptset_overlap_eval.py --mode raw``
    uses; the JSON below records which of the two produced it.
    """
    out: dict[int, str] = {}
    for cs in cohort.get("ConceptSets", []):
        ids = all_item_ids(cs)
        for item in cs.get("expression", {}).get("items", []):
            c = item.get("concept", {})
            cid = c.get("CONCEPT_ID")
            if cid is None or int(cid) not in ids:
                continue
            out[int(cid)] = c.get("CONCEPT_NAME", "")
    return out


def summarize(cohort: dict) -> dict:
    return {
        "concept_sets": len(cohort.get("ConceptSets", [])),
        "inclusion_rules": len(cohort.get("InclusionRules", [])),
        "concepts": extract_concepts(cohort),
    }


def compare_pair(trial: str, role: str, gold_path: Path, gen_path: Path) -> dict:
    gold = summarize(json.loads(gold_path.read_text()))
    gen = summarize(json.loads(gen_path.read_text()))

    gold_ids = set(gold["concepts"])
    gen_ids = set(gen["concepts"])
    shared = gold_ids & gen_ids
    gold_only = gold_ids - gen_ids
    gen_only = gen_ids - gold_ids
    union = gold_ids | gen_ids
    jaccard = round(len(shared) / len(union), 4) if union else 0.0

    names = {**gold["concepts"], **gen["concepts"]}

    def as_list(ids):
        return sorted(({"id": i, "name": names.get(i, "")} for i in ids),
                      key=lambda x: x["name"] or str(x["id"]))

    return {
        "trial": trial,
        "role": role,
        "gold_file": gold_path.name,
        "generated_file": gen_path.name,
        "gold_concept_sets": gold["concept_sets"],
        "gen_concept_sets": gen["concept_sets"],
        "gold_inclusion_rules": gold["inclusion_rules"],
        "gen_inclusion_rules": gen["inclusion_rules"],
        "gold_concepts": len(gold_ids),
        "gen_concepts": len(gen_ids),
        "shared": len(shared),
        "gold_only": len(gold_only),
        "gen_only": len(gen_only),
        "jaccard": jaccard,
        "gold_only_list": as_list(gold_only),
        "gen_only_list": as_list(gen_only),
    }


def study_pairs(study_dir: Path) -> list[tuple[str, str, Path, Path]]:
    """The six one-per-study generated cohorts, paired with the gold treatment arm.

    Additive: these carry role "study" and therefore cannot collide with the
    ``trial|role`` keys build_diagnosis_data.py looks up. The registry is shared
    with conceptset_overlap_eval.py so the gold/generated mapping exists once.
    """
    out = []
    for trial, (gold_rel, gen_name) in STUDY_TRIALS.items():
        out.append((trial, "study", GOLD_DIR / gold_rel, study_dir / gen_name))
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--generated-dir", default=str(DEFAULT_STUDY_DIR),
                    help="directory holding the one-per-study generated Circe JSONs")
    ap.add_argument("--skip-study-rows", action="store_true",
                    help="emit only the six original treatment/comparator rows")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    todo: list[tuple[str, str, Path, Path]] = [
        (trial, role, GOLD_DIR / gold_rel, GEN_DIR / gen_rel)
        for trial, role, gold_rel, gen_rel in PAIRS
    ]
    if not args.skip_study_rows:
        todo += study_pairs(Path(args.generated_dir))

    # A missing gold file is a real error -- data/gold/ is tracked, so its absence
    # means the checkout is broken. A missing GENERATED study file is not: those
    # live under tmp/, which is gitignored (.gitignore:17) and is repopulated by
    # copying out of the artemis-api container. Asserting on it made this script,
    # which predates the study rows and feeds the dashboard, fail on a fresh
    # checkout and leave comparison.json stale rather than regenerated.
    results = []
    skipped: list[str] = []
    for trial, role, gold_path, gen_path in todo:
        assert gold_path.exists(), f"missing gold: {gold_path}"
        if not gen_path.exists():
            skipped.append(f"{trial}/{role}: {gen_path}")
            continue
        results.append(compare_pair(trial, role, gold_path, gen_path))

    if skipped:
        print(f"WARNING: skipped {len(skipped)} pair(s) with no generated CIRCE "
              f"(tmp/ is gitignored; repopulate from the artemis-api container):")
        for s in skipped:
            print(f"  - {s}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        # Stamped so nobody reads these numbers as Circe closure. Raw-item and
        # closure overlap differ by 1.5x-3x on every trial.
        "mode": "raw_items_including_excluded",
        "closure_report": CLOSURE_REPORT,
        "study_generated_dir": None if args.skip_study_rows else str(Path(args.generated_dir)),
        "skipped_pairs": skipped,
        "pairs": results,
    }
    (OUT_DIR / "comparison.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    # console summary
    hdr = f"{'trial':<18}{'role':<11}{'gold_cs':>8}{'gen_cs':>7}{'gold_c':>8}{'gen_c':>7}{'shared':>8}{'g_only':>7}{'ai_only':>8}{'jacc':>7}"
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        print(f"{r['trial']:<18}{r['role']:<11}{r['gold_concept_sets']:>8}{r['gen_concept_sets']:>7}"
              f"{r['gold_concepts']:>8}{r['gen_concepts']:>7}{r['shared']:>8}{r['gold_only']:>7}"
              f"{r['gen_only']:>8}{r['jaccard']:>7.2f}")
    print(f"\nwrote {OUT_DIR / 'comparison.json'}")

    # self-check: numbers must be internally consistent
    for r in results:
        assert r["shared"] + r["gold_only"] == r["gold_concepts"], r
        assert r["shared"] + r["gen_only"] == r["gen_concepts"], r
        assert len(r["gold_only_list"]) == r["gold_only"], r
        assert len(r["gen_only_list"]) == r["gen_only"], r
    print(f"self-check OK: overlap arithmetic consistent for all {len(results)} pairs")
    print(f"mode={payload['mode']} -- for Circe closure overlap run: {CLOSURE_REPORT}")


if __name__ == "__main__":
    main()
