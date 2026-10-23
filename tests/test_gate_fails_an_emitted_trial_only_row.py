"""Check (ae): a row both trial_only wordings call trial-only must not reach a rule.

Structural, from the store row's own `_trialOnlyCheck` record (calls 7/8) and the file's
`_criterionConceptSetRefs` -- no concept name is read. P8 MAIN CARMELINA inclusion 8 (#19
'Informed Consent Provision') emitted rule 6 over consent-verification procedures; with calls
7/8 asked of required rows the builder refuses such a row, and this check fails a file in which
one was emitted anyway (an old build, or a builder path that skipped the refusal).
"""
from __future__ import annotations

from typing import Any

from src.services.criterion_annotation import TRIAL_ONLY_CHECK_KEY
from src.utils.circe_lint import CRITERION_CONCEPT_SET_REFS_KEY, trial_only_occurrence_criteria

LINE = (
    "8. Signed and dated written informed consent by date of Visit 1(screening) in accordance with "
    "Good Clinical Practice (GCP) and local legislation prior to any study related procedure"
)


def _study(trial_only: bool) -> dict[str, Any]:
    row = {"id": 19, "description": "Informed Consent Provision", "protocolLine": LINE,
           TRIAL_ONLY_CHECK_KEY: {"fragment": LINE, "calls": [], "trialOnly": trial_only}}
    return {"eligibility": {"inclusionCriteria": [row], "exclusionCriteria": []}}


def _expression() -> dict[str, Any]:
    entry = {"Criteria": {"ProcedureOccurrence": {"CodesetId": 10}}}
    rule = {"name": "Informed Consent Provision",
            "expression": {"Type": "ALL", "CriteriaList": [entry]}}
    return {"InclusionRules": [rule], CRITERION_CONCEPT_SET_REFS_KEY: {"inclusion:19": 10}}


def test_should_fail_an_emitted_row_both_wordings_call_trial_only():
    findings = trial_only_occurrence_criteria(_expression(), _study(True))
    assert len(findings) == 1 and "inclusion #19" in findings[0]


def test_should_pass_the_row_when_the_wordings_did_not_both_say_trial_only():
    assert trial_only_occurrence_criteria(_expression(), _study(False)) == []


def test_should_pass_the_row_when_it_was_refused_and_never_emitted():
    expression = {**_expression(), CRITERION_CONCEPT_SET_REFS_KEY: {}}
    assert trial_only_occurrence_criteria(expression, _study(True)) == []
