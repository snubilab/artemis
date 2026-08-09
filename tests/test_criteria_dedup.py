"""What counts as "already represented" when one side carries an OR group.

ARISTOTLE's protocol lists five stroke risk factors as alternatives -- any one
qualifies. The parser collapses them correctly into a single [OR-GROUP]. The
enricher then re-added the same five clauses from ClinicalTrials.gov as separate
top-level criteria, because whole-string similarity cannot see that a 66-char
alternative is stated inside a 330-char group. Circe ANDs top-level rules, so a
patient had to satisfy every risk factor at once and the cohort came back empty
against a gold standard of 1,113 patients.

Scores in the comments are the measured coverage for that case.
"""
import pytest

from src.agents.agent1.criteria_dedup import (
    _ABLATION_ENV,
    dedup_enabled,
    is_or_group,
    or_group_alternatives,
    restates_or_group_alternative,
)


ARISTOTLE_GROUP = (
    "[OR-GROUP] 3) One or more of the following risk factor(s) for stroke "
    "with any of: Age 75 years or older | Prior stroke, TIA or systemic "
    "embolus | Either symptomatic congestive heart failure within 3 months "
    "or left ventricular dysfunction with an LV ejection fraction (LVEF) "
    "≤ 40% by echocardiography, radionuclide study or contrast "
    "angiography | Diabetes mellitus | Hypertension requiring "
    "pharmacological treatment"
)

# The same clause list as ClinicalTrials.gov states it -- four alternatives,
# one fewer than the protocol, and worded differently.
ARISTOTLE_CTGOV_GROUP = (
    "[OR-GROUP] Males and females ≥ 18 yrs with atrial fibrillation (AF) and "
    "one or more of the following risk factors for stroke "
    "with any of: Age ≥ 75, previous stroke | transient ischemic attack (TIA) "
    "or Systemic Embolism (SE) | Symptomatic congestive heart failure or left "
    "ventricular dysfunction with left ventricular ejection fraction (LVEF) "
    "≤ 40% | Diabetes mellitus or hypertension requiring pharmacological treatment"
)


class TestRestatement:
    """Candidates the group already offers as an alternative."""

    @pytest.mark.parametrize("candidate", [
        # The four real ClinicalTrials.gov clauses. These are the ones that
        # became AND-ed top-level rules and emptied the cohort.
        "Age ≥ 75, previous stroke",                                          # 0.750
        "transient ischemic attack (TIA) or Systemic Embolism (SE)",          # 0.857
        "Symptomatic congestive heart failure or left ventricular dysfunction "
        "with left ventricular ejection fraction (LVEF) ≤ 40%",               # 1.000
        "Diabetes mellitus or hypertension requiring pharmacological treatment",  # 1.000
        # Paraphrases. An LLM re-parsing the same text is not asked to copy it
        # verbatim, so exact containment would miss all three.
        "Diabetes mellitus or hypertension requiring pharmacologic treatment",  # 1.000
        "Prior stroke, TIA, or systemic embolus",                             # 1.000
        "Symptomatic congestive heart failure or LV dysfunction with LVEF <= 40%",  # 1.000
        "LVEF <= 40%",                                                        # 1.000
    ])
    def test_should_drop_when_candidate_restates_an_alternative(self, candidate):
        assert restates_or_group_alternative(candidate, [ARISTOTLE_GROUP])


class TestMandatoryCriteriaSurvive:
    """The group header carries requirements, not alternatives.

    "Males and females >= 18 yrs with atrial fibrillation (AF) and one or more
    of the following..." states two mandatory conditions before it opens the
    list. Comparing against the whole group line -- the rejected naive
    containment guard -- drops both, and the cohort silently widens to patients
    without atrial fibrillation.
    """

    @pytest.mark.parametrize("candidate", [
        "Atrial fibrillation (AF)",     # 0.000
        "Males and females >= 18 yrs",  # 0.000
        "Age ≥ 18 years",               # 0.333
        "* Males and females ≥ 18 yrs with atrial fibrillation (AF) and one or "
        "more of the following risk factors for stroke:",   # 0.091
    ])
    def test_should_keep_when_candidate_is_a_mandatory_and_criterion(self, candidate):
        assert not restates_or_group_alternative(candidate, [ARISTOTLE_GROUP])


class TestDiscrimination:
    """Near-misses that must not be swallowed."""

    @pytest.mark.parametrize("candidate", [
        "LVEF <= 35%",              # 0.667 -- a different threshold is a different criterion
        "Age >= 65 years",          # 0.333
        # This one killed the competing design: its child-match fired because
        # the group contains "Diabetes mellitus", so every diabetes trial in the
        # corpus lost its type-1 exclusion.
        "Type 1 diabetes mellitus",  # 0.667
        "eGFR < 15 mL/min/1.73m2",   # 0.000
    ])
    def test_should_keep_when_the_candidate_says_something_else(self, candidate):
        assert not restates_or_group_alternative(candidate, [ARISTOTLE_GROUP])


class TestPolarity:
    """A negated candidate is not a restatement of a positive alternative.

    _STOPWORDS discards no/not/either/both, so "No prior stroke, TIA or systemic
    embolus" tokenises identically to the positive clause the group already
    offers and was deleted. Deleting an exclusion WIDENS the cohort silently --
    the opposite direction from the empty-cohort bug and much harder to notice,
    because no test asserts on a patient count that went up.
    """

    @pytest.mark.parametrize("candidate", [
        "No prior stroke, TIA or systemic embolus",
        "Patients must not have diabetes mellitus",
        "Absence of diabetes mellitus",
        "Patients without hypertension requiring pharmacological treatment",
        "Free of congestive heart failure",
        "Neither diabetes mellitus nor hypertension",
        "Excluding patients with LVEF <= 40%",
        "Negative for diabetes mellitus",
    ])
    def test_should_keep_when_the_candidate_negates_an_alternative(self, candidate):
        assert not restates_or_group_alternative(candidate, [ARISTOTLE_GROUP])

    def test_should_drop_when_a_negated_candidate_matches_a_negated_alternative(self):
        """Polarity is a match rule, not a veto. Two negatives still deduplicate."""
        group = (
            "[OR-GROUP] Any of the following disqualifiers with any of: "
            "No prior stroke, TIA or systemic embolus | Not receiving anticoagulation"
        )

        assert restates_or_group_alternative("No prior stroke, TIA or systemic embolus", [group])


class TestConjunction:
    """Requiring BOTH alternatives is a different criterion from offering either.

    "and" is a stopword, so the conjunction tokenises identically to the
    disjunction. The or-form genuinely restates two alternatives the group
    already offers and must still be dropped; the and-form narrows the cohort
    and must survive.
    """

    def test_should_drop_when_the_candidate_disjoins_two_alternatives(self):
        assert restates_or_group_alternative(
            "Diabetes mellitus or hypertension requiring pharmacological treatment",
            [ARISTOTLE_GROUP],
        )

    def test_should_keep_when_the_candidate_conjoins_two_alternatives(self):
        assert not restates_or_group_alternative(
            "Diabetes mellitus and hypertension requiring pharmacological treatment",
            [ARISTOTLE_GROUP],
        )

    # Keying the gate on the single token "and" let every other protocol spelling
    # through, and an unrecognised conjunction is DELETED, not retained -- so this
    # is parametrised over spellings rather than pinned to one.
    @pytest.mark.parametrize("joiner", [
        "and", "plus", "as well as", "combined with", "together with",
        "along with", "in addition to", "accompanied by",
    ])
    def test_should_keep_when_the_candidate_conjoins_with_any_spelling(self, joiner):
        assert not restates_or_group_alternative(
            f"Diabetes mellitus {joiner} hypertension requiring pharmacological treatment",
            [ARISTOTLE_GROUP],
        )

    def test_should_drop_when_a_disjunction_also_carries_a_conjunction_word(self):
        """"A and B or C" stays disjunctive: an explicit "or" outranks the marker."""
        assert restates_or_group_alternative(
            "Prior stroke and prior TIA or prior systemic embolus",
            [ARISTOTLE_GROUP],
        )


class TestShortAlternatives:
    """A verbatim alternative is recognised however few tokens it carries.

    "Prior stroke" is literally one of the group's alternatives, but "prior" is a
    stopword, leaving one content token -- below MIN_CONTENT_TOKENS, so coverage
    is 0.0. The normalised-identity gate handles it instead, and that gate is
    floor-free, so no relaxation of MIN_CONTENT_TOKENS is needed to satisfy this.

    Relaxing the floor to 1 was tried and reverted: it changed no verdict in the
    negation/conjunction probe set, and it silently deleted the bare criteria
    "Hypertension", "Diabetes" and "Stroke" against this very group. A one-token
    candidate that is NOT verbatim must survive -- see the companion test below.
    """

    SHORT_GROUP = (
        "[OR-GROUP] One or more risk factors with any of: Prior stroke | "
        "Diabetes mellitus | Hypertension"
    )

    @pytest.mark.parametrize("candidate", [
        "Prior stroke",       # verbatim alternative
        "prior  stroke.",     # same after normalisation
        "Hypertension",       # verbatim, single token
    ])
    def test_should_drop_when_the_candidate_is_a_verbatim_alternative(self, candidate):
        assert restates_or_group_alternative(candidate, [self.SHORT_GROUP])

    @pytest.mark.parametrize("candidate", [
        "Previous stroke",    # paraphrase, not verbatim -- must not be deleted on one token
        "stroke",             # bare fragment of a longer alternative
        "Diabetes",           # bare fragment of "Diabetes mellitus"
    ])
    def test_should_keep_when_a_one_token_candidate_is_not_verbatim(self, candidate):
        assert not restates_or_group_alternative(candidate, [self.SHORT_GROUP])

    @pytest.mark.parametrize("candidate", [
        "No prior stroke",
        "Patients with no stroke",
        "Hemorrhagic stroke",        # 0.50 coverage -- the THRESHOLD protects this, not the floor
        "Gestational diabetes",
        "Type 1 diabetes mellitus",
        "Uncontrolled hypertension",
        "Pregnancy",
    ])
    def test_should_keep_when_a_short_candidate_says_something_else(self, candidate):
        assert not restates_or_group_alternative(candidate, [self.SHORT_GROUP])

    def test_should_drop_when_the_candidate_is_normalised_identical_to_an_alternative(self):
        """Threshold-free and floor-free: the same oracle the invariant test uses.

        tests/test_and_explosion_invariant._identity_violations already declares
        normalised identity a violation the predicate could not detect. That gap
        IS this defect, so the predicate now mirrors the oracle.
        """
        group = "[OR-GROUP] header with any of: Age 75 years or older | Diabetes mellitus"

        assert restates_or_group_alternative("  age 75 years or older.  ", [group])


class TestScoping:
    """The predicate is inert unless an OR group is actually present."""

    def test_should_return_false_when_no_or_group_is_present(self):
        """A literal substring of a flat item is still not a restatement.

        Without this scoping the LLM fallback would start losing items in
        ordinary criteria lists, where one criterion routinely contains
        another's wording.
        """
        flat = [
            "Patients must have established cardiovascular disease including "
            "prior myocardial infarction or stroke or asymptomatic cardiac "
            "ischemia or chronic heart failure with NYHA class II through III"
        ]

        assert "asymptomatic cardiac ischemia" in flat[0].lower()
        assert not restates_or_group_alternative("Asymptomatic cardiac ischemia", flat)

    def test_should_never_discard_an_or_group_candidate(self):
        """A richer group must not be dropped against a poorer one.

        Measured without the exemption: the 5-alternative protocol group scores
        0.722 against the 4-alternative registry group and is discarded --
        destroying exactly the structure this module exists to protect.
        """
        assert is_or_group(ARISTOTLE_GROUP)
        assert not restates_or_group_alternative(ARISTOTLE_GROUP, [ARISTOTLE_CTGOV_GROUP])


class TestAblationSwitch:
    """The control arm must be opt-in and impossible to enter by accident."""

    def test_should_deduplicate_by_default(self, monkeypatch):
        monkeypatch.delenv(_ABLATION_ENV, raising=False)

        assert dedup_enabled()
        assert restates_or_group_alternative("LVEF <= 40%", [ARISTOTLE_GROUP])

    def test_should_disable_only_for_the_exact_opt_in_value(self, monkeypatch):
        monkeypatch.setenv(_ABLATION_ENV, "1")

        assert not dedup_enabled()
        assert not restates_or_group_alternative("LVEF <= 40%", [ARISTOTLE_GROUP])

    @pytest.mark.parametrize("value", ["", "0", "false", "true", "yes", "2"])
    def test_should_stay_enabled_for_any_other_value(self, monkeypatch, value):
        """A typo in the ablation variable must not silently disable production."""
        monkeypatch.setenv(_ABLATION_ENV, value)

        assert dedup_enabled()


class TestWireFormat:
    """Parsing the [OR-GROUP] string back into its parts."""

    def test_should_expose_the_alternatives_without_the_header(self):
        alternatives = or_group_alternatives(ARISTOTLE_GROUP)

        assert len(alternatives) == 5
        assert alternatives[0] == "Age 75 years or older"
        assert not any("One or more of the following" in a for a in alternatives)

    @pytest.mark.parametrize("item", [
        "Age ≥ 18 years",
        "[OR-GROUP] a header with no join marker",
        "",
    ])
    def test_should_report_no_alternatives_for_a_plain_criterion(self, item):
        assert or_group_alternatives(item) == []
        assert not is_or_group(item)
