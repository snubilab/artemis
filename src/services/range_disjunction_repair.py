"""Export-time repair: a protocol range emitted as a disjunction of its two bounds.

The defect, ``deliveries/2026-09-12/carmelina_{treatment,comparator}.circe.json``
rule #12, named ``"HbA1c at least 6.5% + HbA1c at most 10.0%"``::

    Type: ANY
      group ALL -> Measurement codeset 8 'HbA1c'  ValueAsNumber {Op: gte, Value: 6.5}
      group ALL -> Measurement codeset 9 'HbA1c'  ValueAsNumber {Op: lte, Value: 10.0}

The protocol means ``6.5 <= HbA1c <= 10.0``. As emitted it means "at least 6.5 OR at
most 10.0", which nearly everyone with an HbA1c satisfies -- the rule admits almost the
whole entered population instead of restricting it. It reproduces in the 2026-09-18 cold
re-extraction, so it is a persistent property of the build path rather than one bad run.

It also blocks a second repair. :mod:`src.services.presence_unit_repair` declines to drop
the unit filter on either half, because a one-sided bound can wrongly include a value
recorded in another unit: every IFCC value (>= 15 mmol/mol) passes a bare ``>= 6.5``. A
single ``bt 6.5..10.0`` can be reached by no alternative unit at all, so the collapse is
what makes that criterion repairable -- which is why this runs FIRST at the same export
chokepoint.

WHY THIS REPAIRS AT EXPORT TIME, like its two siblings
(:mod:`src.services.entry_exclusion_repair`, :mod:`src.services.presence_unit_repair`):
the payload already carries everything needed to decide, so re-extracting to fix it would
re-roll roughly a third of every other criterion (see ``feedback: prompt edits re-roll a
third of criteria``) and spend an LLM pass on what is a local rewrite of two numbers.

WHAT IT WILL NOT DO. An ``ANY`` of two bounds is also the correct shape for a genuine
disjunction -- EMPA-REG rule #4 offers one HbA1c range for patients on background therapy
and another for drug-naive patients -- so all five conditions must hold together:

1. the rule expression is ``Type: ANY`` holding exactly two groups and no criterion or
   demographic criterion of its own, and each group holds exactly one criterion, no
   nested group and no demographic criterion. A group type other than ALL/ANY is
   declined: with a single criterion those two are equivalent, ``AT_MOST`` is not;
2. both criteria are ``Measurement`` presence criteria that agree on EVERYTHING except
   ``CodesetId`` and ``ValueAsNumber``. That one comparison subsumes occurrence, window,
   ``CorrelatedCriteria``, ``Unit`` and every other attribute, so a difference anywhere
   declines rather than being silently dropped by the survivor;
3. one bound is ``gte``, the other ``lte``, and low < high. A strict ``gt``/``lt`` is
   DECLINED, not widened: Circe's ``bt`` is inclusive, so collapsing one would admit the
   endpoint the protocol excluded -- a second semantic change nobody asked for, on a
   shape that occurs in no delivered file;
4. the two concept sets resolve to the IDENTICAL, non-empty closure through the
   vocabulary. Two different analytes bracketed by one range is a different and wrong
   repair, and the resolved closure -- not the name, which is model-written free text and
   is ``'HbA1c'`` on both of CARMELINA's sets -- is what establishes they are the same
   measurement;
5. the rule NAME reads as a range over one subject. Decided mechanically, and
   deliberately conservatively: the name is split on ``" + "`` into exactly two halves
   (the separator the builder joins group labels with), each half has its bound language
   removed -- the comparison phrases in :data:`_BOUND_LANGUAGE`, the numbers and their
   percent sign, and brackets -- and what remains must be identical and non-empty on both
   sides. ``"HbA1c at least 6.5%"`` and ``"HbA1c at most 10.0%"`` both reduce to
   ``"hba1c"``; EMPA-REG's two halves reduce to ``"hba1c for patients on background
   therapy"`` and ``"hba1c for drug naive patients"`` and decline. Additionally both
   delivered bound values must appear as numbers in the name, so a name describing some
   other range cannot be read as endorsing this one.

THE REPAIR ITSELF replaces the rule's expression with the low criterion, its
``ValueAsNumber`` rewritten to ``{"Value": low, "Extent": high, "Op": "bt"}``, under
``{"Type": "ALL", "CriteriaList": [it], "DemographicCriteriaList": [], "Groups": []}`` --
the shape every single-criterion rule in the delivered files already has. The low side's
``CodesetId`` survives; condition 4 has established the high side's set resolves to the
same concepts. The now-unreferenced concept set is left in place: pruning it is a
different concern, and Atlas and WebAPI both ignore an unused set.

No database import here. The vocabulary arrives as a
:class:`~src.services.conceptset_closure.VocabularyLookup`, which is what lets the tests
run the real closure resolver with no database at all.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterator

from src.services.conceptset_closure import VocabularyLookup, resolve_concept_set

#: Group types that mean the same thing as ALL when the group holds one criterion.
#: AT_MOST does not, and AT_LEAST carries a count this repair does not read.
_SINGLE_CRITERION_GROUP_TYPES = {"ALL", "ANY"}

_LOW_OPS = {"gte"}
_HIGH_OPS = {"lte"}
_STRICT_OPS = {"gt", "lt"}

#: The separator the builder joins per-group labels with when it names an ANY rule.
_NAME_SEPARATOR = " + "

#: Bound language stripped from a name half before the two halves are compared: the
#: comparison phrases, a number with an optional percent sign, the comparison symbols,
#: and brackets. Anything left is the subject the half is about.
_BOUND_LANGUAGE = re.compile(
    r"\b(?:at\s+least|at\s+most|no\s+more\s+than|no\s+less\s+than|not\s+more\s+than|"
    r"greater\s+than|less\s+than|more\s+than|or\s+equal\s+to|up\s+to|and|to|"
    r"above|below|over|under|from|between)\b"
    r"|\d+(?:\.\d+)?\s*%?"
    r"|[<>=≤≥()\[\]]+",
    re.IGNORECASE,
)

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True)
class RangeCollapse:
    """One applied collapse, for the caller to log and to record."""

    rule_index: int
    rule_number: int
    rule_name: str
    low_codeset_id: int
    high_codeset_id: int
    low: float
    high: float
    ops: tuple[str, str]
    n_concepts: int


@dataclass(frozen=True)
class RangeDisjunction:
    """An ``ANY`` rule satisfying conditions 1-3 and 5, before the closure check."""

    rule_index: int
    rule: dict
    low_entry: dict
    high_entry: dict
    low: float
    high: float
    ops: tuple[str, str]

    @property
    def rule_name(self) -> str:
        return str(self.rule.get("name"))

    def codeset_id(self, entry: dict) -> int:
        return int(entry["Criteria"]["Measurement"]["CodesetId"])


# --------------------------------------------------------------------------
# shape -- no vocabulary needed
# --------------------------------------------------------------------------

def _sole_measurement_entry(group: Any) -> dict | None:
    """The one ``Measurement`` criterion entry a group holds, or None (condition 1)."""
    if not isinstance(group, Mapping):
        return None
    if str(group.get("Type", "ALL")).upper() not in _SINGLE_CRITERION_GROUP_TYPES:
        return None
    if group.get("Groups") or group.get("DemographicCriteriaList"):
        return None
    entries = group.get("CriteriaList") or []
    if len(entries) != 1 or not isinstance(entries[0], dict):
        return None
    criteria = entries[0].get("Criteria")
    if not isinstance(criteria, Mapping) or set(criteria) != {"Measurement"}:
        return None
    if not isinstance(criteria["Measurement"], Mapping):
        return None
    return entries[0]


def _without_varying_keys(entry: dict) -> dict:
    """The criterion entry with the two keys a collapse is allowed to differ on removed."""
    stripped = deepcopy(entry)
    payload = stripped["Criteria"]["Measurement"]
    payload.pop("CodesetId", None)
    payload.pop("ValueAsNumber", None)
    return stripped


def _bound(entry: dict) -> tuple[str, float] | None:
    """``(Op, Value)`` of a criterion's ``ValueAsNumber``, or None if it has no number."""
    value = entry["Criteria"]["Measurement"].get("ValueAsNumber")
    if not isinstance(value, Mapping) or set(value) != {"Value", "Op"}:
        # An Extent present means the bound is already a range (or a !bt); either way
        # there is nothing to collapse.
        return None
    try:
        return str(value["Op"]), float(value["Value"])
    except (TypeError, ValueError):
        return None


def _subject(half: str) -> str:
    """A name half with its bound language removed -- what the half is about."""
    return " ".join(_BOUND_LANGUAGE.sub(" ", half).lower().split())


def _name_states_one_range(name: str, low: float, high: float) -> str | None:
    """None when the name reads as one range over one subject; else why it does not."""
    halves = name.split(_NAME_SEPARATOR)
    if len(halves) != 2:
        return f"name {name!r} does not split into exactly two halves on {_NAME_SEPARATOR!r}"
    subjects = [_subject(h) for h in halves]
    if not subjects[0] or subjects[0] != subjects[1]:
        return (
            f"name {name!r} is about {subjects[0]!r} on one side and {subjects[1]!r} on "
            f"the other, so it reads as two subjects rather than one bracketed range"
        )
    mentioned = {float(m) for m in _NUMBER.findall(name)}
    if not {low, high} <= mentioned:
        return (
            f"name {name!r} mentions {sorted(mentioned)} but the delivered bounds are "
            f"{low:g} and {high:g}, so the name describes some other range"
        )
    return None


def iter_range_disjunctions(base: Mapping[str, Any]) -> Iterator[RangeDisjunction]:
    """Rules this repair could fire on, judged without a vocabulary.

    Applies conditions 1, 2, 3 and 5; condition 4 needs the concept closures and is
    applied by :func:`repair_range_disjunctions`. A caller can therefore ask whether
    anything could possibly fire before paying for a database round trip -- which is the
    answer for every file in the 2026-06-24 and 2026-08-31 deliveries and four of the six
    in 2026-09-12.

    Declines are logged only once the rule is close enough to the shape for the decline to
    be informative: two sole-Measurement groups agreeing on everything but the codeset and
    the bound. Anything else is not this shape at all and is passed over silently.
    """
    for index, rule in enumerate(base.get("InclusionRules") or []):
        if not isinstance(rule, dict):
            # Must be mutable: the repair rewrites `rule["expression"]` in place, and a
            # copy here would make it a silent no-op.
            continue
        expression = rule.get("expression") or {}
        if str(expression.get("Type", "")).upper() != "ANY":
            continue
        if expression.get("CriteriaList") or expression.get("DemographicCriteriaList"):
            continue
        groups = expression.get("Groups") or []
        if len(groups) != 2:
            continue
        entries = [_sole_measurement_entry(group) for group in groups]
        if entries[0] is None or entries[1] is None:
            continue
        first, second = entries

        bounds = [_bound(first), _bound(second)]
        if bounds[0] is None or bounds[1] is None:
            continue
        # Condition 2. One comparison over everything the survivor would carry.
        if _without_varying_keys(first) != _without_varying_keys(second):
            continue

        name = str(rule.get("name"))
        (first_op, first_value), (second_op, second_value) = bounds
        if {first_op, second_op} & _STRICT_OPS:
            logging.warning(
                "[TTE] range-disjunction repair declines rule #%d %r: bounds %s %g and "
                "%s %g include a strict operator, and Circe's bt is inclusive -- "
                "collapsing would admit an endpoint the protocol excludes",
                index + 1, name, first_op, first_value, second_op, second_value,
            )
            continue

        if first_op in _LOW_OPS and second_op in _HIGH_OPS:
            low_entry, high_entry = first, second
            low, high = first_value, second_value
        elif second_op in _LOW_OPS and first_op in _HIGH_OPS:
            low_entry, high_entry = second, first
            low, high = second_value, first_value
        else:
            logging.warning(
                "[TTE] range-disjunction repair declines rule #%d %r: bounds %s %g and "
                "%s %g are not one lower and one upper bound",
                index + 1, name, first_op, first_value, second_op, second_value,
            )
            continue

        if not low < high:
            logging.warning(
                "[TTE] range-disjunction repair declines rule #%d %r: lower bound %g is "
                "not below upper bound %g, so the two do not bracket a range",
                index + 1, name, low, high,
            )
            continue

        why_not = _name_states_one_range(name, low, high)
        if why_not is not None:
            logging.warning(
                "[TTE] range-disjunction repair declines rule #%d: %s", index + 1, why_not
            )
            continue

        yield RangeDisjunction(
            rule_index=index,
            rule=rule,
            low_entry=low_entry,
            high_entry=high_entry,
            low=low,
            high=high,
            ops=(low_entry["Criteria"]["Measurement"]["ValueAsNumber"]["Op"],
                 high_entry["Criteria"]["Measurement"]["ValueAsNumber"]["Op"]),
        )


# --------------------------------------------------------------------------
# the repair
# --------------------------------------------------------------------------

def repair_range_disjunctions(
    base: dict[str, Any], lookup: VocabularyLookup
) -> list[RangeCollapse]:
    """Collapse an ``ANY`` of two bounds into one ``bt`` criterion. Mutates ``base``.

    :param base: a Circe cohort expression (ConceptSets / PrimaryCriteria /
        InclusionRules), mutated in place.
    :param lookup: vocabulary access for resolving concept-set closures (condition 4).
    :returns: one record per collapsed rule; empty means nothing satisfied all five
        conditions, which is the expected answer for almost every file.
    """
    candidates = list(iter_range_disjunctions(base))
    if not candidates:
        return []

    by_id = {int(cs["id"]): cs for cs in base.get("ConceptSets") or [] if "id" in cs}
    applied: list[RangeCollapse] = []

    for candidate in candidates:
        low_id = candidate.codeset_id(candidate.low_entry)
        high_id = candidate.codeset_id(candidate.high_entry)
        sets = [by_id.get(low_id), by_id.get(high_id)]
        if sets[0] is None or sets[1] is None:
            logging.warning(
                "[TTE] range-disjunction repair declines rule #%d %r: codeset %s is not "
                "in ConceptSets, so its closure cannot be compared",
                candidate.rule_index + 1, candidate.rule_name,
                low_id if sets[0] is None else high_id,
            )
            continue

        closures = [resolve_concept_set(cs, lookup) for cs in sets]
        unresolvable = closures[0].unresolvable_ids | closures[1].unresolvable_ids
        if unresolvable:
            logging.warning(
                "[TTE] range-disjunction repair declines rule #%d %r: concept(s) %s in "
                "codesets %d/%d do not resolve in the vocabulary, so the two sets cannot "
                "be compared",
                candidate.rule_index + 1, candidate.rule_name, sorted(unresolvable),
                low_id, high_id,
            )
            continue

        low_ids, high_ids = closures[0].concept_ids, closures[1].concept_ids
        if not low_ids or low_ids != high_ids:
            logging.warning(
                "[TTE] range-disjunction repair declines rule #%d %r: codesets %d and %d "
                "resolve to %d and %d concepts differing by %s -- bracketing two "
                "different measurements with one range would be a different repair",
                candidate.rule_index + 1, candidate.rule_name, low_id, high_id,
                len(low_ids), len(high_ids), sorted(low_ids ^ high_ids) or "nothing",
            )
            continue

        survivor = candidate.low_entry
        survivor["Criteria"]["Measurement"]["ValueAsNumber"] = {
            "Value": candidate.low, "Extent": candidate.high, "Op": "bt",
        }
        candidate.rule["expression"] = {
            "Type": "ALL",
            "CriteriaList": [survivor],
            "DemographicCriteriaList": [],
            "Groups": [],
        }

        applied.append(
            RangeCollapse(
                rule_index=candidate.rule_index,
                rule_number=candidate.rule_index + 1,
                rule_name=candidate.rule_name,
                low_codeset_id=low_id,
                high_codeset_id=high_id,
                low=candidate.low,
                high=candidate.high,
                ops=candidate.ops,
                n_concepts=len(low_ids),
            )
        )
        logging.warning(
            "[TTE] range-disjunction repair: rule #%d %r was Type ANY over codeset %d "
            "%s %g and codeset %d %s %g, which admits either bound alone -- the two sets "
            "resolve to the same %d concepts, so it is now one criterion bt %g..%g",
            candidate.rule_index + 1, candidate.rule_name, low_id, candidate.ops[0],
            candidate.low, high_id, candidate.ops[1], candidate.high, len(low_ids),
            candidate.low, candidate.high,
        )
    return applied
