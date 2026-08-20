"""Step 6 coverage check: the LLM's output must not carry fewer value_constraints
than the deterministic parser found in the input criteria text.

Regression: ARISTOTLE and CAROLINA's "ALT or AST > 2X ULN or a Total Bilirubin
>= 1.5X ULN" reached the LLM with two thresholds correctly annotated (ADR-031-B),
and came back with three sub_criteria whose source_text was the bare analyte name
instead of the full sentence -- the downstream substring match then found nothing
to attach the threshold to, and value_constraint silently came back None on all
three. Nothing errored; the count just dropped from 2 (parsed) to 0 (emitted).
This file tests the counting logic that makes that drop visible instead of silent.
"""
from src.agents.agent1.parser import LogicDecomposer
from src.models.ir import Criteria, ValueConstraint


class TestCountValueConstraintsInput:
    """_count_value_constraints: the input-side ground truth."""

    def test_should_return_zero_for_criteria_with_no_threshold(self):
        assert LogicDecomposer._count_value_constraints(
            ["Documented diagnosis of type 2 diabetes mellitus"]
        ) == 0

    def test_should_count_one_threshold_on_a_simple_criterion(self):
        assert LogicDecomposer._count_value_constraints(["eGFR >= 30 ml/min"]) == 1

    def test_should_count_two_thresholds_on_the_carolina_regression_line(self):
        """The exact motivating sentence: two distinct annotated thresholds
        (ALT/AST share 2X ULN, Total Bilirubin has its own 1.5X ULN)."""
        line = "ALT or AST > 2X ULN or a Total Bilirubin >= 1.5X ULN"
        assert LogicDecomposer._count_value_constraints([line]) == 2

    def test_should_sum_across_multiple_criteria(self):
        lines = ["eGFR >= 30 ml/min", "ALT or AST > 2X ULN or a Total Bilirubin >= 1.5X ULN", "No prior stroke"]
        assert LogicDecomposer._count_value_constraints(lines) == 3


class TestCountValueConstraintsOutput:
    """_count_output_value_constraints: the output-side actual count, recursing
    into sub_criteria the way Pattern E nests them."""

    def _vc(self, value=2.0):
        return ValueConstraint(op="gt", value=value, reference_bound="uln")

    def test_should_return_zero_for_rules_with_no_constraint(self):
        rules = [Criteria(name="T2DM", domain="Condition")]
        assert LogicDecomposer._count_output_value_constraints(rules) == 0

    def test_should_count_a_top_level_constraint(self):
        rules = [Criteria(name="eGFR", domain="Measurement", value_constraint=self._vc())]
        assert LogicDecomposer._count_output_value_constraints(rules) == 1

    def test_should_recurse_into_sub_criteria(self):
        """The regression shape: one parent rule, three sub_criteria, each meant
        to carry the shared/own threshold."""
        parent = Criteria(
            name="Liver enzyme elevation",
            domain="Measurement",
            group_type="ANY",
            sub_criteria=[
                Criteria(name="ALT", domain="Measurement", value_constraint=self._vc(2.0)),
                Criteria(name="AST", domain="Measurement", value_constraint=self._vc(2.0)),
                Criteria(name="Total Bilirubin", domain="Measurement", value_constraint=self._vc(1.5)),
            ],
        )
        assert LogicDecomposer._count_output_value_constraints([parent]) == 3

    def test_should_detect_the_regression_the_check_exists_for(self):
        """The actual failure mode: three sub_criteria correctly split out, but
        source_text collapsed to a bare analyte name so value_constraint is None
        on all three -- output count (0) is less than what the parser found in the
        input (2), which is exactly the gap Step 6 must catch."""
        parent = Criteria(
            name="Liver enzyme elevation",
            domain="Measurement",
            group_type="ANY",
            sub_criteria=[
                Criteria(name="ALT", domain="Measurement", source_text="Alanine aminotransferase"),
                Criteria(name="AST", domain="Measurement", source_text="Aspartate aminotransferase"),
                Criteria(name="Total Bilirubin", domain="Measurement", source_text="Total bilirubin"),
            ],
        )
        input_count = LogicDecomposer._count_value_constraints(
            ["ALT or AST > 2X ULN or a Total Bilirubin >= 1.5X ULN"]
        )
        output_count = LogicDecomposer._count_output_value_constraints([parent])
        assert input_count == 2
        assert output_count == 0
        assert output_count < input_count, "the coverage gap that motivated Step 6"
