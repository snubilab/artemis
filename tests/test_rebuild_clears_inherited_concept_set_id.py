"""A row the rebuild does not map carries no concept-set id out of the rebuild.

``TTEService._apply_draft_concept_set_metadata`` deep-copies each stored row and wrote
``conceptSetId`` / ``conceptSetName`` only when the new build minted a set for it. A row
the new code skips therefore kept the id of the PREVIOUS build, and in the new build that
id belongs to an unrelated set. Export-time steps read the row's id
(``range_disjunction_repair.codeset_provenance``,
``criterion_annotation.stated_exceptions_by_codeset``, the prospective lint's fallback in
``circe_lint``), so the stale id reaches the delivery.

THE ROWS ARE REAL: the delivery candidate
``output/site_gap/2026-10-12_prompt_f2/store/studies.json`` (built by d7dc2bb), at their
stored shape. All three are ``dose-stability-not-representable`` skips of that build, so
its artifact's ``criterionConceptSetRefs`` has no ``inclusion:<id>`` key for them, and
each still carries an id from the build before:

  CARMELINA (study 9)  inclusion:7   -> 6   'Insulin dose change'      (owner inclusion:9)
  CAROLINA  (study 10) inclusion:38  -> 32  'Type 1 diabetes mellitus' (owner exclusion:1)
  CAROLINA  (study 10) inclusion:41  -> 33  'Rosiglitazone'            (owner exclusion:3)

The refs below are that artifact's, restricted to these rows: the owners' role keys and
the bare keys the producer writes beside every role key ("7": 14, "38": 56, "41": 58).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.services.range_disjunction_repair import codeset_provenance

CAROLINA_GROUP = "dd6fa83b-9e7b-4e93-bf43-a0deef399326"
CAROLINA_STABLE_LINE = (
    "Stable anti-diabetic background medication (unchanged daily dose) for at least 8 weeks "
    "prior V1a and without short term use of insulin. Background medication should be stable "
    "during screening/run-in phase to allow randomisation"
)


@pytest.fixture
def service():
    """A bare TTEService -- ``_apply_draft_concept_set_metadata`` reads no instance state."""
    from src.services.tte_service import TTEService

    return TTEService.__new__(TTEService)


def _carmelina_inclusion_7() -> dict[str, Any]:
    return {
        "id": 7,
        "description": "Stable antidiabetic background medication for 8 weeks",
        "domain": "Drug",
        "valueConstraint": None,
        "sourceText": "",
        "protocolLine": (
            "Stable antidiabetic background medication (unchanged daily dose) for at least "
            "8 weeks prior to"
        ),
        "protocolSpan": "",
        "window": {"start": -56, "end": 0},
        "conceptSetId": 6,
        "conceptSetName": "Stable antidiabetic background medication",
        "logicType": "PRESENCE",
        "groupId": None,
        "groupType": "ALL",
        "parentGroupId": None,
        "isGroupLabel": False,
        "mappable": True,
    }


def _carmelina_inclusion_9() -> dict[str, Any]:
    """The row the candidate build DID map to set 6."""
    return {
        "id": 9,
        "description": "Insulin dose change percentage",
        "domain": "Measurement",
        "sourceText": "Insulin dose change",
        "protocolLine": (
            "Stable antidiabetic background medication (unchanged daily dose) for at least 8 "
            "weeks prior to randomization. If insulin is part of the background therapy, the "
            "average daily insulin dose should not have changed by more than 10% within the 8 "
            "weeks prior to randomization compared with the daily insulin dose at randomization."
        ),
        "conceptSetId": 6,
        "conceptSetName": "Insulin dose change",
        "logicType": "ABSENCE",
        "groupId": "a1990ffe-ff3c-47c1-a670-48fd0cbeeffe",
        "groupType": "ALL",
        "isGroupLabel": False,
    }


def _carolina_inclusion_37_label() -> dict[str, Any]:
    return {
        "id": 37,
        "description": "Stable anti-diabetic background medication",
        "domain": "Drug",
        "protocolLine": CAROLINA_STABLE_LINE,
        "conceptSetId": None,
        "conceptSetName": "",
        "logicType": "PRESENCE",
        "groupId": CAROLINA_GROUP,
        "groupType": "ANY",
        "parentGroupId": None,
        "isGroupLabel": True,
    }


def _carolina_inclusion_38() -> dict[str, Any]:
    return {
        "id": 38,
        "description": "Anti-diabetic medication",
        "domain": "Drug",
        "valueConstraint": None,
        "sourceText": "Anti-diabetic medication",
        "protocolLine": CAROLINA_STABLE_LINE,
        "protocolSpan": "",
        "window": {"start": -56, "end": 0},
        "conceptSetId": 32,
        "conceptSetName": "Anti-diabetic medication",
        "logicType": "PRESENCE",
        "groupId": CAROLINA_GROUP,
        "groupType": "ANY",
        "parentGroupId": None,
        "isGroupLabel": False,
        "mappable": True,
    }


def _carolina_inclusion_41() -> dict[str, Any]:
    return {
        "id": 41,
        "description": "Stable anti-diabetic background for 8 weeks",
        "domain": "Drug",
        "valueConstraint": None,
        "sourceText": "Anti-diabetic medication",
        "protocolLine": "stable anti-diabetic background for at least 8 wks before study start",
        "protocolSpan": "",
        "window": {"start": -56, "end": 0},
        "conceptSetId": 33,
        "conceptSetName": "Anti-diabetic medication",
        "logicType": "PRESENCE",
        "groupId": None,
        "groupType": "ALL",
        "parentGroupId": None,
        "isGroupLabel": False,
        "mappable": True,
    }


def _carolina_exclusion_1() -> dict[str, Any]:
    """The row the candidate build DID map to set 32."""
    return {
        "id": 1,
        "description": "Type 1 diabetes mellitus",
        "domain": "Condition",
        "sourceText": "Type 1 diabetes mellitus",
        "protocolLine": "Type 1 diabetes mellitus",
        "conceptSetId": 32,
        "conceptSetName": "Type 1 diabetes mellitus",
        "logicType": "ABSENCE",
        "groupId": None,
        "groupType": "ALL",
        "isGroupLabel": False,
        "window": {"start": -9999, "end": 0},
    }


def _set(set_id: int, name: str) -> dict[str, Any]:
    return {"id": set_id, "name": name, "expression": {"items": []}}


def _carmelina_inclusion() -> list[dict[str, Any]]:
    return [_carmelina_inclusion_7(), _carmelina_inclusion_9()]


def _carolina_inclusion() -> list[dict[str, Any]]:
    return [_carolina_inclusion_37_label(), _carolina_inclusion_38(), _carolina_inclusion_41()]


CARMELINA_SETS = [_set(6, "Insulin dose change"), _set(14, "Thiazolidinediones")]
CARMELINA_REFS = {"inclusion:9": 6, "9": 6, "7": 14}
CAROLINA_SETS = [
    _set(32, "Type 1 diabetes mellitus"),
    _set(33, "Rosiglitazone"),
    _set(56, "Pancreatitis"),
    _set(58, "Bariatric surgery"),
]
CAROLINA_REFS = {"exclusion:1": 32, "1": 32, "exclusion:3": 33, "3": 33, "38": 56, "41": 58}


class TestASkippedRowLeavesItsOldIdBehind:
    @pytest.mark.parametrize(
        "rows, sets, refs, row_id, stale_id",
        [
            (_carmelina_inclusion(), CARMELINA_SETS, CARMELINA_REFS, 7, 6),
            (_carolina_inclusion(), CAROLINA_SETS, CAROLINA_REFS, 38, 32),
            (_carolina_inclusion(), CAROLINA_SETS, CAROLINA_REFS, 41, 33),
        ],
        ids=["carmelina-inc7", "carolina-inc38", "carolina-inc41"],
    )
    def test_should_clear_the_concept_set_id_when_the_rebuild_mints_no_set_for_the_row(
        self, service, rows, sets, refs, row_id, stale_id
    ):
        updated = service._apply_draft_concept_set_metadata(rows, sets, {}, "inclusion", refs)

        row = next(r for r in updated if r["id"] == row_id)
        assert row["conceptSetId"] is None, (
            f"inclusion:{row_id} was skipped by the rebuild (no 'inclusion:{row_id}' ref), yet "
            f"it still carries set {stale_id} from the build before -- in this build that id "
            f"names {next(s['name'] for s in sets if s['id'] == stale_id)!r}, another row's set"
        )
        assert row["conceptSetName"] == ""

    def test_should_keep_the_concept_set_of_the_row_the_rebuild_mapped(self, service):
        updated = service._apply_draft_concept_set_metadata(
            _carmelina_inclusion(),
            CARMELINA_SETS,
            {},
            "inclusion",
            CARMELINA_REFS,
        )

        owner = next(r for r in updated if r["id"] == 9)
        assert (owner["conceptSetId"], owner["conceptSetName"]) == (6, "Insulin dose change")


class TestTheExportReadsNoStaleId:
    def test_should_give_the_range_repair_no_provenance_from_a_skipped_row(self, service):
        """``codeset_provenance`` keys on the row's ``conceptSetId``. With the stale id,
        CAROLINA's set 32 'Type 1 diabetes mellitus' was attributed to the stable-background
        group and line, which no row of this build maps to it."""
        inclusion = service._apply_draft_concept_set_metadata(
            _carolina_inclusion(),
            CAROLINA_SETS,
            {},
            "inclusion",
            CAROLINA_REFS,
        )
        exclusion = service._apply_draft_concept_set_metadata(
            [_carolina_exclusion_1()], CAROLINA_SETS, {}, "exclusion", CAROLINA_REFS
        )

        provenance = codeset_provenance(inclusion, exclusion)

        assert 32 not in provenance, (
            f"set 32 is owned by exclusion:1 (ungrouped); got provenance {provenance.get(32)!r} "
            "from the skipped inclusion:38"
        )
