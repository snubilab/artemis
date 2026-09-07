"""Shared value-constraint normalisation and Circe emission (ADR-031 phase 1).

Both Circe builders route here so the defect is fixed once rather than per caller:
``src/services/tte_service.py`` (production seeded-rule path) and
``src/agents/agent3/assembler.py``. Each previously carried its own value-filter
logic with a *different* defect — one emitted no ``Unit`` at all, the other nested
it inside ``ValueAsNumber`` where Circe ignores it.

Defect #10: "ALT > 3 x ULN" reached Circe as ``ValueAsNumber {Value: 3.0}``. Real
ALT runs 10-40 U/L, so as an exclusion that empties the cohort (2,841 of 2,841
tested Synthea patients). Circe already has ``RangeHighRatio``, which divides
``value_as_number`` by the row's own ``range_high`` — no per-site ULN needed.

Defect #11: the extracted unit was dropped, so a mg/dL threshold applied unchanged
to a mmol/L concept in the same concept set.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from typing import Any, Literal, NamedTuple

from src.models.ir import ValueConstraint

ReferenceBound = Literal["absolute", "uln", "lln"]

# Circe accepts these operator tokens verbatim; the IR Literal already matches.
_CIRCE_OPS = frozenset({"gt", "gte", "lt", "lte", "eq"})

# UCUM concept_id -> (concept_code, concept_name), verified against
# ``{CDM_SCHEMA}.concept`` (see verify_unit_table_against_database).
# Codes are counter-intuitive — year is "a", U/L is "[U]/L", eGFR is
# "mL/min/(173.10*-2.m2)" — so they are recorded, never guessed.
_UNIT_CONCEPTS: dict[int, tuple[str, str]] = {
    8505: ("h", "hour"),
    8511: ("wk", "week"),
    8523: ("{ratio}", "ratio"),
    8554: ("%", "percent"),
    8576: ("mg", "milligram"),
    8587: ("mL", "milliliter"),
    8636: ("g/L", "gram per liter"),
    8645: ("[U]/L", "unit per liter"),
    8713: ("g/dL", "gram per deciliter"),
    8725: ("ng/L", "nanogram per liter"),
    8749: ("umol/L", "micromole per liter"),
    8753: ("mmol/L", "millimole per liter"),
    8785: ("/mm3", "per cubic millimeter"),
    8795: ("mL/min", "milliliter per minute"),
    8840: ("mg/dL", "milligram per deciliter"),
    8842: ("ng/mL", "nanogram per milliliter"),
    8845: ("pg/mL", "picogram per milliliter"),
    8876: ("mm[Hg]", "millimeter mercury column"),
    8985: ("[iU]/mL", "international unit per milliliter"),
    9444: ("10*9/L", "billion per liter"),
    9448: ("a", "year"),
    9529: ("kg", "kilogram"),
    9531: ("kg/m2", "kilogram per square meter"),
    9580: ("mo", "month"),
    9593: ("ms", "millisecond"),
    720843: ("mV", "millivolt"),
    720870: ("mL/min/(173.10*-2.m2)", "milliliter per minute per 1.73 square meter"),
}

# Protocol spelling (already run through _clean) -> UCUM concept_id.
# Case matters here: "G/l" is giga-per-litre (10^9/L) while "g/l" is gram-per-litre.
# Exact match therefore wins over the case-insensitive fallback built below.
_UNIT_ALIASES: dict[str, int] = {
    "%": 8554,
    "percent": 8554,
    "h": 8505,
    "hour": 8505,
    "hr": 8505,
    "wk": 8511,
    "week": 8511,
    "{ratio}": 8523,
    "ratio": 8523,
    "mg": 8576,
    "milligram": 8576,
    "mL": 8587,
    "g/L": 8636,
    "g/l": 8636,
    "[U]/L": 8645,
    "U/L": 8645,
    "IU/L": 8645,
    "g/dL": 8713,
    "ng/L": 8725,
    "umol/L": 8749,
    "μmol/L": 8749,  # NFKC folds the U+00B5 micro sign onto this U+03BC mu
    "mcmol/L": 8749,
    "mmol/L": 8753,
    "/mm3": 8785,
    "cells/mm3": 8785,
    "mL/min": 8795,
    "mg/dL": 8840,
    "ng/mL": 8842,
    "pg/mL": 8845,
    "mmHg": 8876,
    "mm[Hg]": 8876,
    "IU/mL": 8985,
    "[iU]/mL": 8985,
    "10*9/L": 9444,
    "10^9/L": 9444,
    "x10^9/L": 9444,
    "x10*9/L": 9444,
    "G/l": 9444,
    "G/L": 9444,
    "a": 9448,
    "year": 9448,
    "yr": 9448,
    "kg": 9529,
    "kg/m2": 9531,
    "mo": 9580,
    "month": 9580,
    "ms": 9593,
    "msec": 9593,
    "millisecond": 9593,
    "mV": 720843,
    "mL/min/1.73m2": 720870,
    "mL/min/1.73squarem": 720870,
    "mL/min/(173.10*-2.m2)": 720870,
    "mL·min-1·1.73m-2": 720870,
}

# "x ULN", "xULN", "times the upper limit of normal", "ULN" — the reference bound
# used to land in unit_text because ADR-031 D1's field did not exist yet.
_REFERENCE_BOUND_RE = re.compile(
    r"(?:[x×*]\s*|times\s+)?(?:the\s+)?"
    r"(?:(?P<upper>upper|uln)|(?P<lower>lower|lln))"
    r"(?:\s*limits?\s+of\s+normal)?"
    r"(?:\s*\(\s*(?:uln|lln)\s*\))?",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    """Reduce a protocol unit spelling to its comparison form.

    Removes ClinicalTrials.gov backslash escapes (``\\>``, ``=\\<``), applies NFKC
    so U+00B5 and U+03BC collapse and ``kg/m²`` becomes ``kg/m2``, then drops all
    whitespace so ``ml/min/1.73 m2`` and ``mL/min/1.73m2`` are one key.
    """
    normalized = unicodedata.normalize("NFKC", text.replace("\\", ""))
    return "".join(normalized.split())


def _build_case_insensitive_index() -> dict[str, int]:
    """Lowercased alias index, minus any spelling that is ambiguous when folded.

    ``G/l`` and ``g/l`` are different units. Folding them would let one silently
    win, and a wrong Unit filter matches zero rows — the same silent-zero failure
    this module exists to remove. Ambiguous keys are dropped so the fallback
    returns None instead of guessing.
    """
    buckets: dict[str, set[int]] = {}
    for alias, concept_id in _UNIT_ALIASES.items():
        buckets.setdefault(alias.lower(), set()).add(concept_id)
    return {key: ids.pop() for key, ids in buckets.items() if len(ids) == 1}


_UNIT_ALIASES_CI = _build_case_insensitive_index()


def normalize_unit(unit_text: str | None) -> int | None:
    """Resolve a protocol unit spelling to a UCUM concept_id, or None (ADR-031 D5).

    Never substitutes a nearest concept: an unrecognised unit yields no ``Unit``
    filter, which is strictly safer than a wrong one.
    """
    if not unit_text:
        return None
    cleaned = _clean(unit_text)
    if not cleaned:
        return None
    exact = _UNIT_ALIASES.get(cleaned)
    if exact is not None:
        return exact
    folded = cleaned.lower()
    if folded in _UNIT_ALIASES_CI:
        return _UNIT_ALIASES_CI[folded]
    if folded.endswith("s"):
        return _UNIT_ALIASES_CI.get(folded[:-1])
    return None


def unit_concept(concept_id: int) -> dict[str, Any]:
    """Full concept object for a Circe ``Unit`` array element, matching gold shape."""
    concept_code, concept_name = _UNIT_CONCEPTS[concept_id]
    return {
        "CONCEPT_CODE": concept_code,
        "CONCEPT_ID": concept_id,
        "CONCEPT_NAME": concept_name,
        "DOMAIN_ID": "Unit",
        "INVALID_REASON_CAPTION": "Unknown",
        "STANDARD_CONCEPT_CAPTION": "Unknown",
        "VOCABULARY_ID": "UCUM",
    }


def split_reference_bound(unit_text: str | None) -> tuple[ReferenceBound, str | None]:
    """Recover a reference bound that legacy IR stored inside ``unit_text``.

    Stored studies carry ``unit_text: "x ULN"`` because extraction captured it
    correctly and the builder had nowhere to put it. Returns the bound plus what
    remains of the unit; the residual must replace ``unit_text`` so a later
    ``normalize_unit`` is not still trying to resolve "x ULN" as a unit.
    """
    if not unit_text:
        return "absolute", unit_text
    match = _REFERENCE_BOUND_RE.search(unit_text)
    if match is None:
        return "absolute", unit_text
    bound: ReferenceBound = "uln" if match.group("upper") else "lln"
    residual = (unit_text[: match.start()] + unit_text[match.end() :]).strip(" \t()x×*")
    return bound, residual or None


def _field(vc: Any, *names: str) -> Any:
    """Read a field from either a ValueConstraint model or a raw IR dict.

    tte_service holds camelCase dicts straight off the LLM; assembler holds the
    pydantic model. Absorbing both here is what keeps the two callers from each
    growing their own conversion.
    """
    for name in names:
        if isinstance(vc, Mapping):
            if name in vc:
                return vc[name]
        elif hasattr(vc, name):
            return getattr(vc, name)
    return None


def resolve_reference_bound(vc: Any) -> tuple[ReferenceBound, str | None]:
    """The bound a constraint really carries, plus what is left of its unit.

    Reads the ADR-031 D1 field, and falls back to :func:`split_reference_bound`
    when it says ``absolute``, because legacy IR parked the bound in ``unit_text``
    and every study in the current store still does: study 10's liver group is
    written ``{referenceBound: "absolute", unitText: "x ULN"}``. Reading the field
    alone would call that constraint absolute, which is exactly backwards.
    """
    bound: ReferenceBound = _field(vc, "reference_bound", "referenceBound") or "absolute"
    unit_text = _field(vc, "unit_text", "unitText")
    if bound == "absolute":
        return split_reference_bound(unit_text)
    return bound, unit_text


def build_measurement_value_filter(vc: Any) -> dict[str, Any]:
    """Circe fragment for a Measurement value condition (ADR-031 D4).

    Returns a flat dict of Circe keys for the caller to merge into a criteria dict
    that already holds ``CodesetId`` and friends::

        criteria_attrs.update(build_measurement_value_filter(vc))

    | reference_bound | unit resolves | emits                          |
    |-----------------|---------------|--------------------------------|
    | absolute        | yes           | ValueAsNumber + sibling Unit   |
    | absolute        | no            | ValueAsNumber                  |
    | uln             | -             | RangeHighRatio                 |
    | lln             | -             | RangeLowRatio                  |

    ``uln``/``lln`` must not also emit ``ValueAsNumber``: Circe ANDs the two, so
    ``RangeHighRatio > 3`` combined with ``ValueAsNumber > 3`` leaves defect #10
    fully intact. Returns an empty dict when the constraint is unusable, so a
    malformed value never silently becomes a filter that matches nothing.
    """
    if vc is None:
        return {}
    value = _field(vc, "value", "Value")
    op = _field(vc, "op", "Op")
    if value is None or not isinstance(op, str):
        return {}
    circe_op = op.lower()
    if circe_op not in _CIRCE_OPS:
        return {}

    bound, unit_text = resolve_reference_bound(vc)

    operand = {"Value": float(value), "Op": circe_op}
    if bound == "uln":
        return {"RangeHighRatio": operand}
    if bound == "lln":
        return {"RangeLowRatio": operand}

    fragment: dict[str, Any] = {"ValueAsNumber": operand}
    concept_id = _field(vc, "unit_concept_id", "unitConceptId") or normalize_unit(unit_text)
    if concept_id in _UNIT_CONCEPTS:
        # Sibling of ValueAsNumber, not a key inside it — Circe ignores it nested.
        fragment["Unit"] = [unit_concept(concept_id)]
    return fragment


# --------------------------------------------------------------------------
# Group-label threshold propagation
# --------------------------------------------------------------------------

# Wire-format constant: the `_skippedCriteria` reason recorded when a group
# label's threshold reached no member. Import it, never retype it -- a guessed
# spelling makes every probe against the census return False.
STRANDED_GROUP_CONSTRAINT_REASON = "group-label-absolute-constraint-stranded"


class GroupConstraintResolution(NamedTuple):
    """What a group member should carry, and why, given its label's constraint.

    ``constraint`` is what the member ends up with (its own, the label's, or
    None); ``propagated`` says the label's constraint was handed down;
    ``refusal_reason`` is set only when a label constraint existed, the member
    had none, and handing it down would have been unsafe.
    """

    constraint: Any | None
    propagated: bool
    refusal_reason: str | None


def is_reference_relative(vc: Any) -> bool:
    """True when this constraint is a *ratio* against the row's own reference range.

    Such a bound is unit-free and therefore analyte-independent: "3 times the
    upper limit of normal" means the same thing for ALT, AST and ALP, because
    Circe divides by each row's own ``range_high``. An absolute bound is not --
    "240 mg/dL" is meaningful for plasma glucose and meaningless for HbA1c,
    which is reported in % or mmol/mol.

    Asked of :func:`build_measurement_value_filter` rather than re-derived, so
    there is one predicate rather than two that can drift apart: a
    reference-relative constraint is exactly one that emits a ``Range*Ratio``.
    An unusable constraint emits ``{}`` and so is never reference-relative,
    which is the safe answer.
    """
    fragment = build_measurement_value_filter(vc)
    return "RangeHighRatio" in fragment or "RangeLowRatio" in fragment


def resolve_group_member_constraint(
    parent_vc: Any, member_vc: Any
) -> GroupConstraintResolution:
    """Decide what one member of a labelled criteria group is measured against.

    Both Circe builders call this and nothing else decides it:
    ``TTEService._criteria_from_ir`` (store rows) and
    ``CohortAssembler._build_inclusion_rule`` (Circe directly). Each previously
    read only the member's own constraint, so a threshold written once on the
    group label was dropped by both -- and the label row is unconditionally
    refused (``isGroupLabel``), so nothing downstream still held the number.

    Propagation is gated on :func:`is_reference_relative`, never on the analyte.
    Copying "> 240 mg/dL" onto "Elevated HbA1c" builds a MeasurementOccurrence
    matching zero rows; inside an ABSENCE exclusion that turns a visible
    over-exclusion into a silent no-op, and ``refuse_domain_contradiction``
    cannot see it because both sides are Measurement. Refusing instead leaves the
    member honestly unfiltered and returns a reason for the caller to record.

    A member that carries its own constraint always keeps it: SPEC-INFRA-007
    REQ-004/REQ-005 made the decomposer ground each sub-item's threshold in its
    own source text, and this must not overwrite that answer.

    :param parent_vc: the group label's constraint, or None.
    :param member_vc: the member's own constraint, or None.
    :returns: the member's effective constraint plus why.
    """
    if member_vc is not None:
        return GroupConstraintResolution(member_vc, False, None)
    if parent_vc is None:
        return GroupConstraintResolution(None, False, None)
    if is_reference_relative(parent_vc):
        return GroupConstraintResolution(parent_vc, True, None)
    return GroupConstraintResolution(None, False, STRANDED_GROUP_CONSTRAINT_REASON)


# --------------------------------------------------------------------------
# ADR-031 phase 2 (D2/D6/D7/D8): protocol phrase -> ValueConstraint
# --------------------------------------------------------------------------

# Statistical decision rules are the corpus's most dangerous false positives:
# "upper boundary of the two-sided 95% confidence interval was less than 1.3"
# carries a comparator, a number and the words "upper ... of" — one word away
# from "upper limit of normal". A reference bound is always a *limit*, never a
# *boundary*, so the two vocabularies are checked before anything else.
_STATISTICAL_MARKER_RE = re.compile(
    r"confidence\s+interval|boundar(?:y|ies)|(?:one|two)[-\s]?sided"
    r"|alpha\s+level|\bmargins?\b|hazard\s+ratio|non[-\s]?inferiority",
    re.IGNORECASE,
)

# ULN/LLN in every spelling the corpus contains. The negative lookarounds are
# load-bearing: "≤ 5ULN" glues the multiplier onto the abbreviation, so \b does
# not fire between "5" and "U".
_BOUND_RE = re.compile(
    r"(?P<upper>upper\s+limits?\s+of\s+normal|(?<![A-Za-z])ULN(?![A-Za-z]))"
    r"|(?P<lower>lower\s+limits?\s+of\s+normal|(?<![A-Za-z])LLN(?![A-Za-z]))",
    re.IGNORECASE,
)

# Ordered so that at a given position the longer spelling wins ("less than or
# equal" before "less than", "no more than" before "more than").
_COMPARATOR_SPELLINGS: tuple[tuple[str, str], ...] = (
    (r">=|=>|≥", "gte"),
    (r"<=|=<|≤", "lte"),
    (r">", "gt"),
    (r"<", "lt"),
    (r"greater\s+than\s+or\s+equal(?:\s+to)?", "gte"),
    (r"less\s+than\s+or\s+equal(?:\s+to)?", "lte"),
    (r"(?:equal(?:\s+to)?|at)\s+or\s+(?:above|greater|higher)", "gte"),
    (r"(?:equal(?:\s+to)?|at)\s+or\s+(?:below|less|lower)", "lte"),
    (r"at\s+least|no\s+less\s+than", "gte"),
    (r"at\s+most|no\s+more\s+than|no\s+greater\s+than|up\s+to", "lte"),
    (r"greater\s+than|higher\s+than|more\s+than|above", "gt"),
    (r"less\s+than|lower\s+than|below", "lt"),
)
_COMPARATOR_RE = re.compile(
    "|".join(f"(?P<c{i}>{p})" for i, (p, _) in enumerate(_COMPARATOR_SPELLINGS)),
    re.IGNORECASE,
)
_COMPARATOR_OPS = {f"c{i}": op for i, (_, op) in enumerate(_COMPARATOR_SPELLINGS)}

# The comma in "100,000/mm3" is a thousands separator; the first alternative has
# to be tried before the plain one or the value parses as 100.
_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")

# What may stand between a multiplier and the bound it multiplies. Anything else
# means the number belongs to a different clause, so the multiplier is implicit 1
# ("...platelet count <90x10^9/L; hemoglobin below the lower limit of normal").
_MULTIPLIER_FILLER = frozenset(
    {"x", "×", "*", "times", "time", "fold", "of", "the", "a",
     "institutional", "local", "central", "site", "higher", "greater",
     "lower", "than", "above", "below"}
)

# Durations at these scales are index-relative windows, not measured values.
# "year" is absent on purpose: "age >= 18 years" is a patient attribute, and
# "ms" likewise measures an ECG interval.
_WINDOW_UNITS = frozenset(
    {"second", "sec", "minute", "min", "hour", "hr", "h", "day", "week", "wk", "month", "mo"}
)
_TIME_UNITS = _WINDOW_UNITS | {"year", "yr"}
_RELATIVE_TIME_ANCHOR_RE = re.compile(
    r"\bwithin\b|\bprior\s+to\b|\bpreceding\b|\bbefore\b|\bafter\b|\bsince\b|\bago\b",
    re.IGNORECASE,
)

# ClinicalTrials.gov strips the caret upstream, so "1.5 x 10^9/L" can arrive as
# "1.5 x 109/L". Reading 109 as the magnitude is off by nine orders.
_GIGA_PER_LITRE_RE = re.compile(r"^[x×*]?\s*10\s*[\^*]?\s*9\s*/\s*l$", re.IGNORECASE)

_PHRASE_SPLIT_RE = re.compile(r";|\s+(?:and/or|or|and)\s+|,(?!\d)", re.IGNORECASE)


def _canonical_unit(text: str) -> str:
    return "x 10^9/L" if _GIGA_PER_LITRE_RE.match(text) else text


def _resolve_unit(tail: str) -> tuple[str | None, int | None]:
    """Longest leading run of `tail` that names a unit, plus its concept_id.

    A threshold phrase can be handed over with prose still attached
    ("mg prednisolone or equivalent"), so the whole tail is rarely the unit;
    conversely "ml/min/1.73 m2" is two whitespace-separated tokens that are one
    unit. When nothing resolves the tail is returned verbatim and unresolved —
    ADR-031 D5 forbids substituting a nearest concept.
    """
    tail = tail.strip()
    if not tail:
        return None, None
    tokens = tail.split()
    for size in range(len(tokens), 0, -1):
        candidate = _canonical_unit(" ".join(tokens[:size]).rstrip(".,;:)"))
        concept_id = normalize_unit(candidate)
        if concept_id is not None:
            return candidate, concept_id
    return tail, None


def _is_temporal(unit_text: str | None, phrase: str) -> bool:
    """True when the quantity is a time window rather than a measured value (D8)."""
    if not unit_text:
        return False
    token = "".join(unit_text.split()).lower().rstrip(".")
    token = token[:-1] if token.endswith("s") else token
    if token in _WINDOW_UNITS:
        return True
    # A year is an age until something anchors it to the index event.
    return token in _TIME_UNITS and _RELATIVE_TIME_ANCHOR_RE.search(phrase) is not None


def _comparator_before(text: str, limit: int) -> tuple[str, int] | None:
    """Last comparator starting before `limit`, as (op, end offset)."""
    found: tuple[str, int] | None = None
    for match in _COMPARATOR_RE.finditer(text):
        if match.start() >= limit:
            break
        found = (_COMPARATOR_OPS[match.lastgroup or ""], match.end())
    return found


def _multiplier_before(text: str, bound_start: int) -> float:
    """The multiplier attached to a reference bound, or the implicit 1.0 (D6).

    This is where the overloaded "x" is decided. It is never read as a token:
    "3x ULN" attaches because only filler separates 3 from the bound, while
    "3x10^9/L" has no bound at all and never reaches here.
    """
    numbers = list(_NUMBER_RE.finditer(text, 0, bound_start))
    if not numbers:
        return 1.0
    last = numbers[-1]
    between = text[last.end() : bound_start]
    if all(token.strip("().,-").lower() in _MULTIPLIER_FILLER for token in between.split()):
        return float(last.group().replace(",", ""))
    return 1.0


def parse_value_constraint(phrase: str) -> ValueConstraint | None:
    """Structure one already-isolated threshold phrase, or reject it (ADR-031 D2).

    Returns None for the eight negative families in the corpus: statistical
    decision rules, inclusive ranges, unit-conversion restatements, definitional
    equalities, protocol names, spelled-out counts, carve-out clauses and
    non-numeric grades. A false positive here is silent — it produces a
    valid-looking cohort holding the wrong patients — so every branch that
    cannot justify a number declines to invent one.
    """
    if not phrase:
        return None
    text = phrase.replace("\\", "").strip()  # CT.gov escapes: \> =\< \[ALT\]
    if _STATISTICAL_MARKER_RE.search(text):
        return None
    # A wholly parenthesised threshold is an aside, not the operative one: the
    # corpus's two cases are a unit restatement of the threshold just stated
    # (">240 mg/dl (>13.3 mmol/L)" — emitting both ANDs mutually exclusive
    # filters) and a duration gloss ("long-standing (>5 years)").
    if text.startswith("(") and text.endswith(")"):
        return None

    bound_match = _BOUND_RE.search(text)
    if bound_match is not None:
        comparator = _comparator_before(text, bound_match.start())
        if comparator is None:
            return None  # a bound with no direction is not a constraint
        return ValueConstraint(
            op=comparator[0],
            value=_multiplier_before(text, bound_match.start()),
            reference_bound="uln" if bound_match.group("upper") else "lln",
        )

    # First comparator, not last: ">240 mg/dl (>13.3 mmol/L)" states one
    # threshold twice, and the operative one is the first. Reading the last
    # would emit the parenthetical restatement and silently drop the mg/dL.
    comparator = _COMPARATOR_RE.search(text)
    if comparator is None:
        return _bare_value(text)
    number = _NUMBER_RE.search(text, comparator.end())
    if number is None:
        return None
    unit_text, unit_concept_id = _resolve_unit(text[number.end() :])
    if _is_temporal(unit_text, text):
        return None
    return ValueConstraint(
        op=_COMPARATOR_OPS[comparator.lastgroup or ""],
        value=float(number.group().replace(",", "")),
        unit_text=unit_text,
        unit_concept_id=unit_concept_id,
    )


def _bare_value(text: str) -> ValueConstraint | None:
    """A comparator-less phrase counts only as "<number> <unit>", nothing more.

    Protocols elide the comparator when restating a threshold in a second unit
    ("ANC >= 1,000/mm3 (1 G/l)"), which reads as at-least. Requiring the phrase
    to be *exactly* a number and a resolvable unit is what keeps "margin of 1.3",
    "24-hour urine collection", "1 cup = 250 mL" and "6.5 - 8.5%" out.
    """
    match = _NUMBER_RE.match(text)
    if match is None:
        return None
    unit_text = _canonical_unit(text[match.end() :].strip())
    unit_concept_id = normalize_unit(unit_text)
    if unit_concept_id is None or _is_temporal(unit_text, text):
        return None
    return ValueConstraint(
        op="gte",
        value=float(match.group().replace(",", "")),
        unit_text=unit_text,
        unit_concept_id=unit_concept_id,
    )


def parse_value_constraints(line: str) -> list[ValueConstraint]:
    """Every constraint on one criterion line (ADR-031 D7).

    "TSH >1.2 ULN or <0.8 LLN" is two constraints; a return type of
    ``ValueConstraint | None`` cannot express it. Splitting on clause boundaries
    is deliberately blunt — a segment that is not a threshold parses to None and
    is dropped, so over-splitting costs nothing while under-splitting loses a
    constraint.
    """
    return [
        constraint
        for segment in _PHRASE_SPLIT_RE.split(line)
        if (constraint := parse_value_constraint(segment)) is not None
    ]


def annotate_value_constraints(line: str) -> str:
    """Render a criterion's parsed constraints for Agent 1's prompt (ADR-031-B).

    ADR-031 D2 split the work one way -- the LLM finds which criteria carry a
    threshold, deterministic code turns the phrase into structure. ADR-031-B closes
    the loop: the parser runs FIRST and its answer travels back into the prompt, so
    the numbers survive even when the model summarises the phrase away.

    The division this implements, stated because reports must not overclaim: the
    parser extracts the numbers, the model places them into one rule per analyte.
    "the LLM extracts value constraints from the literature" is not what happens.

    Agent 1 is asked to classify a criterion and extract its numbers in one pass.
    It is reliable at the first and not at the second, and the failure is silent:
    ARISTOTLE's exclusion 20) reached the LLM intact and came back as
    ``{"description": "Liver Enzyme Elevation", "valueConstraint": null}`` in the
    same run that extracted LVEF, haemoglobin, platelets and creatinine correctly.
    Shape separated them -- three analytes and two thresholds in one sentence --
    not difficulty, so a larger model is the wrong remedy.

    ``parse_value_constraints`` reads that sentence as 2.0 gt uln and 1.5 gte uln,
    which is what the gold Circe carries. Putting its answer next to the criterion
    makes the numbers something the model copies rather than derives.

    Returns an empty string when nothing parses. Annotating every line, including
    the ones with no threshold, would teach the model that an annotation is always
    expected and invite it to invent one.

    :param line: a single criterion as it will appear in the prompt.
    :returns: newline-separated ``[value_constraint] {...}`` lines, or "".
    """
    rendered = []
    for constraint in parse_value_constraints(line):
        payload: dict[str, Any] = {
            "op": constraint.op,
            "value": constraint.value,
            "referenceBound": getattr(constraint, "reference_bound", None) or "absolute",
        }
        if constraint.unit_text:
            payload["unitText"] = constraint.unit_text
        rendered.append(f"      [value_constraint] {json.dumps(payload)}")
    return "\n".join(rendered)


def verify_unit_table_against_database() -> list[str]:
    """Compare _UNIT_CONCEPTS against the live vocabulary; return discrepancies.

    The static table keeps normalize_unit a pure function that tests can run
    without Postgres. This is how the table is kept honest: run it after a
    vocabulary refresh rather than assuming no drift.
    """
    import psycopg2

    from src.settings import settings

    problems: list[str] = []
    conn = psycopg2.connect(settings.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT concept_id, concept_code, concept_name, domain_id, "
                f"vocabulary_id, invalid_reason FROM {settings.CDM_SCHEMA}.concept "
                f"WHERE concept_id = ANY(%s)",
                (list(_UNIT_CONCEPTS),),
            )
            rows = {r[0]: r[1:] for r in cur.fetchall()}
    finally:
        conn.close()

    for concept_id, (code, name) in _UNIT_CONCEPTS.items():
        row = rows.get(concept_id)
        if row is None:
            problems.append(f"{concept_id}: absent from vocabulary")
            continue
        db_code, db_name, domain, vocabulary, invalid_reason = row
        if db_code != code:
            problems.append(f"{concept_id}: concept_code {code!r} != {db_code!r}")
        if db_name != name:
            problems.append(f"{concept_id}: concept_name {name!r} != {db_name!r}")
        if domain != "Unit" or vocabulary != "UCUM":
            problems.append(f"{concept_id}: {vocabulary}/{domain}, expected UCUM/Unit")
        if invalid_reason is not None:
            problems.append(f"{concept_id}: invalid_reason={invalid_reason!r}")
    return problems


def demo() -> None:
    """Self-check of the four D4 rows on real corpus inputs."""
    for alias in _UNIT_ALIASES:
        assert _clean(alias) == alias, f"alias {alias!r} is not in cleaned form"
        assert _UNIT_ALIASES[alias] in _UNIT_CONCEPTS, f"alias {alias!r} has no concept"

    rows = [
        ("absolute + unit resolves", {"op": "gte", "value": 7.0, "unitText": "%"}),
        ("absolute + unit unresolvable", {"op": "gt", "value": 110.0, "unitText": "bpm"}),
        ("uln (legacy unit_text)", {"op": "gt", "value": 3.0, "unitText": "x ULN"}),
        ("lln (first-class field)", {"op": "lt", "value": 0.8, "reference_bound": "lln"}),
    ]
    for label, vc in rows:
        print(f"{label:32} {vc}\n{'':32} -> {build_measurement_value_filter(vc)}")

    assert build_measurement_value_filter(rows[0][1]) == {
        "ValueAsNumber": {"Value": 7.0, "Op": "gte"},
        "Unit": [unit_concept(8554)],
    }
    assert build_measurement_value_filter(rows[1][1]) == {
        "ValueAsNumber": {"Value": 110.0, "Op": "gt"}
    }
    assert build_measurement_value_filter(rows[2][1]) == {
        "RangeHighRatio": {"Value": 3.0, "Op": "gt"}
    }
    assert build_measurement_value_filter(rows[3][1]) == {
        "RangeLowRatio": {"Value": 0.8, "Op": "lt"}
    }

    # Spelling variants that exact-match against a 9-key dict cannot survive.
    assert normalize_unit("years") == 9448
    assert normalize_unit("kg/m²") == 9531
    assert normalize_unit("ml/min/1.73 m2") == 720870
    assert normalize_unit("µmol/L") == normalize_unit("μmol/L") == 8749
    assert normalize_unit("G/l") == 9444 and normalize_unit("g/l") == 8636
    assert normalize_unit("bpm") is None and normalize_unit("cups per day") is None

    # Phase 2: one row per trap the corpus sets for a number-first parser.
    phrases = [
        ("uln ratio", "\\> 3 x upper limit of normal (ULN)", ("gt", 3.0, "uln")),
        ("lln ratio", "\\<0.8 LLN", ("lt", 0.8, "lln")),
        ("implicit x1", "≤ institutional ULN", ("lte", 1.0, "uln")),
        ("x is a magnitude", "\\> 3x109/L", ("gt", 3.0, "absolute")),
        ("statistical rule", "upper boundary of the 95% confidence interval [CI], <1.30", None),
    ]
    for label, phrase, expected in phrases:
        parsed = parse_value_constraint(phrase)
        print(f"{label:32} {phrase!r}\n{'':32} -> {parsed}")
        if expected is None:
            assert parsed is None, f"{label}: parsed a non-constraint"
        else:
            assert parsed is not None, f"{label}: parsed nothing"
            assert (parsed.op, parsed.value, parsed.reference_bound) == expected

    assert parse_value_constraint("\\> 3x109/L").unit_concept_id == 9444
    two = parse_value_constraints("Thyroid stimulating hormone (TSH) \\>1.2 ULN or \\<0.8 LLN;")
    print(f"{'two constraints on one line':32} -> {two}")
    assert [(c.op, c.value, c.reference_bound) for c in two] == [
        ("gt", 1.2, "uln"),
        ("lt", 0.8, "lln"),
    ]
    print("\nself-check ok")


if __name__ == "__main__":
    import sys

    if "--verify-db" in sys.argv:
        issues = verify_unit_table_against_database()
        print("\n".join(issues) if issues else "unit table matches the vocabulary")
    else:
        demo()
