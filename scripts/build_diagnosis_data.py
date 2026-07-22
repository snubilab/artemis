#!/usr/bin/env python3
"""Assemble diagnosis.json (rows + defects with CODE root causes) for the dashboard.

Rows come from comparison.json (concept overlap) + the two sites' reported counts.
Each defect carries a code_cause block: the exact function/file/line and the
mechanism proven by reading the generation code + the container TTE store.

Usage: python3 artemis/scripts/build_diagnosis_data.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "output" / "gold_vs_generated"
SVC = "artemis/src/services/tte_service.py"
A2 = "artemis/src/agents/agent2/workflow.py"
A3 = "artemis/src/agents/agent3/assembler.py"


def main() -> None:
    cmp = {p["trial"] + "|" + p["role"]: p
           for p in json.loads((OUT / "comparison.json").read_text())["pairs"]}
    trial_map = {"carolina": "CAROLINA", "carmelina": "CARMELINA", "empa_reg": "EMPA-REG OUTCOME"}
    counts = {
        "carmelina|treatment": (0, 0), "carmelina|comparator": (0, 0),
        "carolina|treatment": (11, 36), "carolina|comparator": (43, 116),
        "empa_reg|treatment": (0, 0), "empa_reg|comparator": (0, 0),
    }
    gold_drug = {
        "carolina": {"treatment": "Linagliptin (ATC)", "comparator": "Glimepiride (ATC)"},
        "carmelina": {"treatment": "Linagliptin (ATC)", "comparator": "Sulfonylureas (ATC)"},
        "empa_reg": {"treatment": "Empagliflozin (ATC)", "comparator": "DPP-4 inhibitors (ATC)"},
    }
    gen_drug = {"carolina": "1580747 sitagliptin", "carmelina": "1580747 sitagliptin",
                "empa_reg": "1254065 CHF-6366 metabolite"}
    killer = {"empa_reg": "#11 Dietary/Exercise regimen (Observation)",
              "carmelina": "#9 Albuminuria / UACR (Condition/Measurement)", "carolina": None}

    rows = []
    for tk in ["carolina", "carmelina", "empa_reg"]:
        for role in ["treatment", "comparator"]:
            c = cmp[trial_map[tk] + "|" + role]
            r1, r2 = counts[f"{tk}|{role}"]
            rows.append({
                "trial": trial_map[tk], "role": role,
                "patients_ajou": r1, "patients_keimyung": r2,
                "gen_entry": "Type 2 Diabetes (ConditionOccurrence)",
                "gold_entry": f"DrugEra: {gold_drug[tk][role]}",
                "gen_drug_concept": gen_drug[tk],
                "gold_drug_expected": gold_drug[tk][role],
                "comparator_design": ("require drug (PRESENCE)" if role == "treatment"
                                      else "exclude TREATMENT drug (No linagliptin) — not real comparator"),
                "killer_rule": killer[tk],
                "gen_concept_sets": c["gen_concept_sets"], "gold_concept_sets": c["gold_concept_sets"],
                "gen_rules": c["gen_inclusion_rules"], "gold_rules": c["gold_inclusion_rules"],
                "gen_concepts": c["gen_concepts"], "gold_concepts": c["gold_concepts"],
                "shared": c["shared"], "gold_only": c["gold_only"], "gen_only": c["gen_only"],
                "jaccard": c["jaccard"],
                "gold_only_ex": [x["name"] for x in c["gold_only_list"][:12] if x["name"]],
                "gen_only_ex": [x["name"] for x in c["gen_only_list"][:12] if x["name"]],
            })

    defects = [
        {
            "id": "A", "title": "Wrong entry event (drug → disease swap)",
            "severity": "critical", "affects": "all 6",
            "detail": "Every generated cohort enters on Type 2 Diabetes instead of the index drug. The upstream base was CORRECT (DrugEra of the drug, verified in the TTE store); the swap breaks it.",
            "code_cause": {
                "where": f"{SVC} :: _swap_primary_to_disease()",
                "refs": [f"{SVC}#L4657 swap fn", f"{SVC}#L168 DISEASE_ANCHOR_CONCEPTS (only LEADER/PLATO/ARISTOTLE)",
                         f"{SVC}#L4750 fallback grabs first Condition CS", f"{SVC}#L3803 always called"],
                "mechanism": "Function deliberately converts Drug PrimaryCriteria to ConditionOccurrence. For the 3 benchmark NCTs in DISEASE_ANCHOR_CONCEPTS it builds a clean disease-only base and STRIPS all inclusion rules (L4737). CARMELINA/CAROLINA/EMPA are NOT in that map, so the fallback (L4750) picks the first Condition concept set found in the inclusion rules — which is 'Type 2 Diabetes' — as the entry anchor, and KEEPS every restrictive rule (incl. the killers).",
                "evidence": "Store base entry = DrugEra «drug» for all 6; output entry = ConditionOccurrence cs=2 Type 2 Diabetes.",
            },
        },
        {
            "id": "B", "title": "Wrong drug concept (RAG embedding mismap)",
            "severity": "critical", "affects": "all 6",
            "detail": "ConceptSets named for the study drug contain the WRONG concept: linagliptin→sitagliptin, empagliflozin/'BI 10773'→CHF-6366 metabolite. CV drugs (ticagrelor, apixaban) mapped correctly.",
            "code_cause": {
                "where": f"{SVC} :: _recommend_seeded_concept_set() → Agent2Workflow",
                "refs": [f"{SVC}#L5214 mapping entry", f"{A2}#L385 fast path disabled → slow/RAG",
                         f"{A2}#L296 ATC route (drug CLASSES only)", "artemis/src/agents/conceptset/rag_search.py"],
                "mechanism": "Single ingredient names have no ATC drug-class match, so they fall to the slow/RAG path (MedCPT embeddings). RAG top-5 for 'linagliptin' are sitagliptin/saxagliptin (no linagliptin at all); all candidate scores ≈0.011, indistinguishable, and top-1 is selected with NO exact-name guard. 'BI 10773' (investigational code) has no embedding signal → garbage (metabolite, even an HIV drug at rank 2). Result is cached in criterion_cache.sqlite so it persists.",
                "evidence": "Live RAG query: linagliptin→[sitagliptin, saxagliptin...]; BI 10773→[CHF-6366 metabolite, Biktarvy...].",
            },
        },
        {
            "id": "C", "title": "Comparator = NOT-treatment-drug (not real comparator)",
            "severity": "critical", "affects": "3 comparators",
            "detail": "Comparator cohorts are 'disease patients without the TREATMENT drug', never the real active comparator (Glimepiride/Sulfonylureas/DPP-4). The treatment-vs-comparator contrast collapses.",
            "code_cause": {
                "where": f"{SVC} :: _build_disease_based_comparator_circe()",
                "refs": [f"{SVC}#L4851 comparator builder", f"{SVC}#L4877 maps the TREATMENT arm name",
                         f"{SVC}#L4905 'No {{drug}}' absence rule, Occurrence Type:0/Count:0",
                         f"{SVC}#L274 _uses_explicit_comparator gate", f"{SVC}#L3795 derived path"],
                "mechanism": "The comparator builder receives the TREATMENT drug name (_treatment_name), maps that drug, and appends a 'No <treatment>' absence rule (exactly 0 occurrences). The real comparator drug is never mapped. This derived path fires because all 3 studies have comparisonMode='target_minus_treatment' (not 'explicit_comparator').",
                "evidence": "Output comparator rule name = 'No linagliptin'; store comparisonMode = target_minus_treatment for studies 8/9/10.",
            },
        },
        {
            "id": "D", "title": "Data-infeasible criteria forced as mandatory inclusions",
            "severity": "blocker", "affects": "carmelina, empa_reg",
            "detail": "EMPA #11 requires Dietary/Exercise regimen Observations; CARMELINA #9 requires Albuminuria/UACR. These drop every patient. CAROLINA has no such rule → non-zero (but still invalid via A/B/C).",
            "code_cause": {
                "where": f"{A3} :: inclusion-rule assembly (Agent 3)",
                "refs": [f"{A3} assembler", f"{SVC}#L4737 benchmark path strips rules (ours does not)"],
                "mechanism": "Agent 3 encodes EVERY trial eligibility criterion as a mandatory InclusionRule with no CDM-feasibility check. Unlike Defect B, the CONCEPTS here map fine (Therapeutic diet, Regular exercise, UACR labs) — but these data elements are essentially absent/sparse in routine hospital CDM, so the criterion is unsatisfiable → 0 patients. These rules survive only because Defect A's fallback keeps all rules for non-benchmark studies.",
                "evidence": "Killer concepts map to reasonable concepts, yet CARMELINA/EMPA=0 while CAROLINA (no such rule)=non-zero.",
            },
        },
    ]

    payload = {"rows": rows, "defects": defects,
               "sources": {"ajou": "김청수 (아주대 의료정보학교실), CohortGenerator run #1",
                           "keimyung": "조재형 (계명대), CohortGenerator run #2"}}
    (OUT / "diagnosis.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print("wrote", OUT / "diagnosis.json", f"| rows={len(rows)} defects={len(defects)}")


if __name__ == "__main__":
    main()
