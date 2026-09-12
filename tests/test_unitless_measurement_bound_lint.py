"""A numeric bound with no unit ships; one with an unresolvable unit is refused.

The pipeline already refuses a criterion whose unit string it cannot map to a UCUM
concept -- `unstated-unit-bound`, raised in `src.services.value_constraint`. The
recorded reason says exactly what is wrong with it::

    'Platelet count' carries lte 100000.0 '/ mm', and '/ mm' resolves to no UCUM unit
    concept, so the bound would be emitted as a bare number and compared against
    whatever scale the CDM stores.

A criterion that never stated a unit at all produces the same bare number and is not
refused. The safe case -- a unit was written, the pipeline could not read it, and the
criterion is dropped rather than shipped wrong -- is punished; the dangerous case
ships. Measured on `output/site_gap/2026-09-14/DELIVERY` (12 files), over every
`Measurement` leaf::

    ValueAsNumber   Unit   RangeHighRatio   count
        True        True        False         40
        False       False       True          32
        False       False       False         10
        True        False       False         10     <- this check

The ten are five distinct concept sets, all LEADER, each appearing on both the
treatment and the comparator arm::

    codeset  6   'Ankle-brachial index'   {"Value": 0.9,  "Op": "lt"}
    codeset  9   'eGFR'                   {"Value": 60.0, "Op": "lt"}
    codeset 17   'Glycated hemoglobin'    {"Value": 7.0,  "Op": "gte"}
    codeset 18   'Hemoglobin A1c'         {"Value": 7.0,  "Op": "gte"}
    codeset 33   'Calcitonin'             {"Value": 50.0, "Op": "gte"}

HbA1c is the concrete harm. 7.0% is 53 mmol/mol, so a bare `>= 7.0` against a site
storing IFCC units passes essentially every patient rather than none -- the failure is
silent and inverted, not empty. Codesets 17 and 18 make the ambiguity internal to the
file: both hold 4197971 `HbA1c measurement (DCCT aligned)` (reported in %) AND
44793001 `Hb A1c ... IFCC` (reported in mmol/mol). The set names both unit systems and
the criterion picks neither.

Why the checks beside this one cannot see it
--------------------------------------------
  * `unreadable_value_filter_criteria` needs an attribute the CDM table cannot read.
    `Measurement` reads both `ValueAsNumber` and `Unit`; nothing here is unreadable.
  * `asserted_bound_missing_criteria` needs a NAME asserting a bound and finds the
    bound gone. The bound is present -- it is the unit that is missing, and no
    concept-set name in the corpus asserts a unit.
  * `unfiltered_measurement_absence_criteria` needs no value condition at all. There
    is one.
  * `domain_mismatched_criteria` needs a set the table cannot join. The join is
    perfect.

Measured: the delivery gate returns FAIL on both LEADER files for six other reasons
and not one of them mentions codesets 6, 9, 17, 18 or 33.

Ankle-brachial index is the control, not an oversight
-----------------------------------------------------
ABI is a quotient of ankle systolic pressure over brachial systolic pressure. Both are
mmHg, the unit cancels, and `< 0.9` means one thing everywhere. A unit filter on it
would be wrong, so it is allowlisted by concept id in
`DIMENSIONLESS_MEASUREMENT_CONCEPTS` -- see that table's own comment for why the
allowlist is keyed on concept ids rather than on concept-set names, and for the three
corpus candidates that were examined and rejected.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from src.utils.circe_lint import (
    DIMENSIONLESS_MEASUREMENT_CONCEPTS,
    _criterion_locations,
    unitless_measurement_bound_criteria,
)

REPO = pathlib.Path(__file__).resolve().parents[1]
BATCH = REPO / "output" / "site_gap" / "2026-09-14" / "DELIVERY"

#: LEADER codeset 18, verbatim from the delivered file. Two of the five members name
#: the two unit systems the criterion fails to choose between.
HBA1C_CONCEPTS = [
    (3004410, "Hemoglobin A1c/Hemoglobin.total in Blood"),
    (3005446, "Hemoglobin A1/Hemoglobin.total in Blood"),
    (3034639, "Hemoglobin A1c [Mass/volume] in Blood"),
    (4197971, "HbA1c measurement (DCCT aligned)"),
    (44793001, "Hb A1c (Haemoglobin A1c) measurement - IFCC (International F"),
]

#: LEADER codeset 6, verbatim. All three members are ratios or computed indices.
ABI_CONCEPTS = [
    (3016205, "Systolic blood pressure Posterior tibial artery/Brachial artery"),
    (46237026, "Ankle-brachial index"),
    (46237027, "Cardio-ankle vascular index Calculated"),
]

#: The `%` unit filter the same pipeline attaches to the same analyte on CARMELINA,
#: CAROLINA and EMPA-REG. Verbatim from `carmelina_treatment.circe.json`.
PERCENT_UNIT = [
    {
        "CONCEPT_CODE": "%",
        "CONCEPT_ID": 8554,
        "CONCEPT_NAME": "percent",
        "DOMAIN_ID": "Unit",
        "VOCABULARY_ID": "UCUM",
    }
]


def _concept_set(codeset_id: int, name: str, concepts: list[tuple[int, str]]):
    return {
        "id": codeset_id,
        "name": name,
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": concept_id,
                        "CONCEPT_NAME": concept_name,
                        "DOMAIN_ID": "Measurement",
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
    value: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One InclusionRule in the shape LEADER's HbA1c rule actually carries."""
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
                            "Occurrence": {"Type": 2, "Count": 1},
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


def _leader_hba1c(value: dict[str, Any] | None = None):
    if value is None:
        value = {"ValueAsNumber": {"Value": 7.0, "Op": "gte"}}
    return _expression(
        [_rule("Hemoglobin A1c", 18, value=value)],
        [_concept_set(18, "Hemoglobin A1c", HBA1C_CONCEPTS)],
    )


class TestLeaderHbA1cReproduced:
    """The defect itself, and the one-field edits that make it correct. Each control
    changes exactly one thing, so a passing test says which field is being read."""

    def test_should_fire_when_a_measurement_bound_carries_no_unit(self):
        findings = unitless_measurement_bound_criteria(_leader_hba1c())
        assert len(findings) == 1
        assert "Hemoglobin A1c" in findings[0]
        assert "codeset 18" in findings[0]

    def test_should_stay_silent_when_the_same_criterion_carries_its_unit(self):
        """The repair the same pipeline already applies to the same analyte on three
        other trials. Nothing else differs, so silence here is the check reading the
        Unit field rather than the name."""
        expression = _leader_hba1c(
            value={"ValueAsNumber": {"Value": 7.0, "Op": "gte"}, "Unit": PERCENT_UNIT}
        )
        assert unitless_measurement_bound_criteria(expression) == []

    def test_should_fire_when_the_unit_filter_is_present_but_empty(self):
        """`Unit: []` renders no unit predicate, so the bare number ships exactly as
        it does with the key absent. Keying on presence rather than on content would
        make an empty list a silent exemption."""
        expression = _leader_hba1c(
            value={"ValueAsNumber": {"Value": 7.0, "Op": "gte"}, "Unit": []}
        )
        assert len(unitless_measurement_bound_criteria(expression)) == 1

    def test_should_stay_silent_when_there_is_no_numeric_bound(self):
        """No `ValueAsNumber`, nothing to misread. The absent-value-condition defect is
        `unfiltered_measurement_absence_criteria`'s, with its own repair."""
        assert unitless_measurement_bound_criteria(_leader_hba1c(value={})) == []

    def test_should_stay_silent_when_the_criteria_type_is_not_measurement(self):
        """A scope boundary, NOT a claim that the defect stops at `Measurement`.
        `Observation` reads `ValueAsNumber` and `Unit` too and carries the same defect
        in this very batch -- see
        `TestTheObservationLeavesThisCheckDoesNotCover` below, which counts them."""
        expression = _expression(
            [
                _rule(
                    "Hemoglobin A1c",
                    18,
                    criteria_type="Observation",
                    value={"ValueAsNumber": {"Value": 7.0, "Op": "gte"}},
                )
            ],
            [_concept_set(18, "Hemoglobin A1c", HBA1C_CONCEPTS)],
        )
        assert unitless_measurement_bound_criteria(expression) == []


class TestTheDimensionlessAllowlist:
    """Ankle-brachial index is the case a unit filter would make WRONG. If this check
    flagged it the repair would be to invent a unit for a quantity that has none."""

    def test_should_stay_silent_on_ankle_brachial_index(self):
        expression = _expression(
            [_rule("Ankle-brachial index", 6, value={"ValueAsNumber": {"Value": 0.9, "Op": "lt"}})],
            [_concept_set(6, "Ankle-brachial index", ABI_CONCEPTS)],
        )
        assert unitless_measurement_bound_criteria(expression) == []

    def test_should_fire_when_one_member_of_the_set_is_not_dimensionless(self):
        """The exemption is ALL-members, not ANY. A set mixing a bare ratio with a
        dimensioned analyte has no single scale, so the bare number is ambiguous again
        -- and a mapper that widened a ratio set with a lab test is exactly how that
        happens."""
        mixed = ABI_CONCEPTS + [(3004249, "Systolic blood pressure")]
        expression = _expression(
            [_rule("Ankle-brachial index", 6, value={"ValueAsNumber": {"Value": 0.9, "Op": "lt"}})],
            [_concept_set(6, "Ankle-brachial index", mixed)],
        )
        assert len(unitless_measurement_bound_criteria(expression)) == 1

    def test_should_not_exempt_an_empty_concept_set(self):
        """`all()` over an empty sequence is True, which would silently exempt every
        set whose members were lost. The emptiness is a different defect; exempting on
        it would hide this one."""
        expression = _expression(
            [_rule("Ankle-brachial index", 6, value={"ValueAsNumber": {"Value": 0.9, "Op": "lt"}})],
            [_concept_set(6, "Ankle-brachial index", [])],
        )
        assert len(unitless_measurement_bound_criteria(expression)) == 1

    def test_should_key_the_allowlist_on_concept_ids(self):
        """A name-keyed allowlist is defeated by a respelling, and this corpus supplies
        three spellings of one analyte ('Glycated hemoglobin', 'Hemoglobin A1c',
        'Glycosylated haemoglobin') and three of another ('eGFR', 'Estimated
        glomerular filtration rate', 'Glomerular Filtration Rate')."""
        assert all(isinstance(key, int) for key in DIMENSIONLESS_MEASUREMENT_CONCEPTS)

    def test_should_record_a_written_reason_for_every_allowlist_entry(self):
        """An allowlist entry suppresses a soundness failure. One with no recorded
        reason cannot be audited, and cannot be argued with."""
        for concept_id, (name, reason) in DIMENSIONLESS_MEASUREMENT_CONCEPTS.items():
            assert name.strip(), concept_id
            assert len(reason.strip()) > 40, concept_id

    @pytest.mark.parametrize(
        "concept_id, label",
        [
            (3038553, "BMI [Ratio] -- kg/m2, and the set also holds a [Percentile]"),
            (3020682, "Albumin/Creatinine [Ratio] -- mg/g or mg/mmol, ~8.8x apart"),
            (3004410, "HbA1c/Hemoglobin.total -- % or mmol/mol"),
        ],
    )
    def test_should_not_allowlist_a_rejected_candidate(self, concept_id, label):
        """The three corpus candidates whose LOINC names read as ratios and which are
        NOT dimensionless. Each was found by the same scan that found ABI; a check
        derived from that scan alone would have admitted all three."""
        assert concept_id not in DIMENSIONLESS_MEASUREMENT_CONCEPTS, label


class TestWhatTheFindingHasToSay:
    def test_should_quote_the_bound_that_ships_unitless(self):
        findings = unitless_measurement_bound_criteria(_leader_hba1c())
        assert "gte" in findings[0] and "7.0" in findings[0]

    def test_should_name_the_member_concepts_so_a_reader_can_judge_the_scale(self):
        findings = unitless_measurement_bound_criteria(_leader_hba1c())
        assert "Hemoglobin A1c/Hemoglobin.total in Blood" in findings[0]

    def test_should_say_what_the_emitted_rule_actually_compares_against(self):
        findings = unitless_measurement_bound_criteria(_leader_hba1c())
        assert "scale" in findings[0]

    def test_should_report_one_finding_per_criterion_not_per_concept(self):
        findings = unitless_measurement_bound_criteria(_leader_hba1c())
        assert len(findings) == 1

    def test_should_survive_a_codeset_with_no_matching_concept_set(self):
        """Reported rather than dropped, like the checks beside it -- the missing
        concept set is a different defect, and losing the finding to it would hide
        this one. It is also the conservative direction: an unknown set cannot be
        shown to be dimensionless."""
        expression = _expression(
            [_rule("Hemoglobin A1c", 999, value={"ValueAsNumber": {"Value": 7.0, "Op": "gte"}})],
            [],
        )
        findings = unitless_measurement_bound_criteria(expression)
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
            path.name: unitless_measurement_bound_criteria(json.loads(path.read_text()))
            for path in sorted(BATCH.glob("*.circe.json"))
        }

    def test_should_fire_on_leaders_hba1c_in_both_arms(self):
        findings = self._findings()
        for arm in ("leader_treatment.circe.json", "leader_comparator.circe.json"):
            joined = " | ".join(findings[arm])
            assert "codeset 18" in joined, arm
            assert "Hemoglobin A1c" in joined, arm

    def test_should_fire_on_egfr_and_calcitonin_in_both_arms(self):
        """The other two whose scale is genuinely ambiguous. eGFR carries
        mL/min/1.73m2 on CAROLINA and EMPA-REG in this same batch; calcitonin's own
        set holds both `[Mass/volume]` and `[Moles/volume]` LOINC concepts."""
        findings = self._findings()
        for arm in ("leader_treatment.circe.json", "leader_comparator.circe.json"):
            joined = " | ".join(findings[arm])
            assert "codeset 9" in joined, arm
            assert "codeset 33" in joined, arm

    def test_should_not_fire_on_ankle_brachial_index(self):
        """Matched on the finding's SUBJECT -- ``over codeset 6 'Ankle-brachial
        index'`` -- not on the substring. The rule ABI sits in is a four-member group
        whose name quotes every member, so 'Ankle-brachial' appears inside the eGFR
        finding's `where` and a substring test would fail on a correct check.

        That rule name is worth reading for a second reason: it ends
        `eGFR < 60 mL/min/1.73m2`. The unit was present in the criterion's own name and
        did not reach the emitted filter."""
        findings = self._findings()
        for arm in ("leader_treatment.circe.json", "leader_comparator.circe.json"):
            subjects = [f.split(": ", 1)[1].split(" bounds ")[0] for f in findings[arm]]
            assert "Measurement over codeset 6 'Ankle-brachial index'" not in subjects, arm
            assert not any("codeset 6 " in s for s in subjects), arm

    def test_should_fire_on_exactly_four_criteria_per_leader_arm(self):
        """Five unitless leaves per arm, one allowlisted. A count rather than a
        membership test, so a check that started flagging the other 82 Measurement
        leaves would fail here rather than pass quietly."""
        findings = self._findings()
        assert len(findings["leader_treatment.circe.json"]) == 4
        assert len(findings["leader_comparator.circe.json"]) == 4

    def test_should_be_silent_on_every_file_that_carries_its_units(self):
        """The other ten files hold 40 `ValueAsNumber` + `Unit` leaves between them.
        A check that fired on any of those would be reading something other than the
        Unit field."""
        findings = self._findings()
        noisy = {name: f for name, f in findings.items() if f and not name.startswith("leader_")}
        assert noisy == {}

    def test_should_not_fire_on_any_observation_leaf(self):
        """The scope boundary, asserted from the other side: every finding this check
        produces names `Measurement`, never `Observation`."""
        for findings in self._findings().values():
            for finding in findings:
                assert "Observation over codeset" not in finding, finding

    def test_should_not_fire_on_any_range_high_ratio_leaf(self):
        """A `RangeHighRatio` bound is a multiple of the lab's own reference range, so
        the units cancel and it legitimately carries none. 32 such leaves exist in the
        batch. They are excluded structurally -- none carries `ValueAsNumber` -- which
        is a property worth asserting rather than assuming."""
        for path in sorted(BATCH.glob("*.circe.json")):
            expression = json.loads(path.read_text())
            for _where, entry in _criterion_locations(expression):
                body = entry.get("Criteria")
                body = body if isinstance(body, dict) else entry
                payload = body.get("Measurement")
                if not isinstance(payload, dict) or "RangeHighRatio" not in payload:
                    continue
                assert "ValueAsNumber" not in payload, f"{path.name}: {payload}"


@pytest.mark.skipif(not BATCH.is_dir(), reason=f"delivered batch not present: {BATCH}")
class TestTheObservationLeavesThisCheckDoesNotCover:
    """The same defect on a different CDM table, counted rather than described.

    `Observation` reads `ValueAsNumber` and `Unit` exactly as `Measurement` does
    (`CRITERIA_TYPE_VALUE_ATTRIBUTES`), so an unitless numeric bound there ships the
    same bare number. `unitless_measurement_bound_criteria` is scoped to `Measurement`
    and does NOT cover these; that is a deliberate scope boundary, not a finding that
    the defect stops there.

    Pinning the count here does two things prose cannot: it fails if the batch is ever
    regenerated with more of them, and it hands whoever widens the check a measured
    starting number instead of a re-survey.
    """

    @staticmethod
    def _unitless_observation_bounds() -> list[tuple[str, Any, str]]:
        found: list[tuple[str, Any, str]] = []
        for path in sorted(BATCH.glob("*.circe.json")):
            expression = json.loads(path.read_text())
            for _where, entry in _criterion_locations(expression):
                body = entry.get("Criteria")
                body = body if isinstance(body, dict) else entry
                payload = body.get("Observation")
                if not isinstance(payload, dict) or "ValueAsNumber" not in payload:
                    continue
                if payload.get("Unit"):
                    continue
                concept_set = next(
                    (
                        candidate
                        for candidate in expression.get("ConceptSets") or []
                        if candidate.get("id") == payload.get("CodesetId")
                    ),
                    {},
                )
                found.append((path.name, payload["CodesetId"], concept_set.get("name") or ""))
        return found

    def test_should_find_exactly_four_unitless_observation_bounds(self):
        """CARMELINA 'Life expectancy' lt 5.0 and CAROLINA 'Systolic blood pressure'
        gt 140.0, on both arms each. Both have a unit-carrying counterpart in the same
        batch -- CAROLINA's own codeset 44 'life expectancy less than 5 years' carries
        year, and ARISTOTLE's SBP carries mm[Hg] -- so these are missing units, not
        dimensionless quantities."""
        found = self._unitless_observation_bounds()
        assert len(found) == 4, found
        assert {name for _file, _codeset, name in found} == {
            "Life expectancy",
            "Systolic blood pressure",
        }, found

    def test_should_confirm_this_check_leaves_all_four_uncaught(self):
        """The gap stated as a test rather than a comment: if someone widens the check
        to Observation, this is the assertion that tells them it worked."""
        for file_name, codeset_id, _name in self._unitless_observation_bounds():
            expression = json.loads((BATCH / file_name).read_text())
            findings = unitless_measurement_bound_criteria(expression)
            assert not any(f"codeset {codeset_id} " in f for f in findings), file_name
