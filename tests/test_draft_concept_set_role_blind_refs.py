"""A bare criterion id is not an identity -- it must not resolve a concept set.

``TTEService._apply_draft_concept_set_metadata`` resolved a criterion's concept set
through four paths. Two are keyed by ROLE and id (``"<role>:<id>"``); two were keyed
by the BARE id alone:

  P1 role-keyed-ref       criterion_concept_set_refs["<role>:<id>"]   -- kept
  P2 role-keyed-metadata  concept_sets_by_criterion_id["<role>:<id>"] -- kept
  P3 bare-id-ref          criterion_concept_set_refs["<id>"]          -- REMOVED
  P4 bare-id-metadata     concept_sets_by_criterion_id["<id>"]        -- REMOVED

Inclusion and exclusion criteria are numbered in INDEPENDENT sequences, so a bare
numeric key structurally cannot tell ``inclusion:42`` from ``exclusion:42``. On the
six cold-run studies in ``tmp/tte_cold6_32k_20260907`` the two sequences overlap on
18 / 16 / 11 / 14 / 13 / 49 ids (studies 1 / 2 / 3 / 8 / 9 / 10), and the producer
writes BOTH a role key and a bare key for every set it mints -- so whenever it
refuses one role's criterion, the other role's ref is sitting under the bare key
waiting to be picked up.

Measured over those six studies: the role-blind paths resolved 7 rows, all 7
producer-refused, and in all 7 the id equals the OTHER role's ref. 7 wrong answers,
0 right ones. P4's count under the live ordering was 0 only because P3 shadowed it:
measured in isolation, P4 alone resolves the same 7 rows (giving a DIFFERENT wrong
answer on one of them -- study 10 inclusion:14 gets 35 'Anti-diabetic drug exposure'
from P4 where P3 gives 46 'DPP-4 inhibitors'). Removing P3 while leaving P4 would
have moved every row one path down and changed nothing.

The fixtures below are the clearest of the 7, at its real shape. CAROLINA (study 10)
carries an id 42 in both sequences:

  inclusion:42  "Urinary albumin creatinine ratio >= 30 ug/mg", domain Measurement,
                PRESENCE -- the producer mapped it and recorded ref[inclusion:42] = 31
                AND ref["42"] = 31.
  exclusion:42  "Thiazolidinediones", domain Drug, ABSENCE -- the producer REFUSED it
                ("restated-distinctness-duplicate"), so there is no ref[exclusion:42].

The bare lookup then handed the Drug exclusion rule the lab-measurement concept set
belonging to the Measurement inclusion rule. Same outcome as the positional fallback
this file's sibling removed -- a rule that should match nobody instead matches the
wrong patients -- reached by a different route.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def service():
    """A bare TTEService -- ``_apply_draft_concept_set_metadata`` reads no instance state."""
    from src.services.tte_service import TTEService

    return TTEService.__new__(TTEService)


def _inclusion_42() -> dict[str, Any]:
    """study 10 inclusion:42 -- the criterion the producer DID map."""
    return {
        "id": 42,
        "description": "Urinary albumin creatinine ratio >= 30 ug/mg",
        "domain": "Measurement",
        "valueConstraint": {
            "op": "gte",
            "value": 30.0,
            "unitText": "ug/mg",
            "referenceBound": "absolute",
            "unitConceptId": None,
        },
        "sourceText": "Urinary albumin creatinine ratio",
        "window": {"start": -365, "end": 0},
        "conceptSetId": None,
        "conceptSetName": "",
        "logicType": "PRESENCE",
        "groupId": None,
        "groupType": "ALL",
        "isGroupLabel": False,
    }


def _exclusion_42() -> dict[str, Any]:
    """study 10 exclusion:42 -- the criterion the producer REFUSED.

    Reason recorded in the store: "restated-distinctness-duplicate".
    """
    return {
        "id": 42,
        "description": "Thiazolidinediones",
        "domain": "Drug",
        "valueConstraint": None,
        "sourceText": "Thiazolidinediones",
        "window": {"start": -365, "end": 0},
        "conceptSetId": None,
        "conceptSetName": "",
        "logicType": "ABSENCE",
        "groupId": "190fdc7c-0419-47c0-be24-6f7e8baa39b4",
        "groupType": "ALL",
        "isGroupLabel": False,
    }


# Concept set 31 is the one the producer minted for INCLUSION 42. Nothing was minted
# for exclusion 42, so no slot in this list belongs to it.
_UACR_CONCEPT_ID = 4098583
_CONCEPT_SETS = [
    {"id": 0, "name": "Target: linagliptin", "expression": {"items": []}},
    {
        "id": 31,
        "name": "Urinary albumin creatinine ratio",
        "expression": {"items": [{"concept": {"CONCEPT_ID": _UACR_CONCEPT_ID}}]},
    },
]


class TestBareIdRefDoesNotCrossRoles:
    def test_should_leave_concept_set_null_when_only_the_other_roles_bare_ref_matches(
        self, service
    ):
        """P3: the producer writes ref["42"] alongside ref["inclusion:42"]."""
        refs = {
            service._criterion_mapping_key("inclusion", "42"): 31,
            "42": 31,
        }

        updated = service._apply_draft_concept_set_metadata(
            [_exclusion_42()], _CONCEPT_SETS, {}, "exclusion", refs,
        )

        row = updated[0]
        assert row["conceptSetId"] is None, (
            "exclusion:42 is a Drug ABSENCE rule the producer refused "
            "(restated-distinctness-duplicate); the only ref carrying id 42 is the "
            "one written for INCLUSION 42, a Measurement rule. Inclusion and "
            "exclusion ids are numbered independently, so a bare-id lookup cannot "
            "tell them apart and must not resolve at all; got conceptSetId="
            f"{row['conceptSetId']!r} name={row['conceptSetName']!r}"
        )
        assert row["conceptSetName"] == ""

    def test_should_leave_concept_set_null_when_only_the_other_roles_bare_metadata_matches(
        self, service
    ):
        """P4: the same collision through the metadata lookup, with no refs at all.

        ``_build_concept_set_lookup_by_criterion_metadata`` keys on whatever key the
        mapping metadata carries, and the producer writes a bare-id entry beside every
        role-keyed one -- so P4 collides exactly like P3. Measured in isolation it
        resolves the same 7 rows, which is why it goes with P3 rather than after it.
        """
        meta = {
            service._criterion_mapping_key("inclusion", "42"): {
                "selectedConceptIds": [_UACR_CONCEPT_ID],
            },
            "42": {"selectedConceptIds": [_UACR_CONCEPT_ID]},
        }

        updated = service._apply_draft_concept_set_metadata(
            [_exclusion_42()], _CONCEPT_SETS, meta, "exclusion", {},
        )

        row = updated[0]
        assert row["conceptSetId"] is None, (
            "the bare-id METADATA lookup collides across roles for the same reason "
            "the bare-id ref does -- removing only the ref would move this row one "
            f"path down and change nothing; got conceptSetId={row['conceptSetId']!r} "
            f"name={row['conceptSetName']!r}"
        )
        assert row["conceptSetName"] == ""

    def test_should_not_give_two_criteria_sharing_an_id_the_same_concept_set(self, service):
        """The collision stated directly: same numeric id, two roles, one concept set."""
        refs = {
            service._criterion_mapping_key("inclusion", "42"): 31,
            "42": 31,
        }

        inc = service._apply_draft_concept_set_metadata(
            [_inclusion_42()], _CONCEPT_SETS, {}, "inclusion", refs,
        )
        exc = service._apply_draft_concept_set_metadata(
            [_exclusion_42()], _CONCEPT_SETS, {}, "exclusion", refs,
        )

        assert inc[0]["conceptSetId"] == 31, (
            "the criterion the producer DID map keeps its role-keyed concept set; "
            f"got {inc[0]}"
        )
        assert exc[0]["conceptSetId"] != inc[0]["conceptSetId"], (
            "a Drug exclusion rule and a Measurement inclusion rule that merely share "
            "the number 42 must not end up on the same concept set; both report "
            f"conceptSetId={exc[0]['conceptSetId']!r}"
        )


class TestRoleKeyedPathsStillResolve:
    """Scope guard: the two ROLE-keyed paths are untouched (P1 262 resolutions)."""

    def test_should_resolve_by_role_keyed_ref_when_the_role_matches(self, service):
        refs = {service._criterion_mapping_key("exclusion", "42"): 31}

        updated = service._apply_draft_concept_set_metadata(
            [_exclusion_42()], _CONCEPT_SETS, {}, "exclusion", refs,
        )

        assert updated[0]["conceptSetId"] == 31
        assert updated[0]["conceptSetName"] == "Urinary albumin creatinine ratio"

    def test_should_resolve_by_role_keyed_metadata_when_the_role_matches(self, service):
        meta = {
            service._criterion_mapping_key("exclusion", "42"): {
                "selectedConceptIds": [_UACR_CONCEPT_ID],
            },
        }

        updated = service._apply_draft_concept_set_metadata(
            [_exclusion_42()], _CONCEPT_SETS, meta, "exclusion", {},
        )

        assert updated[0]["conceptSetId"] == 31
