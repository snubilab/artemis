"""
Benchmark A_direct: Tier 1 Mapping Accuracy — Agent 2 Only (Parallelized)

This script evaluates Agent 2's pure mapping ability by:
  1. Extracting each TROY rule's concept set names as query text
  2. Feeding query text directly to Agent 2 (NO Agent 1 decomposition)
  3. Resolving Agent 2 output with descendants (standard only)
  4. Comparing with TROY's resolved concept set (1:1 per rule)

Usage:
    PIPELINE_MODE=benchmark conda run -n artemis python scripts/benchmark_a_direct.py
"""
import json
import sys
import os
import time
from datetime import datetime
from typing import List, Dict, Any, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from psycopg2.pool import ThreadedConnectionPool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")
os.environ.setdefault("PIPELINE_MODE", "benchmark")

from src.agents.agent2.workflow import get_agent2

# Reuse infrastructure from benchmark_v5
from benchmark_v5 import (
    TROY_PATH, REPORT_DIR, SCHEMA,
    resolve_concept_set,
    map_nonstandard_to_standard,
    TROYRule, extract_troy_rules, get_troy_concept_ids, resolve_troy_rule,
    _clean_rule_name, calculate_semantic_distance,
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS
)

def process_single_rule(rule: TROYRule, troy_json: Dict, db_pool: ThreadedConnectionPool, agent2_cache: Any) -> Dict:
    if rule.is_demographic:
        return {
            "rule_index": rule.index,
            "rule_name": rule.name,
            "status": "DEMOGRAPHIC_SKIP",
            "log": f"[{rule.index+1}] {rule.name}\n  ⏭ Demographic rule — skipped\n"
        }

    conn = db_pool.getconn()
    cur = conn.cursor()
    try:
        # 1. TROY reference
        troy_raw_ids = get_troy_concept_ids(rule, troy_json)
        troy_resolved = resolve_troy_rule(cur, rule, troy_json)
        
        log_lines = []
        log_lines.append(f"[{rule.index+1}] {rule.name}")
        log_lines.append(f"  TROY: {len(troy_raw_ids)} raw → {len(troy_resolved)} resolved")

        # 2. Query text
        clean_name = _clean_rule_name(rule.name)
        cs_names = rule.concept_set_names
        if cs_names:
            query_texts = list(set(cs_names))
        else:
            query_texts = [clean_name]

        log_lines.append(f"  Query ({len(query_texts)}): {query_texts}")

        # 3. Agent 2 map
        all_agent2_ids = []
        all_overbroad_ids = set()
        sub_results = []
        total_ms = 0.0
        new_cache_entries = []
        rule_cache_hits = 0
        rule_cache_misses = 0

        for qt in query_texts:
            cached_ids = agent2_cache.get(qt) if agent2_cache else None
            if cached_ids is not None:
                ids = cached_ids
                meta = {"processing_ms": 0, "cached": True}
                rule_cache_hits += 1
            else:
                _a2 = get_agent2()
                _start = time.time()
                try:
                    query_domain = rule.cs_domains.get(qt, rule.domain)
                    _detail = _a2.process_with_details(qt, domain_hint=query_domain)
                    ids = _detail.concept_ids
                    meta = {"processing_ms": _detail.processing_time_ms}
                    if _detail.overbroad_concept_ids:
                        all_overbroad_ids.update(_detail.overbroad_concept_ids)
                except Exception as e:
                    ids = []
                    meta = {"error": str(e), "processing_ms": (time.time() - _start) * 1000}
                rule_cache_misses += 1
                if agent2_cache and ids:
                    new_cache_entries.append({"entity_text": qt, "domain_hint": None, "concept_ids": ids})

            all_agent2_ids.extend(ids)
            total_ms += meta.get("processing_ms", 0)
            cache_tag = " [cached]" if meta.get("cached") else ""
            sub_results.append({
                "query_text": qt,
                "concept_ids": ids,
                "count": len(ids),
                **{k: v for k, v in meta.items() if k != "cached"},
            })
            log_lines.append(f"    → {qt}: {len(ids)} raw concepts{cache_tag}")
        
        if new_cache_entries and agent2_cache:
            agent2_cache.put_batch(new_cache_entries)

        # 4. Resolve Agent 2
        no_expand_ids = set()
        if all_agent2_ids:
            agent2_std_ids, _ = map_nonstandard_to_standard(cur, all_agent2_ids)
            if all_overbroad_ids:
                overbroad_std, _ = map_nonstandard_to_standard(cur, list(all_overbroad_ids))
                no_expand_ids = overbroad_std
                log_lines.append(f"    ⚠️  {len(no_expand_ids)} non-seed concepts → includeDescendants=false")
        else:
            agent2_std_ids = set()
            
        agent2_resolved = resolve_concept_set(
            cur, list(agent2_std_ids) if all_agent2_ids else [],
            no_expand_ids=no_expand_ids
        )

        log_lines.append(f"  Agent 2 total: {len(all_agent2_ids)} raw → {len(agent2_resolved)} resolved ({total_ms:.0f}ms)")

        # 5. Compare
        if not troy_resolved or not agent2_resolved:
            recall, precision = 0.0, 0.0
        else:
            overlap = len(troy_resolved & agent2_resolved)
            recall = overlap / len(troy_resolved)
            precision = overlap / len(agent2_resolved)

        f1 = (2 * recall * precision / (recall + precision)) if (recall + precision) > 0 else 0.0
        semantic_dist = calculate_semantic_distance(cur, troy_raw_ids, all_agent2_ids)

        if not agent2_resolved:
            emoji, status = "⭕", "EMPTY"
        elif recall >= 0.8:
            emoji, status = "✅", "FULL"
        elif recall >= 0.3:
            emoji, status = "🔶", "PARTIAL"
        else:
            emoji, status = "❌", "WRONG"

        overlap_count = len(troy_resolved & agent2_resolved) if troy_resolved and agent2_resolved else 0
        log_lines.append(f"  {emoji} R={recall:.0%} P={precision:.0%} F1={f1:.0%} "
                         f"(Soft P1={semantic_dist['soft_precision_1hop']:.0%}, "
                         f"Soft P2={semantic_dist['soft_precision_2hop']:.0%}) "
                         f"(overlap={overlap_count}, troy={len(troy_resolved)}, "
                         f"agent2={len(agent2_resolved)})\n")

        return {
            "rule_index": rule.index,
            "rule_name": rule.name,
            "occurrence_type": rule.occurrence_type,
            "troy": {
                "concept_set_names": rule.concept_set_names,
                "raw_count": len(troy_raw_ids),
                "resolved_count": len(troy_resolved),
            },
            "agent2": {
                "query_texts": query_texts,
                "raw_ids": all_agent2_ids,
                "resolved_count": len(agent2_resolved),
                "total_ms": round(total_ms, 1),
                "sub_results": sub_results,
            },
            "comparison": {
                "overlap": overlap_count,
                "recall": round(recall, 4),
                "precision": round(precision, 4),
                "f1": round(f1, 4),
                "status": status,
                "semantic_distance": semantic_dist,
            },
            "log": "\n".join(log_lines),
            "stats": {
                "recall": recall, "precision": precision, "f1": f1,
                "soft_p1": semantic_dist["soft_precision_1hop"],
                "soft_p2": semantic_dist["soft_precision_2hop"],
                "status": status,
                "cache_hits": rule_cache_hits,
                "cache_misses": rule_cache_misses
            }
        }
    finally:
        cur.close()
        db_pool.putconn(conn)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Benchmark A_direct: Tier 1 Mapping Accuracy (Parallel)")
    parser.add_argument("--troy", default=TROY_PATH)
    parser.add_argument("--report-dir", default=REPORT_DIR)
    parser.add_argument("--no-agent2-cache", action="store_true", help="Disable Agent2 result cache")
    parser.add_argument("--workers", type=int, default=5, help="Number of parallel threads")
    args = parser.parse_args()
    
    from src.agents.agent2.agent2_cache import Agent2Cache
    agent2_cache = None if args.no_agent2_cache else Agent2Cache()

    print(f"{'='*70}")
    print(f"  Benchmark A_direct: TROY Rule Name → Agent 2 (Parallel)")
    print(f"  TROY: {args.troy}")
    print(f"  Schema: {SCHEMA}")
    print(f"  Workers: {args.workers}")
    cache_label = "DISABLED" if args.no_agent2_cache else f"ON ({agent2_cache.size} entries)"
    print(f"  Agent2 cache: {cache_label}")
    print(f"{'='*70}\n")

    with open(args.troy) as f:
        troy_json = json.load(f)

    rules = extract_troy_rules(troy_json)
    print(f"TROY Rules: {len(rules)}\n")

    db_pool = ThreadedConnectionPool(
        minconn=1, maxconn=args.workers + 5,
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS
    )

    results = []
    total_recall = 0.0
    total_precision = 0.0
    total_f1 = 0.0
    total_soft_p1 = 0.0
    total_soft_p2 = 0.0
    n_evaluated = 0
    full, partial, wrong, empty = 0, 0, 0, 0
    total_cache_hits = 0
    total_cache_misses = 0

    agent2_start = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_single_rule, rule, troy_json, db_pool, agent2_cache): rule for rule in rules}
        
        # To maintain deterministic output order
        for future in as_completed(futures):
            res = future.result()
            results.append(res)
            print(res["log"])
            
            if res.get("status") != "DEMOGRAPHIC_SKIP":
                st = res["stats"]
                total_recall += st["recall"]
                total_precision += st["precision"]
                total_f1 += st["f1"]
                total_soft_p1 += st["soft_p1"]
                total_soft_p2 += st["soft_p2"]
                total_cache_hits += st["cache_hits"]
                total_cache_misses += st["cache_misses"]
                n_evaluated += 1
                
                status = st["status"]
                if status == "FULL": full += 1
                elif status == "PARTIAL": partial += 1
                elif status == "WRONG": wrong += 1
                elif status == "EMPTY": empty += 1

    db_pool.closeall()

    # Sort results to be in correct rule index order
    results.sort(key=lambda x: x["rule_index"])
    # Delete internal temporary keys from results before JSON dump
    for r in results:
        r.pop("log", None)
        r.pop("stats", None)

    avg_recall = total_recall / n_evaluated if n_evaluated else 0.0
    avg_precision = total_precision / n_evaluated if n_evaluated else 0.0
    avg_f1 = total_f1 / n_evaluated if n_evaluated else 0.0
    avg_soft_p1 = total_soft_p1 / n_evaluated if n_evaluated else 0.0
    avg_soft_p2 = total_soft_p2 / n_evaluated if n_evaluated else 0.0

    agent2_elapsed = time.time() - agent2_start
    total_queries = total_cache_hits + total_cache_misses
    hit_rate = total_cache_hits / (total_queries) * 100 if total_queries else 0
    
    print(f"\n{'='*70}")
    print(f"  SUMMARY — Exp A_direct (Tier 1: Mapping Accuracy - Parallel)")
    print(f"  Total: {len(rules)} rules | Evaluated: {n_evaluated}")
    print(f"  Full(≥80%): {full} | Partial(30-80%): {partial} | "
          f"Wrong(<30%): {wrong} | Empty: {empty}")
    print(f"  Avg Recall: {avg_recall:.1%} | Avg Precision: {avg_precision:.1%} | "
          f"Avg F1: {avg_f1:.1%}")
    print(f"  Soft-Margin P (≤1 hop): {avg_soft_p1:.1%} | Soft-Margin P (≤2 hop): {avg_soft_p2:.1%}")
    print(f"  ⏱ Elapsed: {agent2_elapsed:.1f}s | "
          f"Cache: {total_cache_hits}H/{total_cache_misses}M ({hit_rate:.0f}%)")
    print(f"{'='*70}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    report = {
        "version": "A_direct_v1",
        "tier": "Tier 1 — Mapping Accuracy",
        "pipeline": "TROY entity_text → Agent 2 (no Agent 1) [Parallel]",
        "timestamp": timestamp,
        "troy_path": args.troy,
        "schema": SCHEMA,
        "workers": args.workers,
        "totals": {
            "troy_rules": len(rules),
            "evaluated": n_evaluated,
            "full": full,
            "partial": partial,
            "wrong": wrong,
            "empty": empty,
        },
        "metrics": {
            "avg_recall": round(avg_recall, 4),
            "avg_precision": round(avg_precision, 4),
            "avg_f1": round(avg_f1, 4),
            "avg_soft_p1": round(avg_soft_p1, 4),
            "avg_soft_p2": round(avg_soft_p2, 4),
        },
        "cache_stats": {
            "enabled": not args.no_agent2_cache,
            "hits": total_cache_hits,
            "misses": total_cache_misses,
            "total_queries": total_queries,
            "hit_rate": round(hit_rate, 1),
        },
        "timings": {
            "total_sec": round(agent2_elapsed, 1),
        },
        "rules": results,
    }

    os.makedirs(args.report_dir, exist_ok=True)
    report_path = os.path.join(args.report_dir, f"benchmark_a_direct_{timestamp}.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Report saved: {report_path}")

if __name__ == "__main__":
    main()
