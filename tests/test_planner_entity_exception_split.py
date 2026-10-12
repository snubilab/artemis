"""The planner must not turn a stated entity exception into a sibling criterion.

EMPA-REG's protocol line is verbatim::

    Medical history of cancer (except for basal cell carcinoma) and/or treatment
    for cancer within the last 5 years

Agent 1 reads it as ONE criterion -- ``entity_text='Cancer'``, no ``sub_criteria``
in any of the eleven cached NCT01131676 extractions. The planner then split it in
two, and the 2026-09-14 delivery shipped the inversion::

    InclusionRules[17] 'Cancer diagnosis (excluding basal cell carcinoma)
                        + Basal cell carcinoma exclusion'   Type: ALL
        codeset 21 'Cancer'                Occurrence {Type: 0, Count: 0}
        codeset 22 'Basal cell carcinoma'  Occurrence {Type: 0, Count: 0}

"zero cancers AND zero basal cell carcinomas". The exception became an additional
exclusion, so the patient the protocol admits -- whose only malignancy is a BCC --
is the one it removes.

RFC-016 §3: the planner's own output carries ``excepted_entities`` -- each entry a name
and the fragment of the protocol line that names it -- and the planner keeps the
criterion whole when one of the members it proposed IS a stated exception. No regex reads
the line; the only text test is that each span is a substring of the line.

No live LLM here: the planner's single call is mocked.
"""
from unittest.mock import MagicMock, patch

from src.agents.planner.decomposer import CriteriaPlanner
from src.models.ir import Criteria, TemporalWindow
from src.services.criterion_annotation import PLANNER_EXCEPTED_KEY, stated_exceptions
from src.services.tte_service import TTEService

# Verbatim, from the EMPA-REG protocol, as it stands in
# data/cache/agent1_ir/NCT01131676_vllm_google_gemma-4-E4B-it_17eaf31c786b5abb.json
EMPA_REG_LINE = (
    "Medical history of cancer (except for basal cell carcinoma) and/or treatment "
    "for cancer within the last 5 years"
)

_MEMBERS = """
  "sub_criteria": [
    {"name": "Cancer diagnosis (excluding basal cell carcinoma)", "entity_text": "Cancer", "domain": "Condition", "source_span": "cancer", "value_constraint_text": null},
    {"name": "Basal cell carcinoma exclusion", "entity_text": "Basal cell carcinoma", "domain": "Condition", "source_span": "basal cell carcinoma", "value_constraint_text": null}
  ]"""


def _response(excepted: str) -> str:
    """The split as it really happened (store study 8, exclusion ids 18/19/20), with the
    planner's ``excepted_entities`` answer set to ``excepted`` (a JSON list)."""
    return (
        '{"decompose": true, "reasoning": "cancer with a carve-out", '
        f'"excepted_entities": {excepted},' + _MEMBERS + "}"
    )


STATED = '[{"text": "basal cell carcinoma", "span": "basal cell carcinoma"}]'


def _planner_with_mocked_llm(content: str) -> CriteriaPlanner:
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=content)
    with patch("src.agents.planner.decomposer.get_llm", return_value=mock_llm):
        return CriteriaPlanner()


def _empa_reg_cancer_criterion(line: str = EMPA_REG_LINE) -> Criteria:
    return Criteria(
        name="Medical history of cancer",
        domain="Condition",
        entity_text="Cancer",
        source_text=line,
        logic_type="ABSENCE",
        window=TemporalWindow(start=-1825, end=0),
    )


class TestTheSplitIsDeclined:
    def test_should_keep_one_criterion_when_a_member_is_the_stated_exception(self):
        result = _planner_with_mocked_llm(_response(STATED))._decompose_criterion(
            _empa_reg_cancer_criterion())
        assert result.sub_criteria == [], (
            "the excepted entity is still a sibling criterion: "
            f"{[s.entity_text for s in result.sub_criteria]}"
        )

    def test_should_carry_the_exception_as_a_field_and_leave_the_entity_alone(self):
        result = _planner_with_mocked_llm(_response(STATED))._decompose_criterion(
            _empa_reg_cancer_criterion())
        assert result.entity_text == "Cancer"
        assert [(e.text, e.span) for e in result.excepted_entities] == [
            ("basal cell carcinoma", "basal cell carcinoma")]
        assert result.source_text == EMPA_REG_LINE

    def test_should_reach_the_store_row_where_the_mapper_reads_it(self):
        kept = _planner_with_mocked_llm(_response(STATED))._decompose_criterion(
            _empa_reg_cancer_criterion())
        [row] = TTEService.__new__(TTEService)._criteria_from_ir([kept])
        assert row[PLANNER_EXCEPTED_KEY] == [
            {"text": "basal cell carcinoma", "span": "basal cell carcinoma"}]
        assert [e["text"] for e in stated_exceptions(row)] == ["basal cell carcinoma"]


class TestTheSplitStands:
    def test_should_split_when_the_planner_states_no_exception(self):
        """The line's words decide nothing: no field, no keep-whole."""
        result = _planner_with_mocked_llm(_response("[]"))._decompose_criterion(
            _empa_reg_cancer_criterion())
        assert [s.entity_text for s in result.sub_criteria] == ["Cancer", "Basal cell carcinoma"]
        assert result.excepted_entities == []

    def test_should_split_when_the_exception_span_is_not_in_the_line(self):
        """The line without its carve-out: "basal cell carcinoma" is the model's word."""
        result = _planner_with_mocked_llm(_response(STATED))._decompose_criterion(
            _empa_reg_cancer_criterion(
                "Medical history of cancer and/or treatment for cancer within the last 5 years"))
        assert [s.entity_text for s in result.sub_criteria] == ["Cancer", "Basal cell carcinoma"]
        assert result.excepted_entities == []

    def test_should_keep_the_members_when_none_of_them_is_an_excepted_entity(self):
        """LEADER's insulin line excepts three insulins and names none of them as a
        member, so the split is a reading and survives; the parent records the field."""
        line = ("Use of insulin other than human NPH insulin or long-acting insulin analogue "
                "or premixed insulin within 3 months prior to screening")
        response = """{
  "decompose": true,
  "reasoning": "three permitted insulins",
  "excepted_entities": [
    {"text": "human NPH insulin", "span": "human NPH insulin"},
    {"text": "long-acting insulin analogue", "span": "long-acting insulin analogue"},
    {"text": "premixed insulin", "span": "premixed insulin"}
  ],
  "sub_criteria": [
    {"name": "Insulin other than human NPH insulin", "entity_text": "insulin other than human NPH insulin", "domain": "Drug", "source_span": null, "value_constraint_text": null},
    {"name": "Insulin other than long-acting insulin analogue", "entity_text": "insulin other than long-acting insulin analogue", "domain": "Drug", "source_span": null, "value_constraint_text": null},
    {"name": "Insulin other than premixed insulin", "entity_text": "insulin other than premixed insulin", "domain": "Drug", "source_span": null, "value_constraint_text": null}
  ]
}"""
        result = _planner_with_mocked_llm(response)._decompose_criterion(Criteria(
            name="Use of other insulin within 3 months prior to screening",
            domain="Drug", entity_text="insulin", source_text=line,
            logic_type="ABSENCE", window=TemporalWindow(start=-90, end=0),
        ))
        assert len(result.sub_criteria) == 3
        assert result.entity_text == "insulin"
        assert [e.text for e in result.excepted_entities] == [
            "human NPH insulin", "long-acting insulin analogue", "premixed insulin"]

    def test_should_record_the_field_on_an_atomic_criterion_too(self):
        response = ('{"decompose": false, "reasoning": "one concept", '
                    f'"excepted_entities": {STATED}, "sub_criteria": []}}')
        result = _planner_with_mocked_llm(response)._decompose_criterion(
            _empa_reg_cancer_criterion())
        assert result.sub_criteria == []
        assert [e.text for e in result.excepted_entities] == ["basal cell carcinoma"]
