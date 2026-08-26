"""SPEC-INFRA-007 item 2: sub-criteria value_constraint is grounded in the
sub-item's own source text, never unconditionally inherited from the parent.

`decomposer.py:107` (pre-fix) unconditionally copied `criterion.value_constraint`
onto every sub-criterion. This suite RED/GREENs against that specific line:
before the fix, this suite's negative case (AC-004a) would show the sub-item
carrying the parent's value regardless of the mocked LLM response, because the
pre-fix code never looked at the LLM's per-sub-item threshold at all. After
the fix, the decomposer reads each sub-item's `value_constraint_text` field
(LLM-determined, grounded in `criterion.source_text` per the
DECOMPOSITION_PROMPT grounding requirement, plan-audit D2) and parses it via
`src.services.value_constraint.parse_value_constraint` -- reusing tested
machinery rather than trusting the LLM to emit structured numbers directly.

The mocked LLM responses below are not invented: GROUNDED_RESPONSE and
UNGROUNDED_RESPONSE mirror the exact shape captured live against the
production model (google/gemma-4-E4B-it via vLLM) for CAROLINA's real
liver-disease protocol sentence -- see the SPEC-INFRA-007 completion report
for the verbatim live-capture command and output. Mocking here keeps the
suite fast and deterministic; the live reproduction is the evidence that the
grounded mechanism actually works end-to-end against a real model.
"""
from unittest.mock import MagicMock, patch

from src.agents.planner.decomposer import CriteriaPlanner
from src.models.ir import Criteria, ValueConstraint


def _mock_llm(content: str) -> MagicMock:
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=content)
    return mock_llm


def _planner_with_mocked_llm(content: str) -> CriteriaPlanner:
    with patch("src.agents.planner.decomposer.get_llm", return_value=_mock_llm(content)):
        return CriteriaPlanner()


# Real shape captured live 2026-08-27 against CAROLINA's actual protocol
# sentence: "Active liver disease or impaired hepatic function, defined by
# serum levels of either ALT (SGPT), AST (SGOT), or alkaline phosphatase
# above 3 x upper limit of normal (ULN) as determined at visit 1a"
# (jama_2019_carolina_supplement.pdf, exclusion criteria).
GROUNDED_RESPONSE = """```json
{
  "decompose": true,
  "reasoning": "three distinct lab thresholds sharing one comparator",
  "sub_criteria": [
    {"name": "Elevated ALT", "entity_text": "ALT (SGPT) above 3 x upper limit of normal (ULN)", "domain": "Measurement", "value_constraint_text": "above 3 x upper limit of normal (ULN)"},
    {"name": "Elevated AST", "entity_text": "AST (SGOT) above 3 x upper limit of normal (ULN)", "domain": "Measurement", "value_constraint_text": "above 3 x upper limit of normal (ULN)"},
    {"name": "Elevated Alkaline Phosphatase", "entity_text": "alkaline phosphatase above 3 x upper limit of normal (ULN)", "domain": "Measurement", "value_constraint_text": "above 3 x upper limit of normal (ULN)"}
  ]
}
```"""

# Real shape captured live 2026-08-27 for the umbrella "Acute Liver Disease"
# entity_text (no numeric threshold anywhere in that shorter framing) --
# sub-items are named diseases, none of which carries its own number.
UNGROUNDED_RESPONSE = """```json
{
  "decompose": true,
  "reasoning": "distinct liver conditions, no shared numeric threshold",
  "sub_criteria": [
    {"name": "Acute Hepatitis", "entity_text": "Acute Hepatitis", "domain": "Condition", "value_constraint_text": null},
    {"name": "Acute Liver Failure", "entity_text": "Acute Liver Failure", "domain": "Condition", "value_constraint_text": null}
  ]
}
```"""

# Malformed on purpose: the sub-criterion is missing value_constraint_text
# entirely (as if an older/degraded LLM response omitted the new field).
MALFORMED_RESPONSE_MISSING_FIELD = """```json
{
  "decompose": true,
  "reasoning": "malformed sub-criterion, missing value_constraint_text entirely",
  "sub_criteria": [
    {"name": "Elevated ALT", "entity_text": "ALT elevation", "domain": "Measurement"}
  ]
}
```"""

# Field present but the text is not a parseable threshold phrase at all.
UNPARSEABLE_RESPONSE = """```json
{
  "decompose": true,
  "reasoning": "field present but not a real threshold phrase",
  "sub_criteria": [
    {"name": "Elevated ALT", "entity_text": "ALT elevation", "domain": "Measurement", "value_constraint_text": "not a real threshold phrase"}
  ]
}
```"""


class TestSubCriteriaValueConstraintNotInherited:
    """AC-004a: a sub-criterion does not unconditionally inherit the parent's
    value_constraint (negative case)."""

    def test_should_not_inherit_parent_value_constraint_when_own_text_carries_none(self):
        planner = _planner_with_mocked_llm(UNGROUNDED_RESPONSE)
        parent = Criteria(
            name="Acute liver disease or impaired hepatic function",
            domain="Condition",
            entity_text="Acute Liver Disease",
            logic_type="ABSENCE",
            # Deliberately distinct marker value: if the pre-fix inheritance
            # line were still active, every sub-item below would carry this
            # exact value instead of None.
            value_constraint=ValueConstraint(op="gt", value=999.0),
            source_text="Acute liver disease or impaired hepatic function of any cause",
        )

        result = planner._decompose_criterion(parent)

        assert len(result.sub_criteria) == 2
        for sc in result.sub_criteria:
            assert sc.value_constraint is None, (
                f"{sc.name!r} inherited the parent's value_constraint unchanged"
            )


class TestSubCriteriaValueConstraintGrounded:
    """AC-004b: a sub-criterion whose own text implies a distinct constraint
    is assigned that constraint (positive case -- closes the degenerate
    'always assign None' loophole AC-004a alone cannot catch)."""

    def test_should_assign_own_grounded_constraint_when_source_text_carries_one(self):
        planner = _planner_with_mocked_llm(GROUNDED_RESPONSE)
        parent = Criteria(
            name="Elevated Liver Enzymes (ALT/AST)",
            domain="Condition",
            entity_text="Elevated Liver Enzymes (ALT/AST)",
            logic_type="ABSENCE",
            source_text=(
                "Active liver disease or impaired hepatic function, defined by serum "
                "levels of either ALT (SGPT), AST (SGOT), or alkaline phosphatase above "
                "3 x upper limit of normal (ULN) as determined at visit 1a"
            ),
        )

        result = planner._decompose_criterion(parent)

        assert len(result.sub_criteria) == 3
        for sc in result.sub_criteria:
            vc = sc.value_constraint
            assert vc is not None, f"{sc.name!r} should carry its own grounded value_constraint"
            assert vc.op == "gt"
            assert vc.value == 3.0
            assert vc.reference_bound == "uln"


class TestAtomicCriteriaUnaffected:
    """AC-005: atomic (non-decomposed) criteria are unaffected."""

    def test_should_leave_value_constraint_untouched_when_criterion_stays_atomic(self):
        planner = _planner_with_mocked_llm('{"decompose": false, "sub_criteria": []}')
        vc = ValueConstraint(op="gte", value=7.0)
        atomic = Criteria(
            name="Type 2 Diabetes Mellitus", domain="Condition",
            entity_text="Type 2 Diabetes Mellitus", logic_type="PRESENCE",
            value_constraint=vc,
        )

        result = planner._decompose_criterion(atomic)

        assert result.sub_criteria == []
        assert result.value_constraint is vc


class TestFailOpenOnMechanismFailure:
    """AC-006: the mechanism's failure to determine a sub-criterion's
    value_constraint fails open to None -- no exception, no fallback to the
    (possibly wrong) parent value."""

    def test_should_fail_open_to_none_when_value_constraint_text_field_is_missing(self):
        planner = _planner_with_mocked_llm(MALFORMED_RESPONSE_MISSING_FIELD)
        parent = Criteria(
            name="Elevated Liver Enzymes (ALT/AST)", domain="Condition",
            entity_text="Elevated Liver Enzymes (ALT/AST)", logic_type="ABSENCE",
            value_constraint=ValueConstraint(op="gt", value=999.0),
            source_text="ALT above 3 x ULN",
        )

        result = planner._decompose_criterion(parent)  # must not raise

        assert len(result.sub_criteria) == 1
        assert result.sub_criteria[0].value_constraint is None

    def test_should_fail_open_to_none_when_value_constraint_text_does_not_parse(self):
        planner = _planner_with_mocked_llm(UNPARSEABLE_RESPONSE)
        parent = Criteria(
            name="Elevated Liver Enzymes (ALT/AST)", domain="Condition",
            entity_text="Elevated Liver Enzymes (ALT/AST)", logic_type="ABSENCE",
            source_text="ALT above some undefined level",
        )

        result = planner._decompose_criterion(parent)

        assert len(result.sub_criteria) == 1
        assert result.sub_criteria[0].value_constraint is None
