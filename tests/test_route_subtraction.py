"""Turning a route qualifier into concept-set subtractions.

The two halves meet here. `route_qualifier` says what the criterion asked for,
`dose_form_route` says what each product is, and this decides which
ingredient-by-dose-form concepts to mark `isExcluded`.

See omx_wiki/route-of-administration-overreach.md.
"""
import pytest

from src.services.route_qualifier import detect_route_qualifiers
from src.services.route_subtraction import (
    DrugForm,
    compute_route_subtraction,
    routes_to_keep,
)


def _forms(*pairs):
    """(concept_id, dose form) -> DrugForm list, names derived."""
    return [DrugForm(concept_id=cid, concept_name=f"prednisolone {form}", dose_form=form)
            for cid, form in pairs]


class TestRoutesToKeep:

    def test_systemic_keeps_every_systemic_route(self):
        keep = routes_to_keep(detect_route_qualifiers("systemic corticosteroids"))
        assert keep == {"oral", "injection", "rectal", "sublingual", "transdermal", "dialysis"}

    def test_a_named_route_keeps_only_that_route(self):
        """"oral anticoagulants" excludes injectable ones too, though both are
        systemic. PLATO means warfarin, not heparin."""
        assert routes_to_keep(detect_route_qualifiers("Oral anticoagulation therapy")) == {"oral"}

    def test_several_named_routes_are_unioned(self):
        keep = routes_to_keep(detect_route_qualifiers("oral or intravenous corticosteroids"))
        assert keep == {"oral", "injection"}

    def test_a_named_route_wins_over_the_systemic_intent(self):
        """"systemic" is the looser statement; if the text also names a route,
        the route is what was asked for."""
        keep = routes_to_keep(detect_route_qualifiers("systemic oral corticosteroids"))
        assert keep == {"oral"}

    def test_no_qualifier_means_no_subtraction(self):
        assert routes_to_keep(detect_route_qualifiers("Type 1 diabetes mellitus")) is None


class TestSubtraction:

    def test_forms_outside_the_kept_routes_are_excluded(self):
        forms = _forms((1, "Oral Tablet"), (2, "Topical Cream"), (3, "Ophthalmic Solution"))
        result = compute_route_subtraction(forms, keep_routes={"oral"})
        assert {c.concept_id for c in result.excluded} == {2, 3}

    def test_kept_forms_are_left_alone(self):
        forms = _forms((1, "Oral Tablet"), (2, "Oral Capsule"))
        result = compute_route_subtraction(forms, keep_routes={"oral"})
        assert result.excluded == []

    def test_a_systemic_route_that_was_not_asked_for_is_still_excluded(self):
        """Injectable is systemic, but "oral" did not ask for it."""
        forms = _forms((1, "Oral Tablet"), (2, "Injectable Solution"))
        result = compute_route_subtraction(forms, keep_routes={"oral"})
        assert {c.concept_id for c in result.excluded} == {2}

    def test_undecidable_forms_are_reported_not_excluded(self):
        """"Prefilled Applicator" may be vaginal, rectal or topical. Excluding it
        on a guess is the bug this exists to prevent; leaving it in preserves the
        status quo, which is at least the state everything was measured against."""
        forms = _forms((1, "Oral Tablet"), (2, "Prefilled Applicator"))
        result = compute_route_subtraction(forms, keep_routes={"oral"})
        assert result.excluded == []
        assert [c.concept_id for c in result.undecidable] == [2]

    def test_a_form_missing_from_the_dictionary_is_undecidable_too(self):
        forms = _forms((1, "Oral Tablet"), (2, "Something The Vocabulary Added Later"))
        result = compute_route_subtraction(forms, keep_routes={"oral"})
        assert result.excluded == []
        assert [c.concept_id for c in result.undecidable] == [2]

    def test_empty_keep_routes_subtracts_nothing(self):
        """A caller with no qualifier must not accidentally subtract everything."""
        forms = _forms((1, "Oral Tablet"), (2, "Topical Cream"))
        assert compute_route_subtraction(forms, keep_routes=None).excluded == []


class TestTheCarolinaCase:

    def test_systemic_corticosteroids_drops_the_local_forms(self):
        qualifier = detect_route_qualifiers("Systemic corticosteroids")
        keep = routes_to_keep(qualifier)
        forms = _forms(
            (1, "Oral Tablet"), (2, "Injectable Solution"), (3, "Rectal Suppository"),
            (4, "Topical Ointment"), (5, "Ophthalmic Solution"), (6, "Otic Solution"),
            (7, "Nasal Spray"), (8, "Medicated Shampoo"), (9, "Prefilled Applicator"),
        )
        result = compute_route_subtraction(forms, keep_routes=keep)
        assert {c.concept_id for c in result.excluded} == {4, 5, 6, 7, 8}
        assert [c.concept_id for c in result.undecidable] == [9]

    def test_rectal_survives_because_it_is_absorbed(self):
        keep = routes_to_keep(detect_route_qualifiers("Systemic corticosteroids"))
        result = compute_route_subtraction(_forms((1, "Rectal Suppository")), keep_routes=keep)
        assert result.excluded == []
