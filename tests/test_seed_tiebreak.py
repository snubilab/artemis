"""Only two explicit negative enum verdicts may reject a disputed seed."""
import json
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda


def _judge(monkeypatch, replies):
    from src.agents.agent2 import seed_tiebreak as judge
    from src.agents.agent2.critic_cache import CriticCache

    monkeypatch.setattr(judge, "_cache", CriticCache())
    monkeypatch.setattr(judge, "resolve_model", lambda: "stub-model")
    llm = Mock()
    llm.invoke.side_effect = [
        value if isinstance(value, Exception) else AIMessage(content=value) for value in replies
    ]
    factory = Mock(return_value=RunnableLambda(llm.invoke))
    monkeypatch.setattr(judge, "get_llm", factory)
    return judge, llm, factory


@pytest.mark.parametrize("replies,drop,calls", [
    (['{"answer":"no"}', '{"answer":"no"}'], True, 2),
    (['{"answer":"yes"}'], False, 1),
    (['{"answer":"no"}', '{"answer":"yes"}'], False, 2),
    ([RuntimeError("unavailable")], False, 1),
    (['{"answer":"no"}', RuntimeError("unavailable")], False, 2),
    (['{"answer":"NO"}'], False, 1),
    (['{"answer":"no"'], False, 1),
    (['{"reason":"no"}'], False, 1),
    (['{"answer":["no"]}'], False, 1),
    (['{"answer":"no"}', '[]'], False, 2),
])
def test_should_drop_only_when_both_wordings_answer_no(monkeypatch, replies, drop, calls):
    judge, llm, factory = _judge(monkeypatch, replies)
    result = judge.judge_seed("term", "concept")
    assert result["drop"] is drop
    assert llm.invoke.call_count == calls
    assert result["first"]["prompt_version"] == judge.SEED_TIEBREAK_PROMPT_VERSION
    assert result["second"]["prompt_version"] == judge.SEED_TIEBREAK_AGREEMENT_PROMPT_VERSION
    assert result["first"]["cache_key"] != result["second"]["cache_key"]
    if calls == 1:
        assert result["second"]["answer"] == "not_called"
    assert factory.call_args.kwargs["temperature"] == 0.0
    assert factory.call_args.kwargs["json_mode"] is True


def test_should_reuse_both_cached_answers_when_inputs_repeat(monkeypatch):
    judge, llm, _ = _judge(monkeypatch, ['{"answer":"no"}', '{"answer":"no"}'])
    first = judge.judge_seed("term", "concept")
    second = judge.judge_seed("term", "concept")
    assert second == first
    assert llm.invoke.call_count == 2


@pytest.mark.parametrize("changed", ["term", "concept", "model", "version"])
def test_should_miss_cache_when_judge_identity_changes(monkeypatch, changed):
    judge, llm, _ = _judge(monkeypatch, ['{"answer":"yes"}', '{"answer":"yes"}'])
    first = judge.judge_seed("term", "concept")
    if changed == "model":
        monkeypatch.setattr(judge, "resolve_model", lambda: "other-model")
    if changed == "version":
        monkeypatch.setattr(judge, "SEED_TIEBREAK_PROMPT_VERSION", "other-version")
    second = judge.judge_seed("other" if changed == "term" else "term",
                              "other" if changed == "concept" else "concept")
    assert first["first"]["cache_key"] != second["first"]["cache_key"]
    assert llm.invoke.call_count == 2


def test_should_retry_when_answer_was_unreadable(monkeypatch):
    judge, llm, _ = _judge(monkeypatch, ['{}', '{"answer":"yes"}'])
    assert judge.judge_seed("term", "concept")["first"]["answer"] == "unreadable"
    assert judge.judge_seed("term", "concept")["first"]["answer"] == "yes"
    assert llm.invoke.call_count == 2


def test_should_keep_seed_when_response_is_truncated(monkeypatch):
    judge, llm, _ = _judge(monkeypatch, [])
    llm.invoke.side_effect = None
    llm.invoke.return_value = AIMessage(content=json.dumps({"answer": "no"}),
                                        response_metadata={"finish_reason": "length"})
    assert judge.judge_seed("term", "concept")["drop"] is False
    assert llm.invoke.call_count == 1
