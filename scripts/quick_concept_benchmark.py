#!/usr/bin/env python3
"""
Quick Concept Mapping Benchmark
Compares RAG, LLM Direct, and Agent2 mappers on 50 atlas cohort concept sets.

Memory strategy: run all 50 items for one mapper at a time (load → run → unload),
so only one mapper is in memory per phase.
"""

import sys
import os

# Ensure /app is on path so src.* imports resolve regardless of cwd
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

import json
import gc
import glob
import time
import random
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from collections import defaultdict
from typing import List, Tuple, Dict, Any, Optional

# ─────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────
DOMAIN_PRIORITY = ["Condition", "Drug", "Measurement"]
AGENT2_TIMEOUT_S = 30
SAMPLE_SIZE = 50
RANDOM_SEED = 42


# ─────────────────────────────────────────────────────────────────────
# 1. DATA LOADING
# ─────────────────────────────────────────────────────────────────────

def load_concept_set_items(atlas_dir: str) -> List[Tuple[str, List[int], str]]:
    """Return (name, gold_concept_ids, domain) tuples.

    Filters: name>=5 chars, gold count 2-50, isExcluded==False only.
    Deduplicates by name (first-seen wins).
    """
    files = glob.glob(os.path.join(atlas_dir, "*.json"))
    random.shuffle(files)

    seen_names: dict = {}
    all_items: List[Tuple[str, List[int], str]] = []

    for fpath in files:
        try:
            with open(fpath) as fp:
                data = json.load(fp)
        except Exception:
            continue

        if not isinstance(data, dict):
            continue
        expr = data.get("expression") or {}
        concept_sets = (expr.get("ConceptSets") if isinstance(expr, dict) else None) or []

        for cs in concept_sets:
            name = (cs.get("name") or "").strip()
            if len(name) < 5:
                continue
            if name in seen_names:
                continue

            items = cs.get("expression", {}).get("items", []) or []
            non_excluded = [i for i in items if not i.get("isExcluded", False)]
            gold_ids = [i["concept"]["CONCEPT_ID"] for i in non_excluded if "concept" in i]

            if not (2 <= len(gold_ids) <= 50):
                continue

            domain = "Other"
            if non_excluded:
                raw_domain = non_excluded[0].get("concept", {}).get("DOMAIN_ID", "")
                if raw_domain:
                    domain = raw_domain

            seen_names[name] = True
            all_items.append((name, gold_ids, domain))

    return all_items


def stratified_sample(
    items: List[Tuple[str, List[int], str]], n: int
) -> List[Tuple[str, List[int], str]]:
    """Sample n items stratified by domain (round-robin, priority order)."""
    by_domain: Dict[str, list] = defaultdict(list)
    for item in items:
        by_domain[item[2]].append(item)

    order = DOMAIN_PRIORITY + [d for d in by_domain if d not in DOMAIN_PRIORITY]
    selected: List[Tuple[str, List[int], str]] = []
    domain_iter = {d: iter(by_domain[d]) for d in order}

    while len(selected) < n:
        added_any = False
        for d in order:
            if len(selected) >= n:
                break
            try:
                selected.append(next(domain_iter[d]))
                added_any = True
            except StopIteration:
                pass
        if not added_any:
            break

    return selected[:n]


# ─────────────────────────────────────────────────────────────────────
# 2. MAPPERS
# ─────────────────────────────────────────────────────────────────────

def run_rag_pass(sample: List[Tuple[str, List[int], str]]) -> List[Dict[str, Any]]:
    """Run RAG mapper on all items, return per-item result dicts."""
    print("\n[Phase 1/3] Loading RAG mapper...")
    from src.agents.conceptset.rag_search import get_rag_search
    rag = get_rag_search()

    rows = []
    for i, (name, gold_ids, domain) in enumerate(sample):
        if i % 10 == 0:
            print(f"  [RAG {i + 1}/{len(sample)}] {name[:50]}...")
        top_k = max(20, len(gold_ids))
        t0 = time.perf_counter()
        try:
            candidates = rag.search(name, n_results=top_k)
            pred_ids = [c.concept_id for c in candidates]
        except Exception as exc:
            print(f"    [RAG] ERROR on '{name[:40]}': {exc}")
            pred_ids = []
        latency = (time.perf_counter() - t0) * 1000
        rows.append({"name": name, "domain": domain, "gold_ids": gold_ids,
                     "pred_ids": pred_ids, "latency_ms": latency})

    del rag
    gc.collect()
    return rows


def run_llm_pass(sample: List[Tuple[str, List[int], str]]) -> List[Dict[str, Any]]:
    """Run LLM Direct mapper on all items."""
    print("\n[Phase 2/3] Loading LLM Direct mapper...")
    from src.utils.llm import get_llm
    from langchain_core.messages import HumanMessage
    llm = get_llm()

    rows = []
    for i, (name, gold_ids, domain) in enumerate(sample):
        if i % 10 == 0:
            print(f"  [LLM {i + 1}/{len(sample)}] {name[:50]}...")
        t0 = time.perf_counter()
        try:
            prompt = (
                f'You are a medical ontology expert. Map this OMOP concept set name to standard OMOP concept IDs.\n\n'
                f'Concept set name: "{name}"\n\n'
                f'Return ONLY a JSON object: {{"concept_ids": [int, ...]}}\n'
                f'Include the most relevant standard OMOP concept IDs. No explanation.'
            )
            response = llm.invoke([HumanMessage(content=prompt)])
            raw = response.content.strip()
            # Strip code fences if present
            if raw.startswith("```"):
                lines = raw.split("\n")
                raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
            parsed = json.loads(raw)
            ids = parsed.get("concept_ids", [])
            pred_ids = [int(x) for x in ids if isinstance(x, (int, float, str))]
        except Exception as exc:
            print(f"    [LLM] ERROR on '{name[:40]}': {exc}")
            pred_ids = []
        latency = (time.perf_counter() - t0) * 1000
        rows.append({"name": name, "domain": domain, "gold_ids": gold_ids,
                     "pred_ids": pred_ids, "latency_ms": latency})

    del llm
    gc.collect()
    return rows


def _agent2_call(agent2, name: str, domain: str) -> List[int]:
    return agent2.process(name, domain_hint=domain)


def run_agent2_pass(sample: List[Tuple[str, List[int], str]]) -> List[Dict[str, Any]]:
    """Run Agent2 mapper on all items (with per-item timeout)."""
    print("\n[Phase 3/3] Loading Agent2 mapper...")
    from src.agents.agent2.workflow import get_agent2
    agent2 = get_agent2()

    rows = []
    for i, (name, gold_ids, domain) in enumerate(sample):
        if i % 10 == 0:
            print(f"  [Agent2 {i + 1}/{len(sample)}] {name[:50]}...")
        t0 = time.perf_counter()
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_agent2_call, agent2, name, domain)
                try:
                    pred_ids = fut.result(timeout=AGENT2_TIMEOUT_S)
                except FuturesTimeoutError:
                    print(f"    [Agent2] TIMEOUT for '{name[:40]}'")
                    pred_ids = []
        except Exception as exc:
            print(f"    [Agent2] ERROR on '{name[:40]}': {exc}")
            pred_ids = []
        latency = (time.perf_counter() - t0) * 1000
        rows.append({"name": name, "domain": domain, "gold_ids": gold_ids,
                     "pred_ids": pred_ids, "latency_ms": latency})

    del agent2
    gc.collect()
    return rows


# ─────────────────────────────────────────────────────────────────────
# 3. METRICS
# ─────────────────────────────────────────────────────────────────────

def compute_metrics(pred_ids: List[int], gold_ids: List[int]) -> Dict[str, float]:
    gold_set = set(gold_ids)
    pred_set = set(pred_ids)

    precision = len(pred_set & gold_set) / len(pred_set) if pred_set else 0.0
    recall = len(pred_set & gold_set) / len(gold_set) if gold_set else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    hit_at_1 = int(bool(set(pred_ids[:1]) & gold_set))
    hit_at_5 = int(bool(set(pred_ids[:5]) & gold_set))
    hit_at_10 = int(bool(set(pred_ids[:10]) & gold_set))
    hallucinated = len([p for p in pred_ids if p not in gold_set])

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "hit_at_1": hit_at_1,
        "hit_at_5": hit_at_5,
        "hit_at_10": hit_at_10,
        "hallucinated": hallucinated,
    }


def enrich_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add metric fields to each row."""
    for row in rows:
        m = compute_metrics(row["pred_ids"], row["gold_ids"])
        row.update(m)
    return rows


# ─────────────────────────────────────────────────────────────────────
# 4. REPORTING
# ─────────────────────────────────────────────────────────────────────

def avg(lst: List[Dict], key: str) -> float:
    vals = [x[key] for x in lst if key in x]
    return sum(vals) / len(vals) if vals else 0.0


def print_results(
    mapper_names: List[str],
    results: Dict[str, List[Dict[str, Any]]],
    sample_size: int,
) -> Dict[str, Any]:
    all_domains = sorted(set(r["domain"] for rows in results.values() for r in rows))

    print("\n" + "=" * 70)
    print(f"=== CONCEPT MAPPING BENCHMARK ({sample_size} items) ===")
    print("=" * 70)

    header = (
        f"{'Mapper':<14} {'Precision':>9}  {'Recall':>8}  {'F1':>7}"
        f"  {'Hit@1':>6}  {'Hit@5':>6}  {'Hit@10':>7}  {'Latency(ms)':>11}"
    )
    print(header)
    print("-" * len(header))

    agg: Dict[str, Dict[str, float]] = {}
    for mapper_name in mapper_names:
        rows = results[mapper_name]
        a = {
            "precision": avg(rows, "precision"),
            "recall": avg(rows, "recall"),
            "f1": avg(rows, "f1"),
            "hit_at_1": avg(rows, "hit_at_1"),
            "hit_at_5": avg(rows, "hit_at_5"),
            "hit_at_10": avg(rows, "hit_at_10"),
            "latency_ms": avg(rows, "latency_ms"),
        }
        agg[mapper_name] = a
        print(
            f"{mapper_name:<14} {a['precision']:>9.3f}  {a['recall']:>8.3f}  {a['f1']:>7.3f}"
            f"  {a['hit_at_1']:>6.3f}  {a['hit_at_5']:>6.3f}  {a['hit_at_10']:>7.3f}"
            f"  {a['latency_ms']:>11.0f}"
        )

    domain_agg: Dict[str, Dict[str, float]] = {}
    print("\n=== By Domain (F1) ===")
    dom_header = f"{'Domain':<20} {'RAG':>8}  {'LLM Direct':>10}  {'Agent2':>8}"
    print(dom_header)
    print("-" * len(dom_header))
    for domain in all_domains:
        row: Dict[str, float] = {}
        for mapper_name in mapper_names:
            domain_rows = [r for r in results[mapper_name] if r["domain"] == domain]
            row[mapper_name] = avg(domain_rows, "f1") if domain_rows else 0.0
        domain_agg[domain] = row
        print(
            f"{domain:<20} {row.get('RAG', 0):>8.3f}  {row.get('LLM Direct', 0):>10.3f}"
            f"  {row.get('Agent2', 0):>8.3f}"
        )

    return {"aggregate": agg, "by_domain": domain_agg}


# ─────────────────────────────────────────────────────────────────────
# 5. MAIN
# ─────────────────────────────────────────────────────────────────────

def run_benchmark() -> None:
    random.seed(RANDOM_SEED)

    print("=" * 60)
    print("LOADING BENCHMARK DATA...")
    print("=" * 60)

    atlas_dir = "/app/data/atlas_cohorts"
    all_items = load_concept_set_items(atlas_dir)
    print(f"  Loaded {len(all_items)} valid concept sets")

    sample = stratified_sample(all_items, SAMPLE_SIZE)
    print(f"  Sampled {len(sample)} items")

    domain_counts: Dict[str, int] = defaultdict(int)
    for _, _, d in sample:
        domain_counts[d] += 1
    print(f"  Domain distribution: {dict(domain_counts)}")

    # ── Run each mapper in sequence (one in memory at a time) ──
    rag_rows = enrich_rows(run_rag_pass(sample))
    llm_rows = enrich_rows(run_llm_pass(sample))
    a2_rows = enrich_rows(run_agent2_pass(sample))

    mapper_names = ["RAG", "LLM Direct", "Agent2"]
    results: Dict[str, List[Dict[str, Any]]] = {
        "RAG": rag_rows,
        "LLM Direct": llm_rows,
        "Agent2": a2_rows,
    }

    agg_data = print_results(mapper_names, results, len(sample))

    # ── Save ──
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = f"/app/data/benchmark_results/quick_benchmark_{timestamp}.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    output = {
        "timestamp": timestamp,
        "sample_size": len(sample),
        "domain_distribution": dict(domain_counts),
        "aggregate": agg_data["aggregate"],
        "by_domain": agg_data["by_domain"],
        "per_item": {
            mapper_name: [
                {k: v for k, v in row.items() if k != "gold_ids"}
                for row in results[mapper_name]
            ]
            for mapper_name in mapper_names
        },
    }

    with open(out_path, "w") as fp:
        json.dump(output, fp, indent=2)
    print(f"\nResults saved to: {out_path}")
    print("=" * 60)


if __name__ == "__main__":
    run_benchmark()
