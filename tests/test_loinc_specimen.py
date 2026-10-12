"""Specimen, property and challenge refinement of LOINC lab tests in Measurement concept sets.

The defect, measured on the 2026-09-23 delivery: EMPA-REG codeset 10 and CAROLINA codesets 41/42
(glucose > 240 mg/dL / > 13.3 mmol/L) shipped as {3000483, 3004378, 3004676, 44816672} -- blood,
CSF/plasma ratio, vitreous fluid, serum/plasma/blood -- and none of those has a single row at Ajou,
Dong-A or Keimyung, which record glucose as 3004501 (serum or plasma) or 3037110 (fasting). The
exclusion excluded nobody. Codeset 42 is also in mmol/L over Mass-Concentration codes only, so its
unit filter can never match.

Every attribute below is the real vocabulary row (synthea23m, verified 2026-10-07). The logic under
test reaches its answer from component / property / scale / time and from the judge's answer --
which specimen and challenge the criterion states is the specimen critic's decision in production
(RFC-016 step 4) and a stub judge here. No criterion text is passed to the plan at all.
"""

from __future__ import annotations

import pytest

from src.services.loinc_specimen import (
    POINT_IN_TIME as PT,
)
from src.services.loinc_specimen import (
    LabTest,
    plan_specimen_refinement,
    refine_measurement_concept_set,
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


BLOOD = ("Serum or Plasma", "Blood", "Serum, Plasma or Blood")
FAST = "post CFst"


def accepting(*systems, challenges=(None,)):
    """A stub judge standing in for the specimen critic: accepts the options in these LOINC
    Systems under these challenges, and records what it was shown."""

    def judge(analyte, options):
        judge.calls.append((analyte, list(options)))
        return frozenset(
            o.key for o in options if o.system in systems and o.challenge in challenges
        )

    judge.calls = []
    return judge


def no_answer(_analyte, _options):
    return None


def _plan(members, *, judge, unit_code=None, numeric=True, vocab=None):
    vocab = vocab or FakeVocabulary(*GLUCOSE_FAMILY, *members)
    return plan_specimen_refinement(
        member_ids=[m.concept_id for m in members],
        lab_tests=vocab.lab_tests([m.concept_id for m in members]),
        unit_prop=unit_property(unit_code) if unit_code else None,
        numeric_bound=numeric,
        analyte_lab_tests=vocab.analyte_lab_tests,
        judge=judge,
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


class TestTheJudgeDecides:
    def test_should_show_the_judge_the_analyte_and_every_member_and_candidate_option(self):
        judge = accepting(*BLOOD)
        _plan(DELIVERED_GLUCOSE, judge=judge, unit_code="mg/dL")
        [(analyte, options)] = judge.calls
        assert analyte == "Glucose"
        assert {(o.system, o.challenge) for o in options} == {
            ("Blood", None),
            ("Plasma and CSF", None),
            ("Vitreous fluid", None),
            ("Serum, Plasma or Blood", None),
            ("Serum or Plasma", None),
            ("Serum or Plasma", FAST),
            ("Serum or Plasma", "2H post 75 g glucose PO"),
        }

    def test_should_decide_no_specimen_when_the_judge_gives_no_answer(self):
        """The critic failed: only the unit's property removes, nothing is added, and the plan
        says so instead of guessing a specimen."""
        plan = _plan(DELIVERED_GLUCOSE, judge=no_answer, unit_code="mg/dL")
        assert plan.judged is False
        assert plan.added == ()
        assert {cid for cid, _ in plan.removed} == {3004378}  # Relative Mass Concentration

    def test_should_keep_a_challenge_variant_only_when_the_judge_accepts_its_condition(self):
        fasting = _plan(
            DELIVERED_GLUCOSE, judge=accepting(*BLOOD, challenges=(None, FAST)), unit_code="mg/dL"
        )
        plain = _plan(DELIVERED_GLUCOSE, judge=accepting(*BLOOD), unit_code="mg/dL")
        assert 3037110 in {t.concept_id for t in fasting.added}
        assert 3037110 not in {t.concept_id for t in plain.added}
        assert 3025673 not in {t.concept_id for t in fasting.added}


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
            judge=accepting(*BLOOD),
            unit_code="mg/dL",
            vocab=FakeVocabulary(*members, *candidates),
        )
        assert {t.concept_id for t in plan.added} == {3004501}, glucagon_glucose

    def test_should_add_the_serum_code_and_drop_other_specimens_when_no_fast_is_accepted(self):
        plan = _plan(DELIVERED_GLUCOSE, judge=accepting(*BLOOD), unit_code="mg/dL")
        assert plan.declined is None
        assert {t.concept_id for t in plan.added} == {3004501}
        assert {cid for cid, _ in plan.removed} == {3004378, 3004676}

    def test_should_add_the_fasting_code_when_the_judge_accepts_the_fast(self):
        plan = _plan(
            DELIVERED_GLUCOSE, judge=accepting(*BLOOD, challenges=(None, FAST)), unit_code="mg/dL"
        )
        assert {t.concept_id for t in plan.added} == {3004501, 3037110}

    def test_should_swap_to_substance_codes_when_the_unit_is_mmol_per_litre(self):
        plan = _plan(
            DELIVERED_GLUCOSE, judge=accepting(*BLOOD, challenges=(None, FAST)), unit_code="mmol/L"
        )
        assert {t.concept_id for t in plan.added} == {3013826, 3018251}
        assert {cid for cid, _ in plan.removed} == {3000483, 3004378, 3004676, 44816672}

    def test_should_leave_the_set_unchanged_when_the_component_is_ambiguous(self):
        plan = _plan(
            [HBA1C, HBA1], judge=accepting(*BLOOD), unit_code="%", vocab=FakeVocabulary(HBA1C, HBA1)
        )
        assert plan.declined and "majority" in plan.declined
        assert plan.added == () and plan.removed == ()

    def test_should_keep_urine_members_when_the_judge_accepts_urine(self):
        plan = _plan([UACR], judge=accepting("Urine"), numeric=False, vocab=FakeVocabulary(UACR))
        assert plan.removed == ()

    def test_should_leave_an_all_urine_set_unchanged_when_urine_is_not_accepted(self):
        plan = _plan([UACR], judge=accepting(*BLOOD), numeric=False, vocab=FakeVocabulary(UACR))
        assert plan.declined and plan.removed == () and plan.added == ()

    def test_should_leave_the_set_unchanged_when_it_holds_no_loinc_lab_test(self):
        plan = plan_specimen_refinement(
            member_ids=[4213628],
            lab_tests={},
            unit_prop=None,
            numeric_bound=True,
            analyte_lab_tests=lambda _a: pytest.fail("must not query"),
            judge=lambda _a, _o: pytest.fail("must not judge"),
        )
        assert plan.declined and plan.added == () and plan.removed == ()

    def test_should_decline_when_the_unit_contradicts_every_member(self):
        plan = _plan(
            [EGFR], judge=accepting(*BLOOD), unit_code="mL/min", vocab=FakeVocabulary(EGFR)
        )
        assert plan.declined and plan.removed == () and plan.added == ()

    def test_should_drop_red_cell_members_and_keep_the_serum_code_when_the_bound_is_relative(self):
        plan = _plan(
            [ALT_SP, ALT_RBC], judge=accepting(*BLOOD), vocab=FakeVocabulary(ALT_SP, ALT_RBC)
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
            judge=accepting("Urine"),
            unit_code="ug/mg",
            vocab=FakeVocabulary(UACR, UACR_SPOT, UACR_24H),
        )
        assert {t.concept_id for t in plan.added} == {3034485}

    def test_should_not_add_a_study_mean_when_the_criterion_bounds_glucose(self):
        plan = _plan(
            DELIVERED_GLUCOSE,
            judge=accepting(*BLOOD),
            unit_code="mg/dL",
            vocab=FakeVocabulary(*GLUCOSE_FAMILY, GLU_MEAN, *DELIVERED_GLUCOSE),
        )
        assert 1002230 not in {t.concept_id for t in plan.added}
        assert 3004501 in {t.concept_id for t in plan.added}

    def test_should_keep_a_24_hour_member_the_mapper_chose(self):
        """Negative control: the time axis governs additions only; removal is specimen/property."""
        plan = _plan(
            [UACR, UACR_24H],
            judge=accepting("Urine"),
            unit_code="ug/mg",
            vocab=FakeVocabulary(UACR, UACR_SPOT, UACR_24H),
        )
        assert 3002827 not in {cid for cid, _ in plan.removed}


class TestBoundGate:
    """Refinement (b): a criterion with no numeric bound gains nothing; removal still applies."""

    def test_should_add_nothing_when_the_criterion_carries_no_bound(self):
        """CAROLINA cs3 'Glycaemic control insufficient' shape: one blood glucose, no threshold."""
        plan = _plan([GLU_BLD], judge=accepting(*BLOOD), numeric=False)
        assert plan.added == ()

    def test_should_still_drop_vitreous_when_the_criterion_carries_no_bound(self):
        plan = _plan(DELIVERED_GLUCOSE, judge=accepting(*BLOOD), numeric=False)
        assert plan.added == ()
        assert {cid for cid, _ in plan.removed} == {3004378, 3004676}

    def test_should_add_when_the_same_criterion_carries_a_bound(self):
        """Negative control for the gate above: the same set under a bound gains the serum code."""
        plan = _plan([GLU_BLD], judge=accepting(*BLOOD), unit_code="mg/dL")
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
            judge=accepting(*BLOOD),
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
            judge=lambda _a, _o: pytest.fail("must not judge"),
            value_filter={},
            vocabulary=Unreachable(),
        )
        assert refined == expression and plan.declined


class TestTheEligibilityBuilderApplies:
    """A refinement no production path calls is indistinguishable from one that does nothing."""

    @staticmethod
    def _build(domain, *, vocabulary, criterion=None, judge=None):
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
        if judge is not None:
            service._specimen_judge = lambda _criterion: judge
        criterion = criterion or {
            "sourceText": "glucose",
            "description": "Uncontrolled hyperglycemia",
            "domain": domain,
            "valueConstraint": {
                "op": "gt",
                "value": 240.0,
                "unitText": "mg/dL",
                "unitConceptId": 8840,
            },
            "window": {"start": -180, "end": 0},
            "logicType": "ABSENCE",
        }
        return service._build_seeded_eligibility_rule(
            criterion=criterion, codeset_id=10, exclusion=True
        )

    def test_should_ship_the_serum_code_not_the_vitreous_code_when_the_criterion_is_a_measurement(
        self,
    ):
        built = self._build(
            "Measurement",
            vocabulary=FakeVocabulary(*GLUCOSE_FAMILY, *DELIVERED_GLUCOSE),
            judge=accepting(*BLOOD),
        )
        ids = {i["concept"]["CONCEPT_ID"] for i in built["conceptSet"]["expression"]["items"]}
        assert ids == {3000483, 44816672, 3004501}

    def test_should_record_the_decision_gate_u_re_reads(self):
        built = self._build(
            "Measurement",
            vocabulary=FakeVocabulary(*GLUCOSE_FAMILY, *DELIVERED_GLUCOSE),
            judge=accepting(*BLOOD),
        )
        record = built["_specimen_decision"]
        assert record["judged"] is True and record["analyte"] == "Glucose"
        assert {a["system"] for a in record["accepted"]} == set(BLOOD)
        assert {cid for cid, _ in record["removed"]} == {3004378, 3004676}
        assert record["added"] == [3004501]

    def test_should_tell_the_critic_the_rows_line_and_its_annotated_specimen(self, monkeypatch):
        """EMPA-REG exclusion 1, real row (``tests/fixtures/rfc016_step4_rows.json``): its line
        names no body material, so the annotation records ``any``. The critic is told that,
        and the line; the seed and description reach it nowhere."""
        import json
        from copy import deepcopy
        from pathlib import Path

        from src.agents.agent2 import specimen_critic
        from src.services.criterion_annotation import ANNOTATION_KEY, validate_annotation

        rows = json.loads(
            (Path(__file__).resolve().parent / "fixtures" / "rfc016_step4_rows.json").read_text()
        )
        row = deepcopy(rows["empareg_exclusion_1"])
        fields, rejected = validate_annotation(
            {"record_requirement": "forbidden", "excepted_entities": [], "specimen": "any"},
            row["protocolLine"],
        )
        assert rejected == []
        row[ANNOTATION_KEY] = {"promptVersion": "test", "model": "stub", **fields}
        told = []

        def fake(**kwargs):
            told.append(kwargs)
            return frozenset(o.key for o in kwargs["options"] if o.system in BLOOD)

        monkeypatch.setattr(specimen_critic, "judge_specimen_options", fake)
        built = self._build(
            "Measurement",
            vocabulary=FakeVocabulary(*GLUCOSE_FAMILY, *DELIVERED_GLUCOSE),
            criterion=row,
        )
        [call] = told
        assert call["protocol_line"] == row["protocolLine"]
        assert (call["specimen"], call["specimen_span"]) == ("any", None)
        assert call["analyte"] == "Glucose"
        assert built["_specimen_decision"]["specimen"] == "any"

    def test_should_not_consult_the_vocabulary_when_the_criterion_is_not_a_measurement(self):
        class Unreachable:
            def lab_tests(self, _ids):
                raise AssertionError("vocabulary must not be queried")

        built = self._build(
            "Observation", vocabulary=Unreachable(), judge=lambda _a, _o: pytest.fail("no judge")
        )
        ids = [i["concept"]["CONCEPT_ID"] for i in built["conceptSet"]["expression"]["items"]]
        assert ids == [3000483, 3004378, 3004676, 44816672]
        assert built["_specimen_decision"] is None


def test_should_record_the_decision_under_the_codeset_the_emitted_rule_reads(monkeypatch):
    """Through ``_build_seeded_target_circe``: the record is keyed by the FINAL codeset id, the
    one gate (u) finds on the delivered Measurement criterion."""
    from src.services.tte_service import TTEService
    from src.utils.circe_lint import SPECIMEN_DECISIONS_KEY

    def recommend(seed, **_kwargs):
        if seed.strip() == "glucose":
            items = [
                {
                    **_circe_item(t),
                    "concept": {**_circe_item(t)["concept"], "DOMAIN_ID": "Measurement"},
                }
                for t in DELIVERED_GLUCOSE
            ]
            return {"name": "glucose", "domain": "Measurement", "expression": {"items": items}}
        return {
            "name": seed,
            "domain": "Drug",
            "expression": {
                "items": [
                    {
                        "concept": {
                            "CONCEPT_ID": 1594973,
                            "CONCEPT_NAME": seed,
                            "CONCEPT_CODE": "1",
                            "DOMAIN_ID": "Drug",
                            "VOCABULARY_ID": "RxNorm",
                            "CONCEPT_CLASS_ID": "Ingredient",
                        },
                        "includeDescendants": True,
                        "isExcluded": False,
                    }
                ]
            },
        }

    from src.agents.agent2 import workflow as agent2_workflow

    def no_workflow(*_args, **_kwargs):
        raise RuntimeError("Agent 2 is not built in this test")

    monkeypatch.setattr(agent2_workflow, "Agent2Workflow", no_workflow)
    svc = TTEService.__new__(TTEService)
    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", recommend)
    monkeypatch.setattr(
        svc, "_lab_test_vocabulary", lambda: FakeVocabulary(*GLUCOSE_FAMILY, *DELIVERED_GLUCOSE)
    )
    monkeypatch.setattr(svc, "_specimen_judge", lambda _criterion: accepting(*BLOOD))
    circe = svc._build_seeded_target_circe(
        {
            "targetCohortName": "empagliflozin",
            "inclusionCriteria": [],
            "exclusionCriteria": [
                {
                    "id": 1,
                    "domain": "Measurement",
                    "sourceText": "glucose",
                    "valueConstraint": {
                        "op": "gt",
                        "value": 240.0,
                        "unitText": "mg/dL",
                        "unitConceptId": 8840,
                    },
                    "window": {"start": -180, "end": 0},
                    "logicType": "ABSENCE",
                }
            ],
        }
    )
    [record] = circe[SPECIMEN_DECISIONS_KEY]
    reads = [
        body["CodesetId"]
        for rule in circe["InclusionRules"]
        for entry in rule["expression"]["CriteriaList"]
        for kind, body in entry["Criteria"].items()
        if kind == "Measurement"
    ]
    assert reads == [record["codesetId"]]
    assert (record["role"], record["criterionId"], record["judged"]) == ("exclusion", "1", True)
