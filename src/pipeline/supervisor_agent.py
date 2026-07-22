"""
ARTEMIS Supervisor Agent — LangGraph-based 6-Agent Orchestrator.

Manages the full pipeline: Trial → Mapping → Assembly → Extraction → Analysis → Reporting.
Each agent execution is followed by a review node that evaluates the result
and decides: PROCEED / RETRY / SKIP / ESCALATE.

References:
- ADR-023: Supervisor Orchestrator Promotion
- RFC-005: Pipeline Feedback Loops (Loop 1-5)
- RFC-012: Post-Agent2 Quality Gate
"""
import logging
import os
from typing import Optional, Any, Literal, Annotated
from typing_extensions import TypedDict
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from langgraph.graph import StateGraph
from langgraph.graph.graph import START, END

from src.models.ir import (
    ARTEMISRequest,
    GapReport,
    LoopResult,
    PipelineErrorClassification,
)
from src.registry.models import RegisteredConceptSet
from src.agents.agent4.validator import ValidationResult

logger = logging.getLogger(__name__)

MAX_RETRY = 3


def _remediation_parallel_enabled() -> bool:
    return os.environ.get("SUPERVISOR_REMEDIATION_PARALLEL", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }


def _remediation_max_workers(candidate_count: int) -> int:
    raw = os.environ.get("SUPERVISOR_REMEDIATION_MAX_WORKERS", "4").strip()
    try:
        configured = int(raw)
    except ValueError:
        configured = 4
    return max(1, min(configured, max(1, candidate_count)))


# ══════════════════════════════════════════════════════════════
# State Definition
# ══════════════════════════════════════════════════════════════

@dataclass
class SupervisorDecision:
    """Result of a Supervisor review node."""
    agent_name: str
    status: Literal["SUCCESS", "PARTIAL", "FAILED"]
    action: Literal["PROCEED", "RETRY", "SELECTIVE_RETRY", "SKIP", "ESCALATE"]
    reason: str
    metrics: dict = field(default_factory=dict)


def _merge_decisions(
    existing: list[SupervisorDecision], new: list[SupervisorDecision]
) -> list[SupervisorDecision]:
    """Merge strategy: append new decisions."""
    return existing + new


def _merge_errors(existing: list[str], new: list[str]) -> list[str]:
    return existing + new


def _merge_loops(existing: list[LoopResult], new: list[LoopResult]) -> list[LoopResult]:
    return existing + new


class ArtemisState(TypedDict, total=False):
    """Full pipeline state tracked across all nodes."""
    # Input
    query: str

    # Agent 1 output
    ir: Optional[ARTEMISRequest]

    # Agent 2 output
    entities_to_map: list[dict]
    mapped_sets: list[dict]
    gap_report: Optional[GapReport]
    agent2_mapping_telemetry: Optional[Any]

    # Registry output
    registered_sets: list[RegisteredConceptSet]

    # Agent 3+4 output
    assembly_result: Optional[Any]  # AssemblyResult from agent3
    circe_json: dict
    comparator_circe_json: Optional[dict]
    validation: Optional[ValidationResult]
    heal_log: Optional[list]

    # Execution output
    patient_data: Optional[Any]  # pd.DataFrame
    execution_diagnostics: list[dict]

    # Agent 5 output
    analysis_results: dict

    # Agent 6 output
    report_path: str
    plot_paths: dict
    report_summary: dict

    # Supervisor tracking
    decisions: Annotated[list[SupervisorDecision], _merge_decisions]
    error_log: Annotated[list[str], _merge_errors]
    loop_results: Annotated[list[LoopResult], _merge_loops]
    retry_counts: dict  # {"mapping": 0, "assembly": 0, ...}
    current_phase: str
    escalate_reason: Optional[str]

    # Phase 2: Pre-consolidation mapping preservation
    raw_mapped_sets: list[dict]  # Entity mappings before consolidation

    # Phase 3: Selective retry queue
    retry_queue: list[dict]  # RetryCandidate dicts for remediation


# ══════════════════════════════════════════════════════════════
# Agent Nodes (execute the actual work)
# ══════════════════════════════════════════════════════════════

def trial_node(state: ArtemisState) -> dict:
    """Step 1 + 1.5: Parse NL/NCT → IR → Planner decomposition."""
    from src.agents.agent1.parser import get_agent1
    from src.agents.planner import get_planner

    query = state["query"]
    logger.info(f"[Trial] Parsing: {query[:80]}...")
    print(f"\n[Trial Agent] Parsing query...")

    try:
        if query.strip().upper().startswith("NCT"):
            ir = get_agent1().parse_nct(query.strip())
        else:
            ir = get_agent1().parse(query)

        ir = get_planner().plan(ir)
        print(f"  ✓ IR generated: {len(ir.target.inclusion_rules)} inc, "
              f"{len(ir.target.exclusion_rules)} exc rules")
        return {"ir": ir, "current_phase": "trial"}
    except Exception as e:
        logger.error(f"[Trial] Failed: {e}")
        return {
            "ir": None,
            "error_log": [f"Trial Agent failed: {e}"],
            "current_phase": "trial",
        }


def mapping_node(state: ArtemisState) -> dict:
    """Step 2 + 2.1 + 2.5 + 3: Map entities → Quality Gate → Consolidate → Register."""
    from src.pipeline.supervisor import get_supervisor
    from src.registry.models import RegisteredConcept
    from src.registry.store import registry

    ir = state["ir"]
    print(f"\n[Mapping Agent] Mapping entities to OMOP concepts...")

    try:
        sv = get_supervisor()

        # Step 2: Map
        mapped_sets, gap, entities, agent2_mapping_telemetry = sv._step2_map(ir)

        # Step 2.1: Quality gate (report-only)
        report = sv.post_agent2_check(mapped_sets, gap, entities)
        if report.retries_triggered > 0:
            print(f"  ⚠ {report.retries_triggered} weak entities detected")

        # Step 2.5: Consolidate
        raw_mapped_sets = list(mapped_sets)  # Phase 2: preserve pre-consolidation
        mapped_sets = sv._step2_5_consolidate(mapped_sets)

        # Step 3: Register
        registered = sv._step3_register(mapped_sets, registry, RegisteredConcept)

        return {
            "entities_to_map": entities,
            "mapped_sets": mapped_sets,
            "raw_mapped_sets": raw_mapped_sets,
            "gap_report": gap,
            "agent2_mapping_telemetry": agent2_mapping_telemetry,
            "registered_sets": registered,
            "current_phase": "mapping",
        }
    except Exception as e:
        logger.error(f"[Mapping] Failed: {e}")
        return {
            "mapped_sets": [],
            "gap_report": GapReport(),
            "registered_sets": [],
            "error_log": [f"Mapping Agent failed: {e}"],
            "current_phase": "mapping",
        }


def assembly_node(state: ArtemisState) -> dict:
    """Step 4 + 5: Assemble Circe JSON + Validate."""
    from src.agents.agent3.assembler import agent3
    from src.agents.agent4.validator import agent4

    ir = state["ir"]
    registered_sets = state.get("registered_sets", [])
    print(f"\n[Assembly] Assembling Circe JSON...")

    try:
        result = agent3.assemble(ir, registered_sets)
        validation = agent4.validate(result.circe_json)
        print(agent4.format_report(validation))

        return {
            "assembly_result": result,
            "circe_json": result.circe_json,
            "treatment_circe_json": result.treatment_circe_json,
            "comparator_circe_json": result.comparator_circe_json,
            "validation": validation,
            "heal_log": result.heal_log,
            "current_phase": "assembly",
        }
    except Exception as e:
        logger.error(f"[Assembly] Failed: {e}")
        return {
            "circe_json": {},
            "validation": None,
            "error_log": [f"Assembly failed: {e}"],
            "current_phase": "assembly",
        }


def extraction_node(state: ArtemisState) -> dict:
    """Execute cohort against OMOP CDM."""
    print(f"\n[Extraction Agent] Executing cohort...")

    try:
        from src.pipeline.cohort_executor import CohortExecutor
        executor = CohortExecutor()
        execution = executor.execute(
            circe_json=state.get("circe_json", {}),
            comparator_circe_json=state.get("comparator_circe_json"),
        )
        diag_dicts = [
            {"concept_id": d.concept_id, "suggestion": d.suggestion, "patient_count": d.patient_count}
            for d in execution.diagnostics
        ] if execution.diagnostics else []

        print(f"  ✓ {execution.patient_count} patients extracted")
        return {
            "patient_data": execution.data,
            "execution_diagnostics": diag_dicts,
            "current_phase": "extraction",
        }
    except Exception as e:
        logger.error(f"[Extraction] Failed: {e}")
        return {
            "patient_data": None,
            "execution_diagnostics": [],
            "error_log": [f"Extraction failed: {e}"],
            "current_phase": "extraction",
        }


def analysis_node(state: ArtemisState) -> dict:
    """Agent 5: Causal inference analysis."""
    print(f"\n[Analysis Agent] Running causal inference...")

    try:
        from src.agents.agent5 import Agent5Workflow
        agent5 = Agent5Workflow()
        results = agent5.run(data=state.get("patient_data"))
        hr = results.get("hazard_ratio", {})
        hr_val = hr.get("hr")
        p_val = hr.get("p_value")
        if hr_val is not None and p_val is not None:
            print(f"  ✓ HR={hr_val:.3f}, p={p_val:.4f}")
        else:
            print(f"  ⚠ HR or p_value missing in results")
        return {"analysis_results": results, "current_phase": "analysis"}
    except Exception as e:
        logger.error(f"[Analysis] Failed: {e}")
        return {
            "analysis_results": {},
            "error_log": [f"Analysis failed: {e}"],
            "current_phase": "analysis",
        }


def reporting_node(state: ArtemisState) -> dict:
    """Agent 6: Generate report and visualizations."""
    print(f"\n[Reporting Agent] Generating report...")

    try:
        from src.agents.agent6 import Agent6Workflow
        agent6 = Agent6Workflow()
        results = state.get("analysis_results", {})
        hr = results.get("hazard_ratio", {})

        from src.reporting.models import HazardRatioSummary
        hr_summary = HazardRatioSummary(
            hr=hr.get("hr", 1.0),
            ci_lower=hr.get("ci_lower", 0.5),
            ci_upper=hr.get("ci_upper", 2.0),
            p_value=hr.get("p_value", 1.0),
        )
        agent6.set_results(
            study_title=f"ARTEMIS: {state['query'][:50]}",
            hazard_ratio=hr_summary,
            target_n=results.get("n_target", 0),
            comparator_n=results.get("n_comparator", 0),
            balance=results.get("balance", {}),
            ps_scores=results.get("ps_scores", []),
            treatment=results.get("treatment", []),
            survival_data=results.get("survival_data", {}),
        )

        output_dir = "./output/artemis_run"
        plot_paths = agent6.generate_plots(f"{output_dir}/plots")
        report_path = f"{output_dir}/report.html"
        agent6.generate_html_report(report_path)
        print(f"  ✓ Report: {report_path}")

        return {
            "report_path": report_path,
            "plot_paths": plot_paths,
            "current_phase": "reporting",
        }
    except Exception as e:
        logger.error(f"[Reporting] Failed: {e}")
        return {
            "report_path": "",
            "plot_paths": {},
            "error_log": [f"Reporting failed: {e}"],
            "current_phase": "reporting",
        }


# ══════════════════════════════════════════════════════════════
# Review Nodes (Supervisor evaluates each agent's output)
# ══════════════════════════════════════════════════════════════

def review_trial(state: ArtemisState) -> dict:
    """Review Trial Agent output: is the IR valid?"""
    ir = state.get("ir")

    if ir is None:
        decision = SupervisorDecision(
            agent_name="trial", status="FAILED", action="ESCALATE",
            reason="IR generation failed", metrics={},
        )
        return {"decisions": [decision], "escalate_reason": "Trial Agent produced no IR"}

    # Check IR completeness
    issues = []
    if not ir.target.primary_criteria.entity_text:
        issues.append("target primary_criteria.entity_text is empty")
    if not ir.comparator.primary_criteria.entity_text:
        issues.append("comparator primary_criteria.entity_text is empty")

    if issues:
        decision = SupervisorDecision(
            agent_name="trial", status="PARTIAL", action="PROCEED",
            reason=f"IR incomplete: {'; '.join(issues)}",
            metrics={"issues": len(issues)},
        )
    else:
        n_rules = len(ir.target.inclusion_rules) + len(ir.target.exclusion_rules)
        decision = SupervisorDecision(
            agent_name="trial", status="SUCCESS", action="PROCEED",
            reason=f"IR valid: {n_rules} rules",
            metrics={"n_rules": n_rules},
        )

    print(f"  [Review] Trial: {decision.action} — {decision.reason}")
    return {"decisions": [decision]}


def _check_domain_mismatches(mapped_sets: list[dict], registered_sets: list) -> list[dict]:
    """Check if entity domain_hint matches the domain_id of mapped concepts.

    Uses registered_sets (which contain concept metadata from _step2_5_consolidate)
    to avoid extra DB calls.

    Returns a list of mismatch records:
        [{"entity": str, "entity_domain": str, "concept_domains": [...], ...}]
    """
    concept_domain_map: dict[int, str] = {}
    for rs in (registered_sets or []):
        for rc in getattr(rs, "concepts", []):
            if isinstance(rc, dict):
                cid = rc.get("concept_id")
                dom = rc.get("domain_id")
            else:
                cid = getattr(rc, "concept_id", None)
                dom = getattr(rc, "domain_id", None)
            if cid is not None and dom is not None:
                concept_domain_map[cid] = dom

    mismatches = []
    DOMAIN_ALIASES = {
        "Drug": {"Drug"},
        "Condition": {"Condition"},
        "Measurement": {"Measurement"},
        "Procedure": {"Procedure"},
        "Observation": {"Observation"},
        "Device": {"Device"},
    }

    for ms in mapped_sets:
        entity_domain = ms.get("domain", "")
        entity_name = ms.get("name", "")
        concept_ids = ms.get("concept_ids", [])

        if not entity_domain or not concept_ids:
            continue

        expected_domains = DOMAIN_ALIASES.get(entity_domain, {entity_domain})

        mismatch_count = 0
        mismatch_domains = []
        domain_counts: dict[str, int] = {}
        expected_domain_count = 0
        known_concept_count = 0
        unknown_domain_count = 0
        for cid in concept_ids:
            concept_dom = concept_domain_map.get(cid)
            if concept_dom is None:
                unknown_domain_count += 1
                continue

            known_concept_count += 1
            domain_counts[concept_dom] = domain_counts.get(concept_dom, 0) + 1
            if concept_dom in expected_domains:
                expected_domain_count += 1
            else:
                mismatch_count += 1
                mismatch_domains.append(concept_dom)

        if mismatch_count > 0:
            dominant_domain = None
            dominant_ratio = 0.0
            if domain_counts and known_concept_count > 0:
                dominant_domain, dominant_count = max(
                    domain_counts.items(),
                    key=lambda item: item[1],
                )
                dominant_ratio = dominant_count / known_concept_count

            mismatches.append({
                "entity": entity_name,
                "entity_key": ms.get("entity_key"),
                "entity_domain": entity_domain,
                "concept_domains": list(mismatch_domains),
                "mismatch_count": mismatch_count,
                "total_concepts": len(concept_ids),
                "domain_counts": domain_counts,
                "expected_domain_count": expected_domain_count,
                "known_concept_count": known_concept_count,
                "unknown_domain_count": unknown_domain_count,
                "dominant_domain": dominant_domain,
                "dominant_ratio": dominant_ratio,
            })

    return mismatches


def audit_mapping_results(
    mapped_sets: list[dict],
    registered_sets: list,
    gap: "GapReport",
) -> dict:
    """Centralized mapping health check — collects all risk signals in one place.

    Returns a structured audit report with:
        - domain_mismatches: entity domain ≠ mapped concept domain
        - too_few_concepts: entities with only 1 concept (may be too narrow)
        - overbroad_entities: entities with overbroad concepts (footprint guard fired)
        - unmapped_entities: from gap report
        - domain_overrides: pre-check overrode Agent 1 domain
        - route_stats: fast/slow/atc path distribution
        - high_risk_entities: entities that bypassed LLM verification
        - severity: "CLEAN", "WARNING", "CRITICAL"
    """
    report: dict = {
        "domain_mismatches": [],
        "too_few_concepts": [],
        "overbroad_entities": [],
        "unmapped_entities": [],
        "domain_overrides": [],
        "high_risk_entities": [],
        "route_stats": {"fast": 0, "slow": 0, "atc": 0, "unknown": 0},
        "critic_skip_count": 0,
        "total_entities": len(mapped_sets) + (gap.unmapped_count if gap else 0),
        "mapped_count": len(mapped_sets),
        "warnings": [],
        "severity": "CLEAN",
    }

    # 1. Domain mismatches (reuse existing function)
    report["domain_mismatches"] = _check_domain_mismatches(mapped_sets, registered_sets)

    # 2-5. Per-entity checks
    for ms in mapped_sets:
        name = ms.get("name", "")
        concept_ids = ms.get("concept_ids", [])
        overbroad = ms.get("overbroad_concept_ids", [])
        route = ms.get("route_path")
        domain_overridden = ms.get("domain_overridden")

        # Too few concepts (single concept may be too narrow)
        if len(concept_ids) == 1:
            report["too_few_concepts"].append({
                "entity": name,
                "entity_key": ms.get("entity_key"),
                "concept_count": 1,
                "domain": ms.get("domain", ""),
            })

        # Overbroad (ConceptSetRefiner flagged)
        if overbroad:
            report["overbroad_entities"].append({
                "entity": name,
                "entity_key": ms.get("entity_key"),
                "overbroad_count": len(overbroad),
                "total_concepts": len(concept_ids),
            })

        # Domain override (pre-check fired)
        if domain_overridden:
            report["domain_overrides"].append({
                "entity": name,
                "entity_key": ms.get("entity_key"),
                "original_domain": domain_overridden,
                "overridden_to": ms.get("domain", ""),
            })

        # Route stats
        if route in ("fast", "slow", "atc"):
            report["route_stats"][route] += 1
        else:
            report["route_stats"]["unknown"] += 1

        # Critic skip count
        if ms.get("critic_skipped"):
            report["critic_skip_count"] += 1

    # 6. Unmapped entities from gap report
    if gap:
        for g in gap.unmapped_items:
            report["unmapped_entities"].append({
                "entity": g.original_text if hasattr(g, "original_text") else str(g),
                "reason": g.reason if hasattr(g, "reason") else "",
            })

    # 7. High-risk entity audit (entities that bypassed LLM verification)
    report["high_risk_entities"] = audit_high_risk_entities(mapped_sets)

    # 8. Build warnings list + severity
    if report["domain_mismatches"]:
        names = [dm["entity"] for dm in report["domain_mismatches"]]
        report["warnings"].append(
            f"⚠ {len(report['domain_mismatches'])} domain mismatch(es): {', '.join(names)}"
        )

    if report["too_few_concepts"]:
        names = [e["entity"] for e in report["too_few_concepts"]]
        report["warnings"].append(
            f"⚠ {len(report['too_few_concepts'])} entity(s) with only 1 concept (may be too narrow): "
            f"{', '.join(names[:5])}"
        )

    if report["overbroad_entities"]:
        names = [e["entity"] for e in report["overbroad_entities"]]
        report["warnings"].append(
            f"⚠ {len(report['overbroad_entities'])} overbroad entity(s) (footprint guard): "
            f"{', '.join(names[:5])}"
        )

    if report["domain_overrides"]:
        items = [f"{d['entity']}({d['original_domain']}→{d['overridden_to']})"
                 for d in report["domain_overrides"]]
        report["warnings"].append(
            f"⚠ {len(report['domain_overrides'])} domain override(s): {', '.join(items)}"
        )

    if report["unmapped_entities"]:
        names = [e["entity"] for e in report["unmapped_entities"]]
        report["warnings"].append(
            f"❌ {len(report['unmapped_entities'])} unmapped entity(s): {', '.join(names[:5])}"
        )

    if report["high_risk_entities"]:
        names = [e["entity"] for e in report["high_risk_entities"]][:5]
        report["warnings"].append(
            f"🔍 {len(report['high_risk_entities'])} high-risk entity(s) "
            f"(bypassed LLM verification): {', '.join(names)}"
        )

    # Severity classification
    n_critical = len(report["unmapped_entities"]) + len(report["domain_mismatches"])
    n_warnings = len(report["too_few_concepts"]) + len(report["overbroad_entities"])
    if n_critical > 0:
        report["severity"] = "CRITICAL"
    elif n_warnings > 0:
        report["severity"] = "WARNING"

    return report


def audit_high_risk_entities(mapped_sets: list[dict]) -> list[dict]:
    """Identify entities that bypassed LLM verification.

    High-risk triggers (per lab meeting 2026-03-15 합의):
    - fast_path: ChromaDB direct hit, no LLM reranker/critic
    - atc_expanded: ATC drug class expansion (vocab-based, no LLM check)
    - critic_skipped: anchor ≤10 so critic was skipped
    - domain_overridden: pre-check overrode Agent 1's domain assignment

    These entities passed through Agent 2 without full LLM-based quality
    verification. The audit is report-only — no hard gate or retry is
    triggered. Use this data to focus manual review on blind spots.

    Returns:
        List of dicts, each with:
            entity: str, triggers: list[str], concept_count: int, domain: str
    """
    high_risk = []

    for ms in mapped_sets:
        triggers = []

        route = ms.get("route_path")
        if route == "fast":
            triggers.append("fast_path")
        if route == "atc" or ms.get("atc_expanded"):
            triggers.append("atc_expanded")
        if ms.get("critic_skipped"):
            triggers.append("critic_skipped")
        if ms.get("domain_overridden"):
            triggers.append("domain_overridden")

        if triggers:
            high_risk.append({
                "entity": ms.get("name", ""),
                "triggers": triggers,
                "concept_count": len(ms.get("concept_ids", [])),
                "domain": ms.get("domain", ""),
            })

    return high_risk


def review_mapping(state: ArtemisState) -> dict:
    """Review Mapping Agent output: mapping quality + centralized audit."""
    gap: GapReport = state.get("gap_report") or GapReport()
    mapped_sets = state.get("mapped_sets", [])
    registered_sets = state.get("registered_sets", [])
    retry_counts = state.get("retry_counts", {})
    mapping_retries = retry_counts.get("mapping", 0)

    rate = gap.mapping_rate
    n_mapped = len(mapped_sets)

    # Centralized audit (replaces inline domain mismatch check)
    audit = audit_mapping_results(mapped_sets, registered_sets, gap)

    # Log all warnings
    for w in audit["warnings"]:
        logger.warning(f"[Mapping Audit] {w}")

    # Route stats summary
    rs = audit["route_stats"]
    logger.info(
        f"[Mapping Audit] Route stats: fast={rs['fast']}, slow={rs['slow']}, "
        f"atc={rs['atc']}, critic_skipped={audit['critic_skip_count']}"
    )

    if n_mapped == 0:
        if mapping_retries >= MAX_RETRY:
            action = "ESCALATE"
            reason = f"0 concepts mapped after {MAX_RETRY} retries"
        else:
            action = "RETRY"
            reason = "0 concepts mapped"
    elif rate < 50:
        action = "ESCALATE"
        reason = f"Mapping rate {rate:.0f}% < 50% — human review needed"
    elif rate < 80:
        if mapping_retries >= MAX_RETRY:
            action = "PROCEED"
            reason = f"Mapping rate {rate:.0f}% < 80% but max retries exhausted"
        else:
            action = "RETRY"
            reason = f"Mapping rate {rate:.0f}% < 80%"
    else:
        action = "PROCEED"
        reason = f"Mapping rate {rate:.0f}%, {n_mapped} concept sets"

    # Append audit warnings to reason
    if audit["warnings"]:
        reason += f" | audit[{audit['severity']}]: {'; '.join(audit['warnings'][:3])}"

    status = "SUCCESS" if action == "PROCEED" else "PARTIAL" if action == "RETRY" else "FAILED"
    updates: dict = {}

    # Check for selective retry candidates (Phase 3)
    if action == "PROCEED" and (audit.get("domain_mismatches") or _has_empty_entities(state)):
        # Build retry plan to check if selective retry is warranted
        from src.pipeline.mapping_retry import build_retry_plan
        retry_plan = build_retry_plan(
            audit=audit,
            raw_mapped_sets=state.get("raw_mapped_sets", []),
            entities_to_map=state.get("entities_to_map", []),
            retry_counts=retry_counts,
        )
        if retry_plan.has_candidates:
            action = "SELECTIVE_RETRY"
            status = "PARTIAL"
            strategy_summary = ",".join(sorted({c.strategy for c in retry_plan.candidates}))
            reason += (
                f" | {len(retry_plan.candidates)} entities need selective re-map"
                f" ({strategy_summary})"
            )
            updates["retry_queue"] = [_retry_candidate_to_dict(c) for c in retry_plan.candidates]

    decision = SupervisorDecision(
        agent_name="mapping", status=status, action=action,
        reason=reason,
        metrics={
            "mapping_rate": rate,
            "n_mapped": n_mapped,
            "retries": mapping_retries,
            "audit": audit,
        },
    )

    print(f"  [Review] Mapping: {decision.action} — {decision.reason}")

    updates["decisions"] = [decision]
    if action == "RETRY":
        retry_counts = dict(retry_counts)
        retry_counts["mapping"] = mapping_retries + 1
        updates["retry_counts"] = retry_counts
        updates["loop_results"] = [LoopResult(
            loop_id="LOOP_2_MAPPING", attempt=mapping_retries + 1,
            max_attempts=MAX_RETRY, status="FAILED",
            details=reason,
        )]
    elif action == "SELECTIVE_RETRY":
        updates["loop_results"] = [LoopResult(
            loop_id="LOOP_SR_SELECTIVE", attempt=mapping_retries + 1,
            max_attempts=MAX_RETRY, status="PARTIAL",
            remaining_failures=[c["entity_text"] for c in updates.get("retry_queue", [])],
            details=reason,
        )]
    if action == "ESCALATE":
        updates["escalate_reason"] = reason

    return updates


def _has_empty_entities(state: ArtemisState) -> bool:
    """Check if any entity in entities_to_map is missing from mapped_sets."""
    mapped_names = {ms.get("name", "").lower() for ms in state.get("raw_mapped_sets", [])}
    for ent in state.get("entities_to_map", []):
        if ent["text"].lower() not in mapped_names:
            return True
    return False


def _retry_candidate_to_dict(c) -> dict:
    """Convert RetryCandidate dataclass to plain dict for state serialization."""
    return {
        "entity_key": c.entity_key,
        "entity_text": c.entity_text,
        "domain_hint": c.domain_hint,
        "rule_context": c.rule_context,
        "reason": c.reason,
        "strategy": c.strategy,
        "corrected_domain": c.corrected_domain,
        "force_slow_path": c.force_slow_path,
    }


def review_assembly(state: ArtemisState) -> dict:
    """Review Assembly + Validation output."""
    validation = state.get("validation")
    heal_log = state.get("heal_log") or []
    retry_counts = state.get("retry_counts", {})
    asm_retries = retry_counts.get("assembly", 0)

    skipped = [h for h in heal_log if getattr(h, "action", "") == "SKIP"]
    total = len(heal_log) if heal_log else 1
    completeness = (total - len(skipped)) / total if total else 1.0

    if validation is None:
        action = "ESCALATE"
        reason = "Assembly or validation failed completely"
    elif not validation.valid and asm_retries < MAX_RETRY:
        action = "RETRY"
        reason = f"Validation failed: {len(validation.errors)} errors"
    elif not validation.valid and asm_retries >= MAX_RETRY:
        action = "ESCALATE"
        reason = f"Validation still invalid after {MAX_RETRY} retries"
    elif completeness < 0.5:
        action = "ESCALATE"
        reason = f"Completeness {completeness:.0%} < 50%"
    elif len(skipped) > 0 and asm_retries < MAX_RETRY:
        action = "RETRY"
        reason = f"{len(skipped)} rules skipped, retrying mapping"
    else:
        action = "PROCEED"
        reason = f"Valid={validation.valid}, completeness={completeness:.0%}"

    status = "SUCCESS" if action == "PROCEED" else "PARTIAL" if action == "RETRY" else "FAILED"
    decision = SupervisorDecision(
        agent_name="assembly", status=status, action=action,
        reason=reason,
        metrics={"completeness": completeness, "skipped_rules": len(skipped), "retries": asm_retries},
    )

    print(f"  [Review] Assembly: {decision.action} — {decision.reason}")

    updates: dict = {"decisions": [decision]}
    if action == "RETRY":
        retry_counts = dict(retry_counts)
        retry_counts["assembly"] = asm_retries + 1
        updates["retry_counts"] = retry_counts
        updates["loop_results"] = [LoopResult(
            loop_id="LOOP_1_ASSEMBLY", attempt=asm_retries + 1,
            max_attempts=MAX_RETRY, status="FAILED",
            remaining_failures=[getattr(h, 'entity_text', '') for h in skipped],
            details=reason,
        )]
    if action == "ESCALATE":
        updates["escalate_reason"] = reason

    return updates


def review_extraction(state: ArtemisState) -> dict:
    """Review Extraction output: did we get patients?"""
    patient_data = state.get("patient_data")
    diagnostics = state.get("execution_diagnostics", [])
    retry_counts = state.get("retry_counts", {})
    ext_retries = retry_counts.get("extraction", 0)

    has_data = patient_data is not None and len(patient_data) > 0

    if not has_data:
        if ext_retries >= MAX_RETRY:
            action = "ESCALATE"
            reason = "0 patients after max retries"
        else:
            action = "RETRY"
            reason = "0 patients extracted"
    else:
        n = len(patient_data) if patient_data is not None else 0
        action = "PROCEED"
        reason = f"{n} patients"

    status = "SUCCESS" if action == "PROCEED" else "PARTIAL" if action == "RETRY" else "FAILED"
    decision = SupervisorDecision(
        agent_name="extraction", status=status, action=action,
        reason=reason,
        metrics={"patient_count": len(patient_data) if has_data else 0, "retries": ext_retries},
    )

    print(f"  [Review] Extraction: {decision.action} — {decision.reason}")

    updates: dict = {"decisions": [decision]}
    if action == "RETRY":
        retry_counts = dict(retry_counts)
        retry_counts["extraction"] = ext_retries + 1
        updates["retry_counts"] = retry_counts
        updates["loop_results"] = [LoopResult(
            loop_id="LOOP_3_EXTRACTION", attempt=ext_retries + 1,
            max_attempts=MAX_RETRY, status="FAILED",
            details=reason,
        )]
    if action == "ESCALATE":
        updates["escalate_reason"] = reason

    return updates


def review_analysis(state: ArtemisState) -> dict:
    """Review Analysis output: are results statistically meaningful?"""
    results = state.get("analysis_results", {})
    hr = results.get("hazard_ratio", {})
    n_target = results.get("n_target", 0)
    n_comp = results.get("n_comparator", 0)

    issues = []
    if n_target < 30:
        issues.append(f"target n={n_target} < 30")
    if n_comp < 30:
        issues.append(f"comparator n={n_comp} < 30")
    if not hr:
        issues.append("no hazard ratio computed")

    if issues:
        decision = SupervisorDecision(
            agent_name="analysis", status="PARTIAL", action="PROCEED",
            reason=f"Warnings: {'; '.join(issues)}",
            metrics={"n_target": n_target, "n_comparator": n_comp},
        )
    else:
        decision = SupervisorDecision(
            agent_name="analysis", status="SUCCESS", action="PROCEED",
            reason=f"HR={hr.get('hr', 'N/A')}, n={n_target}+{n_comp}",
            metrics={"hr": hr.get("hr"), "p": hr.get("p_value"), "n": n_target + n_comp},
        )

    print(f"  [Review] Analysis: {decision.action} — {decision.reason}")
    return {"decisions": [decision]}


def review_reporting(state: ArtemisState) -> dict:
    """Review Reporting output: was usable report output produced?"""
    report_path = (state.get("report_path") or "").strip()
    plot_paths = state.get("plot_paths") or {}
    report_summary = state.get("report_summary") or {}
    summary_text = str(report_summary.get("text") or "").strip()
    summary_status = str(report_summary.get("status") or "").strip().lower()
    summary_reason = str(report_summary.get("reason") or "").strip()

    issues = []
    if not report_path and not summary_text:
        issues.append("no report output generated")
    if summary_status in {"warning", "fallback"}:
        issues.append(f"summary status={summary_status}")
    if summary_reason and summary_status in {"warning", "fallback"}:
        issues.append(summary_reason)

    metrics = {
        "has_report_path": bool(report_path),
        "plot_count": len(plot_paths),
        "has_summary_text": bool(summary_text),
    }

    if issues:
        decision = SupervisorDecision(
            agent_name="reporting",
            status="PARTIAL",
            action="PROCEED",
            reason=f"Warnings: {'; '.join(issues)}",
            metrics=metrics,
        )
    else:
        output_label = report_path or "summary ready"
        decision = SupervisorDecision(
            agent_name="reporting",
            status="SUCCESS",
            action="PROCEED",
            reason=f"report ready: {output_label}",
            metrics=metrics,
        )

    print(f"  [Review] Reporting: {decision.action} — {decision.reason}")
    return {"decisions": [decision]}


# ══════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════
# Phase 3: Selective Retry Remediation Nodes
# ══════════════════════════════════════════════════════════════

def plan_mapping_remediation(state: ArtemisState) -> dict:
    """Pass the retry_queue through — planning already happened in review_mapping.

    This node exists as a distinct pipeline stage for observability and
    potential future expansion (e.g., Agent 1 IR repair in v2).
    """
    queue = state.get("retry_queue", [])
    if not queue:
        logger.info("[Remediation] No retry candidates — passing through")
    else:
        logger.info(f"[Remediation] Planning re-map for {len(queue)} entities")
        for item in queue:
            print(f"  📋 {item['entity_text']} ({item['reason']})")
    return {"current_phase": "plan_remediation"}


def execute_mapping_remediation(state: ArtemisState) -> dict:
    """Execute selective re-mapping for retry_queue entities.

    For each retry candidate:
    1. Re-map via map_single_entity(force_slow_path=True)
    2. Rollback gate: only commit if new mapping has more concepts
    3. Update raw_mapped_sets and mapped_sets with improved results
    """
    queue = state.get("retry_queue", [])
    if not queue:
        return {"retry_queue": [], "current_phase": "execute_remediation"}

    raw_mapped_sets = list(state.get("raw_mapped_sets", []))
    retry_counts = dict(state.get("retry_counts", {}))

    # Build lookup: entity_key → index in raw_mapped_sets
    key_to_idx: dict = {}
    for idx, ms in enumerate(raw_mapped_sets):
        key = ms.get("entity_key")
        if key:
            key_to_idx[key] = idx

    prepared_queue = []
    for item in queue:
        entity_key = item["entity_key"]
        retry_key = f"entity:{entity_key}"
        retry_counts[retry_key] = retry_counts.get(retry_key, 0) + 1
        if item.get("reason") == "domain_mismatch":
            mismatch_retry_key = f"domain_mismatch:{entity_key}"
            retry_counts[mismatch_retry_key] = retry_counts.get(mismatch_retry_key, 0) + 1

        prepared_item = dict(item)
        prepared_item["_resolved_domain"] = item.get("corrected_domain") or item.get("domain_hint")
        prepared_queue.append(prepared_item)

    outcomes = _run_remediation_work_items(prepared_queue)

    improved = 0
    healed_entities = []
    for outcome in outcomes:
        item = outcome["item"]
        emr = outcome["emr"]
        entity_key = item["entity_key"]
        if not emr.success:
            print(f"  ✗ Re-map failed for '{item['entity_text']}': {emr.error}")
            continue

        # Rollback gate: compare with original
        orig_idx = key_to_idx.get(entity_key)
        if orig_idx is not None:
            orig = raw_mapped_sets[orig_idx]
            orig_count = len(orig.get("concept_ids", []))
            new_count = len(emr.concept_ids)
            if new_count <= orig_count and item["reason"] != "domain_mismatch":
                print(f"  ↩ Rollback '{item['entity_text']}': new({new_count}) ≤ orig({orig_count})")
                continue

            # Commit: update in place
            raw_mapped_sets[orig_idx]["concept_ids"] = emr.concept_ids
            raw_mapped_sets[orig_idx]["overbroad_concept_ids"] = emr.overbroad_concept_ids
            raw_mapped_sets[orig_idx]["route_path"] = emr.route_path
            raw_mapped_sets[orig_idx]["critic_skipped"] = emr.critic_skipped
            raw_mapped_sets[orig_idx]["domain_overridden"] = emr.domain_overridden
            print(f"  ✓ Improved '{item['entity_text']}': {orig_count} → {new_count} concepts")
            improved += 1
            healed_entities.append(item["entity_text"])
        else:
            # New entity (was missing) — append to raw_mapped_sets
            new_entry = emr.to_mapped_set(
                entity_id=len(raw_mapped_sets) + 1,
                entity_text=item["entity_text"],
                domain=item.get("domain_hint", ""),
                entity_key=entity_key,
            )
            raw_mapped_sets.append(new_entry)
            print(f"  ✓ Filled '{item['entity_text']}': {len(emr.concept_ids)} concepts")
            improved += 1
            healed_entities.append(item["entity_text"])

    print(f"  [Remediation] {improved}/{len(queue)} entities improved")

    # Re-consolidate and re-register
    from src.pipeline.supervisor import get_supervisor
    from src.registry.models import RegisteredConcept
    from src.registry.store import registry
    sv = get_supervisor()
    mapped_sets = sv._step2_5_consolidate(raw_mapped_sets)
    registered = sv._step3_register(mapped_sets, registry, RegisteredConcept)

    # Build telemetry
    return {
        "raw_mapped_sets": raw_mapped_sets,
        "mapped_sets": mapped_sets,
        "registered_sets": registered,
        "retry_queue": [],
        "retry_counts": retry_counts,
        "current_phase": "execute_remediation",
        "loop_results": [LoopResult(
            loop_id="LOOP_SR_REMEDIATION",
            attempt=1,
            max_attempts=1,
            status="SUCCESS" if improved > 0 else "FAILED",
            healed_entities=healed_entities,
            details=f"{improved}/{len(queue)} entities improved",
        )],
    }


def _run_remediation_work_items(queue: list[dict]) -> list[dict]:
    if len(queue) <= 1 or not _remediation_parallel_enabled():
        return [
            _run_single_remediation_work_item(index, item)
            for index, item in enumerate(queue)
        ]

    try:
        outcomes_by_index: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=_remediation_max_workers(len(queue))) as pool:
            future_to_payload = {
                pool.submit(_run_single_remediation_work_item, index, item): (index, item)
                for index, item in enumerate(queue)
            }
            for future in as_completed(future_to_payload):
                index, item = future_to_payload[future]
                outcome = future.result()
                emr = outcome["emr"]
                if outcome.get("raised_error") or emr.error:
                    retry_outcome = _run_single_remediation_work_item(index, item)
                    retry_outcome["used_sequential_retry"] = True
                    outcome = retry_outcome
                outcomes_by_index[index] = outcome
        return [outcomes_by_index[index] for index in range(len(queue))]
    except Exception as exc:
        print(f"  ⚠ Remediation parallel pool unavailable, falling back to sequential execution: {exc}")
        return [
            _run_single_remediation_work_item(index, item)
            for index, item in enumerate(queue)
        ]


def _run_single_remediation_work_item(index: int, item: dict) -> dict:
    from src.agents.agent2.map_entity import map_single_entity

    try:
        emr = map_single_entity(
            item["entity_text"],
            domain_hint=item.get("_resolved_domain"),
            rule_context=item.get("rule_context"),
            force_slow_path=item.get("force_slow_path", True),
        )
        return {
            "index": index,
            "item": item,
            "emr": emr,
            "raised_error": None,
            "used_sequential_retry": False,
        }
    except Exception as exc:
        class FailedRemap:
            success = False
            error = str(exc)
            concept_ids = []
            overbroad_concept_ids = []
            route_path = None
            critic_skipped = False
            domain_overridden = None

        return {
            "index": index,
            "item": item,
            "emr": FailedRemap(),
            "raised_error": str(exc),
            "used_sequential_retry": False,
        }


# ══════════════════════════════════════════════════════════════
# Routing Functions (conditional edges)
# ══════════════════════════════════════════════════════════════

def _last_decision_action(state: ArtemisState) -> str:
    """Get the action from the most recent SupervisorDecision."""
    decisions = state.get("decisions", [])
    if not decisions:
        return "PROCEED"
    return decisions[-1].action


def route_after_trial(state: ArtemisState) -> str:
    action = _last_decision_action(state)
    return "mapping"


def route_after_mapping(state: ArtemisState) -> str:
    action = _last_decision_action(state)
    if action == "RETRY":
        return "mapping"
    if action == "SELECTIVE_RETRY":
        return "plan_mapping_remediation"
    return "assembly"


def route_after_assembly(state: ArtemisState) -> str:
    action = _last_decision_action(state)
    if action == "RETRY":
        return "mapping"  # re-map failed entities
    return "extraction"


def route_after_extraction(state: ArtemisState) -> str:
    action = _last_decision_action(state)
    if action == "RETRY":
        return "extraction"
    return "analysis"


def route_after_analysis(state: ArtemisState) -> str:
    # Analysis always proceeds to reporting (PROCEED or WARN)
    return "reporting"


# ══════════════════════════════════════════════════════════════
# Graph Builder
# ══════════════════════════════════════════════════════════════

def build_graph() -> StateGraph:
    """Build the ARTEMIS Supervisor Agent graph.

    Structure:
        trial → review_trial → [mapping | END]
        mapping → review_mapping → [assembly | mapping(retry) | plan_remediation | END]
        plan_mapping_remediation → execute_mapping_remediation → review_mapping
        assembly → review_assembly → [extraction | mapping(retry) | END]
        extraction → review_extraction → [analysis | extraction(retry) | END]
        analysis → review_analysis → reporting
        reporting → review_reporting → END
    """
    graph = StateGraph(ArtemisState)

    # Agent nodes
    graph.add_node("trial", trial_node)
    graph.add_node("mapping", mapping_node)
    graph.add_node("assembly", assembly_node)
    graph.add_node("extraction", extraction_node)
    graph.add_node("analysis", analysis_node)
    graph.add_node("reporting", reporting_node)

    # Review nodes
    graph.add_node("review_trial", review_trial)
    graph.add_node("review_mapping", review_mapping)
    graph.add_node("review_assembly", review_assembly)
    graph.add_node("review_extraction", review_extraction)
    graph.add_node("review_analysis", review_analysis)
    graph.add_node("review_reporting", review_reporting)

    # Phase 3: Selective retry remediation nodes
    graph.add_node("plan_mapping_remediation", plan_mapping_remediation)
    graph.add_node("execute_mapping_remediation", execute_mapping_remediation)

    # Entry / finish points for pinned langgraph runtime
    graph.set_entry_point("trial")
    graph.add_edge("trial", "review_trial")
    graph.add_conditional_edges("review_trial", route_after_trial)

    graph.add_edge("mapping", "review_mapping")
    graph.add_conditional_edges("review_mapping", route_after_mapping)

    # Selective retry loop: plan → execute → back to review
    graph.add_edge("plan_mapping_remediation", "execute_mapping_remediation")
    graph.add_edge("execute_mapping_remediation", "review_mapping")

    graph.add_edge("assembly", "review_assembly")
    graph.add_conditional_edges("review_assembly", route_after_assembly)

    graph.add_edge("extraction", "review_extraction")
    graph.add_conditional_edges("review_extraction", route_after_extraction)

    graph.add_edge("analysis", "review_analysis")
    graph.add_conditional_edges("review_analysis", route_after_analysis)

    graph.add_edge("reporting", "review_reporting")

    graph.set_finish_point("review_reporting")

    return graph


def compile_graph():
    """Build and compile the graph for execution."""
    return build_graph().compile()


# ══════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════

def run_supervisor(query: str) -> ArtemisState:
    """Run the full ARTEMIS pipeline via Supervisor Agent.

    Args:
        query: Natural language clinical question or NCT ID

    Returns:
        Final ArtemisState with all pipeline outputs + supervisor decisions
    """
    app = compile_graph()

    initial_state: ArtemisState = {
        "query": query,
        "decisions": [],
        "error_log": [],
        "loop_results": [],
        "retry_counts": {},
        "current_phase": "init",
    }

    print("\n" + "=" * 60)
    print("ARTEMIS 3.1 — Supervisor Agent")
    print("=" * 60)
    print(f"Query: {query[:100]}")
    print("=" * 60)

    result = app.invoke(initial_state)

    # Print summary
    decisions = result.get("decisions", [])
    print("\n" + "=" * 60)
    print("Supervisor Summary")
    print("-" * 60)
    for d in decisions:
        icon = "✓" if d.action == "PROCEED" else "⚠" if d.action == "RETRY" else "✗"
        print(f"  {icon} {d.agent_name}: {d.action} — {d.reason}")

    escalate = result.get("escalate_reason")
    if escalate:
        print(f"\n  🛑 ESCALATED: {escalate}")
    else:
        print(f"\n  ✅ Pipeline complete!")
    print("=" * 60)

    return result
