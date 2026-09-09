"""The domain gate stays binary, and what it cannot judge is reported instead.

``refuse_domain_contradiction`` raises only when EVERY concept in the mapped set is
outside the criterion's own table, so a set whose remaining concepts are all wrong
passes on the strength of one right one. The question was whether to tighten the
predicate. It was measured before it was changed, in both directions.

MEASUREMENT 1 -- how often the gate is near its edge. Over the 552 criterion ->
concept-set references in ``tmp/tte_cold6_20260908/studies.json`` and the 541 in
``output/site_gap/2026-09-08/deliver_20260908/``, the distribution is bimodal:

    549 / 552   100% of concepts readable by the criterion's own table
      3 / 552   <= 33% readable
      0 / 552   0% readable  -- the gate never fires on this corpus
      0 / 552   between 50% and 99%

The three are real defects: an ``Observation`` criterion over a
"Pregnancy/Nursing/Contraception" set whose other concepts are Condition, Procedure
and Measurement, in EMPA-REG and CARMELINA.

MEASUREMENT 2 -- what refusing them would cost. Both are exclusion criteria that
today read 2 of their 6-7 concepts. Refusing removes the pregnancy exclusion
entirely; the corpus contains no case where that is better than a partial exclusion,
and the real repair -- emitting the criterion under the type its concepts live in,
or splitting it -- is a mapping change, not a gate change. So a majority or ratio
threshold would separate the corpus cleanly and still be the wrong action.

MEASUREMENT 3 -- the predicate rejected in audit stays rejected. Skipping
``isExcluded`` items empties ``domains`` for an all-excluded set, and the gate's
early return is ``if not domains or domains & allowed``, so that set would move from
CHECKED to SILENTLY PASSED. It is also unmeasurable here: **0 of the 552 concept
sets in this store carry a single ``isExcluded`` item**, so such a predicate could
only be validated on synthetic data. ``TestTheRejectedIsExcludedPredicateStaysOut``
pins the direction that would silently regress.

Conclusion: the gate is unchanged and the partial readability is reported. Invisible
is what let these ship; refusing them is a worse trade than saying so out loud.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.utils.circe_lint import (
    domain_mismatched_criteria,
    partially_readable_criteria,
    refuse_domain_contradiction,
)


def _concept(concept_id: int, domain: str, name: str, excluded: bool = False) -> dict:
    return {
        "concept": {
            "CONCEPT_ID": concept_id,
            "CONCEPT_NAME": name,
            "DOMAIN_ID": domain,
            "VOCABULARY_ID": "SNOMED",
        },
        "isExcluded": excluded,
        "includeDescendants": True,
        "includeMapped": False,
    }


# Transcribed from tmp/tte_cold6_20260908/studies.json, study 9 (CARMELINA).
PREGNANCY_SET = {
    "id": 4,
    "name": "Pregnancy/Nursing/Uncontrolled Contraception",
    "expression": {
        "items": [
            _concept(1617132, "Observation", "Do you want to talk about contraception"),
            _concept(4011629, "Observation", "Contraception failure"),
            _concept(4059985, "Condition", "Unplanned pregnancy unknown if child is wanted"),
            _concept(4060237, "Condition", "Pregnancy unplanned but wanted"),
            _concept(4061785, "Condition", "Pregnancy unplanned and unwanted"),
            _concept(4250598, "Procedure", "Contraception care management"),
            _concept(36203530, "Measurement", "Mother attended a family planning clinic"),
        ]
    },
}


def _expression(concept_set: dict[str, Any], criteria_type: str) -> dict[str, Any]:
    return {
        "ConceptSets": [concept_set],
        "PrimaryCriteria": {
            "CriteriaList": [{"DrugEra": {"CodesetId": 99}}],
            "ObservationWindow": {"PriorDays": 365, "PostDays": 0},
            "PrimaryCriteriaLimit": {"Type": "First"},
        },
        "InclusionRules": [
            {
                "name": "Pregnancy or nursing",
                "expression": {
                    "Type": "ALL",
                    "CriteriaList": [
                        {
                            "Criteria": {
                                criteria_type: {"CodesetId": concept_set["id"]}
                            },
                            "Occurrence": {"Type": 0, "Count": 0},
                        }
                    ],
                    "DemographicCriteriaList": [],
                    "Groups": [],
                },
            }
        ],
        "CensoringCriteria": [],
    }


class TestTheGateStaysBinary:
    def test_should_not_refuse_a_criterion_that_reads_two_of_seven_concepts(self):
        """Refusing deletes a partially working exclusion; nothing measured says to."""
        refuse_domain_contradiction("Observation", PREGNANCY_SET, "Pregnancy/Nursing")

    def test_should_still_refuse_a_criterion_that_reads_none_of_its_concepts(self):
        drug_only = {
            "id": 27,
            "name": "Glimepiride",
            "expression": {"items": [_concept(1597756, "Drug", "glimepiride")]},
        }
        with pytest.raises(ValueError):
            refuse_domain_contradiction("ConditionOccurrence", drug_only, "Glimepiride")

    def test_should_not_flag_the_mixed_set_in_the_delivery_gate_either(self):
        assert domain_mismatched_criteria(_expression(PREGNANCY_SET, "Observation")) == []


class TestTheRejectedIsExcludedPredicateStaysOut:
    """An all-excluded set must stay CHECKED, never silently passed."""

    def test_should_still_refuse_when_every_out_of_domain_item_is_excluded(self):
        all_excluded = {
            "id": 27,
            "name": "Glimepiride",
            "expression": {
                "items": [_concept(1597756, "Drug", "glimepiride", excluded=True)]
            },
        }
        with pytest.raises(ValueError):
            refuse_domain_contradiction(
                "ConditionOccurrence", all_excluded, "Glimepiride"
            )

    def test_should_still_flag_an_all_excluded_set_in_the_delivery_gate(self):
        all_excluded = {
            "id": 27,
            "name": "Glimepiride",
            "expression": {
                "items": [_concept(1597756, "Drug", "glimepiride", excluded=True)]
            },
        }
        assert (
            domain_mismatched_criteria(_expression(all_excluded, "ConditionOccurrence"))
            != []
        )


class TestPartialReadabilityIsReported:
    def test_should_report_how_many_concepts_the_criterion_can_read(self):
        findings = partially_readable_criteria(_expression(PREGNANCY_SET, "Observation"))

        assert len(findings) == 1
        finding = findings[0]
        assert "Pregnancy or nursing" in finding
        assert "Observation" in finding
        assert "2 of 7" in finding
        assert "Condition" in finding

    def test_should_report_nothing_when_every_concept_is_readable(self):
        measurement_set = {
            "id": 5,
            "name": "HbA1c",
            "expression": {
                "items": [
                    _concept(3004410, "Measurement", "Hemoglobin A1c"),
                    _concept(3005673, "Measurement", "Hemoglobin A1c/Hemoglobin.total"),
                ]
            },
        }
        assert partially_readable_criteria(_expression(measurement_set, "Measurement")) == []

    def test_should_report_nothing_when_no_concept_is_readable(self):
        """That case is the binary gate's, and reporting it twice is noise."""
        drug_only = {
            "id": 27,
            "name": "Glimepiride",
            "expression": {"items": [_concept(1597756, "Drug", "glimepiride")]},
        }
        assert partially_readable_criteria(_expression(drug_only, "ConditionOccurrence")) == []

    def test_should_count_a_compound_domain_as_readable_by_both_its_tables(self):
        compound = {
            "id": 6,
            "name": "Mixed",
            "expression": {
                "items": [
                    _concept(1, "Condition/Meas", "compound"),
                    _concept(2, "Measurement", "plain"),
                ]
            },
        }
        assert partially_readable_criteria(_expression(compound, "Measurement")) == []

    def test_should_stay_silent_on_an_unmodelled_criteria_type(self):
        assert (
            partially_readable_criteria(_expression(PREGNANCY_SET, "PayerPlanPeriod"))
            == []
        )


class TestTheReportReachesAnEmittedExpression:
    def test_should_log_partial_readability_when_an_expression_is_emitted(self, caplog):
        import logging

        from src.services.tte_service import TTEService

        expression = _expression(PREGNANCY_SET, "Observation")
        with caplog.at_level(logging.WARNING):
            TTEService._build_emittable_expression(lambda: expression)

        assert any(
            "2 of 7" in record.getMessage() for record in caplog.records
        ), "the partial readability was invisible, which is how two of these shipped"
