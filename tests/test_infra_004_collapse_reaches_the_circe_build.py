"""SPEC-INFRA-004 AC-009 / AC-012: the generalized collapse must reach the emitted CIRCE.

`restated_distinctness.py` decides *what* to drop. This is the wiring that makes the decision
count: the dropped criteria must never reach the mapper, so the cohort stops being filtered on
the union of their divergent concept sets.

Two properties are load-bearing here and neither is visible from the pure module:

**The census identity still holds.** `_generationCensus` asserts
``total == mapped + unmapped + demographicRules + skipped``. A new drop branch that does not
record itself breaks that identity, which is why the drop routes through `_record_skip` rather
than a bare `continue`, and why each path records its own reason rather than sharing one.

**The two paths still do not contend.** AC-009 is the REQ-008 hinge and deliberately the one
case where they meet: CARMELINA's pregnancy pair is empty-`sourceText`, so REQ-004 withholds
the generalized signal and the Demographics path must therefore still be the thing that
collapses it. If that pair collapses because the *generalized* signal reached it, REQ-004 has
been violated.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.services.restated_demographics import COLLAPSE_REASON as DEMOGRAPHICS_REASON
from src.services.restated_distinctness import COLLAPSE_REASON as DISTINCTNESS_REASON
from src.services.tte_service import TTEService


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


def _criterion(
    id: str,
    description: str,
    source_text: str,
    *,
    domain: str = "Condition",
    value_constraint: dict[str, Any] | None = None,
    group_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "domain": domain,
        "description": description,
        "sourceText": source_text,
        "valueConstraint": value_constraint,
        "groupId": group_id,
        "isGroupLabel": False,
        "logicType": "ABSENCE",
    }


def _demographic(id: str, description: str) -> dict[str, Any]:
    """The shape `SPEC-INFRA-003` fixes: Demographics carrying none of the four disqualifiers."""
    return _criterion(id, description, "", domain="Demographics")


# CARMELINA's pregnancy pair, as `acceptance.md` AC-009 describes it.
CARMELINA_PREGNANCY = [
    _demographic("14", "Pregnancy/Nursing/Uncontrolled Contraception"),
    _demographic("23", "Pregnancy/Nursing/Uncontrolled Contraception (Exclusion)"),
]

# CAROLINA's alcohol pair: byte-identical `sourceText`, no constraint, different groups.
CAROLINA_ALCOHOL = [
    _criterion("5", "Alcohol Use Disorder", "Alcohol Use Disorder", group_id="c8c4cfc2"),
    _criterion("49", "Alcohol Use Disorder", "Alcohol Use Disorder", group_id="ade8ea06"),
]

# EMPA-REG's liver group: six criteria, three analytes, each emitted twice.
_ULN = {"op": "gt", "value": 3.0, "unitText": "x ULN"}
EMPA_REG_LIVER = [
    _criterion(str(i), "Liver disease (ALT/AST/ALP > 3x ULN)", analyte, domain="Measurement",
               value_constraint=_ULN)
    for i, analyte in zip(
        range(44, 50),
        [
            "Alanine aminotransferase",
            "Aspartate aminotransferase",
            "Alkaline phosphatase",
            "Alanine aminotransferase",
            "Aspartate aminotransferase",
            "Alkaline phosphatase",
        ],
    )
]

# EMPA-REG's Category 2 cluster: one description, three distinct entities.
EMPA_REG_CARDIOVASCULAR = [
    _criterion("13", "Cardiovascular Disease", "Hypertension"),
    _criterion("14", "Cardiovascular Disease", "Myocardial Infarction"),
    _criterion("15", "Cardiovascular Disease", "Heart Failure"),
]


class TestTheGeneralizedCollapseIsEmitted:
    def test_should_always_carry_both_keys_even_when_nothing_collapses(self):
        """Present-and-empty, matching every sibling key. An absent key would be
        indistinguishable from a clean run on an artifact built before this shipped."""
        circe = service_build(
            _eligibility(inclusion=[_criterion("i1", "T2DM", "Type 2 diabetes mellitus")])
        )
        assert circe.get("_restatedDistinctnessCollapse") == []
        assert circe.get("_restatedIntactGroups") == []

    def test_should_record_the_collapse_for_the_alcohol_pair(self):
        circe = service_build(_eligibility(exclusion=CAROLINA_ALCOHOL))
        (record,) = circe["_restatedDistinctnessCollapse"]
        assert record["role"] == "exclusion"
        assert record["stem"] == "Alcohol Use Disorder"
        assert record["survivorId"] == "5"
        assert record["droppedIds"] == ["49"]
        assert record["survivorRule"] == "first-in-document-order"

    def test_should_report_an_intact_category_two_cluster_rather_than_omitting_it(self):
        circe = service_build(_eligibility(exclusion=EMPA_REG_CARDIOVASCULAR))
        assert circe["_restatedDistinctnessCollapse"] == []
        (group,) = circe["_restatedIntactGroups"]
        assert group["stem"] == "Cardiovascular Disease"
        assert group["reason"] == "key-distinct"
        assert len(group["classes"]) == 3


class TestTheDroppedCriteriaNeverReachTheMapper:
    def test_should_emit_one_concept_set_where_two_restatements_went_in(self):
        circe = service_build(_eligibility(exclusion=CAROLINA_ALCOHOL))
        assert circe["_generationCensus"]["mapped"] == 1

    def test_should_keep_the_survivor_mapped_rather_than_dropping_both(self):
        circe = service_build(_eligibility(exclusion=CAROLINA_ALCOHOL))
        assert any("5" in str(k) for k in circe["_criterionConceptSetRefs"])

    def test_should_emit_three_concept_sets_for_the_six_member_liver_group(self):
        """AC-006 end to end. Six is the unfixed defect; one would destroy two analytes."""
        circe = service_build(_eligibility(exclusion=EMPA_REG_LIVER))
        assert circe["_generationCensus"]["mapped"] == 3
        assert circe["_generationCensus"]["skipped"] == 3
        assert len(circe["_restatedDistinctnessCollapse"]) == 3

    def test_should_leave_the_category_two_cluster_fully_mapped(self):
        """The inverse of the criterion above, and the one that matters more: three distinct
        entities in, three concept sets out, nothing dropped."""
        circe = service_build(_eligibility(exclusion=EMPA_REG_CARDIOVASCULAR))
        assert circe["_generationCensus"]["mapped"] == 3
        assert circe["_generationCensus"]["skipped"] == 0

    def test_should_record_each_dropped_criterion_under_the_generalized_reason(self):
        circe = service_build(_eligibility(exclusion=CAROLINA_ALCOHOL))
        dropped = [r for r in circe["_skippedCriteria"] if r["reason"] == DISTINCTNESS_REASON]
        assert {r["criterionId"] for r in dropped} == {"49"}


class TestTheCensusStillBalances:
    """AC-012. The gate: a drop that skipped `_record_skip` breaks this identity."""

    @pytest.mark.parametrize(
        "exclusion,total,skipped",
        [
            (CAROLINA_ALCOHOL, 2, 1),
            (EMPA_REG_LIVER, 6, 3),
            (EMPA_REG_CARDIOVASCULAR, 3, 0),
            (CARMELINA_PREGNANCY, 2, 1),
        ],
    )
    def test_should_account_for_every_criterion_on_the_way_out(self, exclusion, total, skipped):
        census = service_build(_eligibility(exclusion=exclusion))["_generationCensus"]
        assert census["total"] == total
        assert census["skipped"] == skipped
        assert census["total"] == (
            census["mapped"] + census["unmapped"] + census["demographicRules"] + census["skipped"]
        ), "a criterion went in and is in no bucket on the way out"

    def test_should_count_the_new_reason_in_the_breakdown(self):
        census = service_build(_eligibility(exclusion=EMPA_REG_LIVER))["_generationCensus"]
        assert census["skippedByReason"][DISTINCTNESS_REASON] == 3
        assert sum(census["skippedByReason"].values()) == census["skipped"]


class TestTheDemographicsCollapseIsUnchanged:
    """AC-009 — the REQ-008 hinge."""

    def test_should_still_collapse_the_carmelina_pregnancy_pair(self):
        circe = service_build(_eligibility(exclusion=CARMELINA_PREGNANCY))
        (record,) = circe["_restatedDemographicsCollapse"]
        assert record["role"] == "exclusion"
        assert record["survivorId"] == "14"
        assert record["droppedIds"] == ["23"]
        assert record["survivorRule"] == "first-in-document-order"
        assert record["reason"] == DEMOGRAPHICS_REASON

    def test_should_not_let_the_generalized_signal_be_what_collapsed_it(self):
        """If this pair collapses because the generalized signal reached it, REQ-004 has been
        violated — and AC-008 would show it. The generalized list must be empty here."""
        circe = service_build(_eligibility(exclusion=CARMELINA_PREGNANCY))
        assert circe["_restatedDistinctnessCollapse"] == []

    def test_should_record_the_drop_under_the_demographics_reason_not_the_generalized_one(self):
        circe = service_build(_eligibility(exclusion=CARMELINA_PREGNANCY))
        (dropped,) = [r for r in circe["_skippedCriteria"] if r["criterionId"] == "23"]
        assert dropped["reason"] == DEMOGRAPHICS_REASON

    def test_should_report_the_pair_as_demographics_path_territory(self):
        """REQ-011's reporting still names the group, so a reader sees it was routed rather
        than missed."""
        circe = service_build(_eligibility(exclusion=CARMELINA_PREGNANCY))
        (group,) = circe["_restatedIntactGroups"]
        assert group["reason"] == "demographics-path"
        assert group["consideredIds"] == []


class TestTheTwoPathsNeverBothDropOneCriterion:
    def test_should_produce_disjoint_drop_sets_on_a_mixed_role(self):
        """Both shapes in one role: the Demographics pair and the alcohol pair. Each path
        claims its own, and no criterion is recorded as skipped twice."""
        circe = service_build(_eligibility(exclusion=CARMELINA_PREGNANCY + CAROLINA_ALCOHOL))
        skipped = circe["_skippedCriteria"]
        assert len(skipped) == len({r["criterionId"] for r in skipped})
        by_reason = {r["criterionId"]: r["reason"] for r in skipped}
        assert by_reason == {"23": DEMOGRAPHICS_REASON, "49": DISTINCTNESS_REASON}


class TestSpecInfra003AC004IsNotBrokenByTheWiring:
    def test_should_leave_a_distinct_analyte_triple_fully_mapped(self):
        """`SPEC-INFRA-003` `AC-004`, restated as REQ-009 and now inside this SPEC's fix
        scope for the first time: three analytes in, three concept sets out."""
        triple = [
            _criterion(str(i), desc, analyte, domain="Measurement", value_constraint=_ULN)
            for i, desc, analyte in (
                (1, "Active Liver Disease", "Alanine aminotransferase"),
                (2, "Active Liver Disease (AST)", "Aspartate aminotransferase"),
                (3, "Active Liver Disease (AP)", "Alkaline phosphatase"),
            )
        ]
        circe = service_build(_eligibility(exclusion=triple))
        assert circe["_restatedDistinctnessCollapse"] == []
        assert circe["_generationCensus"]["mapped"] == 3
        assert circe["_generationCensus"]["skipped"] == 0


service_build = None


@pytest.fixture(autouse=True)
def _bind_service_build(service):
    global service_build
    service_build = service._build_seeded_target_circe
    yield
    service_build = None
