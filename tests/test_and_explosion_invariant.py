"""No criterion may restate an alternative that sits in the same result list.

This is the invariant whose violation emptied the ARISTOTLE cohort, and the only
test here that would have caught it. Circe ANDs top-level inclusion rules, so a
clause standing alongside the OR group that already offers it turns "any one of
these five risk factors" into "all five at once". Measured on ARISTOTLE before
the fix: four violations under supplement_priority and four under merge.

The criteria are copied literally rather than re-parsed from the PDF, so this
test stays a fixed invariant check and cannot drift with the extractor.
"""
import pytest

from src.agents.agent1 import criteria_dedup
from src.agents.agent1.criteria_dedup import (
    is_or_group,
    or_group_alternatives,
    restates_or_group_alternative,
)
from src.agents.agent1.enricher import (
    _merge_criteria,
    _pick_richer,
    _supplement_priority_merge,
)


# Verbatim output of extract_eligibility_from_text over
# data/papers/NCT00412984/nejmoa1107039_protocol.pdf, 2026-08-07.
PDF_INCLUSION = [
    "[OR-GROUP] 3) One or more of the following risk factor(s) for stroke with any of: "
    "Age 75 years or older | Prior stroke, TIA or systemic embolus | Either symptomatic "
    "congestive heart failure within 3 months or left ventricular dysfunction with an LV "
    "ejection fraction (LVEF) ≤ 40% by echocardiography, radionuclide study or contrast "
    "angiography | Diabetes mellitus | Hypertension requiring pharmacological treatment",
    "For entry into the study, the following criteria MUST be met",
    "Age ≥ 18 years",
    "In atrial fibrillation or atrial flutter not due to a reversible cause and documented by",
    "ECG at the time of enrollment",
    "If not in atrial fibrillation/flutter at the time of enrollment, must have atrial "
    "fibrillation/flutter documented on two separate occasions, not due to a reversible "
    "cause at least 2 weeks apart in the 12 months prior to enrollment. Atrial "
    "fibrillation/flutter may be documented by ECG, or as an episode lasting at least one "
    "minute on a rhythm strip,",
    "Holter recording, or intracardiac electrogram (from an implanted pacemaker or defibrillator)",
    "Women of childbearing potential (WOCBP) must be using an adequate method of "
    "contraception to avoid pregnancy throughout the",
]

# Verbatim output of nct_fetcher._parse_criteria_text over
# data/nct_cache/NCT00412984.json. Items 1-4 are the same five risk factors the
# protocol lists as alternatives, flattened into siblings.
NCT_INCLUSION = [
    "* Males and females ≥ 18 yrs with atrial fibrillation (AF) and one or more of the "
    "following risk factors for stroke:",
    "Age ≥ 75, previous stroke",
    "transient ischemic attack (TIA) or Systemic Embolism (SE)",
    "Symptomatic congestive heart failure or left ventricular dysfunction with left "
    "ventricular ejection fraction (LVEF) ≤ 40%",
    "Diabetes mellitus or hypertension requiring pharmacological treatment",
]

STRATEGIES = {
    "supplement_priority": lambda: _supplement_priority_merge(PDF_INCLUSION, NCT_INCLUSION),
    "merge": lambda: _merge_criteria(NCT_INCLUSION, PDF_INCLUSION),
    "replace": lambda: _pick_richer(NCT_INCLUSION, PDF_INCLUSION),
}


def _coverage_violations(result):
    """Items that restate an alternative offered by a group in the same list."""
    return [item for item in result
            if not is_or_group(item) and restates_or_group_alternative(item, result)]


def _identity_violations(result):
    """Items whose normalised form equals an alternative's, threshold-independent.

    Coverage uses a tuned threshold; this second check does not, so a candidate
    that slips past the threshold because it carries too few content tokens is
    still caught.
    """
    alternatives = {criteria_dedup._normalize(alt)
                    for item in result for alt in or_group_alternatives(item)}
    return [item for item in result
            if not is_or_group(item) and criteria_dedup._normalize(item) in alternatives]


@pytest.mark.parametrize("strategy", sorted(STRATEGIES))
def test_should_not_restate_a_group_alternative_as_its_own_criterion(strategy):
    result = STRATEGIES[strategy]()

    assert _coverage_violations(result) == []
    assert _identity_violations(result) == []


@pytest.mark.parametrize("strategy", sorted(STRATEGIES))
def test_should_keep_the_risk_factor_group_intact(strategy):
    """Deduplication must remove the restatements, not the structure."""
    result = STRATEGIES[strategy]()
    groups = [item for item in result if is_or_group(item)]

    assert len(groups) == 1
    assert len(or_group_alternatives(groups[0])) == 5


def test_should_keep_the_group_when_the_flat_source_is_the_longer_one():
    """_pick_richer must not choose by count alone.

    Collapsing five alternatives into one string costs that source four from
    its length, so a raw comparison is biased against whichever side carries
    the structure. On ARISTOTLE today the margin is only +3 (PDF 8 against
    registry 5); three more swallowed siblings and the group is discarded
    outright and its five risk factors go back to being AND-ed.

    The main fixture above cannot catch this -- with PDF 8 > registry 5 the
    pre-fix count comparison happens to return the right list, so the
    [replace] case passes for a reason unrelated to the fix.
    """
    group_side = [PDF_INCLUSION[0], "Age ≥ 18 years"]

    result = _pick_richer(NCT_INCLUSION, group_side)
    groups = [item for item in result if is_or_group(item)]

    assert len(NCT_INCLUSION) > len(group_side), "fixture must exercise the losing branch"
    assert len(groups) == 1, "the OR group was discarded for being outnumbered"
    assert len(or_group_alternatives(groups[0])) == 5
    assert _coverage_violations(result) == []


def test_the_invariant_fails_when_the_predicate_is_disabled(monkeypatch):
    """A guard on the guard.

    If the predicate ever silently degrades to "nothing is a duplicate", every
    assertion above still passes vacuously unless something proves the fixture
    can violate the invariant in the first place. Measured: four violations.

    Disabled via the ablation switch rather than by monkeypatching a name in
    enricher. The decision now has two entry points on this path -- the merge
    site's own call and the one inside criteria_dedup.prune_superseded -- and
    patching only enricher's binding left the sweep live, so the guard measured
    ZERO violations and would have passed vacuously for the rest of its life.
    The env var reaches every entry point by construction and cannot go stale
    when a call site is added. It also pins that the ablation arm genuinely
    reproduces the pre-fix behaviour rather than being a second code path.
    """
    monkeypatch.setenv(criteria_dedup._ABLATION_ENV, "1")
    result = _supplement_priority_merge(PDF_INCLUSION, NCT_INCLUSION)

    # The oracle is the same predicate, so it must be re-enabled before the
    # count is taken. Measuring inside the ablation reports zero violations for
    # the trivial reason that nothing is a duplicate when nothing is compared.
    monkeypatch.delenv(criteria_dedup._ABLATION_ENV)

    assert len(_coverage_violations(result)) == 4
