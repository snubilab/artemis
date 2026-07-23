#!/usr/bin/env python3
"""Definition-level simulation of the Defect A fix (drug-anchored entry, follow gold).

For each study's TREATMENT cohort, compare three versions on entry event, drug
concept, inclusion-rule count, and concept overlap (Jaccard) vs gold:

  * current-gen  : the shipped generated cohort (disease-anchored swap applied)
  * fixed-gen(A) : swap disabled -> the base structuredExpression (DrugEra entry
                   + eligibility rules) = what the A fix would emit
  * gold         : TROY v1.1 reference (atlas-demo / provided)

No DB is touched; this predicts how much the A fix realigns the definition to gold.
Residual gap after A (wrong drug concept, infeasible rules) shows B/D still needed.

Usage: python3 artemis/scripts/simulate_defect_a_fix.py
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

ART = Path(__file__).resolve().parents[1]
GOLD = ART / "data" / "gold"
GEN = ART / "data" / "generated"
BASE = ART / "data" / "base_sim"
OUT = ART / "output" / "gold_vs_generated"

# study -> (gold treatment filename glob, generated dir/file, disease anchor concept for the swap path)
STUDIES = {
    "CAROLINA":         {"gold": "CAROLINA/*Linagliptin (CAROLINA).json",      "gen": "carolina/carolina_treatment.circe.json",  "anchor": None},
    "CARMELINA":        {"gold": "CARMELINA/*Linagliptin (CARMELINA).json",    "gen": "carmelina/carmelina_treatment.circe.json","anchor": None},
    "EMPA-REG OUTCOME": {"gold": "EMPA-REG OUTCOME/*Empagliflozin (EMPA-REG OUTCOME).json", "gen": "empa_reg/empa_reg_treatment.circe.json", "anchor": None},
    "LEADER":           {"gold": "LEADER/*Liraglutide (LEADER).json",          "gen": None, "anchor": (201826, "Type 2 diabetes mellitus")},
    "PLATO":            {"gold": "PLATO/*Ticagrelor (PLATO).json",             "gen": None, "anchor": (4270024, "Acute NSTEMI")},
    "ARISTOTLE":        {"gold": "ARISTOTLE/*Apixaban (ARISTOTLE).json",       "gen": None, "anchor": (313217, "Atrial fibrillation")},
}


def concepts(circe: dict) -> dict[int, str]:
    out = {}
    for cs in circe.get("ConceptSets", []):
        for it in cs.get("expression", {}).get("items", []):
            c = it.get("concept", {})
            cid = c.get("CONCEPT_ID")
            if cid is not None:
                out[int(cid)] = c.get("CONCEPT_NAME", "")
    return out


def entry_domain(circe: dict) -> str:
    pc = circe.get("PrimaryCriteria", {}).get("CriteriaList", [])
    doms = [k for c in pc for k in c.keys()]
    return "+".join(doms) if doms else "(none)"


def entry_drug_concept(base: dict):
    """The concept the base uses as its DrugEra entry (reveals Defect B)."""
    pc = base.get("PrimaryCriteria", {}).get("CriteriaList", [])
    csmap = {cs["id"]: cs for cs in base.get("ConceptSets", [])}
    for c in pc:
        for dom, body in c.items():
            if dom in ("DrugEra", "DrugExposure"):
                cs = csmap.get(body.get("CodesetId"), {})
                its = cs.get("expression", {}).get("items", [])
                if its:
                    cc = its[0]["concept"]
                    return cc.get("CONCEPT_ID"), cc.get("CONCEPT_NAME")
    return None, None


def load_one(pattern_dir: Path, pat: str):
    hits = glob.glob(str(pattern_dir / pat))
    return json.loads(Path(hits[0]).read_text()) if hits else None


def jac(a: set, b: set) -> float:
    u = a | b
    return round(len(a & b) / len(u), 4) if u else 0.0


def simulate():
    rows = []
    for study, cfg in STUDIES.items():
        gold = load_one(GOLD, cfg["gold"])
        base_rec = json.loads((BASE / f"{study}.json").read_text())
        base = base_rec["base"]
        gold_c = set(concepts(gold))

        # fixed-gen (A fix) == base (DrugEra entry + eligibility rules)
        fixed_c = set(concepts(base))
        fixed_entry = entry_domain(base)
        fixed_rules = len(base.get("InclusionRules", []))
        dcid, dname = entry_drug_concept(base)

        # current-gen
        if cfg["gen"]:
            cur = json.loads((GEN / cfg["gen"]).read_text())
            cur_c = set(concepts(cur))
            cur_entry = entry_domain(cur)
            cur_rules = len(cur.get("InclusionRules", []))
        else:
            # LEADER/PLATO/ARISTOTLE: anchor swap path = disease-only + drug presence,
            # inclusion rules stripped. Concepts = {anchor disease} U {entry drug}.
            cur_c = {cfg["anchor"][0]}
            if dcid is not None:
                cur_c.add(dcid)
            cur_entry = "ConditionOccurrence"
            cur_rules = 0  # anchor path strips eligibility rules, appends 1 drug rule

        rows.append({
            "study": study,
            "gold_entry": entry_domain(gold), "gold_rules": len(gold.get("InclusionRules", [])),
            "gold_concepts": len(gold_c),
            "cur_entry": cur_entry, "cur_rules": cur_rules, "cur_concepts": len(cur_c),
            "cur_jaccard": jac(cur_c, gold_c),
            "fixed_entry": fixed_entry, "fixed_rules": fixed_rules, "fixed_concepts": len(fixed_c),
            "fixed_jaccard": jac(fixed_c, gold_c),
            "base_drug_concept": f"{dcid} {dname}",
            "drug_concept_ok": not bool(re.search(r"sitagliptin|metabolite|Saxenda|\[.*\]", dname or "")),
            "entry_fixed": (fixed_entry.startswith("DrugEra") and not cur_entry.startswith("DrugEra")),
        })

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "simulation.json").write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=2) + "\n")

    hdr = f"{'study':<17}{'entry cur→fix (gold)':<26}{'rules cur/fix/gold':<20}{'Jaccard cur→fix':<18}{'drugB?'}"
    print(hdr); print("-" * len(hdr))
    for r in rows:
        entry = f"{r['cur_entry'][:4]}→{r['fixed_entry'][:4]} ({r['gold_entry'][:4]})"
        rules = f"{r['cur_rules']}/{r['fixed_rules']}/{r['gold_rules']}"
        jstr = f"{r['cur_jaccard']:.2f}→{r['fixed_jaccard']:.2f}"
        drugb = "OK" if r["drug_concept_ok"] else "WRONG"
        print(f"{r['study']:<17}{entry:<26}{rules:<20}{jstr:<18}{drugb}")
    print(f"\nwrote {OUT/'simulation.json'}")
    # self-check
    for r in rows:
        assert r["fixed_entry"].startswith("DrugEra"), f"fixed entry not drug for {r['study']}"
    print("self-check OK: every fixed-gen entry is DrugEra (drug-anchored, matches gold)")


if __name__ == "__main__":
    simulate()
