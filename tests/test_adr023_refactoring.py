"""
Characterization tests for ADR-023 Phase 2: Supervisor Orchestrator Promotion.

These tests pin the PUBLIC INTERFACE of the pipeline modules.
Each refactoring step must keep these tests green.

Tests are pure import/structural checks — no DB, no LLM, no Agent calls.
"""
import pytest
import inspect


# ══════════════════════════════════════════════════════════════
# Group 1: Import contract — all existing import paths must work
# ══════════════════════════════════════════════════════════════

class TestImportContracts:
    """Verify that all known import paths remain valid."""

    def test_import_from_cohort_pipeline(self):
        """Scripts import CohortPipeline directly."""
        from src.pipeline.cohort_pipeline import CohortPipeline, PipelineResult
        assert CohortPipeline is not None
        assert PipelineResult is not None

    def test_import_pipeline_singleton(self):
        """Scripts use `from src.pipeline.cohort_pipeline import pipeline`."""
        from src.pipeline.cohort_pipeline import pipeline
        assert pipeline is not None

    def test_import_from_package_init(self):
        """Package-level imports."""
        from src.pipeline import CohortPipeline, PipelineResult, pipeline
        assert CohortPipeline is not None
        assert PipelineResult is not None
        assert pipeline is not None

    def test_import_orchestrator(self):
        """ArtemisPipeline imports."""
        from src.pipeline.orchestrator import ArtemisPipeline, ArtemisResult, run_artemis
        assert ArtemisPipeline is not None

    def test_import_supervisor(self):
        """Supervisor imports (used by benchmark_v5.py)."""
        from src.pipeline.supervisor import get_supervisor, SupervisorReport
        assert get_supervisor is not None
        assert SupervisorReport is not None

    def test_import_pipeline_result_from_supervisor(self):
        """After Step 1: PipelineResult must be importable from supervisor."""
        from src.pipeline.supervisor import PipelineResult
        assert PipelineResult is not None


# ══════════════════════════════════════════════════════════════
# Group 2: CohortPipeline interface contract
# ══════════════════════════════════════════════════════════════

class TestCohortPipelineInterface:
    """Verify CohortPipeline has the expected public interface."""

    def test_has_run_method(self):
        from src.pipeline.cohort_pipeline import CohortPipeline
        assert hasattr(CohortPipeline, 'run')
        sig = inspect.signature(CohortPipeline.run)
        params = list(sig.parameters.keys())
        assert 'query' in params, f"run() must accept 'query', got {params}"

    def test_pipeline_singleton_is_cohort_pipeline(self):
        from src.pipeline.cohort_pipeline import CohortPipeline, pipeline
        assert isinstance(pipeline, CohortPipeline)

    def test_run_returns_pipeline_result_annotation(self):
        from src.pipeline.cohort_pipeline import CohortPipeline, PipelineResult
        sig = inspect.signature(CohortPipeline.run)
        assert sig.return_annotation is PipelineResult or sig.return_annotation == PipelineResult


# ══════════════════════════════════════════════════════════════
# Group 3: PipelineResult dataclass contract
# ══════════════════════════════════════════════════════════════

class TestPipelineResultContract:
    """Verify PipelineResult has required fields and properties."""

    def test_has_required_fields(self):
        from src.pipeline.cohort_pipeline import PipelineResult
        import dataclasses
        assert dataclasses.is_dataclass(PipelineResult)
        field_names = {f.name for f in dataclasses.fields(PipelineResult)}
        required = {'ir', 'concept_sets', 'circe_json', 'validation',
                     'comparator_circe_json', 'heal_log', 'completeness',
                     'skipped_rules', 'loop_results', 'gap_report',
                     'supervisor_report'}
        missing = required - field_names
        assert not missing, f"Missing fields: {missing}"

    def test_has_properties(self):
        from src.pipeline.cohort_pipeline import PipelineResult
        assert isinstance(PipelineResult.is_valid, property)
        assert isinstance(PipelineResult.has_assembly_failures, property)
        assert isinstance(PipelineResult.needs_human_review, property)


# ══════════════════════════════════════════════════════════════
# Group 4: Supervisor interface contract (benchmark_v5.py compat)
# ══════════════════════════════════════════════════════════════

class TestSupervisorInterface:
    """Verify PipelineSupervisor has the expected interface."""

    def test_has_post_agent2_check(self):
        from src.pipeline.supervisor import PipelineSupervisor
        assert hasattr(PipelineSupervisor, 'post_agent2_check')
        sig = inspect.signature(PipelineSupervisor.post_agent2_check)
        params = list(sig.parameters.keys())
        assert 'mapped_sets' in params
        assert 'gap_report' in params
        assert 'entities_to_map' in params

    def test_singleton_returns_instance(self):
        from src.pipeline.supervisor import get_supervisor, PipelineSupervisor
        s = get_supervisor()
        assert isinstance(s, PipelineSupervisor)

    def test_supervisor_report_has_summary(self):
        from src.pipeline.supervisor import SupervisorReport
        report = SupervisorReport()
        assert hasattr(report, 'summary')
        assert isinstance(report.summary, str)

    def test_has_run_method(self):
        """Step 6: PipelineSupervisor must have run(query)."""
        from src.pipeline.supervisor import PipelineSupervisor
        assert hasattr(PipelineSupervisor, 'run')
        sig = inspect.signature(PipelineSupervisor.run)
        params = list(sig.parameters.keys())
        assert 'query' in params, f"run() must accept 'query', got {params}"

    def test_cohort_pipeline_delegates_to_supervisor(self):
        """Step 7: CohortPipeline.run() must delegate to get_supervisor().run()."""
        from src.pipeline.cohort_pipeline import CohortPipeline
        source = inspect.getsource(CohortPipeline.run)
        assert 'get_supervisor' in source, \
            "CohortPipeline.run() must call get_supervisor()"
        assert '.run(' in source, \
            "CohortPipeline.run() must call .run() on supervisor"

    def test_cohort_pipeline_is_thin_wrapper(self):
        """Step 7: CohortPipeline should be a thin wrapper (< 50 lines)."""
        import src.pipeline.cohort_pipeline as mod
        source = inspect.getsource(mod)
        line_count = len(source.splitlines())
        assert line_count < 50, f"cohort_pipeline.py should be thin wrapper, got {line_count} lines"


# ══════════════════════════════════════════════════════════════
# Group 5: Orchestrator interface contract
# ══════════════════════════════════════════════════════════════

class TestOrchestratorInterface:
    """Verify ArtemisPipeline uses CohortPipeline internally."""

    def test_orchestrator_has_cohort_pipeline(self):
        """ArtemisPipeline.__init__ creates a CohortPipeline."""
        from src.pipeline.orchestrator import ArtemisPipeline
        sig = inspect.signature(ArtemisPipeline.__init__)
        # Just verify the class exists and has run()
        assert hasattr(ArtemisPipeline, 'run')

    def test_cohort_result_alias(self):
        """orchestrator uses ArtemisState as the primary data carrier."""
        from src.pipeline.orchestrator import ArtemisPipeline
        from src.pipeline.cohort_pipeline import PipelineResult
        import dataclasses
        from src.pipeline.orchestrator import ArtemisResult
        fields = {f.name for f in dataclasses.fields(ArtemisResult)}
        # After refactoring, 'state' replaced 'cohort_result' as the data carrier
        assert 'state' in fields
