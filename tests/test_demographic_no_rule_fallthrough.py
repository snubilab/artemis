"""Demographic-domain exclusion criteria with no buildable numeric rule must fall
through to ordinary concept-set mapping instead of being silently dropped.

Real fixture data (verified against ``artemis/tmp/mesh_fix/studies.json``): 7 leaf
exclusion criteria across studies 8/9/10 share this exact shape --
``domain="Demographics"``, ``valueConstraint=None``, ``isGroupLabel=False``,
``groupId=None``, ``logicType="ABSENCE"`` -- and one 8th criterion (id=70) is the
group LABEL that must remain excluded from direct mapping in every code path.

Before this fix, ``TTEService._build_seeded_target_circe``'s exclusion loop dropped
every one of the 7 leaf criteria as ``"demographic-no-rule"`` without ever asking
whether they could be mapped like an ordinary (non-demographic) criterion. This test
module pins the fix at all 6+ touch points named in the approved design:

  (a)(b)(c)  TTEService._build_seeded_target_circe -- exclusion loop fallthrough +
             ordered_pairs mirror + the expected_domain=None regression guard on
             TTEService._build_seeded_eligibility_rule
  (d)        the existing operator-inversion path (real numeric valueConstraint)
             stays unchanged
  (e)        the isGroupLabel carve-out (id=70) stays unchanged
  (f)        TTEService._apply_draft_concept_set_metadata -- preview/draft parity
  (g)        Criterion.mappable (src/api/models/tte.py) -- the computed_field
  (h)        POST .../re-recommend -- the 400-gate in src/api/tte.py
  (i)        GET .../mapping-candidates legacy fallback -- src/api/tte.py
"""

from __future__ import annotations

import importlib.util
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.api.models.tte import CriterionMappingMetadata, MappingCandidateItem

_fastapi_available = importlib.util.find_spec("fastapi") is not None
_skip_http = pytest.mark.skipif(not _fastapi_available, reason="fastapi not installed")


# ---------------------------------------------------------------------------
# Fixtures matching the real data exactly (tmp/mesh_fix/studies.json)
# ---------------------------------------------------------------------------


def _id63_fixture(
    *,
    id_: int = 63,
    description: str = "Pre-menopausal women exclusion (General)",
    source_text: str = "Pre-menopausal women",
) -> dict[str, Any]:
    """study8/63 shape -- shared by all 7 real "demographic-no-rule" exclusions."""
    return {
        "id": id_,
        "description": description,
        "domain": "Demographics",
        "valueConstraint": None,
        "sourceText": source_text,
        "window": {"start": -365, "end": 0},
        "conceptSetId": None,
        "conceptSetName": "",
        "logicType": "ABSENCE",
        "groupId": None,
        "groupType": "ALL",
        "isGroupLabel": False,
    }


def _id70_fixture() -> dict[str, Any]:
    """study8/70 -- the group LABEL that must remain excluded from direct mapping."""
    return {
        "id": 70,
        "description": "Nursing or pregnant exclusion",
        "domain": "Demographics",
        "valueConstraint": None,
        "sourceText": "Nursing or pregnant",
        "window": {"start": -9999, "end": 0},
        "conceptSetId": None,
        "conceptSetName": "",
        "logicType": "ABSENCE",
        "groupId": "1ebb0d67-cd81-4896-b073-00e8a710f647",
        "groupType": "ALL",
        "isGroupLabel": True,
    }


def _age_gt_65_exclusion_fixture() -> dict[str, Any]:
    """A real numeric valueConstraint -- must still take the operator-inversion path."""
    return {
        "id": 999,
        "description": "Age > 65 exclusion",
        "domain": "Demographics",
        "valueConstraint": {"op": "gt", "value": 65},
        "sourceText": "Age > 65",
        "window": None,
        "conceptSetId": None,
        "conceptSetName": "",
        "logicType": "PRESENCE",
        "groupId": None,
        "groupType": "ALL",
        "isGroupLabel": False,
    }


def _stub_recommend(
    seed_text: str,
    *,
    expected_domain: str | None = None,
    pre_fetched_candidates: list | None = None,
    workflow: Any | None = None,
    alias_candidates: list[str] | None = None,
) -> dict[str, Any]:
    """Canned Observation-domain concept-set recommendation.

    Signature mirrors ``TTEService._recommend_seeded_concept_set`` exactly so it can
    be substituted for it wholesale -- this stub never touches ChromaDB/vLLM.
    """
    return {
        "name": seed_text or "stub concept set",
        "domain": "Observation",
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": 4145762,
                        "CONCEPT_NAME": "Pregnant",
                        "CONCEPT_CODE": "77386006",
                        "DOMAIN_ID": "Observation",
                        "VOCABULARY_ID": "SNOMED",
                        "CONCEPT_CLASS_ID": "Clinical Finding",
                    },
                    "includeDescendants": True,
                    "isExcluded": False,
                }
            ]
        },
    }


@pytest.fixture
def service():
    """A TTEService with the expensive mapping method stubbed (no DB/vLLM calls)."""
    from src.services.tte_service import TTEService

    svc = TTEService.__new__(TTEService)
    return svc


@pytest.fixture
def recommend_mock():
    return MagicMock(side_effect=_stub_recommend)


def _build_circe(service, recommend_mock, *, exclusion: list[dict[str, Any]]) -> dict[str, Any]:
    service._recommend_seeded_concept_set = recommend_mock
    eligibility = {
        "targetCohortName": "T2DM cohort",
        "inclusionCriteria": [],
        "exclusionCriteria": exclusion,
    }
    return service._build_seeded_target_circe(eligibility)


# ---------------------------------------------------------------------------
# (a)(b)(c) -- the id=63-shaped criterion falls through to mappable_items,
# produces a real (non-demographic) CIRCE rule, and the mapper is called with
# expected_domain=None (NOT the bogus raw "Demographics" domain hint).
# ---------------------------------------------------------------------------


class TestDemographicNoRuleFallsThroughToMappable:
    def test_a_not_recorded_as_demographic_no_rule_skip(self, service, recommend_mock):
        circe = _build_circe(service, recommend_mock, exclusion=[_id63_fixture()])
        reasons = [r["reason"] for r in circe["_skippedCriteria"]]
        assert "demographic-no-rule" not in reasons, (
            f"id=63-shaped criterion must fall through to mappable, not be skipped; "
            f"_skippedCriteria={circe['_skippedCriteria']}"
        )

    def test_b_rule_uses_observation_criteria_list_not_demographic_criteria(
        self, service, recommend_mock
    ):
        circe = _build_circe(service, recommend_mock, exclusion=[_id63_fixture()])
        rules = circe["InclusionRules"]
        assert len(rules) == 1, rules
        expr = rules[0]["expression"]
        assert expr["DemographicCriteriaList"] == []
        assert len(expr["CriteriaList"]) == 1
        entry = expr["CriteriaList"][0]
        assert set(entry["Criteria"].keys()) == {"Observation"}, entry
        assert "DemographicCriteria" not in entry["Criteria"], (
            "invalid CIRCE occurrence-table key 'DemographicCriteria' must never "
            f"be emitted for a CriteriaList entry; got {entry}"
        )
        codeset_id = entry["Criteria"]["Observation"]["CodesetId"]
        assert entry == {
            "Criteria": {"Observation": {"CodesetId": codeset_id}},
            "StartWindow": entry["StartWindow"],
            "RestrictVisit": False,
            "IgnoreObservationPeriod": False,
            "Occurrence": {"Type": 0, "Count": 0},
        }

    def test_c_mapper_called_with_expected_domain_none(self, service, recommend_mock):
        _build_circe(service, recommend_mock, exclusion=[_id63_fixture()])
        matching_calls = [
            call
            for call in recommend_mock.call_args_list
            if call.args and call.args[0] == "Pre-menopausal women"
        ]
        assert matching_calls, (
            f"mapper was never called with the id=63 criterion's label; "
            f"calls={recommend_mock.call_args_list}"
        )
        assert len(matching_calls) == 1, matching_calls
        got_domain = matching_calls[0].kwargs.get("expected_domain")
        assert got_domain is None, (
            "expected_domain must be None so the mapper infers the real domain "
            f"from the concept-set match itself; got {got_domain!r} (the raw "
            "'Demographics' domain hint would emit an invalid CIRCE "
            "'DemographicCriteria' key)"
        )


# ---------------------------------------------------------------------------
# (d) -- a companion fixture WITH a real numeric valueConstraint must be
# unchanged: still produces a DemographicCriteriaList rule via the existing
# operator-inversion path, and never reaches the mapper.
# ---------------------------------------------------------------------------


class TestRealValueConstraintStaysDemographicOnly:
    def test_d_age_gt_65_exclusion_still_inverts_to_demographic_rule(
        self, service, recommend_mock
    ):
        circe = _build_circe(
            service, recommend_mock, exclusion=[_age_gt_65_exclusion_fixture()]
        )
        assert circe["_skippedCriteria"] == []
        assert circe["_generationCensus"]["demographicRules"] == 1

        rules = circe["InclusionRules"]
        assert len(rules) == 1, rules
        expr = rules[0]["expression"]
        assert expr["CriteriaList"] == []
        assert expr["DemographicCriteriaList"] == [{"Age": {"Value": 65, "Op": "lte"}}]

        matching_calls = [
            call
            for call in recommend_mock.call_args_list
            if call.args and call.args[0] == "Age > 65"
        ]
        assert not matching_calls, (
            "a criterion with a real numeric valueConstraint must stay "
            f"demographic-only and never reach the mapper; calls={matching_calls}"
        )


# ---------------------------------------------------------------------------
# (e) -- the group-label carve-out (id=70) must remain excluded from direct
# mapping in every code path.
# ---------------------------------------------------------------------------


class TestGroupLabelCarveOutPreserved:
    def test_e_group_label_still_skipped_not_mapped(self, service, recommend_mock):
        circe = _build_circe(service, recommend_mock, exclusion=[_id70_fixture()])
        skipped = circe["_skippedCriteria"]
        assert len(skipped) == 1, skipped
        assert skipped[0]["criterionId"] == "70"
        assert skipped[0]["reason"] == "group-label"
        assert skipped[0]["isGroupLabel"] is True
        assert circe["InclusionRules"] == []

        matching_calls = [
            call
            for call in recommend_mock.call_args_list
            if call.args and call.args[0] == "Nursing or pregnant"
        ]
        assert not matching_calls, (
            f"a group-label criterion must never reach the mapper; calls={matching_calls}"
        )


# ---------------------------------------------------------------------------
# (f) -- preview/draft parity: _apply_draft_concept_set_metadata must enrich
# the id=63-shaped criterion with a real conceptSetId, not leave it null.
# ---------------------------------------------------------------------------


class TestDraftPreviewParity:
    def test_f_apply_draft_concept_set_metadata_populates_concept_set_id(self, service):
        criterion = _id63_fixture()
        concept_sets = [{"id": 5, "name": "Pregnancy-related", "expression": {"items": []}}]
        role = "exclusion"
        key = service._criterion_mapping_key(role, str(criterion["id"]))
        refs = {key: 5}

        updated = service._apply_draft_concept_set_metadata(
            [criterion], concept_sets, 1, {}, role, refs,
        )

        assert len(updated) == 1
        assert updated[0]["conceptSetId"] == 5, (
            "the draft/preview payload must show the same concept set the final "
            f"generation would use, not leave conceptSetId null; got {updated[0]}"
        )
        assert updated[0]["conceptSetName"] == "Pregnancy-related"


# ---------------------------------------------------------------------------
# Regression (found post-merge by a full-suite audit, not part of the original
# 9-item spec): the exclusion-only scope of the generation-loop fallthrough
# (commit 2ea02b2) means _build_seeded_target_circe's INCLUSION loop still
# drops a demographic-no-rule criterion unconditionally -- but
# _apply_draft_concept_set_metadata's skip check, now driven by the shared
# helper, no longer knows that. For criterion_role="inclusion" it must keep
# skipping a demographic-no-rule criterion (matching what generation actually
# does), or the positional-fallback lookup consumes a slot that belongs to
# the FOLLOWING criterion and silently shifts every concept set after it by
# one -- confirmed against real LEADER-trial data (tmp/mesh_fix/studies.json
# study id=4, inclusion criteria id 6/7/8 have exactly this shape).
# ---------------------------------------------------------------------------


class TestInclusionSidePreviewDoesNotStealFollowingConceptSets:
    def test_inclusion_demographic_no_rule_criterion_is_skipped_not_enriched(self, service):
        demo = _id63_fixture(id_=6, description="Age and cardiovascular risk factors", source_text="Age")
        following = {
            "id": 9,
            "description": "Type 2 diabetes",
            "domain": "Condition",
            "valueConstraint": None,
            "sourceText": "Type 2 diabetes",
            "conceptSetId": None,
            "conceptSetName": "",
            "isGroupLabel": False,
            "groupId": None,
        }
        concept_sets = [
            {"id": 0, "name": "Target", "expression": {"items": []}},
            {"id": 1, "name": "Type 2 diabetes concept set", "expression": {"items": []}},
        ]

        updated = service._apply_draft_concept_set_metadata(
            [demo, following], concept_sets, 1, {}, "inclusion", {},
        )

        assert updated[0].get("conceptSetId") is None, (
            "an inclusion-side demographic-no-rule criterion must stay unmapped in "
            "the preview, matching what generation actually does (the fallthrough "
            "is exclusion-only) -- got a fabricated conceptSetId "
            f"{updated[0].get('conceptSetId')!r}"
        )
        assert updated[1]["conceptSetId"] == 1, (
            "the criterion AFTER the demographic-no-rule one must receive its own "
            "concept set (index 1), not be shifted by the demographic criterion "
            f"consuming a positional slot it should not have; got {updated[1]}"
        )

    def test_exclusion_demographic_no_rule_criterion_is_still_enriched(self, service):
        """Regression guard the other direction: the fix above must not
        accidentally also start skipping the exclusion side, which is exactly
        what test_f already pins -- restated here with a following sibling to
        confirm the offset stays correct for exclusion too."""
        demo = _id63_fixture(id_=63)
        following = {
            "id": 64,
            "description": "Elevated LDL",
            "domain": "Measurement",
            "valueConstraint": None,
            "sourceText": "Elevated LDL",
            "conceptSetId": None,
            "conceptSetName": "",
            "isGroupLabel": False,
            "groupId": None,
        }
        concept_sets = [
            {"id": 0, "name": "Target", "expression": {"items": []}},
            {"id": 5, "name": "Pregnancy-related", "expression": {"items": []}},
            {"id": 6, "name": "LDL concept set", "expression": {"items": []}},
        ]
        refs = {service._criterion_mapping_key("exclusion", "63"): 5}

        updated = service._apply_draft_concept_set_metadata(
            [demo, following], concept_sets, 1, {}, "exclusion", refs,
        )

        assert updated[0]["conceptSetId"] == 5
        assert updated[1]["conceptSetId"] == 6


# ---------------------------------------------------------------------------
# (g) -- Criterion.mappable computed_field
# ---------------------------------------------------------------------------


class TestCriterionMappableComputedField:
    def test_g_mappable_true_for_id63_shape(self):
        from src.api.models.tte import Criterion

        crit = Criterion(**_id63_fixture())
        assert crit.mappable is True

    def test_g_mappable_false_for_group_label_id70_shape(self):
        from src.api.models.tte import Criterion

        crit = Criterion(**_id70_fixture())
        assert crit.mappable is False

    def test_g_mappable_false_for_empty_description_regression_guard(self):
        from src.api.models.tte import Criterion

        data = _id63_fixture()
        data["description"] = ""
        data["sourceText"] = ""
        crit = Criterion(**data)
        assert crit.mappable is False


# ---------------------------------------------------------------------------
# HTTP helpers shared by (h) and (i)
# ---------------------------------------------------------------------------


def _create_test_client():
    from src.api.main import create_app
    from testclient_compat import CompatTestClient

    return CompatTestClient(create_app())


def _make_criterion_mapping_metadata(*, query: str = "prior myocardial infarction") -> CriterionMappingMetadata:
    return CriterionMappingMetadata(
        allCandidates=[
            MappingCandidateItem(
                conceptId=4145762,
                conceptName="Pregnant",
                score=0.9,
                source="rag",
                included=True,
            )
        ],
        rerankConfidence=0.85,
        rerankMethod="cross_encoder",
        queryUsed=query,
        selectedConceptIds=[4145762],
    )


# ---------------------------------------------------------------------------
# (h) -- POST re-recommend must return 200 (not 400) for the id=63 shape.
# ---------------------------------------------------------------------------


@_skip_http
class TestReRecommendAllowsDemographicNoRuleFallthrough:
    def test_h_returns_200_not_400_for_id63_shape(self) -> None:
        study = {
            "id": 1,
            "name": "Study 1",
            "eligibility": {
                "inclusionCriteria": [],
                "exclusionCriteria": [_id63_fixture()],
            },
        }
        meta = _make_criterion_mapping_metadata()

        mock_service = MagicMock()
        mock_service.get_study.return_value = study
        mock_service.run_mapping_pipeline_for_query.return_value = meta

        client = _create_test_client()

        with patch("src.api.tte.get_tte_service", return_value=mock_service):
            response = client.post(
                "/tte/studies/1/criteria/63/re-recommend",
                json={"hint": ""},
            )

        assert response.status_code == 200, response.json()


# ---------------------------------------------------------------------------
# (i) -- GET mapping-candidates legacy fallback: the id=63 shape must now be
# included in the legacy mappable_ids list at the correct (shifted) index.
# ---------------------------------------------------------------------------


@_skip_http
class TestGetMappingCandidatesLegacyFallbackIncludesFallthroughCriterion:
    def test_i_id63_shape_included_at_correct_index(self) -> None:
        study = {
            "id": 1,
            "name": "Study 1",
            "eligibility": {
                "inclusionCriteria": [
                    {"id": 100, "domain": "Condition", "description": "T2DM", "isGroupLabel": False},
                ],
                "exclusionCriteria": [_id63_fixture()],
            },
        }
        meta_for_100 = _make_criterion_mapping_metadata(query="T2DM query")
        meta_for_63 = _make_criterion_mapping_metadata(query="Pre-menopausal women query")

        artifact = MagicMock()
        artifact.id = "art-1"
        artifact.kind = "eligibility_processing"
        artifact.payload = {
            "criterionMappingMetadata": {
                "100": meta_for_100.model_dump(),
                "63": meta_for_63.model_dump(),
            }
        }

        mock_service = MagicMock()
        mock_service.list_artifacts.return_value = [artifact]
        mock_service.get_artifact.return_value = artifact
        mock_service.get_study.return_value = study

        client = _create_test_client()

        with patch("src.api.tte.get_tte_service", return_value=mock_service):
            # criterion_id=1 is the 0-based legacy rule index: mappable_ids should
            # now resolve to ["100", "63"] (id=63 no longer excluded), so index 1
            # must resolve to criterion "63"'s metadata, not a 404 or "100"'s.
            response = client.get("/tte/studies/1/criteria/1/mapping-candidates")

        assert response.status_code == 200, response.json()
        data = response.json()
        assert data["queryUsed"] == "Pre-menopausal women query", data
