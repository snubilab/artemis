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

import re
import unicodedata
from collections.abc import Mapping
from typing import Any, Literal

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

    bound: ReferenceBound = _field(vc, "reference_bound", "referenceBound") or "absolute"
    unit_text = _field(vc, "unit_text", "unitText")
    if bound == "absolute":
        # Legacy IR predating ADR-031 D1 parked the bound in unit_text.
        bound, unit_text = split_reference_bound(unit_text)

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


def parse_value_constraint(text: str) -> Any:
    """Phase 2 — not implemented. See ADR-031 D2/D6/D7/D8."""
    raise NotImplementedError(
        "ADR-031 phase 2 (D2/D6/D7/D8): the deterministic phrase parser, implicit "
        "multiplier 1, multi-constraint output and negative-case rejection are not "
        "built yet. Phase 1 covers D3/D4/D5 only."
    )


def parse_value_constraints(text: str) -> list[Any]:
    """Phase 2 — not implemented. See ADR-031 D2/D6/D7/D8.

    Plural because one criterion can yield several constraints
    ("TSH >1.2 ULN or <0.8 LLN"), which ADR-031 D7 requires.
    """
    raise NotImplementedError(
        "ADR-031 phase 2 (D2/D6/D7/D8): the deterministic phrase parser, implicit "
        "multiplier 1, multi-constraint output and negative-case rejection are not "
        "built yet. Phase 1 covers D3/D4/D5 only."
    )


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
    print("\nself-check ok")


if __name__ == "__main__":
    import sys

    if "--verify-db" in sys.argv:
        issues = verify_unit_table_against_database()
        print("\n".join(issues) if issues else "unit table matches the vocabulary")
    else:
        demo()
