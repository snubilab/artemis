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

# `criterion_refusal` is a pure constants module with no I/O and no imports of its
# own, so importing it here keeps this module unit-testable without a database. The
# refusal below lives beside the unit resolution it reasons about rather than in
# `circe_lint`, whose stated contract is "pure lint functions over a CIRCE cohort
# expression dict" -- this one is handed a ValueConstraint, not an expression.
from src.utils.criterion_refusal import REFUSAL_UNSTATED_UNIT_BOUND, CriterionRefused

ReferenceBound = Literal["absolute", "uln", "lln"]

# Circe accepts these operator tokens verbatim; the IR Literal already matches.
# "bt" is an inclusive range and is the only one that reads a SECOND number: Circe's
# NumericRange carries it as `Extent`, alongside `Value` as the low bound.
_CIRCE_OPS = frozenset({"gt", "gte", "lt", "lte", "eq", "bt"})

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
    8647: ("/uL", "per microliter"),
    8713: ("g/dL", "gram per deciliter"),
    8723: ("mg/g", "milligram per gram"),
    8725: ("ng/L", "nanogram per liter"),
    8749: ("umol/L", "micromole per liter"),
    8753: ("mmol/L", "millimole per liter"),
    8785: ("/mm3", "per cubic millimeter"),
    8795: ("mL/min", "milliliter per minute"),
    8838: ("ug/mg", "microgram per milligram"),
    8840: ("mg/dL", "milligram per deciliter"),
    8842: ("ng/mL", "nanogram per milliliter"),
    8845: ("pg/mL", "picogram per milliliter"),
    8848: ("10*3/uL", "thousand per microliter"),
    8876: ("mm[Hg]", "millimeter mercury column"),
    8961: ("10*3/mm3", "thousand per cubic millimeter"),
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


def _unit_label(concept_id: int) -> str:
    """``"mg/g (milligram per gram)"`` -- one home for how a unit is named to a human."""
    code, name = _UNIT_CONCEPTS[concept_id]
    return f"{code} ({name})"


# Standard unit concept -> the DEPRECATED UCUM spellings of the SAME unit.
#
# Circe emits `AND unit_concept_id IN (...)`, an AND with no fallback, so a unit the
# CDM's ETL wrote under an older code zeroes the criterion silently. EMPA-REG exclusion
# 8 and CAROLINA inclusion 25 both declare 720870 over eGFR and matched 0 rows in every
# CDM checked; the three delivery sites carry 13,845 eGFR rows between them (ajou 4,266,
# donga 2,331, keimyung 7,248) and every one of them is 9117, the concept 720870
# REPLACED on 2022-04-07. The emitted filter excluded exactly the rows it selected for.
#
# Derived from the vocabulary, never authored. Each row is a `Maps to` edge into the
# standard concept whose source is a UCUM Unit concept the vocabulary marks INVALID:
#
#   SELECT cr.concept_id_2, c.concept_id, c.concept_code, c.concept_name, c.invalid_reason
#     FROM {CDM_SCHEMA}.concept_relationship cr
#     JOIN {CDM_SCHEMA}.concept c ON c.concept_id = cr.concept_id_1
#    WHERE cr.relationship_id = 'Maps to' AND cr.invalid_reason IS NULL
#      AND cr.concept_id_2 = ANY(<_UNIT_CONCEPTS keys>) AND cr.concept_id_1 <> cr.concept_id_2
#      AND c.vocabulary_id = 'UCUM' AND c.domain_id = 'Unit' AND c.invalid_reason IS NOT NULL
#
# run 2026-09-11 against `synthea23m` (vocabulary shared with `omop_vocab`). It returns
# exactly the three rows below across all 27 units, which is why this is a derivation
# rather than a maintenance burden -- `verify_unit_table_against_database` re-runs it.
#
# The 'UCUM + invalid' filter is the load-bearing narrowing, not decoration. Dropping it
# admits 51 further `Maps to` sources, nearly all SNOMED, including 25 distinct concepts
# that map to 8554 ("Percentage energy intake from fat", "Percentage oxyhemoglobin", ...).
# Those are different QUANTITIES that happen to normalise to percent; adding them would
# widen a filter rather than restate it, which is the opposite of the defect being fixed.
#
# What this deliberately does NOT fix: a site whose ETL left `unit_concept_id = 0`.
# 8876 `mm[Hg]` has no deprecated predecessor and matches 0 systolic-pressure rows at
# all three sites because their rows carry 0. That is a site ETL gap with no vocabulary
# answer, and stretching this table to cover it would mean guessing. It is reported
# instead -- see `scripts/audit_declared_units.py`.
#
# The 8848/8961 rows came in with those concepts and are the same derivation re-run on
# 2026-09-12 against `synthea23m`. Their concept_names read wrong and are copied
# verbatim anyway: the vocabulary parsed the lab spelling "K/uL" as Kelvin per
# microlitre and still maps it onto "thousand per microlitre", which is what a CDM
# writing K/uL actually means. Correcting the name here would put this table's copy out
# of step with `verify_unit_table_against_database`, which compares it to the row.
_UNIT_DEPRECATED_FORMS: dict[int, tuple[tuple[int, str, str], ...]] = {
    8848: ((8792, "K/uL", "Kelvin per microliter"),),
    8961: (
        (8903, "K/mm3", "Kelvin per cubic millimeter"),
        (8978, "10*3/mm4", "Thousand per cubic millimeter4"),
    ),
    9448: ((8528, "y", "year"),),
    720870: (
        (9117, "mL/min/1.73.m2", "milliliter per minute per 1.73 square meter"),
        (9062, "mL/min/{1.73}m", "Milliliter per minute per 1.73 meter"),
    ),
}

# Standard unit concepts that are the SAME quantity at the SAME scale, so one filter
# must accept every member. A DIFFERENT axis from _UNIT_DEPRECATED_FORMS above, which is
# why it is a sibling table rather than more rows in that one: there every added
# spelling is a UCUM concept the vocabulary marks INVALID (its derivation query filters
# `invalid_reason IS NOT NULL`, and `test_should_only_ever_add_deprecated_ucum_units_of
# _the_same_concept` asserts no member is live). Here every member is a LIVE standard
# concept. Folding the two would break both the query and the guard.
#
# The same AND-with-no-fallback that motivated the deprecated-forms table motivates this
# one: a criterion declaring 8838 `ug/mg` matches 0 rows in a CDM whose ETL wrote 8723
# `mg/g`, and the two are the same number -- 1 mg/g == 1 ug/mg. CAROLINA inclusion 26
# ("Urinary albumin creatinine ratio >= 30 ug/mg") is the corpus case.
#
# Equal scale is the WHOLE admission test. A pair one thousand apart is the ARISTOTLE
# platelet error: gold writes `100` thousands/uL, the protocol PDF writes `100,000/mm3`,
# and a filter accepting both takes the cohort to 0. `_UNIT_NEVER_SAME_SCALE` below
# names those pairs and `_build_same_scale_index` refuses a table that merges one --
# including through a third unit, which is how such a merge actually arrives.
#
# No conversion lives here and none may: these rows restate one quantity in two
# spellings, they never rescale a value. A bound that needs rescaling stays refused.
_UNIT_SAME_SCALE: tuple[frozenset[int], ...] = (
    frozenset({8838, 8723}),  # ug/mg == mg/g          (1e-3 g/g both)
    frozenset({8848, 8961}),  # 10*3/uL == 10*3/mm3    (1 uL == 1 mm3)
    frozenset({8785, 8647}),  # /mm3 == /uL            (1 uL == 1 mm3)
)

# Pairs that are the same DIMENSION and a factor of 1000 apart. Listing them is the
# point: "these two are obviously the same thing" is exactly the reasoning that produced
# the ARISTOTLE platelet error, and prose asking a future reader not to do it is not a
# gate. `_build_same_scale_index` raises on any of these appearing in one class.
_UNIT_NEVER_SAME_SCALE: tuple[frozenset[int], ...] = (
    frozenset({8785, 8848}),  # /mm3      vs 10*3/uL
    frozenset({8785, 8961}),  # /mm3      vs 10*3/mm3
    frozenset({8647, 8848}),  # /uL       vs 10*3/uL
    frozenset({8647, 8961}),  # /uL       vs 10*3/mm3
)


def _build_same_scale_index(
    classes: tuple[frozenset[int], ...] = _UNIT_SAME_SCALE,
    forbidden: tuple[frozenset[int], ...] = _UNIT_NEVER_SAME_SCALE,
) -> dict[int, tuple[int, ...]]:
    """concept_id -> the OTHER live units one filter must accept alongside it.

    Merges overlapping classes first, so the check below runs against what a filter
    would really emit rather than against the rows as written. Two edges that each look
    safe can compose into one that is not: ``/mm3 == /uL`` and ``/uL == 10*3/uL`` are a
    single addition apart and together put 8785 in the same class as 8848.

    :param classes: the same-scale equivalence classes to index.
    :param forbidden: pairs that must never share a class.
    :raises ValueError: when a merged class holds a forbidden pair, or a member is not
        in :data:`_UNIT_CONCEPTS`.
    """
    merged: list[set[int]] = []
    for members in classes:
        for concept_id in members:
            if concept_id not in _UNIT_CONCEPTS:
                raise ValueError(
                    f"same-scale class {sorted(members)} names {concept_id}, which is "
                    f"not in _UNIT_CONCEPTS; record the concept there first"
                )
        overlapping = [group for group in merged if group & members]
        combined = set(members).union(*overlapping)
        merged = [group for group in merged if group not in overlapping] + [combined]

    for group in merged:
        for pair in forbidden:
            if pair <= group:
                low, high = sorted(pair)
                raise ValueError(
                    f"same-scale class {sorted(group)} merges {_unit_label(low)} and "
                    f"{_unit_label(high)}, which are the same dimension a factor of "
                    f"1000 apart. Circe ANDs `unit_concept_id IN (...)`, so accepting "
                    f"both makes a threshold mean two things at once -- the ARISTOTLE "
                    f"platelet error, where gold's `100` thousands/uL and the "
                    f"protocol's `100,000/mm3` are the same bound at two scales. "
                    f"Rescaling the VALUE is the only correct fix and this module does "
                    f"not do it; leave the criterion refused instead"
                )

    index: dict[int, tuple[int, ...]] = {}
    for group in merged:
        for concept_id in group:
            index[concept_id] = tuple(sorted(group - {concept_id}))
    return index


#: Built at import so a forbidden merge fails here, not in a delivered file.
_UNIT_SAME_SCALE_INDEX = _build_same_scale_index()

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
    "/uL": 8647,
    "/μL": 8647,  # NFKC folds the U+00B5 micro sign onto this U+03BC mu
    "cells/uL": 8647,
    "cells/μL": 8647,
    "mL/min": 8795,
    "mg/g": 8723,
    "ug/mg": 8838,
    "μg/mg": 8838,
    "mcg/mg": 8838,
    "mg/dL": 8840,
    "ng/mL": 8842,
    "pg/mL": 8845,
    "mmHg": 8876,
    "mm[Hg]": 8876,
    "IU/mL": 8985,
    "[iU]/mL": 8985,
    # The 10*3 family, spelled the four ways the 10*9 family below already is, plus the
    # mu rendering of microlitre. `synthea_cdm` writes 8848 on all 41,114 of its platelet
    # rows, so this is the spelling a CDM is most likely to carry for a count.
    "10*3/uL": 8848,
    "10^3/uL": 8848,
    "x10^3/uL": 8848,
    "x10*3/uL": 8848,
    "10*3/μL": 8848,
    "10^3/μL": 8848,
    "10*3/mm3": 8961,
    "10^3/mm3": 8961,
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


def _unit_item(concept_id: int, concept_code: str, concept_name: str) -> dict[str, Any]:
    """One Circe ``Unit`` array element, in the shape gold writes."""
    return {
        "CONCEPT_CODE": concept_code,
        "CONCEPT_ID": concept_id,
        "CONCEPT_NAME": concept_name,
        "DOMAIN_ID": "Unit",
        "INVALID_REASON_CAPTION": "Unknown",
        "STANDARD_CONCEPT_CAPTION": "Unknown",
        "VOCABULARY_ID": "UCUM",
    }


def unit_concept(concept_id: int) -> dict[str, Any]:
    """Full concept object for a Circe ``Unit`` array element, matching gold shape."""
    return _unit_item(concept_id, *_UNIT_CONCEPTS[concept_id])


def unit_concepts(concept_id: int) -> list[dict[str, Any]]:
    """Every UCUM concept a ``Unit`` filter must accept for ``concept_id``.

    The standard concept FIRST -- callers and tests read ``Unit[0]`` as "the unit this
    bound is written in", and :func:`absolute_unit_concept_id` must keep agreeing with
    it. After it, two kinds of restatement of the SAME quantity, and nothing else:

    * the deprecated UCUM spellings of that unit (:data:`_UNIT_DEPRECATED_FORMS`);
    * the live units at the SAME SCALE (:data:`_UNIT_SAME_SCALE`), each with its own
      deprecated spellings, so an equivalence never silently loses one.

    Restating one quantity, never widening to a second. Circe ANDs the filter, so a CDM
    that wrote any other spelling of the same quantity matched nothing at all: 720870
    replaced 9117 in 2022 and all 13,845 eGFR rows across the three delivery sites still
    carry 9117, and a criterion declaring 8838 ``ug/mg`` matches no row in a CDM whose
    ETL wrote the equally-correct 8723 ``mg/g``.

    What is NOT here is a scale change. Every id this returns denotes the same number as
    ``concept_id``; a bound needing a value rescaled stays refused -- see
    :data:`_UNIT_NEVER_SAME_SCALE`.
    """
    items: list[dict[str, Any]] = []
    for cid in (concept_id, *_UNIT_SAME_SCALE_INDEX.get(concept_id, ())):
        items.append(_unit_item(cid, *_UNIT_CONCEPTS[cid]))
        items.extend(
            _unit_item(deprecated_id, code, name)
            for deprecated_id, code, name in _UNIT_DEPRECATED_FORMS.get(cid, ())
        )
    return items


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


def absolute_unit_concept_id(vc: Any) -> int | None:
    """The UCUM concept an absolute bound is written in, or None if it does not resolve.

    One derivation, two readers: the ``Unit`` element
    :func:`build_measurement_value_filter` emits, and the analyte check
    :func:`resolve_group_member_constraint` runs before handing an absolute bound down
    to a group member. Deriving it twice is how the emitted filter and the check that
    approved it drift into disagreeing about what unit the bound is even in.

    Reads the explicit ``unit_concept_id`` first and falls back to
    :func:`normalize_unit` over what is left of ``unit_text`` once
    :func:`resolve_reference_bound` has taken any ULN/LLN wording out of it. Returns
    None for a spelling outside :data:`_UNIT_CONCEPTS` -- never a nearest match, per
    ADR-031 D5.
    """
    _, unit_text = resolve_reference_bound(vc)
    concept_id = _field(vc, "unit_concept_id", "unitConceptId") or normalize_unit(unit_text)
    return concept_id if concept_id in _UNIT_CONCEPTS else None


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

    ``op == "bt"`` adds ``Extent`` to whichever operand the table selects: Circe's
    ``NumericRange`` spells an inclusive range ``{Value: lo, Extent: hi, Op: "bt"}``,
    and the low bound stays in ``Value`` so every other op keeps the shape it had.
    A ``bt`` reaching here without an upper bound returns ``{}`` for the same reason
    a missing value does -- half a range is not a narrower range, it is a different one.

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

    operand: dict[str, Any] = {"Value": float(value), "Op": circe_op}
    if circe_op == "bt":
        extent = _field(vc, "value_high", "valueHigh")
        if extent is None:
            return {}
        operand["Extent"] = float(extent)
    if bound == "uln":
        return {"RangeHighRatio": operand}
    if bound == "lln":
        return {"RangeLowRatio": operand}

    fragment: dict[str, Any] = {"ValueAsNumber": operand}
    concept_id = absolute_unit_concept_id(vc)
    if concept_id is not None:
        # Sibling of ValueAsNumber, not a key inside it — Circe ignores it nested.
        # ...and the whole equivalence class, not just the standard concept: Circe ANDs
        # `unit_concept_id IN (...)`, so a site whose ETL still writes the retired
        # spelling matched nothing. See `_UNIT_DEPRECATED_FORMS`.
        fragment["Unit"] = unit_concepts(concept_id)
    return fragment


def unstated_absolute_unit(vc: Any) -> str | None:
    """The unit this absolute bound DECLARED and that did not resolve, or None.

    The predicate half of the gate, deliberately shaped like
    :func:`~src.utils.circe_lint.unreadable_value_attributes`: it answers a question
    and raises nothing, so the delivery-gate reader and the emission-time refusal
    cannot drift apart.

    The defect it names. ``build_measurement_value_filter`` emits ``Unit`` only when
    :func:`absolute_unit_concept_id` resolves, and drops it SILENTLY when it does not --
    which is right, because guessing a nearest unit writes a filter that matches nothing
    (ADR-031 D5). What was never decided is what happens to the NUMBER. It shipped
    alone, and a number alone is not a narrower bound; it is a claim in an unknown unit,
    compared by Circe against whatever scale the CDM stores.

    Measured on ARISTOTLE exclusion 23. ``"Platelet count <= 100,000/ mm"`` -- the
    superscript of ``/mm3`` lost upstream -- emitted
    ``ValueAsNumber {Value: 100000.0, Op: "lte"}`` with no ``Unit``. Against
    ``postgres.synthea_cdm`` (7,834,306 measurements, units populated, NOT generated
    from ``data/gold/``) all 41,114 platelet rows satisfy it: concept 3024929, unit 8848
    ``10*3/uL``, min 99.0 / median 287.3 / max 450.0. Inside an ABSENCE exclusion that
    removed every patient who has ever had the lab drawn. Gold's ``<= 100`` matches 75
    of the same rows (0.18%), the thrombocytopenic population.

    Three shapes are deliberately NOT named, because nothing was dropped from them:

    * a bound that declared no unit at all (``unitText`` empty or absent). LEADER's
      ``HbA1c >= 7.0`` and PLATO's ST-segment criteria are this, and 12 of the 22 bare
      bounds in the 2026-09-13 store are. Whether an undeclared unit is safe is a real
      question and a DIFFERENT one; answering it here would fold two decisions into one
      predicate and make the blast radius unreadable.
    * a reference-relative bound. "3 x ULN" emits ``RangeHighRatio``, which Circe
      divides by the row's own ``range_high`` -- unit-free by construction.
    * a constraint that emits no ``ValueAsNumber`` at all (a ``bt`` missing its upper
      bound, a malformed op). There is no bound to refuse.

    :param vc: a ``ValueConstraint`` model or a raw camelCase IR dict.
    :returns: the declared unit spelling, verbatim as stored, or None when the bound is
        fine. The spelling is returned rather than a bool so the refusal can print the
        thing a human has to go and fix.
    """
    fragment = build_measurement_value_filter(vc)
    if "ValueAsNumber" not in fragment or "Unit" in fragment:
        return None
    _, residual = resolve_reference_bound(vc)
    return residual if (residual or "").strip() else None


def refuse_unstated_unit_bound(vc: Any, label: str) -> None:
    """Raise when an absolute bound is about to be emitted in an unstated unit.

    The emission-time half, and the same choice
    :func:`~src.utils.circe_lint.refuse_unreadable_value_filter` makes: raising rather
    than emitting leaves the caller to record the criterion under its own refusal reason
    and drop it, so the claim is honestly absent instead of present and wrong.

    Converting to the CDM's conventional unit is the alternative, and it was rejected on
    both halves. It needs a per-analyte conversion table -- a clinical decision with
    nowhere auditable to live, and one this module already refuses to grow for the
    related question (see :data:`_ANALYTE_CONVENTIONAL_UNITS`, which records units and
    deliberately records no factors). And on the motivating criterion it buys nothing:
    ``/mm3`` resolves to 8785, and ``Unit [8785]`` matches 0 of the same 41,114
    ``synthea_cdm`` platelet rows, because that CDM writes 8848 ``10*3/uL``.

    :param vc: the constraint about to be built into a value filter.
    :param label: the criterion's seed text, for the recorded reason.
    :raises CriterionRefused: carrying
        :data:`~src.utils.criterion_refusal.REFUSAL_UNSTATED_UNIT_BOUND`.
    """
    unit_text = unstated_absolute_unit(vc)
    if unit_text is None:
        return
    value = _field(vc, "value", "Value")
    op = _field(vc, "op", "Op")
    raise CriterionRefused(
        f"criterion bound in an unstated unit: {label!r} carries {op} {value} "
        f"{unit_text!r}, and {unit_text!r} resolves to no UCUM unit concept, so the "
        f"bound would be emitted as a bare number and compared against whatever scale "
        f"the CDM stores. Fix the extracted unit spelling, or express the threshold in "
        f"a unit this pipeline resolves",
        code=REFUSAL_UNSTATED_UNIT_BOUND,
        detail=f"unresolved unit {unit_text!r} on {op} {value}",
    )


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
    had none, and handing it down would have been unsafe. ``refusal_explanation``
    is the sentence a human needs to act on that refusal -- which analyte, which
    unit it is reported in, which unit the label wrote. It is deliberately NOT the
    ``refusal_reason``: consumers classify on the reason, which is a closed wire
    constant, and read the explanation only to render it.
    """

    constraint: Any | None
    propagated: bool
    refusal_reason: str | None
    refusal_explanation: str | None = None


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


# --------------------------------------------------------------------------
# Which analyte is reported in which unit
# --------------------------------------------------------------------------

# An absolute bound is analyte-specific, but that does not make it useless to every
# member of a labelled group -- only to the members measured in another unit.
# CAROLINA's exclusion group writes "> 240 mg/dL" once, over Hemoglobin A1c, Fasting
# Plasma Glucose and Random Plasma Glucose. It is a correct threshold for the two
# glucoses and meaningless for HbA1c, which is reported in % (or IFCC mmol/mol).
# Refusing all three loses two real filters; propagating to all three writes a
# MeasurementOccurrence over HbA1c that matches zero rows. Which of the two a given
# member is, is a matter of record, so it is recorded here.
#
# Values are concept_ids from `_UNIT_CONCEPTS` above, never unit spellings: the unit
# vocabulary already has one home, and a second copy of "mg/dL" here would be a second
# place for it to be wrong. An analyte whose conventional unit has no concept in that
# table therefore cannot be fully expressed -- HbA1c's IFCC mmol/mol has no entry, so a
# bound written in it refuses instead of propagating on a guessed concept_id. That is
# the safe direction: this table can only ever be too small, never too permissive.
#
# Each row is (spellings, conventional units). The FIRST spelling names the analyte in
# a refusal message. A row is added only for an analyte whose conventional units are a
# matter of record; an analyte absent from the table refuses and says so, because
# guessing here writes a filter that silently matches nothing.
_ANALYTE_CONVENTIONAL_UNITS: tuple[tuple[tuple[str, ...], frozenset[int]], ...] = (
    # NGSP percent. "hemoglobin a1c" and "haemoglobin a1c" are listed in full even
    # though "a1c" alone would match them, because the plain "hemoglobin" row below
    # is a LONGER match than "a1c" and would otherwise win the tie -- see
    # `_match_analyte`, which resolves by longest key.
    (
        (
            "hemoglobin a1c",
            "haemoglobin a1c",
            "hba1c",
            "hb a1c",
            "a1c",
            "glycated hemoglobin",
            "glycated haemoglobin",
            "glycosylated hemoglobin",
            "glycosylated haemoglobin",
        ),
        frozenset({8554}),
    ),
    (("glucose",), frozenset({8840, 8753})),
    (("hemoglobin", "haemoglobin"), frozenset({8713, 8636})),
    (("platelet", "platelets", "thrombocyte"), frozenset({9444, 8785})),
    # "creatinine clearance" is a longer key than "creatinine" and resolves to the
    # clearance row below, which is what stops a mL/min bound reaching serum creatinine.
    (("creatinine",), frozenset({8840, 8749})),
    (
        (
            "estimated glomerular filtration rate",
            "glomerular filtration rate",
            "egfr",
            "creatinine clearance",
        ),
        frozenset({720870, 8795}),
    ),
    (("alanine aminotransferase", "alt", "sgpt"), frozenset({8645})),
    (("aspartate aminotransferase", "ast", "sgot"), frozenset({8645})),
    (("alkaline phosphatase", "alp"), frozenset({8645})),
    (("gamma glutamyl transferase", "ggt", "gamma gt"), frozenset({8645})),
    (("bilirubin",), frozenset({8840, 8749})),
    (("cholesterol", "ldl", "hdl"), frozenset({8840, 8753})),
    (("triglyceride", "triglycerides"), frozenset({8840, 8753})),
    (("blood pressure",), frozenset({8876})),
    (("body mass index", "bmi"), frozenset({9531})),
    (("troponin",), frozenset({8842, 8845, 8725})),
)

#: spelling -> (canonical analyte name, its conventional unit concept_ids).
_ANALYTE_INDEX: dict[str, tuple[str, frozenset[int]]] = {
    spelling: (spellings[0], units)
    for spellings, units in _ANALYTE_CONVENTIONAL_UNITS
    for spelling in spellings
}

_ANALYTE_PUNCTUATION_RE = re.compile(r"[^a-z0-9]+")


def _normalize_analyte(text: str) -> str:
    """Reduce a criterion's analyte text to space-separated lowercase tokens.

    "Elevated Alanine aminotransferase (ALT)" and "Hemoglobin A1c" have to reduce to
    something a fixed key can be found inside, without the parenthesis, the case or
    the hyphen deciding the answer.
    """
    folded = unicodedata.normalize("NFKC", text).lower()
    return " ".join(_ANALYTE_PUNCTUATION_RE.sub(" ", folded).split())


class AnalyteUnitCheck(NamedTuple):
    """Whether a bound in one unit may be applied to one analyte, and why not."""

    compatible: bool
    explanation: str


def _unit_labels(concept_ids: frozenset[int]) -> str:
    return " or ".join(_unit_label(cid) for cid in sorted(concept_ids))


def _match_analyte(analyte_text: str) -> tuple[str, frozenset[int]] | None:
    """The table row this text names, or None when the table cannot settle it.

    Keys are matched on whole tokens, so "fasting" never matches "ast" and "salt"
    never matches "alt". The longest matching key wins, which is what makes
    "Hemoglobin A1c" resolve to HbA1c rather than to haemoglobin.

    Returns None -- meaning refuse, not guess -- in two cases: nothing matched, or
    two matched keys name DIFFERENT analytes and neither key contains the other. The
    second is a text like "haemoglobin and platelet count", which names two analytes
    with two different units and cannot be filtered by one bound. A shorter key
    contained in the winner ("hemoglobin" inside "hemoglobin a1c") is a refinement of
    the same name, not a second analyte, and does not block the match.
    """
    normalized = _normalize_analyte(analyte_text)
    if not normalized:
        return None
    padded = f" {normalized} "
    matched = [key for key in _ANALYTE_INDEX if f" {key} " in padded]
    if not matched:
        return None
    winner = max(matched, key=len)
    name, units = _ANALYTE_INDEX[winner]
    for key in matched:
        other_name, _ = _ANALYTE_INDEX[key]
        if other_name != name and key not in winner:
            return None
    return name, units


def check_analyte_unit(analyte_text: str | None, unit_concept_id: int | None) -> AnalyteUnitCheck:
    """May a bound written in ``unit_concept_id`` be applied to ``analyte_text``?

    Compatible only on a positive answer from :data:`_ANALYTE_CONVENTIONAL_UNITS`.
    Every other outcome -- no analyte text, an unresolvable unit, an analyte the table
    does not carry, an analyte that names two things -- is incompatible WITH ITS
    REASON, never a fall-through to "probably fine". A wrong propagation writes a value
    filter that matches no row at all, and inside an ABSENCE exclusion a rule matching
    no row silently stops excluding anybody, which is the failure this whole module
    exists to prevent.

    :param analyte_text: the member criterion's own text, e.g. "Hemoglobin A1c".
    :param unit_concept_id: the bound's unit, from :func:`absolute_unit_concept_id`.
    :returns: the verdict plus a sentence naming what could not be reconciled.
    """
    if unit_concept_id is None:
        return AnalyteUnitCheck(
            False,
            "the group label's bound resolves to no UCUM unit, so there is nothing to "
            "check the member's analyte against",
        )
    if not (analyte_text or "").strip():
        return AnalyteUnitCheck(
            False, "the member carries no analyte text to check the label's unit against"
        )
    match = _match_analyte(analyte_text)
    if match is None:
        return AnalyteUnitCheck(
            False,
            f"{analyte_text.strip()!r} is not in the analyte/unit table, so whether it "
            f"is reported in {_unit_label(unit_concept_id)} is unknown; add it to "
            f"_ANALYTE_CONVENTIONAL_UNITS rather than assuming",
        )
    name, units = match
    if unit_concept_id in units:
        return AnalyteUnitCheck(True, "")
    return AnalyteUnitCheck(
        False,
        f"{analyte_text.strip()!r} is {name}, which is reported in "
        f"{_unit_labels(units)}, not in {_unit_label(unit_concept_id)}",
    )


def resolve_group_member_constraint(
    parent_vc: Any, member_vc: Any, *, member_analyte: str | None = None
) -> GroupConstraintResolution:
    """Decide what one member of a labelled criteria group is measured against.

    Both Circe builders call this and nothing else decides it:
    ``TTEService._criteria_from_ir`` (store rows) and
    ``CohortAssembler._build_inclusion_rule`` (Circe directly). Each previously
    read only the member's own constraint, so a threshold written once on the
    group label was dropped by both -- and the label row is unconditionally
    refused (``isGroupLabel``), so nothing downstream still held the number.

    A reference-relative bound is unit-free and reaches every member: "3 times the
    upper limit of normal" is meaningful for ALT, AST and ALP alike.

    An absolute bound reaches the members measured in ITS unit and no others.
    "> 240 mg/dL" is a correct threshold for Fasting Plasma Glucose and for Random
    Plasma Glucose, and meaningless for HbA1c, which shares their group and is
    reported in % or mmol/mol. Copying it onto HbA1c builds a MeasurementOccurrence
    matching zero rows; inside an ABSENCE exclusion that turns a visible
    over-exclusion into a silent no-op, and ``refuse_domain_contradiction`` cannot
    see it because both sides are Measurement. Refusing all three instead was the
    safe answer while nothing could tell them apart -- :func:`check_analyte_unit`
    now can, from a table, so the two glucoses are filtered and HbA1c alone refuses.

    The blanket refusal remains the fallback for everything the table cannot settle,
    including a caller that passes no ``member_analyte`` at all. This narrows the
    refusal; it never widens what is emitted.

    A label whose number is a group CARDINALITY -- "≥2 of the following:" -- is neither
    of those. It is not a bound at all, so no member is measured against it and no
    member is stranded by it; see :func:`is_item_count`. The parser stopped producing
    these, and this branch is what keeps a store already holding one from losing its
    members: PLATO's group ``8e787307`` shipped on 2026-09-10 with all four of
    Hypertension / Diabetes Mellitus / Current smoker / Obesity refused.

    A member that carries its own constraint always keeps it: SPEC-INFRA-007
    REQ-004/REQ-005 made the decomposer ground each sub-item's threshold in its
    own source text, and this must not overwrite that answer.

    :param parent_vc: the group label's constraint, or None.
    :param member_vc: the member's own constraint, or None.
    :param member_analyte: the member's own analyte text ("Hemoglobin A1c"). Omitted,
        every absolute bound refuses -- the pre-analyte behaviour.
    :returns: the member's effective constraint plus why.
    """
    if member_vc is not None:
        return GroupConstraintResolution(member_vc, False, None)
    if parent_vc is None:
        return GroupConstraintResolution(None, False, None)
    # A count of the group's own members is not a bound on any of them, so there is
    # nothing to hand down and nothing was stranded: the member emits exactly as it
    # would under a label carrying no constraint at all. Not a refusal -- refusing here
    # is what cost PLATO all four of its risk factors.
    if is_item_count(parent_vc):
        return GroupConstraintResolution(None, False, None)
    if is_reference_relative(parent_vc):
        return GroupConstraintResolution(parent_vc, True, None)
    check = check_analyte_unit(member_analyte, absolute_unit_concept_id(parent_vc))
    if check.compatible:
        return GroupConstraintResolution(parent_vc, True, None)
    return GroupConstraintResolution(
        None, False, STRANDED_GROUP_CONSTRAINT_REASON, check.explanation
    )


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
# The other way a time quantity fails to be a measured value: it is the SPAN the
# criterion is about, anchored to nothing. "duration > 10 years", "≥ 7 consecutive
# days", "life expectancy ≤ 1 year". `_RELATIVE_TIME_ANCHOR_RE` above catches the
# index-relative window; these catch the span with no index at all. Age is
# deliberately not here — "age >= 18 years" is a patient attribute and still parses.
_DURATION_MARKER_RE = re.compile(
    r"\bduration\b|\bconsecutive\b|\blife\s+expectancy\b|\blasting\b|\blong[- ]?standing\b",
    re.IGNORECASE,
)

# A percentage describing a LESION rather than a lab result. No OMOP table carries a
# column for it: ProcedureOccurrence and ConditionOccurrence read no value at all, so
# ">50% stenosis" written as ValueAsNumber is dropped by Circe and the rule matches
# every occurrence of its concept set. Keyed on the anatomy word rather than on "%",
# because "%" is also HbA1c's unit and LVEF's — both of which are measured and stay.
_ANATOMIC_SEVERITY_RE = re.compile(
    r"\bstenos[ei]s\b|\bstenotic\b|\bnarrowing\b|\bocclusi(?:on|ve)\b|"
    r"\bluminal\b|\bobstruction\b",
    re.IGNORECASE,
)
_PERCENT_UNITS = frozenset({"%", "percent", "pct"})

# An amount per unit TIME or per unit BODY MASS is a prescription, not a result.
# drug_exposure has no dose-strength column -- the one value Circe reads there is
# Quantity, which is units DISPENSED -- so "aspirin > 165 mg/day" has no correct home.
# A lab reports a concentration (mg/dL, ng/L) or a mass ratio (μg/mg), which do not
# match this and are untouched.
_DOSE_RATE_UNIT_RE = re.compile(
    r"^(?:mg|g|mcg|µg|μg|ng|u|iu|ml|l)\s*/\s*(?:day|d|kg|hr|h|hour|min|m2|m²)\b",
    re.IGNORECASE,
)
# ...gated on the phrase naming a prescription, because a 24-hour collection reports a
# real excretion rate in the same units ("proteinuria > 300 mg/day") and must survive.
_DOSE_CONTEXT_RE = re.compile(
    r"\bdose\b|\bdosage\b|\bdosing\b|\btreatment\s+with\b|\btherapy\s+with\b|"
    r"\btreated\s+with\b|\breceiving\b|\btaking\b|\bdaily\b",
    re.IGNORECASE,
)

# A number that counts the items in a LIST is not a quantity measured on any one of
# them. PLATO's inclusion group 8e787307 is labelled "≥2 of the following:" over
# Hypertension / Diabetes Mellitus / Current smoker / Obesity -- a group CARDINALITY,
# "at least 2 of these four hold". `_resolve_unit` hands back "of the following:"
# because no part of that tail names a unit; it is the rest of the English phrase. The
# label then carried an absolute bound, `resolve_group_member_constraint` could match
# none of the four members to a unit that is not one, and PLATO's whole "≥2 risk
# factors" criterion left the 2026-09-10 delivery as four `stranded-group-threshold`
# rows. On 2026-09-09, before the label carried a bound, `Diabetes Mellitus` emitted.
#
# The signal is the unit slot on its own: a partitive "of" opens a reference to a SET
# OF ITEMS, and no unit of measure begins with it. Unlike "%" (HbA1c's unit as well as
# a stenosis figure) and "mg/day" (a real excretion rate as well as a dose), this one
# is not ambiguous, so it takes no phrase-level gate -- a context test that cannot
# change the answer is only a second place to be wrong.
#
# Measured over the 1,106 distinct criterion lines in `tmp/tte_cold6_20260908/
# studies.json` and `output/site_gap/2026-09-10/store/studies.json`: 143 -> 137
# annotations, 6 dropped, 0 gained, every drop a count of list members. The ages
# standing beside four of them ("Age ≥60 y and ≥1 of the following criteria:")
# survive, because `_PHRASE_SPLIT_RE` leaves each number with its own tail.
_ITEM_COUNT_UNIT_RE = re.compile(r"^of\b", re.IGNORECASE)

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


def _normalize_unit_token(text: str) -> str:
    token = text.strip("().,;:'\u2019\u201d\"").lower().rstrip(".")
    return token[:-1] if token.endswith("s") else token


def _is_temporal(unit_text: str | None, phrase: str) -> bool:
    """True when the quantity is a time span rather than a measured value (D8).

    Two ways a span reaches here. It is a WINDOW when something anchors it to the index
    event ("within 3 months"), and it is a DURATION when the phrase names it as one
    ("duration > 10 years", "≥ 7 consecutive days") with no anchor at all. Both are
    facts about time; neither is a number a lab reported, and neither has a column.

    The unit is read from the first two whitespace tokens rather than from the whole
    tail, because `_resolve_unit` hands back everything it could not resolve: CARMELINA's
    "Treatment (=> 7 consecutive days) with GLP-1 receptor agonists" arrives with
    ``unit_text`` = ``"consecutive days) with GLP-1 receptor agonists"`` and the time word
    is the second token. Scanning ALL tokens instead would reach the "min" of a
    space-separated "ml / min" and start refusing eGFR bounds on any phrase carrying
    "within" -- the failure is silent and in the direction that loses real thresholds,
    so the scan is bounded to where a unit can actually be.
    """
    if not unit_text:
        return False
    head = _normalize_unit_token("".join(unit_text.split()))
    if head in _WINDOW_UNITS:
        return True
    leading = [_normalize_unit_token(t) for t in unit_text.split()[:2]]
    # A year is an age until something anchors it to the index event or names it a span.
    names_time = head in _TIME_UNITS or any(t in _TIME_UNITS for t in leading)
    if not names_time:
        return False
    return bool(
        _RELATIVE_TIME_ANCHOR_RE.search(phrase) or _DURATION_MARKER_RE.search(phrase)
    )


def _is_anatomic_severity(unit_text: str | None, phrase: str) -> bool:
    """True for "≥50% stenosis" and its kin -- a lesion figure, not a lab result."""
    if not unit_text:
        return False
    return (
        _normalize_unit_token(unit_text.split()[0]) in _PERCENT_UNITS
        and _ANATOMIC_SEVERITY_RE.search(phrase) is not None
    )


def _is_drug_dose_rate(unit_text: str | None, phrase: str) -> bool:
    """True for "aspirin > 165 mg/day" -- a prescription, not a measured result."""
    if not unit_text:
        return False
    return (
        _DOSE_RATE_UNIT_RE.match(unit_text.strip()) is not None
        and _DOSE_CONTEXT_RE.search(phrase) is not None
    )


def _is_item_count(unit_text: str | None) -> bool:
    """True for ">= 2 of the following" -- how many members hold, not how much of one.

    Takes no phrase, unlike its three siblings: the unit slot settles this one by
    itself (see :data:`_ITEM_COUNT_UNIT_RE`).
    """
    return bool(unit_text) and _ITEM_COUNT_UNIT_RE.match(unit_text.strip()) is not None


def is_item_count(vc: Any) -> bool:
    """True when a constraint already in a store counts members rather than measuring.

    The same predicate :func:`parse_value_constraint` applies, asked of a stored row so
    that :func:`resolve_group_member_constraint` has one home for the question rather
    than two. Every store written before the parser declined this family still carries
    the count -- PLATO's label #38 in `output/site_gap/2026-09-10/store/studies.json` is
    ``{gte 2.0, unitText "of the following:"}`` -- and a re-extraction is not the only
    thing that should stop those deliveries losing four criteria each.
    """
    return _is_item_count(_field(vc, "unit_text", "unitText"))


def _is_unmeasurable(unit_text: str | None, phrase: str) -> bool:
    """True when no OMOP value column could ever hold this quantity.

    The one predicate the two parse paths share, so a family excluded here cannot be
    reintroduced by the other. Every family it names was measured in the six-trial
    delivery of 2026-09-09 as a ``value_constraint`` written onto a criteria type whose
    CDM table reads nothing (`circe_lint.CRITERIA_TYPE_VALUE_ATTRIBUTES`): Circe drops
    the condition silently, and since the emission-time refusal landed the whole
    criterion is dropped instead. Refusing to produce the number is the only place the
    loss can be prevented — the extraction prompt cannot, because Rule 0 tells the model
    to copy this parser's annotation verbatim and Step 8a re-attaches it when the model
    leaves it out.

    The fourth family, the item count, loses its criterion by a second route as well.
    Where it lands on a GROUP LABEL the label is refused anyway, but the bound it now
    appears to carry reaches `resolve_group_member_constraint`, which can match no
    member to a unit that is not a unit and refuses every one of them: PLATO's four
    risk factors, in the 2026-09-10 delivery. Where it lands on a flat criterion the
    first route applies as usual -- the same PLATO count reached the 2026-09-08 store
    on a Condition row named "Preexisting Conditions Count", which ConditionOccurrence
    cannot read.
    """
    return (
        _is_temporal(unit_text, phrase)
        or _is_anatomic_severity(unit_text, phrase)
        or _is_drug_dose_rate(unit_text, phrase)
        or _is_item_count(unit_text)
    )


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
    if _is_unmeasurable(unit_text, text):
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
    if unit_concept_id is None or _is_unmeasurable(unit_text, text):
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
        # ...and a bare percentage re-judged against the WHOLE line, because the split
        # can carry the number away from the word that disqualifies it. CAROLINA's
        # "Documented coronary artery disease (≥ 50% luminal diameter narrowing ... or
        # ≥50% in at least two major coronary arteries in angiogram)" splits on " or ",
        # and the second segment is a bare "≥50% in ... angiogram)" with no anatomy word
        # left in it. Judged on the segment alone it reads like a lab result; judged on
        # the line it is the same stenosis figure stated twice.
        #
        # ONLY the anatomic family gets this widening, and the narrowness is measured,
        # not cautious by default. Applying `_is_unmeasurable` to the whole line dropped
        # PLATO's "≥18 years of age" -- a real age -- because the same CT.gov paragraph
        # elsewhere says "≥10 minutes' duration at rest". Duration and dose phrases carry
        # their own disqualifying word inside the segment that holds the number; only the
        # percentage is left naked by the split.
        and not _is_anatomic_severity(constraint.unit_text, line)
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
    """Compare _UNIT_CONCEPTS and _UNIT_DEPRECATED_FORMS against the live vocabulary.

    The static tables keep normalize_unit a pure function that tests can run
    without Postgres. This is how they are kept honest: run it after a
    vocabulary refresh rather than assuming no drift.

    Both halves are re-DERIVED here rather than spot-checked. The codes and names in
    :data:`_UNIT_CONCEPTS` are compared row by row; :data:`_UNIT_DEPRECATED_FORMS` is
    rebuilt from ``concept_relationship`` by the same query its comment records, and any
    difference in either direction is reported -- a retirement the vocabulary has since
    added is as much a discrepancy as a row that no longer holds, because a MISSING
    deprecated spelling is exactly the silent zero-match this table exists to prevent.
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
            # The derivation the `_UNIT_DEPRECATED_FORMS` comment records, run live.
            cur.execute(
                f"SELECT cr.concept_id_2, c.concept_id, c.concept_code, c.concept_name "
                f"FROM {settings.CDM_SCHEMA}.concept_relationship cr "
                f"JOIN {settings.CDM_SCHEMA}.concept c ON c.concept_id = cr.concept_id_1 "
                f"WHERE cr.relationship_id = 'Maps to' AND cr.invalid_reason IS NULL "
                f"  AND cr.concept_id_2 = ANY(%s) AND cr.concept_id_1 <> cr.concept_id_2 "
                f"  AND c.vocabulary_id = 'UCUM' AND c.domain_id = 'Unit' "
                f"  AND c.invalid_reason IS NOT NULL",
                (list(_UNIT_CONCEPTS),),
            )
            derived: dict[int, set[tuple[int, str, str]]] = {}
            for standard_id, concept_id, code, name in cur.fetchall():
                derived.setdefault(standard_id, set()).add((concept_id, code, name))
    finally:
        conn.close()

    for standard_id in set(derived) | set(_UNIT_DEPRECATED_FORMS):
        live = derived.get(standard_id, set())
        recorded = set(_UNIT_DEPRECATED_FORMS.get(standard_id, ()))
        for missing in sorted(live - recorded):
            problems.append(
                f"{standard_id}: vocabulary retires {missing!r} onto it and "
                f"_UNIT_DEPRECATED_FORMS does not carry it, so a CDM still writing "
                f"that spelling matches nothing"
            )
        for stale in sorted(recorded - live):
            problems.append(
                f"{standard_id}: _UNIT_DEPRECATED_FORMS carries {stale!r}, which the "
                f"vocabulary no longer maps onto it"
            )

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

    # The real CAROLINA/EMPA-REG group: one absolute bound, three members, two of
    # which mg/dL measures. Run here so the module's own self-check covers the case
    # that motivated the analyte table, not only a synthetic one.
    glucose_label = {"op": "gt", "value": 240.0, "unitText": "mg/dl"}
    split = {
        member: resolve_group_member_constraint(
            glucose_label, None, member_analyte=member
        )
        for member in ("Hemoglobin A1c", "Fasting Plasma Glucose", "Random Plasma Glucose")
    }
    for member, resolution in split.items():
        print(f"{member:32} propagated={resolution.propagated} "
              f"{resolution.refusal_explanation or ''}")
    assert split["Fasting Plasma Glucose"].propagated is True
    assert split["Random Plasma Glucose"].propagated is True
    assert split["Hemoglobin A1c"].propagated is False
    assert split["Hemoglobin A1c"].refusal_reason == STRANDED_GROUP_CONSTRAINT_REASON
    # No analyte named -> the pre-analyte blanket refusal, unchanged.
    assert resolve_group_member_constraint(glucose_label, None).propagated is False

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
