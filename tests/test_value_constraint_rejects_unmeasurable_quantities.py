"""A threshold the OMOP value columns cannot hold is not a ``value_constraint``.

`parse_value_constraint` is the ONLY producer of the numbers in this class, and it
reaches the store on three independent paths, which is why the extraction prompt could
never own this:

1. ``annotate_value_constraints`` renders it next to the criterion line and
   ``NCT_DECOMPOSITION_PROMPT`` Rule 0 tells the model, in bold, to **copy each one
   verbatim and do not re-derive the numbers**;
2. ``NCTParser._repair_dropped_threshold`` (Step 8a) mechanically RE-ATTACHES it to a
   rule when the model omitted it;
3. ``_llm_match_dropped_threshold`` (Step 8b) assigns the same parsed constraints when
   8a cannot confirm a 1:1 count.

Measured: a system-prompt rule naming drug dose / disease duration / stenosis percentage
as disqualifying was added and ARISTOTLE re-extracted; ``aspirin > 165 mg/day`` came back
unchanged, because path 1 hands the model that exact JSON and path 2 would put it back
anyway. The number has to stop being produced.

What is at stake downstream: Circe silently DROPS a value condition on a table that
cannot read it (`CRITERIA_TYPE_VALUE_ATTRIBUTES` -- DrugExposure reads only Quantity,
ConditionOccurrence and ProcedureOccurrence read nothing), so the rule matched every
occurrence of its concept set while reading as filtered; since the emission-time refusal
landed, the criterion is dropped entirely instead. Either way the protocol's criterion is
lost, and it is lost because of a number that never belonged to it.

Every ``phrase`` below is a verbatim criterion line from the six-trial corpus.
"""
from __future__ import annotations

import pytest

from src.services.value_constraint import annotate_value_constraints, parse_value_constraints


def _one(phrase: str):
    got = parse_value_constraints(phrase)
    return got[0] if got else None


class TestADurationIsNotAMeasuredValue:
    """A time span the criterion is ABOUT, with no index anchor to make it a window."""

    @pytest.mark.parametrize(
        "phrase",
        [
            "Type 2 diabetes mellitus duration > 10 years at Visit 1a",
            "Severe comorbid condition with life expectancy of ≤ 1 year",
            "Patients considered unreliable by the investigator concerning the "
            "requirements for follow up during the study and/or compliance with study "
            "drug administration, have a life expectancy less than 5 years for non-CV causes",
            "Treatment (=> 7 consecutive days) with GLP-1 receptor agonists, other DPP-4 "
            "inhibitors or SGLT-2 inhibitors prior to informed consent",
        ],
    )
    def test_should_refuse_a_span_when_the_phrase_names_it_as_a_duration(self, phrase):
        assert parse_value_constraints(phrase) == []

    @pytest.mark.parametrize(
        "phrase,value",
        [
            ("Age >= 18 years", 18.0),
            ("Age ≥ 70 years (at Visit 1a)", 70.0),
        ],
    )
    def test_should_still_read_an_age_which_is_a_patient_attribute(self, phrase, value):
        vc = _one(phrase)
        assert vc is not None and vc.value == value


class TestAnAnatomicSeverityPercentageIsNotAMeasuredValue:
    """A figure describing a lesion on an image. No OMOP table has a column for it."""

    @pytest.mark.parametrize(
        "phrase",
        [
            "Prior coronary, carotid or peripheral arterial revascularization >50% stenosis "
            "of coronary, carotid, or lower extremity arteries",
            "(c) CAD with ≥50% stenosis in ≥2 vessels",
            "TIA (hospital-based diagnosis), carotid stenosis (≥50%), or cerebral "
            "revascularization",
            "Documented coronary artery disease (≥ 50% luminal diameter narrowing of left "
            "main coronary artery or ≥50% in at least two major coronary arteries in angiogram)",
            "Peripheral occlusive arterial disease (previous limb bypass surgery, stenting or "
            "percutaneous transluminal angioplasty; previous limb or foot amputation due to "
            "circulatory insufficiency, angiographic or ultrasound detected significant vessel "
            "stenosis (≥ 50%) of major limb arteries",
        ],
    )
    def test_should_refuse_a_percentage_describing_a_lesion(self, phrase):
        assert parse_value_constraints(phrase) == []

    def test_should_still_read_an_ejection_fraction_which_is_measured(self):
        vc = _one(
            "Symptomatic congestive heart failure or left ventricular dysfunction with "
            "left ventricular ejection fraction (LVEF) ≤ 40%"
        )
        assert vc is not None and vc.value == 40.0 and vc.unit_text == "%"

    def test_should_still_read_an_hba1c_percentage(self):
        vc = _one("HbA1c of => 6.5% and <= 10.0% at Visit 1 (screening)")
        assert vc is not None and vc.value == 6.5 and vc.unit_text == "%"


class TestADrugDoseRateIsNotAMeasuredValue:
    """drug_exposure reads Quantity -- units dispensed -- and no dose-strength column."""

    def test_should_refuse_a_daily_dose_on_a_treatment_phrase(self):
        assert parse_value_constraints("Required treatment with aspirin > 165 mg/day") == []

    def test_should_still_read_a_concentration_in_a_treatment_phrase(self):
        vc = _one(
            "use of high/moderate intensity statins to achieve LDL cholesterol level "
            "&lt;100 mg/dL"
        )
        assert vc is not None and vc.unit_text == "mg/dL"

    def test_should_still_read_an_excretion_rate_with_no_dose_context(self):
        vc = _one("Proteinuria > 300 mg/day")
        assert vc is not None and vc.value == 300.0


class TestTheAnnotationHandedToTheModelLosesThemToo:
    """Path 1 of the three: what `_format_criteria` puts next to the criterion line.

    Asserted through the real renderer rather than the parser, because Rule 0's
    "copy verbatim" makes THIS string the instruction the model actually follows.
    """

    @pytest.mark.parametrize(
        "phrase",
        [
            "Required treatment with aspirin > 165 mg/day",
            "Type 2 diabetes mellitus duration > 10 years at Visit 1a",
            "Prior coronary, carotid or peripheral arterial revascularization >50% stenosis "
            "of coronary, carotid, or lower extremity arteries",
        ],
    )
    def test_should_annotate_nothing_for_an_unmeasurable_threshold(self, phrase):
        assert annotate_value_constraints(phrase) == ""

    def test_should_still_annotate_a_real_lab_threshold(self):
        rendered = annotate_value_constraints("Hemoglobin < 9 g/dL")
        assert '"value": 9.0' in rendered and '"unitText": "g/dL"' in rendered
