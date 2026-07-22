"""
LEADER E2E — Design Paper Criteria Direct Input.
Bypasses Agent 1, injects full design paper IR directly into pipeline stages:
  Design Paper IR → Planner → Agent 2 (OMOP) → Consolidator → Registry → Agent 3 → Agent 4 → TROY comparison
"""
import json
import sys
import os
import argparse
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from src.models.ir import ARTEMISRequest, CohortDefinition, PrimaryCriteria, Criteria, CohortOutcome, TemporalWindow, ValueConstraint
from src.agents.planner.decomposer import CriteriaPlanner
from src.agents.agent2.workflow import get_agent2
from src.agents.consolidator import ConceptSetConsolidator
from src.agents.agent3.assembler import agent3
from src.agents.agent4.validator import agent4
from src.registry.models import RegisteredConceptSet, RegisteredConcept
from src.registry.store import RegistryStore
from src.agents.agent2.agent2_cache import Agent2Cache

# CLI args
parser = argparse.ArgumentParser()
parser.add_argument("--no-cache", action="store_true", help="Skip Agent 2 cache")
args = parser.parse_args()

# Fresh registry for this run
registry = RegistryStore()

# ============================================================
# Step 0: Load TROY reference
# ============================================================
print("=" * 60)
print("STEP 0: Load TROY Reference")
print("=" * 60)

troy_path = "data/sample/LEADER/[TROY] Liraglutide (LEADER) v3.4.json"
with open(troy_path) as f:
    troy = json.load(f)

troy_concept_sets = troy.get("ConceptSets", [])
troy_cs_names = list({cs["name"] for cs in troy_concept_sets})
troy_concept_ids = set()
troy_cs_by_name = {}
for cs in troy_concept_sets:
    name = cs["name"]
    concept_ids = set()
    for item in cs.get("expression", {}).get("items", []):
        cid = item.get("concept", {}).get("CONCEPT_ID")
        if cid:
            concept_ids.add(cid)
            troy_concept_ids.add(cid)
    troy_cs_by_name[name] = concept_ids

print(f"  TROY ConceptSets: {len(troy_cs_names)} unique")
print(f"  TROY concept IDs: {len(troy_concept_ids)}")

# ============================================================
# Step 1: Build IR from FULL Design Paper Criteria
# ============================================================
print("\n" + "=" * 60)
print("STEP 1: Design Paper IR (Direct Input)")
print("=" * 60)

ir = ARTEMISRequest(
    target=CohortDefinition(
        primary_criteria=PrimaryCriteria(
            domain="Drug", entity_text="liraglutide", limit="First"
        ),
        inclusion_rules=[
            # Demographics
            Criteria(name="Age >= 50", domain="Demographics",
                     entity_text="age", logic_type="PRESENCE",
                     value_constraint=ValueConstraint(op="gte", value=50, unit_text="years")),
            Criteria(name="Type 2 Diabetes", domain="Condition",
                     entity_text="Type 2 Diabetes Mellitus", logic_type="PRESENCE"),
            Criteria(name="Anti-diabetic treatment", domain="Drug",
                     entity_text="oral anti-diabetic drugs or human NPH insulin or long-acting insulin analogue or premixed insulin",
                     logic_type="PRESENCE"),
            Criteria(name="HbA1c >= 7%", domain="Measurement",
                     entity_text="HbA1c", logic_type="PRESENCE"),
            # CV disease cohort (age >= 50)
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
            # No prior CVD group (age >= 60)
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
            Criteria(name="Type 1 Diabetes", domain="Condition",
                     entity_text="Type 1 Diabetes Mellitus", logic_type="ABSENCE"),
            Criteria(name="Elevated Calcitonin", domain="Measurement",
                     entity_text="calcitonin", logic_type="ABSENCE"),
            Criteria(name="Prior GLP-1 RA/pramlintide/DPP-4i", domain="Drug",
                     entity_text="GLP-1 receptor agonist, pramlintide, or DPP-4 inhibitor", logic_type="ABSENCE"),
            Criteria(name="Non-allowed insulin", domain="Drug",
                     entity_text="insulin", logic_type="ABSENCE"),
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
                     entity_text="end-stage liver disease, acute hepatic failure, acute necrosis of liver, toxic hepatitis, esophageal varices, jaundice, ascites, cirrhosis of liver, viral hepatitis", logic_type="ABSENCE"),
            Criteria(name="Organ transplant (condition)", domain="Condition",
                     entity_text="transplanted organ present, bone marrow transplant present, transplanted heart present, transplanted kidney present, transplanted liver present, transplanted lung present, transplanted organ failure, transplanted organ rejection", logic_type="ABSENCE"),
            Criteria(name="Organ transplant (procedure)", domain="Procedure",
                     entity_text="solid organ transplant, transplant of kidney, transplantation of bone marrow, transplantation of heart, transplantation of liver, lung transplant", logic_type="ABSENCE"),
            Criteria(name="Malignant neoplasm", domain="Condition",
                     entity_text="malignant neoplastic disease", logic_type="ABSENCE"),
            Criteria(name="MEN2 or MTC", domain="Condition",
                     entity_text="multiple endocrine neoplasia type 2 or medullary thyroid carcinoma", logic_type="ABSENCE"),
            Criteria(name="Pregnancy", domain="Condition",
                     entity_text="pregnancy, childbirth and puerperium finding", logic_type="ABSENCE"),
            Criteria(name="Substance abuse", domain="Condition",
                     entity_text="drug abuse, drug dependence, substance abuse", logic_type="ABSENCE"),
            Criteria(name="Severe renal impairment (measurement)", domain="Measurement",
                     entity_text="glomerular filtration rate, creatinine renal clearance", logic_type="ABSENCE",
                     value_constraint=ValueConstraint(op="lt", value=30, unit_text="mL/min/1.73m2")),
            Criteria(name="Severe renal impairment (CKD 4-5)", domain="Condition",
                     entity_text="chronic kidney disease stage 4, chronic kidney disease stage 5", logic_type="ABSENCE"),
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

print(f"  Inclusion: {len(ir.target.inclusion_rules)} rules")
print(f"  Exclusion: {len(ir.target.exclusion_rules)} rules")

# ============================================================
# Step 2: Run Planner
# ============================================================
print("\n" + "=" * 60)
print("STEP 2: Planner (Composite Decomposition)")
print("=" * 60)

planner = CriteriaPlanner()
ir = planner.plan(ir)

# Count total entities
def collect_entities(cohort):
    entities = set()
    for rule in cohort.inclusion_rules + cohort.exclusion_rules:
        if rule.sub_criteria:
            for sc in rule.sub_criteria:
                if sc.entity_text:
                    entities.add(sc.entity_text)
        elif rule.entity_text:
            entities.add(rule.entity_text)
    if cohort.primary_criteria.entity_text:
        entities.add(cohort.primary_criteria.entity_text)
    return entities

target_entities = collect_entities(ir.target)
print(f"  Target entities after Planner: {len(target_entities)}")

# ============================================================
# Step 3: Agent 2 — OMOP Mapping
# ============================================================
print("\n" + "=" * 60)
print("STEP 3: Agent 2 (OMOP Concept Mapping)")
print("=" * 60)

def collect_mapping_entities(cohort, source_label):
    entities = []
    if cohort.primary_criteria.entity_text:
        entities.append({
            "entity_text": cohort.primary_criteria.entity_text,
            "domain": cohort.primary_criteria.domain,
            "source": source_label,
            "parent_rule": None,
        })
    for rule in cohort.inclusion_rules + cohort.exclusion_rules:
        if rule.sub_criteria:
            for sc in rule.sub_criteria:
                if sc.entity_text:
                    entities.append({
                        "entity_text": sc.entity_text,
                        "domain": sc.domain,
                        "source": source_label,
                        "parent_rule": rule.name,
                    })
        elif rule.entity_text:
            entities.append({
                "entity_text": rule.entity_text,
                "domain": rule.domain,
                "source": source_label,
                "parent_rule": None,
            })
    return entities

all_entities = collect_mapping_entities(ir.target, "target")
if ir.comparator:
    all_entities += collect_mapping_entities(ir.comparator, "comparator")

print(f"  Total entities to map: {len(all_entities)}")

agent2 = get_agent2()
cache = Agent2Cache()
if args.no_cache:
    cache.clear()
    print("  ⚠️  Cache disabled (--no-cache)")
else:
    print(f"  📦 Cache: {cache.size} entries")

t_start = time.time()
mapped_sets = []
cache_hits = 0

for i, ent in enumerate(all_entities):
    entity_text = ent["entity_text"]
    domain_hint = ent.get("domain")
    
    # Check cache
    cached_ids = cache.get(entity_text, domain_hint)
    if cached_ids is not None:
        cache_hits += 1
        concept_ids = cached_ids
        status = "💾"
    else:
        # Cache miss — call Agent 2
        try:
            concept_ids = agent2.process(entity_text)
            cache.put(entity_text, domain_hint, concept_ids or [])
        except Exception as e:
            print(f"  [{i+1}/{len(all_entities)}] ❌ {entity_text[:50]}... Error: {e}")
            continue
        status = "✅" if concept_ids else "⚠"
    
    if concept_ids:
        mapped_sets.append({
            "id": i + 1,
            "name": entity_text,
            "domain": ent["domain"],
            "concept_ids": concept_ids,
            "parent_rule": ent.get("parent_rule"),
        })
    
    print(f"  [{i+1}/{len(all_entities)}] {status} {entity_text[:50]}... → {len(concept_ids or [])} concepts")

t_elapsed = time.time() - t_start
print(f"\n  Mapped: {len(mapped_sets)} concept sets")
print(f"  Cache hits: {cache_hits}/{len(all_entities)} ({cache_hits*100//max(1,len(all_entities))}%)")
print(f"  Time: {t_elapsed:.1f}s")

# ============================================================
# Step 4: Consolidator
# ============================================================
print("\n" + "=" * 60)
print("STEP 4: Consolidator")
print("=" * 60)

try:
    from src.agents.conceptset.ontology_search import get_ontology_search
    consolidator = ConceptSetConsolidator(ontology_search=get_ontology_search())
    mapped_sets = consolidator.consolidate(mapped_sets)
    print(f"  After consolidation: {len(mapped_sets)} sets")
except Exception as e:
    print(f"  ⚠ Consolidation skipped: {e}")

# ============================================================
# Step 5: Registry + Agent 3 + Agent 4
# ============================================================
print("\n" + "=" * 60)
print("STEP 5: Registry → Agent 3 → Agent 4")
print("=" * 60)

# Register
registered = []
seen_ids = set()
for ms in mapped_sets:
    concepts = [
        RegisteredConcept(
            concept_id=cid,
            concept_name=ms["name"],
            domain_id=ms["domain"],
            vocabulary_id="SNOMED",
            include_descendants=True
        )
        for cid in ms.get("concept_ids", [])
    ]
    if concepts:
        result = registry.register(name=ms["name"], concepts=concepts, source_entity_text=ms["name"])
        if result.concept_set and result.concept_set.id not in seen_ids:
            seen_ids.add(result.concept_set.id)
            registered.append(result.concept_set)

print(f"  Registered: {len(registered)} sets (deduped)")

# Agent 3
assembly_result = agent3.assemble(ir, registered)
circe_json = assembly_result.circe_json
print(f"  Circe JSON ConceptSets: {len(circe_json.get('ConceptSets', []))}")

# Agent 4
validation = agent4.validate(circe_json)
print(agent4.format_report(validation))

# Save
output_path = "data/sample/LEADER/ARTEMIS_LEADER_design_paper_e2e.json"
os.makedirs(os.path.dirname(output_path), exist_ok=True)
with open(output_path, "w") as f:
    json.dump(circe_json, f, indent=2, ensure_ascii=False)
print(f"💾 Saved: {output_path}")

# ============================================================
# Step 6: TROY Comparison
# ============================================================
print("\n" + "=" * 60)
print("STEP 6: TROY vs ARTEMIS Comparison")
print("=" * 60)

# Concept ID comparison
artemis_concept_ids = set()
artemis_cs_by_name = {}
for cs in registered:
    concept_ids = {c.concept_id for c in cs.concepts}
    artemis_concept_ids |= concept_ids
    artemis_cs_by_name[cs.name] = concept_ids

overlap = troy_concept_ids & artemis_concept_ids
print(f"  TROY concept IDs:  {len(troy_concept_ids)}")
print(f"  ARTEMIS concept IDs: {len(artemis_concept_ids)}")
print(f"  Overlapping IDs:   {len(overlap)} ({100*len(overlap)/max(len(troy_concept_ids),1):.1f}%)")

# Name comparison
troy_names_lower = {n.lower().strip() for n in troy_cs_names}
artemis_names_lower = {n.lower().strip() for n in artemis_cs_by_name.keys()}

matched = set()
for artemis_name in artemis_names_lower:
    for troy_name in troy_names_lower:
        if artemis_name in troy_name or troy_name in artemis_name:
            matched.add((artemis_name, troy_name))

troy_matched = {m[1] for m in matched}
troy_only = troy_names_lower - troy_matched
artemis_only = artemis_names_lower - {m[0] for m in matched}

print(f"\n✅ MATCHED ({len(troy_matched)} TROY concepts covered):")
for t, r in sorted(matched):
    print(f"  ✅ {t} ↔ {r}")

print(f"\n❌ TROY-only ({len(troy_only)}):")
for name in sorted(troy_only):
    print(f"  - {name}")

print(f"\n🆕 ARTEMIS-only ({len(artemis_only)}):")
for name in sorted(artemis_only)[:30]:
    print(f"  - {name}")
if len(artemis_only) > 30:
    print(f"  ... and {len(artemis_only)-30} more")

# ============================================================
# Summary
# ============================================================
print(f"\n{'='*60}")
print(f"📊 DESIGN PAPER E2E SUMMARY")
print(f"{'='*60}")
n_inc = len(ir.target.inclusion_rules)
n_exc = len(ir.target.exclusion_rules)
print(f"  Input:       {n_inc} inclusion + {n_exc} exclusion = {n_inc + n_exc} criteria")
print(f"  After Plan:  {len(target_entities)} entities")
print(f"  Mapped:      {len(mapped_sets)} concept sets")
print(f"  Registered:  {len(registered)} (deduped)")
print(f"  Valid:        {validation.valid}")
print(f"  TROY name:    {len(troy_matched)}/{len(troy_names_lower)} ({100*len(troy_matched)/len(troy_names_lower):.1f}%)")
print(f"  TROY concept: {len(overlap)}/{len(troy_concept_ids)} ({100*len(overlap)/len(troy_concept_ids):.1f}%)")
