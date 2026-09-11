"""An inclusive range is a real threshold, and Circe has always been able to carry it.

``ValueConstraint`` used to declare ``op: Literal["gt","lt","eq","gte","lte"]`` and a
scalar ``value``, so every range the model emitted was rejected at parse time and
``LogicDecomposer._build_criteria`` set ``value_constraint = None``. Measured over the
65 current-model IR caches in ``data/cache/agent1_ir/``: 27 constraints written
``{"op": "between", "value": [lo, hi]}``, all in NCT01243424 (CAROLINA) --
"Moderately impaired renal function (eGFR 30-59)" among them.

The second failure was worse than the first. ``_validate_measurement_rules`` then
reported each dropped rule as "missing value_constraint - likely LLM omission",
naming the model for a constraint this schema had discarded. A defect that
misattributes its own cause is the one that survives, which is why the diagnosis is
pinned here alongside the operand.

The emitted shape is pinned against TROY v1.1 gold rather than against our own
reading of it: ``data/gold/CAROLINA/[TROY v1.1] Linagliptin (CAROLINA).json`` encodes
the same eGFR criterion as ``ValueAsNumber {Value: 30, Extent: 59, Op: "bt"}``.

The fixture below reloads ``src.models.ir`` and ``src.agents.agent1.parser`` for the
same reason ``tests/test_threshold_repair_role_scoping.py`` does: another test module
(``tests/test_parser_paper_status.py``) installs a ``MagicMock`` over
``sys.modules["src.models.ir"]`` at import time and does not restore it, so a test
that simply imports ``ValueConstraint`` asserts against a mock in a full-suite run and
passes only in isolation.
"""
from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest

_MODULES = (
    "src.models.ir",
    "src.services.value_constraint",
    "src.agents.agent1.parser",
)


@pytest.fixture
def parser_module():
    saved = {name: sys.modules.get(name) for name in _MODULES}
    for name in _MODULES:
        sys.modules.pop(name, None)
    try:
        module = None
        for name in _MODULES:
            module = importlib.import_module(name)
        assert not isinstance(sys.modules["src.models.ir"].ValueConstraint, MagicMock)
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


class TestRangeSurvivesParsing:
    def test_should_keep_both_bounds_when_the_model_emits_a_between_range(self, models):
        """`value` is the LOW bound and `value_high` the high one, as gold writes them."""
        vc = models.ValueConstraint(
            op="between", value=[30.0, 59.0], unit_text="mL/min/1.73 m2"
        )

        assert (vc.op, vc.value, vc.value_high) == ("bt", 30.0, 59.0)

    def test_should_refuse_a_range_when_only_one_bound_was_supplied(self, models):
        """Four of the corpus's 27 ranges are ``{"op": "between", "value": 80.0}``.

        Half a range is not a narrower range. Supplying the missing bound here would
        put a threshold into Circe that no protocol wrote.
        """
        with pytest.raises(ValueError, match="needs an upper bound"):
            models.ValueConstraint(op="between", value=80.0, unit_text="%")

    def test_should_refuse_a_range_whose_bounds_are_inverted(self, models):
        """``BETWEEN 59 AND 30`` is valid SQL that returns no rows -- the silent shape."""
        with pytest.raises(ValueError, match="inverted"):
            models.ValueConstraint(op="bt", value=59.0, value_high=30.0)

    def test_should_refuse_an_upper_bound_on_an_operator_that_has_no_range(self, models):
        with pytest.raises(ValueError, match="only op 'bt'"):
            models.ValueConstraint(op="gte", value=6.5, value_high=8.5)

    def test_should_leave_every_other_operator_untouched(self, models):
        for op in ("gt", "gte", "lt", "lte", "eq"):
            vc = models.ValueConstraint(op=op, value=6.5)
            assert (vc.op, vc.value, vc.value_high) == (op, 6.5, None)


class TestRejectionNamesTheRightParty:
    def test_should_blame_the_schema_not_the_llm_when_a_constraint_is_rejected(
        self, decomposer
    ):
        rejected = decomposer._build_criteria({
            "name": "Treatment compliance in placebo run-in",
            "domain": "Measurement",
            "entity_text": "Compliance",
            "value_constraint": {"op": "between", "value": 80.0, "unit_text": "%"},
        })

        assert rejected.value_constraint is None
        assert "op='between'" in rejected.value_constraint_error
        assert "needs an upper bound" in rejected.value_constraint_error

    def test_should_record_no_error_when_the_model_supplied_no_constraint(
        self, decomposer
    ):
        """The two cases wear the same symptom; only this field tells them apart."""
        supplied_nothing = decomposer._build_criteria({
            "name": "HbA1c",
            "domain": "Measurement",
            "entity_text": "Hemoglobin A1c",
        })

        assert supplied_nothing.value_constraint is None
        assert supplied_nothing.value_constraint_error is None

    def test_should_record_no_error_when_the_constraint_parsed(self, decomposer):
        parsed = decomposer._build_criteria({
            "name": "Moderately impaired renal function (eGFR 30-59)",
            "domain": "Measurement",
            "entity_text": "Estimated glomerular filtration rate",
            "value_constraint": {
                "op": "between", "value": [30.0, 59.0], "unit_text": "mL/min/1.73 m2",
            },
        })

        assert parsed.value_constraint_error is None
        assert (parsed.value_constraint.value, parsed.value_constraint.value_high) == (
            30.0, 59.0,
        )


def _rule(models, name, *, op, value, logic="PRESENCE", source, analyte="Glycosylated haemoglobin",
          domain="Measurement", unit="%"):
    return models.Criteria(
        name=name, domain=domain, entity_text=analyte, source_text=source,
        logic_type=logic,
        value_constraint=models.ValueConstraint(op=op, value=value, unit_text=unit),
    )


class TestSplitBandRepair:
    """Agent 1 emits one band as a PRESENCE lower bound and an ABSENCE upper bound.

    Flat rules are conjunctive, so the pair demands "a measurement at or above 6.5 AND
    no measurement above 8.5" where the protocol states one inclusive band. Measured
    over the 65 current-model IR caches: 58 such pairs, every upper bound written with
    De Morgan (ABSENCE + gt/gte), not one with lt/lte.
    """

    LINE = ("Elevated glycosylated haemoglobin (HbA1c): 6.5 - 8.5%, inclusive, if "
            "treatment naive or mono-/dual therapy with metformin")

    def test_should_merge_a_band_when_the_merged_bounds_are_exactly_the_flat_ones(
        self, decomposer, models
    ):
        """`>= 6.5` with `NOT > 8.5` is `<= 8.5`, which is Circe's inclusive bt exactly."""
        rules = [
            _rule(models, "HbA1c 6.5 - 8.5% (Naive)", op="gte", value=6.5, source=self.LINE),
            _rule(models, "HbA1c <= 8.5% (Naive)", op="gt", value=8.5,
                  logic="ABSENCE", source=self.LINE),
        ]

        out = decomposer._repair_split_bands(rules)

        assert len(out) == 1
        assert out[0].name == "HbA1c 6.5 - 8.5% (Naive)"
        assert out[0].logic_type == "PRESENCE"
        assert (out[0].value_constraint.op, out[0].value_constraint.value,
                out[0].value_constraint.value_high) == ("bt", 6.5, 8.5)

    def test_should_decline_a_half_open_band_rather_than_move_its_boundary(
        self, decomposer, models
    ):
        """`NOT >= 10.0` is `< 10.0`; Circe's bt is inclusive, so merging widens the rule.

        46 of the corpus's 58 pairs are this shape -- every pair on NCT01131676 and
        NCT01897532. Widening them would change who the cohort matches, as a side
        effect of a repair asked for something else.
        """
        rules = [
            _rule(models, "HbA1c >= 7.0% (Background)", op="gte", value=7.0, source=self.LINE),
            _rule(models, "HbA1c <= 10% (Background)", op="gte", value=10.0,
                  logic="ABSENCE", source=self.LINE),
        ]

        out = decomposer._repair_split_bands(rules)

        assert [r.name for r in out] == [r.name for r in rules]
        assert out[1].value_constraint.op == "gte"

    def test_should_pair_each_band_separately_when_one_line_carries_two(
        self, decomposer, models
    ):
        """NCT01131676 writes both its bands on one protocol line, in lo/up/lo/up order."""
        rules = [
            _rule(models, "band A lower", op="gte", value=7.0, source=self.LINE),
            _rule(models, "band A upper", op="gt", value=10.0, logic="ABSENCE", source=self.LINE),
            _rule(models, "band B lower", op="gte", value=7.0, source=self.LINE),
            _rule(models, "band B upper", op="gt", value=9.0, logic="ABSENCE", source=self.LINE),
        ]

        out = decomposer._repair_split_bands(rules)

        assert [(r.name, r.value_constraint.value, r.value_constraint.value_high) for r in out] == [
            ("band A lower", 7.0, 10.0),
            ("band B lower", 7.0, 9.0),
        ]

    def test_should_not_pair_bounds_that_came_from_different_protocol_lines(
        self, decomposer, models
    ):
        """CAROLINA writes three HbA1c bands on three lines; the line is what separates them."""
        rules = [
            _rule(models, "line 1 lower", op="gte", value=6.5, source=self.LINE),
            _rule(models, "line 2 upper", op="gt", value=7.5, logic="ABSENCE",
                  source="HbA1c 6.5 - 7.5% while treated with sulphonylurea monotherapy"),
        ]

        assert [r.name for r in decomposer._repair_split_bands(rules)] == [r.name for r in rules]

    def test_should_not_pair_halves_separated_by_another_rule(self, decomposer, models):
        """All 58 corpus pairs are adjacent, so reaching further establishes nothing."""
        rules = [
            _rule(models, "lower", op="gte", value=6.5, source=self.LINE),
            _rule(models, "something else", op="gte", value=1.0, source=self.LINE,
                  analyte="Creatinine"),
            _rule(models, "upper", op="gt", value=8.5, logic="ABSENCE", source=self.LINE),
        ]

        assert [r.name for r in decomposer._repair_split_bands(rules)] == [r.name for r in rules]

    def test_should_not_pair_bounds_written_in_different_units(self, decomposer, models):
        rules = [
            _rule(models, "lower %", op="gte", value=6.5, source=self.LINE, unit="%"),
            _rule(models, "upper mmol/mol", op="gt", value=69.0, logic="ABSENCE",
                  source=self.LINE, unit="mmol/mol"),
        ]

        assert [r.name for r in decomposer._repair_split_bands(rules)] == [r.name for r in rules]

    def test_should_not_pair_a_rule_that_carries_no_protocol_line(self, decomposer, models):
        rules = [
            _rule(models, "lower", op="gte", value=6.5, source=""),
            _rule(models, "upper", op="gt", value=8.5, logic="ABSENCE", source=""),
        ]

        assert [r.name for r in decomposer._repair_split_bands(rules)] == [r.name for r in rules]

    def test_should_merge_the_real_carolina_cache_into_three_bands(self, decomposer):
        """The motivating case, from the cached IR rather than a fixture.

        `_repair_band_tiers` runs straight after this repair in the same pipeline, so
        the three bands are asserted where they end up -- inside the ANY group -- and
        the restated third one is gone by then. This test owns the claim that the six
        flat halves became whole bands; `TestBandTierRepair` owns what happens next.
        """
        import json
        from pathlib import Path

        arm = Path(
            "data/cache/agent1_ir/"
            "NCT01243424_vllm_google_gemma-4-E4B-it_ac7e953e86d338ee.json"
        )
        ir = decomposer._build_artemis_request(json.loads(arm.read_text()))

        bands = [
            (member.name, member.value_constraint.value, member.value_constraint.value_high)
            for rule in ir.target.inclusion_rules
            for member in ([rule] + list(rule.sub_criteria or []))
            if member.value_constraint is not None and member.value_constraint.op == "bt"
        ]

        assert ("HbA1c 6.5 - 8.5% (Naïve/Metformin/Alpha-glucosidase)", 6.5, 8.5) in bands
        assert ("HbA1c 6.5 - 7.5% (SU/Glinide/Metformin combos)", 6.5, 7.5) in bands
        assert not [
            r.name for r in ir.target.inclusion_rules
            if r.logic_type == "ABSENCE" and "HbA1c" in r.name
        ]


class TestBandTierRepair:
    """Three whole bands on one analyte, in a row, are alternatives -- not conjuncts.

    CAROLINA's protocol writes "a) ... or b)", and flat rules are conjunctive, so as
    parsed a patient needed a reading inside EVERY band and the widest tier was dead:
    the conjunction of [6.5, 8.5] and [6.5, 7.5] is [6.5, 7.5].
    """

    LINE_A = "Elevated glycosylated haemoglobin (HbA1c): 6.5 - 8.5%, inclusive, if treatment naive"
    LINE_B = "HbA1c 6.5 - 7.5% while patient is treated with sulphonylurea (SU) monotherapy"
    LINE_C = "HbA1c 6.5 - 8.5% while patient is treatment naive (if intolerant)"

    @staticmethod
    def _band(models, name, lo, hi, source, analyte="Glycosylated haemoglobin",
              domain="Measurement", unit="%"):
        return models.Criteria(
            name=name, domain=domain, entity_text=analyte, source_text=source,
            value_constraint=models.ValueConstraint(
                op="bt", value=lo, value_high=hi, unit_text=unit),
        )

    def test_should_group_alternative_bands_on_one_analyte(self, decomposer, models):
        rules = [
            self._band(models, "tier a", 6.5, 8.5, self.LINE_A),
            self._band(models, "tier b", 6.5, 7.5, self.LINE_B),
        ]

        out = decomposer._repair_band_tiers(rules)

        assert len(out) == 1
        assert out[0].group_type == "ANY"
        assert [s.name for s in out[0].sub_criteria] == ["tier a", "tier b"]
        assert out[0].value_constraint is None

    def test_should_drop_a_restated_band_and_keep_one_member_for_it(
        self, decomposer, models
    ):
        """CAROLINA states 6.5-8.5 twice, on two different protocol lines."""
        rules = [
            self._band(models, "tier a", 6.5, 8.5, self.LINE_A),
            self._band(models, "tier b", 6.5, 7.5, self.LINE_B),
            self._band(models, "tier a restated", 6.5, 8.5, self.LINE_C),
        ]

        out = decomposer._repair_band_tiers(rules)

        assert [s.name for s in out[0].sub_criteria] == ["tier a", "tier b"]

    def test_should_not_group_bands_on_different_analytes(self, decomposer, models):
        rules = [
            self._band(models, "hba1c band", 6.5, 8.5, self.LINE_A),
            self._band(models, "egfr band", 30.0, 59.0, self.LINE_A,
                       analyte="Estimated glomerular filtration rate", unit="mL/min/1.73 m2"),
        ]

        assert [r.name for r in decomposer._repair_band_tiers(rules)] == [r.name for r in rules]

    def test_should_not_group_bands_written_in_different_units(self, decomposer, models):
        rules = [
            self._band(models, "percent band", 6.5, 8.5, self.LINE_A, unit="%"),
            self._band(models, "mmol band", 48.0, 69.0, self.LINE_B, unit="mmol/mol"),
        ]

        assert [r.name for r in decomposer._repair_band_tiers(rules)] == [r.name for r in rules]

    def test_should_not_group_bands_separated_by_another_rule(self, decomposer, models):
        rules = [
            self._band(models, "tier a", 6.5, 8.5, self.LINE_A),
            models.Criteria(name="something else", domain="Condition", entity_text="T2DM"),
            self._band(models, "tier b", 6.5, 7.5, self.LINE_B),
        ]

        assert [r.name for r in decomposer._repair_band_tiers(rules)] == [r.name for r in rules]

    def test_should_leave_a_lone_band_flat(self, decomposer, models):
        rules = [self._band(models, "only band", 30.0, 59.0, self.LINE_A)]

        out = decomposer._repair_band_tiers(rules)

        assert len(out) == 1 and out[0].group_type == "ALL"
        assert out[0].value_constraint.op == "bt"

    def test_should_emit_the_survivor_flat_when_every_alternative_was_a_restatement(
        self, decomposer, models
    ):
        """An ANY group of one expresses no choice, so it is not built."""
        rules = [
            self._band(models, "tier a", 6.5, 8.5, self.LINE_A),
            self._band(models, "tier a restated", 6.5, 8.5, self.LINE_C),
        ]

        out = decomposer._repair_band_tiers(rules)

        assert [r.name for r in out] == ["tier a"]
        assert out[0].group_type == "ALL"

    def test_should_leave_the_group_label_without_a_line_when_members_came_from_several(
        self, decomposer, models
    ):
        """Naming one member's line on the label would attribute the others to it."""
        grouped = decomposer._repair_band_tiers([
            self._band(models, "tier a", 6.5, 8.5, self.LINE_A),
            self._band(models, "tier b", 6.5, 7.5, self.LINE_B),
        ])[0]
        shared = decomposer._repair_band_tiers([
            self._band(models, "tier a", 6.5, 8.5, self.LINE_A),
            self._band(models, "tier b", 6.5, 7.5, self.LINE_A),
        ])[0]

        assert grouped.source_text is None
        assert shared.source_text == self.LINE_A

    def test_should_reduce_the_real_carolina_arm_to_two_alternative_bands(self, decomposer):
        """The motivating case, end to end from the cached IR.

        Gold (TROY v1.1) states this rule as one band, ValueAsNumber
        {Value: 6.5, Extent: 8.5, Op: '!bt'}. The ANY group matches the same patients,
        because [6.5, 7.5] lies inside [6.5, 8.5]; the flat conjunction it replaces did
        not -- it required a reading in every band, which is [6.5, 7.5].
        """
        import json
        from pathlib import Path

        arm = Path(
            "data/cache/agent1_ir/"
            "NCT01243424_vllm_google_gemma-4-E4B-it_ac7e953e86d338ee.json"
        )
        ir = decomposer._build_artemis_request(json.loads(arm.read_text()))
        groups = [
            r for r in ir.target.inclusion_rules if r.name.endswith("band (OR group)")
        ]

        assert len(groups) == 1
        assert groups[0].group_type == "ANY"
        assert [
            (s.value_constraint.value, s.value_constraint.value_high)
            for s in groups[0].sub_criteria
        ] == [(6.5, 8.5), (6.5, 7.5)]
        assert not [
            r for r in ir.target.inclusion_rules
            if r.value_constraint is not None
            and r.value_constraint.op == "bt"
            and "HbA1c" in r.name
        ]
