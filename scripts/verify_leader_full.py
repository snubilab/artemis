"""
LEADER Pipeline Verification — Full Design Paper Criteria.
Uses the complete eligibility criteria from the LEADER design paper
instead of the truncated NCT API version.
"""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from src.models.ir import ARTEMISRequest, CohortDefinition, PrimaryCriteria, Criteria, CohortOutcome, TemporalWindow
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

# Deduplicate TROY concept set names
troy_cs_names = list({cs["name"] for cs in troy.get("ConceptSets", [])})
print(f"TROY ConceptSets (unique): {len(troy_cs_names)}")

# ============================================================
# Step 2: Build IR from FULL Design Paper Criteria
# ============================================================
print("\n" + "=" * 60)
print("STEP 2: Agent 1 IR from FULL Design Paper Criteria")
print("=" * 60)

ir = ARTEMISRequest(
    target=CohortDefinition(
        primary_criteria=PrimaryCriteria(
            domain="Drug", entity_text="liraglutide", limit="First"
        ),
        inclusion_rules=[
            # Type 2 Diabetes
            Criteria(name="Type 2 Diabetes", domain="Condition",
                     entity_text="Type 2 Diabetes Mellitus", logic_type="PRESENCE"),
            # Anti-diabetic treatment
            Criteria(name="Anti-diabetic treatment", domain="Drug",
                     entity_text="oral anti-diabetic drugs or human NPH insulin or long-acting insulin analogue or premixed insulin",
                     logic_type="PRESENCE"),
            # HbA1c
            Criteria(name="HbA1c >= 7%", domain="Measurement",
                     entity_text="HbA1c", logic_type="PRESENCE"),

            # ===== Prior CVD cohort (age >= 50) =====
            Criteria(name="Prior MI", domain="Condition",
                     entity_text="Myocardial Infarction", logic_type="PRESENCE"),
            Criteria(name="Prior stroke or TIA", domain="Condition",
                     entity_text="stroke or transient ischemic attack", logic_type="PRESENCE"),
            Criteria(name="Prior revascularization", domain="Procedure",
                     entity_text="coronary, carotid or peripheral arterial revascularization", logic_type="PRESENCE"),
            Criteria(name="Arterial stenosis >50%", domain="Condition",
                     entity_text="stenosis of coronary, carotid, or lower extremity arteries", logic_type="PRESENCE"),
            Criteria(name="Symptomatic CHD", domain="Condition",
                     entity_text="symptomatic coronary heart disease with positive stress test or unstable angina", logic_type="PRESENCE"),
            Criteria(name="Asymptomatic cardiac ischemia", domain="Condition",
                     entity_text="asymptomatic cardiac ischemia", logic_type="PRESENCE"),
            Criteria(name="CHF NYHA II-III", domain="Condition",
                     entity_text="chronic heart failure NYHA class II-III", logic_type="PRESENCE"),
            Criteria(name="Chronic renal failure", domain="Condition",
                     entity_text="chronic renal failure with eGFR less than 60", logic_type="PRESENCE"),

            # ===== No Prior CVD group (age >= 60) =====
            Criteria(name="Microalbuminuria or proteinuria", domain="Measurement",
                     entity_text="microalbuminuria or proteinuria", logic_type="PRESENCE"),
            Criteria(name="Hypertension with LVH", domain="Condition",
                     entity_text="hypertension and left ventricular hypertrophy", logic_type="PRESENCE"),
            Criteria(name="LV dysfunction", domain="Condition",
                     entity_text="left ventricular systolic or diastolic dysfunction", logic_type="PRESENCE"),
            Criteria(name="Low ABI", domain="Measurement",
                     entity_text="ankle-brachial index less than 0.9", logic_type="PRESENCE"),
        ],
        exclusion_rules=[
            # Full exclusion criteria from design paper
            Criteria(name="Type 1 Diabetes", domain="Condition",
                     entity_text="Type 1 Diabetes Mellitus", logic_type="ABSENCE"),
            Criteria(name="Elevated Calcitonin", domain="Measurement",
                     entity_text="calcitonin", logic_type="ABSENCE"),
            Criteria(name="Prior GLP-1 RA/pramlintide/DPP-4i", domain="Drug",
                     entity_text="GLP-1 receptor agonist, pramlintide, or DPP-4 inhibitor", logic_type="ABSENCE"),
            Criteria(name="Non-allowed insulin", domain="Drug",
                     entity_text="insulin other than human NPH insulin or long-acting insulin analogue or premixed insulin", logic_type="ABSENCE"),
            Criteria(name="Acute glycemic decompensation", domain="Condition",
                     entity_text="diabetic ketoacidosis", logic_type="ABSENCE"),
            Criteria(name="Recent acute coronary/cerebrovascular event", domain="Condition",
                     entity_text="acute coronary or cerebrovascular event", logic_type="ABSENCE"),
            Criteria(name="Planned revascularization", domain="Procedure",
                     entity_text="planned coronary, carotid, or peripheral artery revascularization", logic_type="ABSENCE"),
            Criteria(name="Severe heart failure", domain="Condition",
                     entity_text="chronic heart failure NYHA class IV", logic_type="ABSENCE"),
            Criteria(name="Continuous renal replacement therapy", domain="Procedure",
                     entity_text="renal dialysis or continuous renal replacement therapy", logic_type="ABSENCE"),
            Criteria(name="End-stage liver disease", domain="Condition",
                     entity_text="end-stage liver disease", logic_type="ABSENCE"),
            Criteria(name="Organ transplant", domain="Procedure",
                     entity_text="solid organ transplant", logic_type="ABSENCE"),
            Criteria(name="Malignant neoplasm", domain="Condition",
                     entity_text="malignant neoplasm", logic_type="ABSENCE"),
            Criteria(name="MEN2 or MTC", domain="Condition",
                     entity_text="multiple endocrine neoplasia type 2 or medullary thyroid carcinoma", logic_type="ABSENCE"),
        ],
    ),
    comparator=CohortDefinition(
        primary_criteria=PrimaryCriteria(domain="Drug", entity_text="placebo", limit="First"),
    ),
    outcome=CohortOutcome(
        name="MACE", domain="Condition", entity_text="major adverse cardiovascular events",
        time_at_risk=TemporalWindow(start=0, end=365)
    ),
)

print(f"Agent 1 IR (from Design Paper):")
print(f"  Inclusion rules: {len(ir.target.inclusion_rules)}")
print(f"  Exclusion rules: {len(ir.target.exclusion_rules)}")

# ============================================================
# Step 3: Run Planner
# ============================================================
print("\n" + "=" * 60)
print("STEP 3: Run Criteria Planner")
print("=" * 60)

planner = CriteriaPlanner()
ir = planner.plan(ir)

# Collect all entity texts
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

matched = set()
for artemis_name in artemis_names_lower:
    for troy_name in troy_names_lower:
        if artemis_name in troy_name or troy_name in artemis_name:
            matched.add((artemis_name, troy_name))

troy_matched = {m[1] for m in matched}
artemis_matched = {m[0] for m in matched}
troy_only = troy_names_lower - troy_matched
artemis_only = artemis_names_lower - artemis_matched

print(f"\n🔬 CONCEPTSET COMPARISON (Full Design Paper)")
print(f"{'='*60}")
print(f"  TROY: {len(troy_names_lower)} | ARTEMIS: {len(artemis_names_lower)} | TROY matched: {len(troy_matched)}")

print(f"\n✅ MATCHED ({len(troy_matched)} TROY concepts covered):")
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
print(f"  NCT API only (before): 10 entities → 2/46 match (4.3%)")
print(f"  NCT + Planner:         19 entities → 8/46 match (17.4%)")
print(f"  Design Paper + Planner: {len(artemis_entities)} entities → {len(troy_matched)}/{len(troy_names_lower)} match ({100*len(troy_matched)/len(troy_names_lower):.1f}%)")
