"""Real BASE rows; structured answers below test the contract, not model accuracy."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.verify_circe_delivery import threshold_without_value_filter_findings
from src.services.criterion_annotation import validate_annotation
from tests.test_quantity_thresholds_in_build import _build
from tests.test_quantity_thresholds_in_build import service as service

FIXTURE = json.loads((Path(__file__).parent / "fixtures/duration_count_base_rows.json").read_text())


def row_for(study, role, criterion):
    return deepcopy(
        next(
            x["row"]
            for x in FIXTURE["rows"]
            if (x["studyId"], x["role"], x["row"]["id"]) == (study, role, criterion)
        )
    )


def answer(row, target, op, value, unit):
    # Explicit test answer; do not infer any of these fields from protocol words.
    # Isolate the occurrence builder from BASE's separately unresolved group relations.
    row["groupId"] = None
    row["annotation"]["occurrence_threshold"] = {
        "target": target,
        "op": op,
        "value": value,
        "unit": unit,
        "anchor": "index",
        "span": row["annotation"]["threshold_span"],
    }
    return row


def entries(expression):
    if isinstance(expression, dict):
        if "StartWindow" in expression and "Criteria" in expression:
            yield expression
        for value in expression.values():
            yield from entries(value)
    elif isinstance(expression, list):
        for value in expression:
            yield from entries(value)


EVENTS = [
    (9, "exclusion", 36, "lte", 2, "month", -60, 0),
    (9, "exclusion", 79, "lte", 3, "month", -90, 0),
    *[(10, "exclusion", i, "lte", 6, "week", -42, 0) for i in (23, 24, 25, 59)],
    *[(10, "exclusion", i, "lte", 3, "month", -90, 0) for i in (61, 62)],
    (8, "inclusion", 20, "gt", 2, "month", None, -61),
    (8, "inclusion", 28, "lte", 12, "month", -360, 0),
    *[(8, "inclusion", i, "gt", 2, "month", None, -61) for i in (33, 34)],
]


@pytest.mark.parametrize("study,role,cid,op,value,unit,start,end", EVENTS)
def test_should_emit_stated_window_when_real_event_row_has_structured_bound(
    service, study, role, cid, op, value, unit, start, end
):
    row = answer(row_for(study, role, cid), "event_age", op, value, unit)
    circe = _build(service, **{role: [row]})
    [entry] = list(entries(circe["InclusionRules"]))
    assert entry["StartWindow"]["End"] == {"Days": abs(end), "Coeff": -1 if end < 0 else 1}
    if start is None:
        assert "Days" not in entry["StartWindow"]["Start"]  # truly unbounded history
    else:
        assert entry["StartWindow"]["Start"] == {"Days": abs(start), "Coeff": -1}
    assert circe["_unrepresentableThresholds"] == []
    finding = threshold_without_value_filter_findings(
        circe, {"eligibility": {role + "Criteria": [row]}}
    )
    assert finding == ([], [])
    entry["StartWindow"]["End"] = {"Days": 0, "Coeff": 1} if end else {"Days": 1, "Coeff": 1}
    assert threshold_without_value_filter_findings(
        circe, {"eligibility": {role + "Criteria": [row]}}
    ).failures


def test_should_use_first_diagnosis_when_real_diabetes_row_states_disease_duration(service):
    row = answer(row_for(10, "inclusion", 24), "first_diagnosis_age", "gt", 10, "year")
    circe = _build(service, inclusion=[row])
    [entry] = list(entries(circe["InclusionRules"]))
    assert entry["Criteria"]["ConditionOccurrence"]["First"] is True
    assert entry["StartWindow"]["End"] == {"Days": 3651, "Coeff": -1}
    assert circe["_unrepresentableThresholds"] == []


@pytest.mark.parametrize("cid", [4, 5, 6])
def test_should_emit_era_length_when_real_drug_row_has_treatment_duration(service, cid):
    row = answer(row_for(9, "exclusion", cid), "drug_era_length", "gte", 7, "day")
    circe = _build(service, exclusion=[row])
    [entry] = list(entries(circe["InclusionRules"]))
    assert entry["Criteria"]["DrugEra"]["EraLength"] == {"Value": 7, "Op": "gte"}
    assert entry["Criteria"]["DrugEra"]["GapDays"] == {"Value": 0, "Op": "eq"}
    assert entry["StartWindow"] == {"Start": {"Coeff": -1}, "End": {"Days": 7, "Coeff": -1}}
    assert entry["Occurrence"] == {"Type": 0, "Count": 0}
    assert circe["_unrepresentableThresholds"] == []


@pytest.mark.parametrize("study,cid", [(9, 70), (10, 55)])
def test_should_keep_warning_when_real_row_is_life_expectancy(service, study, cid):
    row = answer(row_for(study, "exclusion", cid), "unrepresentable", "lt", 5, "year")
    circe = _build(service, exclusion=[row])
    assert len(circe["_unrepresentableThresholds"]) == 1


def test_should_keep_warning_when_real_count_is_arteries_rather_than_events(service):
    row = answer(row_for(9, "inclusion", 22), "unrepresentable", "gte", 2, "count")
    circe = _build(service, inclusion=[row])
    assert len(circe["_unrepresentableThresholds"]) == 1


def test_should_emit_occurrence_count_when_model_states_event_count(service):
    row = answer(row_for(9, "inclusion", 22), "event_count", "gte", 2, "count")
    # Counterfactual structured answer exercises compilation only; actual row counts arteries.
    circe = _build(service, inclusion=[row])
    [entry] = list(entries(circe["InclusionRules"]))
    assert entry["Occurrence"] == {"Type": 2, "Count": 2}
    assert circe["_unrepresentableThresholds"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("span", "not in protocol"),
        ("unit", None),
        ("unit", "fortnight"),
        ("unit", []),
        ("anchor", "other"),
        ("value", float("nan")),
        ("value", 10**400),
        ("value", True),
        ("op", "invalid"),
        ("target", "first_diagnosis_age"),
    ],
)
def test_should_keep_warning_when_structured_bound_is_invalid(service, field, value):
    row = answer(row_for(9, "exclusion", 36), "event_age", "lte", 2, "month")
    row["annotation"]["occurrence_threshold"][field] = value
    circe = _build(service, exclusion=[row])
    assert len(circe["_unrepresentableThresholds"]) == 1


def test_should_preserve_structured_bound_when_annotation_span_is_valid():
    row = answer(row_for(9, "exclusion", 36), "event_age", "lte", 2, "month")
    fields, rejected = validate_annotation(row["annotation"], row["protocolLine"])
    assert fields["occurrence_threshold"] == row["annotation"]["occurrence_threshold"]
    assert not rejected


def test_should_invert_minimum_count_when_event_count_is_excluded(service):
    row = answer(row_for(9, "inclusion", 22), "event_count", "gte", 2, "count")
    circe = _build(service, exclusion=[row])
    [entry] = list(entries(circe["InclusionRules"]))
    assert entry["Occurrence"] == {"Type": 1, "Count": 1}


def test_should_not_change_window_when_threshold_span_is_outside_protocol(service):
    row = answer(row_for(9, "exclusion", 36), "event_age", "lte", 2, "month")
    row["annotation"]["threshold_span"] = "not in protocol"
    row["annotation"]["occurrence_threshold"]["span"] = "not in protocol"
    circe = _build(service, exclusion=[row])
    [entry] = list(entries(circe["InclusionRules"]))
    from src.services.occurrence_threshold import occurrence_filter

    assert occurrence_filter(row) is None
    assert entry["StartWindow"]["Start"]["Days"] == abs(row["window"]["start"])
    assert entry["StartWindow"]["End"]["Days"] == 0


def test_should_preserve_group_refusal_when_real_base_relation_is_unresolved(service):
    row = row_for(8, "inclusion", 28)
    circe = _build(service, inclusion=[row])
    assert not circe["InclusionRules"]
    assert circe["_skippedCriteria"][0]["reason"] == "group-relation-unresolved"


@pytest.mark.parametrize(
    "study,role,cid,target,op,value,unit,attribute",
    [
        (9, "exclusion", 4, "drug_era_length", "gte", 7, "day", "EraLength"),
        (9, "exclusion", 4, "drug_era_length", "gte", 7, "day", "GapDays"),
        (10, "inclusion", 24, "first_diagnosis_age", "gt", 10, "year", "First"),
        (9, "inclusion", 22, "event_count", "gte", 2, "count", "Occurrence"),
    ],
)
def test_should_fail_delivery_gate_when_compiled_threshold_is_removed(
    service, study, role, cid, target, op, value, unit, attribute
):
    row = answer(row_for(study, role, cid), target, op, value, unit)
    circe = _build(service, **{role: [row]})
    study = {"eligibility": {role + "Criteria": [row]}}
    assert threshold_without_value_filter_findings(circe, study) == ([], [])
    [entry] = list(entries(circe["InclusionRules"]))
    if attribute == "Occurrence":
        del entry[attribute]
    else:
        [attrs] = entry["Criteria"].values()
        del attrs[attribute]
    assert threshold_without_value_filter_findings(circe, study).failures


def test_should_compile_live_bound_when_model_quotes_a_longer_verified_span(service):
    row = row_for(9, "exclusion", 36)
    row["annotation"] = json.loads(
        (Path(__file__).parent / "fixtures/duration_count_live_annotation.json").read_text()
    )
    # This is the captured single-call answer, not agreement-validated exception semantics.
    from src.services.occurrence_threshold import occurrence_filter

    result = occurrence_filter(row)
    assert result["StartWindow"] == {
        "Start": {"Days": 60, "Coeff": -1},
        "End": {"Days": 0, "Coeff": 1},
    }


def test_should_accept_correct_bound_when_another_rule_reads_same_codeset(service):
    row = answer(row_for(9, "exclusion", 36), "event_age", "lte", 2, "month")
    circe = _build(service, exclusion=[row])
    other = deepcopy(circe["InclusionRules"][0])
    other["name"] = "another rule over the same codeset"
    [entry] = list(entries(other))
    entry["StartWindow"]["Start"]["Days"] = 365
    circe["InclusionRules"].append(other)
    study = {"eligibility": {"exclusionCriteria": [row]}}
    assert threshold_without_value_filter_findings(circe, study) == ([], [])
