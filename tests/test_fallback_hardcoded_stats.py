"""
RED tests for removing hardcoded fallback stats.

Covers:
- Fix A: _run_agent5_analysis_wrapper returns error payload (no fabricated HR/CI/p)
          on exception, not fabricated statistics.
- Fix B: CohortExecutor._execute_via_webapi returns data=None with used_fallback=False
          when cohort is empty (patient_count=0) instead of attaching synthetic rows.
- Fix C: _run_agent5_analysis_wrapper (or _build_agent5_dataset_for_analysis)
          raises RuntimeError when ExecutionResult.used_fallback is True.
- Fix D: _generate_fallback_data emits a loud logger.warning() with SYNTHETIC FALLBACK.
"""
import logging
import os
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fix A: wrapper returns error payload on exception, never fabricated stats
# ---------------------------------------------------------------------------

class TestRunAgent5AnalysisWrapperErrorPayload:
    """_run_agent5_analysis_wrapper must return an error payload, not fake stats."""

    def _make_service(self):
        """Minimal TTEService-like object that just has the method under test."""
        from src.services.tte_service import TTEService
        svc = TTEService.__new__(TTEService)
        return svc

    def test_error_payload_has_null_hazard_ratio(self):
        """On Agent5 failure the wrapper must return hazardRatio=None, not 0.83."""
        svc = self._make_service()
        study = {
            "treatmentArms": [{"cohortId": 1}, {"cohortId": 2}],
            "outcomes": {"primary": {"cohortId": 3}},
            "timeParams": {"followUpDuration": 365},
            "analysisSettings": {"psMethod": "weighting"},
        }
        results = {"sourceKey": "TEST", "treatmentN": 100, "comparatorN": 100}

        with patch.object(svc, "_build_agent5_dataset_for_analysis", side_effect=RuntimeError("db error")), \
             patch.object(svc, "_resolve_agent5_analysis_method", return_value="IPTW"), \
             patch.object(svc, "_get_capability_signal", return_value=None):
            analysis_results, artifact_meta = svc._run_agent5_analysis_wrapper(study, results)

        assert analysis_results["hazardRatio"] is None, (
            "hazardRatio must be None on error, not a fabricated value"
        )

    def test_error_payload_has_null_p_value(self):
        """On failure the pValue must be None, not 0.005."""
        svc = self._make_service()
        study = {
            "treatmentArms": [{"cohortId": 1}, {"cohortId": 2}],
            "outcomes": {"primary": {"cohortId": 3}},
            "timeParams": {"followUpDuration": 365},
            "analysisSettings": {"psMethod": "weighting"},
        }
        results = {"sourceKey": "TEST", "treatmentN": 100, "comparatorN": 100}

        with patch.object(svc, "_build_agent5_dataset_for_analysis", side_effect=RuntimeError("db error")), \
             patch.object(svc, "_resolve_agent5_analysis_method", return_value="IPTW"), \
             patch.object(svc, "_get_capability_signal", return_value=None):
            analysis_results, artifact_meta = svc._run_agent5_analysis_wrapper(study, results)

        assert analysis_results["pValue"] is None, (
            "pValue must be None on error, not a fabricated value like 0.005"
        )

    def test_error_payload_has_null_ci(self):
        """On failure CI bounds must be None, not fabricated 0.73/0.95."""
        svc = self._make_service()
        study = {
            "treatmentArms": [{"cohortId": 1}, {"cohortId": 2}],
            "outcomes": {"primary": {"cohortId": 3}},
            "timeParams": {"followUpDuration": 365},
            "analysisSettings": {"psMethod": "weighting"},
        }
        results = {"sourceKey": "TEST", "treatmentN": 100, "comparatorN": 100}

        with patch.object(svc, "_build_agent5_dataset_for_analysis", side_effect=RuntimeError("db error")), \
             patch.object(svc, "_resolve_agent5_analysis_method", return_value="IPTW"), \
             patch.object(svc, "_get_capability_signal", return_value=None):
            analysis_results, artifact_meta = svc._run_agent5_analysis_wrapper(study, results)

        ci = analysis_results.get("CI") or {}
        assert ci.get("lower") is None and ci.get("upper") is None, (
            "CI bounds must be None on error, not fabricated values"
        )

    def test_error_artifact_meta_status_is_error(self):
        """ArtifactMeta.status must be 'error', not 'fallback'."""
        svc = self._make_service()
        study = {
            "treatmentArms": [{"cohortId": 1}, {"cohortId": 2}],
            "outcomes": {"primary": {"cohortId": 3}},
            "timeParams": {"followUpDuration": 365},
            "analysisSettings": {"psMethod": "weighting"},
        }
        results = {"sourceKey": "TEST", "treatmentN": 100, "comparatorN": 100}

        with patch.object(svc, "_build_agent5_dataset_for_analysis", side_effect=RuntimeError("db error")), \
             patch.object(svc, "_resolve_agent5_analysis_method", return_value="IPTW"), \
             patch.object(svc, "_get_capability_signal", return_value=None):
            _, artifact_meta = svc._run_agent5_analysis_wrapper(study, results)

        assert artifact_meta.status == "error", (
            "ArtifactMeta.status must be 'error', not 'fallback'"
        )

    def test_error_artifact_meta_reason_contains_exception_name(self):
        """ArtifactMeta.reason must reference the actual exception type."""
        svc = self._make_service()
        study = {
            "treatmentArms": [{"cohortId": 1}, {"cohortId": 2}],
            "outcomes": {"primary": {"cohortId": 3}},
            "timeParams": {"followUpDuration": 365},
            "analysisSettings": {"psMethod": "weighting"},
        }
        results = {"sourceKey": "TEST", "treatmentN": 100, "comparatorN": 100}

        with patch.object(svc, "_build_agent5_dataset_for_analysis", side_effect=ValueError("bad data")), \
             patch.object(svc, "_resolve_agent5_analysis_method", return_value="IPTW"), \
             patch.object(svc, "_get_capability_signal", return_value=None):
            _, artifact_meta = svc._run_agent5_analysis_wrapper(study, results)

        assert artifact_meta.reason is not None
        assert "ValueError" in artifact_meta.reason, (
            "reason must contain the exception type name"
        )

    def test_error_payload_preserves_dataset_counts_when_analysis_crashes(self):
        """If Agent5 fails after dataset build, raw cohort sizes must survive."""
        svc = self._make_service()
        study = {
            "treatmentArms": [{"cohortId": 1}, {"cohortId": 2}],
            "outcomes": {"primary": {"cohortId": 3}},
            "timeParams": {"followUpDuration": 365},
            "analysisSettings": {"psMethod": "weighting"},
        }
        results = {
            "sourceKey": "ARISTOTLE_BENCHMARK",
            "treatmentN": 395,
            "comparatorN": 0,
        }
        dataset = pd.DataFrame(
            {
                "person_id": [1, 2, 3, 4, 5],
                "treatment": [1, 1, 0, 0, 0],
                "time": [10, 20, 30, 40, 50],
                "event": [0, 0, 0, 0, 0],
            }
        )

        class ConvergenceError(RuntimeError):
            pass

        mock_workflow = MagicMock()
        mock_workflow.run.side_effect = ConvergenceError("Cox model NaN delta")

        with patch.object(svc, "_build_agent5_dataset_for_analysis", return_value=dataset), \
             patch.object(svc, "_resolve_agent5_analysis_method", return_value="IPTW"), \
             patch.object(svc, "_get_capability_signal", return_value=None), \
             patch("src.agents.agent5.workflow.Agent5Workflow", return_value=mock_workflow):
            analysis_results, artifact_meta = svc._run_agent5_analysis_wrapper(study, results)

        assert analysis_results["hazardRatio"] is None
        assert analysis_results["treatmentN"] == 2
        assert analysis_results["comparatorN"] == 3
        assert analysis_results["n_target"] == 2
        assert analysis_results["n_comparator"] == 3
        assert "ConvergenceError" in (artifact_meta.reason or "")


# ---------------------------------------------------------------------------
# Fix B: empty cohort must NOT attach synthetic rows to ExecutionResult
# ---------------------------------------------------------------------------

class TestCohortExecutorEmptyReturnsNoSyntheticRows:
    """When real cohort returns 0 patients, never attach synthetic rows."""

    def _make_executor(self):
        from src.pipeline.cohort_executor import CohortExecutor
        executor = CohortExecutor.__new__(CohortExecutor)
        return executor

    def test_empty_cohort_data_is_none_not_synthetic(self):
        """
        When WebAPI returns 0 patients (cohort_ref.is_empty) and
        fallback_mode == 'auto', ExecutionResult.data must be None,
        not a synthetic DataFrame.
        """
        from src.pipeline.cohort_executor import CohortExecutor
        from src.pipeline.webapi_client import CohortTableReference

        mock_connector = MagicMock()
        mock_webapi = MagicMock()

        empty_ref = CohortTableReference(
            cohort_definition_id=99,
            results_schema="results",
            person_count=0,
            source_key="TEST",
            name="empty",
        )
        mock_webapi.generate_cohort.return_value = empty_ref
        mock_connector.diagnose_concepts.return_value = []

        with patch.dict(os.environ, {"ARTEMIS_FALLBACK_MODE": "auto"}):
            executor = CohortExecutor(connector=mock_connector, webapi_client=mock_webapi)
            result = executor.execute(
                circe_json={"ConceptSets": []},
                cohort_name="test",
            )

        assert result.data is None or (
            isinstance(result.data, pd.DataFrame) and result.data.empty
        ), "data must be None or empty when real cohort has 0 patients"

    def test_empty_cohort_used_fallback_is_false(self):
        """
        When WebAPI returns 0 patients, used_fallback must be False —
        we did not successfully fall back to anything usable.
        """
        from src.pipeline.cohort_executor import CohortExecutor
        from src.pipeline.webapi_client import CohortTableReference

        mock_connector = MagicMock()
        mock_webapi = MagicMock()

        empty_ref = CohortTableReference(
            cohort_definition_id=99,
            results_schema="results",
            person_count=0,
            source_key="TEST",
            name="empty",
        )
        mock_webapi.generate_cohort.return_value = empty_ref
        mock_connector.diagnose_concepts.return_value = []

        with patch.dict(os.environ, {"ARTEMIS_FALLBACK_MODE": "auto"}):
            executor = CohortExecutor(connector=mock_connector, webapi_client=mock_webapi)
            result = executor.execute(
                circe_json={"ConceptSets": []},
                cohort_name="test",
            )

        assert result.used_fallback is False, (
            "used_fallback must be False when real data is empty — "
            "attaching synthetic rows to a zero-patient result is misleading"
        )

    def test_empty_cohort_has_error_field(self):
        """
        ExecutionResult for empty real cohort must carry an error description.
        """
        from src.pipeline.cohort_executor import CohortExecutor
        from src.pipeline.webapi_client import CohortTableReference

        mock_connector = MagicMock()
        mock_webapi = MagicMock()

        empty_ref = CohortTableReference(
            cohort_definition_id=99,
            results_schema="results",
            person_count=0,
            source_key="TEST",
            name="empty",
        )
        mock_webapi.generate_cohort.return_value = empty_ref
        mock_connector.diagnose_concepts.return_value = []

        with patch.dict(os.environ, {"ARTEMIS_FALLBACK_MODE": "auto"}):
            executor = CohortExecutor(connector=mock_connector, webapi_client=mock_webapi)
            result = executor.execute(
                circe_json={"ConceptSets": []},
                cohort_name="test",
            )

        # ExecutionResult should have an error or reason field
        assert hasattr(result, "error") and result.error, (
            "ExecutionResult must have a non-empty error field when real cohort is empty"
        )

    def test_empty_analysis_dataset_data_is_none(self):
        """
        When WebAPI returns patients but connector.build_analysis_dataset returns
        an empty DataFrame, ExecutionResult.data must be None, not synthetic rows.
        """
        from src.pipeline.cohort_executor import CohortExecutor
        from src.pipeline.webapi_client import CohortTableReference

        mock_connector = MagicMock()
        mock_webapi = MagicMock()

        nonempty_ref = CohortTableReference(
            cohort_definition_id=10,
            results_schema="results",
            person_count=100,
            source_key="TEST",
            name="treatment",
        )
        mock_webapi.generate_cohort.return_value = nonempty_ref
        mock_connector.build_analysis_dataset_from_cohort.return_value = pd.DataFrame()

        with patch.dict(os.environ, {"ARTEMIS_FALLBACK_MODE": "auto"}):
            executor = CohortExecutor(connector=mock_connector, webapi_client=mock_webapi)
            result = executor.execute(
                circe_json={"ConceptSets": []},
                cohort_name="test",
            )

        assert result.data is None or (
            isinstance(result.data, pd.DataFrame) and result.data.empty
        ), "data must be None/empty when analysis dataset is empty, not synthetic rows"

        assert result.used_fallback is False, (
            "used_fallback must be False when dataset is empty — no valid substitution occurred"
        )


# ---------------------------------------------------------------------------
# Fix C: wrapper must reject used_fallback=True ExecutionResults
# ---------------------------------------------------------------------------

class TestAgent5WrapperRejectsFallbackCohort:
    """_run_agent5_analysis_wrapper must raise when cohort data is synthetic fallback."""

    def _make_service(self):
        from src.services.tte_service import TTEService
        svc = TTEService.__new__(TTEService)
        return svc

    def test_raises_when_execution_result_used_fallback_true(self):
        """
        If _build_agent5_dataset_for_analysis detects used_fallback=True in
        the underlying ExecutionResult, it must raise RuntimeError before
        the workflow runs.
        """
        svc = self._make_service()
        study = {
            "treatmentArms": [{"cohortId": 1}, {"cohortId": 2}],
            "outcomes": {"primary": {"cohortId": 3}},
            "timeParams": {"followUpDuration": 365},
            "analysisSettings": {"psMethod": "weighting"},
        }
        results = {
            "sourceKey": "TEST",
            "treatmentN": 500,
            "comparatorN": 500,
        }

        # Simulate dataset builder detecting used_fallback=True and raising
        def _raise_on_fallback(study, results):
            raise RuntimeError(
                "Cannot run analysis: cohort data is synthetic fallback, not real OMOP data"
            )

        with patch.object(svc, "_build_agent5_dataset_for_analysis", side_effect=_raise_on_fallback), \
             patch.object(svc, "_resolve_agent5_analysis_method", return_value="IPTW"), \
             patch.object(svc, "_get_capability_signal", return_value=None):
            analysis_results, artifact_meta = svc._run_agent5_analysis_wrapper(study, results)

        # The wrapper catches it and returns error payload — not fabricated stats
        assert analysis_results["hazardRatio"] is None
        assert artifact_meta.status == "error"
        assert "synthetic" in (artifact_meta.reason or "").lower() or \
               "fallback" in (artifact_meta.reason or "").lower(), (
            "reason must indicate the data is synthetic/fallback"
        )


# ---------------------------------------------------------------------------
# Fix D: _generate_fallback_data must emit a loud logger.warning
# ---------------------------------------------------------------------------

class TestGenerateFallbackDataWarning:
    """_generate_fallback_data must emit a WARNING-level log about synthetic data."""

    def test_emits_warning_log(self, caplog):
        from src.pipeline.cohort_executor import CohortExecutor
        executor = CohortExecutor.__new__(CohortExecutor)
        executor.connector = MagicMock()
        executor.webapi_client = MagicMock()

        with patch.dict(os.environ, {"ARTEMIS_FALLBACK_MODE": "auto"}):
            with caplog.at_level(logging.WARNING, logger="src.pipeline.cohort_executor"):
                executor._generate_fallback_data()

        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("SYNTHETIC" in msg.upper() or "synthetic" in msg.lower() for msg in warning_messages), (
            "_generate_fallback_data must emit a WARNING-level log mentioning synthetic/fake data. "
            f"Got: {warning_messages}"
        )

    def test_warning_mentions_fake_patients(self, caplog):
        from src.pipeline.cohort_executor import CohortExecutor
        executor = CohortExecutor.__new__(CohortExecutor)
        executor.connector = MagicMock()
        executor.webapi_client = MagicMock()

        with patch.dict(os.environ, {"ARTEMIS_FALLBACK_MODE": "auto"}):
            with caplog.at_level(logging.WARNING, logger="src.pipeline.cohort_executor"):
                executor._generate_fallback_data(n_treated=50, n_control=50)

        all_text = " ".join(r.message for r in caplog.records if r.levelno >= logging.WARNING)
        assert "NOT real" in all_text or "not real" in all_text.lower() or "fabricated" in all_text.lower() or \
               "fake" in all_text.lower() or "synthetic" in all_text.lower(), (
            "Warning must state data is NOT real OMOP data"
        )
