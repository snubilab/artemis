"""A member's duration that its inherited window already holds is not also a value filter.

Measured on the P6 SEG-OFF arm: EMPA-REG "Bariatric surgery within the past two years"
(window -730, member value_constraint eq 2 years), CARMELINA "ACS diagnosed <= 2 months
prior" (window -60, lte 2 months) and CAROLINA "IMP given 2 months before ..." (window -60,
lt 2 months) were refused as unreadable-value-filter: a Procedure/Condition occurrence
cannot read Unit/ValueAsNumber. The duration was already the window, which every member
inherits from its parent. Time is recognised by the unit's UCUM concept id, never by a word.
"""
from unittest.mock import MagicMock, patch

from src.agents.planner.decomposer import CriteriaPlanner, duration_held_by_window
from src.models.ir import Criteria, TemporalWindow, ValueConstraint


def test_should_recognise_a_duration_the_window_already_holds():
    assert duration_held_by_window(ValueConstraint(op="eq", value=2, unit_text="years"),
                                   TemporalWindow(start=-730, end=0))
    assert duration_held_by_window(ValueConstraint(op="lte", value=2, unit_text="months"),
                                   TemporalWindow(start=-60, end=0))


def test_should_recognise_a_duration_in_days_the_window_already_holds():
    """P7 SEG-OFF, both arms: ARISTOTLE 'Recent ischemic stroke (within 7 days)' (eq 7 days,
    window -7) and 'investigational drug or device within the past 30 days' (eq 30 days,
    window -30) were refused as unreadable-value-filter -- the UCUM concept path resolves no
    day."""
    assert duration_held_by_window(ValueConstraint(op="eq", value=7, unit_text="days"),
                                   TemporalWindow(start=-7, end=0))
    assert duration_held_by_window(ValueConstraint(op="eq", value=30, unit_text="days"),
                                   TemporalWindow(start=-30, end=0))
    assert not duration_held_by_window(ValueConstraint(op="eq", value=7, unit_text="days"),
                                       TemporalWindow(start=-30, end=0))
    assert not duration_held_by_window(ValueConstraint(op="gte", value=7, unit_text="days"),
                                       TemporalWindow(start=-7, end=0))


def test_should_keep_a_bound_that_is_not_the_window():
    # "symptoms >= 10 minutes" under a 24-day window: a duration, but not the window's
    assert not duration_held_by_window(ValueConstraint(op="gte", value=10, unit_text="min"),
                                       TemporalWindow(start=-24, end=0))
    assert not duration_held_by_window(ValueConstraint(op="eq", value=3), TemporalWindow(start=-9999, end=0))
    assert not duration_held_by_window(ValueConstraint(op="lt", value=30, unit_text="mL/min/1.73 m2"),
                                       TemporalWindow(start=-30, end=0))
    assert not duration_held_by_window(ValueConstraint(op="eq", value=2, unit_text="years"), None)
    # "stable for at least 8 weeks": a minimum length, not the 56-day lookback
    assert not duration_held_by_window(ValueConstraint(op="gte", value=8, unit_text="weeks"),
                                       TemporalWindow(start=-56, end=0))


RESPONSE = """{"decompose": true, "reasoning": "two surgeries", "relation": "all", "relation_span": "and", "sub_criteria": [
 {"name": "Bariatric surgery", "entity_text": "Bariatric surgery", "domain": "Procedure",
  "source_span": "Bariatric surgery", "value_constraint_text": "within the past two years",
  "value_constraint": {"op": "eq", "value": 2, "unit_text": "years"}},
 {"name": "GI surgery", "entity_text": "gastrointestinal surgery", "domain": "Procedure",
  "source_span": "gastrointestinal surgeries", "value_constraint_text": null}]}"""


def test_should_build_the_member_without_the_duplicate_duration():
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=RESPONSE)
    with patch("src.agents.planner.decomposer.get_llm", return_value=llm):
        planner = CriteriaPlanner()
    parent = Criteria(
        name="Bariatric or GI surgery", domain="Procedure", entity_text="Bariatric surgery",
        logic_type="ABSENCE", window=TemporalWindow(start=-730, end=0),
        source_text="6. Bariatric surgery within the past two years and other gastrointestinal surgeries",
    )
    members = planner._decompose_criterion(parent).sub_criteria
    assert members and members[0].value_constraint is None
    assert members[0].window.start == -730
