"""
Phase 4: Hierarchy-Aware TROY vs Agent 2 Comparison.

For each TROY ConceptSet where Agent 2 returned a "wrong" concept,
check if Agent 2's concept is an ancestor or descendant of any TROY concept.
This reveals "functional matches" that the ID-level comparison missed.
"""
import json
import psycopg2

# Load gap analysis results
with open("data/sample/LEADER/agent2_gap_analysis.json") as f:
    results = json.load(f)

# Connect to OMOP DB
conn = psycopg2.connect(
    host='localhost', port=5432,
    dbname='postgres', user='postgres', password='mypass'
)
cur = conn.cursor()

SCHEMA = "synthea_cdm"

def check_hierarchy(concept_a: int, concept_b: int) -> dict:
    """Check if A is ancestor/descendant of B."""
    # A is ancestor of B?
    cur.execute(f"""
        SELECT min_levels_of_separation 
        FROM {SCHEMA}.concept_ancestor 
        WHERE ancestor_concept_id = %s AND descendant_concept_id = %s
        LIMIT 1
    """, (concept_a, concept_b))
    row = cur.fetchone()
    if row and row[0] > 0:
        return {"relation": "ancestor_of", "separation": row[0]}
    
    # B is ancestor of A?
    cur.execute(f"""
        SELECT min_levels_of_separation 
        FROM {SCHEMA}.concept_ancestor 
        WHERE ancestor_concept_id = %s AND descendant_concept_id = %s
        LIMIT 1
    """, (concept_b, concept_a))
    row = cur.fetchone()
    if row and row[0] > 0:
        return {"relation": "descendant_of", "separation": row[0]}
    
    return {"relation": "unrelated", "separation": -1}

def lookup_concept(concept_id: int) -> dict:
    """Look up concept name/vocabulary in OMOP."""
    cur.execute(f"""
        SELECT concept_name, vocabulary_id, domain_id, standard_concept
        FROM {SCHEMA}.concept WHERE concept_id = %s
    """, (concept_id,))
    row = cur.fetchone()
    if row:
        return {"name": row[0], "vocab": row[1], "domain": row[2], "standard": row[3]}
    return {"name": "NOT FOUND", "vocab": "?", "domain": "?", "standard": "?"}

# ============================================================
# Hierarchy analysis for category B (wrong concepts)
# ============================================================
print("=" * 80)
print("HIERARCHY-AWARE COMPARISON: Agent 2 vs TROY")
print("=" * 80)

functional_matches = []
true_mismatches = []
partial_hierarchy = []

for r in results:
    if r["category"] not in ("B_WRONG_CONCEPTS", "C_PARTIAL_MATCH"):
        continue
    
    troy_name = r["troy_name"]
    troy_ids = set(r["troy_ids"])
    artemis_ids = r.get("artemis_ids", [])
    
    if not artemis_ids:
        continue
    
    artemis_id = artemis_ids[0]  # Agent 2 returns 1
    artemis_info = lookup_concept(artemis_id)
    
    # Check hierarchy against each TROY concept
    best_relation = None
    best_sep = 999
    best_troy_id = None
    best_troy_name = None
    
    for tid in troy_ids:
        rel = check_hierarchy(artemis_id, tid)
        if rel["relation"] != "unrelated" and rel["separation"] < best_sep:
            best_relation = rel["relation"]
            best_sep = rel["separation"]
            best_troy_id = tid
            troy_info = lookup_concept(tid)
            best_troy_name = troy_info["name"]
    
    entry = {
        "troy_name": troy_name,
        "artemis_id": artemis_id,
        "artemis_name": artemis_info["name"],
        "artemis_vocab": artemis_info["vocab"],
        "artemis_standard": artemis_info["standard"],
        "best_relation": best_relation or "UNRELATED",
        "best_separation": best_sep if best_sep < 999 else -1,
        "best_troy_id": best_troy_id,
        "best_troy_name": best_troy_name,
        "troy_count": len(troy_ids),
    }
    
    if best_relation:
        if best_sep <= 2:
            functional_matches.append(entry)
        else:
            partial_hierarchy.append(entry)
    else:
        true_mismatches.append(entry)

# ============================================================
# Report
# ============================================================
print(f"\n🟢 FUNCTIONAL MATCHES (ancestor/descendant, sep≤2): {len(functional_matches)}")
for e in functional_matches:
    std = f"[{'S' if e['artemis_standard']=='S' else 'NS'}]"
    print(f"  ✅ TROY '{e['troy_name']}' ← Agent2: {e['artemis_name']} (ID={e['artemis_id']}) {std}")
    print(f"     {e['best_relation']} TROY {e['best_troy_name']} (ID={e['best_troy_id']}), sep={e['best_separation']}")

print(f"\n🟡 DISTANT HIERARCHY (sep>2): {len(partial_hierarchy)}")
for e in partial_hierarchy:
    std = f"[{'S' if e['artemis_standard']=='S' else 'NS'}]"
    print(f"  🔗 TROY '{e['troy_name']}' ← Agent2: {e['artemis_name']} (ID={e['artemis_id']}) {std}")
    print(f"     {e['best_relation']} TROY {e['best_troy_name']} (ID={e['best_troy_id']}), sep={e['best_separation']}")

print(f"\n🔴 TRUE MISMATCHES (unrelated): {len(true_mismatches)}")
for e in true_mismatches:
    std = f"[{'S' if e['artemis_standard']=='S' else 'NS'}]"
    troy_concepts = [c['name'] for c in next((r for r in results if r['troy_name']==e['troy_name']), {}).get('troy_concepts',[])][:2]
    print(f"  ❌ TROY '{e['troy_name']}' (expects: {troy_concepts})")
    print(f"     Agent2: {e['artemis_name']} (ID={e['artemis_id']}, vocab={e['artemis_vocab']}) {std}")

# Summary
total_wrong = len(functional_matches) + len(partial_hierarchy) + len(true_mismatches)
print(f"\n{'='*80}")
print(f"📊 SUMMARY")
print(f"{'='*80}")
print(f"  Originally 'Wrong Concepts':    {total_wrong}")
print(f"  🟢 Functional matches (sep≤2):  {len(functional_matches)}")
print(f"  🟡 Distant hierarchy (sep>2):   {len(partial_hierarchy)}")
print(f"  🔴 True mismatches (unrelated): {len(true_mismatches)}")

# Save
report = {
    "functional_matches": functional_matches,
    "partial_hierarchy": partial_hierarchy, 
    "true_mismatches": true_mismatches,
}
with open("data/sample/LEADER/hierarchy_analysis.json", "w") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)
print(f"\n💾 Saved: data/sample/LEADER/hierarchy_analysis.json")

conn.close()
