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
import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest

# `tests/test_parser_paper_status.py` installs MagicMock stubs into sys.modules at
# IMPORT time — `src.models.ir` among them — and removes them only in its
# teardown_module. Every module that binds a name from `src.models.ir` inside that
# window keeps the mock: `src.services.value_constraint` ends up building MagicMock
# ValueConstraints, which is not something a `from ... import` at the top of this
# file can be made to survive. So this file imports nothing from `src` at module
# level; it rebuilds the three modules it needs, in dependency order, per test, and
# puts sys.modules back exactly as it found it so the sibling suite's own teardown
# still sees what it expects.
_MODULES = (
    "src.models.ir",
    "src.services.value_constraint",
    "src.agents.agent1.parser",
)

INCLUSION_LINE = "Age >= 18 years"
EXCLUSION_LINE = "Serum creatinine > 2.0 mg/dL"


@pytest.fixture
def parser_module():
    """A parser module built against the real `src.models.ir`, whatever sys.modules
    happens to hold. Also the object `patch.object(...)` must target, so a patch
    reaches the same globals `_llm_match_dropped_threshold` reads."""
    saved = {name: sys.modules.get(name) for name in _MODULES}
    for name in _MODULES:
        sys.modules.pop(name, None)
    try:
        module = None
        for name in _MODULES:
            module = importlib.import_module(name)
        assert not isinstance(sys.modules["src.models.ir"].Criteria, MagicMock)
        yield module
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


@pytest.fixture
def models(parser_module):
    return sys.modules["src.models.ir"]


@pytest.fixture
def decomposer(parser_module):
    with patch.object(parser_module, "get_llm", return_value=MagicMock()):
        return parser_module.LogicDecomposer(model_name="vllm/google/gemma-4-E4B-it")


def _ir(m, inclusion_rules=None, exclusion_rules=None):
    return m.ARTEMISRequest(
        target=m.CohortDefinition(
            primary_criteria=m.PrimaryCriteria(domain="Drug", entity_text="drugX"),
            inclusion_rules=inclusion_rules or [],
            exclusion_rules=exclusion_rules or [],
        ),
        comparator=m.CohortDefinition(
            primary_criteria=m.PrimaryCriteria(domain="Drug", entity_text="drugY"),
        ),
        outcome=m.CohortOutcome(
            name="death", domain="Condition", entity_text="death",
            time_at_risk=m.TemporalWindow(start=0, end=365),
        ),
    )


def _rule(m, name, source_text):
    return m.Criteria(
        name=name, domain="Measurement", entity_text=name, source_text=source_text,
    )


@pytest.fixture
def creatinine_ir(models):
    """One analyte named by a rule in BOTH blocks — the collision the bare index
    cannot resolve. Inclusion says "measured at screening" (no threshold, and
    correctly so); exclusion is the line that lost its > 2.0 mg/dL."""
    inclusion = [_rule(models, "Serum creatinine", "Serum creatinine measured at screening")]
    exclusion = [_rule(models, "Serum creatinine", "Serum creatinine")]
    return (
        _ir(models, inclusion_rules=inclusion, exclusion_rules=exclusion),
        inclusion[0],
        exclusion[0],
    )


class TestRepairThresholdMissesRoleScoping:
    def test_should_repair_the_exclusion_rule_when_the_miss_names_an_exclusion_line(
        self, decomposer, creatinine_ir
    ):
        ir, _inclusion_rule, exclusion_rule = creatinine_ir
        # line 2 == the 1st exclusion criterion, because the reviewer numbers
        # inclusion (1 line) then exclusion (1 line) as one 1..N sequence.
        still_broken = decomposer._repair_threshold_misses(
            "NCT_TEST", [INCLUSION_LINE], [EXCLUSION_LINE], ir,
            [{"criterion_line": 2, "criterion_text": EXCLUSION_LINE, "reason": "dropped"}],
        )
        assert still_broken == []
        assert exclusion_rule.value_constraint is not None, \
            "the exclusion rule is the one that lost the threshold"
        assert exclusion_rule.value_constraint.value == 2.0

    def test_should_leave_the_inclusion_rule_untouched_when_the_miss_names_an_exclusion_line(
        self, decomposer, creatinine_ir
    ):
        ir, inclusion_rule, _ = creatinine_ir
        decomposer._repair_threshold_misses(
            "NCT_TEST", [INCLUSION_LINE], [EXCLUSION_LINE], ir,
            [{"criterion_line": 2, "criterion_text": EXCLUSION_LINE, "reason": "dropped"}],
        )
        assert inclusion_rule.value_constraint is None, \
            "an exclusion threshold must not become an inclusion requirement"
        assert inclusion_rule.source_text == "Serum creatinine measured at screening", \
            "source_text is ADR-032 provenance; the other role's line must not overwrite it"

    def test_should_repair_the_inclusion_rule_when_the_miss_names_an_inclusion_line(
        self, models, decomposer
    ):
        inclusion = [_rule(models, "Age", "Age")]
        exclusion = [_rule(models, "Age", "Age at randomisation")]
        ir = _ir(models, inclusion_rules=inclusion, exclusion_rules=exclusion)
        still_broken = decomposer._repair_threshold_misses(
            "NCT_TEST", [INCLUSION_LINE], [EXCLUSION_LINE], ir,
            [{"criterion_line": 1, "criterion_text": INCLUSION_LINE, "reason": "dropped"}],
        )
        assert still_broken == []
        assert inclusion[0].value_constraint.value == 18.0
        assert exclusion[0].value_constraint is None
        assert exclusion[0].source_text == "Age at randomisation"

    def test_should_not_reach_the_other_role_when_the_owning_role_has_no_candidate(
        self, models, parser_module, decomposer
    ):
        """8b is role-scoped too. With the exclusion block carrying no candidate
        rule, the miss is still_broken — it must not fall sideways into the
        inclusion block, and must not spend an LLM call trying to."""
        inclusion = [_rule(models, "Serum creatinine", "Serum creatinine")]
        ir = _ir(models, inclusion_rules=inclusion, exclusion_rules=[])
        with patch.object(parser_module, "get_llm") as mock_get_llm:
            still_broken = decomposer._repair_threshold_misses(
                "NCT_TEST", [INCLUSION_LINE], [EXCLUSION_LINE], ir,
                [{"criterion_line": 2, "criterion_text": EXCLUSION_LINE, "reason": "dropped"}],
            )
        assert len(still_broken) == 1
        assert inclusion[0].value_constraint is None
        mock_get_llm.assert_not_called()

    def test_should_keep_a_miss_whose_line_index_is_out_of_range(self, models, decomposer):
        ir = _ir(models, inclusion_rules=[_rule(models, "Age", "Age")])
        still_broken = decomposer._repair_threshold_misses(
            "NCT_TEST", [INCLUSION_LINE], [EXCLUSION_LINE], ir,
            [{"criterion_line": 99, "criterion_text": "?", "reason": "?"}],
        )
        assert len(still_broken) == 1

    def test_should_keep_a_miss_whose_line_index_is_not_an_int(self, models, decomposer):
        ir = _ir(models, inclusion_rules=[_rule(models, "Age", "Age")])
        still_broken = decomposer._repair_threshold_misses(
            "NCT_TEST", [INCLUSION_LINE], [EXCLUSION_LINE], ir,
            [{"criterion_line": "two", "criterion_text": "?", "reason": "?"}],
        )
        assert len(still_broken) == 1


class TestRoleIndexedCriteria:
    def test_should_number_inclusion_before_exclusion_as_one_sequence(self, parser_module):
        indexed = parser_module.LogicDecomposer._role_indexed_criteria(["a", "b"], ["c"])
        assert indexed == [
            ("inclusion", "a"), ("inclusion", "b"), ("exclusion", "c"),
        ], "must match the numbering THRESHOLD_REVIEW_PROMPT's criteria_block uses"
