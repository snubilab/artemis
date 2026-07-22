"""
ARTEMIS Pipeline Orchestrator.
End-to-end: NL Query → Cohort Definition → Analysis → Report.

V2 (ADR-023 Phase 3): Delegates to LangGraph-based Supervisor Agent
for conditional routing and per-agent quality review.

Backward compatible: ArtemisPipeline.run() and run_artemis() still work.
"""
from typing import Dict, Any, Optional
from dataclasses import dataclass
from pathlib import Path

from src.pipeline.supervisor_agent import (
    run_supervisor,
    compile_graph,
    ArtemisState,
    SupervisorDecision,
)
from src.pipeline.cohort_pipeline import PipelineResult as CohortResult


@dataclass
class ArtemisResult:
    """Complete ARTEMIS pipeline result."""
    state: ArtemisState  # Full LangGraph state
    report_path: str
    plot_paths: Dict[str, str]

    @property
    def decisions(self) -> list:
        return self.state.get("decisions", [])

    @property
    def escalated(self) -> bool:
        return self.state.get("escalate_reason") is not None

    @property
    def analysis_results(self) -> Dict[str, Any]:
        return self.state.get("analysis_results", {})


class ArtemisPipeline:
    """
    End-to-end ARTEMIS pipeline orchestrator.

    V2: Uses LangGraph Supervisor Agent for conditional routing
    and per-agent quality review (PROCEED / RETRY / ESCALATE).
    """

    def run(
        self,
        query: str,
        output_dir: str = "./output/artemis_run",
    ) -> ArtemisResult:
        """
        Execute the full ARTEMIS pipeline via Supervisor Agent.

        Args:
            query: Natural language clinical question or NCT ID
            output_dir: Directory for output files

        Returns:
            ArtemisResult with pipeline state + outputs
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        state = run_supervisor(query)

        return ArtemisResult(
            state=state,
            report_path=state.get("report_path", ""),
            plot_paths=state.get("plot_paths", {}),
        )


# Convenience function (backward compat)
def run_artemis(
    query: str,
    output_dir: str = "./output/artemis_run",
    **kwargs
) -> ArtemisResult:
    """Run ARTEMIS pipeline with a single function call."""
    pipeline = ArtemisPipeline()
    return pipeline.run(query, output_dir)

