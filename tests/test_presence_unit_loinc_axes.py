"""Classifying a widened lab set by its members' LOINC axes instead of by allowlisted ids.

THE MOTIVATING EVENT. d97397e widened CAROLINA's eGFR, UACR and LDL concept sets with valid
LOINC siblings (the CKD-EPI 2021 and cystatin-C eGFR codes, the '[Ratio]' microalbumin
codes, LDL by VAP). None is in ``PRESENCE_UNIT_ANALYTES``, so on the 2026-10-08 dry rebuild
every one of those sets classified ``unlisted`` and its presence kept a ``Unit`` filter.

THE RULE UNDER TEST. An unlisted member is admitted when its LOINC axes -- component,
property, system, scale, time aspect -- are identical to those of an allowlisted member of
the same analyte in the same set. It is then the same measurement as an already-analysed
member, reported on the same scale, so the analyte's residual-risk table covers it. No
concept id is added anywhere.

WHY NOT PROPERTY VERIFICATION ALONE, as first proposed. Two measured counterexamples:
HbA1 total 3005446 is 'Mass fraction', exactly what '%' verifies, and it is the confusable
the HbA1c sets must NOT admit; and the UACR units ug/mg and mg/g name no LOINC property in
``loinc_specimen`` (deliberately -- see ``_PROPERTY_FAMILIES_BY_DIMENSIONS``), so
verification declines every UACR set. Axes are taken from ``omop_vocab`` (synthea23m),
2026-10-08, via ``PostgresLabTestVocabulary.lab_tests``.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.utils.presence_unit_allowlist import (  # noqa: E402
    classify_concepts,
    unit_drop_verdict,
)

PT = "Point in time (spot)"
EGFR_AXES = ("Glomerular filtration rate", "Volume Rate/Area", "Serum, Plasma or Blood", "Qn", PT)
#: CAROLINA codeset 24 'eGFR' on the dry rebuild: four allowlisted seeds, eleven not.
EGFR_LISTED = [3049187, 36303797, 40764999, 46236952]
EGFR_UNLISTED = [1619025, 1619026, 3029829, 3029859, 3030104, 3053283, 3965919, 36306178,
                 36660257, 40771922, 42869913]
#: CAROLINA codeset 25 'Urinary albumin creatinine ratio'.
UACR_AXES = {
    3001802: ("Albumin/Creatinine", "Mass Ratio", "Urine", "Qn", PT),
    3020682: ("Albumin/Creatinine", "Ratio", "Urine", "Qn", PT),
    3034485: ("Albumin/Creatinine", "Mass Ratio", "Urine", "Qn", PT),
    1175719: ("Albumin/Creatinine", "Ratio", "Urine", "Qn", PT),
    3022826: ("Albumin/Creatinine", "Ratio", "Urine", "Qn", PT),
    46235434: ("Albumin/Creatinine", "Ratio", "Urine", "Qn", PT),
}
LDL_MASS = ("Cholesterol in LDL", "Mass Concentration", "Serum or Plasma", "Qn", PT)
#: CAROLINA codeset 30 'LDL cholesterol' after the confusable repair; 4041556 is SNOMED.
LDL_AXES = {3009966: LDL_MASS, 3028288: LDL_MASS, 3028437: LDL_MASS, 3053341: LDL_MASS,
            36031404: LDL_MASS, 40758569: LDL_MASS}
LDL_SNOMED = 4041556
#: LDL on a third scale nobody modelled -- the allowlist's own documented decline.
LDL_UNITS_PER_VOLUME = 3035009
LDL_ARBITRARY = ("Cholesterol in LDL", "Arbitrary Concentration", "Serum or Plasma", "Qn", PT)

HBA1C_FRACTION = ("Hemoglobin A1c/Hemoglobin.total", "Mass fraction", "Blood", "Qn", PT)
HBA1_TOTAL = 3005446
HBA1_FRACTION = ("Hemoglobin A1/Hemoglobin.total", "Mass fraction", "Blood", "Qn", PT)


def egfr_axes() -> dict:
    return {cid: EGFR_AXES for cid in EGFR_LISTED + EGFR_UNLISTED}


# ---------------------------------------------------------------------------
# the three widened CAROLINA sets
# ---------------------------------------------------------------------------

def test_should_classify_the_widened_egfr_set_as_egfr_when_every_sibling_shares_a_listed_axes():
    result = classify_concepts(EGFR_LISTED + EGFR_UNLISTED, egfr_axes())

    assert (result.status, result.analyte and result.analyte.name) == ("ok", "eGFR")


def test_should_classify_the_widened_uacr_set_when_the_ratio_siblings_match_a_listed_ratio_code():
    result = classify_concepts(UACR_AXES, UACR_AXES)

    assert result.status == "ok"
    assert result.analyte.name == "urine albumin/creatinine"


def test_should_classify_the_widened_ldl_set_when_the_vap_code_matches_a_listed_mass_code():
    result = classify_concepts([*LDL_AXES, LDL_SNOMED], LDL_AXES)

    assert result.status == "ok"
    assert result.analyte.name == "LDL cholesterol"


def test_should_allow_dropping_the_unit_when_the_widened_set_and_its_bound_can_only_miss():
    verdict = unit_drop_verdict(EGFR_LISTED + EGFR_UNLISTED, {"Value": 30.0, "Op": "gte"},
                                egfr_axes())

    assert verdict.allowed, verdict.why


# ---------------------------------------------------------------------------
# controls: members that must still keep the set unlisted
# ---------------------------------------------------------------------------

def test_should_stay_unlisted_when_no_axes_are_supplied():
    """The DB-free path -- what the lint sees today -- is unchanged."""
    assert classify_concepts(EGFR_LISTED + EGFR_UNLISTED).status == "unlisted"


def test_should_stay_unlisted_when_an_unlisted_member_has_no_lab_test_axes():
    axes = egfr_axes()
    del axes[EGFR_UNLISTED[0]]

    assert classify_concepts(EGFR_LISTED + EGFR_UNLISTED, axes).status == "unlisted"


def test_should_stay_unlisted_when_the_member_is_the_right_analyte_on_an_unmodelled_scale():
    axes = {**LDL_AXES, LDL_UNITS_PER_VOLUME: LDL_ARBITRARY}

    assert classify_concepts([*LDL_AXES, LDL_UNITS_PER_VOLUME], axes).status == "unlisted"


def test_should_stay_unlisted_when_a_confusable_shares_the_property_but_not_the_component():
    """HbA1 total passes '%' property verification; it must not pass this."""
    axes = {3004410: HBA1C_FRACTION, 3007263: HBA1C_FRACTION, HBA1_TOTAL: HBA1_FRACTION}

    assert classify_concepts([3004410, 3007263, HBA1_TOTAL], axes).status == "unlisted"


def test_should_stay_unlisted_when_the_only_listed_member_has_no_axes_to_match():
    """A SNOMED anchor carries no LOINC axes, so it vouches for nothing."""
    assert classify_concepts([LDL_SNOMED, 40758569], {40758569: LDL_MASS}).status == "unlisted"
