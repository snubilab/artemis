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

import logging
import unicodedata
from collections.abc import Callable, Mapping
from contextlib import closing
from typing import Any, Literal, NamedTuple

# Pure functions over LOINC properties and UCUM grammar; the module imports its database
# driver lazily, so importing it here keeps this module unit-testable without one.
from src.services.loinc_specimen import verify_members_against_unit

# `criterion_refusal` is a pure constants module with no I/O and no imports of its
# own, so importing it here keeps this module unit-testable without a database. The
# refusal below lives beside the unit resolution it reasons about rather than in
# `circe_lint`, whose stated contract is "pure lint functions over a CIRCE cohort
# expression dict" -- this one is handed a ValueConstraint, not an expression.
from src.utils.criterion_refusal import REFUSAL_UNSTATED_UNIT_BOUND, CriterionRefused

ReferenceBound = Literal["absolute", "uln", "lln"]

#: Expression key: the criteria whose unit was restored from a dropped trailing exponent.
RESTORED_UNIT_CRITERIA_KEY = "_restoredUnitCriteria"

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


_UNIT_PROMPT_SYSTEM = (
    "Return a JSON object with field ucum_code: the UCUM code for the stated unit, "
    "or null if uncertain."
)
_UNIT_PROMPT_VERSION = "unit-resolution-v1"


def _unit_cache_key(unit_text: str, analyte: str) -> str:
    from src.services import criterion_annotation as annotation
    from src.settings import settings

    prompt = f"Unit: {unit_text}\nAnalyte: {analyte}"
    return annotation.cache_key(
        prompt, settings.LLM_MODEL, version=_UNIT_PROMPT_VERSION, system=_UNIT_PROMPT_SYSTEM
    )


def _ask_unit_code(unit_text: str, analyte: str) -> str | None:
    from src.services import criterion_annotation as annotation
    from src.settings import settings

    prompt = f"Unit: {unit_text}\nAnalyte: {analyte}"
    key = _unit_cache_key(unit_text, analyte)
    cached = annotation._cache_get(key)
    if cached is not None:
        return cached.get("payload")
    payload = annotation._complete(
        annotation._build_llm(settings.LLM_MODEL), prompt, _UNIT_PROMPT_SYSTEM
    )
    code = payload.get("ucum_code") if isinstance(payload, dict) else None
    if not isinstance(code, str) or not code.strip():
        return None
    return code.strip()


def _lookup_ucum(code: str) -> tuple[int, str, str] | None:
    import psycopg2

    from src.settings import settings

    with closing(psycopg2.connect(settings.DATABASE_URL)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT concept_id, concept_code, concept_name FROM omop_vocab.concept "
                "WHERE vocabulary_id = 'UCUM' AND standard_concept = 'S' "
                "AND invalid_reason IS NULL AND concept_code = %s",
                (code,),
            )
            rows = cursor.fetchall()
    return rows[0] if len(rows) == 1 else None


def resolve_unit_constraint(vc: Any, analyte: str) -> tuple[Any, str | None]:
    """Resolve a row's unit and return the constraint and its resolution provenance."""
    if vc is None:
        return vc, None
    bound, unit_text = resolve_reference_bound(vc)
    if bound != "absolute" or not unit_text:
        return vc, None
    if absolute_unit_concept_id(vc) is not None:
        return vc, "alias"
    try:
        code = _ask_unit_code(unit_text, analyte)
        concept = _lookup_ucum(code) if code else None
    except Exception as exc:
        logging.getLogger(__name__).warning("Unit resolution failed for %r: %s", unit_text, exc)
        return vc, None
    if concept is None:
        return vc, None
    from src.services import criterion_annotation as annotation
    from src.settings import settings

    annotation._cache_put(
        _unit_cache_key(unit_text, analyte),
        {"payload": code, "model": settings.LLM_MODEL, "promptVersion": _UNIT_PROMPT_VERSION},
    )
    concept_id, concept_code, concept_name = concept
    _UNIT_CONCEPTS[concept_id] = (concept_code, concept_name)
    if isinstance(vc, Mapping):
        resolved = dict(vc)
        resolved["unit_concept_id"] = concept_id
        resolved["unitConceptId"] = concept_id
    else:
        resolved = vc.model_copy(update={"unit_concept_id": concept_id})
    return resolved, "llm+vocab"


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
    """The bound a constraint carries, plus its unit text.

    Reads the ADR-031 D1 field and nothing else. A store row that parked "x ULN" in
    ``unitText`` under ``referenceBound: "absolute"`` is an absolute bound in an
    unresolvable unit here, and is refused as one (:func:`refuse_unstated_unit_bound`):
    whether its number is a multiple of the upper limit of normal is the annotation's
    ``reference_bound`` (RFC-016 step 3), which the build passes in as this field
    (:func:`src.services.criterion_annotation.applied_value_constraint`). Reading the
    bound out of the unit text was a word rule (A21) and is gone.
    """
    bound: ReferenceBound = _field(vc, "reference_bound", "referenceBound") or "absolute"
    return bound, _field(vc, "unit_text", "unitText")


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
    nowhere auditable to live, and the related question already needs no table here
    (:func:`check_analyte_unit` reads a unit's fit off the member concepts' LOINC
    property and converts nothing). And on the motivating criterion it buys nothing:
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


class RestoredUnit(NamedTuple):
    """An absolute bound whose unit was restored, and the record of why."""

    constraint: dict[str, Any]
    record: dict[str, Any]


def restore_dropped_unit_exponent(
    vc: Any, member_properties: MemberProperties | Callable[[], MemberProperties] | None
) -> RestoredUnit | None:
    """Resolve a unit whose trailing exponent the PDF text lost, from the member concepts.

    ``pdftotext`` lifts a superscript off its line, so a protocol's "100,000/mm³",
    "45 kg/m²" and "ml/min/1.73 m²" reach extraction as "/ mm", "kg/m" and
    "ml/min/1.73 m" (ARISTOTLE exclusion 17, CARMELINA inclusion 6 and exclusion 4 in the
    production rendering). Each is then an absolute bound in an unresolvable unit and is
    refused (:func:`refuse_unstated_unit_bound`).

    Machine format only, no words: the candidates are the UCUM spellings in
    :data:`_UNIT_ALIASES` that equal the stated unit (in :func:`_clean` form, case folded)
    with one trailing digit added -- the exponent of the unit's last atom. A candidate is
    accepted only when its LOINC property is verified among the member concepts
    (:func:`check_analyte_unit`, the check a group label's absolute bound already passes),
    and only when exactly one candidate is. Anything else returns None and the refusal
    stands.

    :param vc: the constraint about to be emitted, as a store row's camelCase mapping.
    :param member_properties: the member's concept ids -> LOINC ``Has property``, or a
        zero-argument callable returning them; read only when a candidate exists.
    :returns: the constraint with ``unitConceptId`` set plus the record, or None.
    """
    stated = unstated_absolute_unit(vc)
    if stated is None or not isinstance(vc, Mapping):
        return None
    folded = _clean(stated).lower()
    candidates = sorted(
        {
            concept_id
            for alias, concept_id in _UNIT_ALIASES.items()
            if alias[-1:].isdigit() and alias[:-1].lower() == folded
        }
    )
    if not candidates:
        return None
    properties = member_properties() if callable(member_properties) else member_properties
    verified = [cid for cid in candidates if check_analyte_unit(properties, cid).compatible]
    if len(verified) != 1:
        return None
    concept_id = verified[0]
    code = _UNIT_CONCEPTS[concept_id][0]
    verdict = verify_members_against_unit(list(properties or {}), properties or {}, code)
    return RestoredUnit(
        constraint={**vc, "unitConceptId": concept_id},
        record={
            "statedUnit": stated,
            "unitConceptId": concept_id,
            "unitCode": code,
            "property": verdict.property,
        },
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
# Which unit a member's concepts are measured in
# --------------------------------------------------------------------------

# An absolute bound is analyte-specific, but that does not make it useless to every
# member of a labelled group -- only to the members measured in another unit.
# CAROLINA's exclusion group writes "> 240 mg/dL" once, over Hemoglobin A1c, Fasting
# Plasma Glucose and Random Plasma Glucose. It is a correct threshold for the two
# glucoses and meaningless for HbA1c, which is reported in % (or IFCC mmol/mol).
#
# What a member measures is read off its own concepts (RFC-016 §4, A20): the LOINC
# ``Has property`` of each, against the property family the bound's UCUM unit names
# (``loinc_specimen.verify_members_against_unit``). mg/dL names Mass Concentration; the
# FPG and RPG sets hold Mass Concentration lab tests, the HbA1c set holds Mass fraction
# ones. Until 2026-10-12 this was a table of analyte NAMES matched against the member's
# text; no member text is read now. A member whose concepts carry no LOINC property, or
# whose caller does not know them, refuses -- the safe direction.

MemberProperties = Mapping[int, "str | None"]


class AnalyteUnitCheck(NamedTuple):
    """Whether a bound in one unit may be applied to one member, and why not."""

    compatible: bool
    explanation: str


def check_analyte_unit(
    member_properties: MemberProperties | None, unit_concept_id: int | None
) -> AnalyteUnitCheck:
    """May a bound written in ``unit_concept_id`` be applied to a member measuring these concepts?

    Compatible only when the unit's LOINC property is verified among the member's own
    concepts (``loinc_specimen.verify_members_against_unit``). Every other outcome -- an
    unresolvable unit, no concepts, no LOINC property, a property the unit does not
    name -- is incompatible WITH ITS REASON, never a fall-through to "probably fine". A
    wrong propagation writes a value filter that matches no row at all, and inside an
    ABSENCE exclusion a rule matching no row silently stops excluding anybody.

    :param member_properties: the member's concept ids -> their LOINC ``Has property``
        name (None for a concept without one), or None when the caller does not know them.
    :param unit_concept_id: the bound's unit, from :func:`absolute_unit_concept_id`.
    :returns: the verdict plus a sentence naming what could not be reconciled.
    """
    if unit_concept_id is None:
        return AnalyteUnitCheck(
            False,
            "the group label's bound resolves to no UCUM unit, so there is nothing to "
            "check the member's concepts against",
        )
    if not member_properties:
        return AnalyteUnitCheck(
            False,
            f"the member's concepts are not known here, so whether they are measured in "
            f"{_unit_label(unit_concept_id)} cannot be checked",
        )
    ucum_code = _UNIT_CONCEPTS[unit_concept_id][0]
    verdict = verify_members_against_unit(list(member_properties), member_properties, ucum_code)
    if verdict.property is not None and verdict.kept:
        return AnalyteUnitCheck(True, "")
    held = sorted({prop for prop in member_properties.values() if prop})
    return AnalyteUnitCheck(
        False,
        f"the member's concepts carry LOINC propert{'y' if len(held) == 1 else 'ies'} "
        f"{held or 'none'}, and {_unit_label(unit_concept_id)} is not verified among them "
        f"({verdict.declined or 'no member in its property'})",
    )


def resolve_group_member_constraint(
    parent_vc: Any,
    member_vc: Any,
    *,
    member_properties: MemberProperties | Callable[[], MemberProperties] | None = None,
    member_holds_bound: bool = True,
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
    now can, from the members' own LOINC properties, so the two glucoses are filtered
    and HbA1c alone refuses.

    The blanket refusal remains the fallback for everything the properties cannot settle,
    including a caller that passes no ``member_properties`` at all. This narrows the
    refusal; it never widens what is emitted.

    A label whose number is a group CARDINALITY -- "≥2 of the following:" -- is neither
    of those, and is not decided here: the label's annotation says its quantity is a
    count, and :func:`src.services.criterion_annotation.applied_value_constraint` then
    hands the label's constraint to nobody (``parent_vc`` arrives as None). Without that
    annotation a count left in a stored label reads as an absolute bound in an
    unresolvable unit, and strands every member that could hold a value.

    A member that carries its own constraint always keeps it: SPEC-INFRA-007
    REQ-004/REQ-005 made the decomposer ground each sub-item's threshold in its
    own source text, and this must not overwrite that answer.

    :param parent_vc: the group label's constraint, or None.
    :param member_vc: the member's own constraint, or None.
    :param member_properties: the member's concept ids -> their LOINC ``Has property``,
        or a zero-argument callable returning them, read only when an absolute bound has
        to be checked (so a caller pays for the vocabulary only then). Omitted, every
        absolute bound refuses -- the pre-analyte behaviour.
    :param member_holds_bound: False when the member's CIRCE criteria type reads none of the
        value attributes the label's bound would emit (a ConditionOccurrence reads none).
        The bound is then not about this member: nothing is handed down and nothing is
        stranded, and the member emits as it would under a label with no bound. Measured
        on ARISTOTLE's 'AF/Risk Factor Check' (an age bound over the AF and stroke-risk
        Conditions) and CARMELINA's renal group (an eGFR bound over 'need for maintenance
        dialysis'), whose Condition members were refused as stranded.
    :returns: the member's effective constraint plus why.
    """
    if member_vc is not None:
        return GroupConstraintResolution(member_vc, False, None)
    if parent_vc is None or not member_holds_bound:
        return GroupConstraintResolution(None, False, None)
    if is_reference_relative(parent_vc):
        return GroupConstraintResolution(parent_vc, True, None)
    properties = member_properties() if callable(member_properties) else member_properties
    check = check_analyte_unit(properties, absolute_unit_concept_id(parent_vc))
    if check.compatible:
        return GroupConstraintResolution(parent_vc, True, None)
    return GroupConstraintResolution(
        None, False, STRANDED_GROUP_CONSTRAINT_REASON, check.explanation
    )


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


if __name__ == "__main__":
    import sys

    # The phrase-parser self-check that ran here without a flag went with the parser
    # (RFC-016 step 3); the builder and unit cases live in tests/test_value_constraint.py.
    if "--verify-db" in sys.argv:
        issues = verify_unit_table_against_database()
        print("\n".join(issues) if issues else "unit table matches the vocabulary")
