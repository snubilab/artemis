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

``ALL`` over two absences is De Morgan and is correct; ``_effective_group_type``
owns it. The defect is that the excepted entity is a MEMBER at all.

No live LLM here: the planner's single call is mocked, and the mapper in the last
class is a stub that records the phrases it was asked.
"""
from unittest.mock import MagicMock, patch

from src.agents.planner.decomposer import CriteriaPlanner
from src.models.ir import Criteria, TemporalWindow
from src.services.entity_exception import detect_entity_exception
from src.services.entity_subtraction import resolve_entity_exception

# Verbatim, from the EMPA-REG protocol, as it stands in
# data/cache/agent1_ir/NCT01131676_vllm_google_gemma-4-E4B-it_17eaf31c786b5abb.json
EMPA_REG_LINE = (
    "Medical history of cancer (except for basal cell carcinoma) and/or treatment "
    "for cancer within the last 5 years"
)

# The split as it really happened, reconstructed from the run's own log line
# (output/site_gap/2026-09-14/reingest.log:3383) and the three store rows it
# produced (store/studies.json, study 8, exclusion ids 18/19/20).
EMPA_REG_SPLIT_RESPONSE = """```json
{
  "decompose": true,
  "reasoning": "cancer with a carve-out",
  "sub_criteria": [
    {"name": "Cancer diagnosis (excluding basal cell carcinoma)", "entity_text": "Cancer", "domain": "Condition", "source_span": "Cancer", "value_constraint_text": null},
    {"name": "Basal cell carcinoma exclusion", "entity_text": "Basal cell carcinoma", "domain": "Condition", "source_span": "basal cell carcinoma", "value_constraint_text": null}
  ]
}
```"""


def _planner_with_mocked_llm(content: str) -> CriteriaPlanner:
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=content)
    with patch("src.agents.planner.decomposer.get_llm", return_value=mock_llm):
        return CriteriaPlanner()


def _empa_reg_cancer_criterion() -> Criteria:
    return Criteria(
        name="Medical history of cancer",
        domain="Condition",
        entity_text="Cancer",
        source_text=EMPA_REG_LINE,
        logic_type="ABSENCE",
        window=TemporalWindow(start=-1825, end=0),
    )


class TestTheSplitIsDeclined:

    def test_should_keep_one_criterion_when_the_split_would_make_the_exception_a_sibling(self):
        planner = _planner_with_mocked_llm(EMPA_REG_SPLIT_RESPONSE)

        result = planner._decompose_criterion(_empa_reg_cancer_criterion())

        assert result.sub_criteria == [], (
            "the excepted entity is still a sibling criterion: "
            f"{[s.entity_text for s in result.sub_criteria]}"
        )

    def test_should_carry_the_exception_in_the_text_the_mapper_is_seeded_on(self):
        planner = _planner_with_mocked_llm(EMPA_REG_SPLIT_RESPONSE)

        result = planner._decompose_criterion(_empa_reg_cancer_criterion())

        # `entity_text` reaches the store as `sourceText`
        # (tte_service._criterion_dict_from_ir_item: `source_text = entity_text`),
        # and `criterion_mapper_seed` prefers `sourceText` over `description`.
        # A repair that fixed only the description would be invisible to the mapper.
        exception = detect_entity_exception(result.entity_text)
        assert exception is not None, f"the mapper seed states no exception: {result.entity_text!r}"
        assert exception.base == "Cancer"
        assert exception.excepted == ["basal cell carcinoma"]

    def test_should_leave_the_protocol_line_untouched(self):
        planner = _planner_with_mocked_llm(EMPA_REG_SPLIT_RESPONSE)

        result = planner._decompose_criterion(_empa_reg_cancer_criterion())

        assert result.source_text == EMPA_REG_LINE


class TestADeclinedParseChangesNothing:
    """The parser declines 19 of the 32 corpus strings, each under a named rule.
    A decline must fall through to the split exactly as before -- not to a third
    path, and not to a guess.
    """

    # Three of the declines, each a different rule in entity_exception.
    HYPHENATED_NON_X = (
        "Non-ST-segment elevation myocardial infarction"  # `non-` is part of a term
    )
    ANAPHORIC = (
        "Other antidiabetic drugs (excluding allowed short-term insulin)"  # `allowed`
    )
    GROUP_LABEL_JOIN = (
        "Unreliable/Non-compliant + Life Expectancy < 5 years "
        "+ Cancer other than nonmelanoma skin cancer"  # ` + ` joins criteria
    )

    SPLIT_RESPONSE = """```json
{
  "decompose": true,
  "reasoning": "two members",
  "sub_criteria": [
    {"name": "First member", "entity_text": "Hemodialysis", "domain": "Condition", "source_span": null, "value_constraint_text": null},
    {"name": "Second member", "entity_text": "Peritoneal dialysis", "domain": "Condition", "source_span": null, "value_constraint_text": null}
  ]
}
```"""

    def test_should_still_split_when_the_parser_declines_a_hyphenated_non_x(self):
        assert detect_entity_exception(self.HYPHENATED_NON_X) is None
        planner = _planner_with_mocked_llm(self.SPLIT_RESPONSE)

        result = planner._decompose_criterion(Criteria(
            name=self.HYPHENATED_NON_X, domain="Condition", entity_text="Dialysis",
            source_text=self.HYPHENATED_NON_X, logic_type="ABSENCE",
        ))

        assert [s.entity_text for s in result.sub_criteria] == [
            "Hemodialysis", "Peritoneal dialysis"]
        assert result.entity_text == "Dialysis"

    def test_should_still_split_when_the_parser_declines_an_anaphoric_exception(self):
        assert detect_entity_exception(self.ANAPHORIC) is None
        planner = _planner_with_mocked_llm(self.SPLIT_RESPONSE)

        result = planner._decompose_criterion(Criteria(
            name=self.ANAPHORIC, domain="Drug", entity_text="Other antidiabetic drug",
            source_text=self.ANAPHORIC, logic_type="ABSENCE",
        ))

        assert [s.entity_text for s in result.sub_criteria] == [
            "Hemodialysis", "Peritoneal dialysis"]
        assert result.entity_text == "Other antidiabetic drug"

    def test_should_still_split_when_the_parser_declines_a_group_label_join(self):
        assert detect_entity_exception(self.GROUP_LABEL_JOIN) is None
        planner = _planner_with_mocked_llm(self.SPLIT_RESPONSE)

        result = planner._decompose_criterion(Criteria(
            name=self.GROUP_LABEL_JOIN, domain="Condition", entity_text="Patient reliability",
            source_text=self.GROUP_LABEL_JOIN, logic_type="ABSENCE",
        ))

        assert [s.entity_text for s in result.sub_criteria] == [
            "Hemodialysis", "Peritoneal dialysis"]
        assert result.entity_text == "Patient reliability"


class TestALegitimateDecompositionIsNotCollapsed:
    """LEADER's insulin line states THREE exceptions and names no excepted entity
    as a member of its own. Each member carries its own exception already, so the
    split is a reading, not an inversion, and must survive.
    """

    LEADER_LINE = (
        "Use of insulin other than human NPH insulin or long-acting insulin analogue "
        "or premixed insulin within 3 months prior to screening"
    )
    RESPONSE = """```json
{
  "decompose": true,
  "reasoning": "three permitted insulins",
  "sub_criteria": [
    {"name": "Insulin other than human NPH insulin", "entity_text": "insulin other than human NPH insulin", "domain": "Drug", "source_span": null, "value_constraint_text": null},
    {"name": "Insulin other than long-acting insulin analogue", "entity_text": "insulin other than long-acting insulin analogue", "domain": "Drug", "source_span": null, "value_constraint_text": null},
    {"name": "Insulin other than premixed insulin", "entity_text": "insulin other than premixed insulin", "domain": "Drug", "source_span": null, "value_constraint_text": null}
  ]
}
```"""

    def test_should_keep_the_three_members_when_no_member_is_the_excepted_entity(self):
        planner = _planner_with_mocked_llm(self.RESPONSE)

        result = planner._decompose_criterion(Criteria(
            name="Use of other insulin within 3 months prior to screening",
            domain="Drug", entity_text="insulin", source_text=self.LEADER_LINE,
            logic_type="ABSENCE", window=TemporalWindow(start=-90, end=0),
        ))

        assert len(result.sub_criteria) == 3
        assert result.entity_text == "insulin"


class TestTheRemainingGatesFire:
    """Each gate shown refusing a case it exists to refuse, not only passing one.

    A gate that has only ever been watched succeeding is indistinguishable from
    one that does nothing.
    """

    def test_should_not_subtract_an_excepted_entity_the_protocol_line_never_names(self):
        # Same members, same parse -- but the line has had the carve-out removed,
        # so "basal cell carcinoma" is now the model's word and nobody else's.
        # Subtracting on that would create a new wrong exclusion, which is the
        # failure the whole exception machinery exists to prevent.
        planner = _planner_with_mocked_llm(EMPA_REG_SPLIT_RESPONSE)

        result = planner._decompose_criterion(Criteria(
            name="Medical history of cancer", domain="Condition", entity_text="Cancer",
            source_text="Medical history of cancer and/or treatment for cancer "
                        "within the last 5 years",
            logic_type="ABSENCE", window=TemporalWindow(start=-1825, end=0),
        ))

        assert [s.entity_text for s in result.sub_criteria] == ["Cancer", "Basal cell carcinoma"]
        assert result.entity_text == "Cancer"

    def test_should_not_rebuild_a_seed_that_no_longer_states_the_same_exception(self):
        # An entity text that already carries a connective rebuilds into
        # "Cancer other than melanoma other than basal cell carcinoma", which the
        # parser reads as excepting the whole tail. Returning that would lose the
        # exception in a new place instead of the old one, so the split stands.
        planner = _planner_with_mocked_llm(EMPA_REG_SPLIT_RESPONSE)

        result = planner._decompose_criterion(Criteria(
            name="Medical history of cancer", domain="Condition",
            entity_text="Cancer other than melanoma", source_text=EMPA_REG_LINE,
            logic_type="ABSENCE", window=TemporalWindow(start=-1825, end=0),
        ))

        assert [s.entity_text for s in result.sub_criteria] == ["Cancer", "Basal cell carcinoma"]
        assert result.entity_text == "Cancer other than melanoma"


class TestTheExceptionReachesTheMapper:
    """End of the chain: the kept criterion's seed is resolved as TWO phrases.

    The mapper is stubbed -- no LLM, no embedding, no database. What is asserted
    is the call sequence and the resulting concept set, not a live mapping.
    """

    CANCER = [4112853, 443392]      # base 'Cancer'
    BCC = [4112853]                 # 'basal cell carcinoma', a member of the base

    def test_should_map_the_base_and_the_excepted_phrase_in_that_order(self):
        planner = _planner_with_mocked_llm(EMPA_REG_SPLIT_RESPONSE)
        kept = planner._decompose_criterion(_empa_reg_cancer_criterion())

        asked: list[str] = []

        def map_phrase(phrase: str) -> dict:
            asked.append(phrase)
            ids = self.BCC if phrase == "basal cell carcinoma" else self.CANCER
            return {"name": phrase, "domain": "Condition", "expression": {"items": [
                {"concept": {"CONCEPT_ID": cid, "CONCEPT_NAME": f"c{cid}"},
                 "isExcluded": False, "includeDescendants": True} for cid in ids]}}

        exception = detect_entity_exception(kept.entity_text)
        resolution = resolve_entity_exception(exception, map_phrase)

        assert asked == ["Cancer", "basal cell carcinoma"]
        assert resolution.fallback_reason == ""
        items = resolution.mapping["expression"]["items"]
        assert [i["concept"]["CONCEPT_ID"] for i in items if i["isExcluded"]] == self.BCC
        assert [i["concept"]["CONCEPT_ID"] for i in items if not i["isExcluded"]] == [443392]
