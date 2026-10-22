"""A `forbidden` criterion whose own entity only a trial can produce is refused, not mapped.

K1/K2 of P7/P8 SEG-OFF (`output/site_gap/2026-10-18_p7_segoff/PREDICTIONS.md` K1): CAROLINA
exclusion 35 'participation in another trail with IMP given 2 months before ... (IMP) start' shipped
its member 'IMP given 2 months before IMP start' on 4082400 'Administration of prophylactic drug or
medicament', and ARISTOTLE exclusion 20 shipped 'Investigational device use' on one junk concept.
Both rows were agreed `forbidden` with `no_entity: none`. Calls 5/6 (`entity_outside_trial`) do not
reach them: asked of them, both answered `yes`, because that definition says "this trial" and both
products belong to another (fix-k12 measurement, 2026-10-22). A forbidden row now gets its own call
pair, `trial_only` (:data:`TRIAL_ONLY_PROMPT`, :data:`TRIAL_ONLY_AGREEMENT_PROMPT`): does the entity
exist only because the patient takes part in a clinical trial, any trial. When both wordings answer
`yes`, the row is refused before mapping with the one code the delivery gate permits, its span as
the detail. Calls 5/6 and their prompts are untouched.

Rows are the P8 MAIN store's (`output/site_gap/2026-10-20_p8_segoff/arm_main/store/studies.json`).
The model is replaced by a replay; nothing reaches a network.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src.services import criterion_annotation as annotation
from src.services.tte_service import _refuse_line_naming_no_entity
from src.utils.criterion_refusal import REFUSAL_UNMAPPABLE_PLACEHOLDER, CriterionRefused

K1_LINE = (
    "35. participation in another trail with IMP given 2 months before Investigational "
    "Medicinal/Medical Product (IMP) start"
)
K1_SPAN = "IMP given 2 months before Investigational Medicinal/Medical Product (IMP) start"
FORBIDDEN = {"record_requirement": "forbidden", "no_entity": "none", "timing": "prior"}


def _k1_row() -> dict[str, Any]:
    return {
        "id": 81, "description": "IMP given 2 months before IMP start", "domain": "Drug",
        "sourceText": K1_SPAN, "protocolLine": K1_LINE, "protocolSpan": K1_SPAN,
        "window": {"start": -60, "end": 0}, "logicType": "ABSENCE",
        "groupId": "24ea5c9f", "isGroupLabel": False,
    }


class _Replay:
    def __init__(self, first: dict[str, Any], outside: tuple[str, str]) -> None:
        self.first = first
        self.outside = outside
        self.kinds: list[str] = []

    def invoke(self, messages: list[Any]) -> AIMessage:
        system, prompt = str(messages[0].content), str(messages[1].content)
        first = system == annotation.ANNOTATION_SYSTEM_PROMPT
        if "entity_outside_trial" in prompt:
            raise AssertionError("calls 5/6 asked of a forbidden row")
        if "trial_only" in prompt:
            kind = "check1" if first else "check2"
            reply = {"trial_only": self.outside[0 if first else 1]}
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


def _annotate(row: dict[str, Any], outside: tuple[str, str], first=FORBIDDEN) -> _Replay:
    llm = _Replay(first, outside)
    annotation.annotate_row(row, [], "exclusion", model="stub", llm=llm)
    return llm


def test_should_refuse_a_forbidden_row_when_both_wordings_say_only_a_trial_produces_it():
    row = _k1_row()
    _annotate(row, ("yes", "yes"))
    with pytest.raises(CriterionRefused) as refused:
        _refuse_line_naming_no_entity(row, "IMP given 2 months before IMP start")
    assert refused.value.code == REFUSAL_UNMAPPABLE_PLACEHOLDER
    assert refused.value.detail == K1_SPAN


def test_should_keep_a_forbidden_row_when_the_two_wordings_disagree():
    row = _k1_row()
    _annotate(row, ("yes", "no"))
    _refuse_line_naming_no_entity(row, "x")  # no raise
    assert annotation.stated_trial_only(row) is None


def test_should_ask_the_second_wording_only_to_confirm_a_yes():
    row = _k1_row()
    llm = _annotate(row, ("no", "yes"))
    assert "check1" in llm.kinds and "check2" not in llm.kinds
    _refuse_line_naming_no_entity(row, "x")


def test_should_not_ask_a_required_row():
    row = _k1_row()
    llm = _annotate(row, ("yes", "yes"), first={**FORBIDDEN, "record_requirement": "required"})
    assert not {"check1", "check2"} & set(llm.kinds)
    _refuse_line_naming_no_entity(row, "x")


def test_should_not_ask_a_group_label_that_has_members():
    """A label with members is never mapped, so a refusal there would change nothing."""
    row = {**_k1_row(), "isGroupLabel": True, "protocolSpan": ""}
    llm = _Replay(FORBIDDEN, ("yes", "yes"))
    member = _k1_row()
    annotation.annotate_row(row, [member], "exclusion", model="stub", llm=llm)
    assert not {"check1", "check2"} & set(llm.kinds)


def test_should_fall_back_to_the_line_when_the_span_is_not_in_it():
    row = {**_k1_row(), "protocolSpan": "not in the line"}
    _annotate(row, ("yes", "yes"))
    assert annotation.stated_trial_only(row) == K1_LINE


def test_should_ask_the_trial_only_pair_with_no_example():
    """Field definitions only; the example guard lints the rendered prompts too."""
    for prompt in (annotation.TRIAL_ONLY_PROMPT, annotation.TRIAL_ONLY_AGREEMENT_PROMPT):
        assert "trial_only" in prompt and "entity_outside_trial" not in prompt
