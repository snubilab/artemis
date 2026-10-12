"""Step 7: a second LLM pass that reads each criterion line against its own rule.

Detection only -- see LogicDecomposer._llm_review_value_constraints. Steps 6 (a
study-wide count from the English threshold parser) and 8a/8b (re-attaching that
parser's numbers) were deleted with the parser (RFC-016 step 3), and so were their
tests; a threshold the line states that the criterion lost is now reported by the
annotation's ``threshold_span`` and delivery-gate check (j).
"""
import warnings
from unittest.mock import MagicMock, patch

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
