"""
Benchmark Exp D: NCT + papers_dir → Agent 1 → Agent 2 → TROY Comparison.

Approach:
  1. Feed NCT JSON + auto-discovered papers (main + appendix) to Agent 1
  2. Agent 1 produces all inclusion/exclusion rules at once (full IR)
  3. Each Agent 1 rule → Agent 2 (concept mapping with ATC expansion)
  4. Compare Agent 2 output vs TROY resolved concepts per rule

This tests the END-TO-END pipeline with appendix enrichment.

NOT THE MEASURE OF RECORD (note added 2026-08-09). What this IS for: the end-to-end arm
(NCT + appendix papers -> Agent 1 -> Agent 2) that pairs with benchmark_v5.py and
benchmark_a_direct.py to attribute a loss across the pipeline stages. What its per-rule
R/P/F1 headline is NOT: the measure of record. Its concept resolution is this script's
own, not the canonical Circe closure (direct items, descendants through concept_ancestor
filtered by invalid_reason IS NULL, isExcluded subtracted as an anti-join), so its
numbers are not comparable to canonical ones despite the shared metric names.

Measure of record: per-eligibility-criterion 1:1 concept-set overlap against data/gold/,
macro-averaged -- scripts/conceptset_overlap_eval.py --mode closure (see AGENTS.md
EVALUATION).
"""
import os
import sys
import json
import time
from datetime import datetime
from typing import Dict, List, Any, Set, Tuple

# Must set before imports
os.environ.setdefault("PIPELINE_MODE", "benchmark")

import psycopg2

# ============================================================
# Configuration
# ============================================================
TROY_PATH = "data/sample/LEADER/[TROY] Liraglutide (LEADER) v3.4.json"
NCT_JSON = "data/sample/LEADER/NCT01179048.json"
NCT_ID = "NCT01179048"
REPORT_DIR = "output"

DB_HOST = os.environ.get("OMOP_DB_HOST", "localhost")
DB_PORT = os.environ.get("OMOP_DB_PORT", "5432")
DB_NAME = os.environ.get("OMOP_DB_NAME", "postgres")
DB_USER = os.environ.get("OMOP_DB_USER", "postgres")
DB_PASS = os.environ.get("OMOP_DB_PASS", "ohdsi")
SCHEMA = os.environ.get("CDM_SCHEMA", "synthea_cdm")

# ============================================================
# Reuse benchmark_v5 utilities
# ============================================================
sys.path.insert(0, os.path.dirname(__file__))
from benchmark_v5 import (
    get_db_connection,
    resolve_concept_set,
    map_nonstandard_to_standard,
    extract_troy_rules,
    resolve_troy_rule,
    invoke_agent2,
    TROYRule,
)

# ============================================================
# Agent 1 — Full NCT + papers_dir parse
# ============================================================
def invoke_agent1_full(nct_id: str, json_path: str):
    """
    Run Agent 1 on full NCT with papers_dir auto-discovery.
    Returns the ARTEMISRequest IR.
    """
    from src.agents.agent1.parser import get_agent1
    agent1 = get_agent1()
    ir = agent1.parse_nct(
        nct_id,
        json_path=json_path,
        # papers_dir auto-discovers from data/papers/{nct_id}/
    )
    return ir

import re

# ============================================================
# Configuration — Matching
# ============================================================
POLARITY_PENALTY = 1.0  # disabled — TROY InclusionRules all use Occurrence.Type=0 (ABSENCE)
MATCHING_STRATEGY_FULL_UNION = "full_union"
MATCHING_STRATEGY_DENSITY = "overlap_density"
OVERLAP_DENSITY_MIN_RATIO = 0.005
OVERLAP_DENSITY_MAX_RULES = 4


def _split_drug_compound(entity_text: str, domain: str) -> List[str]:
    """
    Drug domain에서만 compound text를 분리.
    "GLP-1 receptor agonist, pramlintide, or DPP-4 inhibitor" → 3개
    실패 시 원본 반환.
    """
    if domain.lower() != "drug":
        return [entity_text]
    if not entity_text:
        return [""]

    text = entity_text.strip()
    if not text:
        return [""]

    # Split only at top-level separators; preserve parenthetical clauses like "(short-acting or other types)".
    tokens = []
    start = 0
    depth = 0
    i = 0
    n = len(text)
    separators = [", and/or ", ", and ", ", or ", " and ", " or "]

    while i < n:
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1

        if depth == 0:
            for sep in separators:
                if text.startswith(sep, i):
                    token = text[start:i].strip()
                    if token:
                        tokens.append(token)
                    i += len(sep)
                    start = i
                    break
        i += 1

    tail = text[start:].strip()
    if tail:
        tokens.append(tail)

    tokens = [p.strip() for p in tokens if len(p.strip()) >= 2]
    return tokens if tokens else [entity_text]


def _prune_overlap_density_rules(
    t_resolved: Set[int],
    contributing: List[dict],
    max_rules: int = OVERLAP_DENSITY_MAX_RULES,
    min_density: float = OVERLAP_DENSITY_MIN_RATIO,
) -> Tuple[List[dict], Set[int], Set[int]]:
    """
    Select a small set of high-density contributors.
    This prevents a single low-density broad rule from dominating union size.
    """
    if not contributing or not t_resolved:
        return contributing, set(), set()

    scored = []
    for c in contributing:
        resolved = c.get("resolved_set", set())
        overlap = resolved & t_resolved
        overlap_count = len(overlap)
        if overlap_count == 0:
            continue
        density = overlap_count / max(len(resolved), 1)
        scored.append((density, overlap_count, c))

    if not scored:
        return [], set(), set()

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

    selected: List[dict] = []
    selected_union: Set[int] = set()
    selected_overlap: Set[int] = set()
    current_f1 = 0.0

    target = len(t_resolved)
    for density, _, c in scored:
        if density < min_density and selected:
            break

        resolved = c.get("resolved_set", set())
        if not resolved:
            continue

        new_union = selected_union | resolved
        new_overlap = selected_overlap | (resolved & t_resolved)
        if not (new_overlap - selected_overlap):
            continue

        recall = len(new_overlap) / target
        precision = len(new_overlap) / max(len(new_union), 1)
        new_f1 = 2 * recall * precision / (recall + precision) if (recall + precision) > 0 else 0.0
        if selected and new_f1 + 1e-12 < current_f1:
            continue

        selected.append(c)
        selected_union = new_union
        selected_overlap = new_overlap
        current_f1 = new_f1

        if len(selected_overlap) >= target:
            break
        if len(selected) >= max_rules:
            break

    if not selected:
        # Fallback: return full contributors if pruning produced nothing.
        full_union = set()
        full_overlap = set()
        full_rules = []
        for c in contributing:
            resolved = c.get("resolved_set", set())
            full_union |= resolved
            full_overlap |= resolved & t_resolved
            full_rules.append(c)
        return full_rules, full_union, full_overlap

    return selected, selected_union, selected_overlap


def _invoke_agent2_with_split(entity_text: str, domain: str, cur, cache=None):
    """
    Drug compound split → 개별 Agent 2 호출 → union resolved concepts.
    Supports Agent2Cache for skipping LLM calls on cache HIT.
    
    Returns: (all_raw_ids, resolved_set, cache_hits, cache_misses)
    """
    sub_queries = _split_drug_compound(entity_text, domain)
    all_raw_ids = []
    hits, misses = 0, 0
    new_entries = []  # Batch flush at caller level
    
    for sq in sub_queries:
        cached_ids = cache.get(sq, domain) if cache else None
        if cached_ids is not None:
            all_raw_ids.extend(cached_ids)
            hits += 1
        else:
            ids, meta = invoke_agent2(sq, domain=domain)
            all_raw_ids.extend(ids)
            misses += 1
            if cache:
                new_entries.append({"entity_text": sq, "domain_hint": domain, "concept_ids": ids})
    
    # Batch write new cache entries (single I/O)
    if new_entries and cache:
        cache.put_batch(new_entries)
    
    if all_raw_ids:
        agent2_std, _ = map_nonstandard_to_standard(cur, all_raw_ids)
        resolved = resolve_concept_set(cur, list(agent2_std))
    else:
        resolved = set()
    
    if len(sub_queries) > 1:
        print(f"    [split] {len(sub_queries)} sub-queries: {sub_queries}")
    
    return all_raw_ids, resolved, hits, misses


def evaluate_troy_matching(
    agent1_rules,
    troy_rules: List[TROYRule],
    troy_json: Dict,
    cur,
    cache=None,
    matching_strategy: str = MATCHING_STRATEGY_FULL_UNION,
    max_rules: int = OVERLAP_DENSITY_MAX_RULES,
    min_density: float = OVERLAP_DENSITY_MIN_RATIO,
    explicit_mapping: Dict[str, List[str]] = None,
):
    """
    N:1 TROY matching with Drug compound split + polarity penalty.
    
    Phase 1: Agent 2 per Agent 1 rule (with drug split)
    Phase 2: Per TROY rule, find best contributing Agent 1 rules by union
    """
    # --- Phase 1: Resolve all TROY rules ---
    troy_data = {}
    for t_rule in troy_rules:
        if t_rule.is_demographic:
            continue
        troy_data[t_rule.index] = {
            "rule": t_rule,
            "resolved": resolve_troy_rule(cur, t_rule, troy_json),
        }
    
    print(f"  TROY: {len(troy_data)} non-demographic rules resolved\n")
    
    # --- Phase 2: Agent 2 for each Agent 1 rule ---
    a1_concepts = []  # list of (rule_type, rule, raw_ids, resolved_set)
    total_cache_hits, total_cache_misses = 0, 0
    agent2_start = time.time()
    
    for rule_type, rule in agent1_rules:
        raw_ids, resolved, hits, misses = _invoke_agent2_with_split(
            rule.entity_text, rule.domain, cur, cache=cache
        )
        total_cache_hits += hits
        total_cache_misses += misses
        polarity = getattr(rule, "logic_type", "PRESENCE" if rule_type == "inclusion" else "ABSENCE")
        cache_tag = " [cached]" if misses == 0 and hits > 0 else ""
        print(f"  [{rule_type[:3].upper()}] {rule.entity_text} → {len(raw_ids)} raw → {len(resolved)} resolved{cache_tag}")
        a1_concepts.append({
            "rule_type": rule_type,
            "rule": rule,
            "raw_ids": raw_ids,
            "resolved": resolved,
            "polarity": polarity,
        })
    
    agent2_elapsed = time.time() - agent2_start
    total_queries = total_cache_hits + total_cache_misses
    hit_rate = total_cache_hits / total_queries * 100 if total_queries else 0
    print(f"\n  📊 Agent2 cache: {total_cache_hits} HIT / {total_cache_misses} MISS "
          f"({hit_rate:.0f}% hit rate) — {agent2_elapsed:.1f}s")
    
    # --- Phase 3: N:1 TROY matching (per-group union) ---
    print(f"\n  {'='*60}")
    print(f"  TROY per-rule evaluation (N:1 matching)")
    print(f"  {'='*60}\n")
    
    troy_results = []
    
    for t_idx, t_data in troy_data.items():
        t_rule = t_data["rule"]
        t_resolved = t_data["resolved"]
        t_polarity = t_rule.occurrence_type  # PRESENCE or ABSENCE
        
        if not t_resolved:
            troy_results.append({
                "troy_rule": t_rule.name,
                "troy_polarity": t_polarity,
                "troy_resolved": 0,
                "status": "EMPTY_TROY",
            })
            continue
        
        # Collect all Agent 1 rules that contribute to this TROY rule
        contributing = []
        agent2_union = set()
        
        # Explicit mapping: connect by rule name (decouples from Agent2 quality)
        # Uses substring matching to handle LLM prefix variations
        # e.g., "Prior MI" matches "Prior cardiovascular disease cohort: Prior MI"
        if explicit_mapping and t_rule.name in explicit_mapping:
            mapped_names = explicit_mapping[t_rule.name]
            for a1 in a1_concepts:
                a1_name = a1["rule"].name
                matched = any(mn in a1_name or a1_name in mn for mn in mapped_names)
                if matched:
                    contributing.append({
                        "rule": a1["rule"].entity_text,
                        "domain": a1["rule"].domain,
                        "polarity": a1["polarity"],
                        "overlap": len(a1["resolved"] & t_resolved),
                        "resolved": len(a1["resolved"]),
                        "resolved_set": a1["resolved"],
                    })
                    agent2_union |= a1["resolved"]
        else:
            # Fallback: concept overlap matching
            for a1 in a1_concepts:
                overlap = a1["resolved"] & t_resolved
                if overlap:
                    contributing.append({
                        "rule": a1["rule"].entity_text,
                        "domain": a1["rule"].domain,
                        "polarity": a1["polarity"],
                        "overlap": len(overlap),
                        "resolved": len(a1["resolved"]),
                        "resolved_set": a1["resolved"],
                    })
                    agent2_union |= a1["resolved"]
        
        if not agent2_union:
            print(f"  ⭕ {t_rule.name}: no Agent 1 overlap")
            troy_results.append({
                "troy_rule": t_rule.name,
                "troy_polarity": t_polarity,
                "troy_resolved": len(t_resolved),
                "matching_strategy": matching_strategy,
                "contributing_rules": [],
                "agent2_union": 0,
                "overlap": 0,
                "recall": 0.0,
                "precision": 0.0,
                "f1": 0.0,
                "status": "EMPTY",
            })
            continue
        
        overlap_counted_rules = contributing
        matching_note = MATCHING_STRATEGY_FULL_UNION
        overlap_count = len(t_resolved & agent2_union)

        if matching_strategy == MATCHING_STRATEGY_DENSITY:
            selected_rules, pruned_union, effective_overlap = _prune_overlap_density_rules(
                t_resolved,
                contributing,
                max_rules=max_rules,
                min_density=min_density,
            )
            if selected_rules:
                overlap_counted_rules = selected_rules
                agent2_union = pruned_union
                overlap_count = len(effective_overlap)
                matching_note = f"{MATCHING_STRATEGY_DENSITY}(max_rules={max_rules},min_density={min_density})"

        
        recall = overlap_count / len(t_resolved)
        precision = overlap_count / len(agent2_union) if agent2_union else 0.0
        
        # ABSENCE/PRESENCE soft penalty
        # Check if majority of contributing rules match TROY polarity
        polarity_matches = sum(1 for c in contributing if c["polarity"] == t_polarity)
        if polarity_matches < len(contributing) / 2:
            recall *= POLARITY_PENALTY
            penalty_applied = True
        else:
            penalty_applied = False
        
        f1 = 2 * recall * precision / (recall + precision) if (recall + precision) > 0 else 0.0
        
        # Classify
        if recall >= 0.8:
            emoji, status = "✅", "FULL"
        elif recall >= 0.3:
            emoji, status = "🔶", "PARTIAL"
        else:
            emoji, status = "❌", "WRONG"
        
        penalty_str = " [⚠ polarity penalty]" if penalty_applied else ""
        print(f"  {emoji} {t_rule.name}: R={recall:.0%} P={precision:.0%} "
              f"(overlap={overlap_count}, troy={len(t_resolved)}, union={len(agent2_union)}, "
              f"contributors={len(overlap_counted_rules)}){penalty_str}")
        
        troy_results.append({
            "troy_rule": t_rule.name,
            "troy_polarity": t_polarity,
            "troy_resolved": len(t_resolved),
            "contributing_rules": [c["rule"] for c in overlap_counted_rules],
            "agent2_union": len(agent2_union),
            "overlap": overlap_count,
            "recall": round(recall, 4),
            "precision": round(precision, 4),
            "f1": round(f1, 4),
            "status": status,
            "penalty_applied": penalty_applied,
            "matching_strategy": matching_note,
        })
    
    cache_stats = {
        "enabled": cache is not None,
        "hits": total_cache_hits,
        "misses": total_cache_misses,
        "total_queries": total_queries,
        "hit_rate": round(hit_rate, 1),
        "agent2_elapsed_sec": round(agent2_elapsed, 1),
    }
    return troy_results, a1_concepts, cache_stats


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Benchmark Exp D: NCT + papers_dir → Full Pipeline")
    parser.add_argument("--troy", default=TROY_PATH)
    parser.add_argument("--nct-json", default=NCT_JSON)
    parser.add_argument("--nct-id", default=NCT_ID)
    parser.add_argument("--report-dir", default=REPORT_DIR)
    parser.add_argument("--no-agent2-cache", action="store_true",
                        help="Disable Agent2 result cache (default: cache ON)")
    parser.add_argument(
        "--matching-strategy",
        choices=[MATCHING_STRATEGY_FULL_UNION, MATCHING_STRATEGY_DENSITY],
        default=MATCHING_STRATEGY_FULL_UNION,
        help="How to aggregate Agent1→Agent2 contributors per TROY rule",
    )
    parser.add_argument(
        "--max-matching-rules",
        type=int,
        default=OVERLAP_DENSITY_MAX_RULES,
        help="Max contributor rules kept in overlap-density matching",
    )
    parser.add_argument(
        "--min-overlap-density",
        type=float,
        default=OVERLAP_DENSITY_MIN_RATIO,
        help="Minimum overlap/ resolved ratio for overlap-density matching",
    )
    args = parser.parse_args()
    
    # Initialize Agent2 cache
    from src.agents.agent2.agent2_cache import Agent2Cache
    if args.no_agent2_cache:
        agent2_cache = None
        print("  ⚙ Agent2 cache: DISABLED")
    else:
        agent2_cache = Agent2Cache()
        print(f"  ⚙ Agent2 cache: ON ({agent2_cache.size} entries loaded)")

    print(f"{'='*70}")
    print(f"  Exp D: NCT + papers_dir → Agent 1 → Agent 2 → TROY")
    print(f"  NCT: {args.nct_id} ({args.nct_json})")
    print(f"  TROY: {args.troy}")
    print(f"  Schema: {SCHEMA}")
    print(f"{'='*70}\n")

    # 1. Load TROY
    with open(args.troy) as f:
        troy_json = json.load(f)
    troy_rules = extract_troy_rules(troy_json)
    print(f"TROY Rules: {len(troy_rules)}\n")

    # 2. Agent 1: full NCT + papers_dir
    print(f"{'='*70}")
    print(f"  Phase 1: Agent 1 — NCT + papers_dir enrichment")
    print(f"{'='*70}")
    ir = invoke_agent1_full(args.nct_id, args.nct_json)

    all_rules = []
    for r in ir.target.inclusion_rules:
        all_rules.append(("inclusion", r))
        # Hierarchical expansion: flatten sub_criteria + keep original
        if r.sub_criteria:
            for sc in r.sub_criteria:
                if sc.entity_text and sc.entity_text.lower() != (r.entity_text or "").lower():
                    all_rules.append(("inclusion", sc))
    for r in ir.target.exclusion_rules:
        all_rules.append(("exclusion", r))
        if r.sub_criteria:
            for sc in r.sub_criteria:
                if sc.entity_text and sc.entity_text.lower() != (r.entity_text or "").lower():
                    all_rules.append(("exclusion", sc))

    print(f"\nAgent 1 output: {len(ir.target.inclusion_rules)} inclusion, "
          f"{len(ir.target.exclusion_rules)} exclusion = {len(all_rules)} rules "
          f"(after hierarchical expansion)\n")

    # 3. DB connection
    conn = get_db_connection()
    cur = conn.cursor()

    # 4. Agent 2 mapping + N:1 TROY matching
    print(f"{'='*70}")
    print(f"  Phase 2: Agent 2 (drug compound split) + N:1 TROY matching")
    print(f"{'='*70}\n")

    # Load explicit Agent1→TROY rule mapping if available
    mapping_path = os.path.join(os.path.dirname(args.troy), "agent1_troy_mapping.json")
    explicit_mapping = None
    if os.path.exists(mapping_path):
        with open(mapping_path) as f:
            mapping_data = json.load(f)
        explicit_mapping = mapping_data.get("mapping", {})
        print(f"  📋 Explicit mapping: {len(explicit_mapping)} TROY rules mapped from {mapping_path}")

    bench_start = time.time()
    troy_results, a1_concepts, cache_stats = evaluate_troy_matching(
        all_rules,
        troy_rules,
        troy_json,
        cur,
        cache=agent2_cache,
        matching_strategy=args.matching_strategy,
        max_rules=args.max_matching_rules,
        min_density=args.min_overlap_density,
        explicit_mapping=explicit_mapping,
    )
    bench_elapsed = time.time() - bench_start

    cur.close()
    conn.close()

    # Tally metrics from TROY-centric results
    full, partial, wrong, empty = 0, 0, 0, 0
    total_recall, total_precision, total_f1 = 0.0, 0.0, 0.0
    n_evaluated = 0

    for r in troy_results:
        status = r.get("status", "")
        if status in ("FULL", "PARTIAL", "WRONG"):
            n_evaluated += 1
            total_recall += r["recall"]
            total_precision += r["precision"]
            total_f1 += r["f1"]
            if status == "FULL":
                full += 1
            elif status == "PARTIAL":
                partial += 1
            else:
                wrong += 1
        elif status == "EMPTY":
            empty += 1

    avg_recall = total_recall / n_evaluated if n_evaluated else 0.0
    avg_precision = total_precision / n_evaluated if n_evaluated else 0.0
    avg_f1 = total_f1 / n_evaluated if n_evaluated else 0.0

    # Unmatched (EMPTY) TROY
    empty_troy = [r["troy_rule"] for r in troy_results if r.get("status") in ("EMPTY", "EMPTY_TROY")]

    print(f"\n{'='*70}")
    print(f"  SUMMARY — Exp D v2 (compound split + N:1 + polarity penalty)")
    print(f"  Matching strategy: {args.matching_strategy}")
    print(f"  Agent 1: {len(all_rules)} rules | Agent 2: {len(a1_concepts)} mapped")
    print(f"  TROY evaluated: {n_evaluated} | Empty: {len(empty_troy)}")
    print(f"  Full(≥80%): {full} | Partial(30-80%): {partial} | "
          f"Wrong(<30%): {wrong}")
    print(f"  Avg Recall: {avg_recall:.1%} | Avg Precision: {avg_precision:.1%} | "
          f"Avg F1: {avg_f1:.1%}")
    print(f"  ⏱ Phase 2 elapsed: {bench_elapsed:.1f}s | "
          f"Cache: {cache_stats['hits']}H/{cache_stats['misses']}M ({cache_stats['hit_rate']:.0f}%)")
    print(f"{'='*70}")

    # JSON Report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    report = {
        "version": "exp_d_v2",
        "mode": "benchmark",
        "pipeline": "NCT + papers_dir → Agent 1 → Agent 2 (compound split + N:1 + polarity)",
        "timestamp": timestamp,
        "nct_id": args.nct_id,
        "troy_path": args.troy,
        "schema": SCHEMA,
        "config": {
            "polarity_penalty": POLARITY_PENALTY,
            "agent2_cache": not args.no_agent2_cache,
            "matching_strategy": args.matching_strategy,
            "max_matching_rules": args.max_matching_rules,
            "min_overlap_density": args.min_overlap_density,
        },
        "cache_stats": cache_stats,
        "timings": {
            "phase2_sec": round(bench_elapsed, 1),
            "agent2_sec": cache_stats.get("agent2_elapsed_sec", 0),
        },
        "agent1_summary": {
            "inclusion_rules": len(ir.target.inclusion_rules),
            "exclusion_rules": len(ir.target.exclusion_rules),
            "total_rules": len(all_rules),
        },
        "totals": {
            "troy_rules": len(troy_rules),
            "troy_evaluated": n_evaluated,
            "empty_troy": len(empty_troy),
            "full": full,
            "partial": partial,
            "wrong": wrong,
        },
        "metrics": {
            "avg_recall": round(avg_recall, 4),
            "avg_precision": round(avg_precision, 4),
            "avg_f1": round(avg_f1, 4),
        },
        "troy_results": troy_results,
        "agent1_rules": [
            {"entity_text": a["rule"].entity_text, "domain": a["rule"].domain, 
             "polarity": a["polarity"], "resolved_count": len(a["resolved"])}
            for a in a1_concepts
        ],
    }

    os.makedirs(args.report_dir, exist_ok=True)
    report_path = os.path.join(args.report_dir, f"benchmark_exp_d_v2_{timestamp}.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Report saved: {report_path}")


if __name__ == "__main__":
    main()
