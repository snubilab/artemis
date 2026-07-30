"""Tests for _build_agent5_dataset_for_analysis() behavior.

Verifies that when real cohort data is unavailable or raises an error,
the method raises RuntimeError instead of silently falling back to
hardcoded synthetic data.
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.services.tte_service import TTEService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_omop_connector(connector_instance: MagicMock):
    """Register a stub `src.analysis.omop_connector` module in sys.modules.

    `_build_agent5_real_dataset_from_generated_cohorts` does a function-local
    `from src.analysis.omop_connector import OMOPConnector`. Importing the real
    `src.analysis` package pulls in pandas/numpy/lifelines transitively, which
    this test environment does not always have installed. Pre-registering the
    dotted module name makes Python's import system return the stub directly
    (see importlib._bootstrap._find_and_load) without ever executing
    src/analysis/__init__.py, so these tests exercise only the comparator-
    selection logic under test, not the real connector's dependencies.
    """
    fake_module = types.ModuleType("src.analysis.omop_connector")
    fake_module.OMOPConnector = MagicMock(return_value=connector_instance)
    return patch.dict(sys.modules, {"src.analysis.omop_connector": fake_module})


def _make_service() -> TTEService:
    """Create a TTEService instance with mocked store."""
    svc = TTEService.__new__(TTEService)
    svc.store = MagicMock()
    return svc


def _fake_study() -> dict[str, Any]:
    return {
        "id": 1,
        "name": "Test Study",
        "treatmentArms": [
            {"cohortId": "100"},
            {"cohortId": "200"},
        ],
        "outcomes": {
            "primary": {"cohortId": "300"},
        },
        "timeParams": {"followUpDuration": 365},
        "analysisSettings": {"psMethod": "weighting"},
    }


def _fake_results() -> dict[str, Any]:
    return {
        "sourceKey": "SYNTHEA_CDM",
        "treatmentN": 0,
        "comparatorN": 0,
        "resultsSchema": None,
    }


# ---------------------------------------------------------------------------
# RED tests — these MUST FAIL before the fix is applied
# ---------------------------------------------------------------------------


class TestBuildAgent5DatasetForAnalysis:
    """_build_agent5_dataset_for_analysis() must raise on missing real data."""

    def test_raises_when_real_dataset_returns_none(self) -> None:
        """No real data (None) → RuntimeError, not a synthetic DataFrame."""
        svc = _make_service()
        with patch.object(
            svc,
            "_build_agent5_real_dataset_from_generated_cohorts",
            return_value=None,
        ):
            with pytest.raises(RuntimeError, match="Cannot build analysis dataset"):
                svc._build_agent5_dataset_for_analysis(_fake_study(), _fake_results())

    def test_raises_when_real_dataset_returns_empty_dataframe(self) -> None:
        """Empty DataFrame → RuntimeError, not a synthetic DataFrame."""
        import pandas as pd

        svc = _make_service()
        with patch.object(
            svc,
            "_build_agent5_real_dataset_from_generated_cohorts",
            return_value=pd.DataFrame(),
        ):
            with pytest.raises(RuntimeError, match="Cannot build analysis dataset"):
                svc._build_agent5_dataset_for_analysis(_fake_study(), _fake_results())

    def test_raises_on_connector_exception(self) -> None:
        """Connector failure → RuntimeError with message, not silent fallback."""
        svc = _make_service()
        with patch.object(
            svc,
            "_build_agent5_real_dataset_from_generated_cohorts",
            side_effect=ConnectionError("DB unreachable"),
        ):
            with pytest.raises(RuntimeError, match="Cannot build analysis dataset"):
                svc._build_agent5_dataset_for_analysis(_fake_study(), _fake_results())

    def test_error_message_mentions_cohort_generation(self) -> None:
        """RuntimeError message must mention results schema and cohort generation."""
        svc = _make_service()
        with patch.object(
            svc,
            "_build_agent5_real_dataset_from_generated_cohorts",
            return_value=None,
        ):
            with pytest.raises(RuntimeError) as exc_info:
                svc._build_agent5_dataset_for_analysis(_fake_study(), _fake_results())
            message = str(exc_info.value).lower()
            assert "cohort" in message or "results schema" in message

    def test_returns_real_dataset_when_available(self) -> None:
        """When real data is present, it is returned unchanged."""
        import pandas as pd

        svc = _make_service()
        real_data = pd.DataFrame(
            {
                "person_id": [1, 2],
                "treatment": [1, 0],
                "time": [100, 120],
                "event": [1, 0],
            }
        )
        with patch.object(
            svc,
            "_build_agent5_real_dataset_from_generated_cohorts",
            return_value=real_data,
        ):
            result = svc._build_agent5_dataset_for_analysis(_fake_study(), _fake_results())
        assert result is real_data

    def test_does_not_return_synthetic_24_row_dataframe(self) -> None:
        """Regression guard: result must never be the 12+12 hardcoded synthetic dataset."""
        svc = _make_service()
        with patch.object(
            svc,
            "_build_agent5_real_dataset_from_generated_cohorts",
            return_value=None,
        ):
            with pytest.raises(RuntimeError):
                result = svc._build_agent5_dataset_for_analysis(
                    _fake_study(), _fake_results()
                )
                # If we somehow reach here (pre-fix), ensure it's not the synthetic data
                import pandas as pd
                if isinstance(result, pd.DataFrame):
                    assert len(result) != 24, (
                        "Got the hardcoded 12+12 synthetic dataset — fix not applied"
                    )


def test_build_agent5_real_dataset_uses_rest_comparator_for_aristotle() -> None:
    """Derived comparator with 0 persons must become comparator_ref=None."""
    svc = _make_service()
    study = {
        "timeParams": {"followUpDuration": 365},
    }
    results = {
        "sourceKey": "ARISTOTLE_BENCHMARK",
        "resultsSchema": "synthea_cdm_aristotle_results",
        "generatedCohorts": [
            {
                "role": "treatment",
                "label": "Apixaban",
                "cohortDefinitionId": 890,
                "personCount": 395,
                "sourceKey": "ARISTOTLE_BENCHMARK",
                "resultsSchema": "synthea_cdm_aristotle_results",
            },
            {
                "role": "primary_outcome",
                "label": "Stroke/Systemic Embolism",
                "cohortDefinitionId": 891,
                "personCount": 55,
                "sourceKey": "ARISTOTLE_BENCHMARK",
                "resultsSchema": "synthea_cdm_aristotle_results",
            },
            {
                "role": "comparator",
                "label": "Rest of target population",
                "cohortDefinitionId": 889,
                "personCount": 0,
                "sourceKey": "ARISTOTLE_BENCHMARK",
                "resultsSchema": "synthea_cdm_aristotle_results",
            },
        ],
    }

    connector_instance = MagicMock()
    connector_instance.build_analysis_dataset_from_generated_cohorts.return_value = "dataset"

    with patch("src.analysis.omop_connector.OMOPConnector", return_value=connector_instance) as mock_connector:
        dataset = svc._build_agent5_real_dataset_from_generated_cohorts(study, results)

    assert dataset == "dataset"
    assert mock_connector.call_args.kwargs["schema"] == "synthea_cdm_aristotle"
    assert (
        connector_instance.build_analysis_dataset_from_generated_cohorts.call_args.kwargs["comparator_ref"]
        is None
    )


def test_build_agent5_real_dataset_prefers_generated_comparator_over_stale_mode(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A real, distinct comparator cohort (ADR-027/028 active/derived comparator)
    must be used even when study["comparisonMode"] is still the stale
    "target_minus_treatment" default that _study_from_ir never updates after
    generation. Regression test for the comparator-mode finding: downstream
    analysis must not silently fall back to the eligibility target population
    when a real comparator was generated for this study.
    """
    svc = _make_service()
    study = {
        "id": 42,
        "comparisonMode": "target_minus_treatment",  # stale default, never updated
        "timeParams": {"followUpDuration": 365},
    }
    results = {
        "sourceKey": "SYNTHEA_CDM_BENCHMARK",
        "resultsSchema": "synthea_cdm_benchmark_results",
        "generatedCohorts": [
            {
                "role": "target",
                "label": "Target population",
                "cohortDefinitionId": 1,
                "personCount": 1000,
                "sourceKey": "SYNTHEA_CDM_BENCHMARK",
                "resultsSchema": "synthea_cdm_benchmark_results",
            },
            {
                "role": "treatment",
                "label": "Apixaban",
                "cohortDefinitionId": 2,
                "personCount": 400,
                "sourceKey": "SYNTHEA_CDM_BENCHMARK",
                "resultsSchema": "synthea_cdm_benchmark_results",
            },
            {
                "role": "comparator",
                "label": "Warfarin (active comparator)",
                "cohortDefinitionId": 3,
                "personCount": 350,
                "sourceKey": "SYNTHEA_CDM_BENCHMARK",
                "resultsSchema": "synthea_cdm_benchmark_results",
            },
            {
                "role": "primary_outcome",
                "label": "Stroke/Systemic Embolism",
                "cohortDefinitionId": 4,
                "personCount": 55,
                "sourceKey": "SYNTHEA_CDM_BENCHMARK",
                "resultsSchema": "synthea_cdm_benchmark_results",
            },
        ],
    }

    connector_instance = MagicMock()
    connector_instance.build_analysis_dataset_from_generated_cohorts.return_value = "dataset"

    with _stub_omop_connector(connector_instance):
        with caplog.at_level("WARNING"):
            dataset = svc._build_agent5_real_dataset_from_generated_cohorts(study, results)

    assert dataset == "dataset"
    comparator_ref = (
        connector_instance.build_analysis_dataset_from_generated_cohorts.call_args.kwargs["comparator_ref"]
    )
    # Must be the real generated comparator (id=3), not the eligibility target (id=1).
    assert comparator_ref is not None
    assert comparator_ref.cohort_definition_id == 3
    assert comparator_ref.person_count == 350
    # The mismatch between the stale stored mode and the real generated comparator
    # must be recorded, not silently swallowed.
    assert any("comparisonMode" in record.message for record in caplog.records)


def test_build_agent5_real_dataset_uses_generated_comparator_in_explicit_mode() -> None:
    """Sanity check: when comparisonMode already says explicit_comparator, the
    real comparator cohort is used exactly as before (no behavior change for the
    already-correct case).
    """
    svc = _make_service()
    study = {
        "id": 7,
        "comparisonMode": "explicit_comparator",
        "timeParams": {"followUpDuration": 365},
    }
    source_key = "SYNTHEA_CDM_BENCHMARK"
    schema = "synthea_cdm_benchmark_results"
    results = {
        "sourceKey": source_key,
        "resultsSchema": schema,
        "generatedCohorts": [
            {"role": "treatment", "label": "Drug A", "cohortDefinitionId": 10,
             "personCount": 200, "sourceKey": source_key, "resultsSchema": schema},
            {"role": "comparator", "label": "Drug B", "cohortDefinitionId": 11,
             "personCount": 180, "sourceKey": source_key, "resultsSchema": schema},
            {"role": "primary_outcome", "label": "Outcome", "cohortDefinitionId": 12,
             "personCount": 30, "sourceKey": source_key, "resultsSchema": schema},
        ],
    }

    connector_instance = MagicMock()
    connector_instance.build_analysis_dataset_from_generated_cohorts.return_value = "dataset"

    with _stub_omop_connector(connector_instance):
        svc._build_agent5_real_dataset_from_generated_cohorts(study, results)

    comparator_ref = (
        connector_instance.build_analysis_dataset_from_generated_cohorts.call_args.kwargs["comparator_ref"]
    )
    assert comparator_ref.cohort_definition_id == 11
