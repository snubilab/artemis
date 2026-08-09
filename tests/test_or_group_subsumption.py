"""A richer OR-GROUP must survive a merge against a poorer one, in every caller.

criteria_dedup.restates_or_group_alternative already refuses to call an OR-GROUP
candidate a duplicate -- the first of the two early returns its docstring says
carry "the whole safety argument". But refusing is not enough on its own: both
enricher merge sites fell straight through to the legacy whole-string
SequenceMatcher gate afterwards and dropped the richer group anyway, at a
measured ratio of 0.939. The module docstring predicted this exact loss and 30
predicate-level tests stayed green while it was live, which is why every test
here runs through a CALLER rather than through the predicate.

Losing the 5-alternative group and keeping the 4-alternative one silently
narrows the cohort: the fifth risk factor stops qualifying anyone.
"""
import pytest

from src.agents.agent1.criteria_dedup import (
    _ABLATION_ENV,
    OR_GROUP_JOIN,
    OR_GROUP_PREFIX,
    OR_GROUP_SEP,
    or_group_alternatives,
)
from src.agents.agent1.enricher import (
    _merge_criteria,
    _pick_richer,
    _supplement_priority_merge,
)


HEADER = "Atrial fibrillation (AF), males and females >= 18 yrs"
BASE_FOUR = [
    "Prior stroke",
    "Prior TIA",
    "Prior systemic embolus",
    "Congestive heart failure",
]


def group(alternatives, header=HEADER):
    """Build an OR-GROUP from the exported wire-format constants.

    Never re-typed as a literal: guessing the format makes every probe silently
    return False, which is a green test that proves nothing.

    :param alternatives: the alternative clauses.
    :param header: the group's mandatory AND-criteria.
    :returns: one OR-GROUP criterion string.
    """
    return f"{OR_GROUP_PREFIX}{header}{OR_GROUP_JOIN}{OR_GROUP_SEP.join(alternatives)}"


POOR = group(BASE_FOUR)
RICH = group(BASE_FOUR + ["Diabetes mellitus"])

# The real collision, verbatim: ARISTOTLE's protocol PDF states five stroke risk
# factors, ClinicalTrials.gov states the same list as four differently-worded
# alternatives. Subsumption has to be computed with the module's coverage
# machinery rather than by set operations on the raw strings, because the two
# sources are paraphrases -- "Prior stroke, TIA or systemic embolus" against
# "transient ischemic attack (TIA) or Systemic Embolism (SE)".
PROTOCOL_FIVE = (
    "[OR-GROUP] 3) One or more of the following risk factor(s) for stroke "
    "with any of: Age 75 years or older | Prior stroke, TIA or systemic "
    "embolus | Either symptomatic congestive heart failure within 3 months "
    "or left ventricular dysfunction with an LV ejection fraction (LVEF) "
    "≤ 40% by echocardiography, radionuclide study or contrast "
    "angiography | Diabetes mellitus | Hypertension requiring "
    "pharmacological treatment"
)
CTGOV_FOUR = (
    "[OR-GROUP] Males and females ≥ 18 yrs with atrial fibrillation (AF) and "
    "one or more of the following risk factors for stroke "
    "with any of: Age ≥ 75, previous stroke | transient ischemic attack (TIA) "
    "or Systemic Embolism (SE) | Symptomatic congestive heart failure or left "
    "ventricular dysfunction with left ventricular ejection fraction (LVEF) "
    "≤ 40% | Diabetes mellitus or hypertension requiring pharmacological treatment"
)

DISJOINT = group(["Chronic kidney disease", "Peripheral arterial disease"],
                 header="Any of the following comorbidities")

# Three of the four alternatives are covered by RICH; "Systemic Embolism (SE)"
# standing alone scores 0.667 against "Prior systemic embolus" under the
# module's tuned fuzzy-token threshold. Partial coverage is NOT subsumption.
PARTIALLY_COVERED = group(
    ["Previous stroke", "Transient ischemic attack (TIA)",
     "Systemic Embolism (SE)", "Symptomatic congestive heart failure"],
    header="Males and females >= 18 yrs with atrial fibrillation (AF)",
)


def groups_in(result):
    """:param result: a merged criteria list. :returns: alternative counts, per group."""
    return [len(or_group_alternatives(item)) for item in result
            if or_group_alternatives(item)]


MERGERS = {
    # (name, callable taking (first_list, second_list) in that argument order)
    "merge": _merge_criteria,
    "supplement_priority": _supplement_priority_merge,
    "replace": _pick_richer,
}


@pytest.mark.parametrize("caller", sorted(MERGERS))
@pytest.mark.parametrize("order", ["poor_first", "rich_first"])
def test_should_keep_the_richer_group_when_two_groups_meet(caller, order):
    """Direction must not decide which group survives.

    ARISTOTLE really does take this path: parser._enrich_from_pdf runs once per
    discovered PDF and NCT00412984 has two, so the second PDF's group meets the
    first PDF's group inside _supplement_priority_merge.
    """
    first, second = (POOR, RICH) if order == "poor_first" else (RICH, POOR)

    result = MERGERS[caller]([first], [second])

    assert groups_in(result) == [5], f"{caller}/{order} lost the richer group"
    assert any("Diabetes mellitus" in item for item in result)


@pytest.mark.parametrize("caller", sorted(MERGERS))
@pytest.mark.parametrize("order", ["poor_first", "rich_first"])
def test_should_keep_the_richer_group_when_the_poorer_one_is_a_paraphrase(caller, order):
    """The real collision is between paraphrases, not between identical strings."""
    first, second = ((CTGOV_FOUR, PROTOCOL_FIVE) if order == "poor_first"
                     else (PROTOCOL_FIVE, CTGOV_FOUR))

    result = MERGERS[caller]([first], [second])

    assert groups_in(result) == [5], f"{caller}/{order} lost the richer group"
    assert any("Hypertension requiring" in item for item in result)


@pytest.mark.parametrize("caller", sorted(MERGERS))
def test_should_collapse_to_one_group_when_both_sides_carry_the_same_group(caller):
    """Exactly one survivor. Zero is the failure mode a self-exclusion guard causes:
    each group subsumes the other, so both get swept out and the structure vanishes.
    """
    result = MERGERS[caller]([RICH], [RICH])

    assert groups_in(result) == [5]


@pytest.mark.parametrize("caller", sorted(MERGERS))
def test_should_keep_both_groups_when_neither_subsumes_the_other(caller):
    """"Richer" means superset-of-alternatives, never union.

    Unioning two groups builds an ANY node that no source states, which widens
    an inclusion group to patients the protocol excludes. When neither group
    covers the other, both are kept: two ANY nodes AND-ed is stricter than
    either alone and is precisely what the two sources jointly assert.
    """
    result = MERGERS[caller]([RICH], [DISJOINT])

    assert sorted(groups_in(result)) == [2, 5]


@pytest.mark.parametrize("caller", sorted(MERGERS))
def test_should_keep_both_groups_when_only_some_alternatives_are_covered(caller):
    """Subsumption is all-or-nothing, and partial coverage keeps both groups.

    Three of PARTIALLY_COVERED's four alternatives are stated by RICH; the
    fourth is not, so discarding it would lose a qualifying route into the
    cohort. This is the conservative half of the superset-not-union decision.
    """
    result = MERGERS[caller]([RICH], [PARTIALLY_COVERED])

    assert sorted(groups_in(result)) == [4, 5]


def test_should_drop_the_flat_restatements_but_keep_the_group_in_the_same_merge():
    """Structural retention must not disable the flat-item sweep that motivated the module."""
    flat = ["Prior stroke", "Prior TIA", "Age >= 18 years"]

    result = _merge_criteria(flat, [RICH])

    assert groups_in(result) == [5]
    assert "Prior stroke" not in result
    assert "Prior TIA" not in result
    assert "Age >= 18 years" in result, "a mandatory AND-criterion was swept out"


def test_should_reproduce_the_pre_fix_behaviour_when_the_ablation_is_enabled(monkeypatch):
    """The control arm must be a clean no-op, not a second code path.

    With the ablation on, the richer group is still dropped by the legacy 0.939
    similarity ratio -- that is what the arm exists to measure.
    """
    monkeypatch.setenv(_ABLATION_ENV, "1")

    assert _merge_criteria([POOR], [RICH]) == [POOR]
    assert _supplement_priority_merge([POOR], [RICH]) == [POOR]
