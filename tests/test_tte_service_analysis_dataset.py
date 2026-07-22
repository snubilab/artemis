"""Tests for _build_agent5_dataset_for_analysis() behavior.

Verifies that when real cohort data is unavailable or raises an error,
the method raises RuntimeError instead of silently falling back to
hardcoded synthetic data.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.services.tte_service import TTEService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
