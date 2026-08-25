"""Loader and transformations for the SPEC-INFRA-004 store extract.

`acceptance.md` Conventions require the negative and property criteria to assert against
**real stored criteria transformed**, never against synthetic fixtures — the point of AC-002,
AC-003, AC-010, and AC-016 is that the outcome does not move when grouping state or
`sourceText` does, and a synthetic fixture cannot demonstrate that about the real corpus.

`tests/fixtures/infra_004_store_criteria.json` is a verbatim extract of every top-level
criterion in all 10 studies of the reference store
(`/app/tmp/tte_six_hospital_readiness/studies.json`, commit `3e38b64`), carrying every field
the collapse, its gate, or its reporting reads. Concept-set expressions and mapping metadata
are omitted because nothing in this SPEC reads them.

Clusters are located by (study, role, domain, stem) rather than by id, per `acceptance.md`
Conventions: criterion ids shift across regenerations, and a test that hardcodes one fails
AC-011 in spirit even where it passes mechanically.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from src.services.restated_clusters import description_stem
from src.services.restated_demographics import is_restatable_demographic

_FIXTURE = Path(__file__).parent / "fixtures" / "infra_004_store_criteria.json"

ROLES = ("inclusion", "exclusion")


def load_store() -> dict[str, Any]:
    """Return the full store extract, freshly deep-copied so callers may mutate it."""
    with _FIXTURE.open(encoding="utf-8") as fh:
        return copy.deepcopy(json.load(fh))


def studies() -> list[dict[str, Any]]:
    return load_store()["studies"]


def study_by_nct(nct_id: str) -> dict[str, Any]:
    """Return the one study carrying `nct_id`.

    Raises:
        KeyError: when no study matches, so a renamed or absent study fails loudly rather
            than silently reducing a criterion to a vacuous pass over an empty list.
    """
    for study in studies():
        if study.get("nctId") == nct_id:
            return study
    raise KeyError(f"no study in the store extract carries nctId {nct_id!r}")


def criteria(study: dict[str, Any], role: str) -> list[dict[str, Any]]:
    return study[f"{role}Criteria"]


def stem_group(study: dict[str, Any], role: str, domain: str, stem: str) -> list[dict[str, Any]]:
    """Return one stem group's members, in document order.

    Raises:
        KeyError: when the group is absent or holds fewer than two members. A criterion
            asserting "this cluster does not collapse" over an empty list would pass without
            testing anything, which is the failure mode this guard exists to prevent.
    """
    members = [
        c
        for c in criteria(study, role)
        if (c.get("domain") or "").strip() == domain
        and description_stem(c.get("description")) == stem
    ]
    if len(members) < 2:
        raise KeyError(
            f"stem group ({study.get('nctId')}, {role}, {domain}, {stem!r}) has "
            f"{len(members)} member(s); the fixture it anchors would be vacuous"
        )
    return members


def ungrouped(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the members with all grouping state cleared.

    `spec.md` §2.3 establishes this state is reachable: CARMELINA's ALT/AST/AP triple moved
    from `groupId: null` to a shared non-null `groupId` between two regenerations of identical
    input, with no membership change. Grouping state is a model choice that moves run to run.
    """
    out = copy.deepcopy(members)
    for c in out:
        c["groupId"] = None
        c["groupType"] = None
        c["isGroupLabel"] = False
    return out


def fully_grouped(
    members: list[dict[str, Any]],
    group_id: str = "shared-group",
) -> list[dict[str, Any]]:
    """Return the members sharing one `groupId` — the opposite pole from `ungrouped`."""
    out = copy.deepcopy(members)
    for c in out:
        c["groupId"] = group_id
        c["groupType"] = "ALL"
    return out


def transform_store(study_list: list[dict[str, Any]], fn) -> list[dict[str, Any]]:
    """Apply `fn` to every role's criteria of every study, returning a new store."""
    out = copy.deepcopy(study_list)
    for study in out:
        for role in ROLES:
            study[f"{role}Criteria"] = fn(study[f"{role}Criteria"])
    return out


def ungroup_everything(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return ungrouped(members)


def group_every_stem_group(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign every member of each stem group one shared `groupId`.

    The other pole of AC-010's permutation. Members of a stem group that is a singleton still
    receive a `groupId`, so no criterion is left in its original state by accident.
    """
    out = copy.deepcopy(members)
    for c in out:
        stem = description_stem(c.get("description"))
        c["groupId"] = f"stem::{(c.get('domain') or '').strip()}::{stem}"
        c["groupType"] = "ALL"
    return out


def populate_demographics_source_text_from_stem(
    members: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Give every Demographics-path criterion a `sourceText` taken from its description stem.

    AC-016 fixture 2, and the **stem** is load-bearing rather than incidental. Populating from
    the raw `description` makes the criterion vacuous: CARMELINA {14,23} carry
    `Pregnancy/Nursing/Uncontrolled Contraception` and the same string with a trailing
    `(Exclusion)`, which differ by exactly what the stem operator strips — so a
    description-populated `sourceText` lands them in *different* distinctness classes, and the
    generalized path declines to collapse them whether or not REQ-013 exists. Measured against
    the live store, the description form emits an identical record count with the gate ON and
    OFF, so the test passes on a broken implementation.

    Populated from the stem both members share one `sourceText`, so a missing gate lets the
    generalized path reach them and the record count moves. The stem form is the only variant
    that can fail when the gate is absent.
    """
    out = copy.deepcopy(members)
    for c in out:
        if is_restatable_demographic(c):
            c["sourceText"] = description_stem(c.get("description"))
    return out
