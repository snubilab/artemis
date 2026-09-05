"""A criterion whose domain disagrees with its concept set matches nothing, silently.

CAROLINA ships an ``InclusionRules`` entry named "Glimepiride" whose criterion is
``ConditionOccurrence`` while the concept set it reads holds ``1597756 glimepiride``,
a Drug concept. CIRCE renders that as a join of
``condition_occurrence.condition_concept_id`` against a codeset of drug products, and
that column never holds one, so the rule matches no row at all.

That was reasoned before it was measured. It has now been measured, against WebAPI
2.15.1 / source SYNTHEA (``synthea_cdm``), six cohort definitions each with its own
design hash and "Cache is absent ... Calculating" in the WebAPI log — see
``output/site_gap/2026-09-06/plan048_domain_repair/``:

    entry only, no rule                                     10093 persons
    acetaminophen via DrugExposure          (matching)       3339 persons
    acetaminophen via ConditionOccurrence   (MISMATCHED)        0 persons
    Gingivitis    via ConditionOccurrence   (matching)       5975 persons

The third arm is the defect shape and returns nobody; the fourth is the control that
makes that zero mean something — the same criterion type over a Condition-domain set
returns 5,975 people, so ``ConditionOccurrence`` rules work fine and only the domain
disagreement empties one.

The real rule is an ABSENCE rule (``Occurrence {Type: 0, Count: 0}``), so matching
nothing means everyone satisfies it: the cohort is not emptied, the exclusion is simply
never applied. A rule that silently excludes nobody is exactly what a delivery gate
exists to catch, and no existing check looks at the domain of a criterion's own concept
set.

The fixtures are the real artifacts on disk, read and never modified, so the check is
shown the case that motivated it and not only synthetic data.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from src.utils.circe_lint import domain_mismatched_criteria

ARTEMIS = pathlib.Path(__file__).resolve().parents[1]
EXPORT_DIR = ARTEMIS / "output" / "site_gap" / "2026-09-06" / "reexport_washout_fix"
STORE = ARTEMIS / "tmp" / "tte_six_wiring_fix_20260905" / "studies.json"

MISMATCHED_FILES = [
    EXPORT_DIR / "carolina_treatment.circe.json",
    EXPORT_DIR / "carolina_comparator.circe.json",
]
CLEAN_FILES = [
    EXPORT_DIR / "carmelina_treatment.circe.json",
    EXPORT_DIR / "carmelina_comparator.circe.json",
    EXPORT_DIR / "empa-reg_treatment.circe.json",
    EXPORT_DIR / "empa-reg_comparator.circe.json",
]


def _concept_set(set_id: int, *domains: str) -> dict:
    return {
        "id": set_id,
        "name": f"set {set_id}",
        "expression": {
            "items": [
                {"concept": {"CONCEPT_ID": 100 + i, "DOMAIN_ID": domain}}
                for i, domain in enumerate(domains)
            ]
        },
    }


def _rule(name: str, criteria_type: str, codeset_id: int) -> dict:
    return {
        "name": name,
        "expression": {
            "Type": "ALL",
            "CriteriaList": [
                {
                    "Criteria": {criteria_type: {"CodesetId": codeset_id}},
                    "Occurrence": {"Type": 0, "Count": 0},
                }
            ],
            "DemographicCriteriaList": [],
            "Groups": [],
        },
    }


class TestTheCheckFiresOnTheRealBrokenArtifact:
    @pytest.mark.parametrize("path", MISMATCHED_FILES, ids=lambda p: p.stem)
    def test_should_flag_glimepiride_when_a_condition_criterion_reads_a_drug_set(self, path):
        if not path.exists():
            pytest.skip("artifact not present: " + str(path))
        circe = json.loads(path.read_text())

        findings = domain_mismatched_criteria(circe)

        assert len(findings) == 1, findings
        assert "Glimepiride" in findings[0]
        assert "ConditionOccurrence" in findings[0]
        assert "Drug" in findings[0]

    def test_should_flag_the_same_rule_in_the_store_it_was_exported_from(self):
        if not STORE.exists():
            pytest.skip("store not present: " + str(STORE))
        studies = json.loads(STORE.read_text())["studies"]
        study = next(s for s in studies if s.get("id") == 10)
        structured = study["eligibility"]["structuredExpression"]

        findings = domain_mismatched_criteria(structured)

        assert len(findings) == 1, findings
        assert "Glimepiride" in findings[0]


class TestTheCheckDoesNotFireOnTheSoundDeliveredFiles:
    @pytest.mark.parametrize("path", CLEAN_FILES, ids=lambda p: p.stem)
    def test_should_report_nothing_when_every_criterion_matches_its_set(self, path):
        if not path.exists():
            pytest.skip("artifact not present: " + str(path))
        circe = json.loads(path.read_text())

        assert domain_mismatched_criteria(circe) == []


class TestTheCheckDoesNotFireOnSoundShapes:
    def test_should_not_flag_a_condition_criterion_over_a_condition_set(self):
        expression = {
            "ConceptSets": [_concept_set(1, "Condition")],
            "InclusionRules": [_rule("sound", "ConditionOccurrence", 1)],
        }

        assert domain_mismatched_criteria(expression) == []

    def test_should_not_flag_a_drug_criterion_over_a_drug_set(self):
        expression = {
            "ConceptSets": [_concept_set(1, "Drug")],
            "InclusionRules": [_rule("sound", "DrugExposure", 1)],
        }

        assert domain_mismatched_criteria(expression) == []

    def test_should_not_flag_a_mixed_set_that_contains_the_criterions_domain(self):
        """CAROLINA's real "Pregnancy/Nursing/Uncontrolled Contraception" shape: an
        Observation criterion over a set holding Condition, Measurement, Observation
        and Procedure concepts. One matching item is enough for the criterion to
        return rows, so this is not the defect."""
        expression = {
            "ConceptSets": [
                _concept_set(1, "Condition", "Measurement", "Observation", "Procedure")
            ],
            "InclusionRules": [_rule("mixed", "Observation", 1)],
        }

        assert domain_mismatched_criteria(expression) == []

    def test_should_not_flag_a_compound_omop_domain_that_covers_the_criterion(self):
        """``Condition/Meas`` is a real OMOP ``domain_id`` (8 concepts in this
        vocabulary) and such a concept is routed to either table, so reading it
        through Measurement is sound."""
        expression = {
            "ConceptSets": [_concept_set(1, "Condition/Meas")],
            "InclusionRules": [_rule("compound", "Measurement", 1)],
        }

        assert domain_mismatched_criteria(expression) == []

    def test_should_not_flag_a_criterion_type_the_check_does_not_model(self):
        """An unmodelled criterion type is an unknown, not a defect. Claiming a
        mismatch the check cannot establish would be an unobserved defect claim."""
        expression = {
            "ConceptSets": [_concept_set(1, "Drug")],
            "InclusionRules": [_rule("unmodelled", "PayerPlanPeriod", 1)],
        }

        assert domain_mismatched_criteria(expression) == []

    def test_should_not_flag_a_criterion_whose_concept_set_is_absent(self):
        expression = {
            "ConceptSets": [],
            "InclusionRules": [_rule("dangling", "ConditionOccurrence", 99)],
        }

        assert domain_mismatched_criteria(expression) == []

    def test_should_not_flag_a_concept_set_with_no_usable_domain(self):
        expression = {
            "ConceptSets": [{"id": 1, "name": "empty", "expression": {"items": []}}],
            "InclusionRules": [_rule("empty", "ConditionOccurrence", 1)],
        }

        assert domain_mismatched_criteria(expression) == []


class TestTheCheckReachesEveryCriterionInTheFile:
    def test_should_flag_a_mismatch_nested_inside_groups(self):
        expression = {
            "ConceptSets": [_concept_set(1, "Drug")],
            "InclusionRules": [
                {
                    "name": "nested",
                    "expression": {
                        "Type": "ANY",
                        "CriteriaList": [],
                        "DemographicCriteriaList": [],
                        "Groups": [
                            {
                                "Type": "ALL",
                                "CriteriaList": [
                                    {
                                        "Criteria": {
                                            "ConditionOccurrence": {"CodesetId": 1}
                                        },
                                        "Occurrence": {"Type": 0, "Count": 0},
                                    }
                                ],
                                "DemographicCriteriaList": [],
                                "Groups": [],
                            }
                        ],
                    },
                }
            ],
        }

        findings = domain_mismatched_criteria(expression)

        assert len(findings) == 1, findings
        assert "nested" in findings[0]

    def test_should_flag_a_mismatched_primary_criteria_entry(self):
        expression = {
            "ConceptSets": [_concept_set(1, "Drug")],
            "PrimaryCriteria": {
                "CriteriaList": [{"ConditionOccurrence": {"CodesetId": 1, "First": True}}]
            },
            "InclusionRules": [],
        }

        findings = domain_mismatched_criteria(expression)

        assert len(findings) == 1, findings
        assert "PrimaryCriteria" in findings[0]
