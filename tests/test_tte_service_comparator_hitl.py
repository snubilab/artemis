"""Tests for the mock-HITL comparator recommendation bypass fix.

ADR-028 requires a literature-derived comparator recommendation to be
proposed and then approved by a human before it can change the comparator
(and therefore the causal estimand). _mock_hitl_approve_comparator used to
auto-approve the top recommendation with no durable record and no chance to
reject. Verifies that a recommendation is now always logged (never silently
discarded) and never auto-applied — the derived (safe) comparator is used
until a real approval channel exists.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from src.services.tte_service import TTEService


def _make_service() -> TTEService:
    svc = TTEService.__new__(TTEService)
    svc.store = MagicMock()
    return svc


def _fake_study() -> dict[str, Any]:
    return {
        "id": 1,
        "name": "Placebo-controlled trial",
        "indication": "Type 2 Diabetes",
        "outcomes": {"primary": {"cohortName": "MACE"}},
    }


def _fake_eligibility() -> dict[str, Any]:
    return {"structuredExpression": {"PrimaryCriteria": {"CriteriaList": []}}}


class TestRecordPendingComparatorRecommendation:
    """_record_pending_comparator_recommendation must never approve anything."""

    def test_returns_none_always(self) -> None:
        svc = _make_service()
        result = {
            "recommendation": {
                "class": "DPP-4 inhibitors",
                "drug_class": "DPP-4 inhibitors",
                "ingredients": ["sitagliptin"],
            }
        }
        # No return value to assert on approval — the method must not hand back
        # anything an old caller could treat as "approved".
        assert svc._record_pending_comparator_recommendation(result) is None

    def test_logs_recommendation_when_present(self, caplog) -> None:
        svc = _make_service()
        result = {
            "recommendation": {
                "drug_class": "DPP-4 inhibitors",
                "ingredients": ["sitagliptin", "linagliptin"],
            }
        }
        with caplog.at_level("WARNING"):
            svc._record_pending_comparator_recommendation(result)
        assert any("DPP-4 inhibitors" in r.message for r in caplog.records)

    def test_silent_when_no_recommendation(self, caplog) -> None:
        svc = _make_service()
        with caplog.at_level("WARNING"):
            svc._record_pending_comparator_recommendation({"recommendation": None})
        assert not caplog.records


class TestBuildRecommendedPlaceboComparatorCirce:
    """Regression test for the bypass: a real recommendation must never be
    auto-applied, even when the literature step succeeds and is CDM-groundable.
    """

    def test_never_auto_applies_recommendation_even_when_groundable(self) -> None:
        svc = _make_service()
        recommendation = {
            "drug_class": "DPP-4 inhibitors",
            "ingredients": ["sitagliptin"],
        }

        with patch.object(
            svc, "_build_disease_based_comparator_circe", return_value={"kind": "derived"}
        ) as fallback, patch.object(
            svc, "_build_drug_anchored_comparator_circe", return_value={"kind": "active"}
        ) as active_builder, patch(
            "src.agents.comparator.recommender.recommend_from_literature",
            return_value={"recommendation": recommendation},
        ):
            circe = svc._build_recommended_placebo_comparator_circe(
                _fake_eligibility(), "Empagliflozin", study=_fake_study(), time_params={}
            )

        # Must fall back to the derived (safe) comparator, never the recommended one.
        assert circe == {"kind": "derived"}
        fallback.assert_called_once()
        active_builder.assert_not_called()

    def test_falls_back_when_no_recommendation_produced(self) -> None:
        svc = _make_service()
        with patch.object(
            svc, "_build_disease_based_comparator_circe", return_value={"kind": "derived"}
        ) as fallback, patch(
            "src.agents.comparator.recommender.recommend_from_literature",
            return_value={"recommendation": None},
        ):
            circe = svc._build_recommended_placebo_comparator_circe(
                _fake_eligibility(), "Empagliflozin", study=_fake_study(), time_params={}
            )

        assert circe == {"kind": "derived"}
        fallback.assert_called_once()
