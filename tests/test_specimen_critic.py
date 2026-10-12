"""RFC-016 step 4 (A17 + C3): the specimen critic decides which (System, challenge) options a
Measurement criterion states.

The protocol line is real: CAROLINA exclusion 11 from the 2026-10-12 prompt_f2 store
(``tests/fixtures/rfc016_step4_rows.json``). The options are real LOINC System / challenge
parts of the glucose tests that store's sets hold. The model is a stub; nothing reaches an LLM.

What is pinned: the model is told the line, the analyte, the annotation's specimen and its
fragment, and the options; only identifiers it was offered are kept; an unreadable answer or a
failed call is no answer (``None``) and is never cached; a cached answer is not asked again.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from src.agents.agent2 import specimen_critic
from src.agents.agent2.specimen_critic import judge_specimen_options, render_prompt
from src.services.loinc_specimen import SpecimenOption

ROWS = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "rfc016_step4_rows.json").read_text()
)
CAROLINA_11 = ROWS["carolina_exclusion_11"]

SERUM = SpecimenOption(None, "Serum or Plasma", None)
VITREOUS = SpecimenOption(None, "Vitreous fluid", None)
FASTING = SpecimenOption(None, "Serum or Plasma", "post CFst")
OPTIONS = [SERUM, VITREOUS, FASTING]


class _StubLLM:
    def __init__(self, payload: Any = None, *, fail: Exception | None = None) -> None:
        self.payload = payload
        self.fail = fail
        self.calls: list[str] = []

    def invoke(self, messages: list[Any]) -> AIMessage:
        self.calls.append("\n\n".join(str(m.content) for m in messages))
        if self.fail is not None:
            raise self.fail
        return AIMessage(content=json.dumps(self.payload))


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_SPECIMEN_CRITIC_CACHE_PATH", str(tmp_path / "judgements.jsonl"))
    monkeypatch.delenv("ARTEMIS_SPECIMEN_CRITIC_CACHE", raising=False)
    specimen_critic.reset_for_tests()
    yield
    specimen_critic.reset_for_tests()


def _judge(llm: _StubLLM, options=OPTIONS) -> Any:
    return judge_specimen_options(
        protocol_line=CAROLINA_11["protocolLine"],
        analyte="Glucose",
        specimen="any",
        specimen_span=None,
        options=options,
        model="stub-model",
        llm=llm,
    )


class TestWhatTheCriticIsTold:
    def test_should_show_the_line_the_specimen_and_every_option_under_its_identifier(self):
        prompt, identified = render_prompt(
            protocol_line=CAROLINA_11["protocolLine"],
            analyte="Glucose",
            specimen="blood",
            specimen_span="glucose level",
            options=OPTIONS,
        )
        assert CAROLINA_11["protocolLine"] in prompt
        assert "Measured quantity: Glucose" in prompt
        assert "records for this criterion: blood" in prompt
        assert "names it: glucose level" in prompt
        assert identified == {"V1": SERUM, "V2": VITREOUS, "V3": FASTING}
        assert "- V3: specimen Serum or Plasma; condition post CFst" in prompt
        assert "- V2: specimen Vitreous fluid; condition none" in prompt


class TestTheAnswer:
    def test_should_return_the_keys_of_the_offered_options_it_accepts(self):
        accepted = _judge(_StubLLM({"accepted": ["V1", "V3"]}))
        assert accepted == {SERUM.key, FASTING.key}

    def test_should_drop_an_identifier_it_was_not_offered(self):
        accepted = _judge(_StubLLM({"accepted": ["V1", "V9", "Serum or Plasma"]}))
        assert accepted == {SERUM.key}

    def test_should_accept_nothing_when_the_list_is_empty(self):
        assert _judge(_StubLLM({"accepted": []})) == frozenset()

    @pytest.mark.parametrize("payload", [{"accepted": "V1"}, {"selected": ["V1"]}, ["V1"]])
    def test_should_give_no_answer_when_the_reply_is_not_an_accepted_list(self, payload):
        assert _judge(_StubLLM(payload)) is None

    def test_should_give_no_answer_and_cache_nothing_when_the_call_fails(self):
        assert _judge(_StubLLM(fail=TimeoutError("vLLM"))) is None
        second = _StubLLM({"accepted": ["V1"]})
        assert _judge(second) == {SERUM.key}
        assert len(second.calls) == 1

    def test_should_not_ask_again_when_the_same_question_was_answered(self):
        first = _StubLLM({"accepted": ["V1"]})
        _judge(first)
        again = _StubLLM({"accepted": ["V2"]})
        assert _judge(again) == {SERUM.key}
        assert again.calls == []

    def test_should_not_call_the_model_when_there_is_nothing_to_judge(self):
        llm = _StubLLM({"accepted": ["V1"]})
        assert _judge(llm, options=[]) == frozenset()
        assert llm.calls == []
