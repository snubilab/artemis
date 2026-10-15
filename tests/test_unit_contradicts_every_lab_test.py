"""A stated unit whose LOINC property contradicts every lab test in the set: refuse; FAIL the gate.

CAROLINA inclusion 27 ("eGFR 30-59 mL/min/1.73 m2") reached A2 (output/site_gap/2026-10-14_a2_dry)
as codeset 10 'eGFR' holding Natriuretic peptide B and Epidermal growth factor receptor tests, read
by a ``Unit`` of mL/min/(173.10*-2.m2). The unit's property, 'Volume Rate/Area', contradicts every
LOINC member, and the vocabulary offers no test of the set's analyte in it. The builder declined to
repair and shipped the set; the gate called it a WARN. The decision is structural -- UCUM unit ->
property against each member's LOINC ``Has property`` -- and no analyte name is read.

Real sets, filters and LOINC axes from `tests/fixtures/a2_exception_unit_rows.json.gz` (sources by
sha256). No LLM and no database.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.services.loinc_specimen import LabTest
from src.utils.circe_lint import specimen_mismatched_measurement_criteria
from src.utils.criterion_refusal import CriterionRefused

FIXTURE = Path(__file__).parent / "fixtures" / "a2_exception_unit_rows.json.gz"


@pytest.fixture(scope="module")
def fx():
    return json.loads(gzip.open(FIXTURE).read())


class _FixtureLabVocabulary:
    def __init__(self, fx):
        self._tests = {int(k): LabTest(**v) for k, v in fx["lab"]["labTests"].items()}
        self._by_analyte = {
            a: [LabTest(**t) for t in tests] for a, tests in fx["lab"]["analyteLabTests"].items()
        }

    def lab_tests(self, ids):
        return {int(i): self._tests[int(i)] for i in ids if int(i) in self._tests}

    def analyte_lab_tests(self, analyte):
        return self._by_analyte.get(analyte, [])


def _case(fx, trial, role, cid):
    case = next(
        r for r in fx["rows"] if (r["trial"], r["role"], r["criterionId"]) == (trial, role, cid)
    )
    concept_set = case["a2Sets"][0]
    return case["row"], concept_set, concept_set["measurementFilters"][0]


def _expression(concept_set, value_filter):
    return {
        "ConceptSets": [
            {
                "id": concept_set["id"],
                "name": concept_set["name"],
                "expression": {"items": concept_set["items"]},
            }
        ],
        "PrimaryCriteria": {"CriteriaList": []},
        "InclusionRules": [
            {
                "name": concept_set["name"],
                "expression": {
                    "Type": "ALL",
                    "CriteriaList": [
                        {
                            "Criteria": {
                                "Measurement": {"CodesetId": concept_set["id"], **value_filter}
                            },
                            "StartWindow": {
                                "Start": {"Days": 180, "Coeff": -1},
                                "End": {"Days": 0, "Coeff": 1},
                            },
                            "Occurrence": {"Type": 2, "Count": 1},
                        }
                    ],
                    "DemographicCriteriaList": [],
                    "Groups": [],
                },
            }
        ],
    }


def _gate(fx, trial, role, cid):
    _row, concept_set, value_filter = _case(fx, trial, role, cid)
    vocabulary = _FixtureLabVocabulary(fx)
    ids = [i["concept"]["CONCEPT_ID"] for i in concept_set["items"]]
    return specimen_mismatched_measurement_criteria(
        _expression(concept_set, value_filter),
        vocabulary.lab_tests(ids),
        vocabulary.analyte_lab_tests,
    )


def test_should_fail_the_gate_when_the_stated_unit_contradicts_every_lab_test(fx):
    fail, warn = _gate(fx, "carolina", "inclusion", 27)
    assert warn == []
    assert len(fail) == 1 and "codeset 10 'eGFR'" in fail[0]


def test_should_pass_the_gate_when_the_stated_unit_is_the_members_property(fx):
    """EMPA-REG exclusion 9: GFR tests read in mL/min/(173.10*-2.m2) -- nothing to report."""
    assert _gate(fx, "empa-reg", "exclusion", 9) == ([], [])


def _service(fx):
    from src.services.tte_service import TTEService

    class _Stubbed(TTEService):
        def _lab_test_vocabulary(self):
            return _FixtureLabVocabulary(fx)

        def _specimen_judge(self, criterion):
            return lambda _analyte, _options: None

    return _Stubbed(store=MagicMock())


def test_should_refuse_the_criterion_when_its_unit_contradicts_every_lab_test(fx):
    row, concept_set, value_filter = _case(fx, "carolina", "inclusion", 27)
    with pytest.raises(CriterionRefused) as refused:
        _service(fx)._refine_measurement_specimen(
            {"items": concept_set["items"]},
            criteria_key="Measurement",
            criterion=row,
            value_filter=value_filter,
        )
    assert refused.value.code == "unit-contradicts-set"
    assert "Volume Rate/Area" in str(refused.value)


def test_should_keep_the_set_when_the_stated_unit_is_the_members_property(fx):
    row, concept_set, value_filter = _case(fx, "empa-reg", "exclusion", 9)
    refined, _record = _service(fx)._refine_measurement_specimen(
        {"items": concept_set["items"]},
        criteria_key="Measurement",
        criterion=row,
        value_filter=value_filter,
    )
    assert sorted(i["concept"]["CONCEPT_ID"] for i in refined["items"]) == sorted(
        i["concept"]["CONCEPT_ID"] for i in concept_set["items"]
    )
