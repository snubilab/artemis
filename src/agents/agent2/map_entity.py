"""
Shared Agent 2 single-entity mapping function.

Extracted from supervisor.py _step2_map() and benchmark_v5.py invoke_agent2()
to unify the Agent 2 invocation interface.  Both production pipeline and
benchmark share this function so that behaviour stays in sync.

ADR-024: Any change to mapping logic must be reflected in both paths.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class EntityMappingResult:
    """Standardised result of mapping a single entity via Agent 2.

    Unifies the return shape so production (supervisor.py) and benchmark
    (benchmark_v5.py) work with the same data structure.
    """
    concept_ids: List[int] = field(default_factory=list)
    overbroad_concept_ids: List[int] = field(default_factory=list)

    # Path metadata — which route Agent 2 took
    route_path: Optional[str] = None       # "fast" | "slow" | "atc"
    atc_expanded: bool = False
    critic_skipped: bool = False
    domain_overridden: Optional[str] = None

    # Stats
    processing_time_ms: float = 0.0
    fast_path_count: int = 0
    slow_path_count: int = 0
    gap_count: int = 0

    # Error (if any)
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return len(self.concept_ids) > 0 and self.error is None

    def to_meta_dict(self) -> Dict[str, Any]:
        """Legacy dict format compatible with benchmark_v5.py sub_results."""
        d: Dict[str, Any] = {
            "processing_ms": self.processing_time_ms,
            "fast_path": self.fast_path_count,
            "slow_path": self.slow_path_count,
            "gaps": self.gap_count,
            "overbroad_concept_ids": self.overbroad_concept_ids,
            "route_path": self.route_path,
            "atc_expanded": self.atc_expanded,
            "critic_skipped": self.critic_skipped,
            "domain_overridden": self.domain_overridden,
        }
        if self.error:
            d["error"] = self.error
        return d

    def to_mapped_set(
        self,
        *,
        entity_id: int,
        entity_text: str,
        domain: str,
        source: str = "inclusion",
        parent_rule: Optional[str] = None,
        entity_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build mapped_set dict compatible with supervisor.py / audit."""
        entry: Dict[str, Any] = {
            "id": entity_id,
            "name": entity_text,
            "domain": domain,
            "concept_ids": self.concept_ids,
            "overbroad_concept_ids": self.overbroad_concept_ids,
            "source": source,
            "route_path": self.route_path,
            "atc_expanded": self.atc_expanded,
            "critic_skipped": self.critic_skipped,
            "domain_overridden": self.domain_overridden,
        }
        if parent_rule:
            entry["parent_rule"] = parent_rule
        if entity_key:
            entry["entity_key"] = entity_key
        return entry


def map_single_entity(
    entity_text: str,
    *,
    domain_hint: Optional[str] = None,
    rule_context: Optional[str] = None,
    force_slow_path: bool = False,
    agent2=None,
) -> EntityMappingResult:
    """Map a single entity text to OMOP concept IDs via Agent 2.

    This is the canonical, single entry point used by both production
    pipeline (supervisor.py) and benchmark scripts (benchmark_v5.py).

    Args:
        entity_text: Clinical term to map (e.g., "Type 2 diabetes mellitus")
        domain_hint: OMOP domain hint ("Drug", "Condition", "Procedure", …)
        rule_context: Parent rule name for reranker/critic disambiguation.
        force_slow_path: If True, forces Agent 2 to bypass fast path and use
                        the full LLM reranker pipeline. Used by selective retry.
        agent2: Optional pre-created Agent 2 instance. If None, creates one.

    Returns:
        EntityMappingResult with concept_ids, path metadata, and stats.
    """
    if agent2 is None:
        from src.agents.agent2.workflow import get_agent2
        agent2 = get_agent2()

    start = time.time()
    try:
        detail_result = agent2.process_with_details(
            entity_text,
            context=rule_context,
            domain_hint=domain_hint,
            force_slow_path=force_slow_path,
        )
        elapsed = (time.time() - start) * 1000
        gap_total = detail_result.gap_report.total_criteria
        gap_mapped = detail_result.gap_report.mapped_count

        return EntityMappingResult(
            concept_ids=detail_result.concept_ids,
            overbroad_concept_ids=detail_result.overbroad_concept_ids or [],
            route_path=detail_result.route_path,
            atc_expanded=detail_result.atc_expanded,
            critic_skipped=detail_result.critic_skipped,
            domain_overridden=detail_result.domain_overridden,
            processing_time_ms=detail_result.processing_time_ms or elapsed,
            fast_path_count=detail_result.fast_path_count,
            slow_path_count=detail_result.slow_path_count,
            gap_count=gap_total - gap_mapped,
        )
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        logger.warning(f"Agent 2 error for '{entity_text}': {e}")
        return EntityMappingResult(
            processing_time_ms=elapsed,
            error=str(e),
        )
