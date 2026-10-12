"""Gate check (j), RFC-016 step 3: a verified threshold with no emitted value filter fails.

The check used to read the rule name and the concept-set name for words that "assert" a
bound (A29, ``_BOUND_ASSERTION_RE``). It now reads the store row's annotation: a
``threshold_span`` that is a substring of the row's ``protocolLine`` says the protocol
states a threshold for that criterion, and the file must then carry a value condition on
the criteria over the criterion's own concept set -- or record the threshold under
``_unrepresentableThresholds`` when the annotation says no value filter represents it,
which the gate re-derives from the store row rather than reading off the record.

Producer to gate: every expression here is built by ``_build_seeded_target_circe`` from real
rows (``tests/fixtures/rfc016_quantity_rows.json``) with the mapper stubbed, and handed to
the gate with the store study those rows came from.
"""

from __future__ import annotations

import json
import zlib
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from scripts.verify_circe_delivery import threshold_without_value_filter_findings
from src.services.criterion_annotation import (
    ANNOTATION_KEY,
    UNREPRESENTABLE_THRESHOLDS_KEY,
    validate_annotation,
)
from src.services.tte_service import TTEService
from src.utils.circe_lint import CRITERION_CONCEPT_SET_REFS_KEY

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "rfc016_quantity_rows.json").read_text()
)
PLATO = {row["id"]: row for row in FIXTURE["plato_inclusion"]}
CAROLINA = {row["id"]: row for row in FIXTURE["carolina_inclusion"]}
LEADER_5 = FIXTURE["leader_exclusion_5"]
CARMELINA_16 = FIXTURE["carmelina_inclusion_16"]

COMPLIANCE_SPAN = "between 80% and 120%"


def _annotated(row: dict[str, Any], span: Any, kind: Any, bound: Any) -> dict[str, Any]:
    row = deepcopy(row)
    payload = {
        "record_requirement": "required",
        "threshold_span": span,
        "quantity_kind": kind,
        "reference_bound": bound,
    }
    fields, rejected = validate_annotation(payload, row["protocolLine"])
    assert rejected == [], rejected
    row[ANNOTATION_KEY] = {"promptVersion": "test", "model": "stub", **fields}
    return row


class _Agent2IsStubbed:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Agent 2 is stubbed out in this test")


@pytest.fixture
def service(monkeypatch) -> TTEService:
    monkeypatch.setattr("src.agents.agent2.workflow.Agent2Workflow", _Agent2IsStubbed)
    monkeypatch.setattr("src.agents.agent2.query_expander.QueryExpander", _Agent2IsStubbed)
    monkeypatch.setattr("src.agents.agent2.retriever.ConceptRetriever", _Agent2IsStubbed)
    svc = TTEService.__new__(TTEService)

    def fake_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
        seed = seed_text.strip()
        concept_id = zlib.crc32(seed.encode()) % 10**8
        domain = kwargs.get("expected_domain") or "Measurement"
        return {
            "name": seed,
            "domain": domain,
            "expression": {
                "items": [
                    {
                        "concept": {
                            "CONCEPT_ID": concept_id, "CONCEPT_NAME": seed,
                            "CONCEPT_CODE": str(concept_id), "DOMAIN_ID": domain,
                            "VOCABULARY_ID": "SNOMED", "CONCEPT_CLASS_ID": "Clinical Finding",
                        },
                        "includeDescendants": True,
                        "isExcluded": False,
                    }
                ]
            },
            "mapping_metadata": None,
        }

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
    monkeypatch.setattr(svc, "_concept_set_lab_properties", lambda expression: {})
    return svc


def _delivered(service: TTEService, inclusion=(), exclusion=()) -> tuple[dict, dict]:
    """The built expression and the store study it was built from."""
    eligibility = {
        "targetCohortName": "target",
        "inclusionCriteria": deepcopy(list(inclusion)),
        "exclusionCriteria": deepcopy(list(exclusion)),
    }
    expression = service._build_seeded_target_circe(deepcopy(eligibility))
    return expression, {"id": 1, "eligibility": eligibility}


class TestALabThreshold:
    def test_should_fail_when_the_criterion_emitted_no_value_filter(self, service):
        """CAROLINA inclusion 32: the band survives only in the line, the row carries no
        number, and as a lab value it is emitted bare."""
        row = _annotated(CAROLINA[32], COMPLIANCE_SPAN, "lab_value", "none")
        expression, study = _delivered(service, inclusion=[row])
        [finding] = threshold_without_value_filter_findings(expression, study)
        assert "inclusion #32" in finding
        assert COMPLIANCE_SPAN in finding
        assert "lab_value" in finding

    def test_should_pass_when_the_criterion_carries_its_filter(self, service):
        row = _annotated(PLATO[29], "greater than the upper limit of normal", "lab_value", "uln")
        expression, study = _delivered(service, inclusion=[row])
        assert threshold_without_value_filter_findings(expression, study) == []


class TestAThresholdNoValueFilterRepresents:
    """PLATO inclusion 26, "carotid stenosis (≥50%)" on a Condition row."""

    def test_should_pass_when_the_file_records_it(self, service):
        row = _annotated(PLATO[26], "(≥50%)", "other", "none")
        expression, study = _delivered(service, inclusion=[row])
        assert [r["criterionId"] for r in expression[UNREPRESENTABLE_THRESHOLDS_KEY]] == ["26"]
        assert threshold_without_value_filter_findings(expression, study) == []

    def test_should_fail_when_the_file_does_not_record_it(self, service):
        row = _annotated(PLATO[26], "(≥50%)", "other", "none")
        expression, study = _delivered(service, inclusion=[row])
        expression[UNREPRESENTABLE_THRESHOLDS_KEY] = []
        [finding] = threshold_without_value_filter_findings(expression, study)
        assert "inclusion #26" in finding and UNREPRESENTABLE_THRESHOLDS_KEY in finding

    def test_should_fail_when_the_store_row_says_it_is_a_lab_value(self, service):
        """The record is a permit, re-derived: a file built from one reading cannot pass
        against a store whose annotation says the other."""
        built_from = _annotated(PLATO[26], "(≥50%)", "other", "none")
        expression, _ = _delivered(service, inclusion=[built_from])
        store_row = _annotated(PLATO[26], "(≥50%)", "lab_value", "none")
        study = {"id": 1, "eligibility": {"inclusionCriteria": [store_row]}}
        assert len(threshold_without_value_filter_findings(expression, study)) == 1


class TestTheNameIsNotRead:
    """A29 deleted. The candidate gate's four (j) findings were these two rows on both arms:
    LEADER exclusion 5 ('Elevated HbA1c') and CARMELINA inclusion 16 ('Impaired renal
    function (UACR)'). Neither protocol line states a number."""

    @pytest.mark.parametrize("row", [LEADER_5, CARMELINA_16], ids=["leader-5", "carmelina-16"])
    def test_should_not_fire_on_a_name_when_the_line_states_no_threshold(self, service, row):
        role = "exclusion" if row is LEADER_5 else "inclusion"
        unannotated = dict(deepcopy(row), groupId=None, isGroupLabel=False)
        annotated = _annotated(unannotated, None, None, None)
        for candidate in (unannotated, annotated):
            expression, study = _delivered(service, **{role: [candidate]})
            assert expression["InclusionRules"], "the row must emit for the check to judge it"
            assert threshold_without_value_filter_findings(expression, study) == []


def test_should_fail_closed_when_the_file_cannot_say_what_it_emitted(service):
    row = _annotated(CAROLINA[32], COMPLIANCE_SPAN, "lab_value", "none")
    expression, study = _delivered(service, inclusion=[row])
    expression.pop(CRITERION_CONCEPT_SET_REFS_KEY)
    [finding] = threshold_without_value_filter_findings(expression, study)
    assert CRITERION_CONCEPT_SET_REFS_KEY in finding


def test_should_say_nothing_when_no_store_row_states_a_threshold(service):
    expression, study = _delivered(service, inclusion=[CAROLINA[32]])
    expression.pop(CRITERION_CONCEPT_SET_REFS_KEY)
    assert threshold_without_value_filter_findings(expression, study) == []
