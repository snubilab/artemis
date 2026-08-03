"""Route qualifiers stated in eligibility criteria prose.

The dose-form dictionary answers "what route is this product". This answers the
other half: "what route did the criterion ask for". A criterion reading
"systemic corticosteroids" must not resolve to every form of the drug.

The lexicon deliberately covers every route the dose-form dictionary knows,
not only the ones our six cardiovascular/diabetes trials happen to use. Those
six yield `systemic` and `oral` and nothing else; a dermatology or respiratory
protocol would lean on `topical` and `inhaled`, and the detector has to be ready
for that rather than fitted to the sample.

See omx_wiki/route-of-administration-overreach.md.
"""
import pytest

from src.services.route_qualifier import detect_route_qualifiers


class TestQualifiersSeenInOurCorpus:
    """The ones that actually occur in the six studies, verbatim.

    "systemic" arrives as an intent rather than a route -- see
    TestSystemicIsNotARoute -- so it is asserted on a different field.
    """

    @pytest.mark.parametrize("text", [
        "Systemic corticosteroids",
        "Current or planned systemic corticoid treatment",
        "Systemic steroids or thyroid hormone change",
    ])
    def test_corpus_systemic_criteria_are_detected(self, text):
        assert detect_route_qualifiers(text).systemic_intent is True

    @pytest.mark.parametrize("text", [
        "Oral anticoagulation therapy",
        "Direct Oral Anticoagulants (DOACs)",
    ])
    def test_corpus_oral_criteria_are_detected(self, text):
        assert "oral" in detect_route_qualifiers(text).qualifiers


class TestQualifiersAbsentFromOurCorpus:
    """Zero occurrences in the six studies. Still must work -- this is research,
    and the next protocol is not required to resemble these six."""

    @pytest.mark.parametrize("text,expected", [
        ("inhaled corticosteroids for asthma", "inhalation"),
        ("nebulised bronchodilator therapy", "inhalation"),
        ("topically applied steroid preparations", "topical"),
        ("cutaneous application of calcineurin inhibitors", "topical"),
        ("ophthalmic beta-blocker eye drops", "ophthalmic"),
        ("intravitreal anti-VEGF injection", "ophthalmic"),
        ("ear drops containing an aminoglycoside", "otic"),
        ("intranasal corticosteroid spray", "nasal"),
        ("rectal mesalazine suppository", "rectal"),
        ("transdermal fentanyl patch", "transdermal"),
        ("intravaginal oestrogen pessary", "vaginal"),
        ("sublingual nitroglycerin", "sublingual"),
        ("buccal midazolam", "oromucosal"),
        ("intravesical BCG instillation", "urethral"),
        ("bladder irrigation with saline", "irrigation"),
        ("maintenance haemodialysis", "dialysis"),
    ])
    def test_routes_absent_from_the_corpus_are_still_covered(self, text, expected):
        assert expected in detect_route_qualifiers(text).qualifiers

    def test_every_route_the_dose_form_dictionary_knows_has_a_prose_form(self):
        """A route the dictionary can classify but the detector cannot name is a
        hole: the criterion could never ask for it."""
        from src.services.dose_form_route import _SYSTEMIC_BY_ROUTE
        from src.services.route_qualifier import covered_routes

        missing = set(_SYSTEMIC_BY_ROUTE) - covered_routes()
        assert not missing, f"routes with no prose lexicon: {sorted(missing)}"


class TestAbbreviations:

    @pytest.mark.parametrize("text,expected", [
        ("administered IV for more than 48 hours", "injection"),
        ("given PO twice daily", "oral"),
        ("IM depot antipsychotic", "injection"),
    ])
    def test_clinical_abbreviations_are_detected(self, text, expected):
        assert expected in detect_route_qualifiers(text).qualifiers

    def test_a_bare_capital_letter_pair_is_not_a_route(self):
        """"...PO Box", "...IV of the protocol" must not read as a route."""
        assert detect_route_qualifiers("described in section IV of the protocol").qualifiers == []


class TestSystemicIsNotARoute:

    def test_systemic_is_reported_separately_from_routes(self):
        """"systemic" names an intent, not a route. It selects routes rather than
        being one, so it must not be mistaken for oral."""
        result = detect_route_qualifiers("systemic corticosteroids")
        assert result.systemic_intent is True
        assert "oral" not in result.qualifiers

    def test_local_intent_is_the_mirror_image(self):
        result = detect_route_qualifiers("locally acting agents only")
        assert result.systemic_intent is False

    @pytest.mark.parametrize("text", [
        # verbatim from ARISTOTLE and EMPA-REG -- 3 of the corpus's 7 "systemic" hits
        "Prior stroke, TIA or systemic embolus",
        "TIA or Systemic Embolus",
        "Active systemic infection requiring hospitalisation",
        # the same word, same non-route sense, elsewhere in clinical prose
        "Systemic lupus erythematosus",
        "Systemic sclerosis with renal involvement",
        "Systemic inflammatory response syndrome",
        "Elevated systemic vascular resistance",
    ])
    def test_systemic_meaning_whole_body_is_not_a_route_qualifier(self, text):
        """"Systemic embolus" is an anatomy word. Reading it as a route would
        attach a dose-form filter to a stroke criterion."""
        assert detect_route_qualifiers(text).systemic_intent is None


class TestNoQualifier:

    def test_a_criterion_with_no_route_word_reports_none(self):
        result = detect_route_qualifiers("Type 1 diabetes mellitus")
        assert result.qualifiers == []
        assert result.systemic_intent is None
