import pytest

from src.utils.circe_lint import (
    entry_concept_ids,
    entry_concept_set,
    entry_concept_set_name,
    entry_matches_expected,
    noop_exclusion_rules,
    refuse_domain_contradiction,
    rule_names,
)


def _absence_group(codeset_id: int) -> dict:
    return {
        "Type": "ALL",
        "CriteriaList": [
            {
                "Criteria": {"ConditionOccurrence": {"CodesetId": codeset_id}},
                "Occurrence": {"Type": 0, "Count": 0},
            }
        ],
        "DemographicCriteriaList": [],
        "Groups": [],
    }


def _presence_group(codeset_id: int) -> dict:
    return {
        "Type": "ALL",
        "CriteriaList": [
            {
                "Criteria": {"ConditionOccurrence": {"CodesetId": codeset_id}},
                "Occurrence": {"Type": 2, "Count": 1},
            }
        ],
        "DemographicCriteriaList": [],
        "Groups": [],
    }


def _rule(name: str, expression: dict) -> dict:
    return {"name": name, "expression": expression}


def test_should_flag_any_over_two_absence_groups():
    expression = {
        "InclusionRules": [
            _rule(
                "A or B never occurred",
                {
                    "Type": "ANY",
                    "CriteriaList": [],
                    "DemographicCriteriaList": [],
                    "Groups": [_absence_group(1), _absence_group(2)],
                },
            )
        ]
    }

    assert noop_exclusion_rules(expression) == ["A or B never occurred"]


def test_should_not_flag_all_over_absence_groups():
    expression = {
        "InclusionRules": [
            _rule(
                "Neither A nor B occurred",
                {
                    "Type": "ALL",
                    "CriteriaList": [],
                    "DemographicCriteriaList": [],
                    "Groups": [_absence_group(1), _absence_group(2)],
                },
            )
        ]
    }

    assert noop_exclusion_rules(expression) == []


def test_should_not_flag_any_over_presence_groups():
    expression = {
        "InclusionRules": [
            _rule(
                "A or B occurred",
                {
                    "Type": "ANY",
                    "CriteriaList": [],
                    "DemographicCriteriaList": [],
                    "Groups": [_presence_group(1), _presence_group(2)],
                },
            )
        ]
    }

    assert noop_exclusion_rules(expression) == []


def test_should_flag_nested_groups():
    nested_absence_group = {
        "Type": "ALL",
        "CriteriaList": [],
        "DemographicCriteriaList": [],
        "Groups": [_absence_group(1)],
    }
    expression = {
        "InclusionRules": [
            _rule(
                "Nested no-op",
                {
                    "Type": "ANY",
                    "CriteriaList": [],
                    "DemographicCriteriaList": [],
                    "Groups": [nested_absence_group, _absence_group(2)],
                },
            )
        ]
    }

    assert noop_exclusion_rules(expression) == ["Nested no-op"]


def test_should_return_rule_names_in_order():
    expression = {
        "InclusionRules": [
            _rule("First", {"Type": "ALL", "Groups": []}),
            _rule("Second", {"Type": "ALL", "Groups": []}),
        ]
    }

    assert rule_names(expression) == ["First", "Second"]


def test_should_return_primary_criteria_concept_ids():
    expression = {
        "PrimaryCriteria": {
            "CriteriaList": [{"DrugEra": {"CodesetId": 1}}],
            "ObservationWindow": {"PriorDays": 365, "PostDays": 0},
        },
        "ConceptSets": [
            {
                "id": 1,
                "name": "Empagliflozin",
                "expression": {
                    "items": [
                        {"concept": {"CONCEPT_ID": 45774751, "CONCEPT_NAME": "empagliflozin"}}
                    ]
                },
            },
            {
                "id": 2,
                "name": "Unrelated",
                "expression": {"items": [{"concept": {"CONCEPT_ID": 999}}]},
            },
        ],
    }

    domain, concept_ids = entry_concept_ids(expression)

    assert domain == "DrugEra"
    assert concept_ids == {45774751}


def test_should_match_treatment_entry_only_on_exact_equality():
    assert entry_matches_expected(
        "DrugEra",
        {45774751},
        "DrugEra",
        {45774751},
        is_comparator=False,
        comparison_mode="target_minus_treatment",
    )
    assert not entry_matches_expected(
        "ConditionOccurrence",
        {201826},
        "DrugEra",
        {45774751},
        is_comparator=False,
        comparison_mode="target_minus_treatment",
    )


def test_should_allow_disease_anchored_comparator_under_target_minus_treatment():
    assert entry_matches_expected(
        "ConditionOccurrence",
        {201826},
        "DrugEra",
        {45774751},
        is_comparator=True,
        comparison_mode="target_minus_treatment",
    )
    # Same swap is not granted to an explicit-comparator study.
    assert not entry_matches_expected(
        "ConditionOccurrence",
        {201826},
        "DrugEra",
        {45774751},
        is_comparator=True,
        comparison_mode="explicit_comparator",
    )


def test_should_return_entry_concept_set_name():
    expression = {
        "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 73}}]},
        "ConceptSets": [{"id": 73, "name": "glimepiride", "expression": {"items": []}}],
    }

    assert entry_concept_set_name(expression) == "glimepiride"


def test_should_return_the_entry_concept_set_when_it_has_items():
    concept_set = {
        "id": 73,
        "name": "glimepiride",
        "expression": {"items": [{"concept": {"CONCEPT_ID": 1597756}}]},
    }
    expression = {
        "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 73}}]},
        "ConceptSets": [concept_set],
    }

    assert entry_concept_set(expression) is concept_set


def test_should_return_none_when_the_entry_concept_set_has_no_items():
    expression = {
        "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 73}}]},
        "ConceptSets": [{"id": 73, "name": "glimepiride", "expression": {"items": []}}],
    }

    assert entry_concept_set(expression) is None


def test_should_refuse_a_condition_criterion_over_a_drug_set():
    mapped = {
        "expression": {
            "items": [{"concept": {"CONCEPT_ID": 1597756, "DOMAIN_ID": "Drug"}}]
        }
    }

    with pytest.raises(ValueError, match="domain contradiction"):
        refuse_domain_contradiction("ConditionOccurrence", mapped, "Glimepiride")


def test_should_accept_comparator_entry_matching_arm2_name_for_active_comparator():
    # CAROLINA: linagliptin vs glimepiride, comparisonMode is (per the real
    # store) "target_minus_treatment" even though arm 2 is a genuine active
    # drug, not a placebo — so this must not depend on comparison_mode.
    assert entry_matches_expected(
        "DrugEra",
        {1597756},
        "DrugEra",
        {40239216},
        is_comparator=True,
        comparison_mode="target_minus_treatment",
        file_entry_name="glimepiride",
        comparator_arm_name="glimepiride",
    )
    # Case-insensitive, stripped.
    assert entry_matches_expected(
        "DrugEra",
        {1597756},
        "DrugEra",
        {40239216},
        is_comparator=True,
        comparison_mode="target_minus_treatment",
        file_entry_name="  Glimepiride  ",
        comparator_arm_name="glimepiride",
    )


def test_should_still_reject_treatment_entry_that_differs_from_store():
    # A treatment arm never gets the active-comparator or disease-swap
    # exceptions, even when the name happens to match arm 2's name.
    assert not entry_matches_expected(
        "DrugEra",
        {1597756},
        "DrugEra",
        {40239216},
        is_comparator=False,
        comparison_mode="target_minus_treatment",
        file_entry_name="glimepiride",
        comparator_arm_name="glimepiride",
    )


def test_should_still_reject_comparator_entry_naming_neither_drug():
    # A DrugEra comparator entry that matches neither the store's own entry
    # nor the study's second arm name is a genuine defect (the 2026-08-31
    # EMPA-REG shape), not a sanctioned design choice.
    assert not entry_matches_expected(
        "DrugEra",
        {859730, 1201447, 1201518, 1254065, 702171},
        "DrugEra",
        {45774751},
        is_comparator=True,
        comparison_mode="target_minus_treatment",
        file_entry_name="BI 10773",
        comparator_arm_name="Placebo",
    )
