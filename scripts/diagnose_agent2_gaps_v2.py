"""
Diagnostic V2: Agent 2 OMOP Mapping Gap Analysis (Resolved Set Comparison).

Unlike V1 which compared raw seed IDs, V2 resolves BOTH TROY and Agent 2
concept sets through CONCEPT_ANCESTOR (simulating includeDescendants=true)
before comparison. This matches how ATLAS actually evaluates concept sets.

Categories:
  A) Full Match — Agent 2's resolved set covers ≥ TROY's resolved set
  B) Partial Match — some overlap
  C) Wrong — Agent 2 returned concepts with 0 overlap after resolution
  D) No Results — Agent 2 returned nothing
"""
import json
import sys
import os
import time
import psycopg2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from src.agents.agent2.workflow import get_agent2

# ============================================================
# Setup: DB connection
# ============================================================
conn = psycopg2.connect(
    host=os.environ.get('OMOP_DB_HOST', 'localhost'),
    port=int(os.environ.get('OMOP_DB_PORT', '5432')),
    dbname=os.environ.get('OMOP_DB_NAME', 'postgres'),
    user=os.environ.get('OMOP_DB_USER', 'postgres'),
    password=os.environ.get('OMOP_DB_PASS', 'mypass'),
)
cur = conn.cursor()
SCHEMA = os.environ.get("CDM_SCHEMA", "synthea23m")


def resolve_concept_set(concept_ids: list, include_descendants: bool = True) -> set:
    """
    Resolve a concept set by expanding via CONCEPT_ANCESTOR.
    Simulates ATLAS/Circe includeDescendants behavior.
    
    Returns the full resolved set (seeds + all standard descendants).
    """
    if not concept_ids:
        return set()
    
    resolved = set(concept_ids)
    
    if include_descendants and concept_ids:
        cur.execute(f"""
            SELECT DISTINCT ca.descendant_concept_id
            FROM {SCHEMA}.concept_ancestor ca
            JOIN {SCHEMA}.concept c ON ca.descendant_concept_id = c.concept_id
            WHERE ca.ancestor_concept_id = ANY(%s)
              AND c.standard_concept = 'S'
        """, (list(concept_ids),))
        for row in cur.fetchall():
            resolved.add(row[0])
    
    return resolved


def jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def recall_score(predicted: set, reference: set) -> float:
    """What fraction of reference items are covered by predicted."""
    if not reference:
        return 1.0
    return len(predicted & reference) / len(reference)


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
# For each TROY concept set, resolve TROY then compare
# ============================================================
agent2 = get_agent2()

results = []
start_time = time.time()

for i, cs in enumerate(unique_troy):
    name = cs["name"]
    
    # Parse TROY items with includeDescendants flags
    troy_seed_ids = set()
    troy_items_with_desc = []
    troy_concepts_info = []
    
    for item in cs.get("expression", {}).get("items", []):
        c = item.get("concept", {})
        cid = c.get("CONCEPT_ID")
        cname = c.get("CONCEPT_NAME", "")
        domain = c.get("DOMAIN_ID", "")
        vocab = c.get("VOCABULARY_ID", "")
        inc_desc = item.get("includeDescendants", False)
        is_excluded = item.get("isExcluded", False)
        
        if cid and not is_excluded:
            troy_seed_ids.add(cid)
            troy_items_with_desc.append({
                "concept_id": cid,
                "includeDescendants": inc_desc,
            })
            troy_concepts_info.append({
                "id": cid, "name": cname, 
                "domain": domain, "vocab": vocab,
                "includeDescendants": inc_desc,
            })
    
    # Resolve TROY set (expand with descendants where flagged)
    troy_resolved = set(troy_seed_ids)
    desc_ids = [item["concept_id"] for item in troy_items_with_desc if item["includeDescendants"]]
    if desc_ids:
        troy_resolved |= resolve_concept_set(desc_ids, include_descendants=True)
    
    # No-descendants IDs are already in troy_resolved from initial add
    
    print(f"\n[{i+1}/{len(unique_troy)}] TROY: '{name}' ({len(troy_seed_ids)} seeds → {len(troy_resolved)} resolved)")
    
    # Process with Agent 2
    search_name = name.replace("[TROY] ", "").replace("COPY OF: ", "").replace("Copy of: ", "")
    
    try:
        t0 = time.time()
        artemis_seed_ids = agent2.process(search_name)
        elapsed = time.time() - t0
        
        # Resolve Agent 2 output (always includeDescendants=True per our model default)
        artemis_resolved = resolve_concept_set(artemis_seed_ids, include_descendants=True)
        
        # Compute metrics
        overlap = artemis_resolved & troy_resolved
        recall = recall_score(artemis_resolved, troy_resolved)
        jaccard = jaccard_similarity(artemis_resolved, troy_resolved)
        seed_overlap = set(artemis_seed_ids) & troy_seed_ids
        
        result = {
            "troy_name": name,
            "search_name": search_name,
            "troy_seed_count": len(troy_seed_ids),
            "troy_resolved_count": len(troy_resolved),
            "artemis_seed_count": len(artemis_seed_ids),
            "artemis_seed_ids": sorted(artemis_seed_ids),
            "artemis_resolved_count": len(artemis_resolved),
            "overlap_count": len(overlap),
            "recall": round(recall, 3),
            "jaccard": round(jaccard, 3),
            "seed_overlap_count": len(seed_overlap),
            "elapsed_sec": round(elapsed, 1),
        }
        
        # Categorize based on recall of resolved sets
        if len(artemis_seed_ids) == 0:
            result["category"] = "D_NO_RESULTS"
            print(f"  ❌ No results ({elapsed:.1f}s)")
        elif recall >= 0.8:
            result["category"] = "FULL_MATCH"
            print(f"  ✅ Full: recall={recall:.0%} ({len(overlap)}/{len(troy_resolved)}) Jaccard={jaccard:.2f} [{elapsed:.1f}s]")
        elif recall > 0:
            result["category"] = "PARTIAL_MATCH"
            print(f"  🟡 Partial: recall={recall:.0%} ({len(overlap)}/{len(troy_resolved)}) Jaccard={jaccard:.2f} [{elapsed:.1f}s]")
        else:
            result["category"] = "WRONG"
            print(f"  ⚠ Wrong: 0 overlap after resolution ({len(artemis_resolved)} vs {len(troy_resolved)}) [{elapsed:.1f}s]")
            # Show what TROY expected vs what Agent 2 returned
            troy_sample = troy_concepts_info[:3]
            sample_strs = ["{} ({})".format(c["name"], c["id"]) for c in troy_sample]
            print(f"    TROY seeds: {sample_strs}...")
            print(f"    Agent2 seeds: {sorted(artemis_seed_ids)[:5]}...")
        
        results.append(result)
    except Exception as e:
        results.append({
            "troy_name": name, "search_name": search_name,
            "category": "E_ERROR", "error": str(e),
            "troy_seed_count": len(troy_seed_ids),
            "troy_resolved_count": len(troy_resolved),
        })
        print(f"  ❌ Error: {e}")

total_time = time.time() - start_time

# ============================================================
# Summary
# ============================================================
categories = {}
for r in results:
    cat = r["category"]
    categories[cat] = categories.get(cat, 0) + 1

recalls = [r.get("recall", 0) for r in results if "recall" in r]
avg_recall = sum(recalls) / len(recalls) if recalls else 0

print(f"\n{'='*60}")
print(f"📊 RESOLVED SET COMPARISON (V2)")
print(f"{'='*60}")
for cat, count in sorted(categories.items()):
    label = {
        "FULL_MATCH": "✅ Full match (recall ≥ 80%)",
        "PARTIAL_MATCH": "🟡 Partial match (0 < recall < 80%)",
        "WRONG": "⚠ Wrong (0% overlap after resolution)",
        "D_NO_RESULTS": "❌ No results",
        "E_ERROR": "❌ Error",
    }.get(cat, cat)
    print(f"  {label}: {count}")

print(f"\n  📈 Average recall: {avg_recall:.1%}")
print(f"  ⏱  Total time: {total_time/60:.1f} min")

# Detailed breakdown of non-full matches
print(f"\n{'='*60}")
print(f"📋 DETAILED NON-FULL MATCHES")
print(f"{'='*60}")
for r in results:
    if r.get("category") in ("PARTIAL_MATCH", "WRONG"):
        recall = r.get("recall", 0)
        print(f"\n  {r['troy_name']}: recall={recall:.0%}")
        print(f"    TROY: {r['troy_seed_count']} seeds → {r['troy_resolved_count']} resolved")
        print(f"    Agent2: {r['artemis_seed_count']} seeds → {r['artemis_resolved_count']} resolved")
        print(f"    Overlap: {r['overlap_count']}")

# Save
report_path = "data/sample/LEADER/agent2_gap_analysis_v2.json"
os.makedirs(os.path.dirname(report_path), exist_ok=True)
with open(report_path, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\n💾 Detailed report: {report_path}")

conn.close()
