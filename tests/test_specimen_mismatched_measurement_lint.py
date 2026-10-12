"""Gate (u): Measurement criteria reading LOINC lab tests in a specimen or property not stated.

``deliveries/2026-09-23/carolina_*.circe.json`` codeset 42 'Glucose' is read by a ``> 13.3`` filter
whose ``Unit`` is 8753 mmol/L, over {3000483, 3004378, 3004676, 44816672}: three Mass-Concentration
codes, a CSF/plasma ratio and a vitreous-fluid code. The unit matches none of them and the vitreous
and CSF codes are not the specimen the protocol means. Every existing check passed it. The rule this
gate reads is ``src.services.loinc_specimen.plan_specimen_refinement`` -- the same one the builder
repairs with -- so the two cannot disagree about which sets are in scope.

Since RFC-016 step 4 the specimen is not re-decided here and the rule name is not read: the gate
judges specimen and challenge from the specimen critic's decision the builder recorded under
``_specimenDecisions`` for the codeset, and a codeset with no record on its unit's property alone.
"""

from __future__ import annotations

import json
from typing import Any

from src.services.loinc_specimen import POINT_IN_TIME as PT
from src.services.loinc_specimen import LabTest
from src.utils.circe_lint import (
    SPECIMEN_DECISIONS_KEY,
    measurement_lab_test_ids,
    specimen_mismatched_measurement_criteria,
)


def _findings(cohort, lookup=None):
    """(fail, warn) locators, with the analyte query the fake vocabulary answers."""
    lookup = LOOKUP if lookup is None else lookup
    return specimen_mismatched_measurement_criteria(
        cohort, lookup, lambda a: [t for t in lookup.values() if t.component.split("^")[0] == a]
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
LOOKUP = {t.concept_id: t for t in (GLU_BLD, GLU_SPB, GLU_VIT, GLU_CSF, GLU_SP, UACR)}

MG_DL = [{"CONCEPT_ID": 8840, "CONCEPT_CODE": "mg/dL", "CONCEPT_NAME": "milligram per deciliter"}]
MMOL_L = [{"CONCEPT_ID": 8753, "CONCEPT_CODE": "mmol/L", "CONCEPT_NAME": "millimole per liter"}]

BLOOD = ("Serum or Plasma", "Blood", "Serum, Plasma or Blood")


def decided(*systems: str, challenges=(None,)) -> list[dict[str, Any]]:
    """The ``accepted`` options of a recorded specimen-critic decision."""
    return [
        {"systemId": None, "system": system, "challenge": challenge}
        for system in systems
        for challenge in challenges
    ]


def _lab(test: LabTest) -> dict[str, Any]:
    return {
        "concept": {
            "CONCEPT_ID": test.concept_id,
            "CONCEPT_NAME": test.concept_name,
            "DOMAIN_ID": "Measurement",
            "VOCABULARY_ID": "LOINC",
            "CONCEPT_CLASS_ID": "Lab Test",
            "STANDARD_CONCEPT": "S",
        },
        "isExcluded": False,
        "includeDescendants": False,
        "includeMapped": False,
    }


def _snomed(cid: int) -> dict[str, Any]:
    return {
        "concept": {
            "CONCEPT_ID": cid,
            "CONCEPT_NAME": f"c{cid}",
            "DOMAIN_ID": "Measurement",
            "VOCABULARY_ID": "SNOMED",
            "CONCEPT_CLASS_ID": "Procedure",
            "STANDARD_CONCEPT": "S",
        },
        "isExcluded": False,
        "includeDescendants": True,
        "includeMapped": False,
    }


def _cohort(
    items: list[dict[str, Any]],
    *,
    name: str = "Glucose",
    unit=MG_DL,
    criteria_type: str = "Measurement",
    accepted: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    attrs: dict[str, Any] = {"CodesetId": 42, "ValueAsNumber": {"Value": 240.0, "Op": "gt"}}
    if unit is not None:
        attrs["Unit"] = unit
    decisions = (
        [{"codesetId": 42, "judged": True, "accepted": accepted}] if accepted is not None else []
    )
    return {
        SPECIMEN_DECISIONS_KEY: decisions,
        "ConceptSets": [
            {
                "id": 1,
                "name": "linagliptin",
                "expression": {
                    "items": [
                        {
                            "concept": {
                                "CONCEPT_ID": 40239216,
                                "CONCEPT_NAME": "linagliptin",
                                "DOMAIN_ID": "Drug",
                                "VOCABULARY_ID": "RxNorm",
                                "CONCEPT_CLASS_ID": "Ingredient",
                                "CONCEPT_CODE": "1",
                            },
                            "isExcluded": False,
                            "includeDescendants": True,
                        }
                    ]
                },
            },
            {"id": 42, "name": name, "expression": {"items": items}},
        ],
        "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 1}}]},
        "InclusionRules": [
            {
                "name": name,
                "expression": {
                    "Type": "ALL",
                    "CriteriaList": [
                        {
                            "Criteria": {criteria_type: attrs},
                            "StartWindow": {
                                "Start": {"Days": 180, "Coeff": -1},
                                "End": {"Days": 0, "Coeff": 1},
                            },
                            "RestrictVisit": False,
                            "IgnoreObservationPeriod": False,
                            "Occurrence": {"Type": 0, "Count": 0},
                        }
                    ],
                    "DemographicCriteriaList": [],
                    "Groups": [],
                },
            }
        ],
    }


DELIVERED = [_lab(GLU_BLD), _lab(GLU_CSF), _lab(GLU_VIT), _lab(GLU_SPB)]


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
AST_SP = LabTest(
    3013721,
    "Aspartate aminotransferase [Enzymatic activity/volume] in Serum or Plasma",
    "Aspartate aminotransferase",
    "Serum or Plasma",
    "Catalytic Concentration",
    "Qn",
    "1920-8",
    time_aspect=PT,
)
AST_RBC = LabTest(
    3005435,
    "Aspartate aminotransferase [Enzymatic activity/volume] in Red Blood Cells",
    "Aspartate aminotransferase",
    "Red Blood Cells",
    "Catalytic Concentration",
    "Qn",
    "16412-9",
    time_aspect=PT,
)
EGFR = LabTest(
    46236952,
    "Glomerular filtration rate [Volume Rate/Area] in Serum, Plasma or Blood by "
    "Creatinine-based formula (MDRD)/1.73 sq M",
    "Glomerular filtration rate",
    "Serum, Plasma or Blood",
    "Volume Rate/Area",
    "Qn",
    "77147-7",
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
ML_MIN = [{"CONCEPT_ID": 8795, "CONCEPT_CODE": "mL/min", "CONCEPT_NAME": "milliliter per minute"}]


class TestTheDeliveredShapeFails:
    def test_should_fail_the_vitreous_and_csf_members_when_the_critic_accepted_only_blood(self):
        fail, warn = _findings(_cohort(DELIVERED, accepted=decided(*BLOOD)))
        assert len(fail) == 1 and warn == [], (fail, warn)
        assert "3004676" in fail[0] and "3004378" in fail[0]
        assert "3000483" not in fail[0] and "44816672" not in fail[0]

    def test_should_judge_only_the_property_when_no_specimen_decision_was_recorded(self):
        """The rule name ("Glucose") and the concept set name are not read for a specimen: with
        no recorded decision the vitreous member is not judged, and only the CSF/plasma ratio,
        whose property contradicts mg/dL, is reported."""
        fail, warn = _findings(_cohort(DELIVERED))
        assert len(fail) == 1 and warn == [], (fail, warn)
        assert "3004378" in fail[0] and "3004676" not in fail[0]

    def test_should_fail_every_mass_member_when_the_unit_is_mmol_per_litre(self):
        """The builder repairs this one (Substance codes exist), so it is a FAIL, not a WARN."""
        fail, warn = _findings(
            _cohort(DELIVERED, unit=MMOL_L, accepted=decided(*BLOOD)),
            {**LOOKUP, GLU_SP_MOL.concept_id: GLU_SP_MOL},
        )
        assert len(fail) == 1 and warn == [], (fail, warn)
        assert all(str(cid) in fail[0] for cid in (3000483, 3004378, 3004676, 44816672))
        assert "'Mass Concentration' contradicts the unit's 'Substance Concentration'" in fail[0]

    def test_should_name_only_the_lab_tests_a_measurement_criterion_reads(self):
        cohort = _cohort(DELIVERED + [_snomed(4144235)])
        assert measurement_lab_test_ids(cohort) == {3000483, 3004378, 3004676, 44816672}


class TestTheDeclinedSetsWarn:
    """Refinement (c): a finding on a set the builder declines to repair is a WARN, with reason."""

    def test_should_warn_with_the_reason_when_no_analyte_holds_a_majority(self):
        lookup = {t.concept_id: t for t in (ALT_SP, AST_SP, AST_RBC)}
        fail, warn = _findings(
            _cohort(
                [_lab(ALT_SP), _lab(AST_SP), _lab(AST_RBC)],
                name="Liver enzymes",
                unit=None,
                accepted=decided(*BLOOD),
            ),
            lookup,
        )
        assert fail == [] and len(warn) == 1, (fail, warn)
        assert "no analyte majority" in warn[0] and "3005435" in warn[0]

    def test_should_warn_when_the_unit_contradicts_every_member_and_nothing_can_be_added(self):
        """EMPA-REG codeset 37: eGFR extracted in mL/min, every member is /1.73 sq M."""
        fail, warn = _findings(
            _cohort([_lab(EGFR)], name="Glomerular Filtration Rate", unit=ML_MIN),
            {EGFR.concept_id: EGFR},
        )
        assert fail == [] and len(warn) == 1, (fail, warn)
        assert "contradicts" in warn[0] and "declined" in warn[0]

    def test_should_warn_when_the_critic_rejected_the_only_specimen_the_set_holds(self):
        cohort = _cohort(
            [_lab(UACR)],
            name="Microalbuminuria or proteinuria",
            unit=None,
            accepted=decided(*BLOOD),
        )
        fail, warn = _findings(cohort)
        assert fail == [] and len(warn) == 1, warn
        assert "no LOINC lab-test member in a specimen the criterion states" in warn[0], warn


class TestTheSoundShapesStaySilent:
    def test_should_stay_silent_when_every_lab_test_is_serum_in_the_units_property(self):
        assert _findings(_cohort([_lab(GLU_SP), _lab(GLU_BLD)], accepted=decided(*BLOOD))) == (
            [],
            [],
        )

    def test_should_stay_silent_when_the_critic_accepted_the_urine_it_reads(self):
        cohort = _cohort(
            [_lab(UACR), _lab(GLU_SP)],
            name="Urine albumin creatinine ratio",
            unit=None,
            accepted=decided("Urine", *BLOOD),
        )
        assert _findings(cohort) == ([], [])

    def test_should_stay_silent_on_a_set_with_no_loinc_lab_test(self):
        assert _findings(_cohort([_snomed(4144235)])) == ([], [])
        assert measurement_lab_test_ids(_cohort([_snomed(4144235)])) == set()


class TestTheDeliveryGateRunsTheCheck:
    """A lint nobody calls is indistinguishable from one that returns nothing."""

    class _FakeVocabulary:
        opened = 0

        def __init__(self, *_args):
            type(self).opened += 1

        def lab_tests(self, ids):
            return {cid: LOOKUP[cid] for cid in ids if cid in LOOKUP}

        def analyte_lab_tests(self, analyte):
            return [t for t in LOOKUP.values() if t.component.split("^")[0] == analyte]

        def close(self):
            pass

    @staticmethod
    def _deliver(tmp_path, cohort):
        study = {
            "id": 10,
            "name": "Study 10",
            "comparisonMode": "target_minus_treatment",
            "treatmentArms": [{"name": "linagliptin"}, {"name": "glimepiride"}],
            "eligibility": {"structuredExpression": json.loads(json.dumps(cohort))},
        }
        for role in ("treatment", "comparator"):
            (tmp_path / f"carolina_{role}.circe.json").write_text(json.dumps(cohort))
        store = tmp_path / "studies.json"
        store.write_text(json.dumps([study]))
        return store

    def _run(self, monkeypatch, tmp_path, capsys, cohort, opener=None):
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        import scripts.verify_circe_delivery as gate

        self._FakeVocabulary.opened = 0
        monkeypatch.setattr(gate, "_open_lab_test_vocabulary", opener or self._FakeVocabulary)
        store = self._deliver(tmp_path, cohort)
        rc = gate.main(["--dir", str(tmp_path), "--store", str(store), "--map", "carolina=10"])
        captured = capsys.readouterr()
        return rc, captured.out, captured.err

    def test_should_fail_the_delivery_when_a_glucose_set_holds_vitreous_fluid(
        self, monkeypatch, tmp_path, capsys
    ):
        rc, out, _err = self._run(
            monkeypatch, tmp_path, capsys, _cohort(DELIVERED, accepted=decided(*BLOOD))
        )
        assert rc == 1, out
        assert "specimen-mismatched measurement (1)" in out, out

    def test_should_not_fail_on_this_check_when_the_set_is_serum(
        self, monkeypatch, tmp_path, capsys
    ):
        _rc, out, _err = self._run(monkeypatch, tmp_path, capsys, _cohort([_lab(GLU_SP)]))
        assert "specimen-mismatched" not in out, out

    def test_should_print_a_warn_and_not_fail_on_this_check_when_the_builder_declines(
        self, monkeypatch, tmp_path, capsys
    ):
        cohort = _cohort(
            [_lab(UACR)],
            name="Microalbuminuria or proteinuria",
            unit=None,
            accepted=decided(*BLOOD),
        )
        _rc, out, _err = self._run(monkeypatch, tmp_path, capsys, cohort)
        assert "specimen-mismatched measurement (" not in out, out
        assert "specimen refinement declined (WARN, 1)" in out, out

    def test_should_not_open_the_vocabulary_when_no_measurement_reads_a_lab_test(
        self, monkeypatch, tmp_path, capsys
    ):
        self._run(monkeypatch, tmp_path, capsys, _cohort([_snomed(4144235)]))
        assert self._FakeVocabulary.opened == 0

    def test_should_abort_when_a_lab_test_needs_the_vocabulary_and_it_is_unreachable(
        self, monkeypatch, tmp_path, capsys
    ):
        def _unreachable(*_args):
            raise OSError("connection refused")

        rc, _out, err = self._run(
            monkeypatch, tmp_path, capsys, _cohort(DELIVERED), opener=_unreachable
        )
        assert rc == 2
        assert "vocabulary unreachable" in err
