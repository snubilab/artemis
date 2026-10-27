"""Recover only UCUM text stated in the recorded EMPA-REG threshold span."""

import json
from copy import deepcopy
from pathlib import Path

from src.services.criterion_annotation import applied_value_constraint
from src.services.value_constraint import build_measurement_value_filter
from src.utils.circe_lint import unitless_value_bound_criteria

FIXTURE = json.loads((Path(__file__).parent / "fixtures/loss_h2_egfr.json").read_text())


def test_should_emit_a_ucum_unit_when_the_real_egfr_span_contains_whitespace():
    row = FIXTURE["row"]
    applied = applied_value_constraint(row)
    assert applied["unitText"] == "ml/min/1.73 m2"
    value_filter = build_measurement_value_filter(applied)
    assert value_filter["ValueAsNumber"] == {"Value": 30.0, "Op": "lt"}
    assert {u["CONCEPT_ID"] for u in value_filter["Unit"]} == {720870, 9117, 9062}
    cohort = deepcopy(FIXTURE["cohort"])
    assert len(unitless_value_bound_criteria(cohort)) == 1
    payload = cohort["InclusionRules"][0]["expression"]["CriteriaList"][0]["Criteria"]
    payload["Measurement"].update(value_filter)
    assert unitless_value_bound_criteria(cohort) == []
    assert row["valueConstraint"]["unitText"] == ""


def test_should_not_infer_units_when_the_real_egfr_span_has_no_unit():
    row = deepcopy(FIXTURE["row"])
    row["protocolLine"] = row["protocolLine"].replace(" ml/min/1.73 m2", "")
    row["annotation"]["threshold_span"] = "<30"
    assert applied_value_constraint(row)["unitText"] == ""


def test_should_not_recover_units_when_the_threshold_span_is_not_in_the_protocol():
    row = deepcopy(FIXTURE["row"])
    row["protocolLine"] = row["protocolLine"].replace(" ml/min/1.73 m2", "")
    assert applied_value_constraint(row)["unitText"] == ""


def test_should_not_read_a_unit_after_a_different_number():
    row = deepcopy(FIXTURE["row"])
    row["valueConstraint"]["value"] = 45.0
    assert applied_value_constraint(row)["unitText"] == ""


def test_should_keep_the_unit_and_exclusion_direction_in_the_seeded_builder(monkeypatch):
    from src.services.tte_service import TTEService

    service = TTEService.__new__(TTEService)
    concept_set = FIXTURE["cohort"]["ConceptSets"][0]
    monkeypatch.setattr(service, "_recommend_seeded_concept_set", lambda *_a, **_kw: {
        "name": concept_set["name"], "domain": "Measurement",
        "expression": deepcopy(concept_set["expression"]),
    })
    monkeypatch.setattr(service, "_refine_measurement_specimen", lambda expression, **_kw: (
        expression, None,
    ))
    built = service._build_seeded_eligibility_rule(
        criterion=deepcopy(FIXTURE["row"]), codeset_id=29, exclusion=True,
    )
    entry = built["rule"]["expression"]["CriteriaList"][0]
    payload = entry["Criteria"]["Measurement"]
    assert payload["ValueAsNumber"] == {"Value": 30.0, "Op": "lt"}
    assert {u["CONCEPT_ID"] for u in payload["Unit"]} == {720870, 9117, 9062}
    assert entry["Occurrence"] == {"Type": 0, "Count": 0}
    recorded = FIXTURE["cohort"]["InclusionRules"][0]["expression"]["CriteriaList"][0]
    assert entry["StartWindow"] == recorded["StartWindow"]
