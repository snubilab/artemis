import os
import sys
import json
import uuid
import time
import hashlib
import logging
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass, asdict
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.webapi_client import WebAPIClient
from src.analysis.omop_connector import OMOPConnector
from src.agents.agent1.parser import get_agent1
from src.models.ir import ARTEMISRequest
from src.pipeline.supervisor import PipelineSupervisor
from src.registry.store import registry
from src.registry.models import RegisteredConcept
from src.agents.agent3.assembler import agent3

@dataclass
class BenchmarkConfig:
    trial_type: str
    run_mode: str  # e.g., "E2E_SUPP", "A2_ONLY"
    gold_json_path: str
    output_dir: str = "output"
    workers: int = 1

def get_gold_cache_path(output_dir: str) -> str:
    return os.path.join(output_dir, "v6_cohort_gold_cache.json")

def load_gold_cache(output_dir: str) -> Dict[str, Any]:
    cache_path = get_gold_cache_path(output_dir)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
    return {}

def save_gold_cache(output_dir: str, cache: Dict[str, Any]):
    os.makedirs(output_dir, exist_ok=True)
    with open(get_gold_cache_path(output_dir), 'w') as f:
        json.dump(cache, f, indent=2)

def hash_dict(d: Dict[str, Any]) -> str:
    """Stable hash for a dictionary."""
    s = json.dumps(d, sort_keys=True)
    return hashlib.sha256(s.encode('utf-8')).hexdigest()

def extract_or_load_ir(config: BenchmarkConfig) -> ARTEMISRequest:
    """Get the IR based on run_mode."""
    if config.trial_type == "LEADER":
        nct_id = "NCT01179048"
    elif config.trial_type == "PLATO":
        nct_id = "NCT00391872"
    elif config.trial_type == "ARISTOTLE":
        nct_id = "NCT00412984"
    else:
        raise ValueError(f"Unknown trial_type: {config.trial_type}")

    logger.info(f"Running Agent 1 extraction for {nct_id}...")
    agent1 = get_agent1()
    ir = agent1.parse_nct(nct_id)
    return ir

def _step2_map_parallel(ir: ARTEMISRequest, workers: int) -> Tuple[List[Dict], Any, List[Dict]]:
    """Map entities to OMOP concepts concurrently."""
    from src.pipeline.supervisor import PipelineSupervisor
    from src.models.ir import GapReport
    from src.agents.agent2.map_entity import map_single_entity
    
    logger.info(f"Running Agent 2 mapping concurrently with {workers} workers...")
    entities_to_map = []
    
    # Collect entities
    entities_to_map.extend(PipelineSupervisor._collect_cohort_entities(ir.target, "target"))
    entities_to_map.extend(PipelineSupervisor._collect_cohort_entities(ir.comparator, "comparator"))
    
    if ir.outcome and ir.outcome.entity_text:
        entities_to_map.append({
            "text": ir.outcome.entity_text,
            "domain": ir.outcome.domain,
            "source": "outcome",
            "entity_key": "outcome:primary:0:0",
        })
        
    gap = GapReport()
    gap.total_criteria = len(entities_to_map)
    mapped_sets = []
    
    def _map_entity(i, entity):
        raw_rule = entity.get("parent_rule")
        rule_context = raw_rule.replace("_", " ").title() if raw_rule else None
        try:
            emr = map_single_entity(
                entity["text"],
                domain_hint=entity.get("domain"),
                rule_context=rule_context,
            )
            return i, entity, emr, None
        except Exception as e:
            return i, entity, None, str(e)
            
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_map_entity, i, ent): (i, ent) for i, ent in enumerate(entities_to_map)}
        
        results = []
        for future in as_completed(futures):
            results.append(future.result())
            
        results.sort(key=lambda x: x[0])
        
        for i, entity, emr, err_msg in results:
            if err_msg:
                logger.warning(f"Failed to map '{entity['text']}': {err_msg}")
                gap.add_gap(
                    item_id=f"entity_{i}",
                    original_text=entity["text"],
                    reason=err_msg,
                    section="inclusion",  # Must be one of 'inclusion', 'exclusion', 'primary', 'outcome'
                    domain=entity.get("domain")
                )
            elif emr.success:
                gap.mapped_count += 1
                mapped_sets.append(emr.to_mapped_set(
                    entity_id=i + 1,
                    entity_text=entity["text"],
                    domain=entity["domain"],
                    source=entity["source"],
                    parent_rule=entity.get("parent_rule"),
                    entity_key=entity.get("entity_key"),
                ))
            else:
                reason = emr.error or "Agent 2 returned empty concept_ids"
                gap.add_gap(
                    item_id=f"entity_{i}",
                    original_text=entity["text"],
                    reason=reason,
                    section="inclusion",  # Must be one of 'inclusion', 'exclusion', 'primary', 'outcome'
                    domain=entity.get("domain")
                )
                
    logger.info(f"Mapped {len(mapped_sets)} concept sets. Gap: {gap.unmapped_count} unmapped.")
    return mapped_sets, gap, entities_to_map

def run_cohort_benchmark(config: BenchmarkConfig) -> Dict[str, Any]:
    """Orchestrate the V6 cohort benchmark evaluation."""
    logger.info(f"Starting Cohort Benchmark for {config.trial_type} ({config.run_mode})")
    start_time = time.time()
    
    # 1. Load Gold JSON
    with open(config.gold_json_path, 'r') as f:
        gold_circe = json.load(f)
        
    gold_hash = hash_dict(gold_circe)

    # 2. Run Pipeline to get Agent JSON
    ir = extract_or_load_ir(config)
    
    # Agent 2 -> Registry
    logger.info(f"Running Agent 2 mapping and consolidation (workers={config.workers})...")
    from src.agents.agent2.workflow import get_agent2
    
    if config.workers > 1:
        mapped_sets, gap, entities_to_map = _step2_map_parallel(ir, config.workers)
    else:
        mapped_sets, _, _ = PipelineSupervisor._step2_map(ir, get_agent2)
    consolidated_sets = PipelineSupervisor._step2_5_consolidate(mapped_sets)
    registered_sets = PipelineSupervisor._step3_register(consolidated_sets, registry, RegisteredConcept)
    
    # Agent 3
    logger.info("Running Agent 3 cohort assembly...")
    assembly_result = agent3.assemble(ir, registered_sets)
    agent_circe = assembly_result.circe_json
    
    # Initialize WebAPI and DB Connectors
    webapi = WebAPIClient()
    omop = OMOPConnector()
    
    # 3. Generate Gold Cohort (with Caching)
    cache = load_gold_cache(config.output_dir)
    gold_cohort_id = cache.get(gold_hash)
    
    if gold_cohort_id:
        logger.info(f"Cache HIT for Gold Cohort: ID={gold_cohort_id}")
    else:
        logger.info("Cache MISS for Gold Cohort. Generating in WebAPI...")
        # Unique name to avoid collisions
        gold_name = f"GOLD_{config.trial_type}_{uuid.uuid4().hex[:8]}"
        gold_ref = webapi.generate_cohort(gold_circe, name=gold_name, force_regenerate=True)
        gold_cohort_id = gold_ref.cohort_definition_id
        
        # Save to cache
        cache[gold_hash] = gold_cohort_id
        save_gold_cache(config.output_dir, cache)

    # 4. Generate Agent Cohort
    agent_name = f"AGENT_{config.trial_type}_{config.run_mode}_{uuid.uuid4().hex[:8]}"
    logger.info(f"Generating Agent Cohort in WebAPI ({agent_name})...")
    agent_ref = webapi.generate_cohort(agent_circe, name=agent_name, force_regenerate=True)
    agent_cohort_id = agent_ref.cohort_definition_id

    # 5. Overlap Evaluation (Jaccard)
    logger.info(f"Comparing Cohorts in DB: Gold({gold_cohort_id}) vs Agent({agent_cohort_id})")
    
    # Wait for WebAPI Spring Batch transaction to fully commit
    time.sleep(3)
    
    metrics = omop.get_cohort_overlap_metrics(gold_cohort_id, agent_cohort_id)
    
    if not metrics:
        logger.error("Failed to query overlap metrics from DB.")
        metrics = {}
        
    execution_time = time.time() - start_time
    
    # Compile results
    result = {
        "trial_name": config.trial_type,
        "run_mode": config.run_mode,
        "timestamp": datetime.now().isoformat(),
        "execution_time_seconds": round(execution_time, 2),
        "metrics": metrics,
        "gold_cohort_id": gold_cohort_id,
        "agent_cohort_id": agent_cohort_id,
        "gold_json_hash": gold_hash,
        "payloads": {
            "gold_circe": gold_circe,
            "agent_circe": agent_circe
        }
    }
    
    # Print summary
    print("\n" + "="*50)
    print(f"  Cohort Benchmark Results: {config.trial_type} ({config.run_mode})")
    print("="*50)
    print(f"Gold Patients  : {metrics.get('gold_total', 0):,}")
    print(f"Agent Patients : {metrics.get('agent_total', 0):,}")
    print(f"Intersection   : {metrics.get('intersection_count', 0):,}")
    print(f"Agent Only (FP): {metrics.get('agent_only_count', 0):,}")
    print(f"Gold Only (FN) : {metrics.get('gold_only_count', 0):,}")
    print("-" * 50)
    print(f"Precision      : {metrics.get('precision', 0.0):.1%}")
    print(f"Recall         : {metrics.get('recall', 0.0):.1%}")
    print(f"F1 Score       : {metrics.get('f1_score', 0.0):.1%}")
    print(f"Jaccard (IOU)  : {metrics.get('jaccard_similarity', 0.0):.1%}")
    print("="*50 + "\n")
    
    # Save output
    os.makedirs(config.output_dir, exist_ok=True)
    out_path = os.path.join(
        config.output_dir, 
        f"benchmark_cohort_{config.trial_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(out_path, 'w') as f:
        json.dump(result, f, indent=2)
    logger.info(f"Saved benchmark results to {out_path}")
    
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARTEMIS V6 Cohort Overlap Benchmark")
    parser.add_argument("--trial", type=str, required=True, choices=["LEADER", "PLATO", "ARISTOTLE"], help="Trial to benchmark")
    parser.add_argument("--mode", type=str, default="E2E_SUPP", help="Run mode flag")
    parser.add_argument("--gold", type=str, required=True, help="Path to the Gold Standard Circe JSON file")
    parser.add_argument("--workers", type=int, default=1, help="Number of parallel workers for Agent 2 mapping")
    
    args = parser.parse_args()
    
    config = BenchmarkConfig(
        trial_type=args.trial,
        run_mode=args.mode,
        gold_json_path=args.gold,
        output_dir=os.path.join(os.path.dirname(__file__), "..", "output"),
        workers=args.workers,
    )
    
    run_cohort_benchmark(config)
