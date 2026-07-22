"""
ARTEMIS Pipeline Supervisor — Pipeline orchestrator and quality gate.

ADR-023 Phase 2: Promoted from quality-gate-only to full pipeline orchestrator.

Responsibilities:
1. Run the full cohort definition pipeline (Agent 1-4)
2. Post-Agent2 Quality Gate: detect low seed count / empty mappings (report-only)
3. Loop 1 retry: re-map failed entities after Agent 3/4

Toggle: ENABLE_SUPERVISOR=0 to disable quality gate (pipeline still runs).
"""
import os
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.models.ir import ARTEMISRequest, LoopResult, GapReport
from src.registry.models import RegisteredConceptSet
from src.agents.agent3.assembler import HealAction
from src.agents.agent4.validator import ValidationResult

logger = logging.getLogger(__name__)


# ── Configuration ──

SUPERVISOR_ENABLED = os.environ.get("ENABLE_SUPERVISOR", "1") != "0"
MIN_SEED_COUNT = int(os.environ.get("SUPERVISOR_MIN_SEEDS", "1"))
DOMAIN_MISMATCH_THRESHOLD = float(os.environ.get("SUPERVISOR_DOMAIN_THRESHOLD", "0.5"))

MAX_LOOP_ATTEMPTS = 3


def _agent2_parallel_enabled() -> bool:
    return os.environ.get("SUPERVISOR_AGENT2_PARALLEL", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }


def _agent2_parallel_max_workers(entity_count: int) -> int:
    raw = os.environ.get("SUPERVISOR_AGENT2_MAX_WORKERS", "4").strip()
    try:
        configured = int(raw)
    except ValueError:
        configured = 4
    return max(1, min(configured, max(1, entity_count)))


def _agent2_parallel_trace_enabled() -> bool:
    return os.environ.get("SUPERVISOR_AGENT2_PARALLEL_TRACE", "0").strip().lower() not in {
        "0",
        "false",
        "no",
    }


def _agent2_parallel_slow_ms() -> Optional[float]:
    raw = os.environ.get("SUPERVISOR_AGENT2_PARALLEL_SLOW_MS", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


# ── Data Models ──

@dataclass
class RetryReason:
    """Why a specific entity needs retry."""
    entity_text: str
    domain_hint: Optional[str]
    reason: str  # "empty", "low_seeds", "domain_mismatch"
    seed_count: int = 0
    mismatch_ratio: float = 0.0


@dataclass
class SupervisorReport:
    """Result of supervisor evaluation on Agent 2 outputs."""
    entities_checked: int = 0
    entities_ok: int = 0
    retries_triggered: int = 0
    retry_reasons: list[RetryReason] = field(default_factory=list)
    retry_results: list[dict] = field(default_factory=list)
    detailed_log: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return (
            f"Supervisor: {self.entities_checked} checked, "
            f"{self.entities_ok} OK, {self.retries_triggered} retried"
        )


@dataclass
class Agent2EntityReport:
    index: int
    entity_key: str
    source: str
    domain: str
    final_status: str
    route_path: Optional[str] = None
    concept_count: int = 0
    processing_time_ms: float = 0.0
    used_sequential_retry: bool = False
    error: Optional[str] = None


@dataclass
class Agent2MappingTelemetry:
    mode: str = "sequential"
    entity_count: int = 0
    max_workers_used: int = 1
    parallel_enabled: bool = False
    sequential_retry_count: int = 0
    pool_fallback: bool = False
    pool_fallback_error: Optional[str] = None
    success_count: int = 0
    empty_count: int = 0
    error_count: int = 0
    route_counts: dict[str, int] = field(default_factory=dict)
    wall_time_ms: float = 0.0
    entity_reports: list[Agent2EntityReport] = field(default_factory=list)


@dataclass
class PipelineResult:
    """Result of the cohort definition pipeline.

    ADR-023 Phase 2: Canonical definition moved here from cohort_pipeline.py.
    cohort_pipeline.py re-exports this for backward compatibility.
    """
    ir: ARTEMISRequest
    concept_sets: list[RegisteredConceptSet]
    circe_json: Dict[str, Any]
    validation: ValidationResult
    comparator_circe_json: Optional[Dict[str, Any]] = None
    heal_log: list[HealAction] = None  # type: ignore[assignment]
    completeness: float = 1.0
    skipped_rules: list[str] = field(default_factory=list)
    loop_results: list[LoopResult] = field(default_factory=list)
    gap_report: GapReport = field(default_factory=GapReport)
    supervisor_report: SupervisorReport = field(default_factory=SupervisorReport)
    agent2_mapping_telemetry: Agent2MappingTelemetry = field(default_factory=Agent2MappingTelemetry)

    @property
    def is_valid(self) -> bool:
        return self.validation.valid

    @property
    def has_assembly_failures(self) -> bool:
        return bool(self.heal_log and any(
            h.action == "SKIP" for h in self.heal_log
        ))

    @property
    def needs_human_review(self) -> bool:
        """Loop 3 HITL trigger: True if mapping rate < 80% or completeness < 0.5."""
        low_mapping = self.gap_report.mapping_rate < 80.0
        low_completeness = self.completeness < 0.5
        return low_mapping or low_completeness


class PipelineSupervisor:
    """Pipeline Orchestrator for ARTEMIS cohort definition (Agent 1-4).

    ADR-023 Phase 2: Promoted from quality-gate to full orchestrator.

    Flow:
    1.   Agent 1: NL → IR
    1.5. Planner: Decompose composite criteria
    2.   Agent 2: Entity text → OMOP Concept IDs
    2.1. Quality Gate: Check mapping quality (report-only, ADR-024)
    2.5. Consolidator: Merge sibling ConceptSets
    3.   Registry: Store ConceptSets
    4.   Agent 3: IR + ConceptSets → Circe JSON
    5.   Agent 4: Validate Circe JSON
    * Loop 1: Re-map failed entities (max 3 attempts)
    """

    def __init__(self):
        self.enabled = SUPERVISOR_ENABLED

    # ══════════════════════════════════════════════════════════════
    # Public API: Full Pipeline Orchestration
    # ══════════════════════════════════════════════════════════════

    def run(self, query: str) -> PipelineResult:
        """Execute the full cohort definition pipeline.

        Args:
            query: Natural language clinical question

        Returns:
            PipelineResult with IR, ConceptSets, JSON, and validation
        """
        from src.agents.agent1.parser import get_agent1
        from src.agents.planner import get_planner
        from src.agents.agent2.workflow import get_agent2
        from src.agents.consolidator import ConceptSetConsolidator
        from src.agents.agent3.assembler import agent3
        from src.agents.agent4.validator import agent4
        from src.registry.models import RegisteredConcept
        from src.registry.store import registry

        print(f"\n{'='*60}")
        print("ARTEMIS 3.1 COHORT PIPELINE")
        print(f"{'='*60}")
        print(f"Query: {query[:100]}...")
        print(f"{'='*60}\n")

        # Step 1 + 1.5: Parse and plan
        ir = self._step1_parse(query, get_agent1, get_planner)

        # Step 2: Map entities
        concept_sets, gap_report, entities_to_map, agent2_mapping_telemetry = self._step2_map(ir, get_agent2)

        # Step 2.1: Quality gate (report-only, ADR-024)
        supervisor_report = self.post_agent2_check(
            mapped_sets=concept_sets,
            gap_report=gap_report,
            entities_to_map=entities_to_map,
        )
        if supervisor_report.retries_triggered > 0:
            print(f"[Step 2.1] Supervisor: {supervisor_report.retries_triggered} weak entities detected (report-only)")
        else:
            print("[Step 2.1] Supervisor: All entities passed quality gate ✓")
        print()

        # Step 2.5: Consolidate
        concept_sets = self._step2_5_consolidate(concept_sets)

        # Step 3: Register
        registered_sets = self._step3_register(concept_sets, registry, RegisteredConcept)

        # Steps 4-5 with retry loop
        assembly_result, validation, loop_results = self._step4_5_assemble_validate(
            ir, registered_sets, agent3, agent4, get_agent2, registry, RegisteredConcept,
            entities_to_map=entities_to_map,
        )

        # Compute completeness
        skipped_rules = [h.rule_name for h in assembly_result.heal_log if h.action == "SKIP"]
        total_rules = len(assembly_result.heal_log)
        completeness = 1.0 if total_rules == 0 else (
            (total_rules - len(skipped_rules)) / total_rules
        )

        return PipelineResult(
            ir=ir,
            concept_sets=registered_sets,
            circe_json=assembly_result.circe_json,
            comparator_circe_json=assembly_result.comparator_circe_json,
            validation=validation,
            heal_log=assembly_result.heal_log,
            completeness=completeness,
            skipped_rules=skipped_rules,
            loop_results=loop_results,
            gap_report=gap_report,
            supervisor_report=supervisor_report,
            agent2_mapping_telemetry=agent2_mapping_telemetry,
        )

    # ══════════════════════════════════════════════════════════════
    # Pipeline Steps
    # ══════════════════════════════════════════════════════════════

    @staticmethod
    def _step1_parse(query, get_agent1, get_planner):
        """Step 1 + 1.5: Parse NL/NCT to IR, then decompose with Planner."""
        if query.strip().upper().startswith("NCT"):
            nct_id = query.strip()
            print(f"[Step 1] Agent 1: Parsing NCT protocol ({nct_id})...")
            ir = get_agent1().parse_nct(nct_id)
            print(f"  ✓ Generated IR from {nct_id}\n")
        else:
            print("[Step 1] Agent 1: Parsing natural language...")
            ir = get_agent1().parse(query)
            print(f"  ✓ Generated IR with target/comparator/outcome\n")

        print("[Step 1.5] Planner: Decomposing composite criteria...")
        ir = get_planner().plan(ir)
        print(f"  ✓ Criteria decomposition complete\n")
        return ir

    @staticmethod
    def _step2_map(ir, get_agent2):
        """Step 2: Map all entities in IR to OMOP concepts using Agent 2."""
        print("[Step 2] Agent 2: Mapping entities to OMOP concepts...")
        batch_start = time.perf_counter()

        entities_to_map = []
        gap = GapReport()

        # Collect entities from target
        entities_to_map.extend(PipelineSupervisor._collect_cohort_entities(ir.target, "target"))
        entities_to_map.extend(PipelineSupervisor._collect_cohort_entities(ir.comparator, "comparator"))

        if ir.outcome.entity_text:
            entities_to_map.append({
                "text": ir.outcome.entity_text,
                "domain": ir.outcome.domain,
                "source": "outcome",
                "entity_key": "outcome:primary:0:0",
            })

        gap.total_criteria = len(entities_to_map)

        outcomes, telemetry = PipelineSupervisor._map_entities_with_fallback(entities_to_map)
        mapped_sets = PipelineSupervisor._build_mapped_sets_and_gap(outcomes, gap, telemetry)
        telemetry.wall_time_ms = round((time.perf_counter() - batch_start) * 1000, 3)

        print(f"  ✓ Mapped {len(mapped_sets)} concept sets")
        if gap.unmapped_count > 0:
            print(f"  ⚠ Gap Report: {gap.mapping_rate:.0f}% mapped ({gap.unmapped_count} gaps)")
        print()

        return mapped_sets, gap, entities_to_map, telemetry

    @staticmethod
    def _map_entities_with_fallback(entities_to_map: list[dict]) -> tuple[list[dict], Agent2MappingTelemetry]:
        telemetry = Agent2MappingTelemetry(
            mode="sequential",
            entity_count=len(entities_to_map),
            max_workers_used=1,
            parallel_enabled=_agent2_parallel_enabled(),
        )
        if len(entities_to_map) <= 1 or not _agent2_parallel_enabled():
            outcomes = [
                PipelineSupervisor._map_single_entity_work_item(index, entity)
                for index, entity in enumerate(entities_to_map)
            ]
            return outcomes, telemetry

        max_workers = _agent2_parallel_max_workers(len(entities_to_map))
        telemetry.mode = "parallel"
        telemetry.max_workers_used = max_workers
        logger.info(
            "Agent 2 parallel batch start: entities=%s max_workers=%s",
            len(entities_to_map),
            max_workers,
        )
        try:
            outcomes_by_index: dict[int, dict] = {}
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                future_to_payload = {
                    pool.submit(PipelineSupervisor._map_single_entity_work_item, index, entity): (index, entity)
                    for index, entity in enumerate(entities_to_map)
                }
                for future in as_completed(future_to_payload):
                    index, entity = future_to_payload[future]
                    outcome = future.result()
                    emr = outcome.get("emr")
                    if (outcome.get("raised_error") or (emr is not None and emr.error is not None)):
                        retry_outcome = PipelineSupervisor._map_single_entity_work_item(index, entity)
                        retry_outcome["used_sequential_retry"] = True
                        telemetry.sequential_retry_count += 1
                        logger.warning(
                            "Agent 2 sequential retry: entity_key=%s source=%s domain=%s",
                            entity.get("entity_key"),
                            entity.get("source"),
                            entity.get("domain"),
                        )
                        outcome = retry_outcome
                    PipelineSupervisor._maybe_log_parallel_entity_trace(outcome)
                    outcomes_by_index[index] = outcome
            outcomes = [outcomes_by_index[index] for index in range(len(entities_to_map))]
            logger.info(
                "Agent 2 parallel batch summary: entities=%s retries=%s pool_fallback=%s",
                len(entities_to_map),
                telemetry.sequential_retry_count,
                telemetry.pool_fallback,
            )
            return outcomes, telemetry
        except Exception as exc:
            print(f"  ⚠ Parallel Agent 2 mapping unavailable, falling back to sequential mapping: {exc}")
            telemetry.pool_fallback = True
            telemetry.pool_fallback_error = str(exc)
            telemetry.mode = "sequential"
            telemetry.max_workers_used = 1
            logger.warning("Agent 2 parallel pool fallback: %s", exc)
            outcomes = [
                PipelineSupervisor._map_single_entity_work_item(index, entity)
                for index, entity in enumerate(entities_to_map)
            ]
            logger.info(
                "Agent 2 parallel batch summary: entities=%s retries=%s pool_fallback=%s",
                len(entities_to_map),
                telemetry.sequential_retry_count,
                telemetry.pool_fallback,
            )
            return outcomes, telemetry

    @staticmethod
    def _map_single_entity_work_item(index: int, entity: dict) -> dict:
        started = time.perf_counter()
        try:
            raw_rule = entity.get("parent_rule")
            rule_context = raw_rule.replace("_", " ").title() if raw_rule else None

            from src.agents.agent2.map_entity import map_single_entity

            emr = map_single_entity(
                entity["text"],
                domain_hint=entity.get("domain"),
                rule_context=rule_context,
            )
            return {
                "index": index,
                "entity": entity,
                "emr": emr,
                "raised_error": None,
                "used_sequential_retry": False,
                "processing_time_ms": round(
                    (emr.processing_time_ms or (time.perf_counter() - started) * 1000),
                    3,
                ),
            }
        except Exception as exc:
            return {
                "index": index,
                "entity": entity,
                "emr": None,
                "raised_error": str(exc),
                "used_sequential_retry": False,
                "processing_time_ms": round((time.perf_counter() - started) * 1000, 3),
            }

    @staticmethod
    def _build_mapped_sets_and_gap(
        outcomes: list[dict], gap: GapReport, telemetry: Agent2MappingTelemetry
    ) -> list[dict]:
        mapped_sets = []
        route_counter: Counter[str] = Counter()
        for outcome in outcomes:
            index = outcome["index"]
            entity = outcome["entity"]
            emr = outcome.get("emr")
            processing_time_ms = float(outcome.get("processing_time_ms") or 0.0)
            route_path = emr.route_path if emr is not None else None
            if route_path:
                route_counter[route_path] += 1
            if emr is not None and emr.success:
                gap.mapped_count += 1
                telemetry.success_count += 1
                telemetry.entity_reports.append(
                    Agent2EntityReport(
                        index=index,
                        entity_key=entity.get("entity_key", ""),
                        source=entity.get("source", "inclusion"),
                        domain=entity.get("domain", ""),
                        final_status="success",
                        route_path=route_path,
                        concept_count=len(emr.concept_ids),
                        processing_time_ms=processing_time_ms,
                        used_sequential_retry=bool(outcome.get("used_sequential_retry")),
                        error=None,
                    )
                )
                mapped_sets.append(
                    emr.to_mapped_set(
                        entity_id=index + 1,
                        entity_text=entity["text"],
                        domain=entity["domain"],
                        source=entity["source"],
                        parent_rule=entity.get("parent_rule"),
                        entity_key=entity.get("entity_key"),
                    )
                )
                continue

            reason = outcome.get("raised_error") or (emr.error if emr is not None else None)
            if not reason:
                reason = "Agent 2 returned empty concept_ids"
                telemetry.empty_count += 1
                final_status = "empty"
            else:
                telemetry.error_count += 1
                final_status = "error"
            telemetry.entity_reports.append(
                Agent2EntityReport(
                    index=index,
                    entity_key=entity.get("entity_key", ""),
                    source=entity.get("source", "inclusion"),
                    domain=entity.get("domain", ""),
                    final_status=final_status,
                    route_path=route_path,
                    concept_count=len(emr.concept_ids) if emr is not None else 0,
                    processing_time_ms=processing_time_ms,
                    used_sequential_retry=bool(outcome.get("used_sequential_retry")),
                    error=reason,
                )
            )
            print(f"  ⚠ Failed to map '{entity['text']}': {reason}")
            gap.add_gap(
                item_id=f"entity_{index}",
                original_text=entity["text"],
                reason=reason,
                section=entity.get("source", "inclusion"),
                domain=entity.get("domain"),
            )
        telemetry.route_counts = dict(route_counter)
        return mapped_sets

    @staticmethod
    def _maybe_log_parallel_entity_trace(outcome: dict) -> None:
        entity = outcome["entity"]
        emr = outcome.get("emr")
        processing_time_ms = float(outcome.get("processing_time_ms") or 0.0)
        threshold = _agent2_parallel_slow_ms()
        if threshold is not None and processing_time_ms >= threshold:
            logger.warning(
                "Agent 2 slow entity: entity_key=%s source=%s domain=%s processing_time_ms=%.3f",
                entity.get("entity_key"),
                entity.get("source"),
                entity.get("domain"),
                processing_time_ms,
            )
        if not _agent2_parallel_trace_enabled():
            return
        reason = outcome.get("raised_error") or (emr.error if emr is not None else None)
        logger.info(
            "Agent 2 entity trace: index=%s entity_key=%s source=%s domain=%s route=%s processing_time_ms=%.3f used_sequential_retry=%s error=%s",
            outcome.get("index"),
            entity.get("entity_key"),
            entity.get("source"),
            entity.get("domain"),
            emr.route_path if emr is not None else None,
            processing_time_ms,
            bool(outcome.get("used_sequential_retry")),
            reason,
        )

    @staticmethod
    def _step2_5_consolidate(mapped_sets):
        """Step 2.5: Consolidate sibling ConceptSets using OMOP hierarchy."""
        print("[Step 2.5] Consolidator: Merging sibling concept sets...")
        try:
            from src.agents.conceptset.ontology_search import get_ontology_search
            from src.agents.consolidator import ConceptSetConsolidator
            consolidator = ConceptSetConsolidator(ontology_search=get_ontology_search())
            result = consolidator.consolidate(mapped_sets)
        except Exception as e:
            print(f"  ⚠ Consolidation skipped: {e}")
            result = mapped_sets
        print(f"  ✓ Consolidated to {len(result)} concept sets\n")
        return result

    @staticmethod
    def _step3_register(mapped_sets, registry, RegisteredConcept):
        """Step 3: Register mapped concept sets in the global registry."""
        print("[Step 3] Registry: Storing concept sets...")

        registered = []
        seen_ids = set()

        all_concept_ids = set()
        for ms in mapped_sets:
            all_concept_ids.update(ms.get("concept_ids", []))

        concept_meta = PipelineSupervisor._fetch_concept_metadata(list(all_concept_ids))

        for ms in mapped_sets:
            overbroad_ids = set(ms.get("overbroad_concept_ids", []))
            concepts = []
            for cid in ms.get("concept_ids", []):
                if cid in concept_meta:
                    meta = concept_meta[cid]
                    concepts.append(RegisteredConcept(
                        concept_id=cid,
                        concept_name=meta["concept_name"],
                        domain_id=meta["domain_id"],
                        vocabulary_id=meta["vocabulary_id"],
                        concept_class_id=meta.get("concept_class_id", ""),
                        standard_concept=meta.get("standard_concept", "S"),
                        include_descendants=(cid not in overbroad_ids)
                    ))
                else:
                    print(f"  ⚠ Concept ID {cid} not found in vocabulary, skipping")

            if concepts:
                result = registry.register(
                    name=ms["name"],
                    concepts=concepts,
                    source_entity_text=ms["name"],
                )
                if result.concept_set and result.concept_set.id not in seen_ids:
                    seen_ids.add(result.concept_set.id)
                    registered.append(result.concept_set)

        print(f"  ✓ Registered {len(registered)} sets (with deduplication)\n")
        return registered

    @staticmethod
    def _step4_5_assemble_validate(ir, registered_sets, agent3, agent4, get_agent2, registry, RegisteredConcept, *, entities_to_map=None):
        """Steps 4-5: Assemble Circe JSON + Validate, with Loop 1 retry."""
        loop_results = []
        assembly_result = None
        validation = None

        # Build entity lookup for domain/parent_rule recovery during re-mapping
        entity_lookup: dict = {}
        for ent in (entities_to_map or []):
            entity_lookup[ent["text"].lower()] = ent

        for attempt in range(1, MAX_LOOP_ATTEMPTS + 1):
            print(f"[Step 4] Agent 3: Assembling Circe JSON (attempt {attempt}/{MAX_LOOP_ATTEMPTS})...")
            assembly_result = agent3.assemble(ir, registered_sets)

            if assembly_result.has_failures:
                failed = assembly_result.failed_entities
                print(f"  ⚠ {len(failed)} rule(s) dropped due to missing concepts:")
                for h in assembly_result.heal_log:
                    if h.action == "SKIP":
                        print(f"     - '{h.rule_name}': {h.reason}")
                    elif h.action == "PARTIAL":
                        print(f"     ~ '{h.rule_name}': {h.reason}")
            print(f"  ✓ Generated Circe JSON\n")

            print(f"[Step 5] Agent 4: Validating (attempt {attempt}/{MAX_LOOP_ATTEMPTS})...")
            validation = agent4.validate(assembly_result.circe_json)
            print(agent4.format_report(validation))

            if not assembly_result.has_failures:
                loop_results.append(LoopResult(
                    loop_id="LOOP_1_REMAP", attempt=attempt,
                    max_attempts=MAX_LOOP_ATTEMPTS, status="SUCCESS",
                    details="No assembly failures"
                ))
                break

            failed_entities = [
                {
                    "text": h.entity_text,
                    "domain": entity_lookup.get(h.entity_text.lower(), {}).get("domain"),
                    "parent_rule": entity_lookup.get(h.entity_text.lower(), {}).get("parent_rule"),
                }
                for h in assembly_result.heal_log if h.action == "SKIP"
            ]
            failed_texts = [e["text"] for e in failed_entities]
            loop_result = LoopResult(
                loop_id="LOOP_1_REMAP", attempt=attempt,
                max_attempts=MAX_LOOP_ATTEMPTS, status="FAILED",
                remaining_failures=failed_texts,
                details=f"Attempt {attempt}: {len(failed_texts)} entities failed mapping"
            )

            if attempt >= MAX_LOOP_ATTEMPTS:
                loop_result.status = "FAILED"
                loop_results.append(loop_result)
                print(f"  ⚠ Max retry attempts reached ({MAX_LOOP_ATTEMPTS}). Proceeding with partial result.\n")
                break

            print(f"\n  🔄 Loop 1: Re-mapping {len(failed_entities)} failed entities...")
            from src.pipeline.mapping_retry import remap_and_register_entities
            remap_results = remap_and_register_entities(
                failed_entities,
                registry, RegisteredConcept, registered_sets,
            )
            remapped_any = any(r.success for r in remap_results)

            if not remapped_any:
                loop_result.status = "FAILED"
                loop_result.details = f"Attempt {attempt}: re-mapping produced no new results"
                loop_results.append(loop_result)
                print(f"  ⚠ No new mappings found. Stopping retry loop.\n")
                break

            loop_result.status = "PARTIAL"
            loop_results.append(loop_result)
            print(f"  ✓ Re-mapping complete. Retrying assembly...\n")

        return assembly_result, validation, loop_results

    # ══════════════════════════════════════════════════════════════
    # Entity Collection Helpers
    # ══════════════════════════════════════════════════════════════

    @staticmethod
    def _collect_cohort_entities(cohort, source):
        """Collect all entity texts from a cohort definition.
        
        Each entity gets a stable `entity_key` for identity tracking:
        Format: "{source}:{section}:{rule_idx}:{sub_idx}"
        Examples: "target:primary:0:0", "target:inclusion:2:1"
        """
        entities = []
        if cohort.primary_criteria.entity_text:
            entities.append({
                "text": cohort.primary_criteria.entity_text,
                "domain": cohort.primary_criteria.domain,
                "source": source,
                "entity_key": f"{source}:primary:0:0",
            })
        for i, rule in enumerate(cohort.inclusion_rules):
            entities.extend(PipelineSupervisor._collect_rule_entities(rule, source, "inclusion", i))
        for i, rule in enumerate(cohort.exclusion_rules):
            entities.extend(PipelineSupervisor._collect_rule_entities(rule, source, "exclusion", i))
        return entities

    @staticmethod
    def _collect_rule_entities(rule, source, section="inclusion", rule_idx=0):
        """Collect entity texts from a rule, including sub_criteria.

        Each entity gets a stable `entity_key` for pipeline-wide identity tracking.

        Applies Hierarchical Expansion: when a composite rule has sub_criteria,
        the original rule name is also included if not already present.
        (See §11 in BENCHMARK_CONSOLIDATED_REPORT.md — A' vs A: +6.7pp recall)
        """
        entities = []
        parent_key = rule.name.lower().replace(" ", "_") if rule.name else None
        if rule.sub_criteria:
            for sub_idx, sc in enumerate(rule.sub_criteria):
                if sc.entity_text:
                    entities.append({
                        "text": sc.entity_text, "domain": sc.domain,
                        "source": source, "parent_rule": parent_key,
                        "entity_key": f"{source}:{section}:{rule_idx}:{sub_idx}",
                    })
            if rule.entity_text:
                decomposed = {e["text"].lower() for e in entities}
                original = rule.entity_text.lower()
                if original not in decomposed:
                    primary_domain = entities[0]["domain"] if entities else (rule.domain or "Condition")
                    # Original text gets sub_idx = -1 (sentinel for "parent original")
                    entities.insert(0, {
                        "text": rule.entity_text, "domain": primary_domain,
                        "source": source, "parent_rule": parent_key,
                        "entity_key": f"{source}:{section}:{rule_idx}:-1",
                    })
        elif rule.entity_text:
            entities.append({
                "text": rule.entity_text, "domain": rule.domain,
                "source": source,
                "entity_key": f"{source}:{section}:{rule_idx}:0",
            })
        return entities

    # ══════════════════════════════════════════════════════════════
    # DB Helpers
    # ══════════════════════════════════════════════════════════════

    @staticmethod
    def _fetch_concept_metadata(concept_ids):
        """Batch-fetch concept metadata from OMOP vocabulary."""
        if not concept_ids:
            return {}

        from sqlalchemy import text
        from src.utils.db import engine
        from src.settings import settings

        schema = settings.CDM_SCHEMA

        with engine.connect() as conn:
            result = conn.execute(
                text(f"""
                    SELECT concept_id, concept_name, domain_id, vocabulary_id,
                           concept_class_id, standard_concept
                    FROM {schema}.concept
                    WHERE concept_id = ANY(:ids)
                """),
                {"ids": concept_ids}
            )
            rows = result.fetchall()

        concept_map = {}
        for row in rows:
            concept_map[row[0]] = {
                "concept_name": row[1], "domain_id": row[2],
                "vocabulary_id": row[3], "concept_class_id": row[4] or "",
                "standard_concept": row[5] or "",
            }

        found = len(concept_map)
        total = len(concept_ids)
        if found < total:
            missing = set(concept_ids) - set(concept_map.keys())
            print(f"  ⚠ {total - found}/{total} concept IDs not found in {schema}.concept: {missing}")

        return concept_map

    # ══════════════════════════════════════════════════════════════
    # Quality Gate (Post-Agent2)
    # ══════════════════════════════════════════════════════════════

    def post_agent2_check(
        self,
        mapped_sets: list[dict],
        gap_report,
        entities_to_map: list[dict],
    ) -> SupervisorReport:
        """Evaluate Agent 2 mapping quality and trigger retries for weak entities.
        
        Args:
            mapped_sets: Successfully mapped entities from _map_all_entities
            gap_report: GapReport with unmapped entities
            entities_to_map: Original entity list before mapping
            
        Returns:
            SupervisorReport with retry decisions
        """
        report = SupervisorReport()

        if not self.enabled:
            logger.info("[Supervisor] Disabled (ENABLE_SUPERVISOR=0)")
            return report

        report.entities_checked = len(entities_to_map)

        # Build lookup of what was mapped
        mapped_texts = {ms["name"].lower(): ms for ms in mapped_sets}

        for entity in entities_to_map:
            text = entity["text"]
            text_lower = text.lower()
            domain_hint = entity.get("domain")

            # Case 1: Entity was not mapped at all (in gap_report)
            if text_lower not in mapped_texts:
                report.retry_reasons.append(RetryReason(
                    entity_text=text,
                    domain_hint=domain_hint,
                    reason="empty",
                    seed_count=0,
                ))
                continue

            ms = mapped_texts[text_lower]
            concept_ids = ms.get("concept_ids", [])
            seed_count = len(concept_ids)

            # Case 2: Too few seeds
            if seed_count < MIN_SEED_COUNT:
                report.retry_reasons.append(RetryReason(
                    entity_text=text,
                    domain_hint=domain_hint,
                    reason="low_seeds",
                    seed_count=seed_count,
                ))
                continue

            # Case 3: Domain mismatch (requires metadata lookup)
            # Defer to _check_domain_mismatch if we have metadata
            # For now, mark as OK
            report.entities_ok += 1

        report.retries_triggered = len(report.retry_reasons)
        if report.retry_reasons:
            logger.info(
                f"[Supervisor] {report.retries_triggered} entities need retry: "
                + ", ".join(f"'{r.entity_text}' ({r.reason})" for r in report.retry_reasons)
            )
        else:
            logger.info(f"[Supervisor] All {report.entities_ok} entities passed quality gate")

        return report




# ── Singleton ──

_supervisor: Optional[PipelineSupervisor] = None


def get_supervisor() -> PipelineSupervisor:
    """Get or create the singleton supervisor instance."""
    global _supervisor
    if _supervisor is None:
        _supervisor = PipelineSupervisor()
    return _supervisor
