from __future__ import annotations

from unittest.mock import MagicMock

from src.services.tte_service import TTEService


def _make_service() -> TTEService:
    svc = TTEService.__new__(TTEService)
    svc.store = MagicMock()
    return svc


def _study(ps_method: str = "matching") -> dict:
    return {
        "eligibility": {"structuredExpression": {"ConceptSets": []}},
        "timeParams": {"followUpDuration": 365},
        "analysisSettings": {
            "outcomeModel": "cox",
            "adjustForCovariates": True,
            "psMethod": ps_method,
            "psCaliper": 0.2,
            "trimByPs": True,
            "trimFraction": 0.05,
        },
    }


def _results(treatment_n: int = 800, comparator_n: int = 1600) -> dict:
    return {
        "mode": "webapi_generation",
        "treatmentN": treatment_n,
        "comparatorN": comparator_n,
    }


def test_build_analysis_strategy_includes_recommendation_first_fields() -> None:
    svc = _make_service()

    strategy = svc._build_analysis_strategy(_study(), _results())

    assert strategy.diagnosisTitle == "Cohort balance diagnosis"
    assert strategy.diagnosisSummary
    assert len(strategy.diagnosisFacts) >= 3
    assert strategy.proposedParameters["psMethod"] in {
        "matching",
        "weighting",
        "mahalanobis",
        "stratification",
    }
    assert strategy.rejectedAlternatives
    assert strategy.recommendationStage == "draft"


def test_build_analysis_strategy_honors_requested_ps_method_override() -> None:
    svc = _make_service()

    strategy = svc._build_analysis_strategy(
        _study(),
        _results(),
        requested_ps_method="weighting",
        recommendation_stage="final",
    )

    assert strategy.method == "IPTW"
    assert strategy.proposedParameters["psMethod"] == "weighting"
    assert strategy.requestedPsMethod == "weighting"
    assert strategy.recommendationStage == "final"
    assert "Requested override" in strategy.reasoning["method"]


def test_analysis_strategy_method_to_ps_method_supports_stratification() -> None:
    svc = _make_service()

    assert svc._analysis_strategy_method_to_ps_method("STRATIFICATION") == "stratification"
