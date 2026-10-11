"""Build-time refusal: an absence rule that forbids a concept a mandatory presence names.

THE DEFECT, 2026-10-11 LEADER/PLATO/ARISTOTLE rebuild, both ARISTOTLE arms::

    #3 'AF/Flutter documentation'     >=1 cs3  {313217 AF, 314665 flutter, ...}
    #7 'Reversible cause AF/Flutter'  ==0 cs14 {313217 AF, 314665 flutter, 4065288}

The protocol line of #7 is "Atrial fibrillation or flutter due to reversible causes"; the
mapper was handed the criterion's name and returned the head condition. A patient
recorded with AF satisfies #3 and is removed by #7. The delivery gate reports it as check
(y) (:func:`~src.utils.circe_lint.forbidden_explicit_presence_criteria`) -- and, when the
presence's whole closure is forbidden, as check (t) too.

WHICH HALF IS REFUSED. The absence. A concept the presence lists as qualifying cannot also
be one the protocol excludes, so whatever the exclusion meant, it was not these concepts;
the presence is left alone. The decision is read from check (y)'s own pairs
(:func:`~src.utils.circe_lint.contradicted_absence_pairs`), never re-derived, so this
refusal and the gate cannot disagree about which rules qualify.

WHAT IT WILL NOT DO. A rule holding anything besides the one absence criterion -- other
criteria, groups, demographics -- is passed over with a warning: removing it would take
criteria with it that nothing refuted, and the gate keeps failing it. Nothing else in the
expression is touched; the absence's concept set stays until the export prunes unused
sets, and the record carries its members for a reader.

THE RECORD. Each removal is written under
:data:`~src.utils.circe_lint.CONTRADICTED_ABSENCE_REFUSALS_KEY` in the ``ruleIndex`` /
``rule`` / ``ruleAfter`` / ``outcome`` shape ``_droppedCriteria`` uses, so the gate's
rule-set reconciliation replays it, and the gate's criterion accounting books every record
as criterion LOSS: the protocol stated an exclusion and the file no longer carries one.
The refusal stops a self-contradicting cohort from shipping; it does not make the
exclusion right, and the fix for that is upstream in the mapping.

No database import here: the vocabulary arrives as a
:class:`~src.services.conceptset_closure.VocabularyLookup`.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.services.conceptset_closure import VocabularyLookup
from src.services.restated_rules import RESTATED_RULE_COLLAPSE_KEY
from src.utils.circe_lint import (
    CRITERION_CONCEPT_SET_REFS_KEY,
    DROP_OUTCOME_RULE_REMOVED,
    contradicted_absence_pairs,
)


def _single_criterion(rule: Mapping[str, Any]) -> bool:
    body = rule.get("expression")
    if not isinstance(body, Mapping):
        return False
    return (
        len(body.get("CriteriaList") or []) == 1
        and not body.get("Groups")
        and not body.get("DemographicCriteriaList")
    )


def _member_ids(concept_set: Mapping[str, Any] | None) -> list[int]:
    items = ((concept_set or {}).get("expression") or {}).get("items") or []
    return [
        item["concept"]["CONCEPT_ID"]
        for item in items
        if isinstance(item, Mapping) and isinstance(item.get("concept"), Mapping)
        and isinstance(item["concept"].get("CONCEPT_ID"), int)
    ]


def refuse_contradicted_absences(
    expression: dict[str, Any], lookup: VocabularyLookup
) -> list[dict[str, Any]]:
    """Remove every single-criterion absence rule check (y) pairs with a presence. Mutates.

    :param expression: a CIRCE cohort expression, modified in place.
    :param lookup: vocabulary facts covering at least the concept sets
        :func:`~src.utils.circe_lint.closure_subsumption_codesets` names.
    :returns: one record per rule removed, in rule order; empty when none.
    """
    rules = expression.get("InclusionRules") or []
    by_absence: dict[int, list[tuple[Any, int, Any, list[int]]]] = {}
    for rule_index, absent_id, present_index, present_id, named in contradicted_absence_pairs(
        expression, lookup
    ):
        by_absence.setdefault(rule_index, []).append(
            (absent_id, present_index, present_id, named)
        )
    if not by_absence:
        return []

    concept_sets = {
        cs.get("id"): cs for cs in expression.get("ConceptSets") or [] if isinstance(cs, Mapping)
    }
    refs = expression.get(CRITERION_CONCEPT_SET_REFS_KEY) or {}
    # A rule a collapse record names as its survivor carries that record's criteria too;
    # removing it would strand them, and the gate's check (w) re-derives the survivor.
    survivors = {
        str(record.get("survivorRule") or "")
        for record in expression.get(RESTATED_RULE_COLLAPSE_KEY) or []
        if isinstance(record, Mapping)
    }
    records: list[dict[str, Any]] = []
    removed: set[int] = set()
    for rule_index in sorted(by_absence):
        rule = rules[rule_index]
        name = str(rule.get("name") or "")
        if not _single_criterion(rule) or name in survivors:
            logging.warning(
                "[TTE] Not refusing rule #%d %r: it forbids a concept a mandatory presence "
                "names, but it holds more than the one absence criterion or survives a "
                "collapsed rule", rule_index + 1, name,
            )
            continue
        absent_id, present_index, present_id, _named = by_absence[rule_index][0]
        presence_name = str(rules[present_index].get("name") or "")
        named_all = sorted({cid for pair in by_absence[rule_index] for cid in pair[3]})
        absent_set = concept_sets.get(absent_id)
        records.append(
            {
                "ruleIndex": rule_index,
                "rule": name,
                "ruleAfter": None,
                "outcome": DROP_OUTCOME_RULE_REMOVED,
                "codesetId": absent_id,
                "codesetName": str((absent_set or {}).get("name") or ""),
                "codesetMemberIds": _member_ids(absent_set),
                "criterionKeys": sorted(
                    key for key, value in refs.items()
                    if ":" in str(key) and value == absent_id
                ),
                "presenceRule": presence_name,
                "presenceCodesetId": present_id,
                "namedConceptIds": named_all,
                "summary": (
                    f"rule #{rule_index + 1} {name!r} required ZERO occurrences of "
                    f"{', '.join(str(c) for c in named_all)}, which rule #{present_index + 1} "
                    f"{presence_name!r} names as qualifying; the absence was refused and the "
                    f"exclusion it stated is lost"
                ),
            }
        )
        removed.add(rule_index)

    if removed:
        expression["InclusionRules"] = [r for i, r in enumerate(rules) if i not in removed]
        logging.warning(
            "[TTE] Refused %d absence rule(s) that forbid a concept a mandatory presence "
            "names: %s", len(records), "; ".join(r["summary"] for r in records),
        )
    return records
