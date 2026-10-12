"""Every span check compares a quoted fragment with a PDF line in one comparison form.

A protocol line extracted from a PDF keeps what the symbol font put there: private-use
glyphs (a symbol font's space or bullet, here U+F020) beside the ordinary spaces. A model
copying the line sees a space and types one. The segmentation step already compared its
fragments in a form that reads a private-use glyph as a space; the annotation fields, the
planner's spans and the re-checks at build and gate time folded only whitespace and case,
so a correctly copied fragment was rejected there and the field took its default.

THE LINE IS REAL: ARISTOTLE (NCT00412984) exclusion #52-#59 of the 2026-10-12 P2 NEW
store (``output/site_gap/2026-10-12_p2_new/store/studies.json``), shared by two groups;
member #55 is 'Total Bilirubin elevation'. Its comparator sits between two U+F020 glyphs.

What a check may tolerate is the machine format only. A fragment with a different word
still fails at every one of them.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.agents.agent1 import segmentation
from src.agents.planner.decomposer import _grounded_span, stated_member_value_constraint
from src.services.criterion_annotation import (
    ANNOTATION_KEY,
    ANNOTATION_PROMPT_VERSION,
    FIELD_QUANTITY_KIND,
    FIELD_REFERENCE_BOUND,
    FIELD_RELATION,
    FIELD_RELATION_SPAN,
    FIELD_THRESHOLD_SPAN,
    ThresholdUse,
    check_relation,
    threshold_use,
    validate_annotation,
)

ARISTOTLE_BILIRUBIN_LINE = (
    "17. ALT or AST > 2X ULN or a Total Bilirubin ≥ 1.5X ULN (unless an "
    "alternative causative factor [e.g., Gilbert’s syndrome] is identified)"
)

#: The fragments as a model copying the line types them: ordinary spaces where the PDF
#: has a glyph beside one.
THRESHOLD = "Total Bilirubin ≥ 1.5X ULN"
VALUE_TEXT = "≥ 1.5X ULN"
RELATION_SPAN = "ALT or AST > 2X ULN or a Total Bilirubin ≥ 1.5X ULN"

#: The same fragments with one word or bound changed: not in the line under any form.
OTHER_ANALYTE = "Direct Bilirubin ≥ 1.5X ULN"
OTHER_BOUND = "≥ 1.5X LLN"
OTHER_RELATION_SPAN = "ALT and AST > 2X ULN or a Total Bilirubin ≥ 1.5X ULN"


def _exclusion_55(threshold_span: str) -> dict[str, Any]:
    """Member #55 at its stored shape, carrying an annotation that quotes ``threshold_span``."""
    return {
        "id": 55,
        "description": "Total Bilirubin elevation",
        "domain": "Measurement",
        "sourceText": "Total Bilirubin",
        "protocolLine": ARISTOTLE_BILIRUBIN_LINE,
        "valueConstraint": {
            "op": "gte",
            "value": 1.5,
            "valueHigh": None,
            "unitText": "",
            "referenceBound": "uln",
            "unitConceptId": None,
        },
        "logicType": "ABSENCE",
        "groupId": "d1e70bfb-ed60-4fbe-b052-b5f0f63cd465",
        "groupType": "ALL",
        "isGroupLabel": False,
        "window": {"start": -180, "end": 0},
        ANNOTATION_KEY: {
            "promptVersion": ANNOTATION_PROMPT_VERSION,
            "model": "recorded",
            FIELD_THRESHOLD_SPAN: threshold_span,
            FIELD_QUANTITY_KIND: "lab_value",
            FIELD_REFERENCE_BOUND: "uln",
        },
    }


def _annotation_answer(threshold_span: str) -> dict[str, Any]:
    return {
        "record_requirement": "forbidden",
        FIELD_THRESHOLD_SPAN: threshold_span,
        FIELD_QUANTITY_KIND: "lab_value",
        FIELD_REFERENCE_BOUND: "uln",
    }


class TestTheAnnotationStep:
    def test_should_accept_the_threshold_span_when_the_line_has_glyphs_beside_its_spaces(self):
        fields, rejected = validate_annotation(
            _annotation_answer(THRESHOLD), ARISTOTLE_BILIRUBIN_LINE
        )

        assert [r for r in rejected if r["field"] != "record_requirement"] == []
        assert fields[FIELD_THRESHOLD_SPAN] == THRESHOLD

    def test_should_reject_the_threshold_span_when_it_names_another_analyte(self):
        fields, rejected = validate_annotation(
            _annotation_answer(OTHER_ANALYTE), ARISTOTLE_BILIRUBIN_LINE
        )

        assert fields[FIELD_THRESHOLD_SPAN] is None
        assert [r["field"] for r in rejected] == [FIELD_THRESHOLD_SPAN]

    def test_should_accept_the_relation_span_when_the_line_has_glyphs_beside_its_spaces(self):
        fields, rejection = check_relation(
            {FIELD_RELATION: "any", FIELD_RELATION_SPAN: RELATION_SPAN}, ARISTOTLE_BILIRUBIN_LINE
        )

        assert rejection is None
        assert (fields[FIELD_RELATION], fields[FIELD_RELATION_SPAN]) == ("any", RELATION_SPAN)

    def test_should_reject_the_relation_span_when_a_word_differs(self):
        fields, rejection = check_relation(
            {FIELD_RELATION: "any", FIELD_RELATION_SPAN: OTHER_RELATION_SPAN},
            ARISTOTLE_BILIRUBIN_LINE,
        )

        assert rejection is not None
        assert fields[FIELD_RELATION] is None


class TestTheStoredRowReCheck:
    """``threshold_use`` re-checks the stored span against the row's line; the build and
    the delivery gate (``scripts/verify_circe_delivery.py``) both decide through it."""

    def test_should_use_the_stated_threshold_when_the_line_has_glyphs_beside_its_spaces(self):
        use, stated = threshold_use(_exclusion_55(THRESHOLD))

        assert use is ThresholdUse.MEASURED
        assert (stated.span, stated.bound) == (THRESHOLD, "uln")

    def test_should_fall_back_to_the_default_when_the_stored_span_names_another_analyte(self):
        use, stated = threshold_use(_exclusion_55(OTHER_ANALYTE))

        assert (use, stated) == (ThresholdUse.DEFAULT, None)


class TestThePlanner:
    def test_should_ground_the_source_span_when_the_line_has_glyphs_beside_its_spaces(self):
        assert _grounded_span(THRESHOLD, ARISTOTLE_BILIRUBIN_LINE, "Total Bilirubin") == THRESHOLD

    def test_should_not_ground_a_source_span_that_names_another_analyte(self):
        assert _grounded_span(OTHER_ANALYTE, ARISTOTLE_BILIRUBIN_LINE, "Total Bilirubin") is None

    @pytest.mark.parametrize(
        "text, kept",
        [(VALUE_TEXT, True), (OTHER_BOUND, False)],
        ids=["copied", "other-bound"],
    )
    def test_should_keep_the_member_threshold_only_when_its_text_is_in_the_line(self, text, kept):
        member = {
            "value_constraint_text": text,
            "value_constraint": {"op": "gte", "value": 1.5, "reference_bound": "uln"},
        }

        constraint = stated_member_value_constraint(member, ARISTOTLE_BILIRUBIN_LINE)

        assert (constraint is not None) is kept


class TestSegmentationAgrees:
    def test_should_locate_the_same_fragment_in_the_document(self):
        """The comparison the other checks now share; segmentation already made it."""
        located = segmentation._Located(ARISTOTLE_BILIRUBIN_LINE)

        found = located.find(THRESHOLD, 0, len(ARISTOTLE_BILIRUBIN_LINE))

        assert found is not None
        start, end = found
        assert ARISTOTLE_BILIRUBIN_LINE[start:end] == "Total Bilirubin ≥ 1.5X ULN"
        assert located.find(OTHER_ANALYTE, 0, len(ARISTOTLE_BILIRUBIN_LINE)) is None
