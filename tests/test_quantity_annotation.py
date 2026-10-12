"""RFC-016 step 3: ``quantity_kind``, ``reference_bound`` and ``threshold_span``.

Every case is a real row (``tests/fixtures/rfc016_quantity_rows.json``: the 2026-10-12
prompt_f2 candidate store and the P2 NEW store, each with its SHA-256). The model is a stub;
nothing here reaches an LLM.

What is pinned at this layer:

* the annotation prompt defines the three fields (definitions only) and its version moved,
  so no cached step-1 answer is replayed for a prompt that now asks more;
* the three fields stand or fall together: they are kept only when ``threshold_span`` is a
  substring of ``protocolLine`` and both enums hold a value of their own list; anything else
  leaves all three absent and records why;
* the reader re-checks the span against the row's line, so a hand-edited row cannot carry
  an unchecked threshold into the build.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src.services import criterion_annotation as annotation_mod
from src.services.criterion_annotation import (
    ANNOTATION_KEY,
    ANNOTATION_PROMPT,
    ANNOTATION_PROMPT_VERSION,
    ANNOTATION_REJECTED_KEY,
    QuantityKind,
    StatedThreshold,
    annotate_row,
    stated_threshold,
    validate_annotation,
)

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "rfc016_quantity_rows.json").read_text()
)
ARISTOTLE_ALT = FIXTURE["aristotle_exclusion"][1]  # exclusion 2, 'ALT > 2X ULN'
CAROLINA_32 = FIXTURE["carolina_inclusion"][1]  # inclusion 32, compliance, no valueConstraint

#: Fragments of those rows' own protocol lines.
ALT_SPAN = "> 2X ULN"
COMPLIANCE_SPAN = "between 80% and 120%"


def _threshold(span: Any, kind: Any, bound: Any) -> dict[str, Any]:
    return {
        "record_requirement": "forbidden",
        "conditional_span": None,
        "excepted_entities": [],
        "base_span": None,
        "threshold_span": span,
        "quantity_kind": kind,
        "reference_bound": bound,
    }


def _annotated(row: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    row = deepcopy(row)
    fields, rejected = validate_annotation(payload, row["protocolLine"])
    row[ANNOTATION_KEY] = {"promptVersion": "test", "model": "stub", **fields}
    if rejected:
        row[ANNOTATION_REJECTED_KEY] = rejected
    return row


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_ANNOTATION_CACHE_PATH", str(tmp_path / "annotations.jsonl"))
    monkeypatch.delenv("ARTEMIS_ANNOTATION_CACHE", raising=False)
    annotation_mod.reset_for_tests()
    yield
    annotation_mod.reset_for_tests()


def test_should_have_real_rows_whose_spans_are_in_their_own_lines():
    """Guards the fixture itself: the spans below are copied from these lines."""
    assert ALT_SPAN in ARISTOTLE_ALT["protocolLine"]
    assert COMPLIANCE_SPAN in CAROLINA_32["protocolLine"]
    assert CAROLINA_32["valueConstraint"] is None


class TestThePromptAsksForTheThreeFields:
    def test_should_define_each_field_and_each_value(self):
        for token in (
            "threshold_span", "quantity_kind", "reference_bound",
            "lab_value", "dose", "duration", "count", "statistical", "other",
            "uln", "lln", "none",
        ):
            assert f"`{token}`" in ANNOTATION_PROMPT, token

    def test_should_not_replay_a_step_one_answer_for_the_longer_prompt(self):
        assert ANNOTATION_PROMPT_VERSION != "rfc016-step1-v1"


class TestTheThreeFieldsStandOrFallTogether:
    def test_should_keep_them_when_the_span_is_in_the_line(self):
        fields, rejected = validate_annotation(
            _threshold(ALT_SPAN, "lab_value", "uln"), ARISTOTLE_ALT["protocolLine"]
        )
        assert rejected == []
        assert (fields["threshold_span"], fields["quantity_kind"], fields["reference_bound"]) == (
            ALT_SPAN, "lab_value", "uln",
        )

    def test_should_drop_all_three_and_record_it_when_the_span_is_not_in_the_line(self):
        fields, rejected = validate_annotation(
            _threshold("> 3X ULN", "lab_value", "uln"), ARISTOTLE_ALT["protocolLine"]
        )
        assert (fields["threshold_span"], fields["quantity_kind"], fields["reference_bound"]) == (
            None, None, None,
        )
        assert [r["field"] for r in rejected] == ["threshold_span"]
        # The other fields of the same answer are untouched by the threshold's rejection.
        assert fields["record_requirement"] == "forbidden"

    @pytest.mark.parametrize(
        ("kind", "bound", "field"),
        [("laboratory", "uln", "quantity_kind"), ("lab_value", "upper", "reference_bound")],
    )
    def test_should_drop_all_three_when_an_enum_holds_a_value_of_no_list(self, kind, bound, field):
        fields, rejected = validate_annotation(
            _threshold(ALT_SPAN, kind, bound), ARISTOTLE_ALT["protocolLine"]
        )
        assert fields["threshold_span"] is None and fields["quantity_kind"] is None
        assert [r["field"] for r in rejected] == [field]

    def test_should_record_a_kind_given_without_a_span(self):
        fields, rejected = validate_annotation(
            _threshold(None, "lab_value", "none"), ARISTOTLE_ALT["protocolLine"]
        )
        assert fields["quantity_kind"] is None and fields["reference_bound"] is None
        assert [r["field"] for r in rejected] == ["quantity_kind"]

    def test_should_record_nothing_when_the_line_states_no_threshold(self):
        fields, rejected = validate_annotation(
            _threshold(None, None, None), ARISTOTLE_ALT["protocolLine"]
        )
        assert rejected == []
        assert fields["threshold_span"] is None


class TestTheReaderRechecksTheSpan:
    def test_should_return_the_verified_threshold(self):
        row = _annotated(CAROLINA_32, _threshold(COMPLIANCE_SPAN, "other", "none"))
        assert stated_threshold(row) == StatedThreshold(
            span=COMPLIANCE_SPAN, kind=QuantityKind.OTHER, bound="absolute"
        )

    def test_should_return_nothing_for_a_row_edited_after_annotation(self):
        row = _annotated(CAROLINA_32, _threshold(COMPLIANCE_SPAN, "other", "none"))
        row["protocolLine"] = "Treatment compliance in the placebo run-in"
        assert stated_threshold(row) is None

    def test_should_return_nothing_for_a_row_with_no_annotation(self):
        assert stated_threshold(CAROLINA_32) is None


class _StubLLM:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def invoke(self, messages: list[Any]) -> AIMessage:
        self.calls.append("\n\n".join(str(m.content) for m in messages))
        return AIMessage(content=json.dumps(self.payload))


def test_should_store_the_three_fields_on_the_row():
    row = deepcopy(ARISTOTLE_ALT)
    llm = _StubLLM(_threshold(ALT_SPAN, "lab_value", "uln"))
    assert annotate_row(row, [], "exclusion", model="stub", llm=llm) == "called"
    stored = row[ANNOTATION_KEY]
    assert (stored["threshold_span"], stored["quantity_kind"], stored["reference_bound"]) == (
        ALT_SPAN, "lab_value", "uln",
    )
    assert stored["promptVersion"] == ANNOTATION_PROMPT_VERSION
    assert ANNOTATION_REJECTED_KEY not in row
