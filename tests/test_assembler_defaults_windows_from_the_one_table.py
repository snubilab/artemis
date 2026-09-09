"""The second home of the criterion-window default, routed through the first.

`c1cb2c0` gave the per-domain default one home -- `circe_lint.
DEFAULT_WINDOW_START_DAYS_BY_DOMAIN` -- and fixed the emit site in `tte_service`.
It found this second implementation and listed it rather than sweeping it:
`CohortAssembler._build_inclusion_rule` defaulted a null window to a flat 9999 for
every domain, agreeing with the table on Condition/Procedure and disagreeing on
Drug (365) and Measurement (180). So the same decision had two homes again, one
stage over, and the disagreement was silent in both directions the table exists to
name.

The caution attached to that entry was that routing it "would change an untested
path beyond the measured defect". Measured, that is half right, and the half that
is wrong is the load-bearing half:

* the path IS executed -- instrumenting `_build_inclusion_rule` over the fourteen
  assembler-touching test files, 19 of 27 calls took the null-window branch,
  across 15 test cases in 5 files, emitting 36 of the 44 criteria entries;
* but nothing ASSERTS the value THIS builder emits. `9999` is asserted as a window
  in exactly one file, `test_defaulted_criterion_window_is_domain_correct.py`, and
  every one of those assertions pins the EMITTER
  (`TTEService._build_seeded_eligibility_rule`); no test anywhere read a
  `StartWindow` back out of `CohortAssembler`. The two other assembler fixtures
  carrying a `StartWindow` construct it as INPUT. The branch ran constantly and its
  output was never once checked, which is why two builders could disagree for as
  long as they did.

The two are not legitimately different decisions, which is what would license
leaving them apart. Both builders consume IR produced by Agent 1, and all four of
Agent 1's prompts state these same per-domain defaults, rendered from this same
table (`agent1/prompts.py` lines 42, 198, 243, 649 via
`render_default_window_prompt_line`). `supervisor._step1_parse` reaches them
through `parse_nct` or `parse`. So when the model omits `window` -- 57 of 557
criteria in the cold-6 store, 10% -- the assembler's flat 9999 contradicts the
instruction the model was given, in exactly the shape `c1cb2c0` fixed downstream.

What actually moves, dumping every emitted StartWindow over those fourteen files:

    emitted criteria entries              44
    carried their own window               8   unchanged, both builders
    defaulted, ConditionOccurrence        19   9999 -> 9999, byte-identical
    defaulted, Measurement                17   9999 ->  180

Condition, Procedure and every domain the table does not list keep 9999, because
`_offset_to_circe_window(-9999)` is exactly the literal that was there. Only Drug
and Measurement move, and both move to the number the extraction prompt already
told the model to use.

The default is resolved per EMITTED CRITERION, not per rule. The old code computed
one `start_window` from the rule and wrote it onto every member of a composite
group; that is right when the rule carries a window (the protocol stated one time
frame for the group) and wrong when it does not, because a mixed group would then
take one domain's default for another domain's member. Every group in the current
fixtures is domain-homogeneous, so this changes nothing measurable today -- it is
the unit the decision is keyed by, made to match the table's key and the emit
site's.
"""

from __future__ import annotations

import pytest

from src.models.ir import Criteria, TemporalWindow
from src.utils.circe_lint import (
    DEFAULT_WINDOW_START_DAYS_BY_DOMAIN,
    DEFAULT_WINDOW_START_DAYS_UNLISTED_DOMAIN,
    default_criterion_window,
)


@pytest.fixture
def assembler():
    from src.agents.agent3.assembler import CohortAssembler

    return CohortAssembler()


def _crit(domain: str, **kwargs) -> Criteria:
    return Criteria(
        name=kwargs.pop("name", f"{domain} criterion"),
        domain=domain,
        entity_text=kwargs.pop("entity_text", f"{domain} entity"),
        **kwargs,
    )


def _windows(rule: dict) -> list[dict]:
    return [entry["StartWindow"] for entry in rule["expression"]["CriteriaList"]]


def _start_days(rule: dict) -> list[int]:
    """Signed days, so a sign error cannot read as a magnitude match."""
    return [w["Start"]["Days"] * w["Start"]["Coeff"] for w in _windows(rule)]


class TestADefaultedWindowComesFromTheDomainTable:
    """The four documented domains, each against the one table rather than a literal."""

    @pytest.mark.parametrize(
        "domain",
        sorted(DEFAULT_WINDOW_START_DAYS_BY_DOMAIN),
    )
    def test_should_emit_the_tables_lookback_when_a_rule_carries_no_window(
        self, assembler, domain
    ):
        rule = assembler._build_inclusion_rule(_crit(domain), [], 0)
        expected, _source = default_criterion_window(domain)
        assert _start_days(rule) == [expected["start"]]

    def test_should_narrow_a_drug_rule_to_one_year(self, assembler):
        """The concrete half of the disagreement: 9999 before, 365 now."""
        rule = assembler._build_inclusion_rule(_crit("Drug"), [], 0)
        assert _start_days(rule) == [-365]

    def test_should_narrow_a_measurement_rule_to_one_hundred_eighty_days(self, assembler):
        rule = assembler._build_inclusion_rule(_crit("Measurement"), [], 0)
        assert _start_days(rule) == [-180]

    @pytest.mark.parametrize("domain", ["Condition", "Procedure"])
    def test_should_leave_all_prior_history_unchanged(self, assembler, domain):
        """Byte-identity with the literal that was here, so the only thing this
        change moves is Drug and Measurement."""
        rule = assembler._build_inclusion_rule(_crit(domain), [], 0)
        assert _windows(rule) == [
            {"Start": {"Days": 9999, "Coeff": -1}, "End": {"Days": 0, "Coeff": 1}}
        ]

    @pytest.mark.parametrize("domain", ["Observation", "Device", "Visit", "Death"])
    def test_should_take_all_prior_history_when_the_domain_is_not_in_the_table(
        self, assembler, domain
    ):
        """A domain the prompt never documented takes the judged value, which is the
        only reading that cannot silently NARROW a criterion left unbounded."""
        rule = assembler._build_inclusion_rule(_crit(domain), [], 0)
        assert _start_days(rule) == [DEFAULT_WINDOW_START_DAYS_UNLISTED_DOMAIN]


class TestTheTableIsTheOnlyHome:
    """The point of the change. A retyped copy passes every test above on the day it
    is written and drifts silently afterwards; only following an edit proves there is
    no second number left."""

    def test_should_follow_the_table_when_a_documented_default_moves(
        self, assembler, monkeypatch
    ):
        monkeypatch.setitem(DEFAULT_WINDOW_START_DAYS_BY_DOMAIN, "Procedure", -730)
        rule = assembler._build_inclusion_rule(_crit("Procedure"), [], 0)
        assert _start_days(rule) == [-730]

    def test_should_follow_the_table_when_a_domain_is_added(self, assembler, monkeypatch):
        monkeypatch.setitem(DEFAULT_WINDOW_START_DAYS_BY_DOMAIN, "Observation", -42)
        rule = assembler._build_inclusion_rule(_crit("Observation"), [], 0)
        assert _start_days(rule) == [-42]

    def test_should_agree_with_the_emitter_on_every_documented_domain(self, assembler):
        """The two builders, compared directly. This is the assertion whose absence
        let them disagree on Drug and Measurement for as long as they did."""
        for domain in sorted(DEFAULT_WINDOW_START_DAYS_BY_DOMAIN):
            emitter_window, _ = default_criterion_window(domain)
            rule = assembler._build_inclusion_rule(_crit(domain), [], 0)
            assert _start_days(rule) == [emitter_window["start"]], domain


class TestTheDefaultIsResolvedPerCriterionNotPerRule:
    def test_should_resolve_each_member_of_a_mixed_group_from_its_own_domain(
        self, assembler
    ):
        """One `start_window` shared across a mixed group puts one domain's default
        on another domain's member. Only reachable once a group mixes domains, which
        no current fixture does -- so it is pinned here rather than left to be found."""
        rule = assembler._build_inclusion_rule(
            _crit(
                "Measurement",
                name="Renal or hepatic impairment",
                sub_criteria=[
                    _crit("Measurement", name="Creatinine clearance"),
                    _crit("Drug", name="Nephrotoxic drug"),
                    _crit("Condition", name="Chronic kidney disease"),
                ],
            ),
            [],
            0,
        )
        assert _start_days(rule) == [-180, -365, -9999]

    def test_should_share_the_rules_own_window_across_a_mixed_group(self, assembler):
        """The opposite direction, unchanged: a window the protocol DID state applies
        to the whole group, whatever domains sit in it."""
        rule = assembler._build_inclusion_rule(
            _crit(
                "Measurement",
                name="Renal or hepatic impairment",
                window=TemporalWindow(start=-90, end=0),
                sub_criteria=[
                    _crit("Measurement", name="Creatinine clearance"),
                    _crit("Drug", name="Nephrotoxic drug"),
                ],
            ),
            [],
            0,
        )
        assert _start_days(rule) == [-90, -90]


class TestAnExtractedWindowIsUntouched:
    def test_should_keep_a_rules_own_window_when_it_carries_one(self, assembler):
        rule = assembler._build_inclusion_rule(
            _crit("Drug", window=TemporalWindow(start=-30, end=0)), [], 0
        )
        assert _windows(rule) == [
            {"Start": {"Days": 30, "Coeff": -1}, "End": {"Days": 0, "Coeff": 1}}
        ]

    def test_should_keep_a_forward_looking_window_when_it_carries_one(self, assembler):
        """`_offset_to_circe_window` handles both signs and the default path now runs
        through it too, so a defaulted window cannot be converted differently from an
        extracted one -- the property `c1cb2c0` built into the emit site."""
        rule = assembler._build_inclusion_rule(
            _crit("Condition", window=TemporalWindow(start=-7, end=30)), [], 0
        )
        assert _windows(rule) == [
            {"Start": {"Days": 7, "Coeff": -1}, "End": {"Days": 30, "Coeff": 1}}
        ]
