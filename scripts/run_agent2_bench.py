import json, time, sys
sys.path.insert(0, '/app')

with open('/tmp/bench_10.json') as f:
    items = json.load(f)

# Import recommender (full Agent2 RAG+KG+Critic pipeline)
try:
    from src.agents.conceptset.recommender import ConceptSetRecommender
    recommender = ConceptSetRecommender()
    print("[Agent2] Using ConceptSetRecommender (RAG+KG+Critic)", flush=True)
except Exception as e:
    print(f"[Agent2] ConceptSetRecommender failed: {e}", flush=True)
    sys.exit(1)

def extract_concept_ids(response):
    """Extract concept IDs from RecommendationResponse."""
    ids = []
    for rec in response.include_recommendations:
        for item in rec.expression.items:
            if not item.isExcluded:
                ids.append(item.concept_id)
    return ids

results = []
for item in items:
    query = item['concept_set_name']
    domain = item['domain_hint']
    gt = set(item['ground_truth_concept_ids'])
    top_k = max(20, len(gt))
    t0 = time.time()
    try:
        response = recommender.recommend(query, top_k=top_k, include_descendants=True, use_cache=False)
        concept_ids = extract_concept_ids(response)
        cached = response.cached
    except Exception as e:
        concept_ids = []
        cached = False
        print(f"[ERROR] {query}: {e}", flush=True)
    latency = (time.time() - t0) * 1000

    predicted = set(concept_ids)
    tp = len(predicted & gt)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(gt) if gt else 0.0
    f1 = 2*precision*recall/(precision+recall) if (precision+recall) > 0 else 0.0
    hit1 = 1 if concept_ids[:1] and concept_ids[0] in gt else 0
    hit5 = 1 if any(c in gt for c in concept_ids[:5]) else 0
    hit10 = 1 if any(c in gt for c in concept_ids[:10]) else 0

    results.append({
        'id': item['id'], 'concept_set_name': query, 'domain': domain,
        'gt_count': len(gt), 'predicted': list(predicted),
        'precision': round(precision,4), 'recall': round(recall,4), 'f1': round(f1,4),
        'hit1': hit1, 'hit5': hit5, 'hit10': hit10, 'latency_ms': round(latency,1),
        'cached': cached
    })
    print(f"[Agent2] {query[:40]:40s} F1={f1:.3f} lat={latency/1000:.1f}s pred={len(predicted)} cached={cached}", flush=True)

avg_p = sum(r['precision'] for r in results)/len(results)
avg_r = sum(r['recall'] for r in results)/len(results)
avg_f1 = sum(r['f1'] for r in results)/len(results)
avg_lat = sum(r['latency_ms'] for r in results)/len(results)
h1 = sum(r['hit1'] for r in results)/len(results)
h5 = sum(r['hit5'] for r in results)/len(results)
h10 = sum(r['hit10'] for r in results)/len(results)

print(f"\n=== Agent2 RESULTS ===", flush=True)
print(f"Precision: {avg_p:.4f}  Recall: {avg_r:.4f}  F1: {avg_f1:.4f}", flush=True)
print(f"Hit@1: {h1:.3f}  Hit@5: {h5:.3f}  Hit@10: {h10:.3f}", flush=True)
print(f"Latency: {avg_lat:.0f}ms/item  ({avg_lat/1000:.1f}s/item)", flush=True)

with open('/tmp/agent2_results.json', 'w') as f:
    json.dump({
        'mapper': 'Agent2_ConceptSetRecommender',
        'results': results,
        'summary': {
            'precision': avg_p, 'recall': avg_r, 'f1': avg_f1,
            'hit1': h1, 'hit5': h5, 'hit10': h10, 'latency_ms': avg_lat
        }
    }, f, indent=2)
print("Saved to /tmp/agent2_results.json", flush=True)
