"""Route classification for OMOP Dose Form concepts.

Background: an exclusion criterion reading "systemic corticosteroids" was built
from RxNorm Ingredients with includeDescendants, which pulled in 2,667 topical
and 1,157 ophthalmic products — prednisolone eye drops disqualified a patient.
Route is not guessable from the drug name but IS carried structurally, via
`RxNorm has dose form`. These tests pin the classifier that reads it.

See omx_wiki/route-of-administration-overreach.md.
"""
import pytest

from src.services.dose_form_route import classify_dose_form


class TestRouteDetection:
    """Route is a factual attribute read off the dose form's name."""

    @pytest.mark.parametrize("name,expected", [
        ("Oral Tablet", "oral"),
        ("Delayed Release Oral Tablet", "oral"),
        ("Injectable Solution", "injection"),
        ("Prefilled Syringe", "injection"),
        ("Topical Cream", "topical"),
        ("Topical Ointment", "topical"),
        ("Ophthalmic Solution", "ophthalmic"),
        ("Ophthalmic Ointment", "ophthalmic"),
        ("Rectal Suppository", "rectal"),
        ("Transdermal Patch", "transdermal"),
        ("Metered Dose Inhaler", "inhalation"),
        ("Nasal Spray", "nasal"),
        ("Vaginal Cream", "vaginal"),
        ("Sublingual Tablet", "sublingual"),
    ])
    def test_route_is_detected_from_the_name(self, name, expected):
        assert expected in classify_dose_form(name).routes

    def test_a_form_naming_several_routes_keeps_all_of_them(self):
        """"Ear and eye drops" is genuinely both, and both are local."""
        result = classify_dose_form("Ear and eye and nose drops")
        assert {"otic", "ophthalmic", "nasal"} <= set(result.routes)

    def test_a_form_with_no_route_in_its_name_is_unknown_not_defaulted(self):
        """Silently defaulting "Powder" to oral is how the original bug reads."""
        result = classify_dose_form("Powder")
        assert result.routes == []
        assert result.systemic is None


class TestSystemicJudgement:
    """Systemic-ness is a clinical mapping applied on top of the route."""

    @pytest.mark.parametrize("name", [
        "Oral Tablet", "Injectable Solution", "Rectal Suppository",
        "Sublingual Tablet", "Transdermal Patch",
    ])
    def test_forms_that_reach_the_bloodstream_are_systemic(self, name):
        assert classify_dose_form(name).systemic is True

    @pytest.mark.parametrize("name", [
        "Topical Cream", "Ophthalmic Solution", "Otic Solution",
        "Vaginal Cream", "Medicated Shampoo",
    ])
    def test_locally_acting_forms_are_not_systemic(self, name):
        assert classify_dose_form(name).systemic is False

    def test_transdermal_beats_topical(self):
        """A patch matches both words. It delivers systemically; a cream does not."""
        patch = classify_dose_form("24 Hour Transdermal Patch")
        assert "transdermal" in patch.routes
        assert patch.systemic is True

    def test_any_systemic_route_makes_the_form_systemic(self):
        """A form usable orally and rectally is systemic on both counts."""
        assert classify_dose_form("Concentrate for oral and rectal solution").systemic is True

    def test_inhalation_is_not_systemic(self):
        """CAROLINA: "inhaled use of steroids ... is no exclusion criterion"."""
        assert classify_dose_form("Metered Dose Inhaler").systemic is False


class TestTheCriterionThatStartedThis:

    def test_prednisolone_eye_drops_are_not_a_systemic_corticosteroid(self):
        assert classify_dose_form("Ophthalmic Solution").systemic is False

    def test_hydrocortisone_cream_is_not_a_systemic_corticosteroid(self):
        assert classify_dose_form("Topical Cream").systemic is False

    def test_prednisone_oral_tablet_is(self):
        assert classify_dose_form("Oral Tablet").systemic is True
