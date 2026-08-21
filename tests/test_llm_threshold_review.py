"""Step 7: a second LLM pass that reviews Step 6's blind spot.

Step 6 (test_value_constraint_coverage_check.py) sums value_constraints across a
whole study and can miss a per-criterion loss when another criterion over-produces
and the totals happen to net out even. Step 7 asks a focused reviewer call to read
each criterion line against its own generated rule directly, instead of comparing
totals -- see LogicDecomposer._llm_review_value_constraints.
"""
import warnings
from unittest.mock import MagicMock, patch

import pytest

from src.agents.agent1.parser import LogicDecomposer
from src.models.ir import (
    ARTEMISRequest, CohortDefinition, Criteria, PrimaryCriteria, CohortOutcome,
    TemporalWindow, ValueConstraint,
)


def _ir(inclusion_rules=None, exclusion_rules=None):
    target = CohortDefinition(
        primary_criteria=PrimaryCriteria(domain="Drug", entity_text="drugX"),
        inclusion_rules=inclusion_rules or [],
        exclusion_rules=exclusion_rules or [],
    )
    comparator = CohortDefinition(
        primary_criteria=PrimaryCriteria(domain="Drug", entity_text="drugY"),
    )
    outcome = CohortOutcome(
        name="death", domain="Condition", entity_text="death",
        time_at_risk=TemporalWindow(start=0, end=365),
    )
    return ARTEMISRequest(target=target, comparator=comparator, outcome=outcome)


def _decomposer():
    with patch("src.agents.agent1.parser.get_llm", return_value=MagicMock()):
        return LogicDecomposer(model_name="vllm/google/gemma-4-E4B-it")


class TestFlattenRulesForReview:
    def test_should_render_one_line_per_rule(self):
        rules = [
            Criteria(name="eGFR", domain="Measurement", source_text="eGFR >= 30",
                      value_constraint=ValueConstraint(op="gte", value=30.0)),
            Criteria(name="T2DM", domain="Condition"),
        ]
        lines = LogicDecomposer._flatten_rules_for_review(rules)
        assert len(lines) == 2
        assert "eGFR >= 30" in lines[0]
        assert "null" in lines[1]

    def test_should_recurse_into_sub_criteria(self):
        parent = Criteria(
            name="Liver enzyme elevation", domain="Measurement", group_type="ANY",
            sub_criteria=[
                Criteria(name="ALT", domain="Measurement", source_text="Alanine aminotransferase"),
                Criteria(name="AST", domain="Measurement", source_text="Aspartate aminotransferase"),
            ],
        )
        lines = LogicDecomposer._flatten_rules_for_review([parent])
        assert len(lines) == 3  # parent + 2 sub_criteria
        assert any("Alanine aminotransferase" in l for l in lines)


class TestLlmReviewValueConstraints:
    def test_should_skip_the_call_entirely_when_there_are_no_criteria(self):
        d = _decomposer()
        with patch("src.agents.agent1.parser.get_llm") as mock_get_llm:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                d._llm_review_value_constraints("NCT_TEST", [], [], _ir())
            mock_get_llm.assert_not_called()
            assert not caught

    def test_should_not_warn_when_the_reviewer_finds_nothing(self):
        d = _decomposer()
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content='{"misses": []}')
        with patch("src.agents.agent1.parser.get_llm", return_value=mock_llm):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                d._llm_review_value_constraints(
                    "NCT_TEST", ["eGFR >= 30 ml/min"], [],
                    _ir(inclusion_rules=[Criteria(
                        name="eGFR", domain="Measurement", source_text="eGFR >= 30 ml/min",
                        value_constraint=ValueConstraint(op="gte", value=30.0),
                    )]),
                )
        assert not caught

    def test_should_return_the_misses_the_reviewer_flags(self):
        """Detection only, per the Step 8 split: the caller (parse_nct) decides
        whether to repair or warn — this method neither warns nor repairs."""
        d = _decomposer()
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content='''
        {"misses": [{"criterion_line": 1,
                      "criterion_text": "ALT or AST > 2X ULN or a Total Bilirubin >= 1.5X ULN",
                      "reason": "generated rules carry no value_constraint"}]}
        ''')
        rules = [Criteria(
            name="Liver enzyme elevation", domain="Measurement", group_type="ANY",
            sub_criteria=[
                Criteria(name="ALT", domain="Measurement", source_text="Alanine aminotransferase"),
                Criteria(name="AST", domain="Measurement", source_text="Aspartate aminotransferase"),
            ],
        )]
        with patch("src.agents.agent1.parser.get_llm", return_value=mock_llm):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                misses = d._llm_review_value_constraints(
                    "NCT_TEST",
                    ["ALT or AST > 2X ULN or a Total Bilirubin >= 1.5X ULN"],
                    [],
                    _ir(inclusion_rules=rules),
                )
        assert not caught, "detection alone must not warn — parse_nct owns that decision"
        assert len(misses) == 1
        assert misses[0]["criterion_line"] == 1

    def test_should_fail_open_when_the_reviewer_call_raises(self):
        """A broken review pass must never fail the parse that already succeeded."""
        d = _decomposer()
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("connection refused")
        with patch("src.agents.agent1.parser.get_llm", return_value=mock_llm):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                d._llm_review_value_constraints("NCT_TEST", ["eGFR >= 30"], [], _ir())
        assert not caught  # no warning, and critically: no exception propagated

    def test_should_fail_open_on_malformed_json(self):
        d = _decomposer()
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="not json at all")
        with patch("src.agents.agent1.parser.get_llm", return_value=mock_llm):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                d._llm_review_value_constraints("NCT_TEST", ["eGFR >= 30"], [], _ir())
        assert not caught


class TestRepairDroppedThreshold:
    """Step 8: mechanical repair, no LLM call — the numbers were already parsed
    deterministically before Step 7 ever ran; this only has to reattach them."""

    SHARED = "ALT or AST > 2X ULN or a Total Bilirubin >= 1.5X ULN"
    DISTINCT = "Age >= 65 years and Creatinine > 2.0 mg/dL"

    def test_should_repair_when_each_analyte_has_its_own_distinct_constraint(self):
        """The safe happy path: two analytes, two DISTINCT (non-shared)
        constraints in the same left-to-right order as the rules — candidate
        count equals constraint count AND the order-zip is semantically correct."""
        rules = [
            Criteria(name="Age", domain="Measurement", entity_text="Age", source_text="Age"),
            Criteria(name="Creatinine", domain="Measurement", entity_text="Creatinine", source_text="Creatinine"),
        ]
        repaired = LogicDecomposer._repair_dropped_threshold(self.DISTINCT, rules)
        assert repaired == 2
        assert rules[0].value_constraint.value == 65.0
        assert rules[0].source_text == self.DISTINCT
        assert rules[1].value_constraint.value == 2.0
        assert rules[1].source_text == self.DISTINCT

    def test_should_recurse_into_sub_criteria(self):
        parent = Criteria(
            name="Age and renal function", domain="Measurement", group_type="ALL",
            sub_criteria=[
                Criteria(name="Age", domain="Measurement", entity_text="Age"),
                Criteria(name="Creatinine", domain="Measurement", entity_text="Creatinine"),
            ],
        )
        repaired = LogicDecomposer._repair_dropped_threshold(self.DISTINCT, [parent])
        assert repaired == 2
        assert all(c.value_constraint is not None for c in parent.sub_criteria)

    def test_should_refuse_to_guess_when_analytes_share_one_threshold(self):
        """The ACTUAL motivating regression shape — ALT and AST share one
        constraint (2X ULN), Total Bilirubin carries its own (1.5X ULN): 3
        candidate rules but only 2 parsed constraints. This is genuinely
        ambiguous (which of the 3 gets which of the 2 numbers, and does ALT
        share with AST or with Bilirubin?), so Step 8 must refuse rather than
        zip-assign a wrong pairing. This shape falls through to Step 7's
        warning for a human to fix — auto-repair does not close this specific
        gap, only the distinct-per-analyte case above."""
        rules = [
            Criteria(name="ALT", domain="Measurement", entity_text="ALT"),
            Criteria(name="AST", domain="Measurement", entity_text="AST"),
            Criteria(name="Total Bilirubin", domain="Measurement", entity_text="Total Bilirubin"),
        ]
        repaired = LogicDecomposer._repair_dropped_threshold(self.SHARED, rules)
        assert repaired == 0
        assert all(r.value_constraint is None for r in rules), \
            "an ambiguous match must leave every candidate untouched, not partially assign"

    def test_should_not_touch_rules_that_already_have_a_constraint(self):
        rules = [Criteria(
            name="Age", domain="Measurement", entity_text="Age",
            value_constraint=ValueConstraint(op="gt", value=99.0),
        )]
        repaired = LogicDecomposer._repair_dropped_threshold(self.DISTINCT, rules)
        assert repaired == 0
        assert rules[0].value_constraint.value == 99.0, "must not overwrite an existing constraint"

    def test_should_return_zero_when_the_text_carries_no_constraint(self):
        rules = [Criteria(name="T2DM", domain="Condition", entity_text="T2DM")]
        repaired = LogicDecomposer._repair_dropped_threshold(
            "Documented diagnosis of type 2 diabetes mellitus", rules
        )
        assert repaired == 0
