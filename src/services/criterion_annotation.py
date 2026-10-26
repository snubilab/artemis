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

``record_change`` (+ ``record_change_span``) -- whether the line requires the records of the
criterion's entity to stay the same (``stable``) or to change (``changed``) across a period it
states, or neither (``none``). It replaces the deleted ``dose_stability.py`` word rule. CIRCE can
test that a record exists in a window, not that it stayed the same or changed across one, so a
criterion with either value is not emitted; it is recorded as a skip under
:data:`RECORD_CHANGE_REASON` (:func:`record_change_skips`). It is asked in calls of its own
(calls 3 and 4 below), never in the first two: put into them, the block shifted
``record_requirement`` toward ``conditional`` in both wordings at once (over-fill re-check
``cfpf_20261015_075611``: 4/113 correct exceptions and 4/138 rr controls broken). Measured on
calls 3 and 4 there: ``stable`` on 9/9 go/no-go rows, 25/26 stability targets right, 0/32
controls filled.

The model decides the meaning and quotes the fragment of ``protocolLine`` that supports
it. Code checks one thing only: that each quoted fragment is a substring of the line
(:func:`span_in_line`, from :mod:`src.utils.span_match`: the comparison form every span
check in the pipeline shares, segmentation and the planner included; the planner and the
delivery gate import it from this module). A fragment that
is not in the line makes its field absent -- the row then takes the default behaviour --
and the rejection is recorded on the row under :data:`ANNOTATION_REJECTED_KEY` so it can
be counted. Nothing here reads the line, the description or the entity as words.

Agreement. Three fields are kept only when a second call, asked the same question in other
words (:data:`AGREEMENT_SYSTEM_PROMPT`, :data:`AGREEMENT_PROMPT`), gives them too: each
excepted entity (and with it ``base_span``), ``record_requirement: conditional``, and a
``no_entity`` other than ``none``. Measured with gemma-4-E4B in stage 2 of the over-fill A/B
(``output/site_gap/2026-10-12_p3_dry/overfill/analysis_stage2/``): a wrong excepted entity
changes under almost any rewording while a correct one recurs -- under the second wording 27
of 27 correct spans reappear and 37 of 126 wrong ones do -- so keeping only what both answers
give fixed 44.7 of 62 wrong-exception rows and broke 0 of 113 controls. The second call is
made only when the first validated answer fills one of the three, because the rule only ever
reverts a fill (:func:`agree`). What the second answer confirmed and what it took away are
recorded on the row under :data:`AGREEMENT_KEY`, carried onto the conditional skip record,
and listed in the built expression under :data:`AGREEMENT_RECORDS_KEY`. Every comparison is
of offsets in ``protocolLine`` (:func:`~src.utils.span_match.span_offsets`) or of enum
values; nothing reads either answer's words.

Calls 3 and 4 (record_change). Call 3 (:data:`RECORD_CHANGE_PROMPT`: the first prompt with the
record_change block, the A/B's `cf` arm) is made for every row with a line, and only its
``record_change`` / ``record_change_span`` are read. When it fills ``stable`` or ``changed``,
call 4 (:data:`RECORD_CHANGE_AGREEMENT_PROMPT`: the agreement prompt with the block, `pf`) is
made, and the fill is kept only when call 4 also fills one (:func:`agree_record_change`, the
``no_entity`` rule shape). Recorded under :data:`RECORD_CHANGE_KEY` on every row, listed in the
expression under :data:`RECORD_CHANGE_RECORDS_KEY`, each call cached under its own version.

Calls 5 and 6 (conditional check). Calls 1 and 2 ask one definition in two wordings, so a
reading the definition itself admits survives agreement: P6 SEG-OFF (2026-10-17) skipped CAROLINA
exclusion 16 'Acute or chronic metabolic acidosis (present condition in patient history)' and
exclusion 8 'Current treatment with systemic corticosteroids at time of informed consent', both
answers agreeing on a fragment that names no subgroup -- for an exclusion, "patients who have the
record of the entity" are simply the patients it excludes. When the agreed answer is
``conditional``, call 5 (:data:`CONDITIONAL_CHECK_PROMPT`) asks what its ``conditional_span`` does:
names a kind of patient, says only that the patient has the criterion's own entity, or states only
a time or the record holding it. Call 6 (:data:`CONDITIONAL_CHECK_AGREEMENT_PROMPT`, the same
definitions reworded) is asked when call 5's answer reverts, and the ``conditional`` is reverted
only when both do (:func:`check_conditional`, :func:`_reverting_roles`). Measured on 24 P6/A2 rows
(6 targets, 18 must-keep conditionals incl. PLATO's WOCBP labels, ARISTOTLE inclusion 4 and the
LEADER anti-diabetic labels): 6/6 reverted, 0/18 broken. A single wording was not stable --
ARISTOTLE inclusion 4 'If not in atrial fibrillation/flutter at the time of enrollment' flipped
with an unrelated change to the prompt -- which is why a revert needs both. Recorded on the row
under :data:`CONDITIONAL_CHECK_KEY`; it never fills anything and touches no other field.

Calls 7 and 8 (trial-only check, fix-k12). An agreed ``forbidden`` or ``required`` row with
``no_entity: none`` that is not a label with members is asked ``trial_only``
(:data:`TRIAL_ONLY_PROMPT`): does its own entity exist only because the patient takes part in a
clinical trial, any trial. Call 8 (:data:`TRIAL_ONLY_AGREEMENT_PROMPT`) confirms a ``yes``; both
``yes`` refuses the row before mapping as ``unmappable-placeholder`` (:func:`stated_trial_only`),
recorded under :data:`TRIAL_ONLY_CHECK_KEY`. Calls 5/6 were not reused: their
``entity_outside_trial`` is about this trial, and another trial's product (P8 CAROLINA K1,
ARISTOTLE K2) answered ``yes`` to it.

Separate from Agent 1 on purpose (RFC-016 §2): the annotation can be re-run on an
existing store without re-extraction, so it runs inside ``process_eligibility`` and a dry
rebuild reaches it.

Cache: one JSONL file, keyed on the prompt text, the prompt version, the resolved model
and the rendered inputs (protocol line plus the extracted fields). The agreement call is
cached under its own key (its own system prompt, template and version). The path is
``ARTEMIS_ANNOTATION_CACHE_PATH`` when set, so a run can isolate its cache;
``ARTEMIS_ANNOTATION_CACHE=0`` disables it. Failed calls are never cached.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from src.services.loinc_specimen import MEASUREMENT_DOMAIN
from src.services.route_subtraction import AdministrationRoute
from src.utils.span_match import span_in_line, span_offsets

logger = logging.getLogger(__name__)

#: Bumped whenever either prompt below changes meaning, or what is stored from the answer
#: does (the agreement step); part of the first call's cache key. The wording itself is the
#: one ``rfc016-steps1-4-v1`` sent, which stage 2 of the over-fill A/B measured as `current`.
#: The record_change calls (3 and 4) leave both prompts and the use of their answers as they
#: were, so neither version moves and an answer cached for them stays valid.
ANNOTATION_PROMPT_VERSION = "rfc016-occurrence-threshold-v1"
#: The agreement call's version (:data:`AGREEMENT_SYSTEM_PROMPT`, :data:`AGREEMENT_PROMPT`);
#: part of its cache key, bumped whenever either of those changes.
AGREEMENT_PROMPT_VERSION = "rfc016-occurrence-threshold-placebo-v1"
#: Call 3's version (:data:`RECORD_CHANGE_SYSTEM_PROMPT`, :data:`RECORD_CHANGE_PROMPT`: the
#: over-fill A/B's `cf` arm) and call 4's (the `pf` arm); each part of its call's cache key.
RECORD_CHANGE_PROMPT_VERSION = "rfc016-record-change-cf-v1"
RECORD_CHANGE_AGREEMENT_PROMPT_VERSION = "rfc016-record-change-pf-v1"
#: Calls 5 and 6 (:func:`check_conditional`); each part of its call's cache key.
CONDITIONAL_CHECK_PROMPT_VERSION = "rfc016-conditional-check-v1"
CONDITIONAL_CHECK_AGREEMENT_PROMPT_VERSION = "rfc016-conditional-check-placebo-v1"
#: Calls 7 and 8 (:func:`check_forbidden`); each part of its call's cache key.
#: gate-fix v3: the routine-records definition; named by field, apart from calls 9-12.
TRIAL_ONLY_PROMPT_VERSION = "gatefix-trial-only-routine-records-v1"
TRIAL_ONLY_AGREEMENT_PROMPT_VERSION = "gatefix-trial-only-routine-records-placebo-v1"
#: Calls 9 and 10 (:func:`_window_bound`); each part of its call's cache key.
WINDOW_BOUND_PROMPT_VERSION = "window-bound-v1"
WINDOW_BOUND_AGREEMENT_PROMPT_VERSION = "window-bound-placebo-v1"
#: Calls 11 and 12 (:func:`check_own_entity`); each part of its call's cache key.
OWN_ENTITY_PROMPT_VERSION = "p11-own-entity-v1"
OWN_ENTITY_AGREEMENT_PROMPT_VERSION = "p11-own-entity-placebo-v1"

#: The row key the annotation is stored under, and the key its rejections go to.
ANNOTATION_KEY = "annotation"
ANNOTATION_REJECTED_KEY = "_annotationRejected"
#: The row key of the agreement record (:func:`agree`): present exactly when the second call
#: was made, and holding what it kept and dropped, its answer, version and cache key.
AGREEMENT_KEY = "_annotationAgreement"
#: Expression key: one record per criterion the second call was made for
#: (:func:`agreement_records`), present and empty when there was none.
AGREEMENT_RECORDS_KEY = "_annotationAgreementRecords"
#: The row key of the record_change record (calls 3 and 4, :func:`annotate_row`): present on
#: every row call 3 was made for, with its version, cache key, outcome and validated answer,
#: and call 4's under ``second`` (None when call 3 filled nothing).
RECORD_CHANGE_KEY = "_recordChangeAgreement"
#: Expression key: one record per criterion call 4 was made for, or call 3 failed for
#: (:func:`record_change_records`), present and empty when there was none.
RECORD_CHANGE_RECORDS_KEY = "_recordChangeRecords"
#: The row key of the conditional check record (calls 5 and 6): present exactly when the agreed
#: answer was ``conditional``, with each call's version, cache key, outcome and answer, and
#: whether the ``conditional`` was reverted.
CONDITIONAL_CHECK_KEY = "_conditionalCheck"
#: The row key of the trial-only check (calls 7 and 8, asked of a ``forbidden`` row,
#: :func:`check_forbidden`): the fragment shown, each call's answer, and ``trialOnly`` -- True
#: only when both wordings answer that the entity exists only because of a clinical trial.
TRIAL_ONLY_CHECK_KEY = "_trialOnlyCheck"
#: The row key of the own-entity check (calls 11 and 12, :func:`check_own_entity`): asked of a row
#: whose agreed ``no_entity`` fragment lies wholly outside its own span. Holds the span shown, each
#: call's answer, and ``named`` -- True only when both wordings say that span names an entity.
OWN_ENTITY_CHECK_KEY = "_ownEntityCheck"
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
#: The record of calls 9 and 10 on a row (:func:`_window_bound`).
WINDOW_BOUND_KEY = "_windowBound"
#: The key `TTEService._build_seeded_target_circe` lists every criterion under whose emitted
#: window :func:`annotated_window` changed. Present and empty when none was.
ANNOTATED_WINDOW_CRITERIA_KEY = "_annotatedWindowCriteria"

FIELD_ROUTE = "route"
FIELD_ROUTE_SPAN = "route_span"
FIELD_SPECIMEN = "specimen"
FIELD_SPECIMEN_SPAN = "specimen_span"
FIELD_NO_ENTITY = "no_entity"
FIELD_OWN_ENTITY = "own_entity"
FIELD_TRIAL_ONLY = "trial_only"
FIELD_NO_ENTITY_SPAN = "no_entity_span"
FIELD_RECORD_CHANGE = "record_change"
FIELD_RECORD_CHANGE_SPAN = "record_change_span"
FIELD_WINDOW_BOUND = "window_bound"
#: The store row ``domain`` whose ``beyond`` :func:`annotated_window` does not apply.
DRUG_DOMAIN = "Drug"
FIELD_WINDOW_BOUND_SPAN = "window_bound_span"
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

#: Recorded on each criterion whose agreed annotation says its line requires the records of
#: its entity to stay the same, or to change, across a period (``record_change``); permitted
#: by the delivery gate only when the recorded span is a substring of the deciding row's
#: ``protocolLine``.
RECORD_CHANGE_REASON = "record-change-not-representable"
RECORD_CHANGE_EXPLANATION = (
    "The protocol line requires the patient's records of this criterion's entity to stay "
    "the same, or to change, across a period it states. CIRCE can test that a record "
    "exists in a window, not that it stayed the same or changed across one; emitted, the "
    "rule would require only that the record exists."
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


class RecordChange(str, Enum):
    """Whether the line requires the records of the entity to stay the same, or to change,
    across a period the line states (the over-fill A/B's ``fields_stability`` field)."""

    STABLE = "stable"
    CHANGED = "changed"
    NONE = "none"


class WindowBound(str, Enum):
    """Which side of a length of time counted back from entry the entity falls on."""

    WITHIN = "within"
    BEYOND = "beyond"
    NONE = "none"


_ROUTE_VALUES = frozenset(route.value for route in AdministrationRoute)
_WINDOW_BOUND_VALUES = frozenset(member.value for member in WindowBound)
_SPECIMEN_VALUES = frozenset(member.value for member in Specimen)
_NO_ENTITY_VALUES = frozenset(member.value for member in NoEntity)
_RECORD_CHANGE_VALUES = frozenset(member.value for member in RecordChange)
#: The values the build skips a criterion for; ``none`` (and absent) build as before.
_RECORD_CHANGE_FILLS = frozenset({RecordChange.STABLE.value, RecordChange.CHANGED.value})


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
protocol line is discarded together with the answer it supports.

Return one JSON object and nothing else."""

ANNOTATION_PROMPT = """Protocol line:
{protocol_line}

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

`conditional_span` is the fragment of the protocol line that limits the criterion to those \
patients. It is required when `record_requirement` is `conditional` and null otherwise.

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

# The agreement call's wording (see the module docstring): the two prompts above with the
# system prompt's second paragraph and the definitions of the three compared fields --
# `conditional` and `conditional_span`, `excepted_entities` and `base_span`, and `no_entity` --
# reworded with the same meaning and nothing added. It is the over-fill A/B's stage-2 `placebo`
# arm, character for character (scripts/check_annotation_agreement_identity.py); every other
# definition is identical to the first call's, so the second answer is asked the same question
# in other words.
AGREEMENT_SYSTEM_PROMPT = """You annotate one eligibility criterion of a clinical trial protocol.

The criterion was already extracted from one line of the protocol, and no extracted field is \
yours to change. You read that protocol line and record the facts that the fields below \
define about the criterion, each one with the fragment of the protocol line that states it.

Every fragment you return is copied from the protocol line character for character: no \
paraphrase, no expanded abbreviation, no added word. A fragment that does not occur in the \
protocol line is discarded together with the answer it supports.

Return one JSON object and nothing else."""

AGREEMENT_PROMPT = """Protocol line:
{protocol_line}

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
- `conditional`: the protocol line restricts the criterion to patients who already have a \
record of the entity, or to patients in a subgroup that the line names; this criterion does \
not filter a patient who lacks that record or is not in that subgroup.

`conditional_span` is the fragment of the protocol line that restricts the criterion to those \
patients. It is required when `record_requirement` is `conditional`, and null in every other \
case.

`excepted_entities` lists, one entry for each, the entities that the protocol line explicitly \
removes from the set named by this criterion's entity: `text` is the removed entity's name to \
look up in a clinical vocabulary, and `span` is the fragment of the protocol line naming it. \
When the line removes nothing from that set, it is an empty list.

`base_span` is the fragment of the protocol line naming the set from which the excepted \
entities are removed. It is required when `excepted_entities` is not empty, and null in every \
other case.

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

`no_entity` states whether, for this criterion, the protocol line names a clinical entity \
that could be held in a clinical vocabulary. One of:
- `none`: such an entity is named by the line.
- `refers_elsewhere`: no such entity is named by the line, which identifies what the \
criterion concerns only by pointing elsewhere: to an item, a list, a table or an appendix of \
the protocol, or to a product known only by its role in a study.
- `investigator_judgement`: no such entity is named by the line, which leaves the criterion \
to the assessment of the investigator.

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


# Calls 3 and 4 (coordinator, 2026-10-15): the two prompts above, each with the record_change
# block -- its definition after the `window_span` definition and its two output keys after the
# `window_span` key, the place and the text the over-fill A/B measured (prompts_stability.py's
# `fields_stability` block; the arms `cf` and `pf` of run cfpf_20261015_075611). Only
# `record_change` / `record_change_span` are read from their answers. The block is NOT in calls
# 1 and 2: there it shifted record_requirement toward `conditional` in both wordings at once
# (4/113 correct exceptions and 4/138 rr controls broken), which agreement cannot filter.
RECORD_CHANGE_PROMPT_BLOCK = """\
`record_change` states whether the protocol line requires the patient's records of this \
criterion's entity to stay the same, or to change, across a period that the line states. One of:
- `stable`: the line requires those records to stay the same across that period.
- `changed`: the line requires those records to change across that period.
- `none`: the line requires neither.
A requirement that the entity be present, or have been present, for a length of time states a \
duration, not records that stay the same or change. The name of a disease, a condition or a \
finding is the entity itself, even where the name describes how it runs over time, and states \
no requirement on the records.

`record_change_span` is the fragment of the protocol line that states the requirement. It is \
required when `record_change` is not `none` and null otherwise.

"""
RECORD_CHANGE_PROMPT_KEYS = (
    '"record_change": "<stable|changed|none>", '
    '"record_change_span": "<fragment of the protocol line, or null>", '
)
#: Where the block goes: right after these two pieces of the base templates.
_WINDOW_SPAN_DEFINITION = (
    "`window_span` is the fragment of the protocol line that places the criterion in time. It is "
    "required when `timing` is `prospective`; otherwise it is that fragment when the line states "
    "one, and null when the line does not.\n\n"
)
_WINDOW_SPAN_KEY = '"window_span": "<fragment of the protocol line, or null>", '


def _with_block(template: str, definition: str, keys: str) -> str:
    """``template`` with a field's definition after the `window_span` definition and its output
    keys after the `window_span` key -- where the over-fill A/B measured the record_change block.

    Prompt assembly from this module's own template text, not a reading of protocol text: each
    anchor must occur exactly once, or the import fails rather than send a prompt nobody measured.
    """
    for anchor, block in ((_WINDOW_SPAN_DEFINITION, definition), (_WINDOW_SPAN_KEY, keys)):
        if template.count(anchor) != 1:
            raise RuntimeError(f"prompt anchor occurs {template.count(anchor)} times, not once")
        template = template.replace(anchor, anchor + block)
    return template


# This schema adds no protocol examples; the model supplies both meaning and evidence.
OCCURRENCE_THRESHOLD_PROMPT_BLOCK = """\
`occurrence_threshold` states a representable duration or event-count bound on this
criterion's own entity. It is null for a judgement about future survival, a count of
anatomical entities or list members, an unstated unit, or an unsupported anchor.
When present it is an object with:
- `target`: `event_age` for elapsed time since an event, `first_diagnosis_age` for
  elapsed time since the first diagnosis, `drug_era_length` for uninterrupted
  treatment duration, or `event_count` for the number of recorded events.
- `op`: `lt`, `lte`, `gt`, `gte`, or `eq`, comparing the elapsed duration or count.
- `value`: the nonnegative numeric bound stated by the protocol.
- `unit`: `day`, `week`, `month`, `year`, or `count`; do not infer an unstated unit.
- `anchor`: `index`, `informed_consent`, or `screening`. These anchors map to cohort entry.
- `span`: the same verbatim protocol fragment as `threshold_span`, supporting this bound.

"""
OCCURRENCE_THRESHOLD_PROMPT_KEYS = (
    '"occurrence_threshold": <object with target, op, value, unit, anchor, span, or null>, '
)
ANNOTATION_PROMPT = _with_block(
    ANNOTATION_PROMPT, OCCURRENCE_THRESHOLD_PROMPT_BLOCK, OCCURRENCE_THRESHOLD_PROMPT_KEYS
)
AGREEMENT_PROMPT = _with_block(
    AGREEMENT_PROMPT, OCCURRENCE_THRESHOLD_PROMPT_BLOCK, OCCURRENCE_THRESHOLD_PROMPT_KEYS
)


def _with_record_change(template: str) -> str:
    """``template`` with the record_change block inserted where the over-fill A/B measured it."""
    return _with_block(template, RECORD_CHANGE_PROMPT_BLOCK, RECORD_CHANGE_PROMPT_KEYS)


#: Call 3: stage 2's `current` with the block (`cf`), on every row with a protocol line.
RECORD_CHANGE_SYSTEM_PROMPT = ANNOTATION_SYSTEM_PROMPT
RECORD_CHANGE_PROMPT = _with_record_change(ANNOTATION_PROMPT)
#: Call 4: stage 2's `placebo` with the block (`pf`), only when call 3 fills record_change.
RECORD_CHANGE_AGREEMENT_SYSTEM_PROMPT = AGREEMENT_SYSTEM_PROMPT
RECORD_CHANGE_AGREEMENT_PROMPT = _with_record_change(AGREEMENT_PROMPT)

# Calls 9 and 10 (coordinator, 2026-10-22): the two prompts above, each with the window_bound
# block, placed as the record_change block is; only `window_bound` / `window_bound_span` are read
# from their answers. Not in calls 1 and 2, for the reason the record_change block is not: a new
# field there can shift the fields agreement is measured on. CAROLINA inclusion 7's
# "> 3 months prior" was extracted as the window -90..0, which is "within 3 months": a window
# holds two numbers and no side, and nothing else recorded which side the protocol meant.
WINDOW_BOUND_PROMPT_BLOCK = """\
`window_bound` states how a length of time that the protocol line counts back from the \
patient's entry into the trial bounds when this criterion's entity occurred. One of:
- `within`: the entity occurred inside that length of time, so the length of time is the most \
that may have passed between the entity and entry.
- `beyond`: the entity occurred before that length of time began, so the length of time is the \
least that must have passed between the entity and entry.
- `none`: the line counts back no length of time from entry for this criterion's entity.
A length of time for which the entity must have lasted, or for which a treatment must have been \
taken, is not counted back from entry, and gives `none`.

`window_bound_span` is the fragment of the protocol line that states that length of time, with \
its number and its unit. It is required when `window_bound` is not `none` and null otherwise.

"""
WINDOW_BOUND_PROMPT_KEYS = (
    '"window_bound": "<within|beyond|none>", '
    '"window_bound_span": "<fragment of the protocol line, or null>", '
)
#: Call 9: the first wording with the block, on every row with a line that is not a label with
#: members. Call 10: the second wording with the block, only when call 9 answers `beyond`.
WINDOW_BOUND_SYSTEM_PROMPT = ANNOTATION_SYSTEM_PROMPT
WINDOW_BOUND_PROMPT = _with_block(
    ANNOTATION_PROMPT, WINDOW_BOUND_PROMPT_BLOCK, WINDOW_BOUND_PROMPT_KEYS
)
WINDOW_BOUND_AGREEMENT_SYSTEM_PROMPT = AGREEMENT_SYSTEM_PROMPT
WINDOW_BOUND_AGREEMENT_PROMPT = _with_block(
    AGREEMENT_PROMPT, WINDOW_BOUND_PROMPT_BLOCK, WINDOW_BOUND_PROMPT_KEYS
)

#: ``fragment_role`` values (calls 5 and 6). Which revert a ``conditional`` depends on the
#: criterion's role (:func:`_reverting_roles`).
FRAGMENT_HAS_OWN_ENTITY = "has_own_entity"
FRAGMENT_TIME_OR_RECORD = "time_or_record"
FRAGMENT_PATIENTS = "patients"
FRAGMENT_OTHER = "other"
_FRAGMENT_ROLES = frozenset(
    {FRAGMENT_HAS_OWN_ENTITY, FRAGMENT_TIME_OR_RECORD, FRAGMENT_PATIENTS, FRAGMENT_OTHER}
)

_CHECK_HEAD = """Protocol line:
{protocol_line}

Extracted criterion:
- Role: {role}
- Entity text: {entity_text}
- Description: {description}
- Domain: {domain}
- Logic type: {logic_type}
- Group label: {group_label}
- Members: {members}

Fragment of the protocol line: {fragment}

Fields to return:

"""
_CHECK_TAIL = """
Output JSON:
{{"fragment_role": "<patients|has_own_entity|time_or_record|other>", \
"entity_outside_trial": "<yes|no>"}}"""

#: ``entity_outside_trial`` values. Only ``yes`` from both calls lets a revert stand.
OUTSIDE_YES = "yes"
OUTSIDE_NO = "no"
_OUTSIDE_VALUES = frozenset({OUTSIDE_YES, OUTSIDE_NO})

#: Call 5: what the agreed ``conditional_span`` does in the line. Field definition only.
CONDITIONAL_CHECK_PROMPT = _CHECK_HEAD + """\
`fragment_role` states what the fragment above does in the protocol line. One of:
- `has_own_entity`: the fragment says only that the patient has, or has had, this criterion's \
own entity -- the entity this criterion names -- now or in the patient's history.
- `time_or_record`: the fragment states only a time, a visit, a period, or the record that holds \
this criterion's own entity. It says nothing about the patient's state, characteristic or \
treatment.
- `patients`: the fragment names a kind of patient, picked out by some characteristic, state, \
treatment or record other than having this criterion's own entity, at a stated time or in general.
- `other`: anything else.

`entity_outside_trial` states whether a clinical record kept outside this trial could hold this \
criterion's own entity. One of:
- `yes`: such a record could hold it.
- `no`: no such record could hold it, because the entity arises only from the patient's taking \
part in this trial: from the trial's own procedures, periods or study treatment, or from the \
patient's conduct toward the trial.
""" + _CHECK_TAIL

#: Call 6: the same definitions in other words, asked only when call 5's answer reverts.
CONDITIONAL_CHECK_AGREEMENT_PROMPT = _CHECK_HEAD + """\
`fragment_role` says what the fragment quoted above does within the protocol line. One of:
- `has_own_entity`: all the fragment says is that the patient has this criterion's own entity -- \
the entity named by this criterion -- or has had it, at present or in the patient's history.
- `time_or_record`: all the fragment states is a time, a visit, a period, or the record holding \
the own entity of this criterion. Nothing is said by it about the patient's state, characteristic \
or treatment.
- `patients`: a kind of patient is named by the fragment, picked out by some characteristic, \
state, treatment or record other than having the own entity of this criterion, at a stated time or \
in general.
- `other`: anything else.

`entity_outside_trial` says whether the own entity of this criterion could be held in a clinical \
record kept outside this trial. One of:
- `yes`: a record of that kind could hold it.
- `no`: no record of that kind could hold it, since the entity comes about only through the \
patient's taking part in this trial: through the trial's own procedures, periods or study \
treatment, or through the patient's conduct toward the trial.
""" + _CHECK_TAIL

#: The calls-5/6 head without its fragment line. Shown the row's span ('investigational products'
#: on LEADER's 'Hypersensitivity to investigational products'), the model judged the product named
#: there instead of the criterion's entity; the line, entity text and description carry the entity.
_FRAGMENT_LINE = "Fragment of the protocol line: {fragment}\n\n"
assert _FRAGMENT_LINE in _CHECK_HEAD
_TRIAL_ONLY_HEAD = _CHECK_HEAD.replace(_FRAGMENT_LINE, "")

_TRIAL_ONLY_TAIL = """
Output JSON:
{{"trial_only": "<yes|no>"}}"""

#: ``trial_only`` values. Only ``yes`` from both calls refuses a row.
TRIAL_ONLY_YES = "yes"
TRIAL_ONLY_NO = "no"
_TRIAL_ONLY_VALUES = frozenset({TRIAL_ONLY_YES, TRIAL_ONLY_NO})

#: Call 7: whether routine records from before the approach for this trial could check the criterion.
#: Field definition only. Asked of forbidden and required rows; calls 5/6 are not reused as their
#: ``entity_outside_trial`` is about this trial, and products of another trial answered ``yes``.
TRIAL_ONLY_PROMPT = _TRIAL_ONLY_HEAD + """\
`trial_only` states whether this criterion could be checked from the patient's routine health \
records as they stood before the patient was approached for this trial. One of:
- `no`: it could. What the criterion requires, or requires to be absent, is the kind of thing \
routine care records for a patient who takes part in no trial.
- `yes`: it could not. What the criterion requires comes into being only through the conduct of \
a trial -- this one or another -- or through the patient's conduct toward a trial, so no routine \
record from before the approach can hold it.
""" + _TRIAL_ONLY_TAIL

#: Call 8: the same definition in other words, asked only when call 7 answers ``yes``.
TRIAL_ONLY_AGREEMENT_PROMPT = _TRIAL_ONLY_HEAD + """\
`trial_only` says whether the patient's routine health records, as they stood before the patient \
was approached for this trial, could be used to check this criterion. One of:
- `no`: they could. Routine care records the kind of thing this criterion requires, or requires \
to be absent, for patients who take part in no trial.
- `yes`: they could not. The thing this criterion requires is produced only by the conduct of a \
trial, whether this one or another, or by the patient's conduct toward a trial, so no routine \
record made before the approach can contain it.
""" + _TRIAL_ONLY_TAIL

_OWN_ENTITY_TAIL = """
Output JSON:
{{"own_entity": "<named|not_named>"}}"""

#: ``own_entity`` values. Only ``named`` from both calls lifts a row's ``no_entity`` refusal.
OWN_ENTITY_NAMED = "named"
OWN_ENTITY_NOT_NAMED = "not_named"
_OWN_ENTITY_VALUES = frozenset({OWN_ENTITY_NAMED, OWN_ENTITY_NOT_NAMED})

#: Call 11: whether the row's own part of the line names an entity. Field definition only. Shown the
#: row's own span, because calls 1/2 answer ``no_entity`` for the line: P11 MAIN gave CARMELINA's
#: 'alcohol' and 'drug abuse' rows the fragment 'in the opinion of the investigator' of line 10.
OWN_ENTITY_PROMPT = _CHECK_HEAD + """\
`own_entity` states whether the fragment quoted above, which is this criterion's own part of the \
protocol line, names a clinical entity that a clinical vocabulary could hold. One of:
- `named`: the fragment names such an entity: a condition, a finding, a procedure, a drug or \
drug class, a device, a measurement or an observation that a clinical record could carry.
- `not_named`: the fragment names no such entity. It leaves what the criterion is about to an \
assessment, an opinion or a prediction that someone makes about the patient, or it identifies \
what the criterion is about only by pointing elsewhere: to an item, a list, a table or an \
appendix of the protocol, to a product's label, or to a product known only by its role in a study.
""" + _OWN_ENTITY_TAIL

#: Call 12: the same definition in other words, asked only when call 11 answers ``named``.
OWN_ENTITY_AGREEMENT_PROMPT = _CHECK_HEAD + """\
`own_entity` says whether a clinical entity that could be held in a clinical vocabulary is named \
by the fragment quoted above, the part of the protocol line that belongs to this criterion. One of:
- `named`: such an entity is named by the fragment: a condition, a finding, a procedure, a drug \
or a drug class, a device, a measurement or an observation that could be carried by a clinical \
record.
- `not_named`: no such entity is named by the fragment. What the criterion concerns is left by \
it to an assessment, an opinion or a prediction someone makes about the patient, or is \
identified by it only by pointing elsewhere: to an item, a list, a table or an appendix of the \
protocol, to the label of a product, or to a product known only by its role in a study.
""" + _OWN_ENTITY_TAIL

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
    payload: Any, protocol_line: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Keep each field whose evidence is in the line; record why any other was dropped.

    :param payload: the model's parsed JSON object.
    :param protocol_line: the row's ``protocolLine``.
    :returns: ``(fields, rejections)``. ``fields`` always carries every output key; a
        rejected field is None (``record_requirement``, ``base_span``, ``relation``,
        ``timing`` and their spans, the three threshold fields) or left out of the list
        (``excepted_entities``), which is the default behaviour downstream.
    """
    fields: dict[str, Any] = {
        FIELD_RECORD_REQUIREMENT: None,
        FIELD_CONDITIONAL_SPAN: None,
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
        rejected.append(
            _rejection(
                FIELD_RECORD_REQUIREMENT,
                {FIELD_RECORD_REQUIREMENT: raw, FIELD_CONDITIONAL_SPAN: span},
                f"{FIELD_CONDITIONAL_SPAN} is not a substring of protocolLine",
            )
        )
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
    from src.services.occurrence_threshold import FIELD, validated_threshold

    if payload.get(FIELD) is not None:
        fields[FIELD] = validated_threshold(payload[FIELD], protocol_line)
        if fields[FIELD] is None:
            rejected.append(_rejection(FIELD, payload[FIELD], "invalid occurrence threshold"))
    return fields, rejected


def validate_record_change(
    payload: Any, protocol_line: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The one field read from calls 3 and 4: ``record_change`` and its fragment.

    Kept when the value is ``stable`` / ``changed`` / ``none`` and, unless ``none``, its
    fragment is a substring of the line (:func:`span_in_line`); otherwise absent, with the
    rejection recorded. Every other field of the answer is ignored.

    :param payload: the parsed answer of call 3 or call 4.
    :param protocol_line: the row's ``protocolLine``.
    :returns: ``({record_change, record_change_span}, rejections)``.
    """
    fields: dict[str, Any] = {FIELD_RECORD_CHANGE: None, FIELD_RECORD_CHANGE_SPAN: None}
    rejected: list[dict[str, Any]] = []
    if not isinstance(payload, Mapping):
        rejected.append(_rejection("*", payload, "the response is not a JSON object"))
        return fields, rejected
    _validate_choice(
        payload,
        protocol_line,
        fields,
        rejected,
        field=FIELD_RECORD_CHANGE,
        span_field=FIELD_RECORD_CHANGE_SPAN,
        values=_RECORD_CHANGE_VALUES,
        spanless=RecordChange.NONE.value,
    )
    return fields, rejected


def validate_window_bound(
    payload: Any, protocol_line: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The one field read from calls 9 and 10: ``window_bound`` and its fragment.

    Kept when the value is ``within`` / ``beyond`` / ``none`` and, unless ``none``, its fragment
    is a substring of the line AND states exactly one number followed by a time unit
    (:func:`~src.agents.agent1.temporal_grounding.stated_durations`, a machine-format parse);
    otherwise absent, with the rejection recorded.

    :param payload: the parsed answer of call 9 or call 10.
    :param protocol_line: the row's ``protocolLine``.
    :returns: ``({window_bound, window_bound_span}, rejections)``.
    """
    fields: dict[str, Any] = {FIELD_WINDOW_BOUND: None, FIELD_WINDOW_BOUND_SPAN: None}
    rejected: list[dict[str, Any]] = []
    if not isinstance(payload, Mapping):
        rejected.append(_rejection("*", payload, "the response is not a JSON object"))
        return fields, rejected
    _validate_choice(
        payload, protocol_line, fields, rejected, field=FIELD_WINDOW_BOUND,
        span_field=FIELD_WINDOW_BOUND_SPAN, values=_WINDOW_BOUND_VALUES,
        spanless=WindowBound.NONE.value,
    )
    span = fields[FIELD_WINDOW_BOUND_SPAN]
    if span is not None and _stated_days(span) is None:
        rejected.append(_rejection(
            FIELD_WINDOW_BOUND, {FIELD_WINDOW_BOUND: fields[FIELD_WINDOW_BOUND],
                                 FIELD_WINDOW_BOUND_SPAN: span},
            f"{FIELD_WINDOW_BOUND_SPAN} does not state exactly one number and time unit",
        ))
        fields = {FIELD_WINDOW_BOUND: None, FIELD_WINDOW_BOUND_SPAN: None}
    return fields, rejected


def _stated_days(span: Any) -> int | None:
    """Days of the one ``<number> <unit>`` a quoted fragment states, or None when it states none
    or more than one."""
    from src.agents.agent1.temporal_grounding import stated_durations

    durations = stated_durations(span if isinstance(span, str) else None)
    return durations[0][0] if len(durations) == 1 else None


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


def render_prompt(
    row: Mapping[str, Any],
    members: Sequence[Mapping[str, Any]],
    role: str,
    template: str = ANNOTATION_PROMPT,
    fragment: str = "",
) -> str:
    """The user message for one rule: its protocol line and its already-extracted fields.

    :param row: the store criterion row.
    :param members: the rows of its group when ``row`` is a group label, else empty.
    :param role: ``inclusion`` or ``exclusion``.
    :param template: :data:`ANNOTATION_PROMPT`, or :data:`AGREEMENT_PROMPT` for the
        agreement call; both take the same fields.
    :param fragment: the quoted fragment the conditional check asks about (calls 5 and 6);
        unused by every other template.
    :returns: the rendered prompt.
    """
    return template.format(
        protocol_line=str(row.get(_LINE) or ""),
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
        fragment=fragment,
    )


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #

_CACHE_PATH_ENV = "ARTEMIS_ANNOTATION_CACHE_PATH"
_CACHE_ENABLED_ENV = "ARTEMIS_ANNOTATION_CACHE"
_WORKERS_ENV = "ARTEMIS_ANNOTATION_WORKERS"
_OVERLAP_ENV = "ARTEMIS_ANNOTATION_OVERLAP"
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


def cache_key(
    prompt: str,
    model: str,
    *,
    version: str | None = None,
    system: str | None = None,
) -> str:
    """:param prompt: the rendered user prompt (protocol line + extracted fields).
    :param model: the resolved model string.
    :param version: the prompt version; :data:`ANNOTATION_PROMPT_VERSION` when None.
    :param system: the system prompt; :data:`ANNOTATION_SYSTEM_PROMPT` when None. The
        agreement call passes its own version and system prompt, so the two calls of one row
        never share a key.
    :returns: a stable SHA-256 key."""
    payload = json.dumps(
        [
            ANNOTATION_PROMPT_VERSION if version is None else version,
            ANNOTATION_SYSTEM_PROMPT if system is None else system,
            prompt,
            model,
        ],
        ensure_ascii=False,
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
    from src.utils.llm import ANNOTATION_MAX_TOKENS, get_llm

    return get_llm(model_name=model, temperature=0.0, json_mode=True, max_tokens=ANNOTATION_MAX_TOKENS)


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


def _complete(llm: Any, prompt: str, system: str = ANNOTATION_SYSTEM_PROMPT) -> Any:
    from langchain_core.messages import HumanMessage, SystemMessage

    from src.utils.llm import raise_if_truncated

    response = llm.invoke([SystemMessage(content=system), HumanMessage(content=prompt)])
    raise_if_truncated(response, what="criterion annotation")
    return _parse(response.content)


def _ask(
    llm: Any,
    row: Mapping[str, Any],
    members: Sequence[Mapping[str, Any]],
    role: str,
    *,
    model: str,
    template: str,
    system: str,
    version: str,
    fragment: str = "",
) -> tuple[str, str, Any, str | None]:
    """One call with one wording, or its cached answer. Never raises for a model failure.

    :returns: ``(outcome, key, payload, error)``: outcome ``cached``, ``called`` or ``error``;
        the cache key the answer is (or would be) stored under; the parsed answer (None on
        error); the failure as ``Type: message`` (None unless outcome is ``error``). A failed
        call is never cached.
    """
    prompt = render_prompt(row, members, role, template, fragment)
    key = cache_key(prompt, model, version=version, system=system)
    cached = _cache_get(key)
    if cached is not None:
        return "cached", key, cached.get("payload"), None
    try:
        payload = _complete(llm, prompt, system)
    except Exception as exc:
        return "error", key, None, f"{type(exc).__name__}: {exc}"
    _cache_put(key, {"payload": payload, "model": model, "promptVersion": version})
    return "called", key, payload, None


def needs_agreement(fields: Mapping[str, Any]) -> bool:
    """Whether a validated answer fills a field :func:`agree` compares: an excepted entity,
    ``record_requirement: conditional``, or a ``no_entity`` other than ``none``.

    :param fields: the first answer, as :func:`validate_annotation` returns it.
    :returns: True when the agreement call is needed. The rule only ever reverts a fill, so a
        row whose first answer fills none of the three would come out the same without it.
    """
    return (
        bool(fields.get(FIELD_EXCEPTED_ENTITIES))
        or fields.get(FIELD_RECORD_REQUIREMENT) == RecordRequirement.CONDITIONAL.value
        or fields.get(FIELD_NO_ENTITY) not in (None, NoEntity.NONE.value)
    )


def _located(entry: Mapping[str, Any], protocol_line: str) -> dict[str, Any]:
    """An excepted entity as the agreement record stores it: with the offsets it was compared on."""
    offsets = span_offsets(entry.get(FIELD_SPAN), protocol_line)
    return {
        FIELD_TEXT: entry.get(FIELD_TEXT),
        FIELD_SPAN: entry.get(FIELD_SPAN),
        "offsets": list(offsets) if offsets is not None else None,
    }


def agree(
    first: Mapping[str, Any], second: Mapping[str, Any], protocol_line: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Keep each fill of the first answer the rule compares only when the second gives it too.

    Both answers are :func:`validate_annotation` output for the same row, so every fragment
    compared here is already verified in ``protocol_line``.

    * ``excepted_entities``: an entity is kept when an entity of the second answer sits at the
      same offsets in ``protocol_line`` (:func:`~src.utils.span_match.span_offsets`) -- the same
      stretch of the line, whatever its ``text`` says. ``base_span`` stays the first answer's
      while at least one entity survives; when none does, it goes with them.
    * ``record_requirement: conditional`` is kept when the second answer also says
      ``conditional``. Otherwise ``record_requirement`` and ``conditional_span`` become None:
      the value a rejected field takes. The build reads only whether the value is
      ``conditional`` (:func:`conditional_skips`), so None, ``required`` and ``forbidden`` are
      built alike; None asserts neither polarity, which neither answer agreed on.
    * ``no_entity`` other than ``none`` is kept -- the first answer's value and fragment --
      when the second answer also gives a value other than ``none``, whichever one. The build
      reads only whether the line names no entity: either value is refused as an unmappable
      placeholder (``TTEService._refuse_line_naming_no_entity``). Otherwise ``no_entity`` and
      ``no_entity_span`` become None, which :func:`stated_no_entity` reads as ``none``.
      Measured on stage 2: requiring the same value instead broke one more control (DECLARE
      exclusion 48, refers_elsewhere against investigator_judgement) for no extra fix.

    No field is filled from the second answer: the rule only ever reverts a fill.

    :param first: the first answer's validated fields.
    :param second: the agreement call's validated fields; empty when that call failed, so
        nothing is confirmed.
    :param protocol_line: the row's ``protocolLine``.
    :returns: ``(fields, kept, dropped)``: the first answer with the unconfirmed fills
        reverted, and per field what was confirmed and what was taken away.
    """
    fields = {**first, FIELD_EXCEPTED_ENTITIES: list(first.get(FIELD_EXCEPTED_ENTITIES) or [])}
    kept: dict[str, Any] = {}
    dropped: dict[str, Any] = {}

    entries = fields[FIELD_EXCEPTED_ENTITIES]
    if entries:
        confirmed = {
            span_offsets(entry.get(FIELD_SPAN), protocol_line)
            for entry in second.get(FIELD_EXCEPTED_ENTITIES) or []
            if isinstance(entry, Mapping)
        } - {None}
        verdicts = [span_offsets(e.get(FIELD_SPAN), protocol_line) in confirmed for e in entries]
        survivors = [e for e, ok in zip(entries, verdicts) if ok]
        lost = [e for e, ok in zip(entries, verdicts) if not ok]
        fields[FIELD_EXCEPTED_ENTITIES] = survivors
        if survivors:
            kept[FIELD_EXCEPTED_ENTITIES] = [_located(e, protocol_line) for e in survivors]
            kept[FIELD_BASE_SPAN] = first.get(FIELD_BASE_SPAN)
        if lost:
            dropped[FIELD_EXCEPTED_ENTITIES] = [_located(e, protocol_line) for e in lost]
        if not survivors:
            dropped[FIELD_BASE_SPAN] = first.get(FIELD_BASE_SPAN)
            fields[FIELD_BASE_SPAN] = None

    if first.get(FIELD_RECORD_REQUIREMENT) == RecordRequirement.CONDITIONAL.value:
        decision = {"value": RecordRequirement.CONDITIONAL.value,
                    "span": first.get(FIELD_CONDITIONAL_SPAN)}
        if second.get(FIELD_RECORD_REQUIREMENT) == RecordRequirement.CONDITIONAL.value:
            kept[FIELD_RECORD_REQUIREMENT] = decision
        else:
            dropped[FIELD_RECORD_REQUIREMENT] = decision
            fields[FIELD_RECORD_REQUIREMENT] = None
            fields[FIELD_CONDITIONAL_SPAN] = None

    value = first.get(FIELD_NO_ENTITY)
    if value not in (None, NoEntity.NONE.value):
        decision = {"value": value, "span": first.get(FIELD_NO_ENTITY_SPAN)}
        if second.get(FIELD_NO_ENTITY) not in (None, NoEntity.NONE.value):
            kept[FIELD_NO_ENTITY] = decision
        else:
            dropped[FIELD_NO_ENTITY] = decision
            fields[FIELD_NO_ENTITY] = None
            fields[FIELD_NO_ENTITY_SPAN] = None
    return fields, kept, dropped


def agree_record_change(
    first: Mapping[str, Any], second: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Call 3's ``record_change`` fill, kept only when call 4 also fills one.

    The same rule shape as ``no_entity`` in :func:`agree`: ``stable`` or ``changed`` is kept --
    call 3's value and fragment -- when call 4 also gives ``stable`` or ``changed``, whichever;
    the build skips the criterion for either (:func:`record_change_skips`). Otherwise both become
    None, which builds as ``none``. Nothing is filled from call 4.

    :param first: call 3's :func:`validate_record_change` fields.
    :param second: call 4's; empty when that call failed, so nothing is confirmed.
    :returns: ``(fields, kept, dropped)``.
    """
    fields = {
        FIELD_RECORD_CHANGE: first.get(FIELD_RECORD_CHANGE),
        FIELD_RECORD_CHANGE_SPAN: first.get(FIELD_RECORD_CHANGE_SPAN),
    }
    kept: dict[str, Any] = {}
    dropped: dict[str, Any] = {}
    value = fields[FIELD_RECORD_CHANGE]
    if value in _RECORD_CHANGE_FILLS:
        decision = {"value": value, "span": fields[FIELD_RECORD_CHANGE_SPAN]}
        if second.get(FIELD_RECORD_CHANGE) in _RECORD_CHANGE_FILLS:
            kept[FIELD_RECORD_CHANGE] = decision
        else:
            dropped[FIELD_RECORD_CHANGE] = decision
            fields = {FIELD_RECORD_CHANGE: None, FIELD_RECORD_CHANGE_SPAN: None}
    return fields, kept, dropped


def _agreement(
    row: Mapping[str, Any],
    members: Sequence[Mapping[str, Any]],
    role: str,
    first: Mapping[str, Any],
    *,
    first_key: str,
    model: str,
    llm: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Make the agreement call for one row and apply :func:`agree`.

    :returns: the agreed fields and the record stored under :data:`AGREEMENT_KEY`.
    """
    line = str(row.get(_LINE))
    outcome, key, payload, error = _ask(
        llm, row, members, role, model=model, template=AGREEMENT_PROMPT,
        system=AGREEMENT_SYSTEM_PROMPT, version=AGREEMENT_PROMPT_VERSION,
    )
    second, second_rejected = ({}, []) if error is not None else validate_annotation(payload, line)
    fields, kept, dropped = agree(first, second, line)
    record: dict[str, Any] = {
        "promptVersion": AGREEMENT_PROMPT_VERSION,
        "model": model,
        "cacheKey": key,
        "firstCacheKey": first_key,
        "outcome": outcome,
        "kept": kept,
        "dropped": dropped,
        "second": None if error is not None else {
            FIELD_RECORD_REQUIREMENT: second.get(FIELD_RECORD_REQUIREMENT),
            FIELD_CONDITIONAL_SPAN: second.get(FIELD_CONDITIONAL_SPAN),
            FIELD_EXCEPTED_ENTITIES: [
                _located(e, line) for e in second.get(FIELD_EXCEPTED_ENTITIES) or []
            ],
            FIELD_BASE_SPAN: second.get(FIELD_BASE_SPAN),
            FIELD_NO_ENTITY: second.get(FIELD_NO_ENTITY),
            FIELD_NO_ENTITY_SPAN: second.get(FIELD_NO_ENTITY_SPAN),
        },
    }
    if error is not None:
        record["error"] = error
        logger.warning(
            "[annotation] agreement call failed for row %s (%s); its fills are dropped: %s",
            row.get(_ID), error, sorted(dropped),
        )
    if second_rejected:
        record["secondRejected"] = second_rejected
    return fields, record


def _record_change(
    row: Mapping[str, Any],
    members: Sequence[Mapping[str, Any]],
    role: str,
    *,
    model: str,
    llm: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Calls 3 and 4 for one row: ``record_change`` and nothing else.

    Call 3 sends :data:`RECORD_CHANGE_PROMPT` (the `cf` arm); its answer is read only for
    ``record_change`` / ``record_change_span`` (:func:`validate_record_change`). When that fills
    ``stable`` or ``changed``, call 4 sends :data:`RECORD_CHANGE_AGREEMENT_PROMPT` (`pf`) and
    :func:`agree_record_change` keeps the fill only when call 4 fills one too. A failed call
    confirms nothing: call 3 failing leaves record_change absent, call 4 failing drops the fill;
    either error is on the record and never cached.

    :returns: the agreed ``{record_change, record_change_span}`` and the record stored under
        :data:`RECORD_CHANGE_KEY`.
    """
    line = str(row.get(_LINE))
    absent = {FIELD_RECORD_CHANGE: None, FIELD_RECORD_CHANGE_SPAN: None}
    outcome, key, payload, error = _ask(
        llm, row, members, role, model=model, template=RECORD_CHANGE_PROMPT,
        system=RECORD_CHANGE_SYSTEM_PROMPT, version=RECORD_CHANGE_PROMPT_VERSION,
    )
    record: dict[str, Any] = {
        "promptVersion": RECORD_CHANGE_PROMPT_VERSION,
        "model": model,
        "cacheKey": key,
        "outcome": outcome,
        **absent,
        "kept": {},
        "dropped": {},
        "second": None,
    }
    if error is not None:
        record["error"] = error
        logger.warning(
            "[annotation] record_change call failed for row %s; record_change absent: %s",
            row.get(_ID), error,
        )
        return dict(absent), record
    first, rejected = validate_record_change(payload, line)
    record.update(first)
    if rejected:
        record["rejected"] = rejected
    if first[FIELD_RECORD_CHANGE] not in _RECORD_CHANGE_FILLS:
        return first, record
    outcome, key, payload, error = _ask(
        llm, row, members, role, model=model, template=RECORD_CHANGE_AGREEMENT_PROMPT,
        system=RECORD_CHANGE_AGREEMENT_SYSTEM_PROMPT,
        version=RECORD_CHANGE_AGREEMENT_PROMPT_VERSION,
    )
    second, second_rejected = ({}, []) if error is not None else validate_record_change(
        payload, line
    )
    fields, kept, dropped = agree_record_change(first, second)
    record.update(kept=kept, dropped=dropped)
    record["second"] = {
        "promptVersion": RECORD_CHANGE_AGREEMENT_PROMPT_VERSION,
        "cacheKey": key,
        "outcome": outcome,
        FIELD_RECORD_CHANGE: second.get(FIELD_RECORD_CHANGE),
        FIELD_RECORD_CHANGE_SPAN: second.get(FIELD_RECORD_CHANGE_SPAN),
        **({"error": error} if error is not None else {}),
        **({"rejected": second_rejected} if second_rejected else {}),
    }
    if error is not None:
        logger.warning(
            "[annotation] record_change agreement call failed for row %s; its fill is dropped: %s",
            row.get(_ID), error,
        )
    return fields, record


def agree_window_bound(
    first: Mapping[str, Any], second: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Call 9's ``beyond``, kept only when call 10 also answers ``beyond`` for the same number of
    days. ``within`` and ``none`` change no window, so they pass through unconfirmed.

    :param first: call 9's :func:`validate_window_bound` fields.
    :param second: call 10's; empty when that call failed or was not made.
    :returns: ``(fields, kept, dropped)``.
    """
    fields = {
        FIELD_WINDOW_BOUND: first.get(FIELD_WINDOW_BOUND),
        FIELD_WINDOW_BOUND_SPAN: first.get(FIELD_WINDOW_BOUND_SPAN),
    }
    kept: dict[str, Any] = {}
    dropped: dict[str, Any] = {}
    if fields[FIELD_WINDOW_BOUND] == WindowBound.BEYOND.value:
        decision = {"value": WindowBound.BEYOND.value, "span": fields[FIELD_WINDOW_BOUND_SPAN]}
        if (
            second.get(FIELD_WINDOW_BOUND) == WindowBound.BEYOND.value
            and _stated_days(second.get(FIELD_WINDOW_BOUND_SPAN))
            == _stated_days(fields[FIELD_WINDOW_BOUND_SPAN])
        ):
            kept[FIELD_WINDOW_BOUND] = decision
        else:
            dropped[FIELD_WINDOW_BOUND] = decision
            fields = {FIELD_WINDOW_BOUND: None, FIELD_WINDOW_BOUND_SPAN: None}
    return fields, kept, dropped


def _window_bound(
    row: Mapping[str, Any],
    members: Sequence[Mapping[str, Any]],
    role: str,
    *,
    model: str,
    llm: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Calls 9 and 10 for one row: ``window_bound`` and nothing else.

    Call 9 sends :data:`WINDOW_BOUND_PROMPT`; when its validated answer is ``beyond``, call 10
    sends :data:`WINDOW_BOUND_AGREEMENT_PROMPT` and :func:`agree_window_bound` keeps the
    ``beyond`` only when call 10 gives it too. A failed call confirms nothing and is never cached.

    :returns: the agreed ``{window_bound, window_bound_span}`` and the record stored under
        :data:`WINDOW_BOUND_KEY`.
    """
    line = str(row.get(_LINE))
    absent = {FIELD_WINDOW_BOUND: None, FIELD_WINDOW_BOUND_SPAN: None}
    outcome, key, payload, error = _ask(
        llm, row, members, role, model=model, template=WINDOW_BOUND_PROMPT,
        system=WINDOW_BOUND_SYSTEM_PROMPT, version=WINDOW_BOUND_PROMPT_VERSION,
    )
    record: dict[str, Any] = {
        "promptVersion": WINDOW_BOUND_PROMPT_VERSION, "model": model, "cacheKey": key,
        "outcome": outcome, **absent, "kept": {}, "dropped": {}, "second": None,
    }
    if error is not None:
        record["error"] = error
        logger.warning(
            "[annotation] window_bound call failed for row %s; window_bound absent: %s",
            row.get(_ID), error,
        )
        return dict(absent), record
    first, rejected = validate_window_bound(payload, line)
    record.update(first)
    if rejected:
        record["rejected"] = rejected
    if first[FIELD_WINDOW_BOUND] != WindowBound.BEYOND.value:
        return first, record
    outcome, key, payload, error = _ask(
        llm, row, members, role, model=model, template=WINDOW_BOUND_AGREEMENT_PROMPT,
        system=WINDOW_BOUND_AGREEMENT_SYSTEM_PROMPT, version=WINDOW_BOUND_AGREEMENT_PROMPT_VERSION,
    )
    second, second_rejected = ({}, []) if error is not None else validate_window_bound(
        payload, line
    )
    fields, kept, dropped = agree_window_bound(first, second)
    record.update(kept=kept, dropped=dropped)
    record["second"] = {
        "promptVersion": WINDOW_BOUND_AGREEMENT_PROMPT_VERSION,
        "cacheKey": key,
        "outcome": outcome,
        FIELD_WINDOW_BOUND: second.get(FIELD_WINDOW_BOUND),
        FIELD_WINDOW_BOUND_SPAN: second.get(FIELD_WINDOW_BOUND_SPAN),
        **({"error": error} if error is not None else {}),
        **({"rejected": second_rejected} if second_rejected else {}),
    }
    return fields, record


def _reverting_roles(role: str) -> frozenset[str]:
    """The ``fragment_role`` values that revert a ``conditional`` on a criterion of ``role``.

    :data:`FRAGMENT_TIME_OR_RECORD` on either role: the fragment names no patients at all.
    :data:`FRAGMENT_HAS_OWN_ENTITY` on an exclusion only: the patients who have an exclusion's own
    entity are the patients it excludes, which is ``forbidden``, not a subgroup. On an inclusion
    they can be a subgroup the line asks something further of (P6 SEG-OFF LEADER inclusion 12,
    'treated with one or more oral anti-diabetic drugs', kept).
    """
    if role == EXCLUSION:
        return frozenset({FRAGMENT_TIME_OR_RECORD, FRAGMENT_HAS_OWN_ENTITY})
    return frozenset({FRAGMENT_TIME_OR_RECORD})


def _fragment_role(payload: Any) -> str | None:
    value = payload.get("fragment_role") if isinstance(payload, Mapping) else None
    return value if value in _FRAGMENT_ROLES else None


def _entity_outside_trial(payload: Any) -> str | None:
    value = payload.get("entity_outside_trial") if isinstance(payload, Mapping) else None
    return value if value in _OUTSIDE_VALUES else None


def check_conditional(
    row: Mapping[str, Any],
    members: Sequence[Mapping[str, Any]],
    role: str,
    fields: Mapping[str, Any],
    *,
    model: str,
    llm: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Calls 5 and 6 on an agreed ``conditional``: revert it when both read its fragment as
    naming no subgroup of patients for this criterion (:func:`_reverting_roles`).

    Only reverts, never fills: a failed or unreadable answer keeps the ``conditional``. Call 6 is
    made only when call 5's answer reverts; the two need not give the same reverting value.

    :param fields: the agreed answer; its ``record_requirement`` is ``conditional``.
    :returns: ``(fields, record)``: the answer with ``record_requirement`` and
        ``conditional_span`` set to None when reverted, and the record stored under
        :data:`CONDITIONAL_CHECK_KEY`.
    """
    fragment = str(fields.get(FIELD_CONDITIONAL_SPAN) or "")
    record: dict[str, Any] = {"fragment": fragment, "calls": [], "reverted": False}
    reverting = _reverting_roles(role)
    for template, system, version in (
        (CONDITIONAL_CHECK_PROMPT, ANNOTATION_SYSTEM_PROMPT, CONDITIONAL_CHECK_PROMPT_VERSION),
        (CONDITIONAL_CHECK_AGREEMENT_PROMPT, AGREEMENT_SYSTEM_PROMPT,
         CONDITIONAL_CHECK_AGREEMENT_PROMPT_VERSION),
    ):
        outcome, key, payload, error = _ask(
            llm, row, members, role, model=model, template=template, system=system,
            version=version, fragment=fragment,
        )
        answer = _fragment_role(payload)
        outside = _entity_outside_trial(payload)
        call = {"promptVersion": version, "cacheKey": key, "outcome": outcome,
                "fragment_role": answer, "entity_outside_trial": outside}
        if error is not None:
            call["error"] = error
            logger.warning(
                "[annotation] conditional check failed for row %s (%s); conditional kept",
                row.get(_ID), error,
            )
        record["calls"].append(call)
        # A criterion whose own entity arises only from taking part in the trial keeps its
        # skip even when its fragment names no subgroup: freed, it would require a record no
        # patient has (P6 SEG-OFF CAROLINA inclusion 13, run-in compliance).
        if answer not in reverting or outside != OUTSIDE_YES:
            return dict(fields), record
    record["reverted"] = True
    return {**fields, FIELD_RECORD_REQUIREMENT: None, FIELD_CONDITIONAL_SPAN: None}, record


def check_forbidden(
    row: Mapping[str, Any],
    members: Sequence[Mapping[str, Any]],
    role: str,
    *,
    model: str,
    llm: Any,
) -> dict[str, Any]:
    """Calls 7 and 8 on an agreed ``forbidden`` or ``required`` row: does its entity exist only
    through a trial? (Required rows since gate-fix: P8 MAIN's consent rows shipped as required.)

    :data:`TRIAL_ONLY_PROMPT` and :data:`TRIAL_ONLY_AGREEMENT_PROMPT`, shown the line, the entity
    text and the description but no fragment. The row's own verified span (``protocolSpan``; the
    whole line when the span does not verify) is recorded as the refusal's evidence. Call 8 is
    made only when call 7 answers ``yes``, and the row is marked trial-only only when both do; a
    failed or unreadable answer marks nothing. K1/K2 of P7/P8 SEG-OFF: CAROLINA's 'IMP given 2
    months before ... (IMP) start' and ARISTOTLE's 'investigational ... device' were agreed
    ``forbidden`` with ``no_entity: none`` and shipped on junk concepts. Calls 5/6 asked of them
    answered ``yes`` (another trial's product is not "this trial"), hence a pair of its own.

    :returns: the record stored under :data:`TRIAL_ONLY_CHECK_KEY`.
    """
    line = row.get(_LINE)
    span = row.get("protocolSpan")
    fragment = span if span and span_in_line(span, line) else str(line or "")
    record: dict[str, Any] = {"fragment": fragment, "calls": [], "trialOnly": False}
    for template, system, version in (
        (TRIAL_ONLY_PROMPT, ANNOTATION_SYSTEM_PROMPT, TRIAL_ONLY_PROMPT_VERSION),
        (TRIAL_ONLY_AGREEMENT_PROMPT, AGREEMENT_SYSTEM_PROMPT, TRIAL_ONLY_AGREEMENT_PROMPT_VERSION),
    ):
        outcome, key, payload, error = _ask(
            llm, row, members, role, model=model, template=template, system=system,
            version=version, fragment=fragment,
        )
        raw = payload.get(FIELD_TRIAL_ONLY) if isinstance(payload, Mapping) else None
        answer = raw if raw in _TRIAL_ONLY_VALUES else None
        call = {"promptVersion": version, "cacheKey": key, "outcome": outcome,
                FIELD_TRIAL_ONLY: answer}
        if error is not None:
            call["error"] = error
        record["calls"].append(call)
        if answer != TRIAL_ONLY_YES:
            return record
    record["trialOnly"] = True
    return record


def _own_span_outside(row: Mapping[str, Any], fragment: Any) -> str | None:
    """The row's own verified span when it lies wholly outside ``fragment`` in the row's line.

    Offsets only (:func:`~src.utils.span_match.span_offsets`); no word is read.

    :returns: the span, or None when either does not verify in the line or the two overlap.
    """
    line = row.get(_LINE)
    span = row.get("protocolSpan")
    own = span_offsets(span, line) if span else None
    frag = span_offsets(fragment, line) if fragment else None
    if own is None or frag is None or (own[0] < frag[1] and frag[0] < own[1]):
        return None
    return span


def check_own_entity(
    row: Mapping[str, Any],
    role: str,
    span: str,
    *,
    model: str,
    llm: Any,
) -> dict[str, Any]:
    """Calls 11 and 12: does the row's own part of the line name an entity a vocabulary holds?

    Asked of a row whose agreed ``no_entity`` fragment lies wholly outside its own span
    (:func:`_own_span_outside`), shown that span. Call 12 is made only when call 11 answers
    ``named``, and the record says ``named`` only when both do; a failed or unreadable answer
    says nothing, so the row keeps its refusal. P11 MAIN: every row of CARMELINA's line 10
    ('alcohol', 'drug abuse') and line 13 ('cancer ...') was refused on a judgement clause
    elsewhere in its line, because calls 1/2 answer ``no_entity`` for the line.

    :returns: the record stored under :data:`OWN_ENTITY_CHECK_KEY`.
    """
    record: dict[str, Any] = {"fragment": span, "calls": [], "named": False}
    for template, system, version in (
        (OWN_ENTITY_PROMPT, ANNOTATION_SYSTEM_PROMPT, OWN_ENTITY_PROMPT_VERSION),
        (OWN_ENTITY_AGREEMENT_PROMPT, AGREEMENT_SYSTEM_PROMPT, OWN_ENTITY_AGREEMENT_PROMPT_VERSION),
    ):
        outcome, key, payload, error = _ask(
            llm, row, [], role, model=model, template=template, system=system,
            version=version, fragment=span,
        )
        raw = payload.get(FIELD_OWN_ENTITY) if isinstance(payload, Mapping) else None
        answer = raw if raw in _OWN_ENTITY_VALUES else None
        call = {"promptVersion": version, "cacheKey": key, "outcome": outcome,
                FIELD_OWN_ENTITY: answer}
        if error is not None:
            call["error"] = error
        record["calls"].append(call)
        if answer != OWN_ENTITY_NAMED:
            return record
    record["named"] = True
    return record


def stated_trial_only(row: Mapping[str, Any]) -> str | None:
    """The fragment of a row both wordings said exists only because of a clinical trial.

    Re-checked against the row's line, as :func:`stated_no_entity` is, so an edited row cannot
    carry an unchecked verdict into the build or the delivery gate.

    :returns: the fragment, or None.
    """
    record = row.get(TRIAL_ONLY_CHECK_KEY)
    if not isinstance(record, Mapping) or record.get("trialOnly") is not True:
        return None
    fragment = record.get("fragment")
    return fragment if span_in_line(fragment, row.get(_LINE)) else None


def annotate_row(
    row: dict[str, Any],
    members: Sequence[Mapping[str, Any]],
    role: str,
    *,
    model: str,
    llm: Any,
    branch_pool: Executor | None = None,
) -> str:
    """Annotate one rule in place. Never raises for a model failure.

    The first call uses :data:`ANNOTATION_PROMPT`. When its validated answer fills a field
    :func:`agree` compares (:func:`needs_agreement`), a second call with
    :data:`AGREEMENT_PROMPT` follows, its answer is validated the same way, and the stored
    annotation keeps only what both answers give; the record of that goes under
    :data:`AGREEMENT_KEY`. A row whose first answer fills none of the three gets no second
    call and no record. Calls 1 and 2 decide every field except ``record_change``, which
    calls 3 and 4 decide (:func:`_record_change`, recorded under :data:`RECORD_CHANGE_KEY`);
    call 3 is made whether or not call 1 succeeded.

    :param row: the store criterion row; gains :data:`ANNOTATION_KEY` and, when a field
        was dropped, :data:`ANNOTATION_REJECTED_KEY` (the first answer's rejections).
    :param members: the rows of its group when ``row`` is a group label, else empty.
    :param role: ``inclusion`` or ``exclusion``.
    :param model: the resolved model, recorded and part of the cache key.
    :param llm: the chat model handle (built once per run by the caller).
    :param branch_pool: when given, calls 3-4 run on it while calls 1-2-5-6 run here. Neither
        branch reads what the other writes (both render from the row's extracted fields), and
        the merge below is the sequential one, so the row comes out the same.
    :returns: the first call's outcome: ``no-line``, ``cached``, ``called`` or ``error``. The
        agreement call's outcome is on the row's record.
    """
    line = row.get(_LINE)
    if not isinstance(line, str) or not line.strip():
        # Nothing to check a fragment against, so nothing the model said could be kept.
        return "no-line"
    branch = (
        branch_pool.submit(_record_change, dict(row), members, role, model=model, llm=llm)
        if branch_pool is not None else None
    )
    outcome, key, payload, error = _ask(
        llm, row, members, role, model=model, template=ANNOTATION_PROMPT,
        system=ANNOTATION_SYSTEM_PROMPT, version=ANNOTATION_PROMPT_VERSION,
    )
    fields: dict[str, Any] = {}
    rejected: list[dict[str, Any]] = []
    if error is None:
        fields, rejected = validate_annotation(payload, line)
        if needs_agreement(fields):
            fields, record = _agreement(
                row, members, role, fields, first_key=key, model=model, llm=llm
            )
            row[AGREEMENT_KEY] = record
        else:
            row.pop(AGREEMENT_KEY, None)
        if fields.get(FIELD_RECORD_REQUIREMENT) == RecordRequirement.CONDITIONAL.value:
            fields, row[CONDITIONAL_CHECK_KEY] = check_conditional(
                row, members, role, fields, model=model, llm=llm
            )
        else:
            row.pop(CONDITIONAL_CHECK_KEY, None)
        # A label with members is never mapped, so it is not asked. Required rows too (P8 MAIN:
        # every delivered CARMELINA/CAROLINA/EMPA-REG file required a consent-procedure record
        # mapped from an agreed `required` row); a conditional row is skipped by its own reason.
        if (
            fields.get(FIELD_RECORD_REQUIREMENT)
            in (RecordRequirement.FORBIDDEN.value, RecordRequirement.REQUIRED.value)
            and fields.get(FIELD_NO_ENTITY) in (None, NoEntity.NONE.value)
            and not members
        ):
            row[TRIAL_ONLY_CHECK_KEY] = check_forbidden(row, members, role, model=model, llm=llm)
        else:
            row.pop(TRIAL_ONLY_CHECK_KEY, None)
        # A row whose agreed no_entity fragment lies outside its own span is asked about that span.
        own_span = (
            _own_span_outside(row, fields.get(FIELD_NO_ENTITY_SPAN))
            if fields.get(FIELD_NO_ENTITY) not in (None, NoEntity.NONE.value) and not members
            else None
        )
        if own_span is not None:
            row[OWN_ENTITY_CHECK_KEY] = check_own_entity(row, role, own_span, model=model, llm=llm)
        else:
            row.pop(OWN_ENTITY_CHECK_KEY, None)
    change, row[RECORD_CHANGE_KEY] = (
        branch.result() if branch is not None
        else _record_change(row, members, role, model=model, llm=llm)
    )
    # Calls 9-10 stay on this thread, after calls 1-8 and 11-12 as on window-dir: only calls
    # 3-4 were shown (1f99bcf) to read nothing the other calls write.
    # A label with members is never built as an occurrence, so it is not asked.
    if members:
        bound: dict[str, Any] = {}
        row.pop(WINDOW_BOUND_KEY, None)
    else:
        bound, row[WINDOW_BOUND_KEY] = _window_bound(row, members, role, model=model, llm=llm)
    change = {**change, **bound}
    if error is not None:
        row[ANNOTATION_KEY] = {
            "promptVersion": ANNOTATION_PROMPT_VERSION,
            "model": model,
            "error": error,
            **change,
        }
        row.pop(ANNOTATION_REJECTED_KEY, None)
        row.pop(AGREEMENT_KEY, None)
        row.pop(CONDITIONAL_CHECK_KEY, None)
        row.pop(TRIAL_ONLY_CHECK_KEY, None)
        row.pop(OWN_ENTITY_CHECK_KEY, None)
        row.pop(WINDOW_DISAGREEMENT_KEY, None)
        return "error"
    row[ANNOTATION_KEY] = {
        "promptVersion": ANNOTATION_PROMPT_VERSION, "model": model, **fields, **change
    }
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


def stated_window_bound(row: Mapping[str, Any]) -> int | None:
    """Days that must have passed since the entity, when both wordings agreed ``beyond``.

    Re-checked against the row's line, as the other readers are, so an edited row cannot carry
    an unchecked bound into the build.

    :returns: the days the agreed span states, or None.
    """
    fields = _annotation(row)
    if fields.get(FIELD_WINDOW_BOUND) != WindowBound.BEYOND.value:
        return None
    span = fields.get(FIELD_WINDOW_BOUND_SPAN)
    return _stated_days(span) if span_in_line(span, row.get(_LINE)) else None


def annotated_window(row: Mapping[str, Any]) -> tuple[Any, dict[str, Any] | None]:
    """The window the build emits for a row: the extracted one, unless the annotation states
    the side or the size it should have.

    * ``beyond`` agreed by both wordings (:func:`stated_window_bound`): a window ending at or after
      index becomes all prior history up to that many days before index. Its extracted start is
      not kept: in a window ending at index it is the stated duration put on the wrong side
      (CAROLINA CABG, -1461..0). A window already ending before index states the side itself.
      Not on a row whose ``domain`` is Drug: live on P8 (2026-10-22) all eight agreed ``beyond``
      that were wrong read a duration of treatment ("for at least 8 weeks", "if >= 7 consecutive
      days") as time since an event -- six of them Drug rows -- and all eight right ones were
      Condition / Procedure events. A Drug row keeps its extracted window.
    * otherwise, a verified ``window_span`` stating one duration that neither bound matches
      (:func:`window_disagreement`): the window's one bound that is neither 0 nor all prior
      history takes that duration, its side kept. Two such bounds, or two durations, change
      nothing -- which number stands for which is not decided from numbers alone.

    :returns: ``(window, record)``; ``record`` is None when the window is the extracted one, else
        ``{window, extracted, source, span}``.
    """
    from src.utils.circe_lint import DEFAULT_WINDOW_START_DAYS_UNLISTED_DOMAIN as ALL_HISTORY

    window = row.get("window")
    fields = _annotation(row)
    beyond = stated_window_bound(row) if row.get("domain") != DRUG_DOMAIN else None
    if beyond is not None:
        end = window.get("end") if isinstance(window, Mapping) else None
        if isinstance(end, int) and end < 0:
            return window, None
        new = {"start": ALL_HISTORY, "end": -beyond}
        source, span = "window_bound", fields.get(FIELD_WINDOW_BOUND_SPAN)
    else:
        disagreement = window_disagreement(fields, window)
        span = fields.get(FIELD_WINDOW_SPAN)
        days = _stated_days(span)
        if disagreement is None or days is None or not span_in_line(span, row.get(_LINE)):
            return window, None
        finite = [
            k for k, v in window.items() if isinstance(v, int) and 0 < abs(v) < abs(ALL_HISTORY)
        ]
        if len(finite) != 1:
            return window, None
        (bound,) = finite
        new = {**window, bound: days if window[bound] > 0 else -days}
        source = "window_span_duration"
    if isinstance(window, Mapping) and dict(window) == new:
        return window, None
    return new, {
        "window": new,
        "extracted": dict(window) if isinstance(window, Mapping) else None,
        "source": source,
        "span": span,
    }


def _members_of(
    label: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    group = label.get(_GROUP)
    if not label.get(_IS_LABEL) or not group:
        return []
    return [r for r in rows if r is not label and r.get(_GROUP) == group and not r.get(_IS_LABEL)]


def _workers() -> int:
    # 12, measured 2026-10-22 on LEADER + CAROLINA (233 rows, ~552 calls) with calls 3-4
    # overlapped: 4 -> 6363-8431 s, 8 -> 2909 s, 12 -> 2230 s, 16 -> 2083 s (per-call latency
    # 45 -> 79 -> 98 s). Answers stayed within the run-to-run floor at every count.
    raw = os.environ.get(_WORKERS_ENV, "").strip()
    return max(1, int(raw)) if raw else 12


def _overlap() -> bool:
    """:returns: False only when ``ARTEMIS_ANNOTATION_OVERLAP`` is 0 (calls 3-4 then wait
    for calls 1-2-5-6, as before)."""
    return os.environ.get(_OVERLAP_ENV) != "0"


def annotate_eligibility(
    eligibility: Mapping[str, Any], *, model: str | None = None
) -> dict[str, int]:
    """Annotate every inclusion and exclusion row of an eligibility block, in place.

    :param eligibility: carries ``inclusionCriteria`` and ``exclusionCriteria`` rows.
    :param model: model override; defaults to the pipeline's resolved model.
    :returns: outcome counts, plus ``rejected`` (rows that lost at least one field) and the
        agreement call's counts: ``agreementCalls`` (rows it was made for), ``agreementError``
        (rows where it failed) and ``agreementDropped`` (rows that lost a fill to it); and the
        record_change calls': ``recordChangeCalls`` / ``recordChangeError`` (call 3),
        ``recordChangeAgreementCalls`` / ``recordChangeAgreementError`` (call 4) and
        ``recordChangeDropped`` (rows whose fill call 4 did not confirm).
    """
    from src.utils.llm import resolve_model

    resolved = resolve_model(model)
    jobs: list[tuple[dict[str, Any], list[Mapping[str, Any]], str]] = []
    for role, key in _ROLE_ROWS:
        rows = [r for r in eligibility.get(key) or [] if isinstance(r, dict)]
        jobs += [(row, _members_of(row, rows), role) for row in rows]
    counts: dict[str, int] = {}
    if not jobs:
        return counts
    needs_model = any(
        isinstance(r.get(_LINE), str) and r.get(_LINE).strip() for r, _m, _role in jobs
    )
    llm = _build_llm(resolved) if needs_model else None
    workers = _workers()
    # A pool of its own for calls 3-4: submitting them to ``pool`` from its own workers could
    # leave every worker waiting on a branch no worker is free to run.
    with ThreadPoolExecutor(max_workers=workers) as pool, ThreadPoolExecutor(
        max_workers=workers
    ) as branches:
        branch_pool = branches if _overlap() else None
        outcomes = list(
            pool.map(
                lambda job: annotate_row(
                    job[0], job[1], job[2], model=resolved, llm=llm, branch_pool=branch_pool
                ),
                jobs,
            )
        )
    for outcome in outcomes:
        counts[outcome] = counts.get(outcome, 0) + 1
    counts["rejected"] = sum(1 for row, _m, _role in jobs if row.get(ANNOTATION_REJECTED_KEY))
    counts["windowDisagreement"] = sum(
        1 for row, _m, _role in jobs if row.get(WINDOW_DISAGREEMENT_KEY)
    )
    agreements = [
        record for row, _m, _role in jobs if isinstance(record := row.get(AGREEMENT_KEY), Mapping)
    ]
    counts["agreementCalls"] = len(agreements)
    counts["agreementError"] = sum(1 for record in agreements if record.get("outcome") == "error")
    counts["agreementDropped"] = sum(1 for record in agreements if record.get("dropped"))
    checks = [
        record
        for row, _m, _role in jobs
        if isinstance(record := row.get(CONDITIONAL_CHECK_KEY), Mapping)
    ]
    counts["conditionalChecked"] = len(checks)
    counts["conditionalReverted"] = sum(1 for record in checks if record.get("reverted"))
    changes = [
        record
        for row, _m, _role in jobs
        if isinstance(record := row.get(RECORD_CHANGE_KEY), Mapping)
    ]
    seconds = [record["second"] for record in changes if isinstance(record.get("second"), Mapping)]
    counts["recordChangeCalls"] = len(changes)
    counts["recordChangeError"] = sum(1 for record in changes if record.get("outcome") == "error")
    counts["recordChangeAgreementCalls"] = len(seconds)
    counts["recordChangeAgreementError"] = sum(1 for s in seconds if s.get("outcome") == "error")
    counts["recordChangeDropped"] = sum(1 for record in changes if record.get("dropped"))
    logger.info("[annotation] model=%s version=%s %s", resolved, ANNOTATION_PROMPT_VERSION, counts)
    return counts


# --------------------------------------------------------------------------- #
# Readers
# --------------------------------------------------------------------------- #


def agreement_records(rows: Iterable[Any], role: str) -> list[dict[str, Any]]:
    """What the agreement call kept and dropped, one record per row it was made for.

    Written into the built expression under :data:`AGREEMENT_RECORDS_KEY` (present and empty
    when no row needed it), so the file says which fills a second wording took away, and which
    excepted entities, conditionals and no-entity decisions it confirmed -- with the call's
    version and cache key.

    :param rows: one role's store rows.
    :param role: ``inclusion`` or ``exclusion``.
    :returns: ``[{criterionId, role, **the row's agreement record}]``, in store order.
    """
    return [
        {"criterionId": str(row.get(_ID, "")), "role": role, **record}
        for row in rows
        if isinstance(row, Mapping) and isinstance(record := row.get(AGREEMENT_KEY), Mapping)
    ]


def record_change_records(rows: Iterable[Any], role: str) -> list[dict[str, Any]]:
    """What calls 3 and 4 decided, one record per row call 4 was made for or call 3 failed for.

    Written into the built expression under :data:`RECORD_CHANGE_RECORDS_KEY` (present and
    empty when there was none), so the file says which record_change fills call 4 confirmed or
    took away, and which rows went without an answer because call 3 failed.

    :param rows: one role's store rows.
    :param role: ``inclusion`` or ``exclusion``.
    :returns: ``[{criterionId, role, **the row's record_change record}]``, in store order.
    """
    return [
        {"criterionId": str(row.get(_ID, "")), "role": role, **record}
        for row in rows
        if isinstance(row, Mapping)
        and isinstance(record := row.get(RECORD_CHANGE_KEY), Mapping)
        and (record.get("second") is not None or record.get("outcome") == "error")
    ]


def _annotation(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get(ANNOTATION_KEY)
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class ConditionalSkip:
    """Why a row is recorded as a conditional skip.

    :param span: the fragment of the deciding row's line, None when only Agent 1's
        ``conditional`` flag decided (the gate then refuses the permit).
    :param decided_by: the id of the row whose decision this is -- the row itself, or
        the group label it sits under.
    :param source: :data:`SOURCE_ANNOTATION` or :data:`SOURCE_EXTRACTION`.
    :param agreement_version: the agreement call's prompt version, when the deciding row's
        ``conditional`` was confirmed by it (:data:`AGREEMENT_KEY`); None otherwise.
    :param agreement_key: that call's cache key; None otherwise.
    """

    span: str | None
    decided_by: str
    source: str
    agreement_version: str | None = None
    agreement_key: str | None = None


def _confirmed_by(row: Mapping[str, Any], field: str) -> tuple[str | None, str | None]:
    """The agreement call that kept ``field`` on this row: ``(promptVersion, cacheKey)``, or
    ``(None, None)`` when no agreement record keeps it."""
    record = row.get(AGREEMENT_KEY)
    if not isinstance(record, Mapping) or field not in (record.get("kept") or {}):
        return None, None
    return record.get("promptVersion"), record.get("cacheKey")


def _own_conditional(row: Mapping[str, Any]) -> ConditionalSkip | None:
    annotation = _annotation(row)
    span = annotation.get(FIELD_CONDITIONAL_SPAN)
    if annotation.get(
        FIELD_RECORD_REQUIREMENT
    ) == RecordRequirement.CONDITIONAL.value and span_in_line(span, row.get(_LINE)):
        version, key = _confirmed_by(row, FIELD_RECORD_REQUIREMENT)
        return ConditionalSkip(
            span=span,
            decided_by=str(row.get(_ID, "")),
            source=SOURCE_ANNOTATION,
            agreement_version=version,
            agreement_key=key,
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


def header_over_listed_members(
    label: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], span: Any
) -> bool:
    """Whether a group label's span lies in its own line and in none of its members' lines.

    Structural only: every member (nested groups included) carries a line, and the span is
    a substring of none of them. The members are then lines of their own listed under the
    header (S10 nesting), so the header's fragment ("age ≥50 and ≥1 of the following
    criteria:", P11 MAIN LEADER inclusion 9) states the group -- it qualifies none of the
    rows a skip would remove. A label split from ONE line with its members (PLATO's
    "Females of child-bearing potential must ...", CARMELINA's pre-menopausal exclusion)
    shares that line with every member, so the span is in theirs too and this is False.

    shortcut: a header naming a subgroup over a list of its own lines ("Women of
    child-bearing potential must:" then one line per requirement) reads the same way and
    would be built as the group; none exists in the six evaluated trials' P11 stores.
    Upgrade to a field the header annotation fills if one appears.

    :param label: the group label row.
    :param rows: the role's store rows.
    :param span: the label's conditional span.
    :returns: True when the label is a list header over members on lines of their own.
    """
    if not (label.get(_IS_LABEL) and label.get(_GROUP) and span_in_line(span, label.get(_LINE))):
        return False
    groups = group_descendants(rows, str(label.get(_GROUP)))
    members = [r for r in rows if r is not label and r.get(_GROUP) in groups]
    return (
        bool(members)
        and all(m.get(_LINE) for m in members)
        and not any(span_in_line(span, m.get(_LINE)) for m in members)
    )


def conditional_skips(rows: Iterable[Any]) -> dict[str, ConditionalSkip]:
    """The rows of one role that are not emitted because they are conditional.

    A row is conditional when its own accepted annotation says so (with a fragment that
    is in its line) or when Agent 1 flagged it. A conditional group label takes every row
    of its group, nested groups included, with it: the members are the presence rule the
    label describes, and emitting them alone would emit what the label's decision removes.

    Except a list header (:func:`header_over_listed_members`): its annotated span is the
    group itself, so its own decision is dropped and the group is built. A member's own
    decision stands (CARMELINA inclusion 20 under header 12, P11 MAIN).

    :param rows: one role's store rows.
    :returns: criterion id (stringified) -> the decision.
    """
    rows = [r for r in rows if isinstance(r, Mapping)]
    own = {
        str(r.get(_ID, "")): skip
        for r in rows
        if (skip := _own_conditional(r)) is not None
        and not (
            skip.source == SOURCE_ANNOTATION and header_over_listed_members(r, rows, skip.span)
        )
    }
    return _with_group_members(rows, own)


#: The skip reason of a group whose relation nothing states: the IR declared no
#: ``group_type`` and neither the planner nor the annotation verified a relation on its
#: label. Not a permit -- the delivery gate counts it as loss.
GROUP_RELATION_UNRESOLVED_REASON = "group-relation-unresolved"


def unresolved_group_relations(rows: Iterable[Any]) -> dict[str, str]:
    """The rows of one role whose group has no relation to be built from.

    A group is unresolved when its rows carry ``groupType: None`` (the IR declared none;
    a row without the key, from a store written before it was kept, is declared) and its
    label states no verified relation (:func:`stated_relation`). ALL is not a reading of
    such a group, so nothing is built for it: every row of it and of the groups nested in
    it is returned.

    :param rows: one role's store rows.
    :returns: criterion id (stringified) -> the unresolved ``groupId``.
    """
    rows = [r for r in rows if isinstance(r, Mapping)]
    labels = {str(r.get(_GROUP)): r for r in rows if r.get(_IS_LABEL) and r.get(_GROUP)}
    undeclared = {
        str(r.get(_GROUP))
        for r in rows
        if r.get(_GROUP) and "groupType" in r and r["groupType"] is None
    }
    unresolved: dict[str, str] = {}
    for group in undeclared:
        label = labels.get(group)
        if label is not None and stated_relation(label) is not None:
            continue
        inside = group_descendants(rows, group)
        for row in rows:
            if row.get(_GROUP) in inside:
                unresolved.setdefault(str(row.get(_ID, "")), group)
    return unresolved


@dataclass(frozen=True)
class ProspectiveSkip:
    """Why a row is recorded as not observable at index.

    :param span: the ``window_span`` of the deciding row, a substring of its line.
    :param decided_by: the id of the deciding row -- the row itself, or its group label.
    """

    span: str
    decided_by: str


def _is_prospective(row: Mapping[str, Any]) -> bool:
    annotation = _annotation(row)
    return annotation.get(FIELD_TIMING) == Timing.PROSPECTIVE.value and span_in_line(
        annotation.get(FIELD_WINDOW_SPAN), row.get(_LINE)
    )


def prospective_past_window(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """The part before index of a prospective row's window that runs from before index to after it.

    One row can carry a line's two timings: CAROLINA exclusion 12 ("pre-planned ... within
    next 6 months ... or any previous PCI and/or CABG <= 6 weeks prior", P8 MAIN) came out of
    Agent 1 as one row per entity with window -42..180, and the annotation, which names one
    timing per row, said prospective. The window's own numbers show a part before index;
    that part is observable and is emitted, the part after index is not. A prospective row
    whose window ends at or before index has no such evidence and is still skipped whole.

    :param row: a store criterion.
    :returns: ``{"start": <start>, "end": 0}``, or None when the row is not prospective or its
        window does not straddle index.
    """
    window = row.get("window")
    if not isinstance(window, Mapping) or not _is_prospective(row):
        return None
    start, end = window.get("start"), window.get("end")
    if isinstance(start, (int, float)) and isinstance(end, (int, float)) and start < 0 < end:
        return {"start": start, "end": 0}
    return None


def _own_prospective(row: Mapping[str, Any]) -> ProspectiveSkip | None:
    if _is_prospective(row) and prospective_past_window(row) is None:
        return ProspectiveSkip(span=_annotation(row)[FIELD_WINDOW_SPAN], decided_by=str(row.get(_ID, "")))
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
class RecordChangeSkip:
    """Why a row is recorded as a ``record_change`` skip.

    :param span: the ``record_change_span`` of the deciding row, a substring of its line.
    :param value: ``stable`` or ``changed``.
    :param decided_by: the id of the deciding row -- the row itself, or its group label.
    :param agreement_version: call 4's prompt version, when it confirmed the deciding row's
        ``record_change`` (:data:`RECORD_CHANGE_KEY`); None otherwise.
    :param agreement_key: that call's cache key; None otherwise.
    """

    span: str
    value: str
    decided_by: str
    agreement_version: str | None = None
    agreement_key: str | None = None


def _record_change_confirmed_by(row: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Call 4 when it confirmed this row's record_change: ``(promptVersion, cacheKey)``, else
    ``(None, None)``."""
    record = row.get(RECORD_CHANGE_KEY)
    if not isinstance(record, Mapping) or FIELD_RECORD_CHANGE not in (record.get("kept") or {}):
        return None, None
    second = record.get("second") if isinstance(record.get("second"), Mapping) else {}
    return second.get("promptVersion"), second.get("cacheKey")


def _own_record_change(row: Mapping[str, Any]) -> RecordChangeSkip | None:
    annotation = _annotation(row)
    value = annotation.get(FIELD_RECORD_CHANGE)
    span = annotation.get(FIELD_RECORD_CHANGE_SPAN)
    if value in _RECORD_CHANGE_FILLS and span_in_line(span, row.get(_LINE)):
        version, key = _record_change_confirmed_by(row)
        return RecordChangeSkip(
            span=span,
            value=value,
            decided_by=str(row.get(_ID, "")),
            agreement_version=version,
            agreement_key=key,
        )
    return None


def record_change_skips(rows: Iterable[Any]) -> dict[str, RecordChangeSkip]:
    """The rows of one role that are not emitted because their line requires the records of
    the entity to stay the same, or to change, across a period.

    Decided by the row's own agreed annotation only (``record_change`` ``stable`` or
    ``changed``, with a ``record_change_span`` re-checked here against its line). CIRCE can
    test that a record exists in a window, not that it stayed the same or changed across one,
    so the criterion has no faithful rule. A group label with that decision takes every row of
    its group with it, nested groups included, as :func:`conditional_skips` does; a member's
    own decision stands where it has one.

    :param rows: one role's store rows.
    :returns: criterion id (stringified) -> the decision.
    """
    rows = [r for r in rows if isinstance(r, Mapping)]
    own = {
        str(r.get(_ID, "")): skip for r in rows if (skip := _own_record_change(r)) is not None
    }
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


def exception_anchored(row: Mapping[str, Any]) -> bool:
    """Whether the row's protocol line names the set its exception is taken from apart from
    what it excepts: a verified ``base_span`` whose stretch of the line holds none of the
    verified excepted spans.

    Positions only (:func:`~src.utils.span_match.span_offsets`), no word read. False when the
    base span did not verify (PLATO exclusion 55: no base at all) or an excepted span lies inside
    it (CARMELINA exclusion 32: 'PCI' inside 'Pre-planned coronary artery re-vascularisation
    (PCI, CABG) ...'). Read only where a subtraction was refused for covering the whole base
    (``TTEService._recommend_seeded_concept_set``): an unanchored exception that empties its base
    names the row's own entity, an anchored one names a set the mapper drew too broadly.

    :param row: the store criterion row.
    :returns: True when anchored; False when unanchored or when no exception is stated.
    """
    excepted = stated_exceptions(row)
    line = row.get(_LINE)
    base = span_offsets(_annotation(row).get(FIELD_BASE_SPAN), line)
    if not excepted or base is None:
        return False
    for entry in excepted:
        place = span_offsets(entry[FIELD_SPAN], line)
        if place is not None and base[0] <= place[0] and place[1] <= base[1]:
            return False
    return True


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
    """Whether the row's line names no clinical entity FOR THIS ROW, verified against the line.

    The fragment is the line's (calls 1/2 answer for the line). It stands for the row unless the
    row's own verified span lies wholly outside it AND calls 11/12, shown that span, both said it
    names an entity (:data:`OWN_ENTITY_CHECK_KEY`, recorded for the span the row still carries).
    A row annotated before that check has no record and keeps the line's verdict.

    :param row: the store criterion row.
    :returns: the kind and span, or None when the row names an entity or nothing verified.
    """
    annotation = _annotation(row)
    value = annotation.get(FIELD_NO_ENTITY)
    span = annotation.get(FIELD_NO_ENTITY_SPAN)
    if value not in _NO_ENTITY_VALUES or value == NoEntity.NONE.value:
        return None
    if not span_in_line(span, row.get(_LINE)):
        return None
    own = row.get(OWN_ENTITY_CHECK_KEY)
    own_span = _own_span_outside(row, span)
    if (isinstance(own, Mapping) and own.get("named") is True and own_span is not None
            and own.get("fragment") == own_span):
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
      (the case the build already supports) or on a Demographics row (built as a CIRCE
      ``Age``): applied as a value filter, compared against the annotation's
      ``reference_bound``.
    * ``occurrence`` -- a verified structured duration/count applied as an occurrence filter.
    * ``not-representable`` -- an unsupported duration, count, or an ``other`` quantity outside
      Measurement and Demographics: no value filter is emitted for it, the criterion is
      kept, and the threshold is recorded under :data:`UNREPRESENTABLE_THRESHOLDS_KEY` (the
      delivery gate WARNs on it).
    * ``skip-criterion`` -- a verified dose or statistical quantity: the WHOLE criterion is
      skipped and recorded under :data:`THRESHOLD_NOT_REPRESENTABLE_REASON`, which the
      delivery gate counts as criterion loss. A drug emitted without its dose, or a row
      carrying a quantity of the trial's design, says something the protocol did not.

    Decided on the enum alone (coordinator, 2026-10-12); no text is read.
    """

    DEFAULT = "default"
    MEASURED = "measured"
    OCCURRENCE = "occurrence"
    NOT_REPRESENTABLE = "not-representable"
    SKIP_CRITERION = "skip-criterion"


#: The kinds whose criterion is skipped whole rather than kept without its threshold.
_SKIP_KINDS = frozenset({QuantityKind.DOSE, QuantityKind.STATISTICAL})


def threshold_use(row: Mapping[str, Any]) -> tuple[ThresholdUse, StatedThreshold | None]:
    """Decide how the build uses this row's threshold, from its verified annotation only.

    :param row: the store criterion row.
    :returns: the decision and the verified threshold it rests on (None for ``default``).
    """
    # Imported here, as `scripts/verify_circe_delivery.py` does: the models module pulls in
    # the LLM client, which this module otherwise reaches only when it calls the model.
    from src.api.models.tte import DEMOGRAPHIC_DOMAINS

    stated = stated_threshold(row)
    if stated is None:
        return ThresholdUse.DEFAULT, None
    if stated.kind is QuantityKind.LAB_VALUE or (
        stated.kind is QuantityKind.OTHER
        and (row.get("domain") == MEASUREMENT_DOMAIN or row.get("domain") in DEMOGRAPHIC_DOMAINS)
    ):
        return ThresholdUse.MEASURED, stated
    from src.services.occurrence_threshold import occurrence_filter

    if occurrence_filter(row) is not None:
        return ThresholdUse.OCCURRENCE, stated
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
    if use in (
        ThresholdUse.OCCURRENCE, ThresholdUse.NOT_REPRESENTABLE, ThresholdUse.SKIP_CRITERION
    ):
        return None
    if use is ThresholdUse.MEASURED and isinstance(constraint, Mapping):
        applied = {**constraint, "referenceBound": stated.bound}
        if not (constraint.get("unitText") or "").strip() and stated.bound == "absolute":
            from src.api.models.tte import DEMOGRAPHIC_DOMAINS  # built as an Age: no unit

            unit = _unit_after_bound(stated.span, constraint)
            if unit is not None and row.get("domain") not in DEMOGRAPHIC_DOMAINS:
                applied["unitText"] = unit
        return applied
    return constraint


#: A number as a protocol writes it: digits, thousands commas, one decimal point.
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _unit_after_bound(span: str, constraint: Mapping[str, Any]) -> str | None:
    """The unit the verified threshold span states right after the bound's own number.

    Extraction sometimes writes ``unitText: ''`` while the line says "<= 45 kg/m2" (P8 MAIN
    CAROLINA inclusion 25). Format only: the token directly after the number equal to the
    bound (the upper one of a range), kept only when :func:`normalize_unit` resolves it.

    :param span: the annotation's ``threshold_span``, already checked against the line.
    :param constraint: the row's ``valueConstraint``.
    :returns: the unit spelling as the span writes it, or None.
    """
    from src.services.value_constraint import normalize_unit

    high = constraint.get("valueHigh")
    target = high if constraint.get("op") == "bt" and high is not None else constraint.get("value")
    if not isinstance(target, (int, float)):
        return None
    for match in _NUMBER.finditer(span or ""):
        try:
            if float(match.group().replace(",", "")) != float(target):
                continue
        except ValueError:
            continue
        rest = span[match.end():].split()
        token = rest[0].rstrip(").,;:") if rest else ""
        if token and normalize_unit(token) is not None:
            return token
    return None


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
