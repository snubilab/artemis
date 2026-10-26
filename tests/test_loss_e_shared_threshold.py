"""Real BASE rows: a bound belongs to a Measurement sibling, never its Condition."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.verify_circe_delivery import threshold_without_value_filter_findings

CASES = json.loads((Path(__file__).parent / "fixtures/loss_e_threshold_rows.json").read_text())[
    "cases"
]


def _entries(value):
    if isinstance(value, dict):
        if "Criteria" in value:
            yield value
        for child in value.values():
            yield from _entries(child)
    elif isinstance(value, list):
        for child in value:
            yield from _entries(child)


def _renal():
    case = deepcopy(CASES[0])
    entries = list(_entries(case["expression"]))
    measurement = next(
        e for e in entries if e["Criteria"].get("Measurement", {}).get("CodesetId") == 45
    )
    condition = next(
        e for e in entries if e["Criteria"].get("ConditionOccurrence", {}).get("CodesetId") == 46
    )
    return case, measurement, condition


def _findings(case):
    return threshold_without_value_filter_findings(case["expression"], case["study"])


def test_should_accept_the_existing_measurement_when_the_same_bound_is_mandatory():
    case, measurement, condition = _renal()
    assert measurement["Criteria"]["Measurement"]["ValueAsNumber"] == {"Value": 15.0, "Op": "lt"}
    assert measurement["Criteria"]["Measurement"]["Unit"][0]["CONCEPT_ID"] == 720870
    assert condition["Criteria"]["ConditionOccurrence"] == {"CodesetId": 46}
    findings = _findings(case)
    assert not findings.failures
    assert any("exclusion #29" in w and "exclusion #28" in w for w in findings.warnings)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-value",
        "missing-unit",
        "wrong-table",
        "wrong-value",
        "wrong-op",
        "wrong-window",
        "wrong-occurrence",
        "alternative-group",
        "missing-ref",
        "different-line",
        "different-span",
        "different-group",
        "invalid-span",
    ],
)
def test_should_fail_when_the_sibling_is_not_proof_of_the_bound(mutation):
    case, entry, _ = _renal()
    payload = entry["Criteria"]["Measurement"]
    rows = case["study"]["eligibility"]["exclusionCriteria"]
    sibling = next(r for r in rows if r["id"] == 28)
    if mutation == "missing-value":
        payload.pop("ValueAsNumber")
    elif mutation == "missing-unit":
        payload.pop("Unit")
    elif mutation == "wrong-table":
        entry["Criteria"] = {"ConditionOccurrence": payload}
    elif mutation == "wrong-value":
        payload["ValueAsNumber"]["Value"] = 16
    elif mutation == "wrong-op":
        payload["ValueAsNumber"]["Op"] = "lte"
    elif mutation == "wrong-window":
        entry["StartWindow"]["Start"]["Days"] = 90
    elif mutation == "wrong-occurrence":
        entry["Occurrence"] = {"Type": 2, "Count": 1}
    elif mutation == "alternative-group":
        case["expression"]["InclusionRules"][0]["expression"]["Type"] = "ANY"
    elif mutation == "missing-ref":
        case["expression"]["_criterionConceptSetRefs"].pop("exclusion:28")
    elif mutation == "different-line":
        sibling["protocolLine"] += " "
    elif mutation == "different-span":
        sibling["annotation"]["threshold_span"] = "<15"
    elif mutation == "different-group":
        sibling["groupId"] = "unrelated"
    elif mutation == "invalid-span":
        sibling["annotation"]["threshold_span"] = "not in this protocol"
    assert any("exclusion #29" in f for f in _findings(case).failures)


@pytest.mark.parametrize("case", CASES[1:], ids=[c["name"] for c in CASES[1:]])
def test_should_keep_failing_when_the_measurement_was_not_emitted(case):
    findings = _findings(case)
    assert any(f"inclusion #{case['criterionId']} " in f for f in findings.failures)
    assert not findings.warnings
