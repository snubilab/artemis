"""The planner's reply has a budget, a cut-off reply is refused, and one unusable reply is re-asked.

P11 MAIN (2026-10-22_p11_secnest, code 3a253a4) planned EMPA-REG inclusion 3 'Body Mass index'
("5. Body Mass index <= 45 at Visit 1") and got a 130,054-byte response where the other 341 planner
replies of that run were at most 11,419 bytes. The call carried no ``max_tokens`` (65924ad capped
every other measured call type, not this one) and no ``raise_if_truncated``, so the runaway reached
``json.loads`` and was recorded as "Expecting ':' delimiter: line 4 column 20 (char 5099)" -- a
planning failure the delivery gate FAILs on. The same prompt re-sent alone on 2026-10-24 finished
``stop`` in 324 tokens and parsed (the ``CLEAN`` reply below).

No LLM is called: the model is a stub returning the replies in order.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.messages import AIMessage

from src.models.ir import Criteria

EMPA_BMI_LINE = "5. Body Mass index <= 45 at Visit 1"
CLEAN = json.dumps({
    "decompose": False, "reasoning": "a single measurement", "excepted_entities": [],
    "relation": None, "relation_span": None, "cardinality": None, "sub_criteria": [],
})
#: The start of a reply that never terminates, cut at the reply budget.
RUNAWAY = '{\n  "decompose": true,\n  "reasoning": "' + "the measurement " * 400


def _criterion() -> Criteria:
    return Criteria(name="BMI requirement", domain="Measurement", entity_text="Body Mass index",
                    source_text=EMPA_BMI_LINE, logic_type="PRESENCE")


def _planner(*replies: AIMessage):
    from src.agents.planner.decomposer import CriteriaPlanner

    queue = list(replies)
    calls: list[object] = []

    def invoke(messages):
        calls.append(messages)
        return queue.pop(0)

    planner = CriteriaPlanner.__new__(CriteriaPlanner)
    planner.llm = SimpleNamespace(invoke=invoke)
    return planner, calls


def _reply(content: str, finish: str = "stop") -> AIMessage:
    return AIMessage(content=content, response_metadata={"finish_reason": finish})


def test_should_build_the_planner_model_with_its_reply_budget_when_constructed():
    from src.agents.planner.decomposer import CriteriaPlanner
    from src.utils.llm import PLANNER_MAX_TOKENS

    with patch("src.agents.planner.decomposer.get_llm") as get_llm:
        CriteriaPlanner(model_name="vllm/google/gemma-4-E4B-it")

    assert get_llm.call_args.kwargs.get("max_tokens") == PLANNER_MAX_TOKENS


def test_should_plan_from_the_second_reply_when_the_first_is_cut_off(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_TRUNCATION_DIR", str(tmp_path))
    planner, calls = _planner(_reply(RUNAWAY, "length"), _reply(CLEAN))

    planned = planner._decompose_criterion(_criterion())

    assert len(calls) == 2
    assert planned.planning_failure is None, planned.planning_failure


def test_should_plan_from_the_second_reply_when_the_first_does_not_parse():
    planner, calls = _planner(_reply(RUNAWAY), _reply(CLEAN))

    planned = planner._decompose_criterion(_criterion())

    assert len(calls) == 2
    assert planned.planning_failure is None, planned.planning_failure


def test_should_record_the_failure_when_both_replies_are_cut_off(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_TRUNCATION_DIR", str(tmp_path))
    planner, calls = _planner(_reply(RUNAWAY, "length"), _reply(RUNAWAY, "length"))

    planned = planner._decompose_criterion(_criterion())

    assert len(calls) == 2
    assert "LLMTruncationError" in (planned.planning_failure or ""), planned.planning_failure
    assert planned.sub_criteria == []


def test_should_ask_once_when_the_first_reply_is_usable():
    planner, calls = _planner(_reply(CLEAN))

    planned = planner._decompose_criterion(_criterion())

    assert len(calls) == 1
    assert planned.planning_failure is None
