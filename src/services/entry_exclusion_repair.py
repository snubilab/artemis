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
it -- the exception the criterion's protocol line states, recorded on the stored row
-- and the concept set is data in the payload, not a model output. Re-extracting to
fix it would re-roll every other criterion (see ``feedback: prompt edits re-roll a
third of criteria``) to change one concept set, and would cost an LLM pass for a
defect that is a pure set operation.

WHAT IT WILL NOT DO. Three conditions must hold together, and the FIRST is the
safety one:

1. the criterion behind the absence concept set states an entity exception: its
   protocol line's ``excepted_entities``, quoted with spans the annotation step (or the
   planner) checked against the line, reach this module as ``stated_exceptions`` keyed
   by concept set id (RFC-016; no word list reads the rule name any more).
   Overlap alone is NEVER sufficient: a concept set deliberately excluding the
   entry concepts is exactly what a legitimate washout or contraindication rule
   looks like, and repairing it would erase a real exclusion. The repair only
   ever implements what the protocol text already said;
2. the absence set forbids entry concepts on one of two paths
   (:func:`entry_overlap` decides which, for the gate and the repair alike):

   a. **full coverage** -- its resolved closure covers the ENTIRE entry closure,
      so the rule as written can never be satisfied;
   b. **residual after an exception** -- it already carries ``isExcluded`` items
      whose closure reaches the entry closure, AND it still forbids some entry
      concepts once they are subtracted. The shape the description-stated
      exception leaves on the EMPA-REG comparator: 201826 'T2DM' excluded, while
      44793113 -- a sibling of 201826 under 201820, not a descendant -- is still
      forbidden through 201820. 2a no longer holds there, and before 2b existed the
      repair declined and the comparator kept forbidding 44793113.

   The excluded items reaching the entry are 2b's safety condition. They show a
   stated exception was already APPLIED and that it concerns the entry concept,
   so subtracting the remainder of the entry completes that exception instead of
   inventing one. A partial overlap with no such item -- none at all, or only
   items unrelated to the entry -- is a population cut the protocol may intend; the
   detector reports it WARN and this leaves it alone. What 2b cannot tell apart:
   an exception NARROWER than the entry (entry 'diabetes', rule 'other endocrine
   disorders excluding T2DM') also satisfies it, and the mirror would then subtract
   the whole entry closure, not just the excepted part;
3. the criterion's window covers index day 0 AND every group from the rule root
   down to the criterion is Type ALL. A window ending at -1d can be satisfied by
   a patient whose first qualifying event IS the index event; under an ANY group
   a sibling branch can satisfy the rule instead.

THE PRESENCE PATH applies 2b -- and only 2b -- to every presence on an all-ALL path,
with condition 3's index-day half replaced by :func:`presence_inside_absence` (one table
family, unnarrowed absence, presence window inside the absence's). CIRCE conjoins
inclusion rules, so an absence forbidding part of a required criterion removes those
patients exactly as it would remove entered ones. Measured on the 2026-10-08 dry
rebuild: EMPA-REG treatment enters on a drug, so the entry path is silent, while #15
still forbids 44793113 of #2 'Type 2 Diabetes Mellitus'. A presence fully covered with
nothing excepted is not repaired -- check (t) refuses it.

Conditions 2 and 3 are precisely the detector's FAIL predicate, and the
traversal primitives they are computed from live here so that the gate and the
repair cannot drift apart: ``scripts/verify_entry_exclusion_conflict.py``
imports them from this module. After a repair, no entry concept is left
forbidden on either path; a mirror that could not achieve that is declined
before anything is written.

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
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterator

from src.services.conceptset_closure import (
    VocabularyLookup,
    expand_items,
    iter_items,
    resolve_concept_set,
)

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


#: Circe criteria types that read one CDM table family: an era is built from the
#: occurrences/exposures of the same concepts, so an absence over one forbids what a
#: criterion over the other counts.
_TABLE_FAMILY = {
    "DrugEra": "Drug", "DrugExposure": "Drug",
    "ConditionEra": "Condition", "ConditionOccurrence": "Condition",
}


def table_family(criteria_type: str) -> str:
    """The CDM table family a Circe criteria type reads."""
    return _TABLE_FAMILY.get(criteria_type, criteria_type)


def is_required_presence(criterion: dict) -> bool:
    """``Occurrence`` at least N with N >= 1 -- the criterion demands an event."""
    occurrence = criterion.get("Occurrence") or {}
    count = occurrence.get("Count")
    return (
        occurrence.get("Type") == 2
        and isinstance(count, int)
        and not isinstance(count, bool)
        and count >= 1
    )


def iter_mandatory_presences(cohort: dict) -> Iterator[tuple[int, str, dict]]:
    """``(rule index, rule name, criterion)`` for every presence on an all-ALL path.

    Mandatory is the point: under an ANY group a sibling branch can satisfy the rule,
    so an absence forbidding part of one alternative is not by itself a contradiction.
    """
    def walk(node: dict, conjunctive: bool) -> Iterator[dict]:
        if not isinstance(node, dict):
            return
        here = conjunctive and str(node.get("Type", "ALL")).upper() == "ALL"
        if not here:
            return
        for entry in node.get("CriteriaList") or []:
            if is_required_presence(entry):
                yield entry
        for group in node.get("Groups") or []:
            yield from walk(group, here)

    for index, rule in enumerate(cohort.get("InclusionRules") or []):
        for entry in walk(rule.get("expression") or {}, True):
            yield index, str(rule.get("name")), entry


def _days_window(criterion: dict) -> tuple[float, float]:
    win = criterion.get("StartWindow") or {}
    return window_bound(win.get("Start"), float("-inf")), window_bound(win.get("End"), float("inf"))


def presence_inside_absence(presence: dict, absence: dict) -> tuple[bool, str]:
    """Does the absence see every event the presence can count?

    The structural half of the presence path; closure overlap is the other half. All
    must hold, and each failure names itself so a detector can report it:

    - one table family (an absence on ConditionOccurrence forbids nothing an
      Observation criterion counts);
    - the absence is unnarrowed -- ``CodesetId`` alone, no ``EndWindow``, no
      ``RestrictVisit``. A narrowed absence forbids only some events, so the presence
      can still be met through the rest;
    - the presence's StartWindow lies inside the absence's. A window rebased by
      ``UseIndexEnd``/``UseEventEnd`` counts only when the two are identical;
    - a presence ignoring the observation period is not inside an absence that keeps it.
    """
    found_p = domain_of(presence.get("Criteria") or {})
    found_a = domain_of(absence.get("Criteria") or {})
    if not found_p or not found_a:
        return False, "no domain criterion"
    if table_family(found_p[0]) != table_family(found_a[0]):
        return False, f"reads {found_p[0]}, the absence {found_a[0]}"
    if set(found_a[1]) != {"CodesetId"} or absence.get("EndWindow") or absence.get(
        "RestrictVisit"
    ):
        return False, "the absence is narrowed"
    if presence.get("IgnoreObservationPeriod") and not absence.get("IgnoreObservationPeriod"):
        return False, "the presence ignores the observation period, the absence does not"
    p_win = presence.get("StartWindow") or {}
    a_win = absence.get("StartWindow") or {}
    if any(w.get("UseIndexEnd") or w.get("UseEventEnd") for w in (p_win, a_win)):
        same = p_win == a_win
        return same, "" if same else "a rebased window that differs"
    (p_start, p_end), (a_start, a_end) = _days_window(presence), _days_window(absence)
    if a_start <= p_start and p_end <= a_end:
        return True, ""
    return False, (
        f"the presence window [{p_start:g}d, {p_end:g}d] reaches outside the absence "
        f"window [{a_start:g}d, {a_end:g}d]"
    )


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


#: The two ways an absence set can earn a repair; see the module docstring.
PATH_FULL_COVERAGE = "full-coverage"
PATH_RESIDUAL_AFTER_EXCEPTION = "residual-after-exception"


@dataclass(frozen=True)
class EntryOverlap:
    """How one absence set meets the entry closure -- the reading the gate and the
    repair both act on, so the two cannot disagree about which sets qualify.

    :param overlap: entry concepts the set still forbids, ``isExcluded`` subtracted.
    :param excepts_entry: an ``isExcluded`` item's closure reaches the entry closure.
    """

    entry_ids: frozenset[int]
    overlap: frozenset[int]
    excepts_entry: bool

    @property
    def path(self) -> str:
        """Which repair path qualifies; empty when neither does."""
        if self.entry_ids and self.overlap == self.entry_ids:
            return PATH_FULL_COVERAGE
        if self.overlap and self.excepts_entry:
            return PATH_RESIDUAL_AFTER_EXCEPTION
        return ""


def entry_overlap(
    absence_set: dict, entry_ids: set[int], lookup: VocabularyLookup
) -> EntryOverlap:
    """Read one absence set against the entry closure, as Circe resolves both."""
    excluded = [i for i in iter_items(absence_set) if i.is_excluded]
    return EntryOverlap(
        entry_ids=frozenset(entry_ids),
        overlap=frozenset(entry_ids & resolve_concept_set(absence_set, lookup).concept_ids),
        excepts_entry=bool(excluded) and bool(entry_ids & expand_items(excluded, lookup)),
    )


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
    excepted: tuple[str, ...]
    window: str
    #: Condition 3's index-day half binds the ENTRY path only; against a mandatory
    #: presence the window condition is :func:`presence_inside_absence`.
    covers_index: bool = True


#: What a repair protected: the cohort's entry, or one mandatory presence criterion.
TARGET_ENTRY = "entry"


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
    path: str = PATH_FULL_COVERAGE
    target: str = TARGET_ENTRY


def iter_repair_candidates(
    base: dict[str, Any], stated_exceptions: Mapping[int, Sequence[str]]
) -> Iterator[RepairCandidate]:
    """Rules this repair could fire on, judged without a vocabulary.

    Applies conditions 1 (the criterion behind the absence concept set states an
    entity exception) and 3's all-ALL group path. Whether the window covers index day 0
    is recorded rather than filtered on: the entry path needs it, the presence path does
    not. Condition 2 needs the concept closure and is applied by
    :func:`repair_entry_exclusion_conflicts`.

    :param base: the cohort expression.
    :param stated_exceptions: concept set id -> the excepted entity names its criterion
        states (``criterion_annotation.stated_exceptions_by_codeset``).
    """
    for index, rule in enumerate(base.get("InclusionRules") or []):
        for criterion, conjunctive in iter_absence_criteria(rule.get("expression") or {}):
            if not conjunctive:
                continue
            covers, window = window_covers_index(criterion)
            found = domain_of(criterion.get("Criteria") or {})
            if not found:
                continue
            codeset = found[1].get("CodesetId")
            if codeset is None:
                continue
            excepted = tuple(stated_exceptions.get(int(codeset)) or ())
            if not excepted:
                continue
            yield RepairCandidate(
                rule_index=index,
                rule_name=str(rule.get("name")),
                criterion=criterion,
                codeset_id=int(codeset),
                excepted=excepted,
                window=window,
                covers_index=covers,
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


def _apply_mirror(
    cs: dict, mirrored: list[dict], target_ids: set[int], lookup: VocabularyLookup,
    describe: str,
) -> list[int] | None:
    """Append ``mirrored`` to ``cs`` as excluded items; the ids added, or None to decline.

    The repair's post-condition is checked before anything is written: no target concept
    left forbidden. An excluded item already carrying a target id with narrower flags
    would be skipped by the dedupe and leave a residual; declining keeps the set as it
    was, and the detector still fails it.
    """
    items = (cs.setdefault("expression", {})).setdefault("items", [])
    already = {
        (i.get("concept") or {}).get("CONCEPT_ID")
        for i in items
        if i.get("isExcluded")
    }
    added = [deepcopy(m) for m in mirrored
             if (m.get("concept") or {}).get("CONCEPT_ID") not in already]
    if not added:
        return None
    repaired = {**cs, "expression": {**cs["expression"], "items": items + added}}
    left = entry_overlap(repaired, target_ids, lookup).overlap
    if left:
        logging.warning(
            "[TTE] entry-exclusion repair declines on %s: mirroring into concept set %s "
            "would still forbid %d target concept(s), e.g. %s",
            describe, cs.get("id"), len(left), sorted(left)[:5],
        )
        return None
    items.extend(added)
    return [int((m.get("concept") or {}).get("CONCEPT_ID")) for m in added]


def repair_entry_exclusion_conflicts(
    base: dict[str, Any],
    lookup: VocabularyLookup,
    stated_exceptions: Mapping[int, Sequence[str]],
) -> list[EntryExclusionRepair]:
    """Implement the exception a criterion's protocol line states. Mutates ``base`` in place.

    Two targets, one mechanism. The ENTRY path is the module docstring's conditions
    1-3. The PRESENCE path extends 2b -- and only 2b -- to every presence on an all-ALL
    path: the rule states an exception, the absence set already carries ``isExcluded``
    items whose closure reaches the presence closure, the presence closure is still
    partly forbidden, and :func:`presence_inside_absence` holds. The measured instance is
    the 2026-10-08 dry rebuild of EMPA-REG treatment: #15 'Endocrine disorder (excluding
    T2DM)' excepts 201826 but still forbids 44793113, which #2 'Type 2 Diabetes Mellitus'
    requires. A presence fully covered with nothing excepted is NOT repaired: no
    exception was begun there, and check (t) refuses it instead.

    :param base: a Circe cohort expression (ConceptSets / PrimaryCriteria /
        InclusionRules), mutated in place.
    :param lookup: vocabulary access for resolving concept-set closures.
    :param stated_exceptions: concept set id -> the excepted entity names its criterion
        states; see :func:`iter_repair_candidates`.
    :returns: one record per applied repair; empty means nothing satisfied the
        conditions, which is the expected answer for almost every file.
    """
    candidates = list(iter_repair_candidates(base, stated_exceptions))
    if not candidates:
        return []

    by_id = {int(cs["id"]): cs for cs in base.get("ConceptSets") or [] if "id" in cs}

    entry_sets = [
        by_id[codeset] for _domain, codeset in entry_codeset_ids(base) if codeset in by_id
    ]
    entry_ids: set[int] = set()
    for cs in entry_sets:
        entry_ids |= resolve_concept_set(cs, lookup).concept_ids
    entry_mirror = _mirror_items(entry_sets) if entry_ids else None
    if entry_ids and entry_mirror is None:
        logging.warning(
            "[TTE] entry-exclusion repair declines: the entry concept set carries an "
            "excluded item, which a mirrored exclusion cannot express without removing "
            "more from the absence set than the entry admits",
        )

    presences: list[tuple[int, str, dict, int]] = []
    for p_index, p_name, p_criterion in iter_mandatory_presences(base):
        found = domain_of(p_criterion.get("Criteria") or {})
        codeset = found[1].get("CodesetId") if found else None
        if codeset is not None and int(codeset) in by_id:
            presences.append((p_index, p_name, p_criterion, int(codeset)))
    presence_closures: dict[int, set[int]] = {}

    applied: list[EntryExclusionRepair] = []
    for candidate in candidates:
        cs = by_id.get(candidate.codeset_id)
        if cs is None:
            continue

        # -- the entry path ------------------------------------------------------
        reading = entry_overlap(cs, entry_ids, lookup) if entry_ids else None
        if candidate.covers_index and entry_mirror and reading is not None and reading.path:
            added = _apply_mirror(
                cs, entry_mirror, entry_ids, lookup,
                f"rule #{candidate.rule_index + 1} {candidate.rule_name!r}",
            )
            if added:
                applied.append(
                    EntryExclusionRepair(
                        rule_index=candidate.rule_index,
                        rule_number=candidate.rule_index + 1,
                        rule_name=candidate.rule_name,
                        codeset_id=candidate.codeset_id,
                        codeset_name=str(cs.get("name")),
                        excepted=list(candidate.excepted),
                        excluded_concept_ids=added,
                        path=reading.path,
                    )
                )
                why = (
                    "whose closure contains the whole entry closure -- the rule as written "
                    "can never be satisfied"
                    if reading.path == PATH_FULL_COVERAGE
                    else f"which already excepts part of the entry closure but still "
                    f"forbids {len(reading.overlap)} of its {len(entry_ids)} concepts"
                )
                logging.warning(
                    "[TTE] entry-exclusion repair: rule #%d %r requires the absence of "
                    "concept set %d %r, %s. Its criterion excepts %s, so concepts %s are marked "
                    "isExcluded in that set.",
                    candidate.rule_index + 1, candidate.rule_name, candidate.codeset_id,
                    cs.get("name"), why, ", ".join(candidate.excepted),
                    ", ".join(str(c) for c in added),
                )

        # -- the presence path (2b only) --------------------------------------------
        for p_index, p_name, p_criterion, p_codeset in presences:
            inside, _why_not = presence_inside_absence(p_criterion, candidate.criterion)
            if not inside:
                continue
            if p_codeset not in presence_closures:
                presence_closures[p_codeset] = resolve_concept_set(
                    by_id[p_codeset], lookup
                ).concept_ids
            p_ids = presence_closures[p_codeset]
            if not p_ids:
                continue
            p_reading = entry_overlap(cs, p_ids, lookup)
            if p_reading.path != PATH_RESIDUAL_AFTER_EXCEPTION:
                continue
            target = f"presence #{p_index + 1} {p_name!r}"
            mirror = _mirror_items([by_id[p_codeset]])
            if not mirror:
                logging.warning(
                    "[TTE] entry-exclusion repair declines on rule #%d %r against %s: the "
                    "presence concept set carries an excluded item a flat mirror cannot "
                    "express", candidate.rule_index + 1, candidate.rule_name, target,
                )
                continue
            added = _apply_mirror(
                cs, mirror, p_ids, lookup,
                f"rule #{candidate.rule_index + 1} {candidate.rule_name!r} against {target}",
            )
            if not added:
                continue
            applied.append(
                EntryExclusionRepair(
                    rule_index=candidate.rule_index,
                    rule_number=candidate.rule_index + 1,
                    rule_name=candidate.rule_name,
                    codeset_id=candidate.codeset_id,
                    codeset_name=str(cs.get("name")),
                    excepted=list(candidate.excepted),
                    excluded_concept_ids=added,
                    path=p_reading.path,
                    target=target,
                )
            )
            logging.warning(
                "[TTE] entry-exclusion repair: rule #%d %r requires the absence of concept "
                "set %d %r, which already excepts part of %s (concept set %d) but still "
                "forbids %d of its %d concepts. Its criterion excepts %s, so concepts %s are "
                "marked isExcluded in that set.",
                candidate.rule_index + 1, candidate.rule_name, candidate.codeset_id,
                cs.get("name"), target, p_codeset, len(p_reading.overlap), len(p_ids),
                ", ".join(candidate.excepted), ", ".join(str(c) for c in added),
            )
    return applied
