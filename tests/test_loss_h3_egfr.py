"""Retain the real unresolved eGFR warning and the rejected candidate's loss evidence."""

import json
from copy import deepcopy
from pathlib import Path

from src.services.loinc_specimen import LabTest, option_of
from src.utils.circe_lint import specimen_mismatched_measurement_criteria

FIXTURE = json.loads((Path(__file__).parent / "fixtures/loss_h3_egfr.json").read_text())


def _labs():
    # Has method is recorded separately: the production reader does not expose that axis.
    return {
        int(cid): LabTest(**{key: value for key, value in fields.items() if key != "method"})
        for cid, fields in FIXTURE["labTests"].items()
    }


def test_should_keep_the_real_specimen_warning_when_the_recorded_judge_accepts_no_member():
    cohort = {
        "ConceptSets": deepcopy(FIXTURE["conceptSets"]),
        "InclusionRules": [{"name": "Confirmed history of MI", "expression": {
            "Type": "ALL", "CriteriaList": deepcopy(FIXTURE["entries"]), "Groups": [],
        }}],
        "_specimenDecisions": deepcopy(FIXTURE["decisions"]),
    }
    fail, warn = specimen_mismatched_measurement_criteria(cohort, _labs(), lambda _a: [])
    assert fail == []
    assert len(warn) == 2
    assert all("no LOINC lab-test member in a specimen the criterion states" in f for f in warn)
    assert "codeset 24" in warn[0] and "codeset 25" in warn[1]


def test_should_expose_the_missing_method_axis_when_the_real_egfr_options_collapse():
    labs = _labs()
    assert len({option_of(t).key for t in labs.values()}) == 1
    assert len({t["method"] for t in FIXTURE["labTests"].values()}) == 4
    assert all(t.system_id == 1033343 for t in labs.values())
    assert all(t.property == "Volume Rate/Area" for t in labs.values())


def test_should_reject_the_live_candidate_as_evidence_of_a_lossless_fix():
    result = FIXTURE["rejectedLiveResult"]
    assert "as defined by MDRD formula" in result["protocolLine"]
    assert result["record"]["declined"] is None
    # The warning vanished but a valid MDRD variant also vanished; that is not a PASS.
    assert 3049187 not in result["kept"]
    assert 46236952 in result["kept"]
    assert {3049187, 36303797, 40764999} == {
        cid for cid, _reasons in result["record"]["removed"]
    }
