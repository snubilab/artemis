"""A criterion the PRODUCER refused must carry no concept set in the draft preview.

``TTEService._apply_draft_concept_set_metadata`` resolves each criterion's concept
set through four keyed paths (role-keyed ref, metadata lookup, bare-id ref, metadata
lookup). When all four miss it used to fall through to a POSITIONAL index
``start_index + mappable_offset``, and it advanced ``mappable_offset`` for every row
it walked -- including rows the producer had refused to mint a concept set for.

The producer refuses on four grounds the consumer's single ``isGroupLabel`` /
demographic skip branch knows nothing about:

  - restated-demographics collapse drop      (``_restatedDemographicsCollapse``)
  - restated-distinctness collapse drop      (``_restatedDistinctnessCollapse``)
  - mapping returned None                    (``_unmappedCriteria``)
  - ``refuse_domain_contradiction`` raised   (``_unmappedCriteria``)

Every refused row still advanced the cursor, so the cursor ran ahead of the list it
indexes and later criteria collected a NEIGHBOUR's concept set.

Measured on ``tmp/tte_cold6_32k_20260907/studies.json``: 20 rows across 5 of the 6
cold-run studies were refused by the producer and nonetheless carry a non-null
``conceptSetId`` -- study 1: 1, study 2: 3, study 8: 4, study 9: 4, study 10: 8.
Replaying the resolution over those six studies attributes 13 of the 20 to the
positional fallback and 13 to nothing else: it fired on 13 rows, all 13 refused,
producing 13 wrong answers and 0 right ones. The other 7 arrive through the
role-blind BARE-ID ref (``criterion_concept_set_refs[str(criterion_id)]``), which
collides because inclusion and exclusion criteria are numbered in independent
sequences -- a separate defect these tests do not cover.

The fixtures below are the sharpest of those 20, at its real shape: CAROLINA
(study 10) exclusion id 25, "Hypersensitivity to investigational product or
glimepiride", domain Condition, sourceText 'Glimepiride'. ``refuse_domain_contradiction``
fired CORRECTLY -- the store records

    "domain contradiction: ConditionOccurrence reads Condition but the concept set
     mapped for 'Glimepiride' holds only Drug concepts, so the rule would match nothing"

-- and the store then wired that same row to conceptSetId 67 'Random Plasma Glucose'.
A gate refused, and the fallback overwrote the refusal with something worse: the rule
went from matching nobody to matching the wrong patients.

``conceptSetId: None`` / ``conceptSetName: ""`` is the state
``_criterion_dict_from_ir_item`` already writes for every criterion it builds, so the
null these tests demand is an existing handled state, not a new one.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def service():
    """A bare TTEService -- ``_apply_draft_concept_set_metadata`` reads no instance state."""
    from src.services.tte_service import TTEService

    return TTEService.__new__(TTEService)


def _exclusion_criterion(
    criterion_id: int,
    description: str,
    domain: str,
    source_text: str,
) -> dict[str, Any]:
    """A study-10 exclusion leaf: mappable, not a group label, not demographic."""
    return {
        "id": criterion_id,
        "description": description,
        "domain": domain,
        "valueConstraint": None,
        "sourceText": source_text,
        "window": {"start": -9999, "end": 0},
        "conceptSetId": None,
        "conceptSetName": "",
        "logicType": "ABSENCE",
        "groupId": None,
        "groupType": "ALL",
        "isGroupLabel": False,
    }


# The three rows straddling the refusal, in document order, at their real shape.
_CKD = _exclusion_criterion(24, "Chronic kidney disease", "Condition", "Chronic kidney disease")
_REFUSED = _exclusion_criterion(
    25,
    "Hypersensitivity to investigational product or glimepiride",
    "Condition",
    "Glimepiride",
)
_GLUCOSE = _exclusion_criterion(26, "Random plasma glucose", "Measurement", "Random plasma glucose")

# ConceptSets as the producer emitted them: one per criterion it actually mapped.
# It minted NOTHING for id 25, so there is no slot in this list that belongs to it.
_CONCEPT_SETS = [
    {"id": 0, "name": "Target: linagliptin", "expression": {"items": []}},
    {"id": 1, "name": "Chronic kidney disease", "expression": {"items": []}},
    {"id": 2, "name": "Random Plasma Glucose", "expression": {"items": []}},
]


def _refs(service) -> dict[str, int]:
    """The refs the producer recorded -- one per MINTED set, none for the refused row."""
    return {
        service._criterion_mapping_key("exclusion", "24"): 1,
        service._criterion_mapping_key("exclusion", "26"): 2,
    }


class TestProducerRefusedCriterionCarriesNoConceptSet:
    def test_should_leave_concept_set_null_when_producer_refused_the_criterion(self, service):
        updated = service._apply_draft_concept_set_metadata(
            [_CKD, _REFUSED, _GLUCOSE],
            _CONCEPT_SETS,
            {},
            "exclusion",
            _refs(service),
        )

        refused = next(row for row in updated if row["id"] == 25)
        assert refused["conceptSetId"] is None, (
            "the producer refused to mint a concept set for exclusion id 25 "
            "(domain contradiction: Condition rule, Drug-only concept set), so the "
            "draft must carry no concept set for it -- a refused rule that matches "
            "nobody is honest, a rule wired to someone else's concept set matches "
            f"the WRONG patients; got conceptSetId={refused['conceptSetId']!r} "
            f"name={refused['conceptSetName']!r}"
        )
        assert refused["conceptSetName"] == ""

    def test_should_not_hand_a_refused_criterion_the_following_rows_concept_set(self, service):
        updated = service._apply_draft_concept_set_metadata(
            [_CKD, _REFUSED, _GLUCOSE],
            _CONCEPT_SETS,
            {},
            "exclusion",
            _refs(service),
        )

        by_id = {row["id"]: row for row in updated}
        assert by_id[25]["conceptSetId"] != by_id[26]["conceptSetId"], (
            "the refused row must not collect the concept set that belongs to the "
            "criterion AFTER it -- that is exactly what the positional cursor did "
            f"on the real store; both rows report conceptSetId={by_id[25]['conceptSetId']!r}"
        )
        assert by_id[26]["conceptSetId"] == 2, (
            "the row after the refused one keeps its own keyed concept set; "
            f"got {by_id[26]}"
        )

    def test_should_keep_concept_set_when_criterion_has_a_keyed_ref(self, service):
        """Scope guard: rows the producer DID mint a set for are untouched."""
        updated = service._apply_draft_concept_set_metadata(
            [_CKD, _REFUSED, _GLUCOSE],
            _CONCEPT_SETS,
            {},
            "exclusion",
            _refs(service),
        )

        by_id = {row["id"]: row for row in updated}
        assert by_id[24]["conceptSetId"] == 1
        assert by_id[24]["conceptSetName"] == "Chronic kidney disease"
        assert by_id[26]["conceptSetName"] == "Random Plasma Glucose"

    def test_should_resolve_by_metadata_when_no_ref_is_recorded(self, service):
        """The metadata lookup is a KEYED path and must keep working without refs.

        ``_build_concept_set_lookup_by_criterion_metadata`` keys a concept set to a
        criterion through the concept ids the mapper selected for it, so a store with
        ``criterionMappingMetadata`` but no ``criterionConceptSetRefs`` still resolves
        without any positional guessing.
        """
        concept_sets = [
            {"id": 0, "name": "Target: linagliptin", "expression": {"items": []}},
            {
                "id": 1,
                "name": "Chronic kidney disease",
                "expression": {"items": [{"concept": {"CONCEPT_ID": 46271022}}]},
            },
        ]
        meta = {
            service._criterion_mapping_key("exclusion", "24"): {
                "selectedConceptIds": [46271022],
            },
        }

        updated = service._apply_draft_concept_set_metadata(
            [_CKD, _REFUSED], concept_sets, meta, "exclusion", {},
        )

        by_id = {row["id"]: row for row in updated}
        assert by_id[24]["conceptSetId"] == 1
        assert by_id[25]["conceptSetId"] is None
