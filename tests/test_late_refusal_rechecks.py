"""Late checks use recorded model decisions and grounded spans, never text heuristics."""

import json
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from src.services import criterion_annotation as annotation
from src.services import value_constraint as constraints
from src.services.tte_service import TTEService
from src.utils.circe_lint import CRITERION_CONCEPT_SET_REFS_KEY, trial_only_occurrence_criteria
from src.utils.criterion_refusal import CriterionRefused

LINE = "In South Africa: blood pressure >160/100 mmHg at screening"


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_ANNOTATION_CACHE_PATH", str(tmp_path / "annotations.jsonl"))
    annotation.reset_for_tests()
    yield
    annotation.reset_for_tests()


def replay(monkeypatch, answers):
    llm = MagicMock()
    llm.invoke.side_effect = [
        answer if isinstance(answer, Exception) else AIMessage(content=json.dumps(answer))
        for answer in answers
    ]
    monkeypatch.setattr(annotation, "_build_llm", lambda model: llm)
    return llm


def row(requirement="forbidden"):
    line = "Contraindications to background therapy according to the local label"
    return {
        "id": 24,
        "sourceText": "Contraindications",
        "description": "Contraindications",
        "protocolLine": line,
        "protocolSpan": line,
        "domain": "Condition",
        "annotation": {"record_requirement": requirement},
    }


@pytest.mark.parametrize(
    "answers,expected,count",
    [
        ([{"recordable": "no"}, {"recordable": "no"}], True, 2),
        ([{"recordable": "no"}, {"recordable": "yes"}], False, 2),
        ([{"recordable": "yes"}], False, 1),
        ([{"recordable": "no"}, RuntimeError("offline")], False, 2),
        ([{"recordable": "no"}, {}], False, 2),
        ([RuntimeError("offline")], False, 1),
        ([{"recordable": "unreadable"}], False, 1),
    ],
)
def test_should_confirm_only_agreed_no_when_rechecking_recordability(
    monkeypatch, answers, expected, count
):
    llm = replay(monkeypatch, answers)
    criterion = row()
    fragment = annotation.check_not_recordable(criterion)
    assert (fragment == criterion["protocolLine"]) is expected
    assert llm.invoke.call_count == count
    calls = criterion["_notRecordableCheck"]["calls"]
    assert len(calls) == count
    assert all({"promptVersion", "cacheKey", "outcome", "answer"} <= call.keys() for call in calls)


@pytest.mark.parametrize("requirement", ["conditional", None])
def test_should_not_call_when_row_is_neither_required_nor_forbidden(monkeypatch, requirement):
    llm = replay(monkeypatch, [])
    assert annotation.check_not_recordable(row(requirement)) is None
    llm.invoke.assert_not_called()


def test_should_reuse_cached_calls_when_same_recordability_question_is_repeated(monkeypatch):
    llm = replay(monkeypatch, [{"recordable": "no"}, {"recordable": "no"}])
    annotation.check_not_recordable(row())
    criterion = row()
    annotation.check_not_recordable(criterion)
    assert llm.invoke.call_count == 2
    assert all(call["outcome"] == "cached" for call in criterion["_notRecordableCheck"]["calls"])


def test_should_block_emitted_row_when_both_recordability_calls_say_no(monkeypatch):
    replay(monkeypatch, [{"recordable": "no"}, {"recordable": "no"}])
    criterion = row()
    annotation.check_not_recordable(criterion)
    study = {"eligibility": {"exclusionCriteria": [criterion]}}
    expression = {CRITERION_CONCEPT_SET_REFS_KEY: {"exclusion:24": 10}}
    assert "not-recordable" in trial_only_occurrence_criteria(expression, study)[0]
    expression[CRITERION_CONCEPT_SET_REFS_KEY] = {}
    assert trial_only_occurrence_criteria(expression, study) == []


BOUND = {"op": "gt", "value": 100, "unit": "mmHg", "span": ">160/100 mmHg"}


def member():
    return {
        "id": 52,
        "description": "Diastolic blood pressure",
        "sourceText": "Diastolic blood pressure",
        "protocolLine": LINE,
        "domain": "Measurement",
        "logicType": "ABSENCE",
        "window": {"start": -180, "end": 0},
    }


@pytest.mark.parametrize(
    "answer,compatible,accepted",
    [
        (BOUND, True, True),
        ({**BOUND, "span": "not in line"}, True, False),
        ({**BOUND, "value": 10}, True, False),
        ({**BOUND, "unit": None}, True, False),
        ({**BOUND, "unit": "unresolved-ucum"}, True, False),
        (BOUND, False, False),
        (RuntimeError("offline"), True, False),
        ({**BOUND, "op": "bad"}, True, False),
        ({**BOUND, "value": True}, True, False),
    ],
)
def test_should_accept_only_grounded_compatible_bound_when_group_constraint_is_stranded(
    monkeypatch, caplog, answer, compatible, accepted
):
    replay(monkeypatch, [answer])
    monkeypatch.setattr(
        constraints,
        "check_analyte_unit",
        lambda props, unit: constraints.AnalyteUnitCheck(compatible, "incompatible"),
    )
    monkeypatch.setattr(
        constraints,
        "resolve_unit_constraint",
        lambda vc, seed: (vc, "alias" if constraints.absolute_unit_concept_id(vc) else None),
    )
    criterion = member()
    vc, provenance = constraints.recheck_member_bound(criterion, {1: "Pressure"})
    assert (vc is not None) is accepted
    if accepted:
        assert vc["value"] == 100
        assert constraints.absolute_unit_concept_id(vc) == 8876
        assert provenance == "alias"
        assert criterion["_memberBoundCheck"]["boundSource"] == "member-recheck"
    if isinstance(answer, Exception):
        assert "offline" in caplog.text


@pytest.mark.parametrize(
    "answer,properties,accepted",
    [
        (BOUND, {1: "Pressure"}, True),
        ({**BOUND, "span": "not in line"}, {1: "Pressure"}, False),
        ({**BOUND, "value": 10}, {1: "Pressure"}, False),
        ({**BOUND, "unit": None}, {1: "Pressure"}, False),
        (BOUND, {1: "Mass concentration"}, False),
        (RuntimeError("offline"), {1: "Pressure"}, False),
    ],
)
def test_should_emit_only_verified_member_bound_when_group_threshold_is_stranded(
    monkeypatch,
    caplog,
    answer,
    properties,
    accepted,
):
    replay(monkeypatch, [answer])
    svc = TTEService.__new__(TTEService)
    svc._concept_set_lab_properties = lambda expression: properties
    svc._with_stated_route = lambda mapped, *args: mapped
    svc._refine_measurement_specimen = lambda expression, **kwargs: (expression, None)
    mapped = {
        "name": "Diastolic blood pressure",
        "domain": "Measurement",
        "expression": {"items": [{"concept": {"CONCEPT_ID": 1, "DOMAIN_ID": "Measurement"}}]},
    }
    criterion = member()
    kwargs = dict(
        criterion=criterion,
        codeset_id=1,
        exclusion=True,
        mapped_override=mapped,
        parent_value_constraint={
            "op": "gt",
            "value": 160,
            "unitText": "",
            "referenceBound": "absolute",
        },
    )
    if not accepted:
        with pytest.raises(CriterionRefused) as exc:
            svc._build_seeded_eligibility_rule(**kwargs)
        assert exc.value.code == "stranded-group-threshold"
        assert exc.value.detail == constraints.STRANDED_GROUP_CONSTRAINT_REASON
        if isinstance(answer, Exception):
            assert "offline" in caplog.text
        return
    built = svc._build_seeded_eligibility_rule(**kwargs)
    body = built["rule"]["expression"]["CriteriaList"][0]["Criteria"]["Measurement"]
    assert body["ValueAsNumber"] == {"Value": 100, "Op": "gt"}
    assert body["Unit"][0]["CONCEPT_ID"] == 8876
    assert criterion["_memberBoundCheck"]["boundSource"] == "member-recheck"


@pytest.mark.parametrize(
    "answers,code",
    [
        ([{"recordable": "no"}, {"recordable": "no"}], "unmappable-placeholder"),
        ([{"recordable": "no"}, {"recordable": "yes"}], "reranker-no-match"),
        ([{"recordable": "yes"}], "reranker-no-match"),
        ([RuntimeError("offline")], "reranker-no-match"),
    ],
)
def test_should_preserve_refusal_unless_both_no_when_mapper_refuses(monkeypatch, answers, code):
    replay(monkeypatch, answers)
    svc = TTEService.__new__(TTEService)
    from src.models.ir import MappingResult
    from tests.test_reranker_no_match_refuses_the_criterion import _recommend

    fallback = MagicMock()
    svc._recommend_seeded_concept_set = lambda seed, **kwargs: _recommend(
        svc,
        seed,
        MappingResult(concept_ids=[], route_path="slow", reranker_no_match=60),
        fallback,
        **kwargs,
    )
    criterion = row()
    with pytest.raises(CriterionRefused) as exc:
        svc._build_seeded_eligibility_rule(criterion=criterion, codeset_id=1, exclusion=True)
    assert exc.value.code == code
    assert "_notRecordableCheck" in criterion
    if code == "unmappable-placeholder":
        assert exc.value.detail == criterion["protocolLine"]
        assert "not-recordable" in str(exc.value)
    else:
        assert exc.value.detail == "60 candidates offered, none selected"
        assert "reranker_no_match" in str(exc.value)
    fallback.assert_not_called()


@pytest.mark.parametrize("requirement", ["forbidden", "required"])
def test_should_record_the_verified_fragment_when_trial_participation_is_not_recordable(
    monkeypatch,
    requirement,
):
    replay(monkeypatch, [{"recordable": "no"}, {"recordable": "no"}])
    line = (
        "Participation in another trial with an investigational drug given within "
        "2 months prior to informed consent"
    )
    criterion = {**row(requirement), "protocolLine": line, "protocolSpan": "investigational drug"}
    assert annotation.check_not_recordable(criterion) == "investigational drug"
    criterion["protocolLine"] = "edited line"
    assert annotation.stated_not_recordable(criterion) is None
