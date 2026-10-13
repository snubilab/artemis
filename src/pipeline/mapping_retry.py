"""
Shared re-mapping executor: re-map entities that failed assembly and register the result.

Used by the legacy Loop 1 in supervisor.py (_step4_5_assemble_validate).
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


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

    Used by the legacy Loop 1 in supervisor.py (_step4_5_assemble_validate).

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
