"""A decomposition member says which part of the protocol line named it, or admits it invented itself.

The defect this pins: ``DECOMPOSITION_PROMPT`` asked whether ``entity_text`` -- the
model's clinical knowledge of a term -- was composite, and never asked what the
protocol actually wrote. Its threshold half was already grounded ("copy only text that
is actually present in Source Text, never invent or estimate a number"), so the
asymmetry was specific: numbers were guarded, sub-terms were not.

Measured on CAROLINA/NCT01243424, whose protocol line reads, in full::

    - acute liver disease or impaired hepatic function

That line names no analyte and no threshold. Extraction produced ALT + AST + ALP at
``3x ULN`` in one recorded run and ALT alone in another; neither is a reading of the
line. Across the whole 09-10 CAROLINA store the strings ``Aspartate``, ``Alkaline``,
``AST``, ``ALP`` and ``phosphatase`` appear zero times, so a collapse from three
analytes to one leaves no trace either.

Elaborating that line is legitimate and is what the pipeline is FOR -- "impaired
hepatic function" is unqueryable as written, and refusing to decompose it would lose
the criterion outright. The defect is that nothing marked WHICH sub-terms the protocol
named. So the fix is a mark, and the mark is a verbatim span rather than a boolean,
because the model's own account of where a term came from is exactly the thing that
cannot be taken on trust here: ``stated: true`` on an invented analyte is
indistinguishable from the truth, while a span either is in the line or is not.

``_grounded_span`` is that check, and the cases below run it against the real line and
the really-observed inventions, not only against synthetic text.
"""
from unittest.mock import MagicMock, patch

from src.agents.planner import prompts
from src.agents.planner.decomposer import CriteriaPlanner, _grounded_span
from src.models.ir import Criteria


# Verbatim, from the CAROLINA protocol. The whole point of this line is what it does
# not contain: no analyte, no comparator, no number.
CAROLINA_UNGROUNDED_LINE = "acute liver disease or impaired hepatic function"

# Verbatim, from ARISTOTLE. This line names its three analytes outright, so a
# three-way decomposition of it IS a reading and must stay one.
ARISTOTLE_GROUNDED_LINE = "ALT or AST > 2X ULN or Total Bilirubin >= 1.5X ULN"


def _mock_llm(content: str) -> MagicMock:
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=content)
    return mock_llm


def _planner_with_mocked_llm(content: str) -> CriteriaPlanner:
    with patch("src.agents.planner.decomposer.get_llm", return_value=_mock_llm(content)):
        return CriteriaPlanner()


# The invention as it was actually observed: three analytes, each claiming a span, off
# a line that names none of them. A model asked for a span will happily produce one.
CAROLINA_INVENTED_RESPONSE = """```json
{
  "decompose": true,
  "reasoning": "hepatic panel",
  "sub_criteria": [
    {"name": "Elevated ALT", "entity_text": "Alanine aminotransferase (ALT) elevation", "domain": "Measurement", "source_span": "impaired hepatic function", "value_constraint_text": null},
    {"name": "Elevated AST", "entity_text": "Aspartate aminotransferase (AST) elevation", "domain": "Measurement", "source_span": "Aspartate aminotransferase", "value_constraint_text": "3x ULN"},
    {"name": "Elevated ALP", "entity_text": "Alkaline phosphatase elevation", "domain": "Measurement", "source_span": "alkaline phosphatase", "value_constraint_text": "3x ULN"}
  ]
}
```"""

# The reading, off the line that supports it.
ARISTOTLE_GROUNDED_RESPONSE = """```json
{
  "decompose": true,
  "reasoning": "the line enumerates three analytes",
  "sub_criteria": [
    {"name": "Elevated ALT", "entity_text": "Alanine aminotransferase (ALT) elevation", "domain": "Measurement", "source_span": "ALT", "value_constraint_text": "> 2X ULN"},
    {"name": "Elevated AST", "entity_text": "Aspartate aminotransferase (AST) elevation", "domain": "Measurement", "source_span": "AST", "value_constraint_text": "> 2X ULN"},
    {"name": "Elevated Bilirubin", "entity_text": "Total bilirubin elevation", "domain": "Measurement", "source_span": "Total Bilirubin", "value_constraint_text": ">= 1.5X ULN"}
  ]
}
```"""


class TestGroundedSpanGate:
    """The check itself, against the line that motivated it."""

    def test_should_keep_the_span_when_the_line_really_names_the_sub_term(self):
        assert _grounded_span(
            "Total Bilirubin", ARISTOTLE_GROUNDED_LINE, "Total bilirubin elevation"
        ) == "Total Bilirubin"

    def test_should_reject_an_analyte_the_carolina_line_never_names(self):
        # The real invention: "alkaline phosphatase" is nowhere in the real line.
        assert _grounded_span(
            "alkaline phosphatase", CAROLINA_UNGROUNDED_LINE, "Alkaline phosphatase elevation"
        ) is None
        assert _grounded_span(
            "Aspartate aminotransferase", CAROLINA_UNGROUNDED_LINE,
            "Aspartate aminotransferase (AST) elevation",
        ) is None

    def test_should_reject_a_real_span_that_names_the_umbrella_not_the_sub_term(self):
        # Gate 1 alone is not enough, and this is the case that proves it. "impaired
        # hepatic function" IS a verbatim substring of the CAROLINA line -- the model
        # returned exactly this for an ALT sub-term. Every elaborated member can cite
        # the umbrella it was elaborated from, so accepting it would let the whole
        # failure through wearing a grounding mark.
        assert _grounded_span(
            "impaired hepatic function", CAROLINA_UNGROUNDED_LINE,
            "Alanine aminotransferase (ALT) elevation",
        ) is None
        # ... while the umbrella span is still accepted for a sub-term it does name.
        assert _grounded_span(
            "impaired hepatic function", CAROLINA_UNGROUNDED_LINE, "Impaired hepatic function"
        ) == "impaired hepatic function"

    def test_should_tolerate_case_and_whitespace_drift_in_a_real_copy(self):
        # A model that re-wraps or re-cases a fragment still copied it. Tolerating that
        # cannot admit an invention, which is absent under every one of these forms.
        assert _grounded_span(
            "total   bilirubin", ARISTOTLE_GROUNDED_LINE, "Elevated Bilirubin"
        ) == "total   bilirubin"
        assert _grounded_span(
            "alt", ARISTOTLE_GROUNDED_LINE, "Alanine aminotransferase (ALT) elevation"
        ) == "alt"

    def test_should_reject_an_operand_only_span_that_names_nothing(self):
        # "> 2X ULN" is a real substring of the line and names no clinical term. The
        # operand belongs to value_constraint_text; a sub-term's span must carry a term.
        # Note is_headless() does NOT catch this one -- measured False, because "ULN"
        # is not a unit normalize_unit recognises -- so the naming-word gate is what
        # refuses it.
        assert _grounded_span(
            "> 2X ULN", ARISTOTLE_GROUNDED_LINE, "Alanine aminotransferase (ALT) elevation"
        ) is None
        assert _grounded_span(
            "2", ARISTOTLE_GROUNDED_LINE, "Alanine aminotransferase (ALT) elevation"
        ) is None

    def test_should_refuse_every_span_when_the_line_is_blank(self):
        # The pre-6d0c42f population, and any criterion whose source_text Agent 1 did
        # not record. Nothing is verifiable against nothing, so nothing is claimed.
        assert _grounded_span("ALT", "", "Alanine aminotransferase (ALT) elevation") is None

    def test_should_treat_a_missing_or_nullish_claim_as_no_span(self):
        term = "Alanine aminotransferase (ALT) elevation"
        assert _grounded_span(None, ARISTOTLE_GROUNDED_LINE, term) is None
        assert _grounded_span("null", ARISTOTLE_GROUNDED_LINE, term) is None
        assert _grounded_span("", ARISTOTLE_GROUNDED_LINE, term) is None
        assert _grounded_span(17, ARISTOTLE_GROUNDED_LINE, term) is None


class TestDecompositionIsMarkedNotSuppressed:
    """Elaboration survives; it just stops looking like a reading."""

    def test_should_keep_invented_sub_terms_but_mark_them_all_as_elaboration(self):
        planner = _planner_with_mocked_llm(CAROLINA_INVENTED_RESPONSE)
        criterion = Criteria(
            name="Acute liver disease or impaired hepatic function",
            domain="Condition",
            entity_text="acute liver disease or impaired hepatic function",
            source_text=CAROLINA_UNGROUNDED_LINE,
            logic_type="ABSENCE",
        )

        result = planner._decompose_criterion(criterion)

        # The criterion is NOT lost -- decomposing it is what the pipeline is for.
        assert len(result.sub_criteria) == 3
        # But every member is marked as the model's own, including the two that
        # claimed a span. Both claims are refused because neither is in the line.
        assert [sc.source_span for sc in result.sub_criteria] == [None, None, None]
        # And each still carries the line it came from, so the pair reads as
        # "this line, and nothing in it named this term".
        assert {sc.source_text for sc in result.sub_criteria} == {CAROLINA_UNGROUNDED_LINE}

    def test_should_mark_sub_terms_as_read_when_the_line_names_them(self):
        planner = _planner_with_mocked_llm(ARISTOTLE_GROUNDED_RESPONSE)
        criterion = Criteria(
            name="Hepatic abnormality",
            domain="Measurement",
            entity_text="ALT or AST or Total Bilirubin elevation",
            source_text=ARISTOTLE_GROUNDED_LINE,
            logic_type="ABSENCE",
        )

        result = planner._decompose_criterion(criterion)

        assert len(result.sub_criteria) == 3
        assert [sc.source_span for sc in result.sub_criteria] == ["ALT", "AST", "Total Bilirubin"]

    def test_should_leave_decomposition_behaviour_unchanged_when_the_line_is_blank(self):
        # Decision on the blank-Source-Text path: behaviour is NOT changed. A
        # pre-6d0c42f study, or a criterion Agent 1 recorded no line for, still
        # decomposes from clinical knowledge -- refusing would regress criteria that
        # decompose correctly today, with no evidence of harm. What changes is that
        # the whole group is now marked as model-supplied, which is exactly true.
        planner = _planner_with_mocked_llm(CAROLINA_INVENTED_RESPONSE)
        criterion = Criteria(
            name="Acute liver disease or impaired hepatic function",
            domain="Condition",
            entity_text="acute liver disease or impaired hepatic function",
            source_text=None,
            logic_type="ABSENCE",
        )

        result = planner._decompose_criterion(criterion)

        assert len(result.sub_criteria) == 3
        assert all(sc.source_span is None for sc in result.sub_criteria)


class TestPromptAsksForTheSpan:
    """The gate can only refuse a span the prompt asked the model to produce."""

    def test_should_ask_for_source_span_in_the_output_shape(self):
        assert '"source_span"' in prompts.DECOMPOSITION_PROMPT

    def test_should_scope_the_question_to_the_protocol_line_not_only_the_entity(self):
        # The defect was that the question named only {entity_text}. It must now send
        # the model to Source Text first.
        assert "Read the Source Text above" in prompts.DECOMPOSITION_PROMPT

    def test_should_forbid_padding_a_list_the_line_already_enumerates(self):
        assert "Never pad an exhaustive list" in prompts.DECOMPOSITION_PROMPT


class TestTheSpanReachesTheStore:
    """A mark nobody can read is not a mark. It has to land on the row."""

    def test_should_carry_the_span_onto_the_member_row_and_leave_the_label_blank(self):
        from src.api.models.tte import CRITERION_PROTOCOL_SPAN_KEY, Criterion
        from src.services.tte_service import TTEService

        parent = Criteria(
            name="Hepatic abnormality", domain="Measurement",
            entity_text="ALT or AST or Total Bilirubin elevation",
            source_text=ARISTOTLE_GROUNDED_LINE, logic_type="ABSENCE", group_type="ANY",
            sub_criteria=[
                Criteria(name="Elevated ALT", domain="Measurement",
                         entity_text="Alanine aminotransferase (ALT) elevation",
                         source_text=ARISTOTLE_GROUNDED_LINE, source_span="ALT"),
                Criteria(name="Elevated ALP", domain="Measurement",
                         entity_text="Alkaline phosphatase elevation",
                         source_text=ARISTOTLE_GROUNDED_LINE, source_span=None),
            ],
        )
        rows = TTEService._criteria_from_ir(TTEService.__new__(TTEService), [parent])

        label, read, supplied = rows
        # The group label reads no fragment of its own line -- it IS the line.
        assert label["isGroupLabel"] is True
        assert label[CRITERION_PROTOCOL_SPAN_KEY] == ""
        assert read[CRITERION_PROTOCOL_SPAN_KEY] == "ALT"
        assert supplied[CRITERION_PROTOCOL_SPAN_KEY] == ""
        # Both members still carry the line, so the pair reads as "this line, and
        # this is / is not the part of it that named me".
        assert read["protocolLine"] == supplied["protocolLine"] == ARISTOTLE_GROUNDED_LINE
        assert Criterion.model_validate(read).protocolSpan == "ALT"

    def test_should_add_exactly_one_key_to_the_criterion_row(self):
        from src.api.models.tte import (
            CRITERION_PROTOCOL_LINE_KEY, CRITERION_PROTOCOL_SPAN_KEY,
        )
        from src.services.tte_service import TTEService

        item = Criteria(name="ALT", domain="Measurement", entity_text="ALT")
        row = TTEService._criterion_dict_from_ir_item(
            TTEService.__new__(TTEService), item, 1, "ALT"
        )

        assert set(row) - {
            "id", "description", "domain", "valueConstraint", "sourceText", "window",
            "logicType", "conceptSetId", "conceptSetName", "groupId", "groupType",
            CRITERION_PROTOCOL_LINE_KEY,
        } == {CRITERION_PROTOCOL_SPAN_KEY}


class TestPromptDoesNotLetTheSpanShrinkTheDecomposition:
    """Measured regression guard, not a style check.

    Asking for a span biases the model toward sub-terms that can CARRY one, i.e. terms
    that echo the line. Measured on PLATO/NCT00391872's real line "Persons with moderate
    or severe liver disease" at temperature 0, three runs per arm: the prompt without
    this clause returned ONE sub-term ("Liver disease", span-grounded) where the prior
    prompt returned three (Cirrhosis / Severe hepatitis / Advanced fibrosis). Marking an
    under-decomposition as *grounded* is worse than not marking it at all, because the
    span makes the collapse look correct. With the clause the same line returns five,
    all marked elaboration.

    RESIDUAL, measured on the shipped text over six real lines x three runs: the clause
    reduces the collapse but does not eliminate it. PLATO's "moderate or severe liver
    disease" still returns two line-echoing terms in 1 run of 3 (five in the other two,
    against old's steady three), and PLATO's "ECG indicating ischemia" returns a single
    "ECG finding of myocardial ischemia" in 3 of 3 -- though the old prompt returned
    ZERO sub-terms for that line, so it is not a depth regression there.

    The marking stayed honest in every one of those 18 runs: no sub-term the line did
    not name was ever marked as read from it, including inside the collapsed runs, and
    the gate refused nothing because the model claimed nothing false. The failure mode
    that survives is shallow decomposition, not mislabelled provenance.
    """

    def test_should_state_that_the_span_labels_the_decomposition_and_never_limits_it(self):
        assert "never limits it" in prompts.DECOMPOSITION_PROMPT

    def test_should_forbid_a_single_sub_term_that_restates_the_line(self):
        # Whitespace-collapsed: the clause wraps across lines in the prompt source.
        collapsed = " ".join(prompts.DECOMPOSITION_PROMPT.split())
        assert "A single sub-term that restates the line is not a decomposition" in collapsed

    def test_should_keep_decomposition_the_stated_goal_before_the_marking(self):
        # The goal sentence must come BEFORE the span mechanics, or the model optimises
        # the bookkeeping instead of the decomposition.
        body = prompts.DECOMPOSITION_PROMPT
        assert body.index("individually codeable") < body.index("`source_span`")
