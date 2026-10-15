"""``record_change``: asked in calls of its own; a stable/changed row is recorded as a skip.

CIRCE (and OMOP) can test that a drug exposure exists in a window; it cannot test that the dose
stayed the same, or changed, across a period. Emitted, "Stable antidiabetic background medication
(unchanged daily dose) for at least 8 weeks" became a DrugExposure PRESENCE rule -- which says
only that some antidiabetic exposure exists. The meaning is the annotation model's: it fills
``record_change`` (``stable`` / ``changed`` / ``none``) and quotes ``record_change_span``; code
checks only that the fragment is a substring of ``protocolLine`` and compares enum values.

Four calls per row (coordinator, 2026-10-15). Calls 1 and 2 are stage 2's measured `current` and
`placebo` prompts, unchanged, and decide every field except ``record_change``. Call 3 is `cf`
(`current` with the record_change block) on every row with a line, and only its
``record_change`` / ``record_change_span`` are read; call 4 is `pf` (`placebo` with the block),
made only when call 3 fills one, and the fill is kept only when call 4 also fills one. Putting
the block into calls 1 and 2 instead shifted ``record_requirement`` toward ``conditional`` in both
wordings at once (re-check ``cfpf_20261015_075611``: 4/113 correct exceptions and 4/138 rr
controls broken), which agreement cannot filter.

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
from langchain_core.messages import AIMessage

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
#: The record row key and the four calls' versions.
RECORD_KEY = "_recordChangeAgreement"
#: b027a7d's versions: calls 1 and 2 are its prompts, byte for byte, used the same way.
CALL_1_2_VERSIONS = ("rfc016-steps1-4-agreement-v1", "rfc016-steps1-4-agreement-placebo-v1")


def _line(row: dict[str, Any]) -> str:
    return row["protocolLine"]


def _own(rejected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rejected if r["field"] == "record_change"]


def _with_annotation(row: dict[str, Any], **fields: Any) -> dict[str, Any]:
    out = deepcopy(row)
    for key in (ANNOTATION_KEY, "_annotationRejected", "_annotationAgreement", RECORD_KEY):
        out.pop(key, None)
    out[ANNOTATION_KEY] = {"promptVersion": annotation.ANNOTATION_PROMPT_VERSION, **fields}
    return out


# --------------------------------------------------------------------------- #
# The span check of calls 3 and 4
# --------------------------------------------------------------------------- #


class TestTheSpanCheck:
    def test_should_keep_record_change_when_its_span_is_in_the_protocol_line(self):
        fields, rejected = annotation.validate_record_change(
            {"record_change": "stable", "record_change_span": CARMELINA_SPAN}, _line(CARMELINA_7)
        )
        assert fields == {"record_change": "stable", "record_change_span": CARMELINA_SPAN}
        assert rejected == []

    def test_should_drop_record_change_when_its_span_is_not_in_the_protocol_line(self):
        fields, rejected = annotation.validate_record_change(
            {"record_change": "stable", "record_change_span": "dose unchanged for 8 weeks"},
            _line(CARMELINA_7),
        )
        assert fields == {"record_change": None, "record_change_span": None}
        (rejection,) = _own(rejected)
        assert "record_change_span is not a substring of protocolLine" in rejection["reason"]

    def test_should_keep_none_without_a_span(self):
        fields, rejected = annotation.validate_record_change(
            {"record_change": "none", "record_change_span": None}, _line(CARMELINA_7)
        )
        assert fields == {"record_change": "none", "record_change_span": None}
        assert rejected == []

    def test_should_reject_a_value_outside_the_three_when_the_model_invents_one(self):
        fields, rejected = annotation.validate_record_change(
            {"record_change": "unchanged", "record_change_span": CARMELINA_SPAN}, _line(CARMELINA_7)
        )
        assert fields["record_change"] is None
        assert len(_own(rejected)) == 1

    def test_should_leave_record_change_absent_when_the_answer_omits_it(self):
        fields, rejected = annotation.validate_record_change({}, _line(CARMELINA_7))
        assert fields == {"record_change": None, "record_change_span": None}
        assert rejected == []

    def test_should_not_read_record_change_from_the_answer_of_calls_one_and_two(self):
        fields, _rejected = validate_annotation(
            {"record_change": "stable", "record_change_span": CARMELINA_SPAN}, _line(CARMELINA_7)
        )
        assert "record_change" not in fields and "record_change_span" not in fields


class TestTheRule:
    @pytest.mark.parametrize("second", ["stable", "changed"])
    def test_should_keep_call_threes_value_when_call_four_also_fills_one(self, second):
        first = {"record_change": "stable", "record_change_span": CARMELINA_SPAN}
        fields, kept, dropped = annotation.agree_record_change(
            first, {"record_change": second, "record_change_span": CARMELINA_SPAN}
        )
        assert fields == first
        assert kept == {"record_change": {"value": "stable", "span": CARMELINA_SPAN}}
        assert dropped == {}

    @pytest.mark.parametrize("second", [{"record_change": "none"}, {"record_change": None}, {}])
    def test_should_drop_the_fill_when_call_four_does_not_fill_one(self, second):
        first = {"record_change": "stable", "record_change_span": CARMELINA_SPAN}
        fields, kept, dropped = annotation.agree_record_change(first, second)
        assert fields == {"record_change": None, "record_change_span": None}
        assert kept == {}
        assert dropped == {"record_change": {"value": "stable", "span": CARMELINA_SPAN}}


# --------------------------------------------------------------------------- #
# The four calls of one row
# --------------------------------------------------------------------------- #


class _Router:
    """The chat model, replaced: answers each call by which of the four prompts it was sent.

    ``answers`` maps ``1``-``4`` to a payload (dict) or an Exception; a call whose number has no
    answer fails the test."""

    def __init__(self, row: dict[str, Any], answers: dict[int, Any]) -> None:
        self.answers = answers
        self.prompts = {
            number: (system, annotation.render_prompt(row, [], "inclusion", template))
            for number, (system, template) in {
                1: (annotation.ANNOTATION_SYSTEM_PROMPT, annotation.ANNOTATION_PROMPT),
                2: (annotation.AGREEMENT_SYSTEM_PROMPT, annotation.AGREEMENT_PROMPT),
                3: (annotation.RECORD_CHANGE_SYSTEM_PROMPT, annotation.RECORD_CHANGE_PROMPT),
                4: (
                    annotation.RECORD_CHANGE_AGREEMENT_SYSTEM_PROMPT,
                    annotation.RECORD_CHANGE_AGREEMENT_PROMPT,
                ),
            }.items()
        }
        self.calls: list[int] = []

    def invoke(self, messages: list[Any]) -> AIMessage:
        sent = tuple(str(m.content) for m in messages)
        (number,) = [n for n, prompt in self.prompts.items() if prompt == sent]
        self.calls.append(number)
        answer = self.answers[number]
        if isinstance(answer, Exception):
            raise answer
        return AIMessage(content=json.dumps(answer))


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_ANNOTATION_CACHE_PATH", str(tmp_path / "annotations.jsonl"))
    monkeypatch.delenv("ARTEMIS_ANNOTATION_CACHE", raising=False)
    annotation.reset_for_tests()
    yield
    annotation.reset_for_tests()


STABLE = {"record_change": "stable", "record_change_span": CARMELINA_SPAN}
REQUIRED = {"record_requirement": "required", "excepted_entities": []}


def _run(answers: dict[int, Any]) -> tuple[dict[str, Any], _Router]:
    row = deepcopy(CARMELINA_7)
    llm = _Router(row, answers)
    annotation.annotate_row(row, [], "inclusion", model="stub", llm=llm)
    return row, llm


class TestTheCalls:
    def test_should_ask_call_three_on_a_row_whose_calls_one_and_two_fill_nothing(self):
        row, llm = _run({1: REQUIRED, 3: {"record_change": "none"}})
        assert llm.calls == [1, 3]
        assert row[ANNOTATION_KEY]["record_change"] == "none"
        record = row[RECORD_KEY]
        assert record["promptVersion"] == annotation.RECORD_CHANGE_PROMPT_VERSION
        assert record["second"] is None

    def test_should_ask_call_four_when_call_three_fills_and_keep_the_fill_both_give(self):
        row, llm = _run({1: REQUIRED, 3: STABLE, 4: STABLE})
        assert llm.calls == [1, 3, 4]
        stored = row[ANNOTATION_KEY]
        assert (stored["record_change"], stored["record_change_span"]) == ("stable", CARMELINA_SPAN)
        record = row[RECORD_KEY]
        assert record["kept"]["record_change"]["value"] == "stable"
        second = record["second"]
        assert second["promptVersion"] == annotation.RECORD_CHANGE_AGREEMENT_PROMPT_VERSION

    def test_should_drop_the_fill_when_call_four_says_none(self):
        row, _llm = _run({1: REQUIRED, 3: STABLE, 4: {"record_change": "none"}})
        assert row[ANNOTATION_KEY]["record_change"] is None
        assert row[RECORD_KEY]["dropped"]["record_change"]["value"] == "stable"

    def test_should_drop_the_fill_and_record_the_error_when_call_four_fails(self, tmp_path):
        row, _llm = _run({1: REQUIRED, 3: STABLE, 4: RuntimeError("vLLM went away")})
        assert row[ANNOTATION_KEY]["record_change"] is None
        record = row[RECORD_KEY]
        second = record["second"]
        assert second["outcome"] == "error" and "vLLM went away" in second["error"]
        cached = [json.loads(x) for x in (tmp_path / "annotations.jsonl").read_text().splitlines()]
        assert annotation.RECORD_CHANGE_AGREEMENT_PROMPT_VERSION not in {
            r["promptVersion"] for r in cached
        }

    def test_should_record_the_error_and_fill_nothing_when_call_three_fails(self):
        row, llm = _run({1: REQUIRED, 3: RuntimeError("vLLM went away")})
        assert llm.calls == [1, 3]
        assert row[ANNOTATION_KEY]["record_change"] is None
        assert row[ANNOTATION_KEY]["record_requirement"] == "required"
        assert row[RECORD_KEY]["outcome"] == "error"

    def test_should_take_nothing_but_record_change_from_call_three(self):
        """Call 3 is the whole `cf` prompt, so it answers every field; only record_change is
        read. Call 1 decides the rest -- here it fills nothing, and nothing appears."""
        cf_answer = {
            **STABLE,
            "record_requirement": "conditional",
            "conditional_span": CARMELINA_SPAN,
            "excepted_entities": [{"text": "x", "span": CARMELINA_SPAN}],
            "base_span": "Stable antidiabetic background medication",
            "no_entity": "investigator_judgement",
            "no_entity_span": CARMELINA_SPAN,
        }
        row, llm = _run({1: REQUIRED, 3: cf_answer, 4: STABLE})
        assert llm.calls == [1, 3, 4]
        stored = row[ANNOTATION_KEY]
        assert stored["record_requirement"] == "required"
        assert stored["excepted_entities"] == [] and stored["base_span"] is None
        assert stored["no_entity"] is None
        assert stored["record_change"] == "stable"
        assert "_annotationAgreement" not in row

    def test_should_take_no_record_change_from_call_one(self):
        row, llm = _run({1: {**REQUIRED, **STABLE}, 3: {"record_change": "none"}})
        assert llm.calls == [1, 3]
        assert row[ANNOTATION_KEY]["record_change"] == "none"

    def test_should_cache_each_call_under_its_own_key_and_version(self, tmp_path):
        answers = {1: {**REQUIRED, "no_entity": "investigator_judgement",
                       "no_entity_span": CARMELINA_SPAN},
                   2: {**REQUIRED, "no_entity": "investigator_judgement",
                       "no_entity_span": CARMELINA_SPAN},
                   3: STABLE, 4: STABLE}
        first, llm = _run(answers)
        again, replay = _run(answers)
        assert sorted(llm.calls) == [1, 2, 3, 4] and replay.calls == []
        assert again[ANNOTATION_KEY] == first[ANNOTATION_KEY]
        cached = [json.loads(x) for x in (tmp_path / "annotations.jsonl").read_text().splitlines()]
        assert len({r["key"] for r in cached}) == 4
        assert {r["promptVersion"] for r in cached} == {
            *CALL_1_2_VERSIONS,
            annotation.RECORD_CHANGE_PROMPT_VERSION,
            annotation.RECORD_CHANGE_AGREEMENT_PROMPT_VERSION,
        }
        assert again[RECORD_KEY]["outcome"] == "cached"


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

    def test_should_carry_the_call_that_confirmed_it(self):
        row = _with_annotation(
            CARMELINA_7, record_change="stable", record_change_span=CARMELINA_SPAN
        )
        row[RECORD_KEY] = {
            "promptVersion": annotation.RECORD_CHANGE_PROMPT_VERSION,
            "cacheKey": "k3",
            "kept": {"record_change": {"value": "stable", "span": CARMELINA_SPAN}},
            "dropped": {},
            "second": {
                "promptVersion": annotation.RECORD_CHANGE_AGREEMENT_PROMPT_VERSION,
                "cacheKey": "k4",
            },
        }
        skip = annotation.record_change_skips([row])[str(row["id"])]
        assert (skip.agreement_version, skip.agreement_key) == (
            annotation.RECORD_CHANGE_AGREEMENT_PROMPT_VERSION,
            "k4",
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


DEFINITION = "`record_change` states whether"
KEYS = (
    '"record_change": "<stable|changed|none>", '
    '"record_change_span": "<fragment of the protocol line, or null>", '
)


class TestThePrompts:
    @pytest.mark.parametrize("name", ["ANNOTATION_PROMPT", "AGREEMENT_PROMPT"])
    def test_should_not_ask_record_change_in_calls_one_and_two(self, name):
        template = getattr(annotation, name)
        assert DEFINITION not in template and KEYS not in template

    @pytest.mark.parametrize(
        ("name", "base"),
        [("RECORD_CHANGE_PROMPT", "ANNOTATION_PROMPT"),
         ("RECORD_CHANGE_AGREEMENT_PROMPT", "AGREEMENT_PROMPT")],
    )
    def test_should_be_calls_one_and_two_with_the_block_and_its_keys_alone(self, name, base):
        template = getattr(annotation, name)
        assert template.count(DEFINITION) == 1 and template.count(KEYS) == 1
        without = template.replace(annotation.RECORD_CHANGE_PROMPT_BLOCK, "", 1)
        without = without.replace(KEYS, "", 1)
        assert without == getattr(annotation, base)

    def test_should_keep_b027a7ds_versions_for_calls_one_and_two_and_own_ones_for_three_and_four(
        self,
    ):
        assert (annotation.ANNOTATION_PROMPT_VERSION, annotation.AGREEMENT_PROMPT_VERSION) == (
            CALL_1_2_VERSIONS
        )
        versions = {
            annotation.ANNOTATION_PROMPT_VERSION,
            annotation.AGREEMENT_PROMPT_VERSION,
            annotation.RECORD_CHANGE_PROMPT_VERSION,
            annotation.RECORD_CHANGE_AGREEMENT_PROMPT_VERSION,
        }
        assert len(versions) == 4
