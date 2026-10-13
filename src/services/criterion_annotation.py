"""The annotation step: one LLM call per rule records what its protocol line says about it.

RFC-016 §2 / §6 step 1. Agent 1 and the planner extract a criterion's entity, domain,
logic, window and value. Two further facts about a criterion live only in its protocol
line, and until this step nothing recorded them, so later stages re-derived them from
free text with English word lists (the former ``dose_stability.py`` and
``entity_exception.py``, both removed in this step):

* ``record_requirement`` -- whether the criterion asks for a record of its entity
  (``required``), for its absence (``forbidden``), or only conditions patients who
  already have that record or belong to a subgroup the line names (``conditional``).
  A ``conditional`` rule has no occurrence expression: emitted as PRESENCE it drops
  every patient without the record, which is how CARMELINA's comparator fell 38,664 ->
  1,257 at Ajou on "Stable antidiabetic background medication" (2026-09-23 send).
* ``excepted_entities`` -- the entities the line removes from the set the criterion
  names. Each one is mapped and subtracted as ``isExcluded`` by
  :func:`src.services.entity_subtraction.resolve_entity_exception`.
* ``base_span`` -- the fragment of the line naming the set the exception is taken from.
  When accepted it replaces the mapper seed (:func:`stated_base`), because a seed that
  carries the whole clause ("cancer other than non-melanoma skin cancer within last 3
  years") is mapped tail-first and the subtraction then has nothing sound to act on.

RFC-016 step 2 (RFC-014) adds two more, replacing the word rules that read them off the
line (inventory A2, A4, A18, E3):

* ``relation`` (+ ``relation_span``, ``cardinality``) -- how the line combines a group's
  members: ``all``, ``any`` or ``at_least`` N. :func:`stated_relation` hands the verified
  value to the builder, which derives the group's CIRCE ``Type`` from it and the logic
  (:func:`relation_group_type`). The planner states the same field when it splits a line;
  the annotation's is read only when the planner left none.
* ``timing`` (+ ``window_span``) -- whether the line places the criterion before entry,
  at entry, or after it. A ``prospective`` criterion is not observable at index, so it is
  not emitted as an occurrence; it is recorded as a skip under :data:`PROSPECTIVE_REASON`
  (:func:`prospective_skips`).

The model decides the meaning and quotes the fragment of ``protocolLine`` that supports
it. Code checks one thing only: that each quoted fragment is a substring of the line
(:func:`span_in_line`, from :mod:`src.utils.span_match`: the comparison form every span
check in the pipeline shares, segmentation and the planner included; the planner and the
delivery gate import it from this module). A fragment that
is not in the line makes its field absent -- the row then takes the default behaviour --
and the rejection is recorded on the row under :data:`ANNOTATION_REJECTED_KEY` so it can
be counted. Nothing here reads the line, the description or the entity as words.

The prompt also shows the trial's other ``protocolLine`` values of the row's role
(:func:`context_lines`), for one decision only: whether the criterion applies to every
patient or only to record holders or a subgroup. A line read alone can state a requirement
that another line of the same role makes conditional (CARMELINA inclusion 7 against
inclusion 2, which admits drug-naive patients). ``conditional_span`` alone may be quoted from
one of those lines; the line it verified in is recorded verbatim under
:data:`FIELD_CONDITIONAL_SPAN_LINE`, and the build and the delivery gate re-check the span
against that line, which must itself be a ``protocolLine`` of the same role
(:func:`conditional_span_holds`).

Separate from Agent 1 on purpose (RFC-016 §2): the annotation can be re-run on an
existing store without re-extraction, so it runs inside ``process_eligibility`` and a dry
rebuild reaches it.

Cache: one JSONL file, keyed on the prompt text, the prompt version, the resolved model
and the rendered inputs (protocol line plus the extracted fields). The path is
``ARTEMIS_ANNOTATION_CACHE_PATH`` when set, so a run can isolate its cache;
``ARTEMIS_ANNOTATION_CACHE=0`` disables it. Failed calls are never cached.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from src.services.loinc_specimen import MEASUREMENT_DOMAIN
from src.services.route_subtraction import AdministrationRoute
from src.utils.span_match import span_in_line

logger = logging.getLogger(__name__)

#: Bumped whenever either prompt below changes meaning; part of the cache key.
ANNOTATION_PROMPT_VERSION = "rfc016-steps1-4-context-v1"

#: The row key the annotation is stored under, and the key its rejections go to.
ANNOTATION_KEY = "annotation"
ANNOTATION_REJECTED_KEY = "_annotationRejected"
#: Expression key: the thresholds a verified annotation says no CIRCE value filter represents.
UNREPRESENTABLE_THRESHOLDS_KEY = "_unrepresentableThresholds"
#: The ``reason`` each of those records carries.
THRESHOLD_NOT_REPRESENTABLE_REASON = "threshold-not-representable"
#: Agent 1's own subgroup flag (``Criteria.conditional``), carried onto the store row by
#: ``TTEService._criteria_from_ir`` instead of the row being dropped.
EXTRACTED_CONDITIONAL_KEY = "conditional"
#: The planner's ``excepted_entities`` for a criterion it kept whole (RFC-016 §3, last
#: paragraph). Read before the annotation's own: the annotation fills it only when empty.
PLANNER_EXCEPTED_KEY = "exceptedEntities"

#: Output fields, as the prompt names them and as the row stores them.
FIELD_RECORD_REQUIREMENT = "record_requirement"
FIELD_CONDITIONAL_SPAN = "conditional_span"
#: Not an output field: set by :func:`validate_annotation`, never read from the answer. The
#: other ``protocolLine`` of the row's role that ``conditional_span`` was verified in, verbatim;
#: None when it was verified in the row's own line (and on every annotation stored before the
#: prompt showed other lines). Readers re-check the span against this line, so none of them
#: re-derives the lines the prompt showed.
FIELD_CONDITIONAL_SPAN_LINE = "conditional_span_line"
FIELD_EXCEPTED_ENTITIES = "excepted_entities"
FIELD_BASE_SPAN = "base_span"
FIELD_TEXT = "text"
FIELD_SPAN = "span"
FIELD_RELATION = "relation"
FIELD_RELATION_SPAN = "relation_span"
FIELD_CARDINALITY = "cardinality"
FIELD_TIMING = "timing"
FIELD_WINDOW_SPAN = "window_span"

#: The planner's verified relation for a criterion it split (RFC-016 §3, last paragraph),
#: as ``{relation, relation_span, cardinality}``. Read before the annotation's own.
PLANNER_RELATION_KEY = "plannerRelation"
#: Where :func:`window_disagreement` records a verified ``window_span`` whose own duration
#: is not the extracted window. A report: nothing reads it to change a rule.
WINDOW_DISAGREEMENT_KEY = "_windowDisagreement"

FIELD_ROUTE = "route"
FIELD_ROUTE_SPAN = "route_span"
FIELD_SPECIMEN = "specimen"
FIELD_SPECIMEN_SPAN = "specimen_span"
FIELD_NO_ENTITY = "no_entity"
FIELD_NO_ENTITY_SPAN = "no_entity_span"
#: The one ``route`` entry that states no restriction; it stands alone in the list.
ROUTE_ANY = "any"
#: RFC-016 step 3. The three stand or fall together (:func:`validate_annotation`).
FIELD_THRESHOLD_SPAN = "threshold_span"
FIELD_QUANTITY_KIND = "quantity_kind"
FIELD_REFERENCE_BOUND = "reference_bound"

#: Store row keys the inputs are read from.
_LINE = "protocolLine"
_ID = "id"
_GROUP = "groupId"
_PARENT_GROUP = "parentGroupId"
_IS_LABEL = "isGroupLabel"

INCLUSION = "inclusion"
EXCLUSION = "exclusion"
_INCLUSION_ROWS = "inclusionCriteria"
_EXCLUSION_ROWS = "exclusionCriteria"
_ROLE_ROWS = ((INCLUSION, _INCLUSION_ROWS), (EXCLUSION, _EXCLUSION_ROWS))

#: Recorded on each skipped criterion; permitted by the delivery gate only when the
#: recorded span is a substring of the deciding row's ``protocolLine``.
CONDITIONAL_REASON = "conditional-on-existing-record"
CONDITIONAL_EXPLANATION = (
    "The protocol line states this criterion only for patients who already have the "
    "record (or belong to the subgroup) it names; a patient without that record is not "
    "filtered by it. CIRCE has no conditional occurrence, and emitted as a presence rule "
    "it would require that record of every patient."
)

#: Where a conditional skip was decided.
SOURCE_ANNOTATION = "annotation"
SOURCE_EXTRACTION = "extraction"
SOURCE_PLANNER = "planner"

#: Recorded on each criterion the annotation places after entry; permitted by the delivery
#: gate only when the recorded span is a substring of the deciding row's ``protocolLine``.
PROSPECTIVE_REASON = "prospective-not-observable-at-index"
PROSPECTIVE_EXPLANATION = (
    "The protocol line places this criterion after the patient enters the trial (planned "
    "or expected). Nothing at index records it, and emitted as an occurrence it would be "
    "read from the patient's past."
)


class RecordRequirement(str, Enum):
    """The three values of ``record_requirement`` (RFC-015 §2-1)."""

    REQUIRED = "required"
    FORBIDDEN = "forbidden"
    CONDITIONAL = "conditional"


class Relation(str, Enum):
    """The three values of ``relation`` (RFC-014 §2-1)."""

    ALL = "all"
    ANY = "any"
    AT_LEAST = "at_least"


class Timing(str, Enum):
    """The three values of ``timing`` (RFC-014 §2-2)."""

    PRIOR = "prior"
    AT_INDEX = "at_index"
    PROSPECTIVE = "prospective"


_REQUIREMENT_VALUES = frozenset(member.value for member in RecordRequirement)
_RELATION_VALUES = frozenset(member.value for member in Relation)
_TIMING_VALUES = frozenset(member.value for member in Timing)


class Specimen(str, Enum):
    """The body material the line says the measured quantity is taken from (RFC-016 §3)."""

    BLOOD = "blood"
    URINE = "urine"
    OTHER = "other"
    ANY = "any"


class NoEntity(str, Enum):
    """Whether the line names a clinical entity a vocabulary could hold (RFC-016 §3)."""

    NONE = "none"
    REFERS_ELSEWHERE = "refers_elsewhere"
    INVESTIGATOR_JUDGEMENT = "investigator_judgement"


_ROUTE_VALUES = frozenset(route.value for route in AdministrationRoute)
_SPECIMEN_VALUES = frozenset(member.value for member in Specimen)
_NO_ENTITY_VALUES = frozenset(member.value for member in NoEntity)


def _quoted(values: Iterable[str]) -> str:
    return ", ".join(f"`{value}`" for value in values)


class QuantityKind(str, Enum):
    """What the number in ``threshold_span`` measures (RFC-016 §3)."""

    LAB_VALUE = "lab_value"
    DOSE = "dose"
    DURATION = "duration"
    COUNT = "count"
    STATISTICAL = "statistical"
    OTHER = "other"


class StatedReferenceBound(str, Enum):
    """What that number is compared against, as the annotation states it.

    ``none`` is the store's ``referenceBound: "absolute"``; :class:`StatedThreshold`
    carries the store's spelling so its readers need no second vocabulary.
    """

    ULN = "uln"
    LLN = "lln"
    NONE = "none"


_KIND_VALUES = frozenset(member.value for member in QuantityKind)
_BOUND_VALUES = frozenset(member.value for member in StatedReferenceBound)


ANNOTATION_SYSTEM_PROMPT = """You annotate one eligibility criterion of a clinical trial protocol.

The criterion has already been extracted from a line of the protocol, and you do not change \
any extracted field. You read that protocol line and record the facts the fields below \
define about the criterion, each together with the fragment of the protocol line that \
states it.

Every fragment you return is copied from the protocol line character for character: no \
paraphrase, no expanded abbreviation, no added word. A fragment that does not occur in the \
protocol line is discarded together with the answer it supports. The one exception is \
`conditional_span`, which may instead be copied, character for character, from one of the \
trial's other lines given with the criterion; it is discarded when it occurs in none of them.

Return one JSON object and nothing else."""

ANNOTATION_PROMPT = """Protocol line:
{protocol_line}

The trial's other {role} lines:
{context_lines}

Extracted criterion:
- Role: {role}
- Entity text: {entity_text}
- Description: {description}
- Domain: {domain}
- Logic type: {logic_type}
- Window: {window}
- Value constraint: {value_constraint}
- Group label: {group_label}
- Members: {members}

Fields to return:

`record_requirement` states what this criterion asks of the patient's record of the entity \
it names, as the protocol line states it. One of:
- `required`: the patient meets the criterion only if a record of the entity exists.
- `forbidden`: the patient meets the criterion only if no record of the entity exists.
- `conditional`: the line applies the criterion only to patients who already have a record \
of the entity, or who belong to a subgroup the line names; a patient without that record or \
outside that subgroup is not filtered by this criterion at all.

The trial's other {role} lines are given for one purpose only: to decide whether this \
criterion applies to every patient, or only to patients who already have a record of the \
entity or who belong to a subgroup. Every other field is read from the protocol line alone.

`conditional_span` is the fragment that limits the criterion to those patients, copied from \
the protocol line or from one of the trial's other {role} lines. It is required when \
`record_requirement` is `conditional` and null otherwise.

`excepted_entities` lists the entities the protocol line explicitly removes from the set \
that this criterion's entity names, one entry per removed entity: `text` is the name of the \
removed entity to look up in a clinical vocabulary, and `span` is the fragment of the \
protocol line that names it. It is an empty list when the line removes nothing from that set.

`base_span` is the fragment of the protocol line that names the set the excepted entities \
are removed from. It is required when `excepted_entities` is not empty and null otherwise.

`relation` states how the protocol line combines the members listed above into this \
criterion, read without the criterion's logic type. One of:
- `all`: the criterion holds only when every member holds.
- `any`: the criterion holds when at least one member holds.
- `at_least`: the criterion holds when at least a stated number of members hold.
It is null when the criterion has no members.

`relation_span` is the fragment of the protocol line that states how the members combine. \
It is required when `relation` is not null and null otherwise.

`cardinality` is the stated number of members, as an integer, when `relation` is \
`at_least`, and null otherwise.

`timing` states when, relative to the patient's entry into the trial, the protocol line \
places what this criterion describes. One of:
- `prior`: before entry.
- `at_index`: at entry.
- `prospective`: after entry, as something planned or expected to happen.

`window_span` is the fragment of the protocol line that places the criterion in time. It is \
required when `timing` is `prospective`; otherwise it is that fragment when the line states \
one, and null when the line does not.

`route` lists the routes of administration the protocol line restricts this criterion's drug \
to. Each entry is one of the route values a clinical vocabulary attaches to drug dose forms: \
{route_values}. A value covers the routes the vocabulary files under it: `topical` covers \
`transdermal`, and `respiratory_tract` covers `nasal`. When the line restricts the drug by \
where in the body it acts rather than by naming a route, list every route value by which a \
drug of that kind acts there. The list holds the single value `any` when the line places no \
restriction on route, and when the criterion's entity is not a drug.

`route_span` is the fragment of the protocol line that states the route restriction. It is \
required when `route` is not `any` and null otherwise.

`specimen` states the body material in which the protocol line says the quantity this \
criterion measures is taken. One of:
- `blood`: blood, or a fraction separated from blood.
- `urine`: urine.
- `other`: a body material that is neither blood nor urine.
- `any`: the line names no body material, or the criterion measures no quantity.

`specimen_span` is the fragment of the protocol line that names the body material. It is \
required when `specimen` is not `any` and null otherwise.

`no_entity` states whether the protocol line names, for this criterion, a clinical entity \
that a clinical vocabulary could hold. One of:
- `none`: the line names such an entity.
- `refers_elsewhere`: the line names no such entity and identifies what the criterion is \
about only by pointing elsewhere: to an item, list, table or appendix of the protocol, or to \
a product known only by its role in a study.
- `investigator_judgement`: the line names no such entity and leaves the criterion to the \
investigator's assessment.

`no_entity_span` is the fragment of the protocol line that points elsewhere or states the \
assessment. It is required when `no_entity` is not `none` and null otherwise.

`threshold_span` is the fragment of the protocol line that states the numeric threshold this \
criterion compares its own entity against: the comparison, the number, and the unit or the \
reference limit, as written. It is null when the line states no numeric threshold for this \
criterion's entity.

`quantity_kind` states what the number in `threshold_span` measures. One of:
- `lab_value`: a value that a laboratory test or a clinical measurement records for the patient.
- `dose`: an amount of a drug that is given, taken or prescribed.
- `duration`: how long a condition, a treatment or a state has lasted or must last.
- `count`: a number of events, of episodes, or of listed items that must hold.
- `statistical`: a quantity of the trial's statistical design rather than of the patient.
- `other`: any other quantity.
It is null when `threshold_span` is null.

`reference_bound` states what the number in `threshold_span` is compared against. One of:
- `uln`: a multiple of the upper limit of the normal range of the laboratory that measured it.
- `lln`: a multiple of the lower limit of the normal range of the laboratory that measured it.
- `none`: the number itself, in the unit that `threshold_span` states.
It is null when `threshold_span` is null.

Output JSON:
{{"record_requirement": "<required|forbidden|conditional>", \
"conditional_span": "<fragment of the protocol line, or null>", \
"excepted_entities": [{{"text": "<entity name>", "span": "<fragment of the protocol line>"}}], \
"base_span": "<fragment of the protocol line, or null>", \
"relation": "<all|any|at_least, or null>", \
"relation_span": "<fragment of the protocol line, or null>", \
"cardinality": "<integer, or null>", \
"timing": "<prior|at_index|prospective>", \
"window_span": "<fragment of the protocol line, or null>", \
"route": ["<route value or any>"], \
"route_span": "<fragment of the protocol line, or null>", \
"specimen": "<blood|urine|other|any>", \
"specimen_span": "<fragment of the protocol line, or null>", \
"no_entity": "<none|refers_elsewhere|investigator_judgement>", \
"no_entity_span": "<fragment of the protocol line, or null>", \
"threshold_span": "<fragment of the protocol line, or null>", \
"quantity_kind": "<lab_value|dose|duration|count|statistical|other, or null>", \
"reference_bound": "<uln|lln|none, or null>"}}"""


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def _rejection(field: str, value: Any, reason: str) -> dict[str, Any]:
    return {"field": field, "value": value, "reason": reason}


def _enum_value(raw: Any) -> str | None:
    return raw.strip().casefold() if isinstance(raw, str) else None


def _count(raw: Any) -> int | None:
    """A cardinality as a positive integer, or None. Parses a number, never words."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= 1 else None
    if isinstance(raw, float) and raw.is_integer():
        return int(raw) if raw >= 1 else None
    if isinstance(raw, str):
        try:
            value = int(raw.strip())
        except ValueError:
            return None
        return value if value >= 1 else None
    return None


def check_relation(
    payload: Any, protocol_line: Any
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The relation fields of one answer, kept only when their evidence is in the line.

    Shared by the annotation step, the planner (:mod:`src.agents.planner.decomposer`) and
    :func:`stated_relation`, so the three can never disagree about what verifies.

    :param payload: an object carrying ``relation``, ``relation_span``, ``cardinality``.
    :param protocol_line: the row's ``protocolLine``.
    :returns: ``(fields, rejection)``. ``fields`` always has the three keys, all None
        unless the relation verified; ``rejection`` is None when nothing was dropped
        (including a null relation, which is no claim at all).
    """
    fields: dict[str, Any] = {
        FIELD_RELATION: None,
        FIELD_RELATION_SPAN: None,
        FIELD_CARDINALITY: None,
    }
    if not isinstance(payload, Mapping):
        return fields, None
    raw = payload.get(FIELD_RELATION)
    if raw is None:
        return fields, None
    value = _enum_value(raw)
    span = payload.get(FIELD_RELATION_SPAN)
    count = _count(payload.get(FIELD_CARDINALITY))
    claimed = {
        FIELD_RELATION: raw,
        FIELD_RELATION_SPAN: span,
        FIELD_CARDINALITY: payload.get(FIELD_CARDINALITY),
    }
    if value not in _RELATION_VALUES:
        return fields, _rejection(FIELD_RELATION, claimed, f"not one of {sorted(_RELATION_VALUES)}")
    if not span_in_line(span, protocol_line):
        return fields, _rejection(
            FIELD_RELATION, claimed, f"{FIELD_RELATION_SPAN} is not a substring of protocolLine"
        )
    if value == Relation.AT_LEAST.value and count is None:
        return fields, _rejection(
            FIELD_RELATION, claimed, f"{FIELD_CARDINALITY} is not a positive integer"
        )
    fields[FIELD_RELATION] = value
    fields[FIELD_RELATION_SPAN] = span
    fields[FIELD_CARDINALITY] = count if value == Relation.AT_LEAST.value else None
    return fields, None


def _check_timing(
    payload: Mapping[str, Any], protocol_line: str
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    fields: dict[str, Any] = {FIELD_TIMING: None, FIELD_WINDOW_SPAN: None}
    raw = payload.get(FIELD_TIMING)
    if raw is None:
        return fields, None
    value = _enum_value(raw)
    span = payload.get(FIELD_WINDOW_SPAN)
    quoted = isinstance(span, str) and bool(span.strip())
    claimed = {FIELD_TIMING: raw, FIELD_WINDOW_SPAN: span}
    if value not in _TIMING_VALUES:
        return fields, _rejection(FIELD_TIMING, claimed, f"not one of {sorted(_TIMING_VALUES)}")
    if (value == Timing.PROSPECTIVE.value or quoted) and not span_in_line(span, protocol_line):
        return fields, _rejection(
            FIELD_TIMING, claimed, f"{FIELD_WINDOW_SPAN} is not a substring of protocolLine"
        )
    fields[FIELD_TIMING] = value
    fields[FIELD_WINDOW_SPAN] = span if quoted else None
    return fields, None


def validate_annotation(
    payload: Any, protocol_line: str, context: Sequence[str] = ()
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Keep each field whose evidence is in the line; record why any other was dropped.

    :param payload: the model's parsed JSON object.
    :param protocol_line: the row's ``protocolLine``.
    :param context: the other lines of the row's role the prompt showed
        (:func:`context_lines`). Only ``conditional_span`` may be quoted from one of them:
        it is accepted from the first line, in the order given, that holds it, and that
        line is recorded under :data:`FIELD_CONDITIONAL_SPAN_LINE`. Every other fragment
        is checked against ``protocol_line`` alone.
    :returns: ``(fields, rejections)``. ``fields`` always carries every output key; a
        rejected field is None (``record_requirement``, ``base_span``, ``relation``,
        ``timing`` and their spans, the three threshold fields) or left out of the list
        (``excepted_entities``), which is the default behaviour downstream.
    """
    fields: dict[str, Any] = {
        FIELD_RECORD_REQUIREMENT: None,
        FIELD_CONDITIONAL_SPAN: None,
        FIELD_CONDITIONAL_SPAN_LINE: None,
        FIELD_EXCEPTED_ENTITIES: [],
        FIELD_BASE_SPAN: None,
        FIELD_RELATION: None,
        FIELD_RELATION_SPAN: None,
        FIELD_CARDINALITY: None,
        FIELD_TIMING: None,
        FIELD_WINDOW_SPAN: None,
        FIELD_ROUTE: None,
        FIELD_ROUTE_SPAN: None,
        FIELD_SPECIMEN: None,
        FIELD_SPECIMEN_SPAN: None,
        FIELD_NO_ENTITY: None,
        FIELD_NO_ENTITY_SPAN: None,
    }
    rejected: list[dict[str, Any]] = []
    if not isinstance(payload, Mapping):
        rejected.append(_rejection("*", payload, "the response is not a JSON object"))
        return fields, rejected

    raw = payload.get(FIELD_RECORD_REQUIREMENT)
    value = raw.strip().casefold() if isinstance(raw, str) else None
    span = payload.get(FIELD_CONDITIONAL_SPAN)
    if value not in _REQUIREMENT_VALUES:
        rejected.append(
            _rejection(
                FIELD_RECORD_REQUIREMENT,
                raw,
                f"not one of {sorted(_REQUIREMENT_VALUES)}",
            )
        )
    elif value == RecordRequirement.CONDITIONAL.value and not span_in_line(span, protocol_line):
        source = next((line for line in context if span_in_line(span, line)), None)
        if source is None:
            rejected.append(
                _rejection(
                    FIELD_RECORD_REQUIREMENT,
                    {FIELD_RECORD_REQUIREMENT: raw, FIELD_CONDITIONAL_SPAN: span},
                    f"{FIELD_CONDITIONAL_SPAN} is not a substring of protocolLine"
                    + (" or of any other line of its role shown" if context else ""),
                )
            )
        else:
            fields[FIELD_RECORD_REQUIREMENT] = value
            fields[FIELD_CONDITIONAL_SPAN] = span
            fields[FIELD_CONDITIONAL_SPAN_LINE] = source
    else:
        fields[FIELD_RECORD_REQUIREMENT] = value
        if value == RecordRequirement.CONDITIONAL.value:
            fields[FIELD_CONDITIONAL_SPAN] = span

    entries = payload.get(FIELD_EXCEPTED_ENTITIES)
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        rejected.append(_rejection(FIELD_EXCEPTED_ENTITIES, entries, "not a list"))
        entries = []
    for entry in entries:
        text = entry.get(FIELD_TEXT) if isinstance(entry, Mapping) else None
        entry_span = entry.get(FIELD_SPAN) if isinstance(entry, Mapping) else None
        if not isinstance(text, str) or not text.strip():
            rejected.append(_rejection(FIELD_EXCEPTED_ENTITIES, entry, f"{FIELD_TEXT} is empty"))
        elif not span_in_line(entry_span, protocol_line):
            rejected.append(
                _rejection(
                    FIELD_EXCEPTED_ENTITIES,
                    entry,
                    f"{FIELD_SPAN} is not a substring of protocolLine",
                )
            )
        else:
            fields[FIELD_EXCEPTED_ENTITIES].append(
                {FIELD_TEXT: text.strip(), FIELD_SPAN: entry_span}
            )

    base = payload.get(FIELD_BASE_SPAN)
    if not fields[FIELD_EXCEPTED_ENTITIES]:
        if base is not None:
            rejected.append(_rejection(FIELD_BASE_SPAN, base, "no excepted entity was accepted"))
    elif not span_in_line(base, protocol_line):
        rejected.append(_rejection(FIELD_BASE_SPAN, base, "not a substring of protocolLine"))
    else:
        fields[FIELD_BASE_SPAN] = " ".join(base.split())

    for check in (check_relation, _check_timing):
        checked, rejection = check(payload, protocol_line)
        fields.update(checked)
        if rejection is not None:
            rejected.append(rejection)
    _validate_route(payload, protocol_line, fields, rejected)
    _validate_choice(
        payload,
        protocol_line,
        fields,
        rejected,
        field=FIELD_SPECIMEN,
        span_field=FIELD_SPECIMEN_SPAN,
        values=_SPECIMEN_VALUES,
        spanless=Specimen.ANY.value,
    )
    _validate_choice(
        payload,
        protocol_line,
        fields,
        rejected,
        field=FIELD_NO_ENTITY,
        span_field=FIELD_NO_ENTITY_SPAN,
        values=_NO_ENTITY_VALUES,
        spanless=NoEntity.NONE.value,
    )
    fields.update(_validate_threshold(payload, protocol_line, rejected))
    return fields, rejected


def _validate_choice(
    payload: Mapping[str, Any],
    protocol_line: Any,
    fields: dict[str, Any],
    rejected: list[dict[str, Any]],
    *,
    field: str,
    span_field: str,
    values: frozenset[str],
    spanless: str,
) -> None:
    """One enum field and its fragment: kept when the value is defined and, unless it is the
    value that needs no fragment, the fragment is in the line. Absent stays absent."""
    raw = payload.get(field)
    if raw is None:
        return
    value = _enum_value(raw)
    span = payload.get(span_field)
    if value not in values:
        rejected.append(_rejection(field, raw, f"not one of {sorted(values)}"))
    elif value == spanless:
        fields[field] = value
    elif not span_in_line(span, protocol_line):
        rejected.append(
            _rejection(
                field,
                {field: raw, span_field: span},
                f"{span_field} is not a substring of protocolLine",
            )
        )
    else:
        fields[field] = value
        fields[span_field] = span


def _validate_route(
    payload: Mapping[str, Any],
    protocol_line: Any,
    fields: dict[str, Any],
    rejected: list[dict[str, Any]],
) -> None:
    """``route``: a list of route values, or the single value ``any``; a route list needs its
    fragment in the line. A bare string is read as a one-entry list."""
    raw = payload.get(FIELD_ROUTE)
    if raw is None:
        return
    entries = [raw] if isinstance(raw, str) else raw
    if not isinstance(entries, list) or not entries:
        rejected.append(_rejection(FIELD_ROUTE, raw, "not a non-empty list"))
        return
    tokens = list(dict.fromkeys(_enum_value(entry) for entry in entries))
    span = payload.get(FIELD_ROUTE_SPAN)
    if tokens == [ROUTE_ANY]:
        fields[FIELD_ROUTE] = [ROUTE_ANY]
    elif any(token not in _ROUTE_VALUES for token in tokens):
        rejected.append(
            _rejection(
                FIELD_ROUTE, raw, f"not {ROUTE_ANY!r} alone nor a list of {sorted(_ROUTE_VALUES)}"
            )
        )
    elif not span_in_line(span, protocol_line):
        rejected.append(
            _rejection(
                FIELD_ROUTE,
                {FIELD_ROUTE: raw, FIELD_ROUTE_SPAN: span},
                f"{FIELD_ROUTE_SPAN} is not a substring of protocolLine",
            )
        )
    else:
        fields[FIELD_ROUTE] = tokens
        fields[FIELD_ROUTE_SPAN] = span


def _enum_member(raw: Any, values: frozenset[str]) -> str | None:
    """``raw`` folded by :func:`_enum_value` when it is one of ``values``, else None."""
    value = _enum_value(raw)
    return value if value in values else None


def _validate_threshold(
    payload: Mapping[str, Any], protocol_line: str, rejected: list[dict[str, Any]]
) -> dict[str, Any]:
    """The three threshold fields, all set or all None (RFC-016 step 3).

    They are one statement: a kind or a bound says nothing without the fragment it
    describes, and a fragment whose kind is unknown cannot decide whether a value filter
    belongs on the criterion. So the span must be a substring of the line AND both enums
    must hold a value of their own list, or none of the three is kept and the reason is
    appended to ``rejected``.
    """
    fields: dict[str, Any] = {
        FIELD_THRESHOLD_SPAN: None,
        FIELD_QUANTITY_KIND: None,
        FIELD_REFERENCE_BOUND: None,
    }
    span = payload.get(FIELD_THRESHOLD_SPAN)
    kind_raw = payload.get(FIELD_QUANTITY_KIND)
    bound_raw = payload.get(FIELD_REFERENCE_BOUND)
    answer = {
        FIELD_THRESHOLD_SPAN: span,
        FIELD_QUANTITY_KIND: kind_raw,
        FIELD_REFERENCE_BOUND: bound_raw,
    }
    if span is None or (isinstance(span, str) and not span.strip()):
        if kind_raw is not None or bound_raw is not None:
            rejected.append(
                _rejection(FIELD_QUANTITY_KIND, answer, f"given without a {FIELD_THRESHOLD_SPAN}")
            )
        return fields
    if not span_in_line(span, protocol_line):
        rejected.append(
            _rejection(FIELD_THRESHOLD_SPAN, answer, "not a substring of protocolLine")
        )
        return fields
    kind = _enum_member(kind_raw, _KIND_VALUES)
    if kind is None:
        rejected.append(
            _rejection(FIELD_QUANTITY_KIND, answer, f"not one of {sorted(_KIND_VALUES)}")
        )
        return fields
    bound = _enum_member(bound_raw, _BOUND_VALUES)
    if bound is None:
        rejected.append(
            _rejection(FIELD_REFERENCE_BOUND, answer, f"not one of {sorted(_BOUND_VALUES)}")
        )
        return fields
    fields[FIELD_THRESHOLD_SPAN] = span
    fields[FIELD_QUANTITY_KIND] = kind
    fields[FIELD_REFERENCE_BOUND] = bound
    return fields


# --------------------------------------------------------------------------- #
# Inputs and prompt
# --------------------------------------------------------------------------- #


def _text(value: Any) -> str:
    rendered = " ".join(str(value).split()) if value is not None else ""
    return rendered or "none"


def _window_text(window: Any) -> str:
    if not isinstance(window, Mapping):
        return "none"
    return f"start {window.get('start')} days, end {window.get('end')} days relative to index"


def _value_constraint_text(constraint: Any) -> str:
    if not isinstance(constraint, Mapping) or constraint.get("value") is None:
        return "none"
    parts = [str(constraint.get("op") or ""), str(constraint.get("value"))]
    if constraint.get("valueHigh") is not None:
        parts += ["to", str(constraint.get("valueHigh"))]
    if constraint.get("unitText"):
        parts.append(str(constraint.get("unitText")))
    return " ".join(part for part in parts if part)


def _members_text(members: Sequence[Mapping[str, Any]]) -> str:
    if not members:
        return "none"
    lines = [
        f"\n  - {_text(m.get('description'))} (entity text: {_text(m.get('sourceText'))}; "
        f"domain: {_text(m.get('domain'))})"
        for m in members
    ]
    return "".join(lines)


def context_lines(row: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """The trial's other protocol lines of the row's role, as the prompt shows them.

    Every ``protocolLine`` of ``rows`` (the row's role, in store order) once, by exact
    string; the row's own line and blank lines left out. Machine identity only: nothing
    here reads a line's words.

    :param row: the store criterion row being annotated.
    :param rows: every row of its role, the row itself included.
    :returns: the lines, verbatim.
    """
    seen = {row.get(_LINE) or ""}
    lines: list[str] = []
    for other in rows:
        line = other.get(_LINE)
        if not isinstance(line, str) or not line.strip() or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return lines


def _context_text(lines: Sequence[str]) -> str:
    return "\n".join(f"- {_text(line)}" for line in lines) or "none"


def render_prompt(
    row: Mapping[str, Any],
    members: Sequence[Mapping[str, Any]],
    role: str,
    context: Sequence[str] = (),
) -> str:
    """The user message for one rule: its protocol line, the other lines of its role, and
    its already-extracted fields.

    :param row: the store criterion row.
    :param members: the rows of its group when ``row`` is a group label, else empty.
    :param role: ``inclusion`` or ``exclusion``.
    :param context: the other lines of its role (:func:`context_lines`); ``none`` is
        shown when empty.
    :returns: the rendered prompt.
    """
    return ANNOTATION_PROMPT.format(
        protocol_line=str(row.get(_LINE) or ""),
        context_lines=_context_text(context),
        role=role,
        entity_text=_text(row.get("sourceText")),
        description=_text(row.get("description")),
        domain=_text(row.get("domain")),
        logic_type=_text(row.get("logicType")),
        window=_window_text(row.get("window")),
        value_constraint=_value_constraint_text(row.get("valueConstraint")),
        group_label="yes" if row.get(_IS_LABEL) else "no",
        members=_members_text(members),
        route_values=_quoted(route.value for route in AdministrationRoute),
    )


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #

_CACHE_PATH_ENV = "ARTEMIS_ANNOTATION_CACHE_PATH"
_CACHE_ENABLED_ENV = "ARTEMIS_ANNOTATION_CACHE"
_WORKERS_ENV = "ARTEMIS_ANNOTATION_WORKERS"
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_PATH = _REPO_ROOT / ".cache" / "criterion_annotation" / "annotations.jsonl"

_cache_lock = threading.Lock()
_memory: dict[str, dict[str, Any]] = {}
_loaded_from: str | None = None


def cache_path() -> Path:
    """:returns: the JSONL file backing the cache (``ARTEMIS_ANNOTATION_CACHE_PATH``)."""
    raw = os.environ.get(_CACHE_PATH_ENV, "").strip()
    return Path(raw) if raw else DEFAULT_CACHE_PATH


def cache_enabled() -> bool:
    """:returns: False only when ``ARTEMIS_ANNOTATION_CACHE`` is set to 0."""
    return os.environ.get(_CACHE_ENABLED_ENV) != "0"


def cache_key(prompt: str, model: str) -> str:
    """:param prompt: the rendered user prompt (protocol line + extracted fields).
    :param model: the resolved model string. :returns: a stable SHA-256 key."""
    payload = json.dumps(
        [ANNOTATION_PROMPT_VERSION, ANNOTATION_SYSTEM_PROMPT, prompt, model], ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_cache() -> dict[str, dict[str, Any]]:
    """Read the cache once per process; reload when the path env changes. Call under lock."""
    global _loaded_from
    path = cache_path()
    if _loaded_from == str(path):
        return _memory
    _memory.clear()
    _loaded_from = str(path)
    if not path.exists():
        return _memory
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                _memory[record["key"]] = record
            except (ValueError, KeyError, TypeError):
                logger.warning("[annotation] skipping damaged cache line %s:%d", path, number)
    return _memory


def _cache_get(key: str) -> dict[str, Any] | None:
    if not cache_enabled():
        return None
    with _cache_lock:
        return _load_cache().get(key)


def _cache_put(key: str, record: dict[str, Any]) -> None:
    if not cache_enabled():
        return
    with _cache_lock:
        _load_cache()[key] = record
        path = cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"key": key, **record}, ensure_ascii=False) + "\n")


def reset_for_tests() -> None:
    """Drop the in-process cache. Test helper, not production API."""
    global _loaded_from
    with _cache_lock:
        _loaded_from = None
        _memory.clear()


# --------------------------------------------------------------------------- #
# The call
# --------------------------------------------------------------------------- #


def _build_llm(model: str) -> Any:
    """:param model: the resolved model string. :returns: a chat model handle.

    Separate so a test substitutes a stub without reaching a network.
    """
    from src.utils.llm import get_llm

    return get_llm(model_name=model, temperature=0.0, json_mode=True)


def _parse(content: Any) -> Any:
    from src.utils.llm import _last_json_value, extract_answer

    cleaned, _strategy = extract_answer(str(content))
    try:
        return json.loads(cleaned)
    except ValueError:
        value = _last_json_value(cleaned)
        if value is None:
            raise
        return json.loads(value)


def _complete(llm: Any, prompt: str) -> Any:
    from langchain_core.messages import HumanMessage, SystemMessage

    from src.utils.llm import raise_if_truncated

    response = llm.invoke(
        [SystemMessage(content=ANNOTATION_SYSTEM_PROMPT), HumanMessage(content=prompt)]
    )
    raise_if_truncated(response, what="criterion annotation")
    return _parse(response.content)


def annotate_row(
    row: dict[str, Any],
    members: Sequence[Mapping[str, Any]],
    role: str,
    *,
    model: str,
    llm: Any,
    context: Sequence[str] = (),
) -> str:
    """Annotate one rule in place. Never raises for a model failure.

    :param row: the store criterion row; gains :data:`ANNOTATION_KEY` and, when a field
        was dropped, :data:`ANNOTATION_REJECTED_KEY`.
    :param members: the rows of its group when ``row`` is a group label, else empty.
    :param role: ``inclusion`` or ``exclusion``.
    :param model: the resolved model, recorded and part of the cache key.
    :param llm: the chat model handle (built once per run by the caller).
    :param context: the other lines of its role (:func:`context_lines`), shown in the
        prompt and the only lines besides its own that ``conditional_span`` may come from.
    :returns: ``no-line``, ``cached``, ``called`` or ``error``.
    """
    line = row.get(_LINE)
    if not isinstance(line, str) or not line.strip():
        # Nothing to check a fragment against, so nothing the model said could be kept.
        return "no-line"
    prompt = render_prompt(row, members, role, context)
    key = cache_key(prompt, model)
    cached = _cache_get(key)
    outcome = "cached"
    if cached is not None:
        payload = cached.get("payload")
    else:
        outcome = "called"
        try:
            payload = _complete(llm, prompt)
        except Exception as exc:
            row[ANNOTATION_KEY] = {
                "promptVersion": ANNOTATION_PROMPT_VERSION,
                "model": model,
                "error": f"{type(exc).__name__}: {exc}",
            }
            row.pop(ANNOTATION_REJECTED_KEY, None)
            return "error"
        _cache_put(
            key, {"payload": payload, "model": model, "promptVersion": ANNOTATION_PROMPT_VERSION}
        )
    fields, rejected = validate_annotation(payload, line, context)
    row[ANNOTATION_KEY] = {"promptVersion": ANNOTATION_PROMPT_VERSION, "model": model, **fields}
    if rejected:
        row[ANNOTATION_REJECTED_KEY] = rejected
    else:
        row.pop(ANNOTATION_REJECTED_KEY, None)
    disagreement = window_disagreement(fields, row.get("window"))
    if disagreement is not None:
        row[WINDOW_DISAGREEMENT_KEY] = disagreement
    else:
        row.pop(WINDOW_DISAGREEMENT_KEY, None)
    return outcome


def window_disagreement(fields: Mapping[str, Any], window: Any) -> dict[str, Any] | None:
    """A verified ``window_span`` whose own duration is neither bound of the extracted window.

    Two numbers compared, nothing read for meaning: the duration comes from the number and
    time unit inside a fragment the span check already verified
    (:func:`src.agents.agent1.temporal_grounding.stated_durations`), and the window is
    Agent 1's. Only ``prior`` / ``at_index`` rows are compared -- a ``prospective`` row is
    not emitted at all. A report only: nothing rewrites the window from it. Measured on the
    2026-10-12 P2 re-extraction, ARISTOTLE's CHF member reads "within 3 months" and was
    extracted as ``-3..0``; a verified span alone does not show that.

    :param fields: the validated annotation fields.
    :param window: the row's ``window`` (``{start, end}`` in days, or None).
    :returns: ``{windowSpan, statedDays, window}`` when no stated duration matches either
        bound (within a unit's calendar band), else None -- also when the span states no
        duration or the row has no window.
    """
    if fields.get(FIELD_TIMING) not in (Timing.PRIOR.value, Timing.AT_INDEX.value):
        return None
    span = fields.get(FIELD_WINDOW_SPAN)
    if not span or not isinstance(window, Mapping):
        return None
    from src.agents.agent1.temporal_grounding import stated_durations

    durations = stated_durations(span)
    bounds = {abs(v) for v in (window.get("start"), window.get("end")) if isinstance(v, int)}
    if not durations or not bounds:
        return None
    if any(low <= bound <= high for low, high in durations for bound in bounds):
        return None
    return {
        "windowSpan": span,
        "statedDays": [low for low, _high in durations],
        "window": {"start": window.get("start"), "end": window.get("end")},
    }


def _members_of(
    label: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    group = label.get(_GROUP)
    if not label.get(_IS_LABEL) or not group:
        return []
    return [r for r in rows if r is not label and r.get(_GROUP) == group and not r.get(_IS_LABEL)]


def _workers() -> int:
    raw = os.environ.get(_WORKERS_ENV, "").strip()
    return max(1, int(raw)) if raw else 4


def annotate_eligibility(
    eligibility: Mapping[str, Any], *, model: str | None = None
) -> dict[str, int]:
    """Annotate every inclusion and exclusion row of an eligibility block, in place.

    :param eligibility: carries ``inclusionCriteria`` and ``exclusionCriteria`` rows.
    :param model: model override; defaults to the pipeline's resolved model.
    :returns: outcome counts, plus ``rejected`` (rows that lost at least one field).
    """
    from src.utils.llm import resolve_model

    resolved = resolve_model(model)
    jobs: list[tuple[dict[str, Any], list[Mapping[str, Any]], str, list[str]]] = []
    for role, key in _ROLE_ROWS:
        rows = [r for r in eligibility.get(key) or [] if isinstance(r, dict)]
        jobs += [(row, _members_of(row, rows), role, context_lines(row, rows)) for row in rows]
    counts: dict[str, int] = {}
    if not jobs:
        return counts
    needs_model = any(
        isinstance(r.get(_LINE), str) and r.get(_LINE).strip() for r, *_rest in jobs
    )
    llm = _build_llm(resolved) if needs_model else None
    with ThreadPoolExecutor(max_workers=_workers()) as pool:
        outcomes = list(
            pool.map(
                lambda job: annotate_row(
                    job[0], job[1], job[2], model=resolved, llm=llm, context=job[3]
                ),
                jobs,
            )
        )
    for outcome in outcomes:
        counts[outcome] = counts.get(outcome, 0) + 1
    counts["rejected"] = sum(1 for row, *_rest in jobs if row.get(ANNOTATION_REJECTED_KEY))
    counts["windowDisagreement"] = sum(
        1 for row, *_rest in jobs if row.get(WINDOW_DISAGREEMENT_KEY)
    )
    logger.info("[annotation] model=%s version=%s %s", resolved, ANNOTATION_PROMPT_VERSION, counts)
    return counts


# --------------------------------------------------------------------------- #
# Readers
# --------------------------------------------------------------------------- #


def _annotation(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get(ANNOTATION_KEY)
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class ConditionalSkip:
    """Why a row is recorded as a conditional skip.

    :param span: the fragment of the deciding row's line (or of ``span_line``), None when
        only Agent 1's ``conditional`` flag decided (the gate then refuses the permit).
    :param decided_by: the id of the row whose decision this is -- the row itself, or
        the group label it sits under.
    :param source: :data:`SOURCE_ANNOTATION` or :data:`SOURCE_EXTRACTION`.
    :param span_line: the other ``protocolLine`` of the role that holds ``span``
        (:data:`FIELD_CONDITIONAL_SPAN_LINE`); None when ``span`` is in the deciding row's
        own line.
    """

    span: str | None
    decided_by: str
    source: str
    span_line: str | None = None


def conditional_span_holds(
    span: Any, span_line: Any, own_line: Any, role_lines: frozenset[str]
) -> bool:
    """Whether a conditional span is in the line it is recorded against.

    With no recorded line, that is the row's own line. With one, the line must itself be a
    ``protocolLine`` of the same role (exact string) and hold the span: the prompt showed
    the model only that role's lines, so a span from anywhere else supports nothing.

    :param span: the accepted ``conditional_span``.
    :param span_line: its :data:`FIELD_CONDITIONAL_SPAN_LINE`.
    :param own_line: the deciding row's ``protocolLine``.
    :param role_lines: every ``protocolLine`` of the deciding row's role.
    :returns: True when the span verifies.
    """
    if span_line is None:
        return span_in_line(span, own_line)
    return isinstance(span_line, str) and span_line in role_lines and span_in_line(span, span_line)


def _own_conditional(
    row: Mapping[str, Any], role_lines: frozenset[str]
) -> ConditionalSkip | None:
    annotation = _annotation(row)
    span = annotation.get(FIELD_CONDITIONAL_SPAN)
    span_line = annotation.get(FIELD_CONDITIONAL_SPAN_LINE)
    if annotation.get(
        FIELD_RECORD_REQUIREMENT
    ) == RecordRequirement.CONDITIONAL.value and conditional_span_holds(
        span, span_line, row.get(_LINE), role_lines
    ):
        return ConditionalSkip(
            span=span,
            decided_by=str(row.get(_ID, "")),
            source=SOURCE_ANNOTATION,
            span_line=span_line,
        )
    if row.get(EXTRACTED_CONDITIONAL_KEY) is True:
        return ConditionalSkip(
            span=None, decided_by=str(row.get(_ID, "")), source=SOURCE_EXTRACTION
        )
    return None


def group_descendants(rows: Iterable[Mapping[str, Any]], group_id: str) -> set[str]:
    """``group_id`` and every group nested inside it, through ``parentGroupId``."""
    rows = list(rows)
    groups = {group_id}
    grew = True
    while grew:
        grew = False
        for row in rows:
            child = row.get(_GROUP)
            if child and row.get(_PARENT_GROUP) in groups and child not in groups:
                groups.add(child)
                grew = True
    return groups


def _with_group_members(rows: list[Mapping[str, Any]], own: dict[str, Any]) -> dict[str, Any]:
    """``own`` decisions, plus each decided group label's decision for every row under it."""
    decided = dict(own)
    for label in rows:
        decision = own.get(str(label.get(_ID, "")))
        if decision is None or not label.get(_IS_LABEL) or not label.get(_GROUP):
            continue
        groups = group_descendants(rows, str(label.get(_GROUP)))
        for row in rows:
            if row is not label and row.get(_GROUP) in groups:
                decided.setdefault(str(row.get(_ID, "")), decision)
    return decided


def conditional_skips(rows: Iterable[Any]) -> dict[str, ConditionalSkip]:
    """The rows of one role that are not emitted because they are conditional.

    A row is conditional when its own accepted annotation says so (with a fragment that
    is in its line, or in the other line of this role it records:
    :func:`conditional_span_holds`) or when Agent 1 flagged it. A conditional group label
    takes every row of its group, nested groups included, with it: the members are the
    presence rule the label describes, and emitting them alone would emit what the label's
    decision removes.

    :param rows: one role's store rows.
    :returns: criterion id (stringified) -> the decision.
    """
    rows = [r for r in rows if isinstance(r, Mapping)]
    role_lines = frozenset(line for r in rows if isinstance(line := r.get(_LINE), str))
    own = {
        str(r.get(_ID, "")): skip
        for r in rows
        if (skip := _own_conditional(r, role_lines)) is not None
    }
    return _with_group_members(rows, own)


@dataclass(frozen=True)
class ProspectiveSkip:
    """Why a row is recorded as not observable at index.

    :param span: the ``window_span`` of the deciding row, a substring of its line.
    :param decided_by: the id of the deciding row -- the row itself, or its group label.
    """

    span: str
    decided_by: str


def _own_prospective(row: Mapping[str, Any]) -> ProspectiveSkip | None:
    annotation = _annotation(row)
    span = annotation.get(FIELD_WINDOW_SPAN)
    if annotation.get(FIELD_TIMING) == Timing.PROSPECTIVE.value and span_in_line(
        span, row.get(_LINE)
    ):
        return ProspectiveSkip(span=span, decided_by=str(row.get(_ID, "")))
    return None


def prospective_skips(rows: Iterable[Any]) -> dict[str, ProspectiveSkip]:
    """The rows of one role that are not emitted because the line places them after entry.

    Decided by the row's own accepted annotation only (``timing: prospective`` with a
    ``window_span`` in its line, re-checked here). A prospective group label takes every
    row of its group with it, as :func:`conditional_skips` does.

    :param rows: one role's store rows.
    :returns: criterion id (stringified) -> the decision.
    """
    rows = [r for r in rows if isinstance(r, Mapping)]
    own = {str(r.get(_ID, "")): skip for r in rows if (skip := _own_prospective(r)) is not None}
    return _with_group_members(rows, own)


@dataclass(frozen=True)
class StatedRelation:
    """A group's relation, verified against its label's line.

    :param relation: ``all``, ``any`` or ``at_least``.
    :param span: the fragment of the line stating it.
    :param cardinality: the stated number for ``at_least``, else None.
    :param source: :data:`SOURCE_PLANNER` or :data:`SOURCE_ANNOTATION`.
    """

    relation: str
    span: str
    cardinality: int | None
    source: str


def stated_relation(row: Mapping[str, Any]) -> StatedRelation | None:
    """How the row's line combines its group's members, when a verified answer exists.

    The planner's (:data:`PLANNER_RELATION_KEY`) first; the annotation's only when the
    planner's is absent or does not verify. Both are re-checked against the row's own line
    here, so a hand-edited or stale row cannot carry an unchecked relation into a build.

    :param row: the store row of a group label.
    :returns: the verified relation, or None.
    """
    line = row.get(_LINE)
    for source, payload in (
        (SOURCE_PLANNER, row.get(PLANNER_RELATION_KEY)),
        (SOURCE_ANNOTATION, _annotation(row)),
    ):
        fields, _ = check_relation(payload, line)
        if fields[FIELD_RELATION] is not None:
            return StatedRelation(
                relation=fields[FIELD_RELATION],
                span=fields[FIELD_RELATION_SPAN],
                cardinality=fields[FIELD_CARDINALITY],
                source=source,
            )
    return None


#: CIRCE group types. Machine format (the CIRCE ``CriteriaGroup.Type`` enum).
GROUP_ALL = "ALL"
GROUP_ANY = "ANY"
GROUP_AT_LEAST = "AT_LEAST"
LOGIC_ABSENCE = "ABSENCE"


def relation_group_type(
    logic: str | None, relation: str, cardinality: int | None, members: int
) -> tuple[str, int | None] | None:
    """CIRCE ``(Type, Count)`` for a group from its stated relation and its logic.

    RFC-014 §2-1. The relation is how the line combines the members as conditions; an
    ``ABSENCE`` group emits each member as "no occurrence", so the relation is negated by
    De Morgan: ``any`` -> ALL (absent from every member), ``all`` -> ANY (absent from at
    least one), and ``at_least N`` of ``k`` -> AT_LEAST ``k - N + 1`` absences.

    :param logic: the group's logic type (``ABSENCE`` negates; anything else does not).
    :param relation: ``all``, ``any`` or ``at_least``.
    :param cardinality: N for ``at_least``.
    :param members: how many members the group actually emits.
    :returns: ``(Type, Count)`` with Count only for AT_LEAST; None when the relation cannot
        apply (no members, or N outside ``1..members``) -- the caller keeps its declared type.
    """
    if members < 1:
        return None
    if relation == Relation.AT_LEAST.value:
        if cardinality is None or not 1 <= cardinality <= members:
            return None
        need = members - cardinality + 1 if logic == LOGIC_ABSENCE else cardinality
        if need == 1:
            return GROUP_ANY, None
        if need == members:
            return GROUP_ALL, None
        return GROUP_AT_LEAST, need
    every = relation == Relation.ALL.value
    if logic == LOGIC_ABSENCE:
        every = not every
    return (GROUP_ALL if every else GROUP_ANY), None


def declared_group_type(logic: str | None, relation: str, cardinality: int | None) -> str:
    """The IR ``group_type`` (ALL or ANY) a split records for a relation.

    The builder derives the emitted type from the stored relation; this is the value the IR
    and the store row carry, and what the builder falls back to when the relation cannot
    apply (an ``at_least`` asking for more members than mapped). An ``at_least`` of more
    than one records the strict reading.

    :param logic: the criterion's logic type.
    :param relation: ``all``, ``any`` or ``at_least``.
    :param cardinality: N for ``at_least``.
    :returns: ``ALL`` or ``ANY``.
    """
    every = relation == Relation.ALL.value or (
        relation == Relation.AT_LEAST.value and (cardinality or 0) > 1
    )
    if logic == LOGIC_ABSENCE:
        every = not every
    return GROUP_ALL if every else GROUP_ANY


def stated_exceptions(row: Mapping[str, Any]) -> list[dict[str, str]]:
    """The excepted entities to subtract from this row's concept set, verified.

    The planner's (:data:`PLANNER_EXCEPTED_KEY`) first; the annotation's only when the
    planner left none. Each span is checked against the row's own line again here, so a
    hand-edited or stale row cannot carry an unchecked exception into a concept set.

    :param row: the store criterion row.
    :returns: ``[{text, span}]``, empty when nothing verified.
    """
    line = row.get(_LINE)
    for source in (row.get(PLANNER_EXCEPTED_KEY), _annotation(row).get(FIELD_EXCEPTED_ENTITIES)):
        verified = [
            {FIELD_TEXT: str(entry.get(FIELD_TEXT)).strip(), FIELD_SPAN: entry.get(FIELD_SPAN)}
            for entry in source or []
            if isinstance(entry, Mapping)
            and isinstance(entry.get(FIELD_TEXT), str)
            and entry.get(FIELD_TEXT).strip()
            and span_in_line(entry.get(FIELD_SPAN), line)
        ]
        if verified:
            return verified
    return []


def stated_base(row: Mapping[str, Any]) -> str | None:
    """The fragment naming the set an exception is taken from, when it should seed the mapper.

    Only alongside an exception that is itself verified, and only with its span checked
    against the row's line again. None leaves the seed as it is.

    :param row: the store criterion row.
    :returns: the base fragment, whitespace-collapsed, or None.
    """
    base = _annotation(row).get(FIELD_BASE_SPAN)
    if not stated_exceptions(row) or not span_in_line(base, row.get(_LINE)):
        return None
    return " ".join(base.split())


def stated_exceptions_by_codeset(eligibility: Mapping[str, Any]) -> dict[int, list[str]]:
    """Concept set id -> the excepted entity names its criterion states.

    What the export-time entry-exclusion repair reads instead of a rule's name: a rule's
    absence over that concept set implements a criterion whose protocol line excepted
    these entities.

    :param eligibility: the stored eligibility block, rows carrying ``conceptSetId``.
    :returns: one entry per concept set whose criterion states an exception.
    """
    found: dict[int, list[str]] = {}
    for _role, key in _ROLE_ROWS:
        for row in eligibility.get(key) or []:
            if not isinstance(row, Mapping):
                continue
            codeset = row.get("conceptSetId")
            excepted = stated_exceptions(row)
            if codeset is None or not excepted:
                continue
            try:
                codeset_id = int(codeset)
            except (TypeError, ValueError):
                continue
            names = found.setdefault(codeset_id, [])
            names += [e[FIELD_TEXT] for e in excepted if e[FIELD_TEXT] not in names]
    return found


@dataclass(frozen=True)
class RouteStatement:
    """The routes a row's protocol line restricts its drug to, and the fragment saying so."""

    routes: tuple[AdministrationRoute, ...]
    span: str


@dataclass(frozen=True)
class SpecimenStatement:
    """The body material a row's line names for its measured quantity (``span`` None for any)."""

    specimen: Specimen
    span: str | None


@dataclass(frozen=True)
class NoEntityStatement:
    """A row whose line names no clinical entity, and the fragment that shows it."""

    kind: NoEntity
    span: str


def stated_route(row: Mapping[str, Any]) -> RouteStatement | None:
    """The route restriction to apply to this row's drug concept set, verified.

    The span is checked against the row's own line again here, so a stale or hand-edited
    row cannot carry an unchecked route into a concept set.

    :param row: the store criterion row.
    :returns: the routes and span, or None when the row states no route (``any``, absent,
        rejected, or a span no longer in the line).
    """
    annotation = _annotation(row)
    tokens = annotation.get(FIELD_ROUTE)
    span = annotation.get(FIELD_ROUTE_SPAN)
    if not isinstance(tokens, list) or not tokens or not span_in_line(span, row.get(_LINE)):
        return None
    if any(token not in _ROUTE_VALUES for token in tokens):
        return None
    return RouteStatement(routes=tuple(AdministrationRoute(t) for t in tokens), span=span)


def stated_specimen(row: Mapping[str, Any]) -> SpecimenStatement | None:
    """The specimen the row's line names, verified; ``any`` comes back with no span.

    :param row: the store criterion row.
    :returns: the statement, or None when the annotation carries no accepted specimen.
    """
    annotation = _annotation(row)
    value = annotation.get(FIELD_SPECIMEN)
    if value not in _SPECIMEN_VALUES:
        return None
    if value == Specimen.ANY.value:
        return SpecimenStatement(specimen=Specimen.ANY, span=None)
    span = annotation.get(FIELD_SPECIMEN_SPAN)
    if not span_in_line(span, row.get(_LINE)):
        return None
    return SpecimenStatement(specimen=Specimen(value), span=span)


def stated_no_entity(row: Mapping[str, Any]) -> NoEntityStatement | None:
    """Whether the row's line names no clinical entity, verified against the line.

    :param row: the store criterion row.
    :returns: the kind and span, or None when the line names an entity or nothing verified.
    """
    annotation = _annotation(row)
    value = annotation.get(FIELD_NO_ENTITY)
    span = annotation.get(FIELD_NO_ENTITY_SPAN)
    if value not in _NO_ENTITY_VALUES or value == NoEntity.NONE.value:
        return None
    if not span_in_line(span, row.get(_LINE)):
        return None
    return NoEntityStatement(kind=NoEntity(value), span=span)


# --------------------------------------------------------------------------- #
# The stated threshold (RFC-016 step 3)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StatedThreshold:
    """A threshold the row's own protocol line states, verified against that line.

    :param span: the fragment of ``protocolLine`` stating it.
    :param kind: what its number measures.
    :param bound: what the number is compared against, in the store's ``referenceBound``
        spelling: ``absolute``, ``uln`` or ``lln``.
    """

    span: str
    kind: QuantityKind
    bound: str


def stated_threshold(row: Mapping[str, Any]) -> StatedThreshold | None:
    """The threshold the row's accepted annotation states, its span re-checked here.

    Checked against the row's line again, as :func:`stated_exceptions` does, so a row
    edited after it was annotated cannot carry an unchecked threshold into the build or
    the delivery gate.

    :param row: the store criterion row.
    :returns: the verified threshold, or None when the annotation states none, was
        rejected, or no longer matches the row's line.
    """
    annotation = _annotation(row)
    span = annotation.get(FIELD_THRESHOLD_SPAN)
    kind = _enum_member(annotation.get(FIELD_QUANTITY_KIND), _KIND_VALUES)
    bound = _enum_member(annotation.get(FIELD_REFERENCE_BOUND), _BOUND_VALUES)
    if kind is None or bound is None or not span_in_line(span, row.get(_LINE)):
        return None
    store_bound = "absolute" if bound == StatedReferenceBound.NONE.value else bound
    return StatedThreshold(span=span, kind=QuantityKind(kind), bound=store_bound)


class ThresholdUse(str, Enum):
    """How the build uses a row's threshold, decided by its verified annotation.

    * ``default`` -- no verified threshold (no annotation, a rejected one, or a line that
      states none): the row's own ``valueConstraint`` is used exactly as before.
    * ``measured`` -- a verified lab value, or an ``other`` quantity on a Measurement row
      (the case the build already supports): applied as a value filter, compared against
      the annotation's ``reference_bound``.
    * ``not-representable`` -- a verified duration, count, or an ``other`` quantity outside
      Measurement: no value filter is emitted for it, the criterion is kept, and the
      threshold is recorded under :data:`UNREPRESENTABLE_THRESHOLDS_KEY` (the delivery gate
      WARNs on it).
    * ``skip-criterion`` -- a verified dose or statistical quantity: the WHOLE criterion is
      skipped and recorded under :data:`THRESHOLD_NOT_REPRESENTABLE_REASON`, which the
      delivery gate counts as criterion loss. A drug emitted without its dose, or a row
      carrying a quantity of the trial's design, says something the protocol did not.

    Decided on the enum alone (coordinator, 2026-10-12); no text is read.
    """

    DEFAULT = "default"
    MEASURED = "measured"
    NOT_REPRESENTABLE = "not-representable"
    SKIP_CRITERION = "skip-criterion"


#: The kinds whose criterion is skipped whole rather than kept without its threshold.
_SKIP_KINDS = frozenset({QuantityKind.DOSE, QuantityKind.STATISTICAL})


def threshold_use(row: Mapping[str, Any]) -> tuple[ThresholdUse, StatedThreshold | None]:
    """Decide how the build uses this row's threshold, from its verified annotation only.

    :param row: the store criterion row.
    :returns: the decision and the verified threshold it rests on (None for ``default``).
    """
    stated = stated_threshold(row)
    if stated is None:
        return ThresholdUse.DEFAULT, None
    if stated.kind is QuantityKind.LAB_VALUE or (
        stated.kind is QuantityKind.OTHER and row.get("domain") == MEASUREMENT_DOMAIN
    ):
        return ThresholdUse.MEASURED, stated
    if stated.kind in _SKIP_KINDS:
        return ThresholdUse.SKIP_CRITERION, stated
    return ThresholdUse.NOT_REPRESENTABLE, stated


def applied_value_constraint(row: Mapping[str, Any]) -> Any:
    """The value constraint the build applies for this row (RFC-016 step 3).

    The one place every reader asks -- the member build, the group label's hand-down and
    the delivery gate's re-derivation -- so none of them can read ``valueConstraint``
    differently from another.

    :param row: the store criterion row.
    :returns: None for a threshold no CIRCE value filter represents (a skipped
        criterion included, so its group label hands nothing down); the row's own
        constraint with ``referenceBound`` taken from the annotation for a measured one;
        the row's own constraint unchanged otherwise.
    """
    constraint = row.get("valueConstraint")
    use, stated = threshold_use(row)
    if use in (ThresholdUse.NOT_REPRESENTABLE, ThresholdUse.SKIP_CRITERION):
        return None
    if use is ThresholdUse.MEASURED and isinstance(constraint, Mapping):
        return {**constraint, "referenceBound": stated.bound}
    return constraint


def unrepresentable_threshold_records(
    rows: Iterable[Any], role: str
) -> list[dict[str, Any]]:
    """One record per row whose verified threshold no CIRCE value filter represents.

    Written into the expression under :data:`UNREPRESENTABLE_THRESHOLDS_KEY` whether or not
    the row emitted, so a reader sees every threshold the protocol states that the file does
    not carry. The delivery gate permits an emitted criterion without a value filter only
    when it finds the record AND re-derives the decision from the store row.

    :param rows: one role's store rows.
    :param role: ``inclusion`` or ``exclusion``.
    :returns: the records, in row order.
    """
    records = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        use, stated = threshold_use(row)
        if use is not ThresholdUse.NOT_REPRESENTABLE:
            continue
        records.append(
            {
                "criterionId": str(row.get(_ID, "")),
                "role": role,
                "label": (row.get("sourceText") or row.get("description") or "").strip(),
                "isGroupLabel": bool(row.get(_IS_LABEL)),
                "reason": THRESHOLD_NOT_REPRESENTABLE_REASON,
                "quantityKind": stated.kind.value,
                "thresholdSpan": stated.span,
                "valueConstraint": row.get("valueConstraint"),
            }
        )
    return records



@dataclass(frozen=True)
class ThresholdSkip:
    """Why a row is skipped whole for a dose or statistical threshold.

    :param span: the verified fragment of the deciding row's line.
    :param kind: its ``quantity_kind``.
    :param decided_by: the id of the row that states it -- the row itself, or the group
        label it sits under.
    """

    span: str
    kind: QuantityKind
    decided_by: str


def threshold_skips(rows: Iterable[Any]) -> dict[str, ThresholdSkip]:
    """The rows of one role that are skipped whole because their threshold is a dose or
    a statistical quantity (:attr:`ThresholdUse.SKIP_CRITERION`).

    A group label whose own line states such a threshold takes every row of its group,
    nested groups included, with it -- the members are what the label describes, as
    :func:`conditional_skips` does for a conditional label.

    :param rows: one role's store rows.
    :returns: criterion id (stringified) -> the decision.
    """
    rows = [r for r in rows if isinstance(r, Mapping)]
    own: dict[str, ThresholdSkip] = {}
    for row in rows:
        use, stated = threshold_use(row)
        if use is ThresholdUse.SKIP_CRITERION:
            row_id = str(row.get(_ID, ""))
            own[row_id] = ThresholdSkip(span=stated.span, kind=stated.kind, decided_by=row_id)
    decided = dict(own)
    for label in rows:
        decision = own.get(str(label.get(_ID, "")))
        if decision is None or not label.get(_IS_LABEL) or not label.get(_GROUP):
            continue
        groups = group_descendants(rows, str(label.get(_GROUP)))
        for row in rows:
            if row is not label and row.get(_GROUP) in groups:
                decided.setdefault(str(row.get(_ID, "")), decision)
    return decided
