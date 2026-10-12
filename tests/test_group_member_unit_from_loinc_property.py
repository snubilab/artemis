"""Whether a group label's absolute bound reaches a member is read off the member's concepts.

RFC-016 §4 (A20): ``resolve_group_member_constraint`` used to match the member's TEXT
("Fasting Plasma Glucose", "Hemoglobin A1c") against an analyte -> unit table. It now
reads the LOINC ``Has property`` of the member's own concepts and asks whether the label's
UCUM unit measures that property (``loinc_specimen.verify_members_against_unit``).

Real rows, copied verbatim into ``tests/fixtures/p3_structural_rows.json``:

* ``a20_carolina_glucose_group`` -- CAROLINA exclusion group 44 'Uncontrolled
  hyperglycaemia' of the 2026-09-09 store: the label carries ``gt 240 mg/dl`` and its
  three members 'Hemoglobin A1c', 'Fasting Plasma Glucose', 'Random Plasma Glucose' carry
  none. The FPG and RPG concept sets are that store's sets 64 and 65; the HbA1c set is
  EMPA-REG codeset 3 of the 2026-10-12 candidate (the store's own HbA1c set id does not
  resolve in its cached expression).
* ``vocabulary_loinc_axes`` -- each member concept's ``Has property`` in synthea23m.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.services.value_constraint import (
    STRANDED_GROUP_CONSTRAINT_REASON,
    resolve_group_member_constraint,
)

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "p3_structural_rows.json").read_text()
)
GROUP = FIXTURE["a20_carolina_glucose_group"]
PROPERTY = {
    row[0]: row[6]
    for row in FIXTURE["vocabulary_loinc_axes"]["rows"]
    if row[4] == "Has property"
}


def _members(concept_set: dict) -> list[int]:
    return [
        item["concept"]["CONCEPT_ID"]
        for item in concept_set["expression"]["items"]
        if not item.get("isExcluded")
    ]


def _properties(concept_set: dict) -> dict[int, str | None]:
    return {cid: PROPERTY.get(cid) for cid in _members(concept_set)}


FPG, RPG = (next(s for s in GROUP["fpg_rpg_sets"] if s["id"] == i) for i in (64, 65))
HBA1C = GROUP["hba1c_set"]["set"]
LABEL = next(r for r in GROUP["rows"] if r["isGroupLabel"])
BOUND = SimpleNamespace(
    op=LABEL["valueConstraint"]["op"],
    value=LABEL["valueConstraint"]["value"],
    unit_text=LABEL["valueConstraint"]["unitText"],
    reference_bound=LABEL["valueConstraint"]["referenceBound"],
    unit_concept_id=LABEL["valueConstraint"]["unitConceptId"],
)


@pytest.mark.parametrize("concept_set", [FPG, RPG], ids=["fpg-set-64", "rpg-set-65"])
def test_should_hand_the_bound_to_a_member_whose_concepts_are_measured_in_its_unit(concept_set):
    resolution = resolve_group_member_constraint(
        BOUND, None, member_properties=_properties(concept_set)
    )

    assert resolution.propagated is True
    assert resolution.constraint is BOUND
    assert resolution.refusal_reason is None


def test_should_strand_the_bound_at_a_member_whose_concepts_are_measured_in_another_unit():
    resolution = resolve_group_member_constraint(
        BOUND, None, member_properties=_properties(HBA1C)
    )

    assert resolution.propagated is False
    assert resolution.constraint is None
    assert resolution.refusal_reason == STRANDED_GROUP_CONSTRAINT_REASON
    assert "Mass fraction" in resolution.refusal_explanation
    assert "mg/dL" in resolution.refusal_explanation


def test_should_strand_the_bound_when_the_members_concepts_carry_no_loinc_property():
    """A member mapped to non-LOINC concepts (SNOMED HbA1c procedures here) says nothing
    about the unit, so nothing may be handed down."""
    snomed_only = {4197971: None, 44793001: None}

    resolution = resolve_group_member_constraint(BOUND, None, member_properties=snomed_only)

    assert resolution.refusal_reason == STRANDED_GROUP_CONSTRAINT_REASON


def test_should_strand_the_bound_when_nothing_is_known_about_the_member():
    """The pre-analyte behaviour every caller without the member's concepts inherits."""
    resolution = resolve_group_member_constraint(BOUND, None)

    assert resolution.refusal_reason == STRANDED_GROUP_CONSTRAINT_REASON


def test_should_read_the_properties_only_when_the_bound_needs_them():
    """A lazy source is not consulted for a reference-relative bound or an own bound."""
    asked: list[int] = []

    def lookup() -> dict[int, str | None]:
        asked.append(1)
        return _properties(FPG)

    uln = SimpleNamespace(op="gt", value=3.0, unit_text="x ULN", reference_bound="absolute",
                          unit_concept_id=None)
    assert resolve_group_member_constraint(uln, None, member_properties=lookup).propagated
    assert resolve_group_member_constraint(BOUND, BOUND, member_properties=lookup).constraint is BOUND
    assert asked == []
    assert resolve_group_member_constraint(BOUND, None, member_properties=lookup).propagated
    assert asked == [1]
