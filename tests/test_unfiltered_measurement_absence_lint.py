"""An absence over a lab with no result filter excludes everyone who was ever tested.

`956d8e8` refused ARISTOTLE's platelet exclusion because its threshold carried a unit
the pipeline could not resolve. The same clinical error sits on PLATO by a route that
refusal cannot reach, because there is no bound there to refuse:

    PLATO, InclusionRule 18 'Thrombocytopenia'
      Measurement over codeset 33 -> 3006297 / 3007461 / 3024929, three platelet-count
      LOINC lab tests, and NO value condition at all
      Occurrence {Type: 0, Count: 0}

`Occurrence {0, 0}` over a measurement concept set with no value filter says "exclude
anyone who has ever had this test", not "exclude anyone whose result was abnormal". The
protocol says the second: "Known clinically important thrombocytopenia".

Why the two checks beside this one cannot see it:

  * `unstated-unit-bound` needs a bound whose unit was dropped. Nothing was dropped
    here -- nothing was ever there.
  * `asserted_bound_missing_criteria` needs a NAME that asserts a bound, and reads a
    broken promise. Neither 'Thrombocytopenia' nor its rule name promises anything;
    the name is a diagnosis, and a diagnosis needs no threshold.
  * `unreadable_value_filter_criteria` needs a filter the table cannot read, and
    `domain_mismatched_criteria` needs a concept set the table cannot join. The filter
    is absent and the join is perfect.

Measured: all seven lints in `src.utils.circe_lint` return zero findings mentioning
Thrombocytopenia on `output/site_gap/2026-09-14/DELIVERY/plato_{treatment,comparator}
.circe.json`, which is how it shipped in every delivery from 2026-09-10 to 2026-09-14.

The corpus decides the shape, not PLATO
---------------------------------------
Swept across every produced corpus (`output/site_gap/*/{circe_new,DELIVERY}`) and the
18 hand-built TROY v1.1 files under `data/gold/`, `Measurement` + `Occurrence {0,0}` +
no value condition occurs on nine distinct concept sets:

    produced  'Thrombocytopenia'                            PLATO
    produced  'Hyperglycemia'                               LEADER   (2026-09-11/12)
    produced  'Elevated HbA1c'                              LEADER
    produced  'Alanine aminotransferase (ALT) elevation'    CAROLINA (2026-09-10)
    produced  'Aspartate aminotransferase (AST) elevation'  CAROLINA (2026-09-10)
    produced  'Total Bilirubin elevation'                   CAROLINA (2026-09-10)
    produced  'Hemoglobin level below threshold'            PLATO    (2026-09-10)
    gold      '[TROY lab] Systolic blood pressure (SBP)'    ARISTOTLE
    gold      '[TROY lab] Diastolic blood pressure (DBP)'   ARISTOTLE

Not one of the nine is a criterion about whether a test was performed. Every one names
a clinical state or an explicitly bounded lab -- 'Hemoglobin level below threshold'
carries no threshold, 'Total Bilirubin elevation' no bound, and gold's two sit under
'Persistent, uncontrolled hypertension (systolic BP > 180 mm Hg, or diastolic BP > 100
mm Hg)' with the numbers only in the rule name. The hand-built reference carries the
same defect, which is the strongest evidence available that the shape is not a
convention somebody chose.

The exception this check deliberately does NOT try to separate
--------------------------------------------------------------
A criterion whose subject really is the testing event -- "no pregnancy test on record",
"never had an HbA1c measured" -- has exactly this structure and is correct. Three such
criteria exist in the corpus (CARMELINA exclusion 31, CAROLINA 34, EMPA-REG 23, all
"Pre-menopausal women ... nursing or pregnant ... periodic pregnancy testing"), and the
check is silent on all three -- but not because it recognised them. It is silent
because they are emitted as `Observation` criteria, and this check judges only
`Measurement`, the one CDM table whose rows carry a `value_as_number` and therefore the
one where "no value condition" is a LOSS rather than a shape.

That restriction is a real limit, not a solution: a legitimate "never measured"
criterion emitted as `Measurement` would fire. Two discriminators were measured over
all 83 distinct Measurement criterion/concept-set rows in the produced 2026-09-14 batch
plus `data/gold/`, and one of them works:

  * token disjointness between the concept-set name and its member concept names --
    REJECTED. Six false positives ('[TROY lab] Platelet count', '[TROY] TnT',
    '[TROY] TnI', 'eGFR', 'CK-MB', 'Biomarker'), and it misses gold's two.
  * the concept-set name resolving, by name or synonym, to a standard OMOP concept in
    the Condition domain and not in Measurement -- fires on 'Thrombocytopenia' and
    'Hyperglycemia', on 0 of the other 79 rows ('Serum creatinine', 'Systolic blood
    pressure', 'Platelet count', 'BMI', 'Total bilirubin' all resolve to Measurement).

The second is not wired in, and the reason is the instrument. This check makes the
delivery FAIL; a human then reads the finding. A false positive costs one review line.
Wiring a live `concept` / `concept_synonym` lookup into a gate that today needs no
database would buy that precision at the cost of a check that goes silent whenever the
database is unreachable -- a check that cannot fail is indistinguishable from one never
wired in, and that trade is the wrong way round for a gate.

For the same reason this is NOT a build-time refusal. `refuse_unstated_unit_bound`
refuses because the bound is unrecoverable: the unit text was garbage and converting it
is a clinical decision with nowhere auditable to live. Nothing is unrecoverable here.
The seed still says 'Thrombocytopenia' and the vocabulary still holds 'Thrombocytopenic
disorder' (432870, SNOMED, standard Condition) under that exact synonym; gold repairs
the identical criterion by emitting BOTH a bounded `Measurement` over '[TROY lab]
Platelet count' AND a `ConditionOccurrence` over '[TROY condition] Thrombocytopenia'.
Refusing would turn a repairable mapping error into an irreversible loss.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

# `_criterion_locations` is the walk the check itself uses. Re-implementing it here to
# count the corpus would let a hole in the walk hide from the very test that measures
# coverage.
from src.utils.circe_lint import (
    VALUE_CONDITION_ATTRIBUTES,
    _criterion_locations,
    unfiltered_measurement_absence_criteria,
)

REPO = pathlib.Path(__file__).resolve().parents[1]
BATCH = REPO / "output" / "site_gap" / "2026-09-14" / "DELIVERY"
GOLD = REPO / "data" / "gold"

#: PLATO's platelet concept set, verbatim from the delivered file.
PLATELET_CONCEPTS = [
    (3006297, "Platelets [#/volume] in Plasma"),
    (3007461, "Platelets [#/volume] in Blood"),
    (3024929, "Platelets [#/volume] in Blood by Automated count"),
]


def _concept_set(codeset_id: int, name: str, concepts: list[tuple[int, str]], domain: str):
    return {
        "id": codeset_id,
        "name": name,
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": concept_id,
                        "CONCEPT_NAME": concept_name,
                        "DOMAIN_ID": domain,
                        "VOCABULARY_ID": "LOINC",
                        "CONCEPT_CLASS_ID": "Lab Test",
                        "STANDARD_CONCEPT": "S",
                        "CONCEPT_CODE": "",
                        "INVALID_REASON": None,
                    },
                    "includeDescendants": True,
                    "includeMapped": False,
                    "isExcluded": False,
                }
                for concept_id, concept_name in concepts
            ]
        },
    }


def _rule(
    rule_name: str,
    codeset_id: int,
    *,
    criteria_type: str = "Measurement",
    occurrence: tuple[int, int] = (0, 0),
    value: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One InclusionRule in the shape PLATO's rule 18 actually carries."""
    payload: dict[str, Any] = {"CodesetId": codeset_id}
    payload.update(value or {})
    return {
        "name": rule_name,
        "expression": {
            "Type": "ALL",
            "CriteriaList": [],
            "Groups": [
                {
                    "Type": "ALL",
                    "CriteriaList": [
                        {
                            "Criteria": {criteria_type: payload},
                            "StartWindow": {
                                "Start": {"Days": 9999, "Coeff": -1},
                                "End": {"Days": 0, "Coeff": 1},
                            },
                            "Occurrence": {"Type": occurrence[0], "Count": occurrence[1]},
                        }
                    ],
                    "Groups": [],
                }
            ],
        },
    }


def _expression(rules: list[dict[str, Any]], concept_sets: list[dict[str, Any]]):
    return {
        "ConceptSets": concept_sets,
        "PrimaryCriteria": {"CriteriaList": [{"DrugExposure": {"CodesetId": 1}}]},
        "InclusionRules": rules,
    }


def _plato_rule_18():
    return _expression(
        [_rule("Thrombocytopenia", 33)],
        [_concept_set(33, "Thrombocytopenia", PLATELET_CONCEPTS, "Measurement")],
    )


class TestPlatoRuleEighteenReproduced:
    """The defect itself, and the three one-field edits that make it correct. Each
    control changes exactly one thing, so a passing test says which field the check is
    actually reading."""

    def test_should_fire_when_a_measurement_absence_carries_no_value_condition(self):
        findings = unfiltered_measurement_absence_criteria(_plato_rule_18())
        assert len(findings) == 1
        assert "Thrombocytopenia" in findings[0]
        assert "codeset 33" in findings[0]

    def test_should_stay_silent_when_the_same_criterion_carries_its_bound(self):
        """Gold's repair of this exact criterion: `[TROY lab] Platelet count` with
        `ValueAsNumber {100, lte}`. Nothing else differs, so silence here is the check
        reading the value condition rather than the name."""
        expression = _expression(
            [
                _rule(
                    "Thrombocytopenia",
                    33,
                    value={"ValueAsNumber": {"Value": 100, "Op": "lte"}},
                )
            ],
            [_concept_set(33, "Thrombocytopenia", PLATELET_CONCEPTS, "Measurement")],
        )
        assert unfiltered_measurement_absence_criteria(expression) == []

    @pytest.mark.parametrize(
        "attribute",
        sorted(VALUE_CONDITION_ATTRIBUTES),
        ids=sorted(VALUE_CONDITION_ATTRIBUTES),
    )
    def test_should_stay_silent_on_every_value_condition_attribute(self, attribute):
        """Structural and exact, the same predicate `asserted_bound_missing_criteria`
        uses, so a criterion whose bound survived in ANY readable form is never flagged
        and the two checks cannot disagree about what "filtered" means."""
        expression = _expression(
            [_rule("Thrombocytopenia", 33, value={attribute: {"Value": 1}})],
            [_concept_set(33, "Thrombocytopenia", PLATELET_CONCEPTS, "Measurement")],
        )
        assert unfiltered_measurement_absence_criteria(expression) == []

    def test_should_stay_silent_when_the_occurrence_is_a_presence(self):
        """A presence criterion over an unfiltered lab is over-broad in the other
        direction -- it KEEPS everyone who was tested. Real and uncaught (PLATO's
        'Biomarker', codeset 14), but a different consequence with a different repair,
        so it is out of scope here rather than folded in."""
        expression = _expression(
            [_rule("Thrombocytopenia", 33, occurrence=(2, 1))],
            [_concept_set(33, "Thrombocytopenia", PLATELET_CONCEPTS, "Measurement")],
        )
        assert unfiltered_measurement_absence_criteria(expression) == []

    def test_should_stay_silent_when_the_criteria_type_is_not_measurement(self):
        """The pregnancy shape. `Measurement` is the one CDM table whose rows carry a
        `value_as_number`, so it is the only one where an absent value condition is a
        LOSS; on any other type there was never a result to filter."""
        expression = _expression(
            [_rule("Pregnancy/Contraception Risk", 33, criteria_type="Observation")],
            [_concept_set(33, "Pregnancy/Contraception Risk", PLATELET_CONCEPTS, "Measurement")],
        )
        assert unfiltered_measurement_absence_criteria(expression) == []


class TestWhatTheFindingHasToSay:
    def test_should_name_the_member_concepts_so_a_reader_can_judge_the_name(self):
        """The whole verdict is whether the concept set's NAME describes what its
        CONCEPTS measure. A finding that quotes only the name makes the reader reopen
        the file to answer the only question it asks."""
        findings = unfiltered_measurement_absence_criteria(_plato_rule_18())
        assert "Platelets [#/volume] in Plasma" in findings[0]

    def test_should_say_what_the_emitted_rule_actually_selects(self):
        findings = unfiltered_measurement_absence_criteria(_plato_rule_18())
        assert "ever had" in findings[0]

    def test_should_report_one_finding_per_criterion_not_per_concept(self):
        findings = unfiltered_measurement_absence_criteria(_plato_rule_18())
        assert len(findings) == 1

    def test_should_survive_a_codeset_with_no_matching_concept_set(self):
        """Silent on what the file cannot settle, like the two checks beside it -- but
        the criterion is still reported, because the missing concept set is a different
        defect and losing the finding to it would hide this one."""
        expression = _expression([_rule("Thrombocytopenia", 999)], [])
        findings = unfiltered_measurement_absence_criteria(expression)
        assert len(findings) == 1
        assert "codeset 999" in findings[0]


@pytest.mark.skipif(not BATCH.is_dir(), reason=f"delivered batch not present: {BATCH}")
class TestAgainstTheDeliveredBatch:
    """The measurement that decides whether the check is worth anything. A green
    self-test over shapes this file wrote itself proves nothing about the corpus it was
    written for -- `docs/mistakes.md`, and the reason this class exists."""

    @staticmethod
    def _findings() -> dict[str, list[str]]:
        return {
            path.stem.replace(".circe", ""): unfiltered_measurement_absence_criteria(
                json.loads(path.read_text())
            )
            for path in sorted(BATCH.glob("*.circe.json"))
        }

    def test_should_fire_on_plato_thrombocytopenia_in_both_arms(self):
        findings = self._findings()
        for arm in ("plato_treatment", "plato_comparator"):
            assert len(findings[arm]) == 1, findings[arm]
            assert "Thrombocytopenia" in findings[arm][0]
            assert "Platelets [#/volume]" in findings[arm][0]

    def test_should_fire_on_leader_elevated_hba1c_in_both_arms(self):
        """The second produced instance, and the one `asserted_bound_missing_criteria`
        already flags. Both checks firing on one row is not a duplicate: that check says
        the name promised a bound, this one says what the emitted rule selects without
        it. A reader needs the second sentence to know the size of the loss."""
        findings = self._findings()
        for arm in ("leader_treatment", "leader_comparator"):
            assert len(findings[arm]) == 1, findings[arm]
            assert "Elevated HbA1c" in findings[arm][0]

    def test_should_stay_silent_on_the_eight_other_delivered_files(self):
        findings = self._findings()
        noisy = ("plato_", "leader_")
        quiet = {name: f for name, f in findings.items() if not name.startswith(noisy)}
        assert len(quiet) == 8
        assert all(f == [] for f in quiet.values()), quiet

    def test_should_stay_silent_on_the_three_pregnancy_absence_criteria(self):
        """The legitimate case the check must not destroy, on real data. CARMELINA 31,
        CAROLINA 34 and EMPA-REG 23 are absence criteria whose concept sets DO carry
        Measurement concepts (a pregnancy test among them) and whose subject genuinely
        is whether an event happened."""
        for stem in ("carmelina", "carolina", "empa-reg"):
            for arm in ("treatment", "comparator"):
                path = BATCH / f"{stem}_{arm}.circe.json"
                expression = json.loads(path.read_text())
                pregnancy = [
                    rule["name"]
                    for rule in expression["InclusionRules"]
                    if "regnan" in rule.get("name", "")
                ]
                assert pregnancy, f"{path.name}: no pregnancy rule to control on"
                assert unfiltered_measurement_absence_criteria(expression) == [], path.name

    def test_should_be_the_only_check_that_sees_the_plato_row(self):
        """The claim the whole module rests on: every other lint is silent on it. If one
        of them ever starts firing, this check is redundant and should be deleted rather
        than left to double-report."""
        from src.utils import circe_lint

        expression = json.loads((BATCH / "plato_treatment.circe.json").read_text())
        others = (
            circe_lint.noop_exclusion_rules,
            circe_lint.contradictory_absence_rules,
            circe_lint.domain_mismatched_criteria,
            circe_lint.unreadable_value_filter_criteria,
            circe_lint.partially_readable_criteria,
            circe_lint.asserted_bound_missing_criteria,
        )
        for check in others:
            hits = [f for f in check(expression) if "Thrombocytopenia" in str(f)]
            assert hits == [], f"{check.__name__} also fires: {hits}"

    def test_should_count_every_measurement_criterion_it_passed_over(self):
        """The denominator. Without it, "2 findings" is compatible with a check that
        looked at two criteria and with one that looked at a hundred."""
        judged = 0
        for path in sorted(BATCH.glob("*.circe.json")):
            expression = json.loads(path.read_text())
            for _where, entry in _criterion_locations(expression):
                body = entry.get("Criteria")
                body = body if isinstance(body, dict) else entry
                judged += sum(
                    1
                    for ctype, payload in body.items()
                    if ctype == "Measurement"
                    and isinstance(payload, dict)
                    and "CodesetId" in payload
                )
        total = sum(len(f) for f in self._findings().values())
        assert judged >= 60, judged
        assert total == 4, self._findings()


@pytest.mark.skipif(not GOLD.is_dir(), reason=f"gold corpus not present: {GOLD}")
class TestAgainstTheHandBuiltGold:
    """An independent corpus nobody in this pipeline wrote. It carries the same defect,
    which is what makes the shape a clinical error rather than a house convention."""

    @staticmethod
    def _gold(trial: str) -> list[dict[str, Any]]:
        return [json.loads(p.read_text()) for p in sorted((GOLD / trial).glob("*.json"))]

    def test_should_fire_on_the_gold_uncontrolled_hypertension_rule(self):
        """TROY v1.1 ARISTOTLE exclusion #5 emits `{CodesetId: 98}` and `{CodesetId: 99}`
        -- SBP and DBP -- with no bound at all, under a rule NAMED 'systolic BP > 180 mm
        Hg, or diastolic BP > 100 mm Hg'."""
        for expression in self._gold("ARISTOTLE"):
            findings = unfiltered_measurement_absence_criteria(expression)
            assert len(findings) == 2, findings
            assert all("blood pressure" in f.lower() for f in findings), findings

    def test_should_stay_silent_on_the_gold_platelet_criterion(self):
        """The control that matters most: the SAME analyte as PLATO's defect, in the
        same corpus, absence, and correct -- `[TROY lab] Platelet count` carrying
        `ValueAsNumber {100, lte}`. If this fired, the check would be reading the
        concept set rather than the value condition."""
        for expression in self._gold("ARISTOTLE"):
            findings = unfiltered_measurement_absence_criteria(expression)
            assert not any("Platelet" in f for f in findings), findings

    def test_should_stay_silent_on_the_other_five_gold_trials(self):
        for trial in ("CARMELINA", "CAROLINA", "EMPA-REG OUTCOME", "LEADER", "PLATO"):
            for expression in self._gold(trial):
                assert unfiltered_measurement_absence_criteria(expression) == [], trial


class TestTheDeliveryGateFailsOnIt:
    """It FAILS a delivery rather than warning, on the same argument the check beside it
    makes: the emitted rule is ACTIVELY WRONG rather than merely absent, and nothing in
    the file says so. The site-gap fixture run that motivated this check reports PLATO's
    rule removing 63.1% / 56.3% / 38.7% of each site's population; that figure is quoted
    for scale and is NOT re-measured anywhere in this module, because every CDM on this
    host is synthetic and a patient count from one is not evidence about a site."""

    def test_should_fail_the_delivery_and_name_the_criterion(self, monkeypatch, tmp_path, capsys):
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        expression = _expression(
            [
                {"name": "rule one", "expression": {"Type": "ALL", "CriteriaList": []}},
                _rule("Thrombocytopenia", 33),
            ],
            [
                _concept_set(1, "ticagrelor", [(1, "ticagrelor")], "Drug"),
                _concept_set(33, "Thrombocytopenia", PLATELET_CONCEPTS, "Measurement"),
            ],
        )
        expression["ConceptSets"][0]["expression"]["items"][0]["concept"].update(
            {"VOCABULARY_ID": "RxNorm", "CONCEPT_CLASS_ID": "Ingredient", "CONCEPT_CODE": "1"}
        )
        study = {
            "id": 2,
            "name": "Study 2",
            "comparisonMode": "target_minus_treatment",
            "treatmentArms": [{"name": "ticagrelor"}, {"name": "clopidogrel"}],
            "eligibility": {
                "inclusionCriteria": [],
                "exclusionCriteria": [],
                "structuredExpression": json.loads(json.dumps(expression)),
            },
        }
        core = study["eligibility"]["structuredExpression"]
        for role in ("treatment", "comparator"):
            (tmp_path / f"plato_{role}.circe.json").write_text(json.dumps(core))
        store = tmp_path / "studies.json"
        store.write_text(json.dumps([study]))

        from scripts.verify_circe_delivery import main

        rc = main(["--dir", str(tmp_path), "--store", str(store), "--map", "plato=2"])
        out = capsys.readouterr().out
        assert rc == 1, out
        assert "unfiltered measurement absence (1)" in out
        assert "Thrombocytopenia" in out
