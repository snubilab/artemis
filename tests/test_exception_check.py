"""Agreed exceptions are removed only by two explicit inclusion answers."""

import json
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from src.services import criterion_annotation as annotation


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_ANNOTATION_CACHE_PATH", str(tmp_path / "annotations.jsonl"))
    monkeypatch.delenv("ARTEMIS_ANNOTATION_CACHE", raising=False)
    annotation.reset_for_tests()
    yield
    annotation.reset_for_tests()


def replay(answers):
    llm = MagicMock()
    llm.invoke.side_effect = [
        a if isinstance(a, Exception) else AIMessage(content=json.dumps(a)) for a in answers
    ]
    return llm


def row():
    line = (
        "Inappropriateness of glimepiride treatment for renal safety issues or other issues "
        "(e.g. allergy) according to local prescribing information"
    )
    return {"id": 32, "protocolLine": line, "sourceText": line, "description": line,
            "domain": "Condition"}


def fields():
    return {"excepted_entities": [{"text": "allergy", "span": "allergy"}],
            "base_span": "Inappropriateness of glimepiride treatment", "timing": "retrospective"}


@pytest.mark.parametrize("answers,dropped", [
    ([{"answer": "included"}, {"answer": "included"}], True),
    ([{"answer": "removed"}], False),
    ([{"answer": "included"}, {"answer": "removed"}], False),
    ([RuntimeError("offline")], False),
    ([{"answer": "included"}, RuntimeError("offline")], False),
    ([{}], False),
    ([None], False),
    ([{"answer": "INCLUDED"}], False),
    ([{"answer": "included"}, {}], False),
])
def test_should_drop_exception_only_when_both_wordings_answer_included(answers, dropped):
    criterion, original = row(), fields()
    llm = replay(answers)
    result, records = annotation.check_exceptions(
        criterion, [], "exclusion", original, model="stub", llm=llm
    )
    assert result == {**original, **({"excepted_entities": [], "base_span": None}
                                   if dropped else {})}
    assert original == fields()
    assert len(records) == 1
    assert records[0]["span"] == "allergy"
    assert records[0]["dropped"] is dropped
    assert len(records[0]["calls"]) == llm.invoke.call_count == len(answers)
    for call, version, template, system in zip(
        records[0]["calls"],
        (annotation.EXCEPTION_CHECK_PROMPT_VERSION,
         annotation.EXCEPTION_CHECK_AGREEMENT_PROMPT_VERSION),
        (annotation.EXCEPTION_CHECK_PROMPT, annotation.EXCEPTION_CHECK_AGREEMENT_PROMPT),
        (annotation.ANNOTATION_SYSTEM_PROMPT, annotation.AGREEMENT_SYSTEM_PROMPT),
    ):
        assert {"promptVersion", "cacheKey", "outcome", "answer"} <= call.keys()
        assert call["promptVersion"] == version
        messages = llm.invoke.call_args_list[records[0]["calls"].index(call)].args[0]
        assert messages[0].content == system
        assert messages[1].content == annotation.render_prompt(
            criterion, [], "exclusion", template, "allergy"
        )
    if any(isinstance(a, Exception) for a in answers):
        assert "offline" in records[0]["calls"][-1]["error"]


def test_should_keep_base_span_when_one_of_two_exceptions_survives():
    original = fields()
    original["excepted_entities"].append({"span": "renal safety issues"})
    llm = replay([{"answer": "included"}, {"answer": "included"}, {"answer": "removed"}])
    result, records = annotation.check_exceptions(
        row(), [], "exclusion", original, model="stub", llm=llm
    )
    assert result == {**original, "excepted_entities": [{"span": "renal safety issues"}]}
    assert [r["dropped"] for r in records] == [True, False]
    assert [len(r["calls"]) for r in records] == [2, 1]
    assert llm.invoke.call_count == 3


def test_should_make_no_call_when_no_exceptions_exist():
    original = {"excepted_entities": [], "base_span": None}
    llm = replay([])
    result, records = annotation.check_exceptions(
        row(), [], "exclusion", original, model="stub", llm=llm
    )
    assert result == original
    assert records == []
    llm.invoke.assert_not_called()


def test_should_reuse_exception_cache_when_same_fragment_is_checked_again():
    llm = replay([{"answer": "included"}, {"answer": "included"}])
    for _ in range(2):
        _, records = annotation.check_exceptions(
            row(), [], "exclusion", fields(), model="stub", llm=llm
        )
    assert llm.invoke.call_count == 2
    assert all(c["outcome"] == "cached" for c in records[0]["calls"])
    assert len({c["cacheKey"] for c in records[0]["calls"]}) == 2


@pytest.mark.parametrize("answers,dropped", [
    ([{"answer": "included"}, {"answer": "included"}], 1),
    ([{"answer": "removed"}], 0),
])
def test_should_check_agreed_exception_before_later_calls_and_count_entities(
    monkeypatch, answers, dropped
):
    criterion, agreed = row(), fields()
    llm = replay([agreed, agreed, *answers, {"record_change": "none"}, {}])
    monkeypatch.setattr(annotation, "_build_llm", lambda model: llm)
    monkeypatch.setenv("ARTEMIS_ANNOTATION_OVERLAP", "0")
    counts = annotation.annotate_eligibility({"exclusionCriteria": [criterion]}, model="stub")
    assert counts["exceptionChecked"] == 1
    assert counts["exceptionDropped"] == dropped
    assert criterion["_exceptionCheck"][0]["dropped"] is bool(dropped)
    assert criterion["annotation"]["excepted_entities"] == (
        [] if dropped else agreed["excepted_entities"]
    )
    assert criterion["annotation"]["base_span"] == (None if dropped else agreed["base_span"])
    assert llm.invoke.call_count == len(answers) + 4


@pytest.mark.parametrize("kind", ["empty", "disagreed", "error"])
def test_should_clear_stale_exception_check_when_no_agreed_entities_remain(kind):
    criterion = row()
    criterion["_exceptionCheck"] = [{"dropped": True}]
    answers = {"empty": [{}], "disagreed": [fields(), {}],
               "error": [RuntimeError("offline")]}[kind]
    llm = replay([*answers, {"record_change": "none"}, {}])
    annotation.annotate_row(criterion, [], "exclusion", model="stub", llm=llm)
    assert "_exceptionCheck" not in criterion
    assert llm.invoke.call_count == len(answers) + 2
