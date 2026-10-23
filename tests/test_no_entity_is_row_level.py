"""A row is refused as naming no entity only when its OWN part of the line is the placeholder.

P11 MAIN (``output/site_gap/2026-10-22_p11_secnest/arm_main``, code 3a253a4) refused CARMELINA
exclusions 25 'Alcohol use disorder' and 26 'Substance use disorder' as ``unmappable-placeholder``
(investigator_judgement: 'in the opinion of the investigator'), and 38/40 cancer on the clause
'or has any other condition than mentioned which in the opinion of the investigator, ...'. Each
row is annotated on its own, but both wordings answer for the LINE: every row of line 10 and of
line 13 carries the same judgement fragment, and :func:`agree` keeps it wherever it lies in the
line. So one clause of a line refused every row extracted from it, and gold 98 (substance abuse)
went unmatched in every P10/P11 arm.

The rule now reads the row's own verified span (``protocolSpan``) against that fragment:

* own span overlapping the fragment, or not verifiable: refused as before, nothing asked;
* own span wholly outside it: calls 9/10 (:data:`OWN_ENTITY_PROMPT`,
  :data:`OWN_ENTITY_AGREEMENT_PROMPT`) are shown that span and asked whether it names a clinical
  entity a vocabulary could hold. The row is no longer refused only when both answer ``named``;
  a store annotated before this (no record) keeps the refusal.

Rows are P11 MAIN's. The model is replaced by a replay; nothing reaches a network.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src.services import criterion_annotation as annotation
from src.services.tte_service import _refuse_line_naming_no_entity
from src.utils.criterion_refusal import REFUSAL_UNMAPPABLE_PLACEHOLDER, CriterionRefused

CARMELINA_10 = (
    "10. Any previous or current alcohol or drug abuse that would interfere with trial "
    "participation in the opinion of the investigator"
)
CARMELINA_13 = (
    "13. Patients considered unreliable by the investigator concerning the requirements for "
    "followup during the study and/or compliance with study drug administration, have a life "
    "expectancy less than 5 years for non-CV causes, or have cancer other than nonmelanoma skin "
    "cancer within last 3 years, or has any other condition than mentioned which in the opinion of "
    "the investigator, would not allow safe participation in the study"
)
CAROLINA_23 = (
    "23. Patients considered unreliable by the investigator concerning the requirements for "
    "follow-up during the study and/or compliance with study drug administration, has a life "
    "expectancy less than 5 years for non-CV causes, or has cancer other than non-melanoma skin "
    "cancer within last 3 years, or has any other condition than mentioned which in the opinion of "
    "the investigator, would not allow safe participation in the study"
)
OPINION = "in the opinion of the investigator"
ANY_OTHER = (
    "or has any other condition than mentioned which in the opinion of the investigator, would "
    "not allow safe participation in the study"
)
CAROLINA_58_FRAGMENT = "in the opinion of the investigator, would not allow safe participation"


def _row(rid: int, source: str, line: str, own: str) -> dict[str, Any]:
    return {
        "id": rid, "description": source, "domain": "Condition", "sourceText": source,
        "protocolLine": line, "protocolSpan": own, "window": {"start": -9999, "end": 0},
        "logicType": "ABSENCE", "groupId": "g", "isGroupLabel": False,
    }


CARMELINA_25 = ("CARMELINA exclusion 25", _row(25, "Alcohol use disorder", CARMELINA_10, "alcohol"),
                OPINION)
CARMELINA_41 = ("CARMELINA exclusion 41", _row(
    41, "Condition preventing safe study participation", CARMELINA_13,
    "any other condition than mentioned which in the opinion of the investigator, would not allow "
    "safe participation in the study"), ANY_OTHER)
CAROLINA_58 = ("CAROLINA exclusion 58", _row(
    58, "Patient considered unreliable by the investigator", CAROLINA_23,
    "Patients considered unreliable by the investigator concerning the requirements for follow-up "
    "during the study and/or compliance with study drug administration"), CAROLINA_58_FRAGMENT)


class _Replay:
    """Calls 1/2 answer the row's P11 annotation; calls 9/10 answer ``own``."""

    def __init__(self, fragment: str, own: tuple[str, str]) -> None:
        self.first = {"record_requirement": "forbidden", "timing": "prior",
                      "no_entity": "investigator_judgement", "no_entity_span": fragment}
        self.own = own
        self.kinds: list[str] = []

    def invoke(self, messages: list[Any]) -> AIMessage:
        system, prompt = str(messages[0].content), str(messages[1].content)
        first = system == annotation.ANNOTATION_SYSTEM_PROMPT
        if "own_entity" in prompt:
            kind = "own1" if first else "own2"
            reply: dict[str, Any] = {"own_entity": self.own[0 if first else 1]}
        elif "trial_only" in prompt:
            kind, reply = "trial", {"trial_only": "no"}
        elif annotation.RECORD_CHANGE_PROMPT_BLOCK.split("\n")[0] in prompt:
            kind, reply = ("cf" if first else "pf"), {"record_change": "none"}
        else:
            kind, reply = ("current" if first else "placebo"), self.first
        self.kinds.append(kind)
        return AIMessage(content=json.dumps(reply))


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_ANNOTATION_CACHE_PATH", str(tmp_path / "annotations.jsonl"))
    monkeypatch.delenv("ARTEMIS_ANNOTATION_CACHE", raising=False)
    annotation.reset_for_tests()
    yield
    annotation.reset_for_tests()


def _annotate(case, own: tuple[str, str]) -> tuple[dict[str, Any], _Replay]:
    _name, row, fragment = case
    row = dict(row)
    llm = _Replay(fragment, own)
    annotation.annotate_row(row, [], "exclusion", model="stub", llm=llm)
    return row, llm


def test_should_map_a_row_whose_own_span_lies_outside_the_judgement_when_both_wordings_name_it():
    row, llm = _annotate(CARMELINA_25, ("named", "named"))

    assert {"own1", "own2"} <= set(llm.kinds)
    assert annotation.stated_no_entity(row) is None
    _refuse_line_naming_no_entity(row, "Alcohol use disorder")  # no raise


def test_should_refuse_a_row_whose_own_span_is_the_judgement_without_asking():
    row, llm = _annotate(CARMELINA_41, ("named", "named"))

    assert not {"own1", "own2"} & set(llm.kinds)
    with pytest.raises(CriterionRefused) as refused:
        _refuse_line_naming_no_entity(row, "Condition preventing safe study participation")
    assert refused.value.code == REFUSAL_UNMAPPABLE_PLACEHOLDER


@pytest.mark.parametrize("own, asked", [
    (("not_named", "named"), {"own1"}),
    (("named", "not_named"), {"own1", "own2"}),
], ids=["first says not named", "wordings disagree"])
def test_should_keep_the_refusal_when_the_own_span_is_not_named_by_both(own, asked):
    row, llm = _annotate(CAROLINA_58, own)

    assert {k for k in llm.kinds if k.startswith("own")} == asked
    with pytest.raises(CriterionRefused):
        _refuse_line_naming_no_entity(row, "Patient considered unreliable by the investigator")


def test_should_keep_the_refusal_when_the_row_was_annotated_before_the_own_entity_check():
    _name, row, fragment = CARMELINA_25
    row = {**row, "annotation": {"no_entity": "investigator_judgement", "no_entity_span": fragment}}

    with pytest.raises(CriterionRefused):
        _refuse_line_naming_no_entity(row, "Alcohol use disorder")


def test_should_keep_the_refusal_when_the_recorded_own_span_no_longer_is_the_rows():
    row, _llm = _annotate(CARMELINA_25, ("named", "named"))
    row["protocolSpan"] = "drug abuse"

    with pytest.raises(CriterionRefused):
        _refuse_line_naming_no_entity(row, "Alcohol use disorder")
