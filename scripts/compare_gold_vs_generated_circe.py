#!/usr/bin/env python3
"""Compare gold (TROY v1.1) vs AI-generated Circe cohort definitions.

Definition-level comparison only (no DB / WebAPI). For each trial and role
(treatment/comparator) it pairs the gold Circe JSON against the generated one
and reports ConceptSet counts, unique concept overlap, and InclusionRule counts.

Outputs a single comparison.json consumed by the HTML dashboard.

Usage: python3 artemis/scripts/compare_gold_vs_generated_circe.py
"""
from __future__ import annotations

import json
from pathlib import Path

ARTEMIS_DIR = Path(__file__).resolve().parents[1]
GOLD_DIR = ARTEMIS_DIR / "data" / "gold"
GEN_DIR = ARTEMIS_DIR / "data" / "generated"
OUT_DIR = ARTEMIS_DIR / "output" / "gold_vs_generated"

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
    """concept_id -> concept_name across all ConceptSets."""
    out: dict[int, str] = {}
    for cs in cohort.get("ConceptSets", []):
        for item in cs.get("expression", {}).get("items", []):
            c = item.get("concept", {})
            cid = c.get("CONCEPT_ID")
            if cid is None:
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


def main() -> None:
    results = []
    for trial, role, gold_rel, gen_rel in PAIRS:
        gold_path = GOLD_DIR / gold_rel
        gen_path = GEN_DIR / gen_rel
        assert gold_path.exists(), f"missing gold: {gold_path}"
        assert gen_path.exists(), f"missing generated: {gen_path}"
        results.append(compare_pair(trial, role, gold_path, gen_path))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"pairs": results}
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
    print("self-check OK: overlap arithmetic consistent for all 6 pairs")


if __name__ == "__main__":
    main()
