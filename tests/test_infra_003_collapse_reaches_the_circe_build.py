"""SPEC-INFRA-003 REQ-007: the collapse must reach the emitted CIRCE, not just a report.

`restated_demographics.py` decides *what* to drop. This is the wiring that makes the
decision count: the dropped criteria must never reach the mapper, so the cohort stops
being filtered on the union of their divergent concept sets (`spec.md` §2.2, measured:
CARMELINA's three pregnancy restatements resolve to 7 / 4 / 7 concepts with pairwise
Jaccard 0.00-0.75 and a union of 11).

Two properties are load-bearing here and neither is visible from the pure module:

**The census identity still holds.** `_generationCensus` asserts
``total == mapped + unmapped + demographicRules + skipped``, and
`tests/test_generation_census_accounts_for_every_criterion.py` is the gate on it. A new
drop branch that does not record itself breaks that identity, which is the whole reason
the drop routes through `_record_skip` rather than a bare `continue`.

**The survivor is still mapped.** Collapsing is only a fix if exactly one concept set
survives; dropping all N would be a different defect wearing the same shape.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.services.tte_service import TTEService
from src.utils.circe_lint import CRITERION_CONCEPT_SET_REFS_KEY


def _stub_concept_set(name: str, concept_id: int, domain: str = "Condition") -> dict[str, Any]:
    return {
        "name": name,
        "domain": domain,
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": concept_id,
                        "CONCEPT_NAME": name,
                        "CONCEPT_CODE": str(concept_id),
                        "DOMAIN_ID": domain,
                        "VOCABULARY_ID": "SNOMED",
                        "CONCEPT_CLASS_ID": "Clinical Finding",
                    },
                    "includeDescendants": True,
                    "isExcluded": False,
                }
            ]
        },
        "mapping_metadata": None,
    }


@pytest.fixture
def service(monkeypatch) -> TTEService:
    svc = TTEService.__new__(TTEService)

    def fake_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
        if seed_text.strip() == "empagliflozin":
            return _stub_concept_set("empagliflozin", 1594973, "Drug")
        # Answer in the domain the criterion asked about. These tests are about the
        # collapse reaching the CIRCE build, not about domains, and the stub used to
        # return a Condition concept for every seed -- so a `Measurement` criterion such
        # as "Alanine aminotransferase" came back as a Condition set. That is the exact
        # shape `circe_lint.domain_mismatched_criteria` refuses to deliver and that
        # `_refuse_domain_contradiction` now refuses to build, so the stub was standing
        # in for an answer the pipeline would never accept.
        return _stub_concept_set(
            seed_text.strip(), 201826, kwargs.get("expected_domain") or "Condition"
        )

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
    return svc


def _eligibility(
    inclusion: list[dict[str, Any]] | None = None,
    exclusion: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "targetCohortName": "empagliflozin",
        "inclusionCriteria": inclusion or [],
        "exclusionCriteria": exclusion or [],
    }


def _demographic(id: str, description: str) -> dict[str, Any]:
    """A Demographics criterion carrying none of the four disqualifiers."""
    return {
        "id": id,
        "domain": "Demographics",
        "description": description,
        "sourceText": "",
        "valueConstraint": None,
        "groupId": None,
        "isGroupLabel": False,
        "logicType": "ABSENCE",
    }


# CARMELINA exclusion #10, as the reference store emits it (`spec.md` §2.1).
CARMELINA_PREGNANCY = [
    _demographic("11", "Pregnancy/Nursing/Uncontrolled Contraception"),
    _demographic("12", "Pregnancy/Nursing/Uncontrolled Contraception (<= 1 year)"),
    _demographic("18", "Pregnancy/Nursing/Uncontrolled Contraception (General)"),
]


class TestTheCollapseIsEmitted:
    def test_should_always_carry_the_key_even_when_nothing_collapses(self):
        """Present-and-empty, matching `_restatedClusters` and `_skippedCriteria`.

        An absent key would be indistinguishable from a clean run on an artifact built
        before this shipped.
        """
        circe = service_build(
            _eligibility(inclusion=[{"id": "i1", "domain": "Condition", "sourceText": "T2DM"}])
        )
        assert circe.get("_restatedDemographicsCollapse") == []

    def test_should_record_the_collapse_when_three_restatements_are_present(self):
        circe = service_build(_eligibility(exclusion=CARMELINA_PREGNANCY))
        records = circe["_restatedDemographicsCollapse"]
        assert len(records) == 1
        assert records[0]["role"] == "exclusion"
        assert records[0]["survivorId"] == "11"
        assert records[0]["droppedIds"] == ["12", "18"]
        assert records[0]["survivorRule"] == "first-in-document-order"

    def test_should_leave_the_stem_signal_emission_untouched(self):
        """M2's `_restatedClusters` is a separate signal and keeps reporting all three."""
        circe = service_build(_eligibility(exclusion=CARMELINA_PREGNANCY))
        clusters = circe["_restatedClusters"]
        assert len(clusters) == 1
        assert clusters[0]["criterionIds"] == ["11", "12", "18"]


class TestTheDroppedCriteriaNeverReachTheMapper:
    def test_should_emit_one_concept_set_where_three_restatements_went_in(self):
        """REQ-007 / AC-005: the cohort stops filtering on the union."""
        circe = service_build(_eligibility(exclusion=CARMELINA_PREGNANCY))
        assert circe["_generationCensus"]["mapped"] == 1

    def test_should_keep_the_survivor_mapped_rather_than_dropping_all_three(self):
        circe = service_build(_eligibility(exclusion=CARMELINA_PREGNANCY))
        mapped_ids = set(circe[CRITERION_CONCEPT_SET_REFS_KEY])
        assert any("11" in str(k) for k in mapped_ids), mapped_ids

    def test_should_record_each_dropped_criterion_under_its_own_reason(self):
        circe = service_build(_eligibility(exclusion=CARMELINA_PREGNANCY))
        dropped = [
            r for r in circe["_skippedCriteria"]
            if r["reason"] == "restated-demographics-duplicate"
        ]
        assert {r["criterionId"] for r in dropped} == {"12", "18"}
        assert all(r["role"] == "exclusion" for r in dropped)


class TestTheCensusStillBalances:
    def test_should_balance_the_census_across_the_new_drop_branch(self):
        """The gate. A drop that skipped `_record_skip` breaks this identity."""
        circe = service_build(_eligibility(exclusion=CARMELINA_PREGNANCY))
        census = circe["_generationCensus"]
        assert census["total"] == 3
        assert census["skipped"] == 2
        assert census["total"] == (
            census["mapped"] + census["unmapped"] + census["demographicRules"] + census["skipped"]
        ), "a criterion went in and is in no bucket on the way out"

    def test_should_count_the_new_reason_in_the_breakdown(self):
        circe = service_build(_eligibility(exclusion=CARMELINA_PREGNANCY))
        by_reason = circe["_generationCensus"]["skippedByReason"]
        assert by_reason["restated-demographics-duplicate"] == 2
        assert sum(by_reason.values()) == circe["_generationCensus"]["skipped"]


class TestAC004IsNotBrokenByTheWiring:
    def test_should_leave_the_alt_ast_ap_triple_fully_mapped(self):
        """AC-004 end to end: three analytes in, three concept sets out, no collapse."""
        triple = [
            {
                "id": str(i),
                "domain": "Measurement",
                "description": desc,
                "sourceText": desc,
                "valueConstraint": {"op": "gte", "value": 3.0, "unitText": "x ULN"},
                "groupId": None,
                "isGroupLabel": False,
                "logicType": "ABSENCE",
            }
            for i, desc in (
                (1, "Active Liver Disease/Impaired Hepatic Function"),
                (2, "Active Liver Disease/Impaired Hepatic Function (AST)"),
                (3, "Active Liver Disease/Impaired Hepatic Function (AP)"),
            )
        ]
        circe = service_build(_eligibility(exclusion=triple))
        assert circe["_restatedDemographicsCollapse"] == []
        assert circe["_generationCensus"]["mapped"] == 3
        assert circe["_generationCensus"]["skipped"] == 0


# `service_build` is rebound per test by the fixture below; declaring it at module level
# keeps the test bodies free of the fixture-plumbing noise.
service_build = None


@pytest.fixture(autouse=True)
def _bind_service_build(service):
    global service_build
    service_build = service._build_seeded_target_circe
    yield
    service_build = None
