"""Export-time repair for a cohort whose entry event its own inclusion rule removes.

The defect this repairs is the one
``scripts/verify_entry_exclusion_conflict.py`` refuses a delivery for: the entry
event admits a patient on concept X, and an inclusion rule then requires the
ABSENCE of a concept set whose closure contains X, so every entered patient is
thrown out and the cohort returns zero people on any database.

Measured instance, ``deliveries/2026-09-12/empa-reg_comparator.circe.json``:

    entry event   ConditionOccurrence codeset 2 'Type 2 Diabetes Mellitus'
                  [201826, 44793113], includeDescendants
    rule #14      'Endocrine disorder (excluding T2DM)' requires codeset 29
                  'Endocrine disorder' at Occurrence {Type: 0, Count: 0}
    codeset 29    23 members, ZERO isExcluded, includes 201820 'Diabetes
                  mellitus' with includeDescendants -- and 201826 is a
                  descendant of 201820

Rule 14 returned 0 people (0.00%) at BOTH Ajou and Dong-A while the treatment arm
of the same trial returned 874 and 786. The rule NAME says what the protocol
asked for ("excluding T2DM"); the concept set does not implement it.

WHY THIS REPAIRS AT EXPORT TIME. The build already has the answer in front of
it -- the rule's own name -- and the concept set is data in the payload, not a
model output. Re-extracting to fix it would re-roll every other criterion (see
``feedback: prompt edits re-roll a third of criteria``) to change one concept
set, and would cost an LLM pass for a defect that is a pure set operation.

WHAT IT WILL NOT DO. Three conditions must hold together, and the FIRST is the
safety one:

1. the rule's own text states an entity exception (:mod:`entity_exception`).
   Overlap alone is NEVER sufficient: a concept set deliberately excluding the
   entry concepts is exactly what a legitimate washout or contraindication rule
   looks like, and repairing it would erase a real exclusion. The repair only
   ever implements what the protocol text already said;
2. the absence set's resolved closure covers the ENTIRE entry closure. Partial
   overlap is a population cut, not an unsatisfiable rule -- the detector
   reports it WARN and this leaves it alone;
3. the criterion's window covers index day 0 AND every group from the rule root
   down to the criterion is Type ALL. A window ending at -1d can be satisfied by
   a patient whose first qualifying event IS the index event; under an ANY group
   a sibling branch can satisfy the rule instead.

Conditions 2 and 3 are precisely the detector's FAIL predicate, and the
traversal primitives they are computed from live here so that the gate and the
repair cannot drift apart: ``scripts/verify_entry_exclusion_conflict.py``
imports them from this module.

THE REPAIR ITSELF mirrors the entry concept set's items into the absence set as
``isExcluded`` items, rather than listing the resolved closure concept by
concept. Circe expands the excluded side through ``concept_ancestor`` exactly as
it expands the included side, so the mirrored items subtract the entry closure
precisely, stay readable in Atlas, and survive a vocabulary release that adds a
descendant. An entry set that carries an ``isExcluded`` item of its own declines
for the mirror's one limit: a flat mirror cannot express that subtraction, so it
would remove more from the absence set than the entry actually admits.

No database import here. The vocabulary arrives as a
:class:`~src.services.conceptset_closure.VocabularyLookup`, which is what lets
the tests run the real closure resolver with no database at all.
"""
from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterator

from src.services.conceptset_closure import VocabularyLookup, resolve_concept_set
from src.services.entity_exception import EntityException, detect_entity_exception

#: Keys of a Circe criterion object that are not a domain criterion.
_NON_DOMAIN_KEYS = {
    "CorrelatedCriteria", "Occurrence", "StartWindow", "EndWindow",
    "RestrictVisit", "IgnoreObservationPeriod", "Criteria",
}


# --------------------------------------------------------------------------
# traversal -- shared with scripts/verify_entry_exclusion_conflict.py
# --------------------------------------------------------------------------

def domain_of(criteria: dict) -> tuple[str, dict] | None:
    """The single ``{Domain: {...}}`` pair inside a Circe ``Criteria`` object."""
    for key, value in criteria.items():
        if key not in _NON_DOMAIN_KEYS and isinstance(value, dict):
            return key, value
    return None


def entry_codeset_ids(cohort: dict) -> list[tuple[str, int]]:
    """``(domain, CodesetId)`` for every PrimaryCriteria entry event.

    Circe unions the entry criteria, so a patient enters on ANY of them.
    """
    out: list[tuple[str, int]] = []
    for criteria in (cohort.get("PrimaryCriteria") or {}).get("CriteriaList") or []:
        found = domain_of(criteria)
        if not found:
            continue
        domain, body = found
        codeset = body.get("CodesetId")
        if codeset is not None:
            out.append((domain, int(codeset)))
    return out


def window_bound(side: dict | None, unbounded: float) -> float:
    """A Circe window endpoint in days relative to index.

    A missing side, or a side without ``Days``, is Circe's "all days" -- the
    caller supplies which infinity that means.
    """
    if not side or side.get("Days") is None:
        return unbounded
    return float(side.get("Coeff", 1)) * float(side["Days"])


def window_covers_index(criterion: dict) -> tuple[bool, str]:
    """Does the criterion's StartWindow contain index day 0?

    Load-bearing: the entry event sits at day 0. A window that stops before it
    (``End`` at -1d) can be satisfied by a patient whose first qualifying event
    IS the index event, so full concept coverage is not by itself fatal.
    """
    win = criterion.get("StartWindow") or {}
    start = window_bound(win.get("Start"), float("-inf"))
    end = window_bound(win.get("End"), float("inf"))
    label = f"[{start:g}d, {end:g}d]"
    return (start <= 0 <= end), label


def iter_absence_criteria(
    expression: dict, conjunctive: bool = True
) -> Iterator[tuple[dict, bool]]:
    """Every ABSENCE criterion under a rule expression, with its conjunctivity.

    ``conjunctive`` is False as soon as any enclosing group is not Type ALL --
    under an ANY group a sibling branch can satisfy the rule, so an unsatisfiable
    absence there is not by itself fatal.
    """
    if not isinstance(expression, dict):
        return
    here = conjunctive and str(expression.get("Type", "ALL")).upper() == "ALL"
    for entry in expression.get("CriteriaList") or []:
        occurrence = entry.get("Occurrence") or {}
        if occurrence.get("Type") == 0 and occurrence.get("Count") == 0:
            yield entry, here
    for group in expression.get("Groups") or []:
        yield from iter_absence_criteria(group, here)


# --------------------------------------------------------------------------
# the repair
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RepairCandidate:
    """A rule/criterion pair that satisfies conditions 1 and 3, before closure.

    Conditions 1 and 3 need no vocabulary, so a caller can ask whether anything
    could possibly fire before paying for a database round trip.
    """

    rule_index: int
    rule_name: str
    criterion: dict
    codeset_id: int
    exception: EntityException
    window: str


@dataclass(frozen=True)
class EntryExclusionRepair:
    """One applied repair, for the caller to log and to record."""

    rule_index: int
    rule_number: int
    rule_name: str
    codeset_id: int
    codeset_name: str
    excepted: list[str]
    excluded_concept_ids: list[int] = field(default_factory=list)


def _rule_texts(rule: dict, criterion: dict) -> list[str]:
    """Every text on a rule or its criterion that may carry the exception clause.

    The delivered payloads carry only ``name``; a store-side rule may also carry
    a description, and the criterion may carry its own. All are read because the
    clause is the safety condition -- missing it means declining a real repair,
    never making a wrong one.
    """
    candidates = [rule.get("name"), rule.get("description"), criterion.get("description")]
    return [str(t) for t in candidates if isinstance(t, str) and t.strip()]


def iter_repair_candidates(base: dict[str, Any]) -> Iterator[RepairCandidate]:
    """Rules this repair could fire on, judged without a vocabulary.

    Applies conditions 1 (an entity exception stated in the rule's own text) and
    3 (index-covering window under an all-ALL group path). Condition 2 needs the
    concept closure and is applied by :func:`repair_entry_exclusion_conflicts`.
    """
    for index, rule in enumerate(base.get("InclusionRules") or []):
        for criterion, conjunctive in iter_absence_criteria(rule.get("expression") or {}):
            if not conjunctive:
                continue
            covers, window = window_covers_index(criterion)
            if not covers:
                continue
            found = domain_of(criterion.get("Criteria") or {})
            if not found:
                continue
            codeset = found[1].get("CodesetId")
            if codeset is None:
                continue
            exception = next(
                (e for e in (detect_entity_exception(t) for t in _rule_texts(rule, criterion))
                 if e is not None),
                None,
            )
            if exception is None:
                continue
            yield RepairCandidate(
                rule_index=index,
                rule_name=str(rule.get("name")),
                criterion=criterion,
                codeset_id=int(codeset),
                exception=exception,
                window=window,
            )


def _mirror_items(entry_sets: list[dict]) -> list[dict] | None:
    """The entry sets' items, ready to be appended as ``isExcluded``.

    None means decline: an entry set that already subtracts something cannot be
    mirrored flat without subtracting more than the entry admits.
    """
    mirrored: list[dict] = []
    seen: set[int] = set()
    for cs in entry_sets:
        for raw in (cs.get("expression") or {}).get("items") or []:
            if raw.get("isExcluded"):
                return None
            concept_id = (raw.get("concept") or {}).get("CONCEPT_ID")
            if concept_id is None:
                continue
            if int(concept_id) in seen:
                continue
            seen.add(int(concept_id))
            copy = deepcopy(raw)
            copy["isExcluded"] = True
            mirrored.append(copy)
    return mirrored


def repair_entry_exclusion_conflicts(
    base: dict[str, Any], lookup: VocabularyLookup
) -> list[EntryExclusionRepair]:
    """Implement the exception a rule's own name states. Mutates ``base`` in place.

    :param base: a Circe cohort expression (ConceptSets / PrimaryCriteria /
        InclusionRules), mutated in place.
    :param lookup: vocabulary access for resolving concept-set closures.
    :returns: one record per applied repair; empty means nothing satisfied all
        three conditions, which is the expected answer for almost every file.
    """
    candidates = list(iter_repair_candidates(base))
    if not candidates:
        return []

    by_id = {int(cs["id"]): cs for cs in base.get("ConceptSets") or [] if "id" in cs}
    entry_sets = [
        by_id[codeset] for _domain, codeset in entry_codeset_ids(base) if codeset in by_id
    ]
    if not entry_sets:
        return []

    entry_ids: set[int] = set()
    for cs in entry_sets:
        entry_ids |= resolve_concept_set(cs, lookup).concept_ids
    if not entry_ids:
        return []

    mirrored = _mirror_items(entry_sets)
    if mirrored is None:
        logging.warning(
            "[TTE] entry-exclusion repair declines: the entry concept set carries an "
            "excluded item, which a mirrored exclusion cannot express without removing "
            "more from the absence set than the entry admits",
        )
        return []
    if not mirrored:
        return []

    applied: list[EntryExclusionRepair] = []
    for candidate in candidates:
        cs = by_id.get(candidate.codeset_id)
        if cs is None:
            continue
        absence_ids = resolve_concept_set(cs, lookup).concept_ids
        if not entry_ids or not entry_ids <= absence_ids:
            # Condition 2. Partial or no overlap: a population cut at most, and
            # the detector reports it WARN rather than FAIL.
            continue

        items = (cs.setdefault("expression", {})).setdefault("items", [])
        already = {
            (i.get("concept") or {}).get("CONCEPT_ID")
            for i in items
            if i.get("isExcluded")
        }
        added = [deepcopy(m) for m in mirrored
                 if (m.get("concept") or {}).get("CONCEPT_ID") not in already]
        if not added:
            continue
        items.extend(added)

        applied.append(
            EntryExclusionRepair(
                rule_index=candidate.rule_index,
                rule_number=candidate.rule_index + 1,
                rule_name=candidate.rule_name,
                codeset_id=candidate.codeset_id,
                codeset_name=str(cs.get("name")),
                excepted=list(candidate.exception.excepted),
                excluded_concept_ids=[
                    int((m.get("concept") or {}).get("CONCEPT_ID")) for m in added
                ],
            )
        )
        logging.warning(
            "[TTE] entry-exclusion repair: rule #%d %r requires the absence of concept "
            "set %d %r, whose closure contains the whole entry closure -- the rule as "
            "written can never be satisfied. Its text excepts %s, so concepts %s are "
            "marked isExcluded in that set.",
            candidate.rule_index + 1, candidate.rule_name, candidate.codeset_id,
            cs.get("name"), ", ".join(candidate.exception.excepted),
            ", ".join(str(c) for c in applied[-1].excluded_concept_ids),
        )
    return applied
