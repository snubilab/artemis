"""``record_change``: a criterion whose protocol line requires its records to stay the same, or to
change, across a period is recorded as a skip, not emitted.

CIRCE (and OMOP) can test that a drug exposure exists in a window; it cannot test that the dose
stayed the same, or changed, across a period. Emitted, "Stable antidiabetic background medication
(unchanged daily dose) for at least 8 weeks" became a DrugExposure PRESENCE rule -- which says
only that some antidiabetic exposure exists. The meaning is the annotation model's: it fills
``record_change`` (``stable`` / ``changed`` / ``none``) and quotes ``record_change_span``; code
checks only that the fragment is a substring of ``protocolLine`` and compares enum values.

Measured (over-fill A/B, ``fields_stability`` arm, gemma-4-E4B): ``stable`` with a verified span
on all 9 go/no-go rows (27/27 answers), 0/96 fills on 32 controls, ``changed`` on the 6 thyroid
"change in dose" exclusions.

Rows here are real: ``tests/fixtures/rfc016_store_rows.json`` (CARMELINA inclusion 7, CAROLINA
inclusion 37 -- a group label -- and its member 38). The model answers are stubs; the real
answers on the real go/no-go rows are in ``tests/test_record_change_go_nogo.py``.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from src.services import criterion_annotation as annotation
from src.services.criterion_annotation import ANNOTATION_KEY, validate_annotation

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "rfc016_store_rows.json").read_text()
)
CARMELINA_7 = FIXTURE["carmelina_inclusion_7"]
CAROLINA_37 = FIXTURE["carolina_inclusion_37"]
CAROLINA_38 = FIXTURE["carolina_inclusion_38"]

#: A fragment of CARMELINA 7's own protocol line (the span the measured answers quote).
CARMELINA_SPAN = "(unchanged daily dose)"


def _line(row: dict[str, Any]) -> str:
    return row["protocolLine"]


def _own(rejected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rejections of the record_change field (an answer that omits record_requirement
    always carries that field's own rejection too)."""
    return [r for r in rejected if r["field"] == "record_change"]


def _with_annotation(row: dict[str, Any], **fields: Any) -> dict[str, Any]:
    out = deepcopy(row)
    for key in (ANNOTATION_KEY, "_annotationRejected", "_annotationAgreement"):
        out.pop(key, None)
    out[ANNOTATION_KEY] = {"promptVersion": annotation.ANNOTATION_PROMPT_VERSION, **fields}
    return out


# --------------------------------------------------------------------------- #
# The span check
# --------------------------------------------------------------------------- #


class TestTheSpanCheck:
    def test_should_keep_record_change_when_its_span_is_in_the_protocol_line(self):
        fields, rejected = validate_annotation(
            {"record_change": "stable", "record_change_span": CARMELINA_SPAN}, _line(CARMELINA_7)
        )
        assert (fields["record_change"], fields["record_change_span"]) == ("stable", CARMELINA_SPAN)
        assert _own(rejected) == []

    def test_should_drop_record_change_when_its_span_is_not_in_the_protocol_line(self):
        fields, rejected = validate_annotation(
            {"record_change": "stable", "record_change_span": "dose unchanged for 8 weeks"},
            _line(CARMELINA_7),
        )
        assert fields["record_change"] is None and fields["record_change_span"] is None
        (rejection,) = _own(rejected)
        assert "record_change_span is not a substring of protocolLine" in rejection["reason"]

    def test_should_keep_none_without_a_span(self):
        fields, rejected = validate_annotation(
            {"record_change": "none", "record_change_span": None}, _line(CARMELINA_7)
        )
        assert (fields["record_change"], fields["record_change_span"]) == ("none", None)
        assert _own(rejected) == []

    def test_should_reject_a_value_outside_the_three_when_the_model_invents_one(self):
        fields, rejected = validate_annotation(
            {"record_change": "unchanged", "record_change_span": CARMELINA_SPAN}, _line(CARMELINA_7)
        )
        assert fields["record_change"] is None
        assert len(_own(rejected)) == 1

    def test_should_leave_record_change_absent_when_the_answer_omits_it(self):
        fields, rejected = validate_annotation({}, _line(CARMELINA_7))
        assert fields["record_change"] is None and fields["record_change_span"] is None
        assert _own(rejected) == []


# --------------------------------------------------------------------------- #
# Agreement: a fill is kept only when the reworded second call fills it too
# --------------------------------------------------------------------------- #


def _validated(value: str | None, span: str | None = CARMELINA_SPAN) -> dict[str, Any]:
    payload = {} if value is None else {"record_change": value, "record_change_span": span}
    fields, _rejected = validate_annotation(payload, _line(CARMELINA_7))
    return fields


class TestAgreement:
    def test_should_ask_the_second_call_when_the_first_answer_fills_record_change(self):
        assert annotation.needs_agreement(_validated("stable"))
        assert annotation.needs_agreement(_validated("changed"))

    def test_should_not_ask_the_second_call_for_record_change_none(self):
        assert not annotation.needs_agreement(_validated("none", None))

    @pytest.mark.parametrize("second", ["stable", "changed"])
    def test_should_keep_the_first_answers_record_change_when_the_second_also_fills_one(
        self, second
    ):
        fields, kept, dropped = annotation.agree(
            _validated("stable"), _validated(second), _line(CARMELINA_7)
        )
        assert (fields["record_change"], fields["record_change_span"]) == ("stable", CARMELINA_SPAN)
        assert kept["record_change"] == {"value": "stable", "span": CARMELINA_SPAN}
        assert "record_change" not in dropped

    @pytest.mark.parametrize("second", ["none", None])
    def test_should_drop_record_change_when_the_second_answer_does_not_fill_it(self, second):
        fields, kept, dropped = annotation.agree(
            _validated("stable"), _validated(second, None), _line(CARMELINA_7)
        )
        assert fields["record_change"] is None and fields["record_change_span"] is None
        assert dropped["record_change"] == {"value": "stable", "span": CARMELINA_SPAN}
        assert "record_change" not in kept

    def test_should_drop_record_change_when_the_second_call_failed(self):
        fields, _kept, dropped = annotation.agree(_validated("stable"), {}, _line(CARMELINA_7))
        assert fields["record_change"] is None
        assert dropped["record_change"]["value"] == "stable"


# --------------------------------------------------------------------------- #
# Which rows the build skips
# --------------------------------------------------------------------------- #


class TestRecordChangeSkips:
    def test_should_skip_a_row_whose_annotation_says_stable_with_a_span_in_its_line(self):
        row = _with_annotation(
            CARMELINA_7, record_change="stable", record_change_span=CARMELINA_SPAN
        )
        skip = annotation.record_change_skips([row])[str(row["id"])]
        assert (skip.value, skip.span) == ("stable", CARMELINA_SPAN)
        assert skip.decided_by == str(row["id"])

    def test_should_skip_a_row_whose_annotation_says_changed(self):
        row = _with_annotation(
            CARMELINA_7, record_change="changed", record_change_span=CARMELINA_SPAN
        )
        assert annotation.record_change_skips([row])[str(row["id"])].value == "changed"

    @pytest.mark.parametrize(
        "fields",
        [
            {"record_change": "none", "record_change_span": None},
            {"record_change": None, "record_change_span": None},
            {},
            # a stored span that is not in the line is re-checked here and decides nothing
            {"record_change": "stable", "record_change_span": "unchanged dose"},
        ],
        ids=["none", "absent-value", "no-field", "span-not-in-line"],
    )
    def test_should_not_skip_a_row_without_a_verified_fill(self, fields):
        assert annotation.record_change_skips([_with_annotation(CARMELINA_7, **fields)]) == {}

    def test_should_take_the_members_with_it_when_a_group_label_says_stable(self):
        """CAROLINA inclusion 37 is the group label of 38: the members are what the label
        describes, so they go with it, as for a conditional label."""
        label = _with_annotation(
            CAROLINA_37, record_change="stable", record_change_span=CARMELINA_SPAN
        )
        member = _with_annotation(CAROLINA_38)
        skips = annotation.record_change_skips([label, member])
        assert set(skips) == {str(label["id"]), str(member["id"])}
        assert skips[str(member["id"])].decided_by == str(label["id"])

    def test_should_carry_the_agreement_call_that_confirmed_it(self):
        row = _with_annotation(
            CARMELINA_7, record_change="stable", record_change_span=CARMELINA_SPAN
        )
        row["_annotationAgreement"] = {
            "promptVersion": annotation.AGREEMENT_PROMPT_VERSION,
            "cacheKey": "k2",
            "kept": {"record_change": {"value": "stable", "span": CARMELINA_SPAN}},
            "dropped": {},
        }
        skip = annotation.record_change_skips([row])[str(row["id"])]
        assert (skip.agreement_version, skip.agreement_key) == (
            annotation.AGREEMENT_PROMPT_VERSION,
            "k2",
        )


# --------------------------------------------------------------------------- #
# The delivery gate's permit
# --------------------------------------------------------------------------- #


class TestTheDeliveryGatePermit:
    def _record(self, row: dict[str, Any], **extra: Any) -> dict[str, Any]:
        return {
            "criterionId": str(row["id"]),
            "role": "inclusion",
            "label": row.get("sourceText") or row.get("description") or "",
            "isGroupLabel": bool(row.get("isGroupLabel")),
            "reason": annotation.RECORD_CHANGE_REASON,
            **extra,
        }

    def _violations(self, records: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[str]:
        from scripts.verify_circe_delivery import criteria_index, skipped_criteria_violations

        study = {"eligibility": {"inclusionCriteria": rows, "exclusionCriteria": []}}
        expression = {"_unmappedCriteria": [], "_skippedCriteria": records}
        return skipped_criteria_violations(records, criteria_index(study), expression)

    def test_should_be_a_permitted_skip_reason(self):
        from scripts.verify_circe_delivery import ALLOWED_SKIP_REASONS

        assert annotation.RECORD_CHANGE_REASON in ALLOWED_SKIP_REASONS

    def test_should_pass_a_record_whose_span_is_in_the_deciding_rows_line(self):
        record = self._record(
            CARMELINA_7,
            recordChangeSpan=CARMELINA_SPAN,
            recordChangeDecidedBy=str(CARMELINA_7["id"]),
        )
        assert self._violations([record], [deepcopy(CARMELINA_7)]) == []

    def test_should_pass_a_member_decided_by_its_group_label(self):
        record = self._record(
            CAROLINA_38,
            recordChangeSpan="(unchanged daily dose)",
            recordChangeDecidedBy=str(CAROLINA_37["id"]),
        )
        assert self._violations([record], [deepcopy(CAROLINA_37), deepcopy(CAROLINA_38)]) == []

    def test_should_fail_a_record_whose_span_is_not_in_the_line(self):
        record = self._record(
            CARMELINA_7,
            recordChangeSpan="dose unchanged for 8 weeks",
            recordChangeDecidedBy=str(CARMELINA_7["id"]),
        )
        (violation,) = self._violations([record], [deepcopy(CARMELINA_7)])
        assert f"recorded as {annotation.RECORD_CHANGE_REASON} but its span" in violation

    def test_should_fail_a_record_with_no_span(self):
        record = self._record(CARMELINA_7, recordChangeDecidedBy=str(CARMELINA_7["id"]))
        (violation,) = self._violations([record], [deepcopy(CARMELINA_7)])
        assert "its span None" in violation


# --------------------------------------------------------------------------- #
# The prompts
# --------------------------------------------------------------------------- #


class TestThePrompts:
    @pytest.mark.parametrize("name", ["ANNOTATION_PROMPT", "AGREEMENT_PROMPT"])
    def test_should_ask_record_change_once_in_both_calls(self, name):
        template = getattr(annotation, name)
        assert template.count("`record_change` states whether") == 1
        assert template.count('"record_change": "<stable|changed|none>"') == 1
        span_key = '"record_change_span": "<fragment of the protocol line, or null>"'
        assert template.count(span_key) == 1

    def test_should_bump_both_prompt_versions(self):
        assert annotation.ANNOTATION_PROMPT_VERSION != "rfc016-steps1-4-agreement-v1"
        assert annotation.AGREEMENT_PROMPT_VERSION != "rfc016-steps1-4-agreement-placebo-v1"
        assert annotation.ANNOTATION_PROMPT_VERSION != annotation.AGREEMENT_PROMPT_VERSION
