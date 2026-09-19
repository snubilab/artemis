"""Export-time repair: one protocol range emitted twice, once as a presence and once as
an absence that forgot to invert its comparison operators.

The defect, ``deliveries/2026-09-12/carmelina_comparator.circe.json`` (byte-identical in
``carmelina_treatment``), rules #12 and #13 as the hospital received them::

    #12 'HbA1c at least 6.5% + HbA1c at most 10.0%'
        ANY( Occurrence{Type:2,Count:1} Measurement cs8  gte 6.5  unit[8554] win -180..0
           , Occurrence{Type:2,Count:1} Measurement cs9  lte 10.0 unit[8554] win -180..0 )

    #13 'HbA1c below lower limit + HbA1c above upper limit'
        ALL( Occurrence{Type:0,Count:0} Measurement cs10 gte 6.5  unit[8554] win -180..0
           , Occurrence{Type:0,Count:0} Measurement cs11 lte 10.0 unit[8554] win -180..0 )

Codesets 8, 9, 10 and 11 are four different ids under the identical name ``'HbA1c'``
holding the identical five members ``[3004410, 3007263, 3034639, 4197971, 44793001]``.
#12 reduces to "has a %-unit HbA1c" (every value is either >= 6.5 or <= 10); #13 to "has
no %-unit HbA1c". CIRCE conjoins every ``InclusionRules`` entry, so the two are logical
complements and the cohort is 0 people on any CDM, with any data, however complete the
ETL. The hospital's per-rule counts corroborate it: #12 and #13 sum to the entry count
exactly in all four measured arms, which is what a pair of complements looks like from
outside. One protocol sentence is behind both -- "HbA1c of >= 6.5% and <= 10.0% at visit
1 (screening)" -- and the absence half negated the logic type without inverting the
operator.

WHY THIS REPAIRS AT EXPORT TIME, the same argument
:mod:`src.services.range_disjunction_repair` makes for its own existence: the root cause
is upstream in extraction, and the store caches the BUILT CIRCE expression, so a re-export
replays the stored rules and an upstream fix only reaches a delivered file on a cold
re-extraction. The resend needs a repair at the point the payload is assembled.

THE TARGET SHAPE, and it is deliberately NOT the gold shape. One rule survives: #12 as
``PRESENCE bt 6.5..10``, which is exactly what :mod:`src.services.range_disjunction_repair`
already collapses it to (verify it on
``output/site_gap/2026-09-18_verify4/DELIVERY/carmelina_comparator.circe.json``, where the
collapse has run and #13 is still untouched). #13 is removed entirely.

``data/gold/CARMELINA/[TROY v1.1] Linagliptin (CARMELINA).json`` rule 1 says something
different: ``Occurrence {Type:0, Count:0}`` with ``!bt 6.5..10`` and no unit, which admits
a patient who has NO HbA1c recorded at all. The presence reading was chosen instead
because the trial enrolled people whose screening HbA1c was measured and in range, so
"no HbA1c on file" is not an eligible patient. ``!bt`` is also not emittable today
(``src/models/ir.py`` ``Literal[...]``, ``src/services/value_constraint.py``
``_CIRCE_OPS``) and adding it was declined. **The divergence from gold is deliberate and
is recorded here so a later reader does not "fix" it back.**

WHAT IT WILL NOT DO. An absence over a bound is the ORDINARY, CORRECT way to exclude an
out-of-range value, and the delivered corpus is full of them: ``deliveries/2026-06-24``
and ``deliveries/2026-08-31`` CARMELINA rule #5 is ``==0 HbA1c gte 10.0`` sitting beside
``>=1 HbA1c gte 6.5``, and that pair is perfectly satisfiable by every patient between 6.5
and 10. Eating it would be worse than the defect. So all five conditions must hold
together:

1. **Absence shape.** A top-level rule whose expression is ``ALL`` and whose criteria --
   held flat, or one per single-criterion ``ALL``/``ANY`` group -- are every one
   ``Measurement``, ``Occurrence {Type: 0, Count: 0}``, carrying a one-sided
   ``ValueAsNumber`` (``gte``/``lte``/``gt``/``lt``, no ``Extent``), all over the same
   ``StartWindow``. Demographics, a second domain, deeper nesting or a two-sided bound
   means this is not the shape and the rule is passed over silently.

2. **Exactly one partner presence.** A top-level rule whose expression is ``ALL`` holding
   one ``Measurement`` criterion, ``Occurrence {Type: 2, Count: 1}``, ``Op bt`` with
   ``Value`` low and ``Extent`` high, over the same ``StartWindow`` and over a concept set
   with the same members. More than one such rule, or a candidate still under ``ANY``, or
   still one-sided -- meaning
   :func:`~src.services.range_disjunction_repair.repair_range_disjunctions`
   DECLINED -- and this declines too and warns. Half-fixing a pair the collapse would not
   touch would silence :func:`~src.utils.circe_lint.unsatisfiable_presence_rules` without
   making the cohort non-empty, and that finding must stay a gate failure.

3. **A verbatim restatement, not a clip.** Each forbidden half-line must cover the WHOLE
   admissible range, decided by :func:`~src.utils.circe_lint._value_ranges_cover` -- the
   containment predicate :func:`~src.utils.circe_lint.bound_contradicted_presence_criteria`
   already uses, imported rather than reimplemented so the two cannot drift. Three shapes
   decline here, each of them a real and satisfiable rule:

   * ``==0 gte 10`` / ``==0 lte 6.5`` -- the correct exclusion in the correct polarity.
     Neither half covers ``6.5..10``, so containment fails.
   * ``==0 lt 6.5`` / ``==0 gt 10`` -- the same rule with inverted operators. The polarity
     check rejects it before containment.
   * ``==0 gte 6.0`` / ``==0 lte 10.5`` -- unsatisfiable too, but WIDER than the presence.
     Containment holds, so a second and deliberately conservative gate requires the two
     bounds to be the presence's own numbers exactly. This repair was measured on the
     verbatim restatement; a wider forbidding is a different author intent and is left to
     the gate to report.

4. **The same measurement.** Every concept set involved -- both of the absence's and the
   partner's -- resolves to the IDENTICAL, non-empty closure through the vocabulary, the
   way :mod:`src.services.range_disjunction_repair` condition 4 does. The resolved
   closure, not the name, decides: the name is model-written free text and is ``'HbA1c'``
   on all four of CARMELINA's sets. Unit filters are deliberately NOT compared -- the
   finding is that the rule restates the presence's bounds in the presence's own polarity,
   which holds under any unit, and in the ``verify4`` corpus the collapsed presence has
   already had its unit filter dropped while the absence still carries ``[8554]``.

5. **The name says so.** The delivered payloads carry no ``protocolLine``, so the rule
   name is the only provenance available at export time. It must split on ``" + "`` into
   one half per criterion; each half must carry a direction word that CONTRADICTS its
   criterion's operator (``below``/``lower`` against ``gte``, ``above``/``upper`` against
   ``lte``); and every half must reduce to the same non-empty subject as the partner
   presence's name. ``"HbA1c below lower limit"`` and ``"HbA1c above upper limit"`` both
   reduce to ``"hba1c"``, as do ``"HbA1c at least 6.5%"`` and ``"HbA1c at most 10.0%"``.

THE REPAIR ITSELF removes the rule from ``InclusionRules`` and records the removal under
:data:`RESTATED_ABSENCE_REMOVALS_KEY`. The concept sets are left in place, as every
sibling repair leaves them: pruning is a different concern and Atlas and WebAPI both
ignore an unused set.

**RULE-INDEX BOOKKEEPING.** Removing an entry renumbers every rule after it and leaves the
delivered file with one fewer rule than the store's ``structuredExpression``. Nothing in
the payload keys on a rule index -- ``_generationCensus`` counts criteria and is left
untouched for the same reason ``drop_unreadable_value_criteria`` leaves it alone, and every
other record key (``_skippedCriteria``, ``_restatedClusters``, ...) keys on
``criterionId``. What DOES notice is the delivery gate: ``scripts/verify_circe_delivery.py``
check (b) compares the file's rule-name multiset against the store's, adjusted ONLY by
``_droppedCriteria`` records, and ``_rule_multiset_check`` requires ``missing_count == 0``.
A removal this repair performs is therefore a rule-set mismatch the gate cannot attribute.
Laundering it through ``_droppedCriteria`` is not available: ``dropped_criteria_violations``
re-judges every record against ``unreadable_value_attributes``, and a removal for this
reason names no unreadable attribute. So the record is written to its own key, in the same
``rule``/``ruleAfter``/``outcome`` shape ``reconcile_dropped_rules`` replays, and
``scripts/verify_circe_delivery.py`` must be taught to consume it before the next delivery
is gated. Until then the gate will fail a repaired file on ``missing=1``, loudly and for a
reason the record explains.

No database import here. The vocabulary arrives as a
:class:`~src.services.conceptset_closure.VocabularyLookup`, which is what lets the tests
run the real closure resolver with no database at all.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Iterator

from src.services.conceptset_closure import VocabularyLookup, resolve_concept_set
from src.services.range_disjunction_repair import _BOUND_LANGUAGE, _NAME_SEPARATOR
from src.utils.circe_lint import (
    DROP_OUTCOME_RULE_REMOVED,
    _member_ids_by_codeset,
    _value_ranges,
    _value_ranges_cover,
)

#: Present-and-empty on every emitted expression, the same contract
#: :data:`~src.utils.circe_lint.DROPPED_CRITERIA_KEY` carries: an ABSENT key must mean
#: "predates this record", never "nothing was removed".
RESTATED_ABSENCE_REMOVALS_KEY = "_restatedAbsenceRemovals"

#: Group types that mean the same thing as ALL when the group holds one criterion.
_SINGLE_CRITERION_GROUP_TYPES = {"ALL", "ANY"}

_ONE_SIDED_OPS = {"gte", "lte", "gt", "lt"}

#: Direction language, by the side of the range it names. A half carrying words from both
#: classes is ambiguous and declines.
_DIRECTION_LOW = re.compile(
    r"\b(?:below|lower|beneath|less|under|minimum|min|floor)\b", re.IGNORECASE
)
_DIRECTION_HIGH = re.compile(
    r"\b(?:above|upper|higher|greater|over|exceeds?|exceeding|maximum|max|ceiling)\b",
    re.IGNORECASE,
)

#: The operator each direction class CONTRADICTS. "below the lower limit" beside a
#: criterion forbidding ``>= 6.5`` is the contradiction this repair keys on.
_CONTRADICTED_OP = {"low": "gte", "high": "lte"}

#: Stripped from a name half AFTER its direction class has been read, on top of
#: :data:`~src.services.range_disjunction_repair._BOUND_LANGUAGE`. What remains is the
#: subject the half is about.
_LIMIT_NOUNS = re.compile(
    r"\b(?:below|lower|beneath|less|under|minimum|min|floor|above|upper|higher|greater|"
    r"over|exceeds?|exceeding|maximum|max|ceiling|limits?|bounds?|boundary|boundaries|"
    r"thresholds?|ranges?|values?|cut\s*offs?|cutoffs?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AbsenceRemoval:
    """One applied removal, for the caller to log and for the payload to record."""

    rule_index: int
    rule_number: int
    rule_name: str
    partner_rule_index: int
    partner_rule_number: int
    partner_rule_name: str
    low: float
    high: float
    codeset_ids: tuple[int, ...]
    n_concepts: int

    def as_record(self) -> dict[str, Any]:
        """The payload record. ``ruleIndex`` is the index BEFORE the removal and
        ``ruleAfter``/``outcome`` are spelled the way ``_droppedCriteria`` spells them, so
        a reconciler can replay this the same way it replays a drop."""
        return {
            "ruleIndex": self.rule_index,
            "rule": self.rule_name,
            "ruleAfter": None,
            "outcome": DROP_OUTCOME_RULE_REMOVED,
            "partnerRuleIndex": self.partner_rule_index,
            "partnerRule": self.partner_rule_name,
            "low": self.low,
            "high": self.high,
            "codesetIds": list(self.codeset_ids),
            "nConcepts": self.n_concepts,
            "summary": (
                f"rule #{self.rule_number} {self.rule_name!r} forbade every value "
                f"rule #{self.partner_rule_number} {self.partner_rule_name!r} requires "
                f"(bt {self.low:g}..{self.high:g} over the same {self.n_concepts} "
                f"concepts and window), so the two were complements and the cohort was "
                f"empty; the absence rule was removed"
            ),
        }


@dataclass(frozen=True)
class RestatedAbsence:
    """An absence rule satisfying conditions 1, 2, 3 and 5, before the closure check."""

    rule_index: int
    rule: dict
    entries: tuple[dict, ...]
    partner_rule_index: int
    partner_rule: dict
    partner_entry: dict
    low: float
    high: float
    codeset_ids: tuple[int, ...] = field(default=())

    @property
    def rule_name(self) -> str:
        return str(self.rule.get("name") or "")

    @property
    def partner_rule_name(self) -> str:
        return str(self.partner_rule.get("name") or "")


# --------------------------------------------------------------------------
# shape -- no vocabulary needed
# --------------------------------------------------------------------------

def _measurement_body(entry: Any) -> dict | None:
    """The ``Measurement`` payload of a criterion entry holding only that, or None."""
    if not isinstance(entry, Mapping):
        return None
    criteria = entry.get("Criteria")
    if not isinstance(criteria, Mapping) or set(criteria) != {"Measurement"}:
        return None
    body = criteria["Measurement"]
    return body if isinstance(body, Mapping) else None


def _flatten_top_level(expression: Mapping[str, Any]) -> list[dict] | None:
    """Every criterion entry a rule holds at its top level, or None if it nests.

    Accepts the two shapes the builder emits: criteria held flat under ``CriteriaList``
    (what a collapsed rule looks like), and one criterion per single-criterion group
    (what a multi-part rule looks like). A group holding more than one criterion, a
    nested group, or any demographic criterion returns None -- that is not this shape.
    """
    if expression.get("DemographicCriteriaList"):
        return None
    entries = [e for e in (expression.get("CriteriaList") or []) if isinstance(e, dict)]
    if len(entries) != len(expression.get("CriteriaList") or []):
        return None
    for group in expression.get("Groups") or []:
        if not isinstance(group, Mapping):
            return None
        if str(group.get("Type", "ALL")).upper() not in _SINGLE_CRITERION_GROUP_TYPES:
            return None
        if group.get("Groups") or group.get("DemographicCriteriaList"):
            return None
        members = group.get("CriteriaList") or []
        if len(members) != 1 or not isinstance(members[0], dict):
            return None
        entries.append(members[0])
    return entries


def _one_sided_bound(body: Mapping[str, Any]) -> tuple[str, float] | None:
    """``(Op, Value)`` of a one-sided ``ValueAsNumber``, or None. An ``Extent`` present
    means the bound is already a range (or a ``!bt``) and is not one sided."""
    value = body.get("ValueAsNumber")
    if not isinstance(value, Mapping) or set(value) != {"Value", "Op"}:
        return None
    op = str(value.get("Op"))
    if op not in _ONE_SIDED_OPS:
        return None
    try:
        return op, float(value["Value"])
    except (TypeError, ValueError):
        return None


def _between_bound(body: Mapping[str, Any]) -> tuple[float, float] | None:
    """``(low, high)`` of a ``bt`` ``ValueAsNumber`` with ``low < high``, or None."""
    value = body.get("ValueAsNumber")
    if not isinstance(value, Mapping) or str(value.get("Op")) != "bt":
        return None
    if set(value) != {"Value", "Extent", "Op"}:
        return None
    try:
        low, high = float(value["Value"]), float(value["Extent"])
    except (TypeError, ValueError):
        return None
    return (low, high) if low < high else None


def _occurrence(entry: Mapping[str, Any]) -> tuple[Any, Any]:
    occurrence = entry.get("Occurrence")
    if not isinstance(occurrence, Mapping):
        return (None, None)
    return (occurrence.get("Type"), occurrence.get("Count"))


def _absence_entries(expression: Mapping[str, Any]) -> list[dict] | None:
    """Condition 1. The rule's criteria when every one is a one-sided zero-occurrence
    Measurement over one window, else None."""
    if str(expression.get("Type", "")).upper() != "ALL":
        return None
    entries = _flatten_top_level(expression)
    if not entries:
        return None
    windows = []
    for entry in entries:
        body = _measurement_body(entry)
        if body is None or _occurrence(entry) != (0, 0):
            return None
        if _one_sided_bound(body) is None:
            return None
        windows.append(entry.get("StartWindow"))
    if any(window != windows[0] for window in windows[1:]):
        return None
    return entries


def _sole_presence_entry(expression: Mapping[str, Any]) -> dict | None:
    """The one required Measurement criterion a top-level ``ALL`` rule holds, or None."""
    if str(expression.get("Type", "")).upper() != "ALL":
        return None
    entries = _flatten_top_level(expression)
    if not entries or len(entries) != 1:
        return None
    entry = entries[0]
    if _measurement_body(entry) is None or _occurrence(entry) != (2, 1):
        return None
    return entry


def _iter_presence_entries(expression: Mapping[str, Any]) -> Iterator[dict]:
    """Every required Measurement criterion a rule holds at its top level, however it is
    grouped. Used only to notice a CANDIDATE the repair then declines -- a rule still
    under ``ANY`` is reported, not repaired."""
    if not isinstance(expression, Mapping):
        return
    for entry in expression.get("CriteriaList") or []:
        if isinstance(entry, dict) and _measurement_body(entry) is not None:
            if _occurrence(entry) == (2, 1):
                yield entry
    for group in expression.get("Groups") or []:
        if isinstance(group, Mapping):
            yield from _iter_presence_entries(group)


def _codeset_id(body: Mapping[str, Any]) -> Any:
    return body.get("CodesetId")


def _subject(half: str) -> str:
    """A name half with its bound and direction language removed -- what it is about."""
    stripped = _LIMIT_NOUNS.sub(" ", _BOUND_LANGUAGE.sub(" ", half))
    return " ".join(stripped.lower().split())


def _name_subject(name: str) -> str | None:
    """The single subject every ``" + "``-joined half of a rule name reduces to."""
    subjects = {_subject(half) for half in name.split(_NAME_SEPARATOR)}
    if len(subjects) != 1:
        return None
    subject = subjects.pop()
    return subject or None


def _direction_class(half: str) -> str | None:
    """``"low"``, ``"high"``, or None when the half names neither or both."""
    low, high = bool(_DIRECTION_LOW.search(half)), bool(_DIRECTION_HIGH.search(half))
    if low == high:
        return None
    return "low" if low else "high"


def _why_name_does_not_restate(
    name: str, ops: list[str], partner_name: str
) -> str | None:
    """Condition 5. None when the name reads as the partner's range restated in the
    partner's own polarity; else why it does not."""
    halves = name.split(_NAME_SEPARATOR)
    if len(halves) != len(ops):
        return (
            f"name {name!r} splits into {len(halves)} half/halves on "
            f"{_NAME_SEPARATOR!r} but the rule holds {len(ops)} criteri"
            f"{'on' if len(ops) == 1 else 'a'}, so no half can be read against an operator"
        )
    for half, op in zip(halves, ops):
        direction = _direction_class(half)
        if direction is None:
            return (
                f"name half {half!r} names neither one side of a range nor exactly one, "
                f"so it cannot be read as contradicting {op!r}"
            )
        if _CONTRADICTED_OP[direction] != op:
            return (
                f"name half {half!r} reads as the {direction} side of the range while its "
                f"criterion forbids {op!r}, which does not contradict it -- that is an "
                f"ordinary one-sided exclusion, not a restatement"
            )
    subject = _name_subject(name)
    partner_subject = _name_subject(partner_name)
    if subject is None or partner_subject is None or subject != partner_subject:
        return (
            f"name {name!r} is about {subject!r} while the partner presence "
            f"{partner_name!r} is about {partner_subject!r}, so the two are not one "
            f"protocol sentence emitted twice"
        )
    return None


def iter_restated_absences(base: Mapping[str, Any]) -> Iterator[RestatedAbsence]:
    """Rules this repair could fire on, judged without a vocabulary.

    Applies conditions 1, 2, 3 and 5; condition 4 needs the concept closures and is
    applied by :func:`repair_restated_absences`. A caller can therefore ask whether
    anything could possibly fire before paying for a database round trip -- which is the
    answer for every file under ``data/gold/``, ``deliveries/2026-06-24`` and
    ``deliveries/2026-08-31``, and for four of the six in each 2026-09-12 and
    ``verify4`` export.

    Declines are logged only once a candidate partner presence exists over the same
    concept-set members and window. Anything short of that is not this shape at all and
    is passed over silently -- warning on every absence in every file would bury the two
    that matter.
    """
    rules = list(base.get("InclusionRules") or [])
    members_by_codeset = _member_ids_by_codeset(base)  # type: ignore[arg-type]

    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            # Must be mutable: the repair removes it from a rebuilt list and a
            # non-dict cannot carry a name to record.
            continue
        expression = rule.get("expression")
        if not isinstance(expression, Mapping):
            continue
        entries = _absence_entries(expression)
        if entries is None:
            continue

        bodies = [_measurement_body(entry) for entry in entries]
        bounds = [_one_sided_bound(body) for body in bodies]  # type: ignore[arg-type]
        member_keys = {
            members_by_codeset.get(_codeset_id(body)) for body in bodies  # type: ignore[arg-type]
        }
        if len(member_keys) != 1:
            continue
        members = member_keys.pop()
        if not members:
            continue
        window = entries[0].get("StartWindow")
        name = str(rule.get("name") or "")

        # --- condition 2: exactly one partner presence ---------------------
        eligible: list[tuple[int, dict, dict, float, float]] = []
        ineligible: list[str] = []
        for other_index, other in enumerate(rules):
            if other_index == index or not isinstance(other, Mapping):
                continue
            other_expression = other.get("expression")
            if not isinstance(other_expression, Mapping):
                continue
            about_the_same = [
                entry
                for entry in _iter_presence_entries(other_expression)
                if members_by_codeset.get(
                    _codeset_id(_measurement_body(entry))  # type: ignore[arg-type]
                )
                == members
                and entry.get("StartWindow") == window
            ]
            if not about_the_same:
                continue
            sole = _sole_presence_entry(other_expression)
            span = (
                _between_bound(_measurement_body(sole))  # type: ignore[arg-type]
                if sole is not None
                else None
            )
            if sole is not None and span is not None:
                eligible.append((other_index, other, sole, span[0], span[1]))  # type: ignore[arg-type]
            elif sole is None:
                ineligible.append(
                    f"rule #{other_index + 1} {str(other.get('name') or '')!r} is "
                    f"Type {str(other_expression.get('Type', '')).upper()!r} over "
                    f"{len(about_the_same)} presence criteri"
                    f"{'on' if len(about_the_same) == 1 else 'a'} rather than one "
                    f"top-level ALL holding a single criterion, so its bounds are still "
                    f"alternatives under ANY"
                )
            else:
                ineligible.append(
                    f"rule #{other_index + 1} {str(other.get('name') or '')!r} is still "
                    f"one-sided rather than a single bt range, which means the range "
                    f"collapse declined on it"
                )

        if not eligible and not ineligible:
            continue
        if not eligible:
            logging.warning(
                "[TTE] restated-absence repair declines rule #%d %r: no partner presence "
                "states the range as one bt criterion -- %s. The pair stays a gate "
                "finding rather than being half-fixed",
                index + 1, name, "; ".join(ineligible),
            )
            continue
        if len(eligible) > 1:
            logging.warning(
                "[TTE] restated-absence repair declines rule #%d %r: more than one "
                "candidate presence brackets the same %d concept-set members in the same "
                "window (%s), so which one this rule restates is not decidable from the "
                "file",
                index + 1, name, len(members),
                ", ".join(
                    f"#{i + 1} {str(r.get('name') or '')!r}"
                    for i, r, _e, _l, _h in eligible
                ),
            )
            continue

        partner_index, partner_rule, partner_entry, low, high = eligible[0]

        # --- condition 3: a verbatim restatement, not a clip --------------
        ops = [op for op, _value in bounds]  # type: ignore[misc]
        if len(entries) != 2 or sorted(ops) != ["gte", "lte"]:
            logging.warning(
                "[TTE] restated-absence repair declines rule #%d %r: its %d forbidden "
                "bound(s) %s are not one lower and one upper bound in the presence's own "
                "polarity, so they do not restate bt %g..%g",
                index + 1, name, len(entries),
                ", ".join(f"{op} {value:g}" for op, value in bounds),  # type: ignore[misc]
                low, high,
            )
            continue

        presence_ranges = _value_ranges(
            _measurement_body(partner_entry).get("ValueAsNumber")  # type: ignore[union-attr]
        )
        not_covering = [
            (op, value)
            for body, (op, value) in zip(bodies, bounds)  # type: ignore[misc]
            if not _value_ranges_cover(
                _value_ranges(body.get("ValueAsNumber")), presence_ranges  # type: ignore[union-attr]
            )
        ]
        if not_covering:
            logging.warning(
                "[TTE] restated-absence repair declines rule #%d %r: %s merely clips the "
                "range bt %g..%g that rule #%d %r requires rather than covering all of "
                "it, which is the ordinary correct way to exclude an out-of-range value "
                "and leaves the pair satisfiable",
                index + 1, name,
                " and ".join(f"{op} {value:g}" for op, value in not_covering),
                low, high, partner_index + 1, str(partner_rule.get("name") or ""),
            )
            continue

        forbidden = {(op, value) for op, value in bounds}  # type: ignore[misc]
        if forbidden != {("gte", low), ("lte", high)}:
            logging.warning(
                "[TTE] restated-absence repair declines rule #%d %r: its forbidden "
                "bounds %s are not the presence's own bounds %g and %g verbatim -- the "
                "rule is unsatisfiable but forbids a WIDER range, which is a different "
                "author intent than the restatement this repair was measured on",
                index + 1, name,
                ", ".join(f"{op} {value:g}" for op, value in sorted(forbidden)),
                low, high,
            )
            continue

        # --- condition 5: the name says so --------------------------------
        why_not = _why_name_does_not_restate(
            name, list(ops), str(partner_rule.get("name") or "")
        )
        if why_not is not None:
            logging.warning(
                "[TTE] restated-absence repair declines rule #%d: %s", index + 1, why_not
            )
            continue

        yield RestatedAbsence(
            rule_index=index,
            rule=rule,
            entries=tuple(entries),
            partner_rule_index=partner_index,
            partner_rule=partner_rule,
            partner_entry=partner_entry,
            low=low,
            high=high,
            codeset_ids=tuple(
                int(_codeset_id(body))
                for body in (*bodies, _measurement_body(partner_entry))
                if _codeset_id(body) is not None  # type: ignore[arg-type]
            ),
        )


# --------------------------------------------------------------------------
# the repair
# --------------------------------------------------------------------------

def repair_restated_absences(
    base: dict[str, Any], lookup: VocabularyLookup
) -> list[AbsenceRemoval]:
    """Remove an inclusion rule that forbids every value its partner presence requires.

    Mutates ``base``: shrinks ``InclusionRules`` and sets
    :data:`RESTATED_ABSENCE_REMOVALS_KEY` to the record list (present and empty when
    nothing fired).

    :param base: a Circe cohort expression (ConceptSets / PrimaryCriteria /
        InclusionRules), mutated in place.
    :param lookup: vocabulary access for resolving concept-set closures (condition 4).
    :returns: one record per removed rule; empty means nothing satisfied all five
        conditions, which is the expected answer for every file but the four CARMELINA
        payloads of 2026-09-12 and 2026-09-18.
    """
    candidates = list(iter_restated_absences(base))
    base[RESTATED_ABSENCE_REMOVALS_KEY] = records = []
    if not candidates:
        return []

    by_id = {int(cs["id"]): cs for cs in base.get("ConceptSets") or [] if "id" in cs}
    applied: list[AbsenceRemoval] = []
    removed_indices: set[int] = set()

    for candidate in candidates:
        sets = [by_id.get(codeset_id) for codeset_id in candidate.codeset_ids]
        if any(concept_set is None for concept_set in sets):
            logging.warning(
                "[TTE] restated-absence repair declines rule #%d %r: codeset %s is not "
                "in ConceptSets, so its closure cannot be compared",
                candidate.rule_index + 1, candidate.rule_name,
                [i for i, s in zip(candidate.codeset_ids, sets) if s is None],
            )
            continue

        closures = [resolve_concept_set(cs, lookup) for cs in sets]  # type: ignore[arg-type]
        unresolvable: set[int] = set()
        for closure in closures:
            unresolvable |= closure.unresolvable_ids
        if unresolvable:
            logging.warning(
                "[TTE] restated-absence repair declines rule #%d %r: concept(s) %s in "
                "codesets %s do not resolve in the vocabulary, so the sets cannot be "
                "compared",
                candidate.rule_index + 1, candidate.rule_name, sorted(unresolvable),
                list(candidate.codeset_ids),
            )
            continue

        distinct = {frozenset(closure.concept_ids) for closure in closures}
        if len(distinct) != 1 or not next(iter(distinct)):
            logging.warning(
                "[TTE] restated-absence repair declines rule #%d %r: codesets %s resolve "
                "to %s concepts respectively rather than one identical non-empty closure "
                "-- forbidding one analyte's range while requiring another's is a real "
                "exclusion, not a restatement",
                candidate.rule_index + 1, candidate.rule_name,
                list(candidate.codeset_ids),
                [len(closure.concept_ids) for closure in closures],
            )
            continue

        n_concepts = len(next(iter(distinct)))
        removed_indices.add(candidate.rule_index)
        record = AbsenceRemoval(
            rule_index=candidate.rule_index,
            rule_number=candidate.rule_index + 1,
            rule_name=candidate.rule_name,
            partner_rule_index=candidate.partner_rule_index,
            partner_rule_number=candidate.partner_rule_index + 1,
            partner_rule_name=candidate.partner_rule_name,
            low=candidate.low,
            high=candidate.high,
            codeset_ids=candidate.codeset_ids,
            n_concepts=n_concepts,
        )
        applied.append(record)
        records.append(record.as_record())
        logging.warning(
            "[TTE] restated-absence repair: rule #%d %r forbade gte %g and lte %g over "
            "the same %d concepts and window that rule #%d %r requires as bt %g..%g, so "
            "the two were logical complements and the cohort was 0 people on any CDM -- "
            "the absence rule is removed and the presence is left as the single "
            "statement of the protocol range",
            candidate.rule_index + 1, candidate.rule_name, candidate.low, candidate.high,
            n_concepts, candidate.partner_rule_index + 1, candidate.partner_rule_name,
            candidate.low, candidate.high,
        )

    if removed_indices:
        base["InclusionRules"] = [
            rule
            for index, rule in enumerate(base.get("InclusionRules") or [])
            if index not in removed_indices
        ]
    return applied
