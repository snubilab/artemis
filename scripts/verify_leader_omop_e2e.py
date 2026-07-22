"""
LEADER Full Pipeline E2E — Agent 2 OMOP Mapping + TROY Concept-Level Comparison.

Runs the entire pipeline:
  Agent 1 (PubMed enrichment) → Planner → Agent 2 (OMOP) → Consolidator → 
  Registry → Agent 3 (Circe JSON) → Agent 4 (Validation) → TROY comparison

Then compares the resulting ConceptSets at the OMOP concept level against TROY.
"""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from src.pipeline.cohort_pipeline import CohortPipeline

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
print(f"TROY ConceptSets (unique): {len(troy_cs_names)}")

# Collect all TROY concept IDs
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

print(f"TROY total unique concept IDs: {len(troy_concept_ids)}")

# ============================================================
# Step 1: Run Full Pipeline
# ============================================================
print("\n" + "=" * 60)
print("STEP 1: Run Full ARTEMIS Pipeline (NCT01179048)")
print("=" * 60)

pipeline = CohortPipeline()
result = pipeline.run("NCT01179048")

print(f"\n{'='*60}")
print("STEP 2: Pipeline Results")
print(f"{'='*60}")
print(f"  Valid: {result.is_valid}")
print(f"  ConceptSets: {len(result.concept_sets)}")

# ============================================================
# Step 3: Compare at Concept Level
# ============================================================
print(f"\n{'='*60}")
print("STEP 3: TROY vs ARTEMIS Concept-Level Comparison")
print(f"{'='*60}")

# Collect ARTEMIS concept IDs
artemis_concept_ids = set()
artemis_cs_by_name = {}
for cs in result.concept_sets:
    name = cs.name
    concept_ids = set()
    for item in cs.concepts:
        if hasattr(item, 'concept_id'):
            concept_ids.add(item.concept_id)
            artemis_concept_ids.add(item.concept_id)
    artemis_cs_by_name[name] = concept_ids

print(f"  TROY concept IDs:  {len(troy_concept_ids)}")
print(f"  ARTEMIS concept IDs: {len(artemis_concept_ids)}")
overlap = troy_concept_ids & artemis_concept_ids
print(f"  Overlapping IDs:   {len(overlap)}")

if troy_concept_ids:
    print(f"  Concept ID coverage: {len(overlap)}/{len(troy_concept_ids)} "
          f"({100*len(overlap)/len(troy_concept_ids):.1f}%)")

# Name-level comparison
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

print(f"\n✅ NAME-MATCHED ({len(troy_matched)} TROY concepts covered):")
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
# Step 4: Save generated Circe JSON
# ============================================================
output_path = "data/sample/LEADER/ARTEMIS_LEADER_e2e.json"
os.makedirs(os.path.dirname(output_path), exist_ok=True)
with open(output_path, "w") as f:
    json.dump(result.circe_json, f, indent=2, ensure_ascii=False)
print(f"\n💾 Saved ARTEMIS Circe JSON to: {output_path}")

# ============================================================
# Summary
# ============================================================
print(f"\n{'='*60}")
print(f"📊 FULL PIPELINE E2E SUMMARY")
print(f"{'='*60}")
print(f"  Pipeline valid: {result.is_valid}")
print(f"  ConceptSets generated: {len(result.concept_sets)}")
print(f"  TROY concepts matched (by name): {len(troy_matched)}/{len(troy_names_lower)}")
if troy_concept_ids:
    print(f"  TROY concepts matched (by ID):   {len(overlap)}/{len(troy_concept_ids)}")
