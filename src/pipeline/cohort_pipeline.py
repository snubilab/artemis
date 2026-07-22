"""
ARTEMIS Cohort Pipeline — Thin wrapper for backward compatibility.

ADR-023 Phase 2: Orchestration logic moved to supervisor.py (PipelineSupervisor).
This module re-exports PipelineResult and provides CohortPipeline.run() that
delegates to PipelineSupervisor.run().

All new orchestration logic should go in supervisor.py.
"""
from src.pipeline.supervisor import (
    get_supervisor,
    PipelineResult,
)


class CohortPipeline:
    """End-to-end pipeline: NL Query → Validated Circe JSON.

    Thin wrapper — delegates to PipelineSupervisor.run().
    See: docs/adr/ADR-023_Supervisor_Orchestrator_Promotion.md
    """

    def run(self, query: str) -> PipelineResult:
        """Execute the full cohort definition pipeline.

        Args:
            query: Natural language clinical question

        Returns:
            PipelineResult with IR, ConceptSets, JSON, and validation
        """
        return get_supervisor().run(query)


# Singleton instance (backward compat: scripts use `from src.pipeline import pipeline`)
pipeline = CohortPipeline()
