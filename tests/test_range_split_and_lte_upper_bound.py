"""One protocol sentence, two rules no patient can satisfy.

CARMELINA states one line::

    HbA1c of ≥ 6.5% and ≤ 10.0% at Visit 1 (screening)

The 2026-09-18 cold re-extraction turned it into the two delivered inclusion rules
below, and CIRCE ANDs inclusion rules, so together they select nobody on any CDM::

    #12 'HbA1c at least 6.5% + HbA1c at most 10.0%'
        ANY( Measurement gte 6.5 , Measurement lte 10.0 )   -> has a %-unit HbA1c
    #13 'HbA1c below lower limit + HbA1c above upper limit'
        ALL( Occurrence{Type:0,Count:0} gte 6.5
           , Occurrence{Type:0,Count:0} lte 10.0 )          -> has NO %-unit HbA1c

Two stages produce it, and this file pins one repair in each.

**Stage A -- the allowed-side operator on an ABSENCE criterion.** The IR cache
``NCT01897532_vllm_google_gemma-4-E4B-it_97e28790a4d24072.json`` carries
``target/inclusion_rules[5]`` as ``ABSENCE`` + ``lte 10.0``: "no HbA1c <= 10", the
inverse of the line. ``_repair_inclusive_upper_bounds`` exists for exactly this
De Morgan error but gated on the ``gte`` spelling alone, so the ``lte`` spelling
passed through, and ``_repair_split_bands`` -- which needs the upper half's op in
``{gt, gte}`` -- then could not merge the pair into one inclusive band.

**Stage B -- the planner splits each survivor and inherits its polarity.** Both
parents reach ``CriteriaPlanner._decompose_criterion``, whose model answers that
"HbA1c" is an umbrella term and returns two members per rule -- each member the
SAME analyte, each carrying one side of the band copied verbatim off the line, in
the allowed polarity. ``logic_type`` is inherited and ``group_type`` becomes ``ALL``
for the ABSENCE parent, which is how #13's member names ("below lower limit") end
up describing the opposite of their own operators. Those names appear in none of
the 136 IR caches; they are the planner's.

Measured over the 101 decomposition groups of
``output/site_gap/2026-09-18_verify4/store/studies.json``, six groups have every
member naming the parent's own analyte with a one-sided bound. Five are this
defect; the sixth is one threshold restated in two units (CAROLINA study 10
``Uncontrolled hyperglycaemia``: ``>240 mg/dl`` and ``>13.3 mmol/L``), where the
second member adds real coverage rather than tearing a range. That sixth case is
pinned below as a case the decline must NOT fire on.

No live LLM anywhere here: the parser fixture mocks ``get_llm`` and the planner's
single call is a mock returning the response the run really produced.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_MODULES = (
    "src.models.ir",
    "src.services.value_constraint",
    "src.agents.agent1.parser",
)

CACHE = Path("data/cache/agent1_ir")

#: The CARMELINA arm the 2026-09-18 cold re-extraction produced the delivered
#: rule pair from. `target/inclusion_rules[4]` is `PRESENCE gte 6.5` and `[5]` is
#: `ABSENCE lte 10.0`, both off the one screening line.
CARMELINA_ARM = "NCT01897532_vllm_google_gemma-4-E4B-it_97e28790a4d24072.json"

#: CAROLINA's liver-panel exclusion, the genuine umbrella. Its members really are
#: three different analytes, and its parent carries a one-sided bound just like the
#: HbA1c parents do -- so the analyte identity is the only thing separating the two
#: cases, which is what makes this the right control.
CAROLINA_ARM = "NCT01243424_vllm_google_gemma-4-E4B-it_cfd9dbd5a98266e1.json"

CARMELINA_LINE = "HbA1c of ≥ 6.5% and ≤ 10.0% at Visit 1 (screening)"


@pytest.fixture
def parser_module():
    """Reload the parser stack.

    Another module installs a ``MagicMock`` over ``sys.modules["src.models.ir"]`` at
    import time and never restores it, so an unguarded import asserts against a mock
    in a full-suite run. Same fixture as
    ``tests/test_repair_accounting_and_inclusive_bounds.py``.
    """
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
def agent1(parser_module):
    with patch.object(parser_module, "get_llm", return_value=MagicMock()):
        return parser_module.LogicDecomposer(model_name="vllm/google/gemma-4-E4B-it")


def _cache(name: str) -> dict:
    path = CACHE / name
    if not path.exists():
        pytest.skip(f"IR cache {path.name} is not present")
    return json.loads(path.read_text())


def _rules(agent1, arm: str, side: str = "inclusion_rules") -> list:
    """This arm's rules, as Agent 1 emitted them, before any repair."""
    return [agent1._build_criteria(c) for c in _cache(arm)["target"][side]]


# --------------------------------------------------------------- Stage A: the parser


class TestTheLteSpellingOfTheNegatedUpperBound:
    """`<= X` is `NOT (> X)`. An ABSENCE rule carrying `lte X` says `NOT (<= X)`,
    which is `> X` -- the allowed side inverted into the forbidden one."""

    def test_should_correct_the_absence_lte_when_the_line_states_that_bound_inclusive(
        self, agent1
    ):
        rules = _rules(agent1, CARMELINA_ARM)
        upper = rules[5]
        assert (upper.name, upper.logic_type) == ("HbA1c upper limit check", "ABSENCE")
        assert (upper.value_constraint.op, upper.value_constraint.value) == ("lte", 10.0)
        assert upper.source_text == CARMELINA_LINE

        out = agent1._repair_inclusive_upper_bounds(rules)[5]

        assert (out.value_constraint.op, out.value_constraint.value) == ("gt", 10.0)

    def test_should_merge_the_pair_into_one_inclusive_band_once_the_lte_is_corrected(
        self, agent1
    ):
        """The point of the correction: `_repair_split_bands` can then see a pair."""
        cohort = agent1._build_cohort_definition(_cache(CARMELINA_ARM)["target"])

        hba1c = [
            r
            for r in cohort.inclusion_rules
            if (r.entity_text or "").casefold() == "hba1c"
        ]
        assert len(hba1c) == 1, (
            "the band is still split across "
            f"{[(r.name, r.logic_type, r.value_constraint.op) for r in hba1c]}"
        )
        vc = hba1c[0].value_constraint
        assert (hba1c[0].logic_type, vc.op, vc.value, vc.value_high) == (
            "PRESENCE",
            "bt",
            6.5,
            10.0,
        )

    def test_should_leave_an_absence_lte_alone_when_the_line_states_no_such_bound(
        self, agent1, models
    ):
        """CAROLINA's eGFR line reads `30-59`, so 60 is a value the line never states
        as a bound -- it is the same bad De Morgan applied to `<= 59`. Correcting the
        operator alone would give `<= 60`, which is not the band either, so the
        detector reads the LINE and declines."""
        line = (
            "Moderately impaired renal function (as defined by MDRD formula) with "
            "estimated glomerular filtration rate [eGFR] 30-59 mL/min/1.73 m2"
        )
        rule = models.Criteria(
            name="eGFR upper bound (<= 59)",
            domain="Measurement",
            entity_text="eGFR",
            source_text=line,
            logic_type="ABSENCE",
            value_constraint=models.ValueConstraint(op="lte", value=60.0),
        )

        out = agent1._repair_inclusive_upper_bounds([rule])[0]

        assert out is rule
        assert out.value_constraint.op == "lte"


class TestTheCorrectionIsAccountedFor:
    def test_should_account_every_repair_when_the_lte_correction_fires(self, agent1):
        """`assert_repairs_accounted` is what makes the ledger worth reading: a
        criterion rewritten or removed without a record fails at the repair, not as
        an absence in a delivery three stages later."""
        from src.agents.agent1.repair_accounting import (
            RepairLedger,
            assert_repairs_accounted,
        )

        before = _rules(agent1, CARMELINA_ARM)
        ledger = RepairLedger()

        after = agent1._repair_inclusive_upper_bounds(before, ledger)

        assert_repairs_accounted(
            before, after, ledger, role="inclusion/inclusive-upper-bound"
        )
        records = [
            r
            for r in ledger.records()
            if r["action"] == "inclusive-upper-bound-corrected"
        ]
        assert [r["criterion"]["name"] for r in records] == ["HbA1c upper limit check"]
        assert records[0]["before"]["op"] == "lte"
        assert records[0]["after"]["op"] == "gt"

    def test_should_account_the_whole_parse_of_the_arm_that_produced_the_defect(
        self, agent1
    ):
        """End to end: every `_gated` step of the real arm holds to its own
        accounting, the correction included."""
        cohort = agent1._build_cohort_definition(_cache(CARMELINA_ARM)["target"])

        actions = [r["action"] for r in cohort.repair_accounting]
        assert "inclusive-upper-bound-corrected" in actions
        assert actions.count("merged-into-band") == 2


# -------------------------------------------------------------- Stage B: the planner


def _planner(content: str):
    from src.agents.planner.decomposer import CriteriaPlanner

    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=content)
    with patch("src.agents.planner.decomposer.get_llm", return_value=llm):
        return CriteriaPlanner()


def _response(members: list[dict]) -> str:
    return json.dumps({"decompose": True, "reasoning": "umbrella", "sub_criteria": members})


#: The response the 2026-09-18 run really got for CARMELINA's ABSENCE parent,
#: reconstructed from the three store rows it produced
#: (``output/site_gap/2026-09-18_verify4/store/studies.json``, study 9,
#: inclusion ids 13/14/15) and the run's own ``✂ 'HbA1c' → ... (ABSENCE/ALL)``
#: log line. Both members name HbA1c; both bounds are copied off the one line.
TORN_BAND_MEMBERS = [
    {
        "name": "HbA1c below lower limit",
        "entity_text": "HbA1c",
        "domain": "Measurement",
        "source_span": "HbA1c",
        "value_constraint_text": "≥ 6.5%",
    },
    {
        "name": "HbA1c above upper limit",
        "entity_text": "HbA1c",
        "domain": "Measurement",
        "source_span": "HbA1c",
        "value_constraint_text": "≤ 10.0%",
    },
]


def _carmelina_upper_parent(index: int = 5):
    """`target/inclusion_rules[5]` as the planner receives it, verbatim."""
    from src.agents.agent1.parser import LogicDecomposer

    with patch("src.agents.agent1.parser.get_llm", return_value=MagicMock()):
        agent1 = LogicDecomposer(model_name="vllm/google/gemma-4-E4B-it")
    return agent1._build_criteria(_cache(CARMELINA_ARM)["target"]["inclusion_rules"][index])


class TestTheSplitOfOneRangeIsDeclined:
    def test_should_decline_when_every_member_is_the_parent_analyte_with_a_one_sided_bound(
        self,
    ):
        parent = _carmelina_upper_parent()
        planner = _planner(_response(TORN_BAND_MEMBERS))

        out = planner._decompose_criterion(parent)

        assert out.sub_criteria == [], (
            "one criterion's range is still torn into members: "
            f"{[(s.name, s.value_constraint.op) for s in out.sub_criteria]}"
        )

    def test_should_keep_the_parent_exactly_as_agent_1_extracted_it(self):
        parent = _carmelina_upper_parent()
        planner = _planner(_response(TORN_BAND_MEMBERS))

        out = planner._decompose_criterion(parent)

        assert out.entity_text == "HbA1c"
        assert out.logic_type == "ABSENCE"
        assert (out.value_constraint.op, out.value_constraint.value) == ("lte", 10.0)
        # Untouched: `group_type` is only meaningful with members, and #13's `ALL`
        # is what turned the two torn halves into a complement of #12.
        assert out.group_type == "ALL"
        assert out.source_text == CARMELINA_LINE

    def test_should_record_the_decline(self, capsys):
        """A decline that leaves no trace is how this defect stayed invisible: the
        run's log showed `✂ 'HbA1c' → 2 sub-criteria` and nothing said the members
        were two halves of one bound."""
        planner = _planner(_response(TORN_BAND_MEMBERS))

        planner._decompose_criterion(_carmelina_upper_parent())

        out = capsys.readouterr().out
        assert "⊘" in out
        assert "split declined" in out
        assert "HbA1c" in out
        # The reason has to name the shape, not just the outcome.
        assert "one-sided" in out
        assert "below lower limit" in out


class TestTheMergedBandIsNotTornApartAgain:
    """Fix A merges the pair into one `PRESENCE bt 6.5..10.0`, and THAT criterion
    reaches the planner -- same analyte, same line, same model. The decline reads
    the MEMBERS' bounds and never the parent's, so it covers a `bt` parent
    unchanged; without that the correction would hand the planner a whole band to
    tear in half again, and the delivered `ANY(gte, lte)` shape would come back.

    A member can never itself carry a `bt`: `parse_value_constraint` returns None
    for a range phrase, measured -- `"6.5 - 10.0%"` and `"between 6.5 and 10.0%"`
    both parse to None -- so a member's bound is one-sided or absent, never a band.
    """

    def test_should_decline_the_split_when_the_parent_carries_the_merged_band(self, models):
        parent = models.Criteria(
            name="HbA1c within target range",
            domain="Measurement",
            entity_text="HbA1c",
            source_text=CARMELINA_LINE,
            logic_type="PRESENCE",
            value_constraint=models.ValueConstraint(
                op="bt", value=6.5, value_high=10.0, unit_text="%"
            ),
        )
        planner = _planner(_response(TORN_BAND_MEMBERS))

        out = planner._decompose_criterion(parent)

        assert out.sub_criteria == []
        vc = out.value_constraint
        assert (vc.op, vc.value, vc.value_high) == ("bt", 6.5, 10.0)


class TestAGenuineUmbrellaStillSplits:
    #: CAROLINA's liver panel, verbatim from `CAROLINA_ARM`,
    #: `target/exclusion_rules`. The parent carries `gt 3.0 x ULN` -- one-sided,
    #: exactly like the HbA1c parents -- so only the members' analytes differ.
    LIVER_MEMBERS = [
        {
            "name": "ALT elevation",
            "entity_text": "ALT",
            "domain": "Measurement",
            "source_span": "ALT (SGPT)",
            "value_constraint_text": "above 3 x upper limit of normal (ULN)",
        },
        {
            "name": "AST elevation",
            "entity_text": "AST",
            "domain": "Measurement",
            "source_span": "AST (SGOT)",
            "value_constraint_text": "above 3 x upper limit of normal (ULN)",
        },
        {
            "name": "Alkaline phosphatase elevation",
            "entity_text": "alkaline phosphatase",
            "domain": "Measurement",
            "source_span": "alkaline phosphatase",
            "value_constraint_text": "above 3 x upper limit of normal (ULN)",
        },
    ]

    def _liver_parent(self):
        from src.agents.agent1.parser import LogicDecomposer

        with patch("src.agents.agent1.parser.get_llm", return_value=MagicMock()):
            agent1 = LogicDecomposer(model_name="vllm/google/gemma-4-E4B-it")
        for raw in _cache(CAROLINA_ARM)["target"]["exclusion_rules"]:
            if raw.get("entity_text") == "ALT or AST or alkaline phosphatase":
                return agent1._build_criteria(raw, force_logic_type="ABSENCE")
        pytest.skip("the liver-panel umbrella is not in this arm")

    def test_should_still_split_when_the_members_name_different_analytes(self):
        parent = self._liver_parent()
        assert parent.value_constraint.op == "gt", "the control's parent is one-sided"

        out = _planner(_response(self.LIVER_MEMBERS))._decompose_criterion(parent)

        assert [s.entity_text for s in out.sub_criteria] == [
            "ALT",
            "AST",
            "alkaline phosphatase",
        ]
        assert out.group_type == "ALL"

    def test_should_still_split_one_threshold_restated_in_two_units(self, models):
        """CAROLINA study 10's `Uncontrolled hyperglycaemia`, the one of the six
        same-analyte groups that is NOT a torn range: `>240 mg/dl` and
        `>13.3 mmol/L` are one threshold in two units, and CIRCE's unit filter is a
        per-criterion AND, so dropping the second member drops every row recorded in
        mmol/L. Both members name Glucose and both bounds are one-sided, so the two
        stated gates alone would decline this -- the unit gate is what keeps it."""
        parent = models.Criteria(
            name="Uncontrolled hyperglycaemia",
            domain="Measurement",
            entity_text="Glucose",
            source_text=(
                "Any uncontrolled hyperglycaemia with a plasma/serum glucose "
                ">240 mg/dl (>13.3 mmol/L) after an overnight fast"
            ),
            logic_type="ABSENCE",
            value_constraint=models.ValueConstraint(
                op="gt", value=240.0, unit_text="mg/dl"
            ),
        )
        members = [
            {
                "name": "Glucose level >240 mg/dl after overnight fast",
                "entity_text": "Glucose",
                "domain": "Measurement",
                "source_span": "glucose",
                "value_constraint_text": ">240 mg/dl",
            },
            {
                "name": "Glucose level >13.3 mmol/L after overnight fast",
                "entity_text": "Glucose",
                "domain": "Measurement",
                "source_span": "glucose",
                "value_constraint_text": ">13.3 mmol/L",
            },
        ]

        out = _planner(_response(members))._decompose_criterion(parent)

        assert [s.value_constraint.unit_text for s in out.sub_criteria] == [
            "mg/dl",
            "mmol/L",
        ]

    def test_should_still_split_when_a_member_carries_no_bound_at_all(self, models):
        """A member with no parsed bound is not a torn half. EMPA-REG's
        `Bariatric surgery or intervention` fans out into three procedures, none of
        them carrying a number, and must be untouched by a rule about bounds."""
        parent = models.Criteria(
            name="Bariatric surgery or intervention",
            domain="Procedure",
            entity_text="Bariatric surgery or intervention",
            source_text="Bariatric surgery or other gastrointestinal interventions",
            logic_type="ABSENCE",
        )
        members = [
            {
                "name": m,
                "entity_text": m,
                "domain": "Procedure",
                "source_span": None,
                "value_constraint_text": None,
            }
            for m in ("open bariatric surgery", "laparascopic bariatric surgery", "gastric sleeve")
        ]

        out = _planner(_response(members))._decompose_criterion(parent)

        assert len(out.sub_criteria) == 3
