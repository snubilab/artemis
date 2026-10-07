"""Specimen, property and challenge refinement of LOINC lab tests in Measurement concept sets.

The defect, measured on the 2026-09-23 delivery: EMPA-REG codeset 10 and CAROLINA codesets 41/42
(glucose > 240 mg/dL / > 13.3 mmol/L) shipped as {3000483, 3004378, 3004676, 44816672} -- blood,
CSF/plasma ratio, vitreous fluid, serum/plasma/blood -- and none of those has a single row at Ajou,
Dong-A or Keimyung, which record glucose as 3004501 (serum or plasma) or 3037110 (fasting). The
exclusion excluded nobody. Codeset 42 is also in mmol/L over Mass-Concentration codes only, so its
unit filter can never match.

Every attribute below is the real vocabulary row (synthea23m, verified 2026-10-07): the logic under
test must reach its answer from component / system / property / scale and the criterion's own
words, so the fixtures carry nothing a production rule could key on except those.
"""

from __future__ import annotations

import pytest

from src.services.loinc_specimen import (
    POINT_IN_TIME as PT,
)
from src.services.loinc_specimen import (
    LabTest,
    challenge_stated,
    criterion_words,
    plan_specimen_refinement,
    refine_measurement_concept_set,
    system_allowed,
    unit_property,
)

GLU_SP = LabTest(
    3004501,
    "Glucose [Mass/volume] in Serum or Plasma",
    "Glucose",
    "Serum or Plasma",
    "Mass Concentration",
    "Qn",
    "2345-7",
    time_aspect=PT,
)
GLU_SP_MOL = LabTest(
    3013826,
    "Glucose [Moles/volume] in Serum or Plasma",
    "Glucose",
    "Serum or Plasma",
    "Substance Concentration",
    "Qn",
    "14749-6",
    time_aspect=PT,
)
GLU_BLD = LabTest(
    3000483,
    "Glucose [Mass/volume] in Blood",
    "Glucose",
    "Blood",
    "Mass Concentration",
    "Qn",
    "2339-0",
    time_aspect=PT,
)
GLU_SPB = LabTest(
    44816672,
    "Glucose [Mass/volume] in Serum, Plasma or Blood",
    "Glucose",
    "Serum, Plasma or Blood",
    "Mass Concentration",
    "Qn",
    "74774-1",
    time_aspect=PT,
)
GLU_VIT = LabTest(
    3004676,
    "Glucose [Mass/volume] in Vitreous fluid",
    "Glucose",
    "Vitreous fluid",
    "Mass Concentration",
    "Qn",
    "16903-7",
    time_aspect=PT,
)
GLU_CSF = LabTest(
    3004378,
    "Glucose in CSF/Glucose plas",
    "Glucose CSF/Glucose plas",
    "Plasma and CSF",
    "Relative Mass Concentration",
    "Qn",
    "2352-3",
    time_aspect=PT,
)
GLU_FAST = LabTest(
    3037110,
    "Fasting glucose [Mass/volume] in Serum or Plasma",
    "Glucose^post CFst",
    "Serum or Plasma",
    "Mass Concentration",
    "Qn",
    "1558-6",
    time_aspect=PT,
)
GLU_FAST_MOL = LabTest(
    3018251,
    "Fasting glucose [Moles/volume] in Serum or Plasma",
    "Glucose^post CFst",
    "Serum or Plasma",
    "Substance Concentration",
    "Qn",
    "14771-0",
    time_aspect=PT,
)
GLU_OGTT = LabTest(
    3025673,
    "Glucose [Mass/volume] in Serum or Plasma --2 hours post 75 g glucose PO",
    "Glucose^2H post 75 g glucose PO",
    "Serum or Plasma",
    "Mass Concentration",
    "Qn",
    "1518-0",
    time_aspect=PT,
)
UACR = LabTest(
    3001802,
    "Microalbumin/Creatinine [Mass Ratio] in Urine",
    "Albumin/Creatinine",
    "Urine",
    "Mass Ratio",
    "Qn",
    "14959-1",
    time_aspect=PT,
)
ALT_SP = LabTest(
    3006923,
    "Alanine aminotransferase [Enzymatic activity/volume] in Serum or Plasma",
    "Alanine aminotransferase",
    "Serum or Plasma",
    "Catalytic Concentration",
    "Qn",
    "1742-6",
    time_aspect=PT,
)
ALT_RBC = LabTest(
    3015912,
    "Alanine aminotransferase [Enzymatic activity/volume] in Red Blood Cells",
    "Alanine aminotransferase",
    "Red Blood Cells",
    "Catalytic Concentration",
    "Qn",
    "16324-6",
    time_aspect=PT,
)
HBA1C = LabTest(
    3004410,
    "Hemoglobin A1c/Hemoglobin.total in Blood",
    "Hemoglobin A1c/Hemoglobin.total",
    "Blood",
    "Mass fraction",
    "Qn",
    "4548-4",
    time_aspect=PT,
)
HBA1 = LabTest(
    3005446,
    "Hemoglobin A1/Hemoglobin.total in Blood",
    "Hemoglobin A1/Hemoglobin.total",
    "Blood",
    "Mass fraction",
    "Qn",
    "4547-6",
    time_aspect=PT,
)
EGFR = LabTest(
    46236952,
    "Glomerular filtration rate [Volume Rate/Area] in Serum, Plasma or Blood "
    "by Creatinine-based formula (MDRD)/1.73 sq M",
    "Glomerular filtration rate",
    "Serum, Plasma or Blood",
    "Volume Rate/Area",
    "Qn",
    "77147-7",
    time_aspect=PT,
)

GLUCOSE_FAMILY = [GLU_SP, GLU_SP_MOL, GLU_BLD, GLU_SPB, GLU_VIT, GLU_FAST, GLU_FAST_MOL, GLU_OGTT]
DELIVERED_GLUCOSE = [GLU_BLD, GLU_CSF, GLU_VIT, GLU_SPB]  # EMPA-REG cs10 / CAROLINA cs41, cs42


class FakeVocabulary:
    """The vocabulary as the two queries see it: attributes by id, and the tests of one analyte."""

    def __init__(self, *tests: LabTest):
        self.by_id = {t.concept_id: t for t in tests}

    def lab_tests(self, concept_ids):
        return {cid: self.by_id[cid] for cid in concept_ids if cid in self.by_id}

    def analyte_lab_tests(self, analyte):
        return [t for t in self.by_id.values() if t.component.split("^")[0] == analyte]


def _plan(members, *, text, description, unit_code=None, numeric=True, vocab=None):
    vocab = vocab or FakeVocabulary(*GLUCOSE_FAMILY, *members)
    return plan_specimen_refinement(
        member_ids=[m.concept_id for m in members],
        lab_tests=vocab.lab_tests([m.concept_id for m in members]),
        words=criterion_words(text, description),
        description_words=criterion_words(description),
        unit_prop=unit_property(unit_code) if unit_code else None,
        numeric_bound=numeric,
        analyte_lab_tests=vocab.analyte_lab_tests,
    )


class TestUnitProperty:
    def test_should_name_mass_concentration_when_the_unit_is_mass_per_volume(self):
        assert unit_property("mg/dL") == "Mass Concentration"

    def test_should_name_substance_concentration_when_the_unit_is_moles_per_volume(self):
        assert unit_property("mmol/L") == "Substance Concentration"

    def test_should_name_volume_rate_per_area_when_the_unit_is_the_egfr_unit(self):
        assert unit_property("mL/min/(173.10*-2.m2)") == "Volume Rate/Area"

    def test_should_name_nothing_when_the_unit_is_a_mass_ratio(self):
        """'Albumin/Creatinine [Ratio] in Urine' (32294-1) is reported in mg/g like the [Mass Ratio]
        code beside it; TROY's CAROLINA UACR set holds both. A mass-per-mass unit therefore does
        not separate the two LOINC properties, and must not remove either."""
        assert unit_property("ug/mg") is None
        assert unit_property("mg/g") is None

    def test_should_name_nothing_when_the_unit_is_a_percent(self):
        assert unit_property("%") is None


class TestSpecimenNaming:
    def test_should_allow_serum_plasma_and_blood_when_the_criterion_names_no_specimen(self):
        words = criterion_words("glucose", "Uncontrolled hyperglycemia")
        assert all(
            system_allowed(s, words) for s in ("Serum or Plasma", "Blood", "Serum, Plasma or Blood")
        )

    def test_should_refuse_vitreous_and_red_cells_when_the_criterion_does_not_name_them(self):
        words = criterion_words("glucose", "Uncontrolled hyperglycemia")
        assert not system_allowed("Vitreous fluid", words)
        assert not system_allowed("Red Blood Cells", words)
        assert not system_allowed("Plasma and CSF", words)

    def test_should_allow_urine_when_the_criterion_says_urinary(self):
        assert system_allowed("Urine", criterion_words("Urinary albumin creatinine ratio", None))


class TestChallengeAxis:
    def test_should_admit_a_post_fast_variant_when_the_description_states_a_fast(self):
        assert challenge_stated(
            "post CFst", criterion_words("Glucose level >240 mg/dl after overnight fast")
        )

    def test_should_not_admit_a_post_fast_variant_when_the_description_states_no_fast(self):
        assert not challenge_stated("post CFst", criterion_words("Uncontrolled hyperglycemia"))

    def test_should_not_admit_a_glucose_load_when_the_description_states_only_a_fast(self):
        assert not challenge_stated(
            "2H post 75 g glucose PO", criterion_words("after overnight fast")
        )


class TestPlan:
    def test_should_not_add_a_test_whose_component_only_shares_the_analyte_name(self):
        """Two LOINC Component concepts are named 'Glucose' (LP14635-4 40795740 and LP435977-6
        3968605); the second carries only 3964843 '... --1.5 hours post dose glucagon', a
        challenge test whose component lost its '^' part. The analyte is the component the set's
        own members carry, not its name."""
        from dataclasses import replace

        members = [replace(t, component_id=40795740) for t in (GLU_BLD, GLU_SPB)]
        candidates = [
            replace(GLU_SP, component_id=40795740),
            glucagon_glucose := LabTest(
                3964843,
                "Glucose [Mass/volume] in Serum or Plasma --1.5 hours post dose glucagon",
                "Glucose",
                "Serum or Plasma",
                "Mass Concentration",
                "Qn",
                "",
                component_id=3968605,
                time_aspect=PT,
            ),
        ]
        plan = _plan(
            members,
            text="glucose",
            description="Uncontrolled hyperglycemia",
            unit_code="mg/dL",
            vocab=FakeVocabulary(*members, *candidates),
        )
        assert {t.concept_id for t in plan.added} == {3004501}, glucagon_glucose

    def test_should_add_the_serum_code_and_drop_other_specimens_when_no_fast_is_stated(self):
        plan = _plan(
            DELIVERED_GLUCOSE,
            text="glucose",
            description="Uncontrolled hyperglycemia",
            unit_code="mg/dL",
        )
        assert plan.declined is None
        assert {t.concept_id for t in plan.added} == {3004501}
        assert {cid for cid, _ in plan.removed} == {3004378, 3004676}

    def test_should_add_the_fasting_code_when_the_description_states_an_overnight_fast(self):
        plan = _plan(
            DELIVERED_GLUCOSE,
            text="Glucose",
            description="Glucose level >240 mg/dl after overnight fast",
            unit_code="mg/dL",
        )
        assert {t.concept_id for t in plan.added} == {3004501, 3037110}

    def test_should_swap_to_substance_codes_when_the_unit_is_mmol_per_litre(self):
        plan = _plan(
            DELIVERED_GLUCOSE,
            text="Glucose",
            description="Glucose level >13.3 mmol/L after overnight fast",
            unit_code="mmol/L",
        )
        assert {t.concept_id for t in plan.added} == {3013826, 3018251}
        assert {cid for cid, _ in plan.removed} == {3000483, 3004378, 3004676, 44816672}

    def test_should_leave_the_set_unchanged_when_the_component_is_ambiguous(self):
        plan = _plan(
            [HBA1C, HBA1],
            text="HbA1c",
            description="HbA1c",
            unit_code="%",
            vocab=FakeVocabulary(HBA1C, HBA1),
        )
        assert plan.declined and "majority" in plan.declined
        assert plan.added == () and plan.removed == ()

    def test_should_keep_urine_members_when_the_criterion_names_urine(self):
        plan = _plan(
            [UACR],
            text="Urine Albumin Creatinine Ratio",
            description="Impaired renal function (UACR)",
            numeric=False,
            vocab=FakeVocabulary(UACR),
        )
        assert plan.removed == ()

    def test_should_leave_an_all_urine_set_unchanged_when_urine_is_not_named(self):
        plan = _plan(
            [UACR],
            text="Microalbuminuria or proteinuria",
            description=None,
            numeric=False,
            vocab=FakeVocabulary(UACR),
        )
        assert plan.declined and plan.removed == () and plan.added == ()

    def test_should_leave_the_set_unchanged_when_it_holds_no_loinc_lab_test(self):
        plan = plan_specimen_refinement(
            member_ids=[4213628],
            lab_tests={},
            words=criterion_words("eGFR"),
            description_words=frozenset(),
            unit_prop=None,
            numeric_bound=True,
            analyte_lab_tests=lambda _a: pytest.fail("must not query"),
        )
        assert plan.declined and plan.added == () and plan.removed == ()

    def test_should_decline_when_the_unit_contradicts_every_member(self):
        plan = _plan(
            [EGFR],
            text="Glomerular Filtration Rate",
            description="eGFR < 30 ml/min",
            unit_code="mL/min",
            vocab=FakeVocabulary(EGFR),
        )
        assert plan.declined and plan.removed == () and plan.added == ()

    def test_should_drop_red_cell_members_and_keep_the_serum_code_when_the_bound_is_relative(self):
        plan = _plan(
            [ALT_SP, ALT_RBC],
            text="ALT",
            description="ALT elevation",
            vocab=FakeVocabulary(ALT_SP, ALT_RBC),
        )
        assert {cid for cid, _ in plan.removed} == {3015912}
        assert plan.added == ()


UACR_SPOT = LabTest(
    3034485,
    "Albumin/Creatinine [Mass Ratio] in Urine",
    "Albumin/Creatinine",
    "Urine",
    "Mass Ratio",
    "Qn",
    "9318-7",
    time_aspect=PT,
)
UACR_24H = LabTest(
    3002827,
    "Microalbumin/Creatinine [Mass Ratio] in 24 hour Urine",
    "Albumin/Creatinine",
    "Urine",
    "Mass Ratio",
    "Qn",
    "14958-3",
    time_aspect="24 hours",
)
GLU_MEAN = LabTest(
    1002230,
    "Glucose [Mass/volume] mean in Serum or Plasma",
    "Glucose",
    "Serum or Plasma",
    "Mass Concentration",
    "Qn",
    "",
    time_aspect="Stdy^mean",
)


class TestTimeAspect:
    """Refinement (a): an addition is one measurement, never a timed collection or a summary."""

    def test_should_not_add_a_24_hour_collection_when_the_criterion_states_a_spot_ratio(self):
        plan = _plan(
            [UACR],
            text="Urinary albumin creatinine ratio",
            description="UACR >= 30 ug/mg",
            unit_code="ug/mg",
            vocab=FakeVocabulary(UACR, UACR_SPOT, UACR_24H),
        )
        assert {t.concept_id for t in plan.added} == {3034485}

    def test_should_not_add_a_study_mean_when_the_criterion_bounds_glucose(self):
        plan = _plan(
            DELIVERED_GLUCOSE,
            text="glucose",
            description="Uncontrolled hyperglycemia",
            unit_code="mg/dL",
            vocab=FakeVocabulary(*GLUCOSE_FAMILY, GLU_MEAN, *DELIVERED_GLUCOSE),
        )
        assert 1002230 not in {t.concept_id for t in plan.added}
        assert 3004501 in {t.concept_id for t in plan.added}

    def test_should_keep_a_24_hour_member_the_mapper_chose(self):
        """Negative control: the time axis governs additions only; removal is specimen/property."""
        plan = _plan(
            [UACR, UACR_24H],
            text="Urinary albumin creatinine ratio",
            description=None,
            unit_code="ug/mg",
            vocab=FakeVocabulary(UACR, UACR_SPOT, UACR_24H),
        )
        assert 3002827 not in {cid for cid, _ in plan.removed}


class TestBoundGate:
    """Refinement (b): a criterion with no numeric bound gains nothing; removal still applies."""

    def test_should_add_nothing_when_the_criterion_carries_no_bound(self):
        """CAROLINA cs3 'Glycaemic control insufficient' shape: one blood glucose, no threshold."""
        plan = _plan(
            [GLU_BLD], text="Glycaemic control insufficient", description=None, numeric=False
        )
        assert plan.added == ()

    def test_should_still_drop_vitreous_when_the_criterion_carries_no_bound(self):
        plan = _plan(DELIVERED_GLUCOSE, text="glucose", description="hyperglycemia", numeric=False)
        assert plan.added == ()
        assert {cid for cid, _ in plan.removed} == {3004378, 3004676}

    def test_should_add_when_the_same_criterion_carries_a_bound(self):
        """Negative control for the gate above: the same set under a bound gains the serum code."""
        plan = _plan(
            [GLU_BLD], text="Glycaemic control insufficient", description=None, unit_code="mg/dL"
        )
        assert 3004501 in {t.concept_id for t in plan.added}


def _circe_item(test: LabTest) -> dict:
    return {
        "concept": {
            "CONCEPT_ID": test.concept_id,
            "CONCEPT_NAME": test.concept_name,
            "DOMAIN_ID": "Measurement",
            "VOCABULARY_ID": "LOINC",
            "CONCEPT_CLASS_ID": "Lab Test",
            "STANDARD_CONCEPT": "S",
        },
        "includeDescendants": True,
        "includeMapped": False,
        "isExcluded": False,
    }


class TestRefineExpression:
    def test_should_rewrite_the_items_when_the_plan_changes_the_set(self):
        snomed = {
            "concept": {
                "CONCEPT_ID": 4144235,
                "CONCEPT_NAME": "Glucose measurement, blood",
                "VOCABULARY_ID": "SNOMED",
                "CONCEPT_CLASS_ID": "Procedure",
            },
            "includeDescendants": True,
            "includeMapped": False,
            "isExcluded": False,
        }
        expression = {"items": [_circe_item(t) for t in DELIVERED_GLUCOSE] + [snomed]}
        refined, plan = refine_measurement_concept_set(
            expression,
            seed="glucose",
            description="Uncontrolled hyperglycemia",
            value_filter={
                "ValueAsNumber": {"Value": 240.0, "Op": "gt"},
                "Unit": [{"CONCEPT_ID": 8840, "CONCEPT_CODE": "mg/dL"}],
            },
            vocabulary=FakeVocabulary(*GLUCOSE_FAMILY, *DELIVERED_GLUCOSE),
        )
        ids = [i["concept"]["CONCEPT_ID"] for i in refined["items"]]
        assert ids == [3000483, 44816672, 4144235, 3004501]
        added = refined["items"][-1]
        assert (
            added["concept"]["VOCABULARY_ID"] == "LOINC"
            and added["concept"]["CONCEPT_CODE"] == "2345-7"
        )
        assert added["isExcluded"] is False
        assert [i["concept"]["CONCEPT_ID"] for i in expression["items"]][:4] == [
            3000483,
            3004378,
            3004676,
            44816672,
        ]

    def test_should_not_touch_the_vocabulary_when_no_item_is_a_loinc_lab_test(self):
        class Unreachable:
            def lab_tests(self, _ids):
                raise AssertionError("vocabulary must not be queried")

        expression = {"items": [{"concept": {"CONCEPT_ID": 3006923}}]}
        refined, plan = refine_measurement_concept_set(
            expression,
            seed="ALT",
            description=None,
            value_filter={},
            vocabulary=Unreachable(),
        )
        assert refined == expression and plan.declined


class TestTheEligibilityBuilderApplies:
    """A refinement no production path calls is indistinguishable from one that does nothing."""

    @staticmethod
    def _build(domain, *, vocabulary, description="Uncontrolled hyperglycemia"):
        from unittest.mock import MagicMock

        from src.services.tte_service import TTEService

        service = TTEService(store=MagicMock())
        service._recommend_seeded_concept_set = lambda *args, **kwargs: {
            "name": "glucose",
            "domain": domain,
            "expression": {
                "items": [
                    {
                        **_circe_item(t),
                        "concept": {**_circe_item(t)["concept"], "DOMAIN_ID": domain},
                    }
                    for t in DELIVERED_GLUCOSE
                ]
            },
        }
        service._lab_test_vocabulary = lambda: vocabulary
        return service._build_seeded_eligibility_rule(
            criterion={
                "sourceText": "glucose",
                "description": description,
                "domain": domain,
                "valueConstraint": {
                    "op": "gt",
                    "value": 240.0,
                    "unitText": "mg/dL",
                    "unitConceptId": 8840,
                },
                "window": {"start": -180, "end": 0},
                "logicType": "ABSENCE",
            },
            codeset_id=10,
            exclusion=True,
        )

    def test_should_ship_the_serum_code_not_the_vitreous_code_when_the_criterion_is_a_measurement(
        self,
    ):
        built = self._build(
            "Measurement", vocabulary=FakeVocabulary(*GLUCOSE_FAMILY, *DELIVERED_GLUCOSE)
        )
        ids = {i["concept"]["CONCEPT_ID"] for i in built["conceptSet"]["expression"]["items"]}
        assert ids == {3000483, 44816672, 3004501}

    def test_should_not_consult_the_vocabulary_when_the_criterion_is_not_a_measurement(self):
        class Unreachable:
            def lab_tests(self, _ids):
                raise AssertionError("vocabulary must not be queried")

        built = self._build("Observation", vocabulary=Unreachable())
        ids = [i["concept"]["CONCEPT_ID"] for i in built["conceptSet"]["expression"]["items"]]
        assert ids == [3000483, 3004378, 3004676, 44816672]
