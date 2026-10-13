"""SPEC-INFRA-004 AC-009 / AC-012, after the entity-text collapse was removed (2026-10-14).

The generalized collapse dropped, before mapping, every row whose ``(domain, sourceText, window,
valueConstraint, logicType)`` equalled an earlier row's -- a decision on entity text
(`restated_distinctness.py` records what it dropped and why it went). These cases now reach the
mapper, and a restatement is collapsed on what its rule SELECTS, after mapping
(`restated_rules.collapse_redundant_inclusion_rules`, recorded under ``_restatedRuleCollapse``).

Two properties are still load-bearing and neither is visible from a pure module:

**The census identity still holds.** `_generationCensus` asserts
``total == mapped + unmapped + demographicRules + skipped``.

**The Demographics path is unchanged.** CARMELINA's pregnancy pair is constraint-free
Demographics with empty `sourceText`; SPEC-INFRA-003's cardinality collapse still drops the
second before mapping, and nothing else drops anything here.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.services.restated_demographics import COLLAPSE_REASON as DEMOGRAPHICS_REASON
from src.services.restated_distinctness import COLLAPSE_REASON as DISTINCTNESS_REASON
from src.services.restated_rules import IDENTICAL_REASON
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
    concept_ids: dict[tuple[str, str], int] = {}

    def fake_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
        if seed_text.strip() == "empagliflozin":
            return _stub_concept_set("empagliflozin", 1594973, "Drug")
        # Answer in the domain the criterion asked about: a Condition set for a
        # `Measurement` criterion is the shape `_refuse_domain_contradiction` refuses to
        # build. One concept per distinct request, so two analytes select two things and a
        # restatement selects what its original does -- what the criterion cache gives.
        domain = kwargs.get("expected_domain") or "Condition"
        concept_id = concept_ids.setdefault((seed_text.strip(), domain), 201826 + len(concept_ids))
        return _stub_concept_set(seed_text.strip(), concept_id, domain)

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
# The ratio in its field: "x ULN" in `unitText` alone is not read as one since A21 was
# deleted (RFC-016 step 3).
_ULN = {"op": "gt", "value": 3.0, "unitText": "x ULN", "referenceBound": "uln"}
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


class TestNothingIsDroppedOnEntityText:
    def test_should_carry_neither_generalized_key_when_the_build_runs(self):
        """`_restatedDistinctnessCollapse` and `_restatedIntactGroups` reported the removed
        collapse; a file built now carries neither, so no reader takes an empty list for a
        collapse that ran and found nothing."""
        circe = service_build(_eligibility(exclusion=CAROLINA_ALCOHOL + EMPA_REG_LIVER))
        assert "_restatedDistinctnessCollapse" not in circe
        assert "_restatedIntactGroups" not in circe
        assert DISTINCTNESS_REASON not in circe["_generationCensus"]["skippedByReason"]

    @pytest.mark.parametrize(
        "exclusion,mapped",
        [(CAROLINA_ALCOHOL, 2), (EMPA_REG_LIVER, 6), (EMPA_REG_CARDIOVASCULAR, 3)],
    )
    def test_should_map_every_row_when_rows_share_entity_text(self, exclusion, mapped):
        circe = service_build(_eligibility(exclusion=exclusion))
        assert circe["_generationCensus"]["mapped"] == mapped
        assert circe["_generationCensus"]["skipped"] == 0


class TestARestatementIsCollapsedOnWhatItSelects:
    def test_should_collapse_the_alcohol_rule_that_selects_what_the_first_does(self):
        circe = service_build(_eligibility(exclusion=CAROLINA_ALCOHOL))
        (record,) = circe["_restatedRuleCollapse"]
        assert record["reason"] == IDENTICAL_REASON
        assert record["criterionKeys"] == ["exclusion:49"]
        assert record["survivorCriterionKeys"] == ["exclusion:5"]
        assert len(circe["InclusionRules"]) == 1

    def test_should_leave_one_rule_per_analyte_in_the_six_member_liver_group(self):
        """AC-006 end to end, now on what the rules select: six rows, three analytes, each
        stated twice. Three rules remain and the three restatements are recorded."""
        circe = service_build(_eligibility(exclusion=EMPA_REG_LIVER))
        assert len(circe["InclusionRules"]) == 3
        assert sorted(k for r in circe["_restatedRuleCollapse"] for k in r["criterionKeys"]) == [
            "exclusion:47", "exclusion:48", "exclusion:49",
        ]

    def test_should_leave_the_category_two_cluster_fully_emitted(self):
        """Three distinct entities under one description: three rules, nothing collapsed."""
        circe = service_build(_eligibility(exclusion=EMPA_REG_CARDIOVASCULAR))
        assert len(circe["InclusionRules"]) == 3
        assert circe["_restatedRuleCollapse"] == []


class TestTheCensusStillBalances:
    """AC-012. A criterion that went in and is in no bucket on the way out breaks this."""

    @pytest.mark.parametrize(
        "exclusion,total,skipped",
        [
            (CAROLINA_ALCOHOL, 2, 0),
            (EMPA_REG_LIVER, 6, 0),
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

    def test_should_record_the_drop_under_the_demographics_reason_not_the_generalized_one(self):
        circe = service_build(_eligibility(exclusion=CARMELINA_PREGNANCY))
        (dropped,) = [r for r in circe["_skippedCriteria"] if r["criterionId"] == "23"]
        assert dropped["reason"] == DEMOGRAPHICS_REASON


class TestOnlyTheDemographicsPathDropsBeforeMapping:
    def test_should_drop_only_the_demographics_restatement_on_a_mixed_role(self):
        """Both shapes in one role: the Demographics pair and the alcohol pair. Only the
        Demographics path drops before mapping; the alcohol restatement is collapsed on
        what its rule selects."""
        circe = service_build(_eligibility(exclusion=CARMELINA_PREGNANCY + CAROLINA_ALCOHOL))
        by_reason = {r["criterionId"]: r["reason"] for r in circe["_skippedCriteria"]}
        assert by_reason == {"23": DEMOGRAPHICS_REASON}
        assert [r["criterionKeys"] for r in circe["_restatedRuleCollapse"]] == [["exclusion:49"]]


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
        assert circe["_restatedRuleCollapse"] == []
        assert circe["_generationCensus"]["mapped"] == 3
        assert circe["_generationCensus"]["skipped"] == 0


service_build = None


@pytest.fixture(autouse=True)
def _bind_service_build(service):
    global service_build
    service_build = service._build_seeded_target_circe
    yield
    service_build = None
