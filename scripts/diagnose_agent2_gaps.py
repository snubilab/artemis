"""
Diagnostic: Agent 2 OMOP Mapping Gap Analysis.

For each TROY ConceptSet, trace what ARTEMIS Agent 2 actually returned.
Categorize failure modes:
  A) Entity not in IR (Agent 1/Planner gap)
  B) Entity in IR but Agent 2 returned wrong concepts
  C) Entity in IR, correct domain, but different concept IDs
  D) Agent 2 returned 0 results
  F) Functional match via hierarchy (ancestor/descendant, sep≤2)

SUPERSEDED IN PLACE (note added 2026-08-09). What this IS for: a readable taxonomy of
WHY a mapping failed, which no scoring tool provides. What it is NOT: current.
diagnose_agent2_gaps_v2.py documents the defect here -- this version compares raw seed
concepts, which does not match how ATLAS actually resolves a concept set, so the
categories can be assigned on the wrong basis. Run scripts/diagnose_agent2_gaps_v2.py
instead.

Either way this is a diagnostic, not a score. The measure of record is
per-eligibility-criterion 1:1 concept-set overlap against data/gold/, macro-averaged --
scripts/conceptset_overlap_eval.py --mode closure (see AGENTS.md EVALUATION).
"""
import json
import sys
import os
import psycopg2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from src.agents.agent2.workflow import get_agent2

# ============================================================
# Setup: DB connection for hierarchy checks
# ============================================================
conn = psycopg2.connect(
    host='localhost', port=5432,
    dbname='postgres', user='postgres', password='mypass'
)
cur = conn.cursor()
SCHEMA = "synthea_cdm"

def check_hierarchy_match(artemis_ids, troy_ids, max_sep=2):
    """
    Check if any artemis concept is ancestor/descendant of any TROY concept.
    Returns (exact_overlap, functional_matches) tuple.
    """
    exact_overlap = set(artemis_ids) & troy_ids
    functional = set()
    
    remaining_artemis = set(artemis_ids) - exact_overlap
    remaining_troy = troy_ids - exact_overlap
    
    if not remaining_artemis or not remaining_troy:
        return exact_overlap, functional
    
    # Batch query: check all artemis-vs-troy pairs at once
    artemis_list = list(remaining_artemis)
    troy_list = list(remaining_troy)
    
    # artemis is ancestor of troy?
    cur.execute(f"""
        SELECT ancestor_concept_id, descendant_concept_id, min_levels_of_separation
        FROM {SCHEMA}.concept_ancestor
        WHERE ancestor_concept_id = ANY(%s) 
          AND descendant_concept_id = ANY(%s)
          AND min_levels_of_separation > 0
          AND min_levels_of_separation <= %s
    """, (artemis_list, troy_list, max_sep))
    for row in cur.fetchall():
        functional.add(row[0])  # artemis id that functionally matches
    
    # artemis is descendant of troy?
    cur.execute(f"""
        SELECT descendant_concept_id, ancestor_concept_id, min_levels_of_separation
        FROM {SCHEMA}.concept_ancestor
        WHERE descendant_concept_id = ANY(%s) 
          AND ancestor_concept_id = ANY(%s)
          AND min_levels_of_separation > 0
          AND min_levels_of_separation <= %s
    """, (artemis_list, troy_list, max_sep))
    for row in cur.fetchall():
        functional.add(row[0])  # artemis id that functionally matches
    
    return exact_overlap, functional

# ============================================================
# Load TROY reference
# ============================================================
troy_path = "data/sample/LEADER/[TROY] Liraglutide (LEADER) v3.4.json"
with open(troy_path) as f:
    troy = json.load(f)

troy_concept_sets = troy.get("ConceptSets", [])
print(f"TROY ConceptSets: {len(troy_concept_sets)}")

# Deduplicate by name
seen = set()
unique_troy = []
for cs in troy_concept_sets:
    name = cs["name"]
    if name not in seen:
        seen.add(name)
        unique_troy.append(cs)
print(f"Unique by name: {len(unique_troy)}")

# ============================================================
# For each TROY concept set, attempt Agent 2 mapping
# ============================================================
agent2 = get_agent2()

results = []
for i, cs in enumerate(unique_troy):
    name = cs["name"]
    troy_ids = set()
    troy_concepts = []
    for item in cs.get("expression", {}).get("items", []):
        c = item.get("concept", {})
        cid = c.get("CONCEPT_ID")
        cname = c.get("CONCEPT_NAME", "")
        domain = c.get("DOMAIN_ID", "")
        vocab = c.get("VOCABULARY_ID", "")
        if cid:
            troy_ids.add(cid)
            troy_concepts.append({
                "id": cid, "name": cname, 
                "domain": domain, "vocab": vocab
            })
    
    print(f"\n[{i+1}/{len(unique_troy)}] TROY: '{name}' ({len(troy_ids)} concepts)")
    
    search_name = name.replace("[TROY] ", "").replace("Copy of: ", "")
    
    try:
        artemis_ids = agent2.process(search_name)
        exact_overlap, functional = check_hierarchy_match(artemis_ids, troy_ids)
        total_match = len(exact_overlap) + len(functional)
        
        result = {
            "troy_name": name,
            "search_name": search_name,
            "troy_ids": sorted(troy_ids),
            "troy_concepts": troy_concepts,
            "artemis_ids": sorted(artemis_ids),
            "exact_overlap": sorted(exact_overlap),
            "functional_match_ids": sorted(functional),
            "troy_count": len(troy_ids),
            "artemis_count": len(artemis_ids),
            "exact_count": len(exact_overlap),
            "functional_count": len(functional),
            "total_match_count": total_match,
        }
        
        # Categorize
        if len(artemis_ids) == 0:
            result["category"] = "D_NO_RESULTS"
            print(f"  ❌ Category D: Agent 2 returned 0 results")
        elif total_match == 0:
            result["category"] = "B_WRONG_CONCEPTS"
            print(f"  ⚠ Category B: {len(artemis_ids)} concepts, NONE match TROY")
            print(f"    TROY expects: {troy_concepts[:3]}...")
            print(f"    Agent 2 got:  {artemis_ids[:5]}...")
        elif total_match >= len(troy_ids):
            result["category"] = "FULL_MATCH"
            if functional:
                print(f"  ✅ Full match: {len(exact_overlap)} exact + {len(functional)} hierarchy")
            else:
                print(f"  ✅ Full match: {len(exact_overlap)} IDs")
        elif exact_overlap and not functional:
            result["category"] = "C_PARTIAL_MATCH"
            print(f"  🟡 Partial: {len(exact_overlap)}/{len(troy_ids)} exact")
        else:
            result["category"] = "C_PARTIAL_MATCH"
            print(f"  🟡 Partial: {len(exact_overlap)} exact + {len(functional)} hierarchy = {total_match}/{len(troy_ids)}")
        
        results.append(result)
    except Exception as e:
        results.append({
            "troy_name": name, "search_name": search_name,
            "category": "E_ERROR", "error": str(e),
            "troy_ids": sorted(troy_ids), "troy_count": len(troy_ids),
        })
        print(f"  ❌ Error: {e}")

# ============================================================
# Summary
# ============================================================
categories = {}
for r in results:
    cat = r["category"]
    categories[cat] = categories.get(cat, 0) + 1

total_exact = sum(r.get("exact_count", 0) for r in results)
total_functional = sum(r.get("functional_count", 0) for r in results)

print(f"\n{'='*60}")
print(f"📊 FAILURE MODE ANALYSIS (Hierarchy-Aware)")
print(f"{'='*60}")
for cat, count in sorted(categories.items()):
    label = {
        "FULL_MATCH": "✅ Full match (exact + hierarchy)",
        "C_PARTIAL_MATCH": "🟡 Partial match",
        "B_WRONG_CONCEPTS": "⚠ Wrong concepts (non-overlapping)",
        "D_NO_RESULTS": "❌ No results from Agent 2",
        "E_ERROR": "❌ Error",
    }.get(cat, cat)
    print(f"  {label}: {count}")
print(f"\n  📈 Total exact ID matches: {total_exact}")
print(f"  📈 Total hierarchy matches (sep≤2): {total_functional}")

# Detailed breakdown
print(f"\n{'='*60}")
print(f"📋 DETAILED CATEGORY B (Wrong Concepts)")
print(f"{'='*60}")
for r in results:
    if r["category"] == "B_WRONG_CONCEPTS":
        print(f"\n  TROY: '{r['troy_name']}'")
        print(f"    TROY IDs: {r['troy_ids'][:5]}...")
        print(f"    TROY concepts: {[c['name'] for c in r.get('troy_concepts',[])[:3]]}...")
        print(f"    Agent 2 IDs: {r['artemis_ids'][:5]}...")

print(f"\n{'='*60}")
print(f"📋 DETAILED CATEGORY D (No Results)")
print(f"{'='*60}")
for r in results:
    if r["category"] == "D_NO_RESULTS":
        print(f"  ❌ '{r['troy_name']}' (expected {r['troy_count']} concepts)")

# Save detailed report
report_path = "data/sample/LEADER/agent2_gap_analysis.json"
with open(report_path, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\n💾 Detailed report: {report_path}")

conn.close()
