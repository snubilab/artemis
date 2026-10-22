"""``window_bound``: which side of a stated length of time a criterion's entity falls on.

CAROLINA inclusion 7 ("Ischemic or hemorrhagic stroke (> 3 months prior to informed consent)") was
extracted with window ``{start: -90, end: 0}`` -- "within 3 months", the protocol inverted. The
IR window carries two numbers and no side, so a "more than N before" bound and a "within N" bound
were the same shape. Calls 9 and 10 ask ``window_bound`` (``within`` / ``beyond`` / ``none``)
with a quoted span; code checks only that the span is in ``protocolLine`` and holds a number and a
time unit. When both wordings say ``beyond`` the build emits the window ending ``N`` days before
index (:func:`annotated_window`).

Also: the existing ``window_disagreement`` report, which already saw CARMELINA exclusion 28's
"within next 12 months" against its ``{-12, 0}`` window and changed nothing, now has its stated
duration used for the window's one finite bound.

Rows are real: ``tests/fixtures/window_bound_rows.json`` (P8 MAIN/PLACEBO stores). The model
answers are stubs; the live answers are in the commit's validation table.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src.services import criterion_annotation as annotation
from src.services.criterion_annotation import ANNOTATION_KEY
from src.services.tte_service import TTEService

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "window_bound_rows.json").read_text()
)
STROKE = FIXTURE["carolina_inclusion_15"]
PCI = FIXTURE["carolina_inclusion_13"]
CABG = FIXTURE["carolina_inclusion_14"]
ARISTOTLE_38 = FIXTURE["aristotle_exclusion_38"]
CARMELINA_28 = FIXTURE["carmelina_exclusion_28"]
CARMELINA_28_ALL_HISTORY = FIXTURE["carmelina_exclusion_28_placebo"]
PLATO_39 = FIXTURE["plato_exclusion_39"]

STROKE_SPAN = "> 3 months prior to informed consent"
BEYOND = {"window_bound": "beyond", "window_bound_span": STROKE_SPAN}


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_ANNOTATION_CACHE_PATH", str(tmp_path / "annotations.jsonl"))
    monkeypatch.delenv("ARTEMIS_ANNOTATION_CACHE", raising=False)
    annotation.reset_for_tests()
    yield
    annotation.reset_for_tests()


class _Router:
    """The chat model, replaced: answers calls 9 and 10 from ``answers``, every other call with
    an answer that fills nothing."""

    def __init__(self, row: dict[str, Any], answers: dict[int, Any]) -> None:
        self.answers = answers
        self.prompts = {
            number: (system, annotation.render_prompt(row, [], "inclusion", template))
            for number, (system, template) in {
                9: (annotation.WINDOW_BOUND_SYSTEM_PROMPT, annotation.WINDOW_BOUND_PROMPT),
                10: (
                    annotation.WINDOW_BOUND_AGREEMENT_SYSTEM_PROMPT,
                    annotation.WINDOW_BOUND_AGREEMENT_PROMPT,
                ),
            }.items()
        }
        self.calls: list[int] = []

    def invoke(self, messages: list[Any]) -> AIMessage:
        sent = tuple(str(m.content) for m in messages)
        numbers = [n for n, prompt in self.prompts.items() if prompt == sent]
        if not numbers:
            return AIMessage(content=json.dumps({"record_requirement": "required"}))
        (number,) = numbers
        self.calls.append(number)
        return AIMessage(content=json.dumps(self.answers[number]))


def _annotate(row: dict[str, Any], answers: dict[int, Any]) -> tuple[dict[str, Any], _Router]:
    row = deepcopy(row)
    timing = (row.get(ANNOTATION_KEY) or {}).get("timing")
    llm = _Router(row, answers)
    annotation.annotate_row(row, [], "inclusion", model="stub", llm=llm)
    # The stub fills nothing for calls 1 and 2; keep the stored timing so the row reads as P8's.
    row[ANNOTATION_KEY]["timing"] = timing
    return row, llm


class TestTheSpanCheck:
    def test_should_keep_beyond_when_its_span_is_in_the_line_and_states_a_duration(self):
        fields, rejected = annotation.validate_window_bound(BEYOND, STROKE["protocolLine"])
        assert fields == BEYOND
        assert rejected == []

    def test_should_reject_beyond_when_its_span_states_no_duration(self):
        """P8's stroke ``window_span`` was "prior to informed consent": in the line, no number."""
        fields, rejected = annotation.validate_window_bound(
            {"window_bound": "beyond", "window_bound_span": "prior to informed consent"},
            STROKE["protocolLine"],
        )
        assert fields["window_bound"] is None
        assert len(rejected) == 1

    def test_should_reject_beyond_when_its_span_is_not_in_the_line(self):
        fields, rejected = annotation.validate_window_bound(
            {"window_bound": "beyond", "window_bound_span": "more than 90 days before consent"},
            STROKE["protocolLine"],
        )
        assert fields["window_bound"] is None
        assert len(rejected) == 1


class TestTheCalls:
    def test_should_keep_beyond_when_both_wordings_say_beyond(self):
        row, llm = _annotate(STROKE, {9: BEYOND, 10: BEYOND})
        assert llm.calls == [9, 10]
        assert row[ANNOTATION_KEY]["window_bound"] == "beyond"
        assert row[annotation.WINDOW_BOUND_KEY]["kept"]

    @pytest.mark.parametrize(
        "second", [{"window_bound": "within", "window_bound_span": STROKE_SPAN},
                   {"window_bound": "none"}]
    )
    def test_should_drop_beyond_when_the_second_wording_does_not_say_it(self, second):
        row, _llm = _annotate(STROKE, {9: BEYOND, 10: second})
        assert row[ANNOTATION_KEY]["window_bound"] is None
        assert row[annotation.WINDOW_BOUND_KEY]["dropped"]

    def test_should_not_ask_call_ten_when_call_nine_says_within(self):
        within = {"window_bound": "within", "window_bound_span": "within 7 days"}
        row, llm = _annotate(ARISTOTLE_38, {9: within})
        assert llm.calls == [9]
        assert row[ANNOTATION_KEY]["window_bound"] == "within"


def _window(row: dict[str, Any]) -> Any:
    return annotation.annotated_window(row)[0]


class TestTheWindow:
    def test_should_end_the_carolina_stroke_window_three_months_before_index(self):
        row, _llm = _annotate(STROKE, {9: BEYOND, 10: BEYOND})
        window, record = annotation.annotated_window(row)
        assert window == {"start": -9999, "end": -90}
        assert record["source"] == "window_bound"

    def test_should_start_cabg_at_all_history_when_the_extracted_start_was_the_misplaced_duration(
        self,
    ):
        """Live, P8 MAIN: CABG "> 4 years prior" extracted as -1461..0; 4 years is 1460 by the
        unit path, so keeping the "earlier" extracted start emitted a one-day window."""
        span = "4 years prior to informed consent"
        answer = {"window_bound": "beyond", "window_bound_span": span}
        row, _llm = _annotate(CABG, {9: answer, 10: answer})
        assert _window(row) == {"start": -9999, "end": -1460}

    def test_should_keep_an_extracted_window_that_already_ends_before_index(self):
        row, _llm = _annotate(STROKE, {9: BEYOND, 10: BEYOND})
        row["window"] = {"start": -365, "end": -90}
        assert annotation.annotated_window(row) == ({"start": -365, "end": -90}, None)

    def test_should_keep_the_extracted_window_when_beyond_was_not_agreed(self):
        row, _llm = _annotate(STROKE, {9: BEYOND, 10: {"window_bound": "none"}})
        assert annotation.annotated_window(row) == (STROKE["window"], None)

    def test_should_keep_a_within_window_unchanged(self):
        within = {"window_bound": "within", "window_bound_span": "within 7 days"}
        row, _llm = _annotate(ARISTOTLE_38, {9: within})
        assert annotation.annotated_window(row) == ({"start": -7, "end": 0}, None)


class TestTheStatedDuration:
    def test_existing_check_reports_carmelina_28_and_left_its_window(self):
        """The check as it stood: a report, the window untouched."""
        stored = CARMELINA_28[ANNOTATION_KEY]
        assert annotation.window_disagreement(stored, CARMELINA_28["window"]) == {
            "windowSpan": "within next 12 months",
            "statedDays": [360],
            "window": {"start": -12, "end": 0},
        }

    def test_should_use_the_stated_duration_for_carmelina_28s_window(self):
        window, record = annotation.annotated_window(CARMELINA_28)
        assert window == {"start": -360, "end": 0}
        assert record["source"] == "window_span_duration"

    def test_should_turn_platos_24_hours_into_one_day(self):
        assert _window(PLATO_39) == {"start": -1, "end": 0}

    def test_should_leave_an_all_history_bound_alone(self):
        """The PLACEBO arm's CARMELINA 28 is ``{-9999, 0}``: -9999 is "all prior history", not
        a duration the span could contradict."""
        assert annotation.annotated_window(CARMELINA_28_ALL_HISTORY) == (
            CARMELINA_28_ALL_HISTORY["window"], None
        )

    def test_should_leave_a_window_the_span_agrees_with(self):
        assert annotation.annotated_window(ARISTOTLE_38) == (ARISTOTLE_38["window"], None)


def _stub_concept_set(seed: Any, **_kw: Any) -> dict[str, Any]:
    return {
        "name": str(seed),
        "domain": "Condition",
        "expression": {"items": [{
            "concept": {"CONCEPT_ID": 443454, "CONCEPT_NAME": "Cerebral infarction",
                        "CONCEPT_CODE": "432504007", "DOMAIN_ID": "Condition",
                        "VOCABULARY_ID": "SNOMED", "CONCEPT_CLASS_ID": "Clinical Finding"},
            "includeDescendants": True, "isExcluded": False,
        }]},
        "mapping_metadata": None,
    }


class TestTheBuild:
    def test_should_emit_the_carolina_stroke_window_ending_ninety_days_before_index(
        self, monkeypatch
    ):
        row, _llm = _annotate(STROKE, {9: BEYOND, 10: BEYOND})
        svc = TTEService.__new__(TTEService)
        monkeypatch.setattr(svc, "_recommend_seeded_concept_set", _stub_concept_set)
        rule = svc._build_seeded_eligibility_rule(criterion=row, codeset_id=5, exclusion=False)
        start_window = rule["rule"]["expression"]["CriteriaList"][0]["StartWindow"]
        assert start_window["Start"] == {"Days": 9999, "Coeff": -1}
        assert start_window["End"] == {"Days": 90, "Coeff": -1}
        assert rule["_annotated_window"]["window"] == {"start": -9999, "end": -90}

    def test_should_list_the_changed_criterion_in_the_artifact(self, monkeypatch):
        row, _llm = _annotate(STROKE, {9: BEYOND, 10: BEYOND})
        svc = TTEService.__new__(TTEService)
        monkeypatch.setattr(svc, "_recommend_seeded_concept_set", _stub_concept_set)
        circe = svc._build_seeded_target_circe({
            "targetCohortName": "linagliptin",
            "inclusionCriteria": [row, deepcopy(ARISTOTLE_38)],
            "exclusionCriteria": [],
        })
        rows = circe[annotation.ANNOTATED_WINDOW_CRITERIA_KEY]
        assert [(r["criterionId"], r["window"]) for r in rows] == [
            ("15", {"start": -9999, "end": -90})
        ]
        assert rows[0]["extracted"] == {"start": -90, "end": 0}
