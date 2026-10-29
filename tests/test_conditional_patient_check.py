"""Patient checks undo agreed conditionals only on two explicit model answers."""

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
        "Treatment (≥ 7 consecutive days) with GLP-1 receptor agonists, other DPP-4 "
        "inhibitors or SGLT-2 inhibitors prior to informed consent."
    )
    return {"id": 11, "protocolLine": line, "sourceText": line, "description": line,
            "domain": "Drug"}


def fields(criterion):
    return {"record_requirement": "conditional", "conditional_span": criterion["protocolLine"]}


@pytest.mark.parametrize("role,answers,reverted", [
    ("exclusion", [{"answer": "yes"}, {"answer": "yes"}], True),
    ("exclusion", [{"answer": "yes"}, {"answer": "no"}], False),
    ("exclusion", [{"answer": "no"}], False),
    ("exclusion", [RuntimeError("offline")], False),
    ("exclusion", [{"answer": "yes"}, RuntimeError("offline")], False),
    ("exclusion", [{"answer": "yes"}, {}], False),
    ("exclusion", [{"answer": "YES"}], False),
    ("exclusion", [None], False),
    ("inclusion", [{"answer": "no"}, {"answer": "no"}], True),
    ("inclusion", [{"answer": "no"}, {"answer": "yes"}], False),
    ("inclusion", [{"answer": "yes"}], False),
])
def test_should_revert_only_on_agreed_patient_answers_when_conditional_survives(
    role, answers, reverted
):
    criterion = row()
    original = {**fields(criterion), "timing": "retrospective"}
    llm = replay(answers)
    result, record = annotation.check_conditional_patient(
        criterion, [], role, original, model="stub", llm=llm
    )
    assert record["reverted"] is reverted
    assert result == {**original, **({"record_requirement": None, "conditional_span": None}
                                  if reverted else {})}
    assert original["record_requirement"] == "conditional"
    assert record["fragment"] == criterion["protocolLine"]
    assert len(record["calls"]) == llm.invoke.call_count == len(answers)
    for call in record["calls"]:
        assert {"promptVersion", "cacheKey", "outcome", "answer"} <= call.keys()
    if any(isinstance(a, Exception) for a in answers):
        assert "offline" in record["calls"][-1]["error"]
    template = (annotation.CONDITIONAL_PATIENT_EXCLUSION_PROMPT if role == "exclusion"
                else annotation.CONDITIONAL_PATIENT_INCLUSION_PROMPT)
    assert llm.invoke.call_args_list[0].args[0][1].content == annotation.render_prompt(
        criterion, [], role, template, criterion["protocolLine"]
    )
    assert llm.invoke.call_args_list[0].args[0][0].content == annotation.ANNOTATION_SYSTEM_PROMPT
    if len(answers) == 2:
        assert llm.invoke.call_args_list[1].args[0][0].content == annotation.AGREEMENT_SYSTEM_PROMPT


def test_should_reuse_patient_cache_when_same_question_runs_again():
    criterion = row()
    llm = replay([{"answer": "yes"}, {"answer": "yes"}])
    for _ in range(2):
        _, record = annotation.check_conditional_patient(
            criterion, [], "exclusion", fields(criterion), model="stub", llm=llm
        )
    assert llm.invoke.call_count == 2
    assert all(c["outcome"] == "cached" for c in record["calls"])


@pytest.mark.parametrize("kind", ["reverted", "outside_first", "outside_second", "required"])
def test_should_not_ask_patient_when_prior_checks_rule_it_out(kind):
    criterion = row()
    agreed = fields(criterion)
    if kind == "required":
        answers = [{"record_requirement": "required"}, {"trial_only": "no"}]
    else:
        checks = {
            "reverted": [("has_own_entity", "yes"), ("time_or_record", "yes")],
            "outside_first": [("patients", "no")],
            "outside_second": [("has_own_entity", "yes"), ("time_or_record", "no")],
        }[kind]
        answers = [agreed, agreed] + [
            {"fragment_role": fragment, "entity_outside_trial": outside}
            for fragment, outside in checks
        ]
    answers += [{"record_change": "none"}, {}]
    llm = replay(answers)
    criterion["_conditionalPatientCheck"] = {"reverted": True}
    annotation.annotate_row(criterion, [], "exclusion", model="stub", llm=llm)
    assert "_conditionalPatientCheck" not in criterion
    assert llm.invoke.call_count == len(answers)
    assert not any('"answer": "<yes|no>"' in c.args[0][1].content
                   for c in llm.invoke.call_args_list)


@pytest.mark.parametrize("label", [False, True])
def test_should_remove_own_and_propagated_skips_when_patient_check_reverts(label):
    criterion = row()
    members = []
    if label:
        criterion.update(isGroupLabel=True, groupId="g")
        members = [{"id": 12, "groupId": "g", "protocolLine": criterion["protocolLine"]}]
    criterion["annotation"] = fields(criterion)
    assert set(annotation.conditional_skips([criterion, *members])) == (
        {"11", "12"} if label else {"11"}
    )
    agreed = fields(criterion)
    answers = [agreed, agreed, {"fragment_role": "patients", "entity_outside_trial": "yes"},
               {"answer": "yes"}, {"answer": "yes"}, {"record_change": "none"}]
    if not label:
        answers.append({})
    llm = replay(answers)
    annotation.annotate_row(criterion, members, "exclusion", model="stub", llm=llm)
    assert annotation.conditional_skips([criterion, *members]) == {}
    assert criterion["_conditionalPatientCheck"]["reverted"] is True
    assert llm.invoke.call_count == len(answers)


def test_should_clear_patient_record_when_initial_annotation_fails():
    criterion = row()
    criterion["_conditionalPatientCheck"] = {"reverted": True}
    llm = replay([RuntimeError("offline"), {"record_change": "none"}, {}])
    assert annotation.annotate_row(criterion, [], "exclusion", model="stub", llm=llm) == "error"
    assert "_conditionalPatientCheck" not in criterion


@pytest.mark.parametrize("answers,reverted", [
    ([{"answer": "yes"}, {"answer": "yes"}], 1),
    ([{"answer": "no"}], 0),
])
def test_should_count_patient_checks_when_annotating_eligibility(monkeypatch, answers, reverted):
    criterion = row()
    agreed = fields(criterion)
    llm = replay([agreed, agreed,
                  {"fragment_role": "patients", "entity_outside_trial": "yes"},
                  *answers, {"record_change": "none"}, {}])
    monkeypatch.setattr(annotation, "_build_llm", lambda model: llm)
    monkeypatch.setenv("ARTEMIS_ANNOTATION_OVERLAP", "0")
    counts = annotation.annotate_eligibility({"exclusionCriteria": [criterion]}, model="stub")
    assert counts["conditionalChecked"] == 1
    assert counts["conditionalReverted"] == 0
    assert counts["conditionalPatientChecked"] == 1
    assert counts["conditionalPatientReverted"] == reverted


def test_should_remove_inclusion_skip_when_patient_cannot_meet_line_without_fragment():
    criterion = row()
    criterion["protocolLine"] = "Type 2 diabetes mellitus"
    agreed = fields(criterion)
    llm = replay([agreed, agreed,
                  {"fragment_role": "has_own_entity", "entity_outside_trial": "yes"},
                  {"answer": "no"}, {"answer": "no"}, {"record_change": "none"}, {}])
    annotation.annotate_row(criterion, [], "inclusion", model="stub", llm=llm)
    assert annotation.conditional_skips([criterion]) == {}
    assert criterion["_conditionalPatientCheck"]["reverted"] is True
    assert llm.invoke.call_count == 7


def test_should_preserve_extractor_skip_when_only_annotation_conditional_is_reverted():
    criterion = row()
    criterion["conditional"] = True
    agreed = fields(criterion)
    llm = replay([agreed, agreed,
                  {"fragment_role": "patients", "entity_outside_trial": "yes"},
                  {"answer": "yes"}, {"answer": "yes"}, {"record_change": "none"}, {}])
    annotation.annotate_row(criterion, [], "exclusion", model="stub", llm=llm)
    assert criterion["_conditionalPatientCheck"]["reverted"] is True
    assert criterion["annotation"]["record_requirement"] is None
    assert annotation.conditional_skips([criterion])["11"].source == annotation.SOURCE_EXTRACTION
