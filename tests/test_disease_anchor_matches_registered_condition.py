"""The disease entry anchor must be the trial's own registered condition.

Removing the per-NCT anchor table left a general mechanism that takes the FIRST
Condition-domain concept set in document order. Order is not a clinical fact.
LEADER's comparator therefore entered on `LV systolic or diastolic dysfunction`
-- one of several alternative cardiovascular-risk qualifiers -- rather than on
type 2 diabetes, narrowing the cohort to a fraction of the trial population.
CARMELINA and EMPA-REG were correct only because their diabetes rule happened to
be written first.

The trial publishes what it is about: `protocolSection.conditionsModule.conditions`
on ClinicalTrials.gov, e.g. `["Diabetes", "Diabetes Mellitus, Type 2"]` for
NCT01179048. That is the fact the anchor is chosen against here.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.services.tte_service import TTEService

LV_DYSFUNCTION = 44782713
T2DM = 201826
T1DM = 201254
LIRAGLUTIDE = 40170911
LEADER_CONDITIONS = ["Diabetes", "Diabetes Mellitus, Type 2"]


def _concept(concept_id: int, name: str, domain: str = "Condition") -> dict[str, Any]:
    return {
        "concept": {
            "CONCEPT_ID": concept_id,
            "CONCEPT_NAME": name,
            "DOMAIN_ID": domain,
            "VOCABULARY_ID": "SNOMED",
            "CONCEPT_CLASS_ID": "Clinical Finding",
        },
        "includeDescendants": True,
        "isExcluded": False,
    }


def _condition_rule(name: str, codeset_id: int, *, absence: bool = False) -> dict[str, Any]:
    return {
        "name": name,
        "expression": {
            "Type": "ALL",
            "CriteriaList": [
                {
                    "Criteria": {"ConditionOccurrence": {"CodesetId": codeset_id}},
                    "Occurrence": {"Type": 0, "Count": 0} if absence else {"Type": 2, "Count": 1},
                }
            ],
            "DemographicCriteriaList": [],
            "Groups": [],
        },
    }


def _leader_base() -> dict[str, Any]:
    """LEADER's shape: the indication rule is NOT the first Condition rule."""
    return {
        "ConceptSets": [
            {
                "id": 1,
                "name": "liraglutide",
                "expression": {"items": [_concept(LIRAGLUTIDE, "liraglutide", "Drug")]},
            },
            {
                "id": 19,
                "name": "LV systolic or diastolic dysfunction",
                "expression": {
                    "items": [_concept(LV_DYSFUNCTION, "Left ventricular cardiac dysfunction")]
                },
            },
            {
                "id": 21,
                "name": "Type 2 diabetes",
                "expression": {"items": [_concept(T2DM, "Type 2 diabetes mellitus")]},
            },
            {
                "id": 35,
                "name": "Type 1 diabetes",
                "expression": {"items": [_concept(T1DM, "Type 1 diabetes mellitus")]},
            },
        ],
        "PrimaryCriteria": {
            "CriteriaList": [{"DrugEra": {"CodesetId": 1}}],
            "ObservationWindow": {"PriorDays": 365, "PostDays": 0},
            "PrimaryCriteriaLimit": {"Type": "First"},
        },
        "InclusionRules": [
            _condition_rule("LV systolic or diastolic dysfunction", 19),
            _condition_rule("Type 2 diabetes", 21),
            _condition_rule("Type 1 diabetes", 35, absence=True),
        ],
    }


def _study(conditions: list[str] | None) -> dict[str, Any]:
    metadata: dict[str, Any] = {"nctId": "NCT01179048"}
    if conditions is not None:
        metadata["conditions"] = conditions
    return {"trialMetadata": metadata}


def _entry_codeset(swapped: dict[str, Any]) -> int:
    entry = swapped["PrimaryCriteria"]["CriteriaList"][0]
    return entry["ConditionOccurrence"]["CodesetId"]


@pytest.fixture
def service(monkeypatch) -> TTEService:
    svc = TTEService.__new__(TTEService)
    monkeypatch.delenv("TTE_DRUG_ANCHORED_ENTRY", raising=False)
    return svc


class TestTheAnchorIsTheTrialsRegisteredCondition:
    def test_should_anchor_on_diabetes_when_a_non_indication_rule_comes_first(self, service):
        """The defect, measured: document order picks LV dysfunction over diabetes."""
        swapped = service._swap_primary_to_disease(
            _leader_base(), {}, study=_study(LEADER_CONDITIONS)
        )
        assert _entry_codeset(swapped) == 21

    def test_should_keep_every_rule_when_the_anchor_is_chosen(self, service):
        swapped = service._swap_primary_to_disease(
            _leader_base(), {}, study=_study(LEADER_CONDITIONS)
        )
        assert [rule["name"] for rule in swapped["InclusionRules"]] == [
            "LV systolic or diastolic dysfunction",
            "Type 2 diabetes",
            "Type 1 diabetes",
        ]

    def test_should_ignore_an_absence_rule_when_choosing_the_anchor(self, service):
        """A cohort cannot enter on a condition its own criteria exclude."""
        base = _leader_base()
        base["InclusionRules"] = [
            _condition_rule("LV systolic or diastolic dysfunction", 19),
            _condition_rule("Type 2 diabetes", 21, absence=True),
        ]
        with pytest.raises(ValueError, match="registered condition"):
            service._swap_primary_to_disease(base, {}, study=_study(LEADER_CONDITIONS))

    def test_should_refuse_when_no_rule_matches_the_registered_condition(self, service):
        """PLATO's shape: registered on acute coronary syndrome, no such Condition rule."""
        base = _leader_base()
        base["InclusionRules"] = [_condition_rule("LV systolic or diastolic dysfunction", 19)]
        with pytest.raises(ValueError, match="registered condition"):
            service._swap_primary_to_disease(
                base, {}, study=_study(["Acute Coronary Syndrome"])
            )

    def test_should_refuse_when_two_rules_name_the_condition_over_different_concepts(
        self, service
    ):
        """Two sets both entitled to the anchor, holding different concepts: a real
        ambiguity, so the entry would be an arbitrary pick either way."""
        base = _leader_base()
        base["ConceptSets"].append(
            {
                "id": 22,
                "name": "Diabetes Mellitus, Type 2",
                "expression": {
                    "items": [_concept(443767, "Disorder due to type 2 diabetes mellitus")]
                },
            }
        )
        base["InclusionRules"].append(_condition_rule("Diabetes Mellitus, Type 2", 22))
        with pytest.raises(ValueError, match="registered condition"):
            service._swap_primary_to_disease(base, {}, study=_study(LEADER_CONDITIONS))

    def test_should_anchor_on_the_only_rule_when_the_trial_registers_no_condition(self, service):
        """One candidate is not a choice, so document order decides nothing."""
        base = _leader_base()
        base["InclusionRules"] = [_condition_rule("Type 2 diabetes", 21)]
        swapped = service._swap_primary_to_disease(base, {}, study=_study(None))
        assert _entry_codeset(swapped) == 21

    def test_should_refuse_when_no_registered_condition_and_rules_compete(self, service):
        with pytest.raises(ValueError, match="registered condition"):
            service._swap_primary_to_disease(_leader_base(), {}, study=_study(None))


class TestTheRegisteredConditionIsPersisted:
    def test_should_store_the_registered_conditions_when_metadata_is_built(self, tmp_path):
        import json

        from src.agents.agent1 import nct_fetcher

        payload = {
            "protocolSection": {
                "identificationModule": {"briefTitle": "LEADER"},
                "conditionsModule": {"conditions": LEADER_CONDITIONS},
            }
        }
        (tmp_path / "NCT01179048.json").write_text(json.dumps(payload))

        svc = TTEService.__new__(TTEService)
        original = nct_fetcher.DEFAULT_CACHE_DIR
        nct_fetcher.DEFAULT_CACHE_DIR = tmp_path
        try:
            metadata = svc._fetch_nct_trial_metadata("NCT01179048")
        finally:
            nct_fetcher.DEFAULT_CACHE_DIR = original

        assert metadata["conditions"] == LEADER_CONDITIONS


class TestResemblanceIsNotCorrespondence:
    """The LEADER duplicates (store studies 4/5/6) carry no diabetes rule at all.

    A first version of the matcher took the best partial token overlap above zero and
    anchored them on `Symptomatic coronary heart disease`, which scored 0.444 against
    `"Diabetes Mellitus, Type 2"` because one of its members is named `Coronary artery
    disease due to type 2 diabetes mellitus`. A comorbidity qualifier inside a concept
    name is not the trial's indication, so the anchor must refuse rather than take it.
    """

    def test_should_refuse_when_only_a_comorbidity_qualifier_mentions_the_condition(
        self, service
    ):
        base = _leader_base()
        base["ConceptSets"] = [
            cs for cs in base["ConceptSets"] if cs["id"] in (1, 19)
        ] + [
            {
                "id": 6,
                "name": "Symptomatic coronary heart disease",
                "expression": {
                    "items": [
                        _concept(
                            4185932, "Coronary artery disease due to type 2 diabetes mellitus"
                        )
                    ]
                },
            }
        ]
        base["InclusionRules"] = [
            _condition_rule("LV systolic or diastolic dysfunction", 19),
            _condition_rule("Symptomatic coronary heart disease", 6),
        ]
        with pytest.raises(ValueError, match="names the trial's registered condition"):
            service._swap_primary_to_disease(base, {}, study=_study(LEADER_CONDITIONS))

    def test_should_anchor_when_two_matching_rules_hold_the_same_concepts(self, service):
        """CAROLINA carries `Type 2 diabetes` twice, both [201826]. Either builds the
        same cohort, so this is a duplicate rather than an ambiguity."""
        base = _leader_base()
        base["ConceptSets"].append(
            {
                "id": 22,
                "name": "Type 2 diabetes",
                "expression": {"items": [_concept(T2DM, "Type 2 diabetes mellitus")]},
            }
        )
        base["InclusionRules"].append(_condition_rule("Type 2 diabetes (again)", 22))
        swapped = service._swap_primary_to_disease(base, {}, study=_study(LEADER_CONDITIONS))
        assert _entry_codeset(swapped) == 21


class TestNothingToAnchorOnIsNotAWrongAnchor:
    """A study whose rules read no Condition concept set at all is a different case.

    There is no candidate to choose wrongly among, so the pre-existing behaviour is
    kept: warn and leave the entry alone. It does not pass unnoticed -- a placebo
    comparator that keeps its drug entry while requiring zero occurrences of that drug
    is an empty cohort, which `circe_lint.contradictory_absence_rules` reports and the
    delivery gate fails on.
    """

    def test_should_leave_the_entry_alone_when_no_condition_rule_exists(self, service):
        base = _leader_base()
        base["InclusionRules"] = []
        swapped = service._swap_primary_to_disease(base, {}, study=_study(LEADER_CONDITIONS))
        assert swapped["PrimaryCriteria"]["CriteriaList"] == [{"DrugEra": {"CodesetId": 1}}]

    def test_should_leave_the_entry_alone_when_every_condition_rule_is_an_absence_rule(
        self, service
    ):
        base = _leader_base()
        base["InclusionRules"] = [_condition_rule("Type 1 diabetes", 35, absence=True)]
        swapped = service._swap_primary_to_disease(base, {}, study=_study(LEADER_CONDITIONS))
        assert swapped["PrimaryCriteria"]["CriteriaList"] == [{"DrugEra": {"CodesetId": 1}}]
