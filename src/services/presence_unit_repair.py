"""Export-time repair: drop the ``Unit`` filter from allowlisted presence criteria.

The defect, the user's decision, the allowlist and the residual-risk rule all live in
:mod:`src.utils.presence_unit_allowlist`; this module applies them to a cohort. It is
the sibling of :mod:`src.services.entry_exclusion_repair` and follows its contract:
pure over ``(base, lookup)``, mutates ``base`` in place, and gets its vocabulary as a
:class:`~src.services.conceptset_closure.VocabularyLookup` so tests need no database.

A ``Unit`` key is removed only when ALL of these hold:

1. the criterion is a presence criterion in an InclusionRule (``at least N >= 1``,
   under ALL/ANY/AT_LEAST groups only) -- never an exclusion;
2. it is a ``Measurement`` carrying both a non-empty ``Unit`` and ``ValueAsNumber``;
3. the concept set's RESOLVED closure classifies as exactly one allowlisted analyte;
4. every unit being removed is one of that analyte's stated units, so the bound is
   known to be expressed in the unit the risk analysis assumed;
5. the residual risk for that bound is "can only miss patients".

Nothing else in the payload is touched. It composes with the entry-exclusion repair in
either order because the two write disjoint keys: that one appends ``isExcluded`` items
to ABSENCE concept sets, this one deletes ``Unit`` from PRESENCE Measurement criteria.
The one theoretical coupling -- a concept set shared by a presence criterion here and a
repaired absence there, whose closure the mirror would shrink -- does not occur in any
delivered file and is reported rather than engineered around.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Iterator

from src.services.conceptset_closure import VocabularyLookup, resolve_concept_set
from src.utils.presence_unit_allowlist import (
    iter_presence_criteria,
    lab_test_axes,
    unit_drop_verdict,
)

#: ``PostgresLabTestVocabulary.lab_tests``: concept id -> a LabTest, LOINC lab tests only.
LabTestLookup = Callable[[Iterable[int]], Mapping[int, Any]]


def _vocabulary_lab_tests(concept_ids: Iterable[int]) -> Mapping[int, Any]:
    """The live LOINC axes, opened only when a set holds a member the allowlist does not list.

    A failure propagates: an unreadable vocabulary must not read as "unverifiable".
    """
    from src.services.loinc_specimen import PostgresLabTestVocabulary
    from src.settings import settings

    with PostgresLabTestVocabulary(settings.DATABASE_URL, settings.CDM_SCHEMA) as vocabulary:
        return vocabulary.lab_tests(concept_ids)


@dataclass(frozen=True)
class PresenceUnitRepair:
    rule_index: int
    rule_name: str
    codeset_id: int
    codeset_name: str
    analyte: str
    bound: dict
    removed_unit_ids: list[int]


def iter_unit_candidates(base: Mapping[str, Any]) -> Iterator[tuple[int, dict, dict]]:
    """``(rule index, criterion, Measurement payload)`` satisfying conditions 1-2.

    Needs no vocabulary, so a caller can skip the database when nothing qualifies.
    """
    for index, entry in iter_presence_criteria(base):
        criteria = entry.get("Criteria")
        payload = criteria.get("Measurement") if isinstance(criteria, Mapping) else None
        if not isinstance(payload, dict):
            continue
        if not payload.get("Unit") or not isinstance(payload.get("ValueAsNumber"), Mapping):
            continue
        if payload.get("CodesetId") is None:
            continue
        yield index, entry, payload


def repair_presence_unit_filters(
    base: dict[str, Any],
    lookup: VocabularyLookup,
    *,
    lab_tests: LabTestLookup | None = None,
) -> list[PresenceUnitRepair]:
    """Remove ``Unit`` where conditions 1-5 hold. Mutates ``base`` in place.

    Condition 3 has a second way to hold: a closure member the allowlist does not list is
    admitted when its LOINC axes equal those of a listed member of the same analyte in the
    set (:func:`src.utils.presence_unit_allowlist.classify_concepts`). The axes are read
    only for a set that would otherwise be ``unlisted``; gate check (q) reads them for the
    same sets (:func:`src.utils.circe_lint.presence_unit_axes_ids`).

    :param lab_tests: the LOINC-axis lookup; the live vocabulary when None.
    :returns: one record per removed ``Unit``; empty when nothing qualified.
    """
    lab_tests = lab_tests or _vocabulary_lab_tests
    by_id = {int(cs["id"]): cs for cs in base.get("ConceptSets") or [] if "id" in cs}
    rules = base.get("InclusionRules") or []
    applied: list[PresenceUnitRepair] = []

    for index, _entry, payload in iter_unit_candidates(base):
        codeset_id = int(payload["CodesetId"])
        rule_name = str(rules[index].get("name"))
        cs = by_id.get(codeset_id)
        if cs is None:
            continue
        closure = resolve_concept_set(cs, lookup)
        if closure.unresolvable_ids:
            logging.warning(
                "[TTE] presence-unit repair declines rule #%d %r codeset %d: concept(s) "
                "%s do not resolve in the vocabulary, so the set cannot be classified",
                index + 1, rule_name, codeset_id, sorted(closure.unresolvable_ids),
            )
            continue
        verdict = unit_drop_verdict(closure.concept_ids, payload["ValueAsNumber"])
        if verdict.classification.status == "unlisted":
            verdict = unit_drop_verdict(
                closure.concept_ids, payload["ValueAsNumber"],
                lab_test_axes(lab_tests(closure.concept_ids)),
            )
        status = verdict.classification.status
        if verdict.analyte is None:
            if status in {"mixed", "unlisted"}:
                logging.warning(
                    "[TTE] presence-unit repair declines rule #%d %r codeset %d %r: "
                    "ambiguous analyte (%s): %s",
                    index + 1, rule_name, codeset_id, cs.get("name"), status, verdict.why,
                )
            continue

        unit_ids = [
            int(u.get("CONCEPT_ID")) for u in payload["Unit"]
            if isinstance(u, Mapping) and u.get("CONCEPT_ID") is not None
        ]
        if not unit_ids or not set(unit_ids) <= verdict.analyte.stated_unit_ids:
            logging.warning(
                "[TTE] presence-unit repair declines rule #%d %r codeset %d: unit(s) %s "
                "are not %s's stated unit(s) %s, so the bound's scale is not the one the "
                "risk analysis assumes",
                index + 1, rule_name, codeset_id, unit_ids, verdict.analyte.name,
                sorted(verdict.analyte.stated_unit_ids),
            )
            continue
        if not verdict.allowed:
            logging.warning(
                "[TTE] presence-unit repair declines rule #%d %r codeset %d (%s %s): "
                "dropping the unit %s -- %s",
                index + 1, rule_name, codeset_id, verdict.analyte.name,
                dict(payload["ValueAsNumber"]), verdict.risk, verdict.why,
            )
            continue

        del payload["Unit"]
        applied.append(
            PresenceUnitRepair(
                rule_index=index,
                rule_name=rule_name,
                codeset_id=codeset_id,
                codeset_name=str(cs.get("name")),
                analyte=verdict.analyte.name,
                bound=dict(payload["ValueAsNumber"]),
                removed_unit_ids=unit_ids,
            )
        )
        logging.warning(
            "[TTE] presence-unit repair: rule #%d %r codeset %d %s %s -- Unit %s removed "
            "(%s)",
            index + 1, rule_name, codeset_id, verdict.analyte.name,
            dict(payload["ValueAsNumber"]), unit_ids, verdict.risk,
        )
    return applied
