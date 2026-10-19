"""A group label's `conditional` whose fragment sits only in its own header line does not skip
an inclusion group.

P7 SEG-OFF (`output/site_gap/2026-10-18_p7_segoff`), both arms: LEADER inclusion 14 'No Prior
cardiovascular disease group: Age ≥60 y and ≥1 of the following criteria:' came back
`conditional` on 'Age ≥60 y' from calls 1 and 2, calls 5 and 6 read it as naming patients, and the
skip took the label and its three members -- each on a line of its own, none of which states the
fragment, and each annotated `required` there. Inclusion 16 'Prior cardiovascular disease cohort:
age ≥50 and ≥1 of the following criteria:' lost its two members the same way.

The lines below are the arm's store rows, verbatim. The model is replaced by a replay; nothing
reaches a network.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src.services import criterion_annotation as annotation
from src.services.criterion_annotation import conditional_skips

LEADER_GROUP = "2f746b64"
LEADER_ROWS = [
    {"id": 47, "isGroupLabel": True, "groupId": LEADER_GROUP,
     "description": "Prior cardiovascular disease group (Age >=60)",
     "sourceText": "Prior cardiovascular disease", "domain": "Condition", "logicType": "PRESENCE",
     "protocolLine": "14. No Prior cardiovascular disease group: Age ≥60 y and ≥1 of the "
                     "following criteria:"},
    {"id": 48, "groupId": LEADER_GROUP, "description": "Prior MI", "sourceText": "Prior MI",
     "domain": "Condition", "logicType": "PRESENCE", "protocolLine": "prior mi",
     "annotation": {"record_requirement": "required"}},
    {"id": 50, "groupId": LEADER_GROUP, "description": "Prior stroke or TIA",
     "sourceText": "Prior stroke or TIA", "domain": "Condition", "logicType": "PRESENCE",
     "protocolLine": "prior stroke or tia", "annotation": {"record_requirement": "required"}},
]

# CARMELINA exclusion 12 (P6 MAIN exclusion 30): the same header shape on an exclusion, where
# excluding the women the header names who also meet a member IS the conditional reading.
CARMELINA_GROUP = "c0ffee00"
CARMELINA_ROWS = [
    {"id": 30, "isGroupLabel": True, "groupId": CARMELINA_GROUP,
     "description": "Pre-menopausal women", "sourceText": "Pre-menopausal women",
     "domain": "Condition", "logicType": "ABSENCE",
     "protocolLine": "12. Pre-menopausal women (last menstruation ≤ 1 year prior to informed "
                     "consent) who:"},
    {"id": 31, "groupId": CARMELINA_GROUP, "description": "Nursing", "sourceText": "nursing",
     "domain": "Condition", "logicType": "ABSENCE", "protocolLine": "are nursing or pregnant",
     "annotation": {"record_requirement": "forbidden"}},
]


class _Replay:
    """Calls 1 and 2 answer `conditional` on ``span``; calls 3/4 fill nothing; calls 5/6 answer
    ``patients``, which never reverts."""

    def __init__(self, span: str) -> None:
        self.answer = {"record_requirement": "conditional", "conditional_span": span}
        self.kinds: list[str] = []

    def invoke(self, messages: list[Any]) -> AIMessage:
        prompt = str(messages[1].content)
        if "fragment_role" in prompt:
            self.kinds.append("check")
            reply: dict[str, Any] = {"fragment_role": "patients", "entity_outside_trial": "yes"}
        elif annotation.RECORD_CHANGE_PROMPT_BLOCK.split("\n")[0] in prompt:
            self.kinds.append("record_change")
            reply = {"record_change": "none"}
        else:
            self.kinds.append("annotate")
            reply = self.answer
        return AIMessage(content=json.dumps(reply))


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_ANNOTATION_CACHE_PATH", str(tmp_path / "annotations.jsonl"))
    monkeypatch.delenv("ARTEMIS_ANNOTATION_CACHE", raising=False)
    annotation.reset_for_tests()
    yield
    annotation.reset_for_tests()


def _annotate_label(rows: list[dict[str, Any]], role: str, span: str) -> _Replay:
    label = rows[0]
    llm = _Replay(span)
    annotation.annotate_row(label, annotation._members_of(label, rows), role, model="stub", llm=llm)
    return llm


def test_should_emit_an_inclusion_group_when_its_fragment_is_only_in_the_header_line():
    rows = [dict(r) for r in LEADER_ROWS]
    llm = _annotate_label(rows, annotation.INCLUSION, "Age ≥60 y")
    assert conditional_skips(rows) == {}
    record = rows[0][annotation.CONDITIONAL_CHECK_KEY]
    assert record["reverted"] is True and record["headerOnly"] is True
    assert "check" not in llm.kinds  # the header test decides; calls 5 and 6 are not asked


def test_should_keep_an_exclusion_group_skipped_when_its_fragment_is_only_in_the_header_line():
    rows = [dict(r) for r in CARMELINA_ROWS]
    _annotate_label(rows, annotation.EXCLUSION, "Pre-menopausal women")
    assert set(conditional_skips(rows)) == {"30", "31"}


def test_should_ask_the_check_when_a_member_line_states_the_fragment():
    """PLATO's WOCBP shape: the members are read off the label's own line, so the fragment does
    qualify them and the header test does not apply."""
    rows = [dict(r) for r in LEADER_ROWS]
    for member in rows[1:]:
        member["protocolLine"] = rows[0]["protocolLine"]
    llm = _annotate_label(rows, annotation.INCLUSION, "Age ≥60 y")
    assert "check" in llm.kinds
    assert set(conditional_skips(rows)) == {"47", "48", "50"}
