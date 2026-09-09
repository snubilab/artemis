"""Step 7/8 threshold repair must resolve a reviewer line back to its ROLE.

The Step 7 reviewer is handed `inclusion_criteria + exclusion_criteria` numbered
1..N across BOTH blocks (`LogicDecomposer._llm_review_value_constraints`, and
THRESHOLD_REVIEW_PROMPT's "{criteria_block}"), and it answers with a bare
1-based `criterion_line` carrying no role marker. The repair step used to take
that index, recover only the criterion TEXT, and then try
`_repair_dropped_threshold(text, inclusion_rules) or
 _repair_dropped_threshold(text, exclusion_rules)`.

Both halves of that are wrong for an exclusion line whose analyte also names an
inclusion rule:

  * the inclusion rule gains a threshold the protocol never stated for it — the
    cohort starts REQUIRING serum creatinine > 2.0 mg/dL;
  * `repaired` is then truthy, so the exclusion rule keeps
    `value_constraint=None` and emits an ABSENCE rule with no value filter,
    excluding anyone who has ever had a serum creatinine drawn;
  * and `_repair_dropped_threshold` stamps `source_text = original_text`, so the
    inclusion rule's provenance now quotes a line from the exclusion block —
    the field ADR-032's classifier reads (`threshold_classifier.py:427`).

The index resolves to a role, not just to a string. These tests pin that.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.agents.agent1.parser import LogicDecomposer
from src.models.ir import (
    ARTEMISRequest,
    CohortDefinition,
    CohortOutcome,
    Criteria,
    PrimaryCriteria,
    TemporalWindow,
)

INCLUSION_LINE = "Age >= 18 years"
EXCLUSION_LINE = "Serum creatinine > 2.0 mg/dL"


def _ir(inclusion_rules=None, exclusion_rules=None):
    return ARTEMISRequest(
        target=CohortDefinition(
            primary_criteria=PrimaryCriteria(domain="Drug", entity_text="drugX"),
            inclusion_rules=inclusion_rules or [],
            exclusion_rules=exclusion_rules or [],
        ),
        comparator=CohortDefinition(
            primary_criteria=PrimaryCriteria(domain="Drug", entity_text="drugY"),
        ),
        outcome=CohortOutcome(
            name="death", domain="Condition", entity_text="death",
            time_at_risk=TemporalWindow(start=0, end=365),
        ),
    )


def _rule(name, source_text):
    return Criteria(
        name=name, domain="Measurement", entity_text=name, source_text=source_text,
    )


def _decomposer():
    with patch("src.agents.agent1.parser.get_llm", return_value=MagicMock()):
        return LogicDecomposer(model_name="vllm/google/gemma-4-E4B-it")


@pytest.fixture
def creatinine_ir():
    """One analyte named by a rule in BOTH blocks — the collision the bare index
    cannot resolve. Inclusion says "measured at screening" (no threshold, and
    correctly so); exclusion is the line that lost its > 2.0 mg/dL."""
    inclusion = [_rule("Serum creatinine", "Serum creatinine measured at screening")]
    exclusion = [_rule("Serum creatinine", "Serum creatinine")]
    return _ir(inclusion_rules=inclusion, exclusion_rules=exclusion), inclusion[0], exclusion[0]


class TestRepairThresholdMissesRoleScoping:
    def test_should_repair_the_exclusion_rule_when_the_miss_names_an_exclusion_line(
        self, creatinine_ir
    ):
        ir, inclusion_rule, exclusion_rule = creatinine_ir
        d = _decomposer()
        # line 2 == the 1st exclusion criterion, because the reviewer numbers
        # inclusion (1 line) then exclusion (1 line) as one 1..N sequence.
        still_broken = d._repair_threshold_misses(
            "NCT_TEST", [INCLUSION_LINE], [EXCLUSION_LINE], ir,
            [{"criterion_line": 2, "criterion_text": EXCLUSION_LINE, "reason": "dropped"}],
        )
        assert still_broken == []
        assert exclusion_rule.value_constraint is not None, \
            "the exclusion rule is the one that lost the threshold"
        assert exclusion_rule.value_constraint.value == 2.0

    def test_should_leave_the_inclusion_rule_untouched_when_the_miss_names_an_exclusion_line(
        self, creatinine_ir
    ):
        ir, inclusion_rule, _ = creatinine_ir
        d = _decomposer()
        d._repair_threshold_misses(
            "NCT_TEST", [INCLUSION_LINE], [EXCLUSION_LINE], ir,
            [{"criterion_line": 2, "criterion_text": EXCLUSION_LINE, "reason": "dropped"}],
        )
        assert inclusion_rule.value_constraint is None, \
            "an exclusion threshold must not become an inclusion requirement"
        assert inclusion_rule.source_text == "Serum creatinine measured at screening", \
            "source_text is ADR-032 provenance; the other role's line must not overwrite it"

    def test_should_repair_the_inclusion_rule_when_the_miss_names_an_inclusion_line(self):
        inclusion = [_rule("Age", "Age")]
        exclusion = [_rule("Age", "Age at randomisation")]
        ir = _ir(inclusion_rules=inclusion, exclusion_rules=exclusion)
        d = _decomposer()
        still_broken = d._repair_threshold_misses(
            "NCT_TEST", [INCLUSION_LINE], [EXCLUSION_LINE], ir,
            [{"criterion_line": 1, "criterion_text": INCLUSION_LINE, "reason": "dropped"}],
        )
        assert still_broken == []
        assert inclusion[0].value_constraint.value == 18.0
        assert exclusion[0].value_constraint is None
        assert exclusion[0].source_text == "Age at randomisation"

    def test_should_not_reach_the_other_role_when_the_owning_role_has_no_candidate(self):
        """8b is role-scoped too. With the exclusion block carrying no candidate
        rule, the miss is still_broken — it must not fall sideways into the
        inclusion block, and must not spend an LLM call trying to."""
        inclusion = [_rule("Serum creatinine", "Serum creatinine")]
        ir = _ir(inclusion_rules=inclusion, exclusion_rules=[])
        d = _decomposer()
        with patch("src.agents.agent1.parser.get_llm") as mock_get_llm:
            still_broken = d._repair_threshold_misses(
                "NCT_TEST", [INCLUSION_LINE], [EXCLUSION_LINE], ir,
                [{"criterion_line": 2, "criterion_text": EXCLUSION_LINE, "reason": "dropped"}],
            )
        assert len(still_broken) == 1
        assert inclusion[0].value_constraint is None
        mock_get_llm.assert_not_called()

    def test_should_keep_a_miss_whose_line_index_is_out_of_range(self):
        ir = _ir(inclusion_rules=[_rule("Age", "Age")])
        d = _decomposer()
        still_broken = d._repair_threshold_misses(
            "NCT_TEST", [INCLUSION_LINE], [EXCLUSION_LINE], ir,
            [{"criterion_line": 99, "criterion_text": "?", "reason": "?"}],
        )
        assert len(still_broken) == 1

    def test_should_keep_a_miss_whose_line_index_is_not_an_int(self):
        ir = _ir(inclusion_rules=[_rule("Age", "Age")])
        d = _decomposer()
        still_broken = d._repair_threshold_misses(
            "NCT_TEST", [INCLUSION_LINE], [EXCLUSION_LINE], ir,
            [{"criterion_line": "two", "criterion_text": "?", "reason": "?"}],
        )
        assert len(still_broken) == 1


class TestRoleIndexedCriteria:
    def test_should_number_inclusion_before_exclusion_as_one_sequence(self):
        indexed = LogicDecomposer._role_indexed_criteria(["a", "b"], ["c"])
        assert indexed == [
            ("inclusion", "a"), ("inclusion", "b"), ("exclusion", "c"),
        ], "must match the numbering THRESHOLD_REVIEW_PROMPT's criteria_block uses"
