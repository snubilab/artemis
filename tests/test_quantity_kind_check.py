"""A non-value row's lab_value kind changes only on two explicit no answers."""

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from src.api.models.tte import DEMOGRAPHIC_DOMAINS
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
    fixture_path = Path(__file__).parent / "fixtures/loss_e_threshold_rows.json"
    fixture = json.loads(fixture_path.read_text())
    case = next(c for c in fixture["cases"] if c["name"] == "empa-reg_inclusion_25")
    return deepcopy(case["study"]["eligibility"]["inclusionCriteria"][0])


def fields():
    return {"threshold_span": "≥50% luminal narrowing", "quantity_kind": "lab_value",
            "reference_bound": "none", "timing": "at_index"}


@pytest.mark.parametrize("answers,changed", [
    ([{"answer": "no"}, {"answer": "no"}], True),
    ([{"answer": "yes"}], False),
    ([{"answer": "no"}, {"answer": "yes"}], False),
    ([RuntimeError("offline")], False),
    ([{"answer": "no"}, RuntimeError("offline")], False),
    ([{}], False),
    ([None], False),
    ([{"answer": "NO"}], False),
    ([{"answer": "no"}, {}], False),
    ([{"answer": "no"}, None], False),
])
def test_should_change_only_when_both_wordings_answer_no(answers, changed):
    criterion, original = row(), fields()
    llm = replay(answers)
    result, record = annotation.check_quantity_kind(
        criterion, [], "inclusion", original, model="stub", llm=llm
    )
    assert original == fields()
    assert result == {**original, "quantity_kind": "other" if changed else "lab_value"}
    assert record["span"] == original["threshold_span"]
    assert record["changed"] is changed
    assert len(record["calls"]) == llm.invoke.call_count == len(answers)
    for index, (version, template, system) in enumerate(zip(
        (annotation.QUANTITY_KIND_CHECK_PROMPT_VERSION,
         annotation.QUANTITY_KIND_CHECK_AGREEMENT_PROMPT_VERSION),
        (annotation.QUANTITY_KIND_CHECK_PROMPT, annotation.QUANTITY_KIND_CHECK_AGREEMENT_PROMPT),
        (annotation.ANNOTATION_SYSTEM_PROMPT, annotation.AGREEMENT_SYSTEM_PROMPT),
    )):
        if index >= len(answers):
            break
        call = record["calls"][index]
        assert {"promptVersion", "cacheKey", "outcome", "answer"} <= call.keys()
        assert call["promptVersion"] == version
        messages = llm.invoke.call_args_list[index].args[0]
        assert messages[0].content == system
        assert messages[1].content == annotation.render_prompt(
            criterion, [], "inclusion", template, original["threshold_span"]
        )
    if any(isinstance(a, Exception) for a in answers):
        assert "offline" in record["calls"][-1]["error"]


def test_should_reuse_cache_when_same_quantity_is_checked_again():
    llm = replay([{"answer": "no"}, {"answer": "no"}])
    for _ in range(2):
        _, record = annotation.check_quantity_kind(
            row(), [], "inclusion", fields(), model="stub", llm=llm
        )
    assert llm.invoke.call_count == 2
    assert all(c["outcome"] == "cached" for c in record["calls"])
    assert len({c["cacheKey"] for c in record["calls"]}) == 2


@pytest.mark.parametrize("answer,changed", [("no", True), ("yes", False)])
def test_should_record_check_and_counts_when_nonmeasurement_has_lab_value(
    monkeypatch, answer, changed
):
    criterion = row()
    criterion["domain"] = "Procedure"
    llm = replay([fields(), {"answer": answer}, *([{"answer": "no"}] if changed else []),
                  {"record_change": "none"}, {}])
    monkeypatch.setattr(annotation, "_build_llm", lambda model: llm)
    monkeypatch.setenv("ARTEMIS_ANNOTATION_OVERLAP", "0")
    assert annotation.threshold_use(criterion)[0] is annotation.ThresholdUse.MEASURED
    counts = annotation.annotate_eligibility({"inclusionCriteria": [criterion]}, model="stub")
    assert counts["quantityKindChecked"] == 1
    assert counts["quantityKindChanged"] == int(changed)
    assert criterion["_quantityKindCheck"]["changed"] is changed
    assert criterion["annotation"]["quantity_kind"] == ("other" if changed else "lab_value")
    assert annotation.threshold_use(criterion)[0] is (
        annotation.ThresholdUse.NOT_REPRESENTABLE if changed else annotation.ThresholdUse.MEASURED
    )
    assert llm.invoke.call_count == (5 if changed else 4)


@pytest.mark.parametrize("domain,kind,span", [
    ("Measurement", "lab_value", "≥50% luminal narrowing"),
    *[(domain, "lab_value", "≥50% luminal narrowing") for domain in sorted(DEMOGRAPHIC_DOMAINS)],
    ("Condition", "other", "≥50% luminal narrowing"),
    ("Condition", "lab_value", None),
    ("Condition", "lab_value", ""),
    ("Condition", None, None),
    ("Condition", None, ""),
])
def test_should_clear_stale_check_without_call_when_row_is_ineligible(domain, kind, span):
    criterion = row()
    criterion["domain"] = domain
    criterion["_quantityKindCheck"] = {"changed": True}
    payload = {**fields(), "quantity_kind": kind, "threshold_span": span,
               "reference_bound": "none" if span else None}
    llm = replay([payload, {"record_change": "none"}, {}])
    annotation.annotate_row(criterion, [], "inclusion", model="stub", llm=llm)
    assert "_quantityKindCheck" not in criterion
    assert llm.invoke.call_count == 3


def test_should_clear_stale_check_when_annotation_fails():
    criterion = row()
    criterion["_quantityKindCheck"] = {"changed": True}
    llm = replay([RuntimeError("offline"), {"record_change": "none"}, {}])
    assert annotation.annotate_row(criterion, [], "inclusion", model="stub", llm=llm) == "error"
    assert "_quantityKindCheck" not in criterion


def test_should_check_kind_after_agreement_and_exception_check_when_both_are_needed():
    criterion = row()
    payload = {**fields(), "excepted_entities": [{"text": "stenosis", "span": "stenosis"}],
               "base_span": "revascularization"}
    llm = replay([payload, payload, {"answer": "removed"},
                  {"answer": "no"}, {"answer": "no"}, {"record_change": "none"}, {}])
    annotation.annotate_row(criterion, [], "inclusion", model="stub", llm=llm)
    assert criterion["_annotationAgreement"]
    assert criterion["_exceptionCheck"][0]["calls"][0]["answer"] == "removed"
    assert criterion["_quantityKindCheck"]["changed"] is True
    assert llm.invoke.call_count == 7
