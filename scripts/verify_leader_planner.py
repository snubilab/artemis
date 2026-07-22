"""
LEADER Pipeline Verification Script.
Runs the ARTEMIS pipeline with the new Planner agent and compares with TROY.
"""
import json
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.models.ir import ARTEMISRequest, CohortDefinition, PrimaryCriteria, Criteria
from src.agents.planner.decomposer import CriteriaPlanner

# ============================================================
# Step 1: Load TROY reference
# ============================================================
print("=" * 60)
print("STEP 1: Load TROY Reference")
print("=" * 60)

troy_path = "data/sample/LEADER/[TROY] Liraglutide (LEADER) v3.4.json"
with open(troy_path) as f:
    troy = json.load(f)

troy_cs_names = [cs["name"] for cs in troy.get("ConceptSets", [])]
print(f"TROY ConceptSets: {len(troy_cs_names)}")
for name in troy_cs_names:
    concepts = None
    for cs in troy["ConceptSets"]:
        if cs["name"] == name:
            concepts = len(cs["expression"]["items"])
            break
    print(f"  - {name} ({concepts} concepts)")

# ============================================================
# Step 2: Simulate Agent 1 output (from cached NCT data)
# ============================================================
print("\n" + "=" * 60)
print("STEP 2: Simulate Agent 1 IR (from NCT01179048)")
print("=" * 60)

# Build a realistic IR that Agent 1 would produce from the LEADER NCT
# Based on the actual NCT eligibility criteria
ir = ARTEMISRequest(
    target=CohortDefinition(
        primary_criteria=PrimaryCriteria(
            domain="Drug",
            entity_text="liraglutide",
            limit="First"
        ),
        inclusion_rules=[
            Criteria(
                name="Type 2 Diabetes",
                domain="Condition",
                entity_text="Type 2 Diabetes Mellitus",
                logic_type="PRESENCE"
            ),
            Criteria(
                name="HbA1c >= 7.0%",
                domain="Measurement",
                entity_text="HbA1c",
                logic_type="PRESENCE"
            ),
            Criteria(
                name="Age >= 50 with CV disease",
                domain="Condition",
                entity_text="cardiovascular, cerebrovascular or peripheral vascular disease",
                logic_type="PRESENCE"
            ),
            Criteria(
                name="Chronic renal failure",
                domain="Condition",
                entity_text="chronic renal failure",
                logic_type="PRESENCE"
            ),
            Criteria(
                name="Chronic heart failure",
                domain="Condition",
                entity_text="chronic heart failure",
                logic_type="PRESENCE"
            ),
        ],
        exclusion_rules=[
            Criteria(
                name="Type 1 Diabetes",
                domain="Condition",
                entity_text="Type 1 Diabetes Mellitus",
                logic_type="ABSENCE"
            ),
            Criteria(
                name="Prior GLP-1 RA or pramlintide or DPP-4 inhibitor",
                domain="Drug",
                entity_text="GLP-1 receptor agonist, pramlintide, or DPP-4 inhibitor",
                logic_type="ABSENCE"
            ),
            Criteria(
                name="Non-allowed insulin use",
                domain="Drug",
                entity_text="insulin other than human NPH insulin or long-acting insulin analogue or premixed insulin",
                logic_type="ABSENCE"
            ),
        ],
    ),
    comparator=CohortDefinition(
        primary_criteria=PrimaryCriteria(
            domain="Drug",
            entity_text="placebo",
            limit="First"
        ),
    ),
    outcome=__import__("src.models.ir", fromlist=["CohortOutcome"]).CohortOutcome(
        name="MACE",
        domain="Condition",
        entity_text="major adverse cardiovascular events",
        time_at_risk=__import__("src.models.ir", fromlist=["TemporalWindow"]).TemporalWindow(start=0, end=365)
    ),
)

print(f"Agent 1 IR:")
print(f"  Target inclusion rules: {len(ir.target.inclusion_rules)}")
print(f"  Target exclusion rules: {len(ir.target.exclusion_rules)}")
for r in ir.target.inclusion_rules:
    print(f"    [INC] {r.name}: '{r.entity_text}'")
for r in ir.target.exclusion_rules:
    print(f"    [EXC] {r.name}: '{r.entity_text}'")

# ============================================================
# Step 3: Run Planner
# ============================================================
print("\n" + "=" * 60)
print("STEP 3: Run Criteria Planner")
print("=" * 60)

planner = CriteriaPlanner()
ir = planner.plan(ir)

# Collect all entity texts after planning
def collect_entities(cohort):
    entities = set()
    if cohort.primary_criteria.entity_text:
        entities.add(cohort.primary_criteria.entity_text)
    for rule in cohort.inclusion_rules + cohort.exclusion_rules:
        if rule.sub_criteria:
            for sc in rule.sub_criteria:
                if sc.entity_text:
                    entities.add(sc.entity_text)
        elif rule.entity_text:
            entities.add(rule.entity_text)
    return entities

artemis_entities = collect_entities(ir.target)
print(f"\nARTEMIS entities after Planner: {len(artemis_entities)}")
for e in sorted(artemis_entities):
    print(f"  - {e}")

# ============================================================
# Step 4: Compare with TROY
# ============================================================
print("\n" + "=" * 60)
print("STEP 4: TROY vs ARTEMIS Comparison")
print("=" * 60)

troy_names_lower = {n.lower().strip() for n in troy_cs_names}
artemis_names_lower = {e.lower().strip() for e in artemis_entities}

# Fuzzy matching: check if ARTEMIS entity is a substring of any TROY name or vice versa
matched = set()
for artemis_name in artemis_names_lower:
    for troy_name in troy_names_lower:
        if artemis_name in troy_name or troy_name in artemis_name:
            matched.add((artemis_name, troy_name))

troy_only = troy_names_lower - {m[1] for m in matched}
artemis_only = artemis_names_lower - {m[0] for m in matched}

print(f"\n🔬 CONCEPTSET COMPARISON")
print(f"{'='*60}")
print(f"  TROY: {len(troy_names_lower)} | ARTEMIS: {len(artemis_names_lower)} | Matched: {len(matched)}")

print(f"\n✅ MATCHED ({len(matched)}):")
for t, r in sorted(matched):
    print(f"  ✅ {t} ↔ {r}")

print(f"\n❌ TROY-only ({len(troy_only)}):")
for name in sorted(troy_only):
    print(f"  - {name}")

print(f"\n🆕 ARTEMIS-only ({len(artemis_only)}):")
for name in sorted(artemis_only):
    print(f"  - {name}")

# Summary
print(f"\n📊 SUMMARY")
print(f"{'='*60}")
print(f"  Before Planner: ~10 entities")
print(f"  After Planner:  {len(artemis_entities)} entities")
print(f"  TROY reference: {len(troy_names_lower)} concept sets")
print(f"  Match rate:     {len(matched)}/{len(troy_names_lower)} ({100*len(matched)/len(troy_names_lower):.1f}%)")
