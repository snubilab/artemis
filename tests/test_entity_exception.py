"""Reading an entity exclusion out of a criterion's own words.

The entity axis of what `route_qualifier` does for routes: the criterion names a
set and then names part of it to leave out. Measured on the 2026-09-14 delivery,
no concept set the pipeline has ever produced carries an excluded member -- 0
`isExcluded` items across 514 sets in all 12 files -- while gold carries 718
across 59 of its 469 sets. Twenty of our sets are named with a negation and every
one is a plain inclusive set.

The corpus this is fitted to is the ten distinct negation-named concept sets in
`output/site_gap/2026-09-14/DELIVERY/`, plus the store descriptions behind them.
Six of the ten must be DECLINED, and every one of those six declines for the same
reason: a hyphenated `non-X` is part of a term, not a connective. Splitting on it
would wreck `non-familial medullary thyroid carcinoma`,
`Non-ST-segment elevation myocardial infarction`, `Unreliable/Non-compliant`,
`life expectancy less than 5 years for non-CV causes` -- and it would mangle the
excepted phrase of the one case that matters most, `cancer other than
**non-melanoma** skin cancer`.
"""
import pytest

from src.services.entity_exception import detect_entity_exception


class TestTheTwoRealCases:
    """Both taken verbatim from the delivered files."""

    def test_leader_insulin_other_than_human_nph_insulin(self):
        """codeset 54, whose 26 members are byte-identical to codeset 12
        'human NPH insulin' -- the phrase resolved to its own complement."""
        found = detect_entity_exception("insulin other than human NPH insulin")
        assert found is not None
        assert found.base == "insulin"
        assert found.excepted == ["human NPH insulin"]

    def test_carolina_cancer_other_than_non_melanoma_skin_cancer(self):
        """codeset 45. The excepted phrase carries a hyphenated `non-`, which is
        part of the term and must survive the split intact."""
        found = detect_entity_exception("cancer other than non-melanoma skin cancer")
        assert found is not None
        assert found.base == "cancer"
        assert found.excepted == ["non-melanoma skin cancer"]


class TestTheRestOfTheDeliveredCorpus:

    def test_premixed_insulin(self):
        found = detect_entity_exception("insulin other than premixed insulin")
        assert found is not None and found.base == "insulin"
        assert found.excepted == ["premixed insulin"]

    def test_long_acting_insulin_analogue(self):
        found = detect_entity_exception("insulin other than long-acting insulin analogue")
        assert found is not None and found.base == "insulin"
        assert found.excepted == ["long-acting insulin analogue"]

    def test_parenthesised_except(self):
        found = detect_entity_exception("Uncontrolled endocrine disorder (except T2DM)")
        assert found is not None
        assert found.base == "Uncontrolled endocrine disorder"
        assert found.excepted == ["T2DM"]

    def test_parenthesised_excluding_is_case_insensitive(self):
        found = detect_entity_exception("Cancer diagnosis (excluding basal cell carcinoma)")
        assert found is not None
        assert found.base == "Cancer diagnosis"
        assert found.excepted == ["basal cell carcinoma"]

    def test_a_slash_list_of_excepted_entities_splits(self):
        found = detect_entity_exception("Drug Naive or Pre-treated (Excluding GLP-1/DPP-4/SGLT-2)")
        assert found is not None
        assert found.excepted == ["GLP-1", "DPP-4", "SGLT-2"]


class TestWhatMustBeDeclined:
    """Six of the ten delivered negation-named sets, and why each one is not a
    set exception. A decline leaves the current over-inclusion in place; a wrong
    split invents a new exclusion, which is the failure this exists to prevent."""

    @pytest.mark.parametrize("name", [
        "non-familial medullary thyroid carcinoma",
        "Non-ST-segment elevation myocardial infarction",
        "Unreliable/Non-compliant",
        "life expectancy less than 5 years for non-CV causes",
        "Use of intermediate-acting insulin (non-NPH)",
    ])
    def test_a_hyphenated_non_is_part_of_the_term(self, name):
        assert detect_entity_exception(name) is None

    def test_less_than_is_a_comparison_not_an_exception(self):
        assert detect_entity_exception("life expectancy less than 5 years") is None

    def test_rather_than_is_not_other_than(self):
        assert detect_entity_exception("treated with metformin rather than insulin") is None

    def test_not_inside_a_conjunction_is_not_a_set_exception(self):
        name = ("Hospitalized for ACS with onset , ischemic symptoms >=10 min "
                "duration at rest, not pregnant, and informed consent")
        assert detect_entity_exception(name) is None

    def test_a_non_adjacent_other_and_than_is_not_the_connective(self):
        assert detect_entity_exception(
            "has any other condition than mentioned by the investigator") is None


class TestAnaphoraIsUndecidable:
    """The excepted phrase points back at protocol text this module cannot see.
    Mapping "specified types" would return whatever the embedder thinks those
    two words mean, which is worse than not subtracting at all."""

    @pytest.mark.parametrize("name", [
        "Use of insulin other than specified types within 3 months",
        "Other antidiabetic drugs (excluding allowed short-term insulin)",
        "cancer other than the above",
        "drugs other than those listed",
    ])
    def test_an_anaphoric_excepted_phrase_is_declined(self, name):
        assert detect_entity_exception(name) is None


class TestEdges:

    def test_empty_text(self):
        assert detect_entity_exception("") is None
        assert detect_entity_exception(None) is None

    def test_an_empty_base_is_declined(self):
        assert detect_entity_exception("other than premixed insulin") is None

    def test_a_trailing_temporal_clause_is_stripped_from_the_excepted_phrase(self):
        """The store's sourceText for CAROLINA's criterion carries one."""
        found = detect_entity_exception(
            "cancer other than non-melanoma skin cancer within last 3 years")
        assert found is not None
        assert found.excepted == ["non-melanoma skin cancer"]

    def test_an_overlong_excepted_phrase_is_declined(self):
        assert detect_entity_exception(
            "cancer other than a lesion the investigator judges to be of no "
            "clinical consequence whatsoever") is None


class TestFoundByRunningItOverTheCorpusRatherThanOverFixtures:
    """Both of these were written after the parser was green on the two real
    cases and then run over every negation-family string in the store. Neither
    shape was invented."""

    def test_a_comma_list_ending_in_or_does_not_keep_the_conjunction(self):
        """Store s4/s5/s6 conceptSetName. The `, or ` join left a third entity
        literally named 'or premixed insulin', which maps to nothing."""
        found = detect_entity_exception(
            "Insulin other than human NPH, long-acting analogue, or premixed insulin")
        assert found is not None
        assert found.excepted == ["human NPH", "long-acting analogue", "premixed insulin"]

    @pytest.mark.parametrize("label", [
        "Unreliable/Non-compliant + Life Expectancy < 5 years + Cancer other than\n"
        "nonmelanoma skin cancer",
        "Insulin other than human NPH insulin + Insulin other than long-acting\n"
        "insulin analogue + Insulin other than premixed insulin",
        "Cancer diagnosis (excluding basal cell carcinoma) + Basal cell carcinoma exclusion",
    ])
    def test_a_plus_joined_group_label_is_not_a_concept_set_name(self, label):
        """` + ` joins several criteria into one group label. Its base would be
        'A + B + Cancer', which names no entity a mapper can resolve."""
        assert detect_entity_exception(label) is None
