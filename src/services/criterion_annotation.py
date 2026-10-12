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

The model decides the meaning and quotes the fragment of ``protocolLine`` that supports
it. Code checks one thing only: that each quoted fragment is a substring of the line
(:func:`span_in_line`, the same comparison form as the planner's gate 1). A fragment that
is not in the line makes its field absent -- the row then takes the default behaviour --
and the rejection is recorded on the row under :data:`ANNOTATION_REJECTED_KEY` so it can
be counted. Nothing here reads the line, the description or the entity as words.

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

logger = logging.getLogger(__name__)

#: Bumped whenever either prompt below changes meaning; part of the cache key.
ANNOTATION_PROMPT_VERSION = "rfc016-step3-quantity-v1"

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
FIELD_EXCEPTED_ENTITIES = "excepted_entities"
FIELD_BASE_SPAN = "base_span"
FIELD_TEXT = "text"
FIELD_SPAN = "span"
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


class RecordRequirement(str, Enum):
    """The three values of ``record_requirement`` (RFC-015 §2-1)."""

    REQUIRED = "required"
    FORBIDDEN = "forbidden"
    CONDITIONAL = "conditional"


_REQUIREMENT_VALUES = frozenset(member.value for member in RecordRequirement)


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
any extracted field. You read that protocol line and record facts about the criterion, \
each together with the fragment of the protocol line that states it.

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
"threshold_span": "<fragment of the protocol line, or null>", \
"quantity_kind": "<lab_value|dose|duration|count|statistical|other, or null>", \
"reference_bound": "<uln|lln|none, or null>"}}"""


# --------------------------------------------------------------------------- #
# The one text check
# --------------------------------------------------------------------------- #


def _comparison_form(text: str) -> str:
    """Whitespace-folded and case-folded: the planner's gate-1 comparison form."""
    return " ".join(text.split()).casefold()


def span_in_line(span: Any, line: Any) -> bool:
    """Whether an LLM-quoted fragment occurs in the protocol line.

    The only text test the annotation step makes. Tolerates re-wrapped whitespace and
    case, never a missing or changed word.

    :param span: the fragment the model returned.
    :param line: the row's ``protocolLine``.
    :returns: True when ``span`` is a non-empty substring of ``line`` in comparison form.
    """
    if not isinstance(span, str) or not isinstance(line, str):
        return False
    probe = _comparison_form(span)
    return bool(probe) and probe in _comparison_form(line)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def _rejection(field: str, value: Any, reason: str) -> dict[str, Any]:
    return {"field": field, "value": value, "reason": reason}


def validate_annotation(
    payload: Any, protocol_line: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Keep each field whose evidence is in the line; record why any other was dropped.

    :param payload: the model's parsed JSON object.
    :param protocol_line: the row's ``protocolLine``.
    :returns: ``(fields, rejections)``. ``fields`` always carries the seven output keys;
        a rejected field is None (``record_requirement``, ``base_span``, the three
        threshold fields) or left out of the list (``excepted_entities``), which is the
        default behaviour downstream.
    """
    fields: dict[str, Any] = {
        FIELD_RECORD_REQUIREMENT: None,
        FIELD_CONDITIONAL_SPAN: None,
        FIELD_EXCEPTED_ENTITIES: [],
        FIELD_BASE_SPAN: None,
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

    fields.update(_validate_threshold(payload, protocol_line, rejected))
    return fields, rejected


def _enum_value(raw: Any, values: frozenset[str]) -> str | None:
    """``raw`` case- and whitespace-folded when it is one of ``values``, else None."""
    value = raw.strip().casefold() if isinstance(raw, str) else None
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
    kind = _enum_value(kind_raw, _KIND_VALUES)
    if kind is None:
        rejected.append(
            _rejection(FIELD_QUANTITY_KIND, answer, f"not one of {sorted(_KIND_VALUES)}")
        )
        return fields
    bound = _enum_value(bound_raw, _BOUND_VALUES)
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


def render_prompt(row: Mapping[str, Any], members: Sequence[Mapping[str, Any]], role: str) -> str:
    """The user message for one rule: its protocol line and its already-extracted fields.

    :param row: the store criterion row.
    :param members: the rows of its group when ``row`` is a group label, else empty.
    :param role: ``inclusion`` or ``exclusion``.
    :returns: the rendered prompt.
    """
    return ANNOTATION_PROMPT.format(
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
) -> str:
    """Annotate one rule in place. Never raises for a model failure.

    :param row: the store criterion row; gains :data:`ANNOTATION_KEY` and, when a field
        was dropped, :data:`ANNOTATION_REJECTED_KEY`.
    :param members: the rows of its group when ``row`` is a group label, else empty.
    :param role: ``inclusion`` or ``exclusion``.
    :param model: the resolved model, recorded and part of the cache key.
    :param llm: the chat model handle (built once per run by the caller).
    :returns: ``no-line``, ``cached``, ``called`` or ``error``.
    """
    line = row.get(_LINE)
    if not isinstance(line, str) or not line.strip():
        # Nothing to check a fragment against, so nothing the model said could be kept.
        return "no-line"
    prompt = render_prompt(row, members, role)
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
    fields, rejected = validate_annotation(payload, line)
    row[ANNOTATION_KEY] = {"promptVersion": ANNOTATION_PROMPT_VERSION, "model": model, **fields}
    if rejected:
        row[ANNOTATION_REJECTED_KEY] = rejected
    else:
        row.pop(ANNOTATION_REJECTED_KEY, None)
    return outcome


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
    with ThreadPoolExecutor(max_workers=_workers()) as pool:
        outcomes = list(
            pool.map(
                lambda job: annotate_row(job[0], job[1], job[2], model=resolved, llm=llm), jobs
            )
        )
    for outcome in outcomes:
        counts[outcome] = counts.get(outcome, 0) + 1
    counts["rejected"] = sum(1 for row, _m, _role in jobs if row.get(ANNOTATION_REJECTED_KEY))
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

    :param span: the fragment of the deciding row's line, None when only Agent 1's
        ``conditional`` flag decided (the gate then refuses the permit).
    :param decided_by: the id of the row whose decision this is -- the row itself, or
        the group label it sits under.
    :param source: :data:`SOURCE_ANNOTATION` or :data:`SOURCE_EXTRACTION`.
    """

    span: str | None
    decided_by: str
    source: str


def _own_conditional(row: Mapping[str, Any]) -> ConditionalSkip | None:
    annotation = _annotation(row)
    span = annotation.get(FIELD_CONDITIONAL_SPAN)
    if annotation.get(
        FIELD_RECORD_REQUIREMENT
    ) == RecordRequirement.CONDITIONAL.value and span_in_line(span, row.get(_LINE)):
        return ConditionalSkip(
            span=span, decided_by=str(row.get(_ID, "")), source=SOURCE_ANNOTATION
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


def conditional_skips(rows: Iterable[Any]) -> dict[str, ConditionalSkip]:
    """The rows of one role that are not emitted because they are conditional.

    A row is conditional when its own accepted annotation says so (with a fragment that
    is in its line) or when Agent 1 flagged it. A conditional group label takes every row
    of its group, nested groups included, with it: the members are the presence rule the
    label describes, and emitting them alone would emit what the label's decision removes.

    :param rows: one role's store rows.
    :returns: criterion id (stringified) -> the decision.
    """
    rows = [r for r in rows if isinstance(r, Mapping)]
    own = {str(r.get(_ID, "")): skip for r in rows if (skip := _own_conditional(r)) is not None}
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
    kind = _enum_value(annotation.get(FIELD_QUANTITY_KIND), _KIND_VALUES)
    bound = _enum_value(annotation.get(FIELD_REFERENCE_BOUND), _BOUND_VALUES)
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
