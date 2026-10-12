"""RFC-016 step 2 (RFC-014): the annotation's ``relation`` and ``timing`` fields.

Every row is real, copied verbatim into ``tests/fixtures/rfc016_relation_timing_rows.json``
(source paths and SHA-256 inside it): the 2026-10-12 prompt_f2 candidate store, and one row
of the 2026-10-12 P2 re-extraction. The model is a stub; nothing reaches an LLM.

What is pinned:

* ``relation`` / ``relation_span`` / ``cardinality`` and ``timing`` / ``window_span`` are kept
  only when their fragment is a substring of the row's ``protocolLine``; otherwise the field
  is absent and the rejection is recorded on the row;
* :func:`stated_relation` reads the planner's relation first and the annotation's only when
  the planner left none, each re-checked against the line;
* :func:`prospective_skips` decides from the annotation alone, and a prospective group label
  takes its members with it;
* a verified ``window_span`` whose own duration disagrees with the extracted window is
  recorded on the row (report only; the window is not changed).
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src.services import criterion_annotation as annotation_mod

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "rfc016_relation_timing_rows.json").read_text()
)
CAROLINA_HEAD = FIXTURE["carolina_inclusion_1"]
CAROLINA_REVASC = FIXTURE["carolina_exclusion_25"]
CAROLINA_OBESITY = FIXTURE["carolina_exclusion_8"]
LEADER_OADS = FIXTURE["leader_inclusion_12"]
PLATO_TWO_OF = FIXTURE["plato_inclusion_32"]
PLATO_FIBRINOLYTIC = FIXTURE["plato_exclusion_15"][0]
P2_ARISTOTLE_CHF = FIXTURE["p2_aristotle_inclusion_4"][0]

#: Fragments of the rows' own protocol lines.
HEAD_RELATION_SPAN = (
    "T2DM and concurrently insufficient glycaemic control and a high risk of CV events"
)
OADS_RELATION_SPAN = (
    "Anti-diabetic drug naive or treated with one or more oral anti-diabetic drugs (OADs)"
)
REVASC_PLANNED_SPAN = (
    "Pre-planned coronary artery re-vascularisation (PCI, CABG) within next 6 months after V1a"
)
REVASC_PRIOR_SPAN = "≤ 6 weeks prior informed consent"


def _payload(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"record_requirement": "required", "excepted_entities": []}
    base.update(fields)
    return base


def _annotated(row: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    row = deepcopy(row)
    fields, rejected = annotation_mod.validate_annotation(payload, row["protocolLine"])
    row[annotation_mod.ANNOTATION_KEY] = {"promptVersion": "test", "model": "stub", **fields}
    if rejected:
        row[annotation_mod.ANNOTATION_REJECTED_KEY] = rejected
    return row


class _StubLLM:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def invoke(self, messages: list[Any]) -> AIMessage:
        self.calls.append("\n\n".join(str(m.content) for m in messages))
        return AIMessage(content=json.dumps(self.payload))


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_ANNOTATION_CACHE_PATH", str(tmp_path / "annotations.jsonl"))
    monkeypatch.delenv("ARTEMIS_ANNOTATION_CACHE", raising=False)
    annotation_mod.reset_for_tests()
    yield
    annotation_mod.reset_for_tests()


class TestRelationSpanCheck:
    def test_should_keep_relation_all_when_its_span_is_in_the_line(self):
        fields, rejected = annotation_mod.validate_annotation(
            _payload(relation="all", relation_span=HEAD_RELATION_SPAN),
            CAROLINA_HEAD[0]["protocolLine"],
        )
        assert rejected == []
        assert (fields["relation"], fields["relation_span"], fields["cardinality"]) == (
            "all",
            HEAD_RELATION_SPAN,
            None,
        )

    def test_should_reject_relation_when_its_span_is_not_in_the_line(self):
        fields, rejected = annotation_mod.validate_annotation(
            _payload(relation="all", relation_span="T2DM and insufficient glycaemic control"),
            CAROLINA_HEAD[0]["protocolLine"],
        )
        assert fields["relation"] is None
        assert fields["relation_span"] is None
        assert [r["field"] for r in rejected] == ["relation"]

    def test_should_keep_at_least_with_its_cardinality_when_the_span_is_in_the_line(self):
        fields, rejected = annotation_mod.validate_annotation(
            _payload(relation="at_least", relation_span="≥2 of the following", cardinality=2),
            PLATO_TWO_OF[0]["protocolLine"],
        )
        assert rejected == []
        assert (fields["relation"], fields["cardinality"]) == ("at_least", 2)

    def test_should_reject_at_least_when_it_carries_no_cardinality(self):
        fields, rejected = annotation_mod.validate_annotation(
            _payload(relation="at_least", relation_span="≥2 of the following", cardinality=None),
            PLATO_TWO_OF[0]["protocolLine"],
        )
        assert fields["relation"] is None
        assert [r["field"] for r in rejected] == ["relation"]

    def test_should_reject_a_relation_outside_the_three_when_the_model_invents_one(self):
        fields, rejected = annotation_mod.validate_annotation(
            _payload(relation="either", relation_span=OADS_RELATION_SPAN),
            LEADER_OADS[0]["protocolLine"],
        )
        assert fields["relation"] is None
        assert [r["field"] for r in rejected] == ["relation"]

    def test_should_record_no_rejection_when_the_model_leaves_relation_null(self):
        fields, rejected = annotation_mod.validate_annotation(
            _payload(relation=None, relation_span=None), LEADER_OADS[0]["protocolLine"]
        )
        assert rejected == []
        assert fields["relation"] is None


class TestTimingSpanCheck:
    def test_should_keep_prospective_when_its_span_is_in_the_line(self):
        fields, rejected = annotation_mod.validate_annotation(
            _payload(timing="prospective", window_span=REVASC_PLANNED_SPAN),
            CAROLINA_REVASC[0]["protocolLine"],
        )
        assert rejected == []
        assert (fields["timing"], fields["window_span"]) == ("prospective", REVASC_PLANNED_SPAN)

    def test_should_reject_prospective_when_its_span_is_not_in_the_line(self):
        fields, rejected = annotation_mod.validate_annotation(
            _payload(timing="prospective", window_span="planned within the next 6 months"),
            CAROLINA_REVASC[0]["protocolLine"],
        )
        assert (fields["timing"], fields["window_span"]) == (None, None)
        assert [r["field"] for r in rejected] == ["timing"]

    def test_should_reject_prospective_when_it_quotes_no_span(self):
        fields, rejected = annotation_mod.validate_annotation(
            _payload(timing="prospective", window_span=None), CAROLINA_REVASC[0]["protocolLine"]
        )
        assert fields["timing"] is None
        assert [r["field"] for r in rejected] == ["timing"]

    def test_should_keep_prior_without_a_span_when_the_line_states_no_time(self):
        fields, rejected = annotation_mod.validate_annotation(
            _payload(timing="prior", window_span=None), LEADER_OADS[0]["protocolLine"]
        )
        assert rejected == []
        assert (fields["timing"], fields["window_span"]) == ("prior", None)

    def test_should_reject_a_timing_outside_the_three_when_the_model_invents_one(self):
        fields, rejected = annotation_mod.validate_annotation(
            _payload(timing="future", window_span=REVASC_PLANNED_SPAN),
            CAROLINA_REVASC[0]["protocolLine"],
        )
        assert fields["timing"] is None
        assert [r["field"] for r in rejected] == ["timing"]


class TestStatedRelation:
    def test_should_read_the_annotation_relation_when_the_planner_left_none(self):
        label = _annotated(
            LEADER_OADS[0], _payload(relation="any", relation_span=OADS_RELATION_SPAN)
        )
        stated = annotation_mod.stated_relation(label)
        assert (stated.relation, stated.span, stated.source) == (
            "any",
            OADS_RELATION_SPAN,
            "annotation",
        )

    def test_should_prefer_the_planner_relation_when_both_are_verified(self):
        label = _annotated(
            CAROLINA_HEAD[0], _payload(relation="any", relation_span="T2DM and concurrently")
        )
        label[annotation_mod.PLANNER_RELATION_KEY] = {
            "relation": "all",
            "relation_span": HEAD_RELATION_SPAN,
            "cardinality": None,
        }
        stated = annotation_mod.stated_relation(label)
        assert (stated.relation, stated.source) == ("all", "planner")

    def test_should_fall_back_to_the_annotation_when_the_planner_span_is_not_in_the_line(self):
        label = _annotated(
            CAROLINA_HEAD[0], _payload(relation="all", relation_span=HEAD_RELATION_SPAN)
        )
        label[annotation_mod.PLANNER_RELATION_KEY] = {
            "relation": "any",
            "relation_span": "T2DM or glycaemic control",
            "cardinality": None,
        }
        stated = annotation_mod.stated_relation(label)
        assert (stated.relation, stated.source) == ("all", "annotation")

    def test_should_state_nothing_when_no_relation_was_verified(self):
        assert annotation_mod.stated_relation(deepcopy(CAROLINA_HEAD[0])) is None


class TestProspectiveSkips:
    def test_should_take_the_members_with_it_when_the_group_label_is_prospective(self):
        label = _annotated(
            CAROLINA_REVASC[0], _payload(timing="prospective", window_span=REVASC_PLANNED_SPAN)
        )
        rows = [label, deepcopy(CAROLINA_REVASC[1]), deepcopy(CAROLINA_REVASC[2])]
        skips = annotation_mod.prospective_skips(rows)
        assert set(skips) == {"25", "26", "27"}
        assert {s.decided_by for s in skips.values()} == {"25"}
        assert skips["27"].span == REVASC_PLANNED_SPAN

    def test_should_skip_nothing_when_the_timing_was_rejected(self):
        label = _annotated(
            CAROLINA_REVASC[0], _payload(timing="prospective", window_span="planned in 6 months")
        )
        assert annotation_mod.prospective_skips([label, *deepcopy(CAROLINA_REVASC[1:])]) == {}

    def test_should_skip_nothing_when_the_label_is_prior(self):
        label = _annotated(
            CAROLINA_REVASC[0], _payload(timing="prior", window_span=REVASC_PRIOR_SPAN)
        )
        assert annotation_mod.prospective_skips([label, *deepcopy(CAROLINA_REVASC[1:])]) == {}


class TestWindowDisagreementIsRecorded:
    """Report only: the extracted window is never rewritten here."""

    def _annotate(self, row: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        row = deepcopy(row)
        annotation_mod.annotate_row(row, [], "inclusion", model="stub", llm=_StubLLM(payload))
        return row

    def test_should_record_a_disagreement_when_three_months_was_extracted_as_three_days(self):
        row = self._annotate(
            P2_ARISTOTLE_CHF, _payload(timing="prior", window_span="within 3 months")
        )
        assert row["window"] == {"start": -3, "end": 0}
        record = row[annotation_mod.WINDOW_DISAGREEMENT_KEY]
        assert record["windowSpan"] == "within 3 months"
        assert record["statedDays"] == [90]
        assert record["window"] == {"start": -3, "end": 0}

    def test_should_record_a_disagreement_when_24_hours_was_extracted_as_24_days(self):
        row = self._annotate(
            PLATO_FIBRINOLYTIC, _payload(timing="prior", window_span="within the previous 24 h")
        )
        assert row[annotation_mod.WINDOW_DISAGREEMENT_KEY]["statedDays"] == [1]

    def test_should_record_nothing_when_the_window_agrees_with_its_span(self):
        row = self._annotate(
            CAROLINA_OBESITY[0],
            _payload(timing="prior", window_span="within 3 months prior to informed consent"),
        )
        assert row["window"] == {"start": -90, "end": 0}
        assert annotation_mod.WINDOW_DISAGREEMENT_KEY not in row

    def test_should_record_nothing_when_the_timing_is_prospective(self):
        row = self._annotate(
            CAROLINA_REVASC[0], _payload(timing="prospective", window_span=REVASC_PLANNED_SPAN)
        )
        assert annotation_mod.WINDOW_DISAGREEMENT_KEY not in row

    def test_should_record_nothing_when_the_span_states_no_duration(self):
        row = self._annotate(
            LEADER_OADS[0], _payload(timing="prior", window_span="Anti-diabetic drug naive")
        )
        assert annotation_mod.WINDOW_DISAGREEMENT_KEY not in row


class TestThePromptAsksForTheNewFields:
    def test_should_render_the_members_and_store_every_field_when_annotating_a_label(self):
        label, *members = deepcopy(LEADER_OADS)
        llm = _StubLLM(
            _payload(
                relation="any",
                relation_span=OADS_RELATION_SPAN,
                timing="prior",
                window_span=None,
            )
        )
        annotation_mod.annotate_row(label, members, "inclusion", model="stub", llm=llm)
        stored = label[annotation_mod.ANNOTATION_KEY]
        assert stored["relation"] == "any"
        assert stored["timing"] == "prior"
        assert stored["promptVersion"] != "rfc016-step1-v1"
        for member in members:
            assert member["description"] in llm.calls[0]
