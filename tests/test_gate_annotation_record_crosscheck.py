"""Gate check (ae): the expression's annotation record lists against the store rows.

The built expression lists, per criterion, what the annotation's agreement call (calls 1-2)
and the record_change calls (3-4) decided (``_annotationAgreementRecords``,
``_recordChangeRecords``). Each list is read off the store rows the expression was built from.
A file whose list lost a record, gained one, or carries a different one no longer says what the
store decided, and no other check compares the two.

Fixture: the A2 smoke (code be78c16), study 13 -- its store rows and the two lists of its
delivered ``declare_treatment.circe.json``, verbatim
(``tests/fixtures/a2_smoke_annotation_records.json``).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts.verify_circe_delivery import annotation_record_findings

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "a2_smoke_annotation_records.json").read_text()
)
AGREEMENT = "_annotationAgreementRecords"
RECORD_CHANGE = "_recordChangeRecords"


def _case():
    study = {"eligibility": copy.deepcopy(FIXTURE["eligibility"])}
    return copy.deepcopy(FIXTURE["expression"]), study


def test_should_pass_when_the_expression_lists_what_the_store_rows_record():
    expression, study = _case()
    assert len(expression[AGREEMENT]) == 25
    assert annotation_record_findings(expression, study) == []


def test_should_fail_when_the_expression_lost_one_agreement_record():
    expression, study = _case()
    removed = expression[AGREEMENT].pop(3)
    findings = annotation_record_findings(expression, study)
    assert len(findings) == 1
    assert f"{removed['role']} #{removed['criterionId']}" in findings[0]


def test_should_fail_when_the_expression_lists_a_record_no_store_row_carries():
    expression, study = _case()
    row = next(
        r for r in study["eligibility"]["inclusionCriteria"] if "_annotationAgreement" in r
    )
    del row["_annotationAgreement"]
    assert len(annotation_record_findings(expression, study)) == 1


def test_should_fail_when_a_listed_record_differs_from_its_store_row():
    expression, study = _case()
    expression[AGREEMENT][0]["outcome"] = "error"
    assert len(annotation_record_findings(expression, study)) == 1


def test_should_fail_when_the_expression_lacks_a_list_the_store_rows_fill():
    expression, study = _case()
    del expression[AGREEMENT]
    assert len(annotation_record_findings(expression, study)) == 1


def test_should_fail_when_a_record_change_record_is_missing_from_the_expression():
    """No row of the smoke has a call-4 answer, so the real row is given one call 3 failed for:
    such a row is listed (``record_change_records``), and the empty list now omits it."""
    expression, study = _case()
    assert expression[RECORD_CHANGE] == []
    row = next(
        r for r in study["eligibility"]["exclusionCriteria"] if "_recordChangeAgreement" in r
    )
    row["_recordChangeAgreement"]["outcome"] = "error"
    findings = annotation_record_findings(expression, study)
    assert len(findings) == 1
    assert f"exclusion #{row['id']}" in findings[0]


def test_should_fail_when_the_expression_lists_one_record_twice():
    expression, study = _case()
    expression[AGREEMENT].append(copy.deepcopy(expression[AGREEMENT][0]))
    assert len(annotation_record_findings(expression, study)) == 1
