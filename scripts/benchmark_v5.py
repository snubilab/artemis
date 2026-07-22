"""
Benchmark V5.1: Agent 1 + Agent 2 Pipeline Evaluation via TROY Reference.

Approach:
  1. Extract each TROY inclusion rule's name (criteria text)
  2. Feed that text to Agent 1 (Logic Decomposer) to decompose into sub-criteria
  3. Feed each sub-criterion's entity_text to Agent 2 (Intelligent Mapper)
  4. Aggregate Agent 2's output concepts across all sub-criteria
  5. Compare aggregated concepts with TROY's concept set (standard-substituted, resolved)
  6. Report recall, precision, F1 per rule

This evaluates the combined Agent 1 → Agent 2 pipeline.
Agent 1 and Agent 2 performance are coupled — to isolate Agent 2,
use TROY concept set names directly (see v5.0 runs in BENCHMARK_V5_RESULTS.md).

Usage:
    PIPELINE_MODE=benchmark conda run -n artemis python scripts/benchmark_v5.py
    PIPELINE_MODE=benchmark conda run -n artemis python scripts/benchmark_v5.py \
        --troy "data/sample/LEADER/[TROY] Liraglutide (LEADER) v3.4.json"
"""
import json
import sys
import os
import re
import time
from datetime import datetime
from typing import Dict, Any, List, Set, Tuple, Optional
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from psycopg2.pool import ThreadedConnectionPool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")
os.environ.setdefault("PIPELINE_MODE", "benchmark")

import psycopg2
from src.agents.agent1.parser import get_agent1
from src.agents.agent2.map_entity import map_single_entity
from src.pipeline.supervisor import get_supervisor

# ============================================================
# Configuration
# ============================================================
TROY_PATH = "data/sample/LEADER/[TROY] Liraglutide (LEADER) v3.4.json"
REPORT_DIR = "output"

DB_HOST = os.environ.get("OMOP_DB_HOST", "localhost")
DB_PORT = os.environ.get("OMOP_DB_PORT", "5432")
DB_NAME = os.environ.get("OMOP_DB_NAME", "ohdsi")
DB_USER = os.environ.get("OMOP_DB_USER", "postgres")
DB_PASS = os.environ.get("OMOP_DB_PASS", "mypass")
SCHEMA = os.environ.get("CDM_SCHEMA", "synthea23m")


# ============================================================
# DB Helpers (reused from V4)
# ============================================================
def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS
    )


def resolve_concept_set(
    cur, concept_ids: list, no_expand_ids: set = None
) -> Set[int]:
    """Resolve concept IDs with descendants (standard only).
    
    Args:
        cur: Database cursor
        concept_ids: List of concept IDs to resolve
        no_expand_ids: Optional set of concept IDs that should NOT get
                      descendant expansion (includeDescendants=false).
                      These concepts are included as-is but their descendants
                      are not added. Used for broad concepts where expansion
                      would cause overgeneration.
    
    Only keeps standard concepts in the result set.
    """
    if not concept_ids:
        return set()
    
    no_expand = no_expand_ids or set()
    expand_ids = [cid for cid in concept_ids if cid not in no_expand]
    noexpand_ids = [cid for cid in concept_ids if cid in no_expand]
    
    # First: include all seeds that are standard (both expand and no-expand)
    cur.execute(f"""
        SELECT concept_id FROM {SCHEMA}.concept
        WHERE concept_id = ANY(%s) AND standard_concept = 'S'
    """, (list(concept_ids),))
    resolved = {row[0] for row in cur.fetchall()}
    
    # Then: add standard descendants ONLY for expand_ids
    if expand_ids:
        cur.execute(f"""
            SELECT DISTINCT ca.descendant_concept_id
            FROM {SCHEMA}.concept_ancestor ca
            JOIN {SCHEMA}.concept c ON ca.descendant_concept_id = c.concept_id
            WHERE ca.ancestor_concept_id = ANY(%s)
              AND c.standard_concept = 'S'
        """, (expand_ids,))
        for row in cur.fetchall():
            resolved.add(row[0])
    
    return resolved


# ============================================================
# TROY Standard Substitution
# ============================================================
def map_nonstandard_to_standard(
    cur, concept_ids: List[int]
) -> Tuple[Set[int], List[int]]:
    """
    Substitute non-standard TROY concepts to standard via 'Maps to'.
    
    Returns:
        (standard_ids, unmapped_nonstandard_ids)
    """
    if not concept_ids:
        return set(), []

    # Check which are already standard
    cur.execute(f"""
        SELECT concept_id, standard_concept
        FROM {SCHEMA}.concept
        WHERE concept_id = ANY(%s)
    """, (list(concept_ids),))
    
    standard_ids = set()
    nonstandard_ids = []
    
    for cid, std in cur.fetchall():
        if std == 'S':
            standard_ids.add(cid)
        else:
            nonstandard_ids.append(cid)
    
    if not nonstandard_ids:
        return standard_ids, []

    # Maps to 1-hop for non-standard
    cur.execute(f"""
        SELECT cr.concept_id_1, cr.concept_id_2
        FROM {SCHEMA}.concept_relationship cr
        JOIN {SCHEMA}.concept c ON c.concept_id = cr.concept_id_2
        WHERE cr.concept_id_1 = ANY(%s)
          AND cr.relationship_id = 'Maps to'
          AND cr.invalid_reason IS NULL
          AND c.standard_concept = 'S'
          AND c.invalid_reason IS NULL
    """, (nonstandard_ids,))
    
    mapped = set()
    mapped_sources = set()
    for src, dst in cur.fetchall():
        standard_ids.add(dst)
        mapped.add(dst)
        mapped_sources.add(src)
    
    unmapped = [cid for cid in nonstandard_ids if cid not in mapped_sources]
    
    return standard_ids, unmapped


# ============================================================
# Semantic Distance Evaluation
# ============================================================
def calculate_semantic_distance(
    cur, troy_raw_ids: List[int], agent2_raw_ids: List[int]
) -> Dict[str, Any]:
    """
    Calculate the minimum hierarchical distance (hops) between Agent 2 raw concepts and TROY raw concepts.
    Returns a dictionary with counts of Exact (Dist=0), 1-Hop, 2-Hop, and Miss concepts,
    along with Soft-Margin Precision metrics.
    """
    result = {
        "exact": 0,
        "hop1": 0,
        "hop2": 0,
        "miss": 0,
        "total_agent2": len(agent2_raw_ids),
        "soft_precision_1hop": 0.0,
        "soft_precision_2hop": 0.0,
    }
    
    if not troy_raw_ids or not agent2_raw_ids:
        if agent2_raw_ids:
            result["miss"] = len(agent2_raw_ids)
        return result

    troy_set = set(troy_raw_ids)
    
    # Query all distances at once
    cur.execute(f"""
        SELECT ancestor_concept_id, descendant_concept_id, min_levels_of_separation
        FROM {SCHEMA}.concept_ancestor
        WHERE (ancestor_concept_id = ANY(%s) AND descendant_concept_id = ANY(%s))
           OR (ancestor_concept_id = ANY(%s) AND descendant_concept_id = ANY(%s))
    """, (list(troy_set), list(agent2_raw_ids), list(agent2_raw_ids), list(troy_set)))
    
    distances = {} # (anc, desc) -> min_levels
    for anc, desc, dist in cur.fetchall():
        pair1 = (anc, desc)
        pair2 = (desc, anc)
        for pair in (pair1, pair2):
            if pair not in distances or dist < distances[pair]:
                distances[pair] = dist
                
    for a2_id in agent2_raw_ids:
        if a2_id in troy_set:
            result["exact"] += 1
            continue
            
        min_dist = float('inf')
        for t_id in troy_set:
            pair = (a2_id, t_id)
            if pair in distances:
                dist = distances[pair]
                if dist < min_dist:
                    min_dist = dist
                    
        if min_dist == 1:
            result["hop1"] += 1
        elif min_dist == 2:
            result["hop2"] += 1
        else:
            result["miss"] += 1
            
    if result["total_agent2"] > 0:
        result["soft_precision_1hop"] = (result["exact"] + result["hop1"]) / result["total_agent2"]
        result["soft_precision_2hop"] = (result["exact"] + result["hop1"] + result["hop2"]) / result["total_agent2"]
        
    return result


# ============================================================
# TROY Rule & Concept Extraction
# ============================================================
@dataclass
class TROYRule:
    """One TROY inclusion rule with its reference concepts."""
    index: int
    name: str
    occurrence_type: str
    concept_set_ids: List[int]
    concept_set_names: List[str]
    is_demographic: bool = False
    domain: Optional[str] = None  # Inferred from ConceptSet DOMAIN_ID (first CS)
    cs_domains: Dict[str, str] = field(default_factory=dict)  # CS name → DOMAIN_ID


def extract_troy_rules(troy_json: Dict[str, Any]) -> List[TROYRule]:
    """Extract rules from TROY cohort definition."""
    cs_map = {}
    for cs in troy_json.get("ConceptSets", []):
        name = re.sub(r'\[TROY\]\s*', '', cs["name"])
        cs_map[cs["id"]] = name

    rules = []
    for i, rule in enumerate(troy_json.get("InclusionRules", [])):
        rule_name = rule.get("name", "Unnamed")
        expr = rule.get("expression", {})
        criteria_list = expr.get("CriteriaList", [])
        demo_list = expr.get("DemographicCriteriaList", [])

        # Occurrence type
        occurrence_type = "PRESENCE"
        if criteria_list:
            occ = criteria_list[0].get("Occurrence", {})
            occ_type = occ.get("Type", 2)
            if occ_type == 0:
                occurrence_type = "ABSENCE"

        # Collect concept set IDs (recursive for unlimited depth)
        cs_ids = []
        cs_names = []

        def _collect(cl):
            for entry in cl:
                crit = entry.get("Criteria", {})
                for domain_key, content in crit.items():
                    csid = content.get("CodesetId", 0)
                    if csid != 0:
                        cs_ids.append(csid)
                        cs_names.append(cs_map.get(csid, f"CS({csid})"))

        def _collect_groups(groups):
            """Recursively traverse nested Groups."""
            for group in groups:
                _collect(group.get("CriteriaList", []))
                _collect_groups(group.get("Groups", []))

        _collect(criteria_list)
        _collect_groups(expr.get("Groups", []))

        if demo_list and not criteria_list and not cs_ids:
            rules.append(TROYRule(i, rule_name, "DEMOGRAPHIC", [], [], True))
            continue

        # Infer domain per ConceptSet and overall rule domain from first CS
        cs_domains: Dict[str, str] = {}
        domain = None
        cs_by_id_lookup = {cs["id"]: cs for cs in troy_json.get("ConceptSets", [])}
        for csid, csname in zip(cs_ids, cs_names):
            cs_obj = cs_by_id_lookup.get(csid)
            if cs_obj:
                items = cs_obj.get("expression", {}).get("items", [])
                if items and "concept" in items[0]:
                    d = items[0]["concept"].get("DOMAIN_ID")
                    if d:
                        cs_domains[csname] = d
                        if domain is None:
                            domain = d

        rules.append(TROYRule(i, rule_name, occurrence_type, cs_ids, cs_names, domain=domain, cs_domains=cs_domains))

    return rules


def get_troy_concept_ids(rule: TROYRule, troy_json: Dict) -> List[int]:
    """Extract raw concept IDs from TROY concept sets for a rule (for reporting)."""
    cs_by_id = {cs["id"]: cs for cs in troy_json.get("ConceptSets", [])}
    all_ids = []
    for csid in rule.concept_set_ids:
        cs = cs_by_id.get(csid)
        if cs:
            items = cs.get("expression", {}).get("items", [])
            for item in items:
                if "concept" in item:
                    all_ids.append(item["concept"]["CONCEPT_ID"])
    return all_ids


def resolve_troy_rule(cur, rule: TROYRule, troy_json: Dict) -> Set[int]:
    """Resolve TROY concepts respecting includeDescendants and isExcluded flags.
    
    This follows the Circe specification:
    - includeDescendants=true: expand via concept_ancestor
    - includeDescendants=false: use concept ID only
    - isExcluded=true: remove from result set
    Non-standard concepts are mapped to standard via 'Maps to'.
    """
    cs_by_id = {cs["id"]: cs for cs in troy_json.get("ConceptSets", [])}
    included = set()
    excluded = set()
    
    for csid in rule.concept_set_ids:
        cs = cs_by_id.get(csid)
        if not cs:
            continue
        items = cs.get("expression", {}).get("items", [])
        for item in items:
            if "concept" not in item:
                continue
            cid = item["concept"]["CONCEPT_ID"]
            inc_desc = item.get("includeDescendants", False)
            is_excluded = item.get("isExcluded", False)
            
            # Map non-standard to standard first
            std_ids, _ = map_nonstandard_to_standard(cur, [cid])
            seed_ids = std_ids if std_ids else set()  # drop unmapped non-standard
            if not seed_ids:
                continue
            
            if inc_desc:
                # Expand descendants for each seed
                expanded = set()
                for sid in seed_ids:
                    cur.execute(f"""
                        SELECT DISTINCT ca.descendant_concept_id
                        FROM {SCHEMA}.concept_ancestor ca
                        JOIN {SCHEMA}.concept c ON ca.descendant_concept_id = c.concept_id
                        WHERE ca.ancestor_concept_id = %s
                          AND c.standard_concept = 'S'
                    """, (sid,))
                    expanded |= {r[0] for r in cur.fetchall()}
                ids = expanded
            else:
                ids = seed_ids
            
            if is_excluded:
                excluded |= ids
            else:
                included |= ids
    
    return included - excluded


# ============================================================
# Agent 1 & Agent 2 Invocation
# ============================================================
def _clean_rule_name(name: str) -> str:
    """Remove [TROY] prefix and normalize rule name for Agent input."""
    name = re.sub(r'\[TROY\]\s*', '', name)
    name = re.sub(r'\(copy\s*\d*\)', '', name, flags=re.IGNORECASE)
    return name.strip()


def invoke_agent1(rule_name: str) -> list:
    """
    Invoke Agent 1 to decompose a rule name into sub-criteria.
    """
    clean_name = _clean_rule_name(rule_name)
    agent1 = get_agent1()
    try:
        result = agent1.parse(clean_name)
        sub_criteria = []
        
        # ARTEMISRequest has .target and .comparator (both CohortDefinition)
        for cohort in [result.target, result.comparator]:
            if cohort is None:
                continue
            
            # Combine primary_criteria, inclusion_rules, and exclusion_rules
            all_criteria = []
            if cohort.primary_criteria and cohort.primary_criteria.entity_text:
                all_criteria.append(cohort.primary_criteria)
            all_criteria.extend(cohort.inclusion_rules)
            all_criteria.extend(cohort.exclusion_rules)

            for criteria in all_criteria:
                if getattr(criteria, "entity_text", None):
                    sub_criteria.append({
                        "entity_text": criteria.entity_text,
                        "domain": getattr(criteria, "domain", "Condition"),
                        "name": getattr(criteria, "name", criteria.entity_text),
                    })
                # Check for sub_criteria, but primary_criteria may not have this attribute
                if hasattr(criteria, "sub_criteria"):
                    for sc in criteria.sub_criteria:
                        if sc.entity_text:
                            sub_criteria.append({
                                "entity_text": sc.entity_text,
                                "domain": sc.domain,
                                "name": sc.name,
                            })
        
        if not sub_criteria:
            # Agent 1 parsed but produced no criteria — fallback
            return [{"entity_text": clean_name, "domain": "Condition", "name": clean_name}]
        
        # Hierarchical Expansion
        decomposed_texts = {sc["entity_text"].lower() for sc in sub_criteria}
        if clean_name.lower() not in decomposed_texts:
            primary_domain = sub_criteria[0]["domain"] if sub_criteria else "Condition"
            sub_criteria.insert(0, {
                "entity_text": clean_name,
                "domain": primary_domain,
                "name": f"[ORIGINAL] {clean_name}",
            })
        
        return sub_criteria
    except Exception as e:
        print(f"    ⚠️ Agent 1 error: {e}")
        return [{"entity_text": clean_name, "domain": "Condition", "name": clean_name}]


def invoke_agent2(query_text: str, domain: str = None, rule_context: str = None) -> Tuple[List[int], Dict]:
    """Invoke Agent 2 with a query text and return concept IDs + metadata."""
    emr = map_single_entity(
        query_text,
        domain_hint=domain,
        rule_context=rule_context,
    )

    if emr.error:
        print(f"    ⚠️ Agent 2 error for '{query_text}': {emr.error}")

    return emr.concept_ids, emr.to_meta_dict()


# ============================================================
# Parallel Rule Processor
# ============================================================
def process_single_rule(rule: TROYRule, troy_json: Dict, args: Any, db_pool: ThreadedConnectionPool) -> Dict:
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
        troy_raw_ids = get_troy_concept_ids(rule, troy_json)
        troy_resolved = resolve_troy_rule(cur, rule, troy_json)
        
        log_lines = []
        log_lines.append(f"[{rule.index+1}] {rule.name}")
        log_lines.append(f"  TROY: {len(troy_raw_ids)} raw → {len(troy_resolved)} resolved (Circe-compliant)")

        if args.skip_agents:
            log_lines.append("  ⏭ Agents skipped\n")
            return {
                "rule_index": rule.index,
                "rule_name": rule.name,
                "status": "SKIPPED",
                "troy_reference": {
                    "raw_count": len(troy_raw_ids),
                    "resolved_count": len(troy_resolved),
                },
                "log": "\n".join(log_lines)
            }

        # 2. Agent 1
        if not args.supp and rule.concept_set_names:
            unique_names = list(dict.fromkeys(rule.concept_set_names))
            agent1_input = f"{rule.name}: {', '.join(unique_names)}"
        else:
            agent1_input = rule.name
        
        sub_criteria = invoke_agent1(agent1_input)
        log_lines.append(f"  Agent 1: {len(sub_criteria)} sub-criteria decomposed")
        for sc in sub_criteria:
            log_lines.append(f"    - [{sc['domain']}] {sc['entity_text']}")

        # 3. Agent 2
        all_agent2_ids = []
        all_overbroad_ids: Set[int] = set()
        sub_results = []
        total_ms = 0.0
        mapped_sets_for_supervisor = []
        rule_ctx = _clean_rule_name(rule.name) if not args.no_rule_context else None

        for sc in sub_criteria:
            mapping_target = sc.get("name") or sc.get("entity_text")
            ids, meta = invoke_agent2(mapping_target, domain=sc.get("domain"), rule_context=rule_ctx)
            all_agent2_ids.extend(ids)
            all_overbroad_ids.update(meta.get("overbroad_concept_ids", []))
            total_ms += meta.get("processing_ms", 0)
            sub_results.append({
                "entity_text": mapping_target,
                "original_text": sc.get("entity_text"),
                "domain": sc["domain"],
                "concept_ids": ids,
                "count": len(ids),
                **meta,
            })
            mapped_sets_for_supervisor.append({
                "name": mapping_target,
                "domain": sc.get("domain", "Condition"),
                "concept_ids": ids,
            })
            ovb = meta.get('overbroad_concept_ids', [])
            log_lines.append(f"    → {mapping_target}: {len(ids)} concepts"
                             f"{' [overbroad: ' + str(len(ovb)) + ']' if ovb else ''}")

        # 3.1 Supervisor
        supervisor = get_supervisor()
        entities_for_supervisor = [
            {"text": sc["entity_text"], "domain": sc.get("domain", "Condition")}
            for sc in sub_criteria
        ]
        sup_report = supervisor.post_agent2_check(
            mapped_sets=mapped_sets_for_supervisor,
            gap_report=None,
            entities_to_map=entities_for_supervisor,
        )
        if hasattr(sup_report, "retries_triggered") and sup_report.retries_triggered > 0:
            log_lines.append(f"  [Supervisor] {sup_report.retries_triggered} weak entities (report-only)")

        # 4. Standard-substitute
        if all_agent2_ids:
            agent2_std_ids, _ = map_nonstandard_to_standard(cur, all_agent2_ids)
        else:
            agent2_std_ids = set()
            
        overbroad_std = set()
        if all_overbroad_ids:
            overbroad_std, _ = map_nonstandard_to_standard(cur, list(all_overbroad_ids))
            
        agent2_resolved = resolve_concept_set(
            cur, list(agent2_std_ids) if all_agent2_ids else [],
            no_expand_ids=overbroad_std if overbroad_std else None,
        )
        if all_overbroad_ids:
            log_lines.append(f"  [P4] {len(all_overbroad_ids)} overbroad concepts excluded from descendant expansion")

        log_lines.append(f"  Agent 2 total: {len(all_agent2_ids)} raw → {len(agent2_resolved)} resolved ({total_ms:.0f}ms)")

        # 5. Compare
        if not troy_resolved and not agent2_resolved:
            recall, precision = 0.0, 0.0
        elif not troy_resolved or not agent2_resolved:
            recall, precision = 0.0, 0.0
        else:
            overlap = len(troy_resolved & agent2_resolved)
            recall = overlap / len(troy_resolved)
            precision = overlap / len(agent2_resolved)

        f1 = 2 * recall * precision / (recall + precision) if (recall + precision) > 0 else 0.0
        semantic_dist = calculate_semantic_distance(cur, troy_raw_ids, all_agent2_ids)

        if not agent2_resolved:
            emoji, status = "⭕", "EMPTY"
        elif recall >= 0.8:
            emoji, status = "✅", "FULL"
        elif recall >= 0.3:
            emoji, status = "🔶", "PARTIAL"
        else:
            emoji, status = "❌", "WRONG"

        log_lines.append(f"  {emoji} R={recall:.0%} P={precision:.0%} F1={f1:.0%} "
                         f"(Soft P1={semantic_dist['soft_precision_1hop']:.0%}, "
                         f"Soft P2={semantic_dist['soft_precision_2hop']:.0%}) "
                         f"(overlap={len(troy_resolved & agent2_resolved)}, "
                         f"troy={len(troy_resolved)}, agent2={len(agent2_resolved)})\n")

        return {
            "rule_index": rule.index,
            "rule_name": rule.name,
            "troy_reference": {
                "concept_set_names": rule.concept_set_names,
                "raw_count": len(troy_raw_ids),
                "resolved_count": len(troy_resolved),
            },
            "agent1": {
                "sub_criteria_count": len(sub_criteria),
                "sub_criteria": [sc["entity_text"] for sc in sub_criteria],
            },
            "agent2": {
                "raw_ids": all_agent2_ids,
                "resolved_count": len(agent2_resolved),
                "total_processing_ms": total_ms,
                "sub_results": sub_results,
            },
            "comparison": {
                "overlap": len(troy_resolved & agent2_resolved),
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
                "status": status
            }
        }
    finally:
        cur.close()
        db_pool.putconn(conn)


# ============================================================
# Main Evaluation
# ============================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Benchmark V5: Rule → Agent 1 → Agent 2 Evaluation (Parallel)")
    parser.add_argument("--troy", default=TROY_PATH)
    parser.add_argument("--report-dir", default=REPORT_DIR)
    parser.add_argument("--skip-agents", action="store_true",
                        help="Skip Agent 1+2 invocation (only test TROY extraction + substitution)")
    parser.add_argument("--supp", action="store_true",
                        help="E2E_SUPP mode: use only rule name (no concept_set_name hints) for Agent 1 input")
    parser.add_argument("--no-rule-context", action="store_true",
                        help="Disable rule_context pass-through to Agent 2 (AB comparison: A=no context, B=with context)")
    parser.add_argument("--workers", type=int, default=5, help="Number of parallel threads")
    args = parser.parse_args()

    print(f"{'='*70}")
    print(f"  Benchmark V5: Rule → Agent 1 → Agent 2 (Parallel)")
    print(f"  TROY: {args.troy}")
    print(f"  Schema: {SCHEMA}")
    print(f"  Workers: {args.workers}")
    print(f"  Mode: {os.environ.get('PIPELINE_MODE', 'run')}")
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

    benchmark_start_time = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_single_rule, rule, troy_json, args, db_pool): rule for rule in rules}
        
        for future in as_completed(futures):
            res = future.result()
            results.append(res)
            print(res["log"])
            
            status_val = res.get("status")
            if status_val == "DEMOGRAPHIC_SKIP":
                continue
            elif status_val == "SKIPPED":
                continue

            st = res["stats"]
            total_recall += st["recall"]
            total_precision += st["precision"]
            total_f1 += st["f1"]
            total_soft_p1 += st["soft_p1"]
            total_soft_p2 += st["soft_p2"]
            n_evaluated += 1
            
            status = st["status"]
            if status == "FULL": full += 1
            elif status == "PARTIAL": partial += 1
            elif status == "WRONG": wrong += 1
            elif status == "EMPTY": empty += 1

    db_pool.closeall()

    # Sort results
    results.sort(key=lambda x: x["rule_index"])
    for r in results:
        r.pop("log", None)
        r.pop("stats", None)
        r.pop("status", None) # remove local status key

    avg_recall = total_recall / n_evaluated if n_evaluated else 0.0
    avg_precision = total_precision / n_evaluated if n_evaluated else 0.0
    avg_f1 = total_f1 / n_evaluated if n_evaluated else 0.0
    avg_soft_p1 = total_soft_p1 / n_evaluated if n_evaluated else 0.0
    avg_soft_p2 = total_soft_p2 / n_evaluated if n_evaluated else 0.0

    elapsed_time = time.time() - benchmark_start_time

    print(f"{'='*70}")
    print(f"  SUMMARY (Parallel)")
    print(f"  Full(≥80%): {full} | Partial(30-80%): {partial} | "
          f"Wrong(<30%): {wrong} | Empty: {empty}")
    print(f"  Avg Recall: {avg_recall:.1%} | Avg Precision: {avg_precision:.1%} | "
          f"Avg F1: {avg_f1:.1%}")
    print(f"  Soft-Margin P (≤1 hop): {avg_soft_p1:.1%} | Soft-Margin P (≤2 hop): {avg_soft_p2:.1%}")

    print(f"  Rules: {len(rules)} | Evaluated: {n_evaluated} | ⏱ Elapsed: {elapsed_time:.1f}s")
    print(f"{'='*70}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    report = {
        "version": "5.1",
        "mode": "benchmark",
        "pipeline": "Rule → Agent 1 → Agent 2 [Parallel]",
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
        "timings": {
            "total_sec": round(elapsed_time, 1),
        },
        "rules": results,
    }

    os.makedirs(args.report_dir, exist_ok=True)
    report_path = os.path.join(args.report_dir, f"benchmark_v5_{timestamp}.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Report saved: {report_path}")


if __name__ == "__main__":
    main()
