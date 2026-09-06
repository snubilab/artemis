"""A disease-anchored comparator must enter on the trial's registered condition.

Check (c) of the delivery gate accepts ANY `ConditionOccurrence` entry on a comparator,
because the drug->disease swap itself is legitimate. Nothing then looked at WHICH
condition, so the gate exited 0 on a LEADER comparator entering on `LV systolic or
diastolic dysfunction` [4323898] -- one of several alternative cardiovascular-risk
qualifiers -- rather than on type 2 diabetes [201826]. Measured on the real file:

    leader_comparator.circe.json   PASS   entry: disease-anchored comparator swap

Check (h) closes that by asking the same function the generator chooses with
(`src.utils.disease_anchor`) what the anchor should have been.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

T2DM = 201826
LV_DYSFUNCTION = 4323898
LIRAGLUTIDE = 40170911


def _concept(concept_id: int, name: str, domain: str = "Condition") -> dict[str, Any]:
    return {
        "concept": {
            "CONCEPT_ID": concept_id,
            "CONCEPT_NAME": name,
            "DOMAIN_ID": domain,
            "VOCABULARY_ID": "SNOMED",
            "CONCEPT_CLASS_ID": "Clinical Finding",
            "CONCEPT_CODE": "1",
        },
        "includeDescendants": True,
        "isExcluded": False,
    }


def _rule(name: str, codeset_id: int) -> dict[str, Any]:
    return {
        "name": name,
        "expression": {
            "Type": "ALL",
            "CriteriaList": [
                {
                    "Criteria": {"ConditionOccurrence": {"CodesetId": codeset_id}},
                    "Occurrence": {"Type": 2, "Count": 1},
                }
            ],
            "DemographicCriteriaList": [],
            "Groups": [],
        },
    }


def _leader_store_study(conditions: list[str] | None) -> dict[str, Any]:
    metadata: dict[str, Any] = {"nctId": "NCT01179048"}
    if conditions is not None:
        metadata["conditions"] = conditions
    return {
        "id": 1,
        "name": "liraglutide vs placebo",
        "comparisonMode": "target_minus_treatment",
        "treatmentArms": [{"name": "liraglutide"}, {"name": "placebo"}],
        "trialMetadata": metadata,
        "eligibility": {
            "structuredExpression": {
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
                            "items": [
                                _concept(LV_DYSFUNCTION, "Left ventricular cardiac dysfunction")
                            ]
                        },
                    },
                    {
                        "id": 21,
                        "name": "Type 2 diabetes",
                        "expression": {"items": [_concept(T2DM, "Type 2 diabetes mellitus")]},
                    },
                ],
                "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 1}}]},
                "InclusionRules": [
                    _rule("LV systolic or diastolic dysfunction", 19),
                    _rule("Type 2 diabetes", 21),
                ],
            }
        },
    }


def _write_arms(tmp_path, study, comparator_anchor_codeset: int) -> None:
    """Treatment on the store's drug entry; comparator disease-anchored as given."""
    core = study["eligibility"]["structuredExpression"]
    (tmp_path / "leader_treatment.circe.json").write_text(json.dumps(core))
    comparator = json.loads(json.dumps(core))
    comparator["PrimaryCriteria"] = {
        "CriteriaList": [{"ConditionOccurrence": {"CodesetId": comparator_anchor_codeset}}]
    }
    (tmp_path / "leader_comparator.circe.json").write_text(json.dumps(comparator))


@pytest.fixture
def gate(monkeypatch, tmp_path, capsys):
    def _run(study, comparator_anchor_codeset: int) -> tuple[int, str]:
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        _write_arms(tmp_path, study, comparator_anchor_codeset)
        store = tmp_path / "studies.json"
        store.write_text(json.dumps([study]))

        from scripts.verify_circe_delivery import main

        rc = main(["--dir", str(tmp_path), "--store", str(store), "--map", "leader=1"])
        return rc, capsys.readouterr().out

    return _run


class TestTheGateChecksWhichConditionTheComparatorEntersOn:
    def test_should_fail_when_the_comparator_enters_on_a_non_indication_condition(self, gate):
        """The measured LEADER file: a legitimate swap onto the wrong condition."""
        rc, out = gate(_leader_store_study(["Diabetes", "Diabetes Mellitus, Type 2"]), 19)
        assert rc == 1, out
        assert "disease anchor mismatch" in out
        assert "4323898" in out

    def test_should_pass_when_the_comparator_enters_on_the_registered_condition(self, gate):
        rc, out = gate(_leader_store_study(["Diabetes", "Diabetes Mellitus, Type 2"]), 21)
        assert rc == 0, out
        assert "disease anchor" not in out

    def test_should_fail_when_the_store_carries_no_registered_condition(self, gate):
        """Unverifiable is a gap, not a pass: an un-backfilled store must not ship."""
        rc, out = gate(_leader_store_study(None), 21)
        assert rc == 1, out
        assert "disease anchor unverifiable" in out
