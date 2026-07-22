"""
Shared mapping retry planning module.

Used by both production (supervisor_agent.py) and benchmark (benchmark_v5.py)
to ensure consistent retry behavior per ADR-024.

Lab Meeting 2026-03-15: Proposal B — per-entity selective retry based on audit signals.
"""
import os
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Max retries per entity (within the global MAX_RETRY=3 budget)
MAX_ENTITY_RETRIES = 2


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return float(value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


@dataclass
class RetryCandidate:
    """An entity flagged for selective re-mapping."""
    entity_key: str
    entity_text: str
    domain_hint: Optional[str] = None
    rule_context: Optional[str] = None
    reason: str = ""
    strategy: str = "same_domain"
    corrected_domain: Optional[str] = None
    force_slow_path: bool = True


@dataclass
class RetryPlan:
    """Result of build_retry_plan: entities to retry + report-only signals."""
    candidates: List[RetryCandidate] = field(default_factory=list)
    skipped_signals: List[str] = field(default_factory=list)

    @property
    def has_candidates(self) -> bool:
        return len(self.candidates) > 0


def build_retry_plan(
    audit: Dict,
    raw_mapped_sets: List[Dict],
    entities_to_map: List[Dict],
    retry_counts: Dict,
) -> RetryPlan:
    """Build selective retry plan from audit results.

    v1 policy (Lab Meeting 2026-03-15 consensus):
    - empty_mapping → RETRY (slow path forced)
    - domain_mismatch → RETRY (corrected domain_hint)
    - too_few_concepts → SKIP (report-only, unless paired with another signal)
    - high_risk → SKIP (report-only)
    - overbroad → SKIP (report-only)

    Args:
        audit: Dict from audit_mapping_results() with keys like
               'too_few', 'domain_mismatches', 'high_risk_entities', etc.
        raw_mapped_sets: Pre-consolidation entity mappings with entity_key.
        entities_to_map: Original entity collection from _collect_cohort_entities.
        retry_counts: Dict of entity-scoped retry counts, e.g. {"entity:target:inclusion:0:0": 1}

    Returns:
        RetryPlan with candidates and skipped_signals.
    """
    plan = RetryPlan()

    # Build lookup: entity_key → entity info
    entity_by_key: Dict[str, Dict] = {}
    for ent in entities_to_map:
        key = ent.get("entity_key")
        if key:
            entity_by_key[key] = ent

    # Build lookup: entity_key → mapped_set
    mapped_by_key: Dict[str, Dict] = {}
    # Build lookup: entity text (lowered) → mapped_set list
    mapped_by_text: Dict[str, List[Dict]] = {}
    for ms in raw_mapped_sets:
        key = ms.get("entity_key")
        if key:
            mapped_by_key[key] = ms
        text_key = ms.get("name", "").lower()
        mapped_by_text.setdefault(text_key, []).append(ms)

    # --- Signal 1: Empty mappings ---
    # Entities that were in entities_to_map but have no mapping in raw_mapped_sets
    for ent in entities_to_map:
        key = ent.get("entity_key", "")
        retry_key = f"entity:{key}"
        is_missing = (key not in mapped_by_key) if key else (ent["text"].lower() not in mapped_by_text)

        if is_missing:
            if retry_counts.get(retry_key, 0) >= MAX_ENTITY_RETRIES:
                plan.skipped_signals.append(
                    f"empty:{ent['text']} (max retries exhausted)"
                )
                continue
            raw_rule = ent.get("parent_rule")
            rule_ctx = raw_rule.replace("_", " ").title() if raw_rule else None
            plan.candidates.append(RetryCandidate(
                entity_key=key,
                entity_text=ent["text"],
                domain_hint=ent.get("domain"),
                rule_context=rule_ctx,
                reason="empty_mapping",
                force_slow_path=True,
            ))

    # --- Signal 2: Domain mismatches ---
    for mismatch in audit.get("domain_mismatches", []):
        entity_text = mismatch.get("entity", "")
        key = mismatch.get("entity_key", "")
        ms = mapped_by_key.get(key, {}) if key else {}
        if not ms:
            candidates = mapped_by_text.get(entity_text.lower(), [])
            if len(candidates) == 1:
                ms = candidates[0]
                key = ms.get("entity_key", "")
        retry_key = f"domain_mismatch:{key}"

        if not key:
            plan.skipped_signals.append(
                f"domain_mismatch:{entity_text} (ambiguous entity_key)"
            )
            continue

        if retry_counts.get(retry_key, 0) >= MAX_ENTITY_RETRIES:
            plan.skipped_signals.append(
                f"domain_mismatch:{entity_text} (max retries exhausted)"
            )
            continue

        # Already scheduled for empty retry?
        if any(c.entity_key == key for c in plan.candidates):
            continue

        expected_domain = ms.get("domain")
        mismatch_retry_count = retry_counts.get(retry_key, 0)
        corrected_domain = None
        strategy = "same_domain"
        correction_after_retries = _env_int("SUPERVISOR_DOMAIN_CORRECTION_AFTER_RETRIES", 1)

        if mismatch_retry_count >= correction_after_retries and _is_strong_domain_correction_candidate(mismatch):
            corrected_domain = mismatch.get("dominant_domain")
            strategy = "corrected_domain"

        raw_rule = ms.get("parent_rule") or entity_by_key.get(key, {}).get("parent_rule")
        rule_ctx = raw_rule.replace("_", " ").title() if raw_rule else None

        plan.candidates.append(RetryCandidate(
            entity_key=key,
            entity_text=entity_text,
            domain_hint=expected_domain,
            rule_context=rule_ctx,
            reason="domain_mismatch",
            strategy=strategy,
            corrected_domain=corrected_domain,
            force_slow_path=True,
        ))

    # --- Signal 3-5: Report-only ---
    too_few_entities = audit.get("too_few_concepts")
    if too_few_entities is None:
        too_few_entities = audit.get("too_few", [])

    for entity_info in too_few_entities:
        plan.skipped_signals.append(f"too_few:{entity_info.get('entity', '?')}")

    for entity_info in audit.get("high_risk_entities", []):
        plan.skipped_signals.append(
            f"high_risk:{entity_info.get('entity', '?')} ({','.join(entity_info.get('triggers', []))})"
        )

    for entity_info in audit.get("overbroad_entities", []):
        plan.skipped_signals.append(f"overbroad:{entity_info.get('entity', '?')}")

    if plan.candidates:
        logger.info(
            f"[RetryPlan] {len(plan.candidates)} entities scheduled for selective retry: "
            f"{[c.entity_text for c in plan.candidates]}"
        )
    if plan.skipped_signals:
        logger.info(
            f"[RetryPlan] {len(plan.skipped_signals)} signals report-only: "
            f"{plan.skipped_signals}"
        )

    return plan


def _is_strong_domain_correction_candidate(mismatch: Dict) -> bool:
    """Return True only when mismatch evidence is strong enough to change domain."""
    dominant_domain = mismatch.get("dominant_domain")
    if not dominant_domain:
        return False

    min_count = _env_int("SUPERVISOR_DOMAIN_CORRECTION_MIN_COUNT", 3)
    min_ratio = _env_float("SUPERVISOR_DOMAIN_CORRECTION_MIN_RATIO", 0.8)
    require_zero_expected = _env_bool("SUPERVISOR_DOMAIN_CORRECTION_REQUIRE_ZERO_EXPECTED", True)
    require_known_only = _env_bool("SUPERVISOR_DOMAIN_CORRECTION_REQUIRE_KNOWN_ONLY", True)

    dominant_ratio = mismatch.get("dominant_ratio", 0.0)
    domain_counts = mismatch.get("domain_counts", {}) or {}
    dominant_count = domain_counts.get(dominant_domain, 0)
    expected_domain_count = mismatch.get("expected_domain_count", 0)
    unknown_domain_count = mismatch.get("unknown_domain_count", 0)

    if require_known_only and unknown_domain_count != 0:
        return False
    if require_zero_expected and expected_domain_count != 0:
        return False
    if dominant_count < min_count:
        return False
    if dominant_ratio < min_ratio:
        return False

    return True


# ══════════════════════════════════════════════════════════════
# Shared Re-mapping Executor
# ══════════════════════════════════════════════════════════════

@dataclass
class RemapResult:
    """Result of a single entity re-mapping attempt."""
    entity_text: str
    success: bool
    new_concept_ids: List[int] = field(default_factory=list)
    registered: bool = False
    error: Optional[str] = None


def remap_and_register_entities(
    failed_entities: List[Dict],
    registry,
    RegisteredConcept,
    registered_sets: list,
    *,
    force_slow_path: bool = False,
    fetch_metadata_fn=None,
) -> List[RemapResult]:
    """Re-map failed entities and register new concept sets.

    Shared executor used by:
    - Legacy Loop 1 in supervisor.py (_step4_5_assemble_validate)
    - Phase 3 remediation in supervisor_agent.py (execute_mapping_remediation)

    Args:
        failed_entities: List of dicts with keys: text, domain, parent_rule, [entity_key]
        registry: Registry instance for concept set registration.
        RegisteredConcept: RegisteredConcept class for building concepts.
        registered_sets: Mutable list — new registered sets are appended in-place.
        force_slow_path: Force Agent 2 slow path for all entities.
        fetch_metadata_fn: Callable(concept_ids) -> dict. If None, uses
                          PipelineSupervisor._fetch_concept_metadata.

    Returns:
        List of RemapResult with per-entity status.
    """
    from src.agents.agent2.map_entity import map_single_entity

    if fetch_metadata_fn is None:
        from src.pipeline.supervisor import PipelineSupervisor
        fetch_metadata_fn = PipelineSupervisor._fetch_concept_metadata

    results: List[RemapResult] = []

    for entity in failed_entities:
        text = entity["text"]
        raw_rule = entity.get("parent_rule")
        rule_context = raw_rule.replace("_", " ").title() if raw_rule else None
        domain = entity.get("corrected_domain") or entity.get("domain")

        try:
            emr = map_single_entity(
                text,
                domain_hint=domain,
                rule_context=rule_context,
                force_slow_path=force_slow_path,
            )
            new_ids = emr.concept_ids if emr.success else []

            if not new_ids:
                print(f"     ✗ Re-map failed again for '{text}'")
                results.append(RemapResult(entity_text=text, success=False))
                continue

            print(f"     ✓ Re-mapped '{text}' → {new_ids}")

            # Fetch metadata and register
            remap_meta = fetch_metadata_fn(new_ids)
            remap_concepts = []
            for cid in new_ids:
                if cid in remap_meta:
                    m = remap_meta[cid]
                    remap_concepts.append(RegisteredConcept(
                        concept_id=cid,
                        concept_name=m["concept_name"],
                        domain_id=m["domain_id"],
                        vocabulary_id=m["vocabulary_id"],
                        concept_class_id=m.get("concept_class_id", ""),
                        standard_concept=m.get("standard_concept", "S"),
                        include_descendants=True,
                    ))

            was_registered = False
            if remap_concepts:
                result = registry.register(
                    name=text, concepts=remap_concepts, source_entity_text=text,
                )
                if result.concept_set and result.concept_set not in registered_sets:
                    registered_sets.append(result.concept_set)
                    was_registered = True

            results.append(RemapResult(
                entity_text=text, success=True,
                new_concept_ids=new_ids, registered=was_registered,
            ))

        except Exception as e:
            print(f"     ✗ Re-map error for '{text}': {e}")
            results.append(RemapResult(entity_text=text, success=False, error=str(e)))

    return results
