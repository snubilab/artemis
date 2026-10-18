"""A `conditional` both wordings agreed on is checked by a separate question before it skips rows.

Pinned to P6 SEG-OFF (`output/site_gap/2026-10-17_p6_segoff`) through
`tests/fixtures/conditional_check_rows.json`: real store rows with the answers calls 1-4 gave them
(the arm's annotation cache, both files recorded by sha256).

Calls 1 and 2 ask the same definition in two wordings, so a reading the definition itself admits
survives agreement. CAROLINA exclusion 16 'Acute or chronic metabolic acidosis (present condition in
patient history)' came back `conditional` from both, quoting '(present condition in patient
history)', and the skip took the label and both members with it -- an exclusion the protocol states
plainly was never emitted. Calls 5 and 6 ask what the quoted fragment does; the `conditional` is
reverted only when both say it states only when or in which record the criterion's own entity is
found, or that the patient has the exclusion's own entity. PLATO's women-of-child-bearing-potential label, whose fragment names a kind of patient, keeps
its skip and takes its members with it.

The model is replaced by a replay keyed on which call a prompt is; nothing reaches a network.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src.services import criterion_annotation as annotation
from src.services.criterion_annotation import conditional_skips

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "conditional_check_rows.json").read_text()
)
CASES = {(r["trial"], r["role"], r["id"]): r for r in FIXTURE["rows"]}


class _Replay:
    """Answers each call with the recorded answer of the call it is; the check calls with the
    answers the test gives."""

    def __init__(self, answers: dict[str, Any], check: tuple[str, str],
                 outside: tuple[str, str] = ("yes", "yes")) -> None:
        self.answers = answers
        self.check = check
        self.outside = outside
        self.kinds: list[str] = []

    def _kind(self, system: str, prompt: str) -> str:
        if prompt == getattr(self, "_never", None):
            raise AssertionError
        if "fragment_role" in prompt:
            return "check1" if system == annotation.ANNOTATION_SYSTEM_PROMPT else "check2"
        record_change = annotation.RECORD_CHANGE_PROMPT_BLOCK.split("\n")[0] in prompt
        first = system == annotation.ANNOTATION_SYSTEM_PROMPT
        return {(False, True): "current", (False, False): "placebo",
                (True, True): "cf", (True, False): "pf"}[(record_change, first)]

    def invoke(self, messages: list[Any]) -> AIMessage:
        kind = self._kind(str(messages[0].content), str(messages[1].content))
        self.kinds.append(kind)
        if kind in ("check1", "check2"):
            i = 0 if kind == "check1" else 1
            reply = {"fragment_role": self.check[i], "entity_outside_trial": self.outside[i]}
        else:
            reply = self.answers[kind]
        return AIMessage(content=json.dumps(reply))


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_ANNOTATION_CACHE_PATH", str(tmp_path / "annotations.jsonl"))
    monkeypatch.delenv("ARTEMIS_ANNOTATION_CACHE", raising=False)
    annotation.reset_for_tests()
    yield
    annotation.reset_for_tests()


def _group(trial: str, role: str, ids: list[int]) -> list[dict[str, Any]]:
    """The rows as stored, each carrying the annotation the arm gave it."""
    rows = []
    for cid in ids:
        case = CASES[(trial, role, cid)]
        rows.append({**copy.deepcopy(case["row"]), "annotation": case["storedAnnotation"]})
    return rows


def _reannotate(rows: list[dict[str, Any]], cid: int, trial: str, role: str,
                check: tuple[str, str], outside: tuple[str, str] = ("yes", "yes")) -> _Replay:
    row = next(r for r in rows if r["id"] == cid)
    row.pop("annotation")
    members = annotation._members_of(row, rows)
    llm = _Replay(CASES[(trial, role, cid)]["answers"], check, outside)
    annotation.annotate_row(row, members, role, model="stub", llm=llm)
    return llm


def test_should_emit_the_metabolic_acidosis_exclusion_when_both_checks_name_no_subgroup():
    """CAROLINA exclusion 16 (label 41, members 42/43): the arm skipped all three."""
    rows = _group("carolina", "exclusion", [41, 42, 43])
    assert set(conditional_skips(rows)) == {"41", "42", "43"}  # the arm's outcome, as stored
    for cid in (41, 42):
        _reannotate(rows, cid, "carolina", "exclusion", ("has_own_entity", "time_or_record"))
    assert conditional_skips(rows) == {}
    record = next(r for r in rows if r["id"] == 41)[annotation.CONDITIONAL_CHECK_KEY]
    assert record["reverted"] is True


def test_should_keep_the_conditional_when_the_two_checks_disagree():
    rows = _group("carolina", "exclusion", [41, 42, 43])
    for cid in (41, 42):
        _reannotate(rows, cid, "carolina", "exclusion", ("time_or_record", "patients"))
    assert set(conditional_skips(rows)) == {"41", "42", "43"}


def test_should_keep_the_wocbp_skip_and_its_members_when_the_fragment_names_patients():
    """PLATO inclusion 23 'Females of child-bearing potential must have a negative pregnancy test
    ...': must not regress -- the label keeps `conditional` and members 24/25 stay skipped."""
    rows = _group("plato", "inclusion", [23, 24, 25])
    llm = _reannotate(rows, 23, "plato", "inclusion", ("patients", "patients"))
    assert set(conditional_skips(rows)) == {"23", "24", "25"}
    assert "check2" not in llm.kinds  # the second check is asked only to confirm a revert


def test_should_keep_an_inclusion_whose_fragment_names_patients_with_its_own_entity():
    """`has_own_entity` reverts only an exclusion: on an inclusion the patients who have its entity
    can be a subgroup the line asks something further of (LEADER inclusion 12, kept)."""
    rows = _group("plato", "inclusion", [23, 24, 25])
    _reannotate(rows, 23, "plato", "inclusion", ("has_own_entity", "has_own_entity"))
    assert set(conditional_skips(rows)) == {"23", "24", "25"}


def test_should_not_ask_the_check_for_a_row_that_is_not_conditional():
    rows = _group("plato", "inclusion", [23, 24, 25])
    llm = _Replay({"current": {"record_requirement": "required"}, "cf": {"record_change": "none"}},
                  ("time_or_record", "time_or_record"))
    row = rows[1]
    row.pop("annotation")
    annotation.annotate_row(row, [], "inclusion", model="stub", llm=llm)
    assert not {"check1", "check2"} & set(llm.kinds)


def test_should_keep_the_skip_when_the_entity_arises_only_from_taking_part_in_the_trial():
    """CAROLINA inclusion 13 'Treatment compliance in the placebo run-in should be between 80% and
    120%': both checks read 'in the placebo run-in' as a period, but compliance in the trial's own
    run-in is held by no record outside the trial. Freed, it emitted an Observation PRESENCE no
    patient record can satisfy; it keeps its skip."""
    rows = _group("carolina", "inclusion", [35])
    _reannotate(rows, 35, "carolina", "inclusion", ("time_or_record", "time_or_record"),
                outside=("no", "no"))
    assert set(conditional_skips(rows)) == {"35"}


def test_should_keep_the_skip_when_either_check_says_the_entity_is_not_recorded_outside():
    rows = _group("carolina", "exclusion", [41, 42, 43])
    for cid in (41, 42):
        _reannotate(rows, cid, "carolina", "exclusion", ("has_own_entity", "time_or_record"),
                    outside=("yes", "no"))
    assert set(conditional_skips(rows)) == {"41", "42", "43"}
