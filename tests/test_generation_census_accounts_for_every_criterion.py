"""Every criterion that goes in must be accounted for on the way out.

`_unmappedCriteria` (tests/test_unmapped_criteria_are_recorded.py) closed one leak:
a criterion whose mapping *raised*. It cannot close the others, because they happen
before the mapper is ever called. `_build_seeded_target_circe` drops a criterion
silently in three more places:

    for criterion in inc_criteria:
        if domain in DEMOGRAPHIC_DOMAINS:
            demo = self._build_demographic_rule(criterion)
            if demo: ...                      # else: gone, nothing recorded
            continue
        if criterion.get("isGroupLabel"):
            continue                          # gone, nothing recorded

    for criterion in exc_criteria:
        if domain in DEMOGRAPHIC_DOMAINS:
            continue                          # gone -- not even attempted
        if criterion.get("isGroupLabel"):
            continue                          # gone, nothing recorded

The third one is the sharp edge: an exclusion in a demographic domain is discarded
without `_build_demographic_rule` ever being asked whether it could have been built.
On the scored store those are lines like "Nursing or pregnant" and "Pre-menopausal
women" -- real exclusions whose loss widens the cohort past the protocol, which is
the exact failure `_unmappedCriteria` was written to make visible.

Counting these by hand has produced a different answer every time somebody tried
(39/9, then 73, now 82), because the categories overlap: a criterion can be both
`isGroupLabel` and demographic, and which bucket it lands in depends on branch order,
not on the criterion. So the count belongs in the artifact, emitted by the same branch
that does the dropping.

`_generationCensus` carries the balance identity

    total == mapped + unmapped + demographicRules + skipped

which is what makes this a gate rather than a report: add a fourth `continue` without
recording it and the identity breaks in `test_should_balance_the_census_*`.
"""
from __future__ import annotations

from typing import Any

import pytest

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


UNMAPPABLE = "qqzzxx nonexistent clinical term"


@pytest.fixture
def service(monkeypatch) -> TTEService:
    """A service whose mapper resolves everything except UNMAPPABLE."""
    svc = TTEService.__new__(TTEService)

    def fake_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
        if seed_text.strip() == UNMAPPABLE:
            raise ValueError(f"No concept mapping found for '{seed_text}'")
        if seed_text.strip() == "empagliflozin":
            return _stub_concept_set("empagliflozin", 1594973, "Drug")
        return _stub_concept_set(seed_text.strip(), 201826)

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


class TestSkippedCriteriaAreRecorded:
    def test_should_report_empty_skips_when_every_criterion_reaches_the_mapper(self, service):
        """The key is always present, so its absence cannot be read as 'nothing skipped'."""
        circe = service._build_seeded_target_circe(
            _eligibility(
                inclusion=[{"id": "inc-1", "domain": "Condition", "sourceText": "Type 2 diabetes"}],
            )
        )
        assert circe.get("_skippedCriteria") == []

    def test_should_record_the_group_label_when_it_is_skipped(self, service):
        circe = service._build_seeded_target_circe(
            _eligibility(
                inclusion=[
                    {
                        "id": "inc-hdr",
                        "domain": "Condition",
                        "sourceText": "Cardiovascular history (OR group)",
                        "isGroupLabel": True,
                    },
                ],
            )
        )
        skipped = circe["_skippedCriteria"]
        assert len(skipped) == 1
        assert skipped[0]["criterionId"] == "inc-hdr"
        assert skipped[0]["role"] == "inclusion"
        assert skipped[0]["reason"] == "group-label"
        assert "Cardiovascular history" in skipped[0]["label"]

    def test_should_record_the_demographic_when_no_rule_can_be_built(self, service):
        """`Age >= 50` as prose with no valueConstraint yields no CIRCE rule."""
        circe = service._build_seeded_target_circe(
            _eligibility(
                inclusion=[{"id": "inc-age", "domain": "Demographics", "sourceText": "Age >= 50"}],
            )
        )
        skipped = circe["_skippedCriteria"]
        assert len(skipped) == 1
        assert skipped[0]["criterionId"] == "inc-age"
        assert skipped[0]["reason"] == "demographic-no-rule"
        assert skipped[0]["domain"] == "Demographics"

    def test_should_not_record_the_demographic_that_did_produce_a_rule(self, service):
        circe = service._build_seeded_target_circe(
            _eligibility(
                inclusion=[
                    {
                        "id": "inc-age",
                        "domain": "Demographics",
                        "description": "Age >= 50",
                        "valueConstraint": {"op": "gte", "value": 50},
                    }
                ],
            )
        )
        assert circe["_skippedCriteria"] == []
        assert circe["_generationCensus"]["demographicRules"] == 1

    def test_should_record_the_exclusion_demographic_eq_as_unsupported(self, service):
        """`eq` has no single-op inversion in CIRCE's Age/NumericRange Op enum.

        Every other op (gt/gte/lt/lte) is now buildable under exclusion via operator
        inversion; `eq` is the one legitimately unsupported case, and must be recorded
        under its own reason rather than the generic "demographic-no-rule".
        """
        circe = service._build_seeded_target_circe(
            _eligibility(
                exclusion=[
                    {
                        "id": "exc-preg",
                        "domain": "Demographics",
                        "sourceText": "Nursing or pregnant",
                        "valueConstraint": {"op": "eq", "value": 1},
                    }
                ],
            )
        )
        skipped = circe["_skippedCriteria"]
        assert len(skipped) == 1
        assert skipped[0]["criterionId"] == "exc-preg"
        assert skipped[0]["role"] == "exclusion"
        assert skipped[0]["reason"] == "exclusion-demographic-eq-unsupported"
        assert "Nursing or pregnant" in skipped[0]["label"]

    def test_should_build_the_exclusion_demographic_when_a_rule_can_be_built(self, service):
        """The exclusion loop must give `_build_demographic_rule` the same chance
        the inclusion loop gives it, instead of discarding unconditionally.

        A buildable op ("gt") with a valueConstraint must produce a demographic
        rule and must NOT be recorded as skipped.
        """
        circe = service._build_seeded_target_circe(
            _eligibility(
                exclusion=[
                    {
                        "id": "exc-age",
                        "domain": "Demographics",
                        "description": "Age > 65",
                        "valueConstraint": {"op": "gt", "value": 65},
                    }
                ],
            )
        )
        assert circe["_skippedCriteria"] == []
        assert circe["_generationCensus"]["demographicRules"] == 1

    def test_should_classify_by_branch_order_when_a_criterion_is_both_shapes(self, service):
        """Demographic wins over `isGroupLabel` because its branch runs first.

        Four criteria on the scored store are both. Recording `isGroupLabel` alongside
        the reason keeps that overlap visible instead of making the bucket look pure.
        """
        circe = service._build_seeded_target_circe(
            _eligibility(
                inclusion=[
                    {
                        "id": "inc-both",
                        "domain": "Demographics",
                        "sourceText": "Age >= 60 with prior CVD criteria",
                        "isGroupLabel": True,
                    }
                ],
            )
        )
        skipped = circe["_skippedCriteria"]
        assert len(skipped) == 1
        assert skipped[0]["reason"] == "demographic-no-rule"
        assert skipped[0]["isGroupLabel"] is True


class TestGenerationCensusBalances:
    def test_should_report_a_census_when_nothing_is_dropped(self, service):
        circe = service._build_seeded_target_circe(
            _eligibility(
                inclusion=[{"id": "inc-1", "domain": "Condition", "sourceText": "Type 2 diabetes"}],
                exclusion=[{"id": "exc-1", "domain": "Condition", "sourceText": "Heart failure"}],
            )
        )
        census = circe["_generationCensus"]
        assert census["total"] == 2
        assert census["mapped"] == 2
        assert census["unmapped"] == 0
        assert census["skipped"] == 0
        assert census["demographicRules"] == 0

    def test_should_balance_the_census_when_every_drop_shape_is_present(self, service):
        """The gate. A new silent `continue` breaks this identity.

        One of each: mapped, unmapped (mapper raises), demographic rule, demographic
        with no rule, inclusion group label, exclusion group label, exclusion
        demographic with the unsupported "eq" op.
        """
        circe = service._build_seeded_target_circe(
            _eligibility(
                inclusion=[
                    {"id": "i1", "domain": "Condition", "sourceText": "Type 2 diabetes"},
                    {"id": "i2", "domain": "Condition", "sourceText": UNMAPPABLE},
                    {
                        "id": "i3",
                        "domain": "Demographics",
                        "description": "Age >= 50",
                        "valueConstraint": {"op": "gte", "value": 50},
                    },
                    {"id": "i4", "domain": "Demographics", "sourceText": "Age, unspecified"},
                    {
                        "id": "i5",
                        "domain": "Condition",
                        "sourceText": "CV group",
                        "isGroupLabel": True,
                    },
                ],
                exclusion=[
                    {"id": "e1", "domain": "Condition", "sourceText": "Heart failure"},
                    {
                        "id": "e2",
                        "domain": "Condition",
                        "sourceText": "Renal group",
                        "isGroupLabel": True,
                    },
                    {
                        "id": "e3",
                        "domain": "Demographics",
                        "sourceText": "Pre-menopausal women",
                        "valueConstraint": {"op": "eq", "value": 1},
                    },
                ],
            )
        )
        census = circe["_generationCensus"]
        assert census["total"] == 8
        assert census["mapped"] == 2  # i1, e1
        assert census["unmapped"] == 1  # i2
        assert census["demographicRules"] == 1  # i3
        assert census["skipped"] == 4  # i4, i5, e2, e3
        assert census["total"] == (
            census["mapped"] + census["unmapped"] + census["demographicRules"] + census["skipped"]
        ), "a criterion went in and is in no bucket on the way out"

    def test_should_break_down_the_skips_by_reason(self, service):
        circe = service._build_seeded_target_circe(
            _eligibility(
                inclusion=[
                    {"id": "i4", "domain": "Demographics", "sourceText": "Age, unspecified"},
                    {
                        "id": "i5",
                        "domain": "Condition",
                        "sourceText": "CV group",
                        "isGroupLabel": True,
                    },
                ],
                exclusion=[
                    {
                        "id": "e2",
                        "domain": "Condition",
                        "sourceText": "Renal group",
                        "isGroupLabel": True,
                    },
                    {
                        "id": "e3",
                        "domain": "Demographics",
                        "sourceText": "Pre-menopausal women",
                        "valueConstraint": {"op": "eq", "value": 1},
                    },
                ],
            )
        )
        by_reason = circe["_generationCensus"]["skippedByReason"]
        assert by_reason == {
            "demographic-no-rule": 1,
            "group-label": 2,
            "exclusion-demographic-eq-unsupported": 1,
        }
        assert sum(by_reason.values()) == circe["_generationCensus"]["skipped"]
        assert sum(by_reason.values()) == len(circe["_skippedCriteria"])

    def test_should_count_the_unmapped_criterion_the_census_and_the_list_alike(self, service):
        """`_unmappedCriteria` keeps its own contract; the census only reports its length."""
        circe = service._build_seeded_target_circe(
            _eligibility(
                exclusion=[{"id": "exc-1", "domain": "Condition", "sourceText": UNMAPPABLE}],
            )
        )
        assert len(circe["_unmappedCriteria"]) == 1
        assert circe["_generationCensus"]["unmapped"] == 1
        assert circe["_unmappedCriteria"][0]["criterionId"] == "exc-1"
