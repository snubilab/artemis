"""A time window is written by the model and, until now, checked by nothing.

``_build_criteria`` does ``TemporalWindow(**data["window"])`` straight from the LLM's
JSON -- no unit conversion, no comparison against the protocol line. The 2026-09-14
conversion audit (``output/site_gap/2026-09-14/conversion_audit.json``) found seven
time-window defects in one delivery, six of which change who enters a cohort, in three
distinct shapes:

* **the unit is never converted** -- PLATO's ``onset during the previous 24 hours`` and
  ``fibrinolytic therapy ... within the previous 24 h`` both became 24 DAYS, and
  CARMELINA's ``cancer ... within last 3 years`` became 3 DAYS, which made that
  exclusion inert;
* **the magnitude slips** -- CAROLINA's ``6 weeks`` became 420 days on four rules. This
  is not a unit confusion: the same model on the same line writes the correct ``-42``
  on 76 windows across the 122 cached parses, so 420 is a digit the model appended;
* **the direction inverts** -- ``Myocardial infarction (> 6 weeks prior to informed
  consent)`` means the infarction must be OLDER than six weeks, an open-ended lower
  bound on elapsed time. Emitted as ``-42..0`` it says the opposite and selects exactly
  the patients that branch of the protocol excludes. CABG (4 years) and stroke (3
  months) carry the right magnitude and the exactly inverted sense.

A fourth shape, a window with nothing behind it at all: PLATO's ``Index event is an
acute complication of PCI`` states no number anywhere and was emitted with a 24-day
window -- the numeral of the two unrelated ``24 h`` phrases in the same trial.

Every assertion here runs the caches the delivery itself replayed, read from
``output/site_gap/2026-09-14/reingest.log``, rather than a fixture -- a repair has to
be shown on the case that motivated it.

The fixture reloads ``src.models.ir`` and ``src.agents.agent1.parser`` for the reason
``tests/test_repair_accounting_and_inclusive_bounds.py`` gives: another module installs
a ``MagicMock`` over ``sys.modules["src.models.ir"]`` at import time and never restores
it, so an unguarded import asserts against a mock in a full-suite run.
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

#: The caches the 2026-09-14 delivery replayed, read from its own
#: ``output/site_gap/2026-09-14/reingest.log``.
DELIVERED = {
    "PLATO": "NCT00391872_vllm_google_gemma-4-E4B-it_17d77b5f03f09b73.json",
    "CAROLINA": "NCT01243424_vllm_google_gemma-4-E4B-it_ac7e953e86d338ee.json",
    "CARMELINA": "NCT01897532_vllm_google_gemma-4-E4B-it_7ae74b822cdf141a.json",
}

#: The all-time sentinel a lower-bound window opens at (``prompts.py``,
#: ``circe_lint.py``).
ALL_TIME = -9999


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
def decomposer(parser_module):
    with patch.object(parser_module, "get_llm", return_value=MagicMock()):
        return parser_module.LogicDecomposer(model_name="vllm/google/gemma-4-E4B-it")


def _nodes(rules, out=None):
    """Every criterion in the tree, groups and their members alike."""
    out = [] if out is None else out
    for rule in rules or []:
        out.append(rule)
        _nodes(getattr(rule, "sub_criteria", None), out)
    return out


@pytest.fixture
def parsed(decomposer):
    """``{trial: (target_cohort, [every criterion in it])}`` for the delivered arm."""
    built = {}
    for trial, filename in DELIVERED.items():
        request = decomposer._build_artemis_request(json.loads((CACHE / filename).read_text()))
        target = request.target
        built[trial] = (
            target,
            _nodes(target.inclusion_rules) + _nodes(target.exclusion_rules),
        )
    return built


def _one(nodes, name):
    matches = [n for n in nodes if n.name == name]
    assert matches, f"no criterion named {name!r} in this cache"
    return matches[0]


def _window(nodes, name):
    window = _one(nodes, name).window
    return None if window is None else (window.start, window.end)


def _window_records(cohort):
    return [
        record for record in (cohort.repair_accounting or [])
        if str(record.get("action", "")).startswith("protocol-window")
    ]


# ------------------------------------------------------- the seven audit findings


class TestTheDefectsTheConversionAuditFound:
    def test_should_open_at_all_time_when_the_line_says_the_event_must_be_older(
        self, parsed
    ):
        """CAROLINA inclusion 3.A -- the four ``> N prior to informed consent`` qualifiers.

        All four share one 1,861-character OR-group protocol line that states six
        intervals, so each is resolved by where its own entity is named in that line,
        not by picking the line's first number.

        The magnitudes: MI and PCI ``> 6 weeks`` = 42 days (emitted as 420, ten times
        too long AND inverted); CABG ``> 4 years`` = 1460 and stroke ``> 3 months`` = 90
        (both emitted with the right magnitude and the exactly wrong sense).
        """
        _, nodes = parsed["CAROLINA"]
        assert _window(nodes, "Myocardial infarction") == (ALL_TIME, -42)
        assert _window(nodes, "Percutaneous Coronary Intervention (PCI)") == (ALL_TIME, -42)
        assert _window(nodes, "Coronary Artery By-pass Grafting (CABG)") == (ALL_TIME, -1460)
        assert _window(nodes, "Ischemic or hemorrhagic stroke") == (ALL_TIME, -90)

    def test_should_convert_weeks_to_days_when_the_emitted_magnitude_slipped(self, parsed):
        """CAROLINA exclusion -- ``Acute coronary syndrome <= 6 weeks prior to consent``.

        6 weeks is 42 days; 420 removed every patient with an ACS event up to fourteen
        months before consent. ``<=`` keeps this one a recency window, so only the
        magnitude moves -- the same line's ``>`` siblings above change shape as well.
        """
        _, nodes = parsed["CAROLINA"]
        assert _window(nodes, "Acute coronary syndrome") == (-42, 0)

    def test_should_convert_years_to_days_when_the_model_emitted_the_bare_number(
        self, parsed
    ):
        """CARMELINA exclusion 11 -- ``cancer ... within last 3 years`` became 3 DAYS.

        As emitted the exclusion fired only on a cancer diagnosis recorded in the three
        days before index, which is to say never. The line also states a ``life
        expectancy less than 5 years``, so the 3-year interval is the one attached to
        this criterion's own entity and the 5-year one is not a candidate: it is
        forward-looking.
        """
        _, nodes = parsed["CARMELINA"]
        assert _window(nodes, "Cancer other than nonmelanoma skin cancer") == (-1095, 0)

    def test_should_round_a_sub_day_interval_up_to_one_whole_day(self, parsed):
        """PLATO inclusion 1 and exclusion "Drug-related 3" -- both ``24 hours`` as 24 DAYS.

        Circe counts whole days, so 24 hours has to land on one. It lands on 1 and not
        on 0: ``Days: 0`` is not a shorter window but a different one -- the index date
        alone -- which drops an event twenty hours earlier that fell on the previous
        calendar date. Rounding up keeps every patient the protocol admits.
        """
        _, nodes = parsed["PLATO"]
        assert _window(nodes, "Fibrinolytic therapy planned or within the previous 24 h") == (-1, 0)
        onset = _one(nodes, "Hospitalized for ACS with onset in previous 24 hours, "
                            "ischemic symptoms >=10 min duration at rest, not pregnant, "
                            "and informed consent")
        assert (onset.window.start, onset.window.end) == (-1, 0)

    def test_should_drop_a_window_no_number_on_the_line_could_have_produced(self, parsed):
        """PLATO exclusion "Treatment-related 1" -- ``Index event is an acute complication of PCI``.

        No number on the line, none in the criterion's name, and a 24-day window --
        the numeral of the trial's two unrelated ``24 h`` phrases. Dropping it is not
        the same as widening it: ``_criterion_to_circe`` then supplies the documented
        default for the domain and RECORDS that it did, so the emitted window has a
        stated source instead of a borrowed digit.
        """
        _, nodes = parsed["PLATO"]
        assert _window(nodes, "Invasive procedure for current ACS episode") is None

    def test_should_repair_the_exclusion_side_and_not_only_the_inclusion_side(self, parsed):
        """Five of the seven audit findings are exclusions.

        The band repairs next to this one are inclusion-only for a reason specific to
        them -- ``_build_criteria`` forces ABSENCE on every exclusion, so a band's
        PRESENCE lower half cannot exist there. A window carries no operator, so that
        reason does not reach it, and a repair that inherited the restriction would
        leave most of its own subject alone.
        """
        repaired = {
            trial: [r["criterion"]["name"] for r in _window_records(cohort)]
            for trial, (cohort, _) in parsed.items()
        }
        assert "Acute coronary syndrome" in repaired["CAROLINA"]           # exclusion
        assert "Cancer other than nonmelanoma skin cancer" in repaired["CARMELINA"]  # exclusion
        assert "Invasive procedure for current ACS episode" in repaired["PLATO"]     # exclusion


# ------------------------------------------------------------------ the no-op guard


class TestItLeavesAWindowAloneWhenTheLineAgreesWithIt:
    def test_should_not_touch_a_window_that_already_reads_the_line_correctly(self, parsed):
        """Four windows in the delivered arm that the extraction already got right.

        CAROLINA's three ``<= 3 months prior to informed consent`` exclusions and
        CARMELINA's ``stable antidiabetic background medication ... 8 weeks`` are
        grounded by the same two paths that rewrite the seven defects, and are left
        exactly as the model wrote them. A repair that moved these would be churn on
        boundaries that were never wrong, which is the failure mode a rewriting repair
        has to be held to.
        """
        carolina_cohort, carolina = parsed["CAROLINA"]
        carmelina_cohort, carmelina = parsed["CARMELINA"]
        assert _window(carolina, "Alcohol or drug abuse") == (-90, 0)
        assert _window(carolina, "Stroke or TIA") == (-90, 0)
        assert _window(carolina, "Treatment with anti-obesity drugs") == (-90, 0)
        assert _window(carmelina, "Stable Antidiabetic Background Medication") == (-56, 0)

        untouched = {"Alcohol or drug abuse", "Stroke or TIA",
                     "Treatment with anti-obesity drugs",
                     "Stable Antidiabetic Background Medication"}
        rewritten = {
            record["criterion"]["name"]
            for cohort in (carolina_cohort, carmelina_cohort)
            for record in _window_records(cohort)
        }
        assert untouched & rewritten == set()

    def test_should_record_a_disagreement_for_every_window_it_rewrote(self, parsed):
        """Every rewrite is against a window the line contradicts -- none is a no-op.

        Checked by re-reading each record's own ``before`` through the same grounding
        the repair used: if any ``before`` already agreed with the line, the repair
        moved a correct boundary.
        """
        grounding = importlib.import_module("src.agents.agent1.temporal_grounding")
        for trial, (cohort, nodes) in parsed.items():
            by_name = {n.name: n for n in nodes}
            for record in _window_records(cohort):
                if record["action"] != "protocol-window-regrounded":
                    continue
                name = record["criterion"]["name"]
                line = by_name[name].source_text
                interval, _ = grounding.stated_interval(line, name)
                assert interval is not None, f"{trial}/{name}: rewritten without grounding"
                assert not grounding.window_agrees(
                    interval, record["before"]["start"], record["before"]["end"]
                ), f"{trial}/{name}: rewrote a window that already agreed with its line"

    def test_should_accept_both_renderings_of_a_calendar_month(self, parser_module):
        """``12 months`` is defensibly 360 days (12x30) and defensibly 365. Both occur.

        Re-rendering one into the other changes a number without fixing anything, so
        the whole 30-or-31-day band counts as correct and only a value outside it is a
        defect. Held on a real CAROLINA phrase.
        """
        grounding = importlib.import_module("src.agents.agent1.temporal_grounding")
        line = ("Random spot urinary albumin creatinine ratio >= 30 ug/mg in two of "
                "three unrelated specimens in previous 12 months prior Visit 1a")
        found = grounding.temporal_intervals(line)
        assert [(i.days, i.older_than) for i in found] == [(360, False)]
        assert grounding.window_agrees(found[0], -360, 0)
        assert grounding.window_agrees(found[0], -365, 0)
        assert not grounding.window_agrees(found[0], -12, 0)


# ------------------------------------------------- what the line reader refuses to read


class TestItRefusesTheNumbersThatAreNotWindows:
    def test_should_not_read_an_age_bound_as_a_time_window(self, parser_module):
        """PLATO's inclusion line ends ``>=18 years of age``.

        Read as a lookback that is 6,570 days, and it sits on the same line as the
        24-hour onset window, so without this every criterion on that line could
        inherit it.
        """
        grounding = importlib.import_module("src.agents.agent1.temporal_grounding")
        found = grounding.temporal_intervals(
            "documented by cardiac ischemic symptoms, >=18 years of age, not pregnant"
        )
        assert found == []

    def test_should_not_read_a_prospective_clause_as_a_lookback(self, parser_module):
        """CAROLINA states a planned procedure and a past one on ONE line.

        ``within next 6 months after V1a`` is prospective; ``<= 6 weeks prior informed
        consent`` on the same line is not. The direction is decided by the nearest
        direction word before the number, because both words are present.
        """
        grounding = importlib.import_module("src.agents.agent1.temporal_grounding")
        found = grounding.temporal_intervals(
            "Pre-planned coronary artery re-vascularisation (PCI, CABG) within next "
            "6 months after V1a or any previous PCI and/or CABG <= 6 weeks prior "
            "informed consent"
        )
        assert [(i.days, i.older_than) for i in found] == [(42, False)]

    def test_should_decline_when_the_line_states_intervals_that_are_not_this_criterion(
        self, parser_module
    ):
        """A multi-interval line and a criterion whose name states none: no answer.

        Admitting a first-interval-wins path here rewrote 268 further windows across
        the caches, among them ``Age >= 18 years`` taking PLATO's 24-hour window. A
        window this cannot ground is left exactly as the model wrote it.
        """
        grounding = importlib.import_module("src.agents.agent1.temporal_grounding")
        line = ("Myocardial infarction (> 6 weeks prior to informed consent) | "
                "Ischemic or hemorrhagic stroke (> 3 months prior to informed consent)")
        assert grounding.stated_interval(line, "Age >= 18 years") == (None, None)
